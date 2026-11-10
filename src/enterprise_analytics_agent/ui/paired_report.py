"""Judge saved shared-UI attempts offline; never reserve or dispatch a question."""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field

from enterprise_analytics_agent.retail_evaluation.cases import (
    load_goldens,
    load_suite,
    verify_frozen_inputs,
)
from enterprise_analytics_agent.retail_evaluation.judge import CaseResult, judge_response
from enterprise_analytics_agent.retail_evaluation.models import (
    EvaluationModel,
    GoldenCase,
    RetailCase,
    RetailGolden,
    RetailSuite,
)
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record
from enterprise_analytics_agent.retail_evaluation.reporting import (
    _redact,
    latency_summary,
    unique_athena_queries,
)
from enterprise_analytics_agent.ui.models import UiError, UiResult
from enterprise_analytics_agent.ui.shared import SharedLedger, SharedReview

CASE_IDS = ("Q01", "Q02", "Q03", "Q04", "Q05", "Q13", "Q18", "Q29", "Q30")
type Mode = Literal["local_agent", "live"]
MODES: tuple[Mode, ...] = ("local_agent", "live")


class PairedCase(EvaluationModel):
    mode: Mode
    request_id: str | None = None
    result: CaseResult


class PairedReport(EvaluationModel):
    schema_version: Literal["ui-shared-paired-report-v1"] = "ui-shared-paired-report-v1"
    created_at: datetime
    review_sha256: str
    campaign: dict[str, object]
    evidence: dict[str, object] = Field(default_factory=dict)
    verification: CaseResult
    cases: tuple[PairedCase, ...]
    summary: dict[str, object]
    limitations: tuple[str, ...] = (
        "Judges retained attempts only; no SDK call, reservation or deployment is performed.",
        "This report does not prove current AWS readiness or authorize further calls.",
        "Answers are judged by complete semantic plans/results, not exact prose.",
    )


def _question_hash(mode: str, purpose: str, question: str) -> str:
    return hashlib.sha256(json.dumps([mode, purpose, question]).encode()).hexdigest()


def _missing(case: RetailCase, golden: GoldenCase, reason: str) -> CaseResult:
    return CaseResult(
        case_id=case.id,
        question=case.question,
        kind=case.kind,
        status="failed",
        reasons=(reason,),
        expected_queries=case.expected_queries,
        expected_results=golden.results,
    )


def _judge(
    review: SharedReview,
    case: RetailCase,
    golden: GoldenCase,
    reservation: dict[str, Any],
    outcome: dict[str, Any] | None,
) -> CaseResult:
    if outcome is None or outcome["status"] == "failed":
        return _missing(case, golden, "the reserved attempt failed or has no completed outcome")
    result = UiResult.model_validate(outcome["result"])
    if result.response.status != outcome["status"] or result.mode != reservation["mode"]:
        return _missing(case, golden, "saved outcome status/mode differs from its response")
    raw = result.response.model_dump(mode="json")
    for name in result.unreported_diagnostics:
        raw["diagnostics"].pop(name, None)
    judged = judge_response(
        case,
        golden,
        result.response,
        review.target,
        elapsed_ms=result.elapsed_ms,
        raw_response=raw,
    )
    reasons = list(judged.reasons)
    missing = judged.diagnostic_missing
    if reservation["mode"] == "local_agent":
        missing = tuple(name for name in missing if name != "athena")
    else:
        required = Counter(query.metric_id for query in judged.observed_queries)
        succeeded = Counter(
            str(item.get("metric_id"))
            for item in unique_athena_queries((judged,))
            if item.get("operation") == "query_metric"
            and item.get("state") == "SUCCEEDED"
            and item.get("dataset_version") == review.target.dataset_version
            and type(item.get("scanned_bytes")) is int
            and cast(int, item["scanned_bytes"]) >= 0
        )
        if required - succeeded:
            reasons.append("successful Athena query/scan diagnostics are incomplete")
    if missing:
        reasons.append("required diagnostics were not reported: " + ", ".join(missing))
    if result.elapsed_ms is None or result.elapsed_ms > 90000:
        reasons.append("client latency is missing or exceeds the 90-second acceptance limit")
    if result.response.diagnostics.configuration != review.agent_config.model_dump(mode="json"):
        reasons.append("agent configuration differs from the reviewed shared configuration")
    return judged.model_copy(
        update={
            "status": "failed" if reasons else "passed",
            "reasons": tuple(dict.fromkeys(reasons)),
            "diagnostic_missing": missing,
        }
    )


def _metrics(cases: tuple[CaseResult, ...]) -> dict[str, object]:
    result: dict[str, object] = {
        "passed": sum(case.status == "passed" for case in cases),
        "failed": sum(case.status != "passed" for case in cases),
        "client_latency": latency_summary(
            [case.client_latency_ms for case in cases if case.client_latency_ms is not None]
        ),
        "server_latency": latency_summary(
            [case.server_latency_ms for case in cases if case.server_latency_ms is not None]
        ),
    }
    for name in ("model_calls", "input_tokens", "output_tokens"):
        values = [getattr(case, name) for case in cases]
        known = [value for value in values if value is not None]
        result[name] = {
            "reported_total": sum(known) if known else None,
            "reported_samples": len(known),
            "missing_samples": len(values) - len(known),
        }
    queries = unique_athena_queries(cases)
    scans = [
        cast(int, query["scanned_bytes"])
        for query in queries
        if type(query.get("scanned_bytes")) is int
    ]
    result.update(
        athena_queries=queries,
        athena_bytes_scanned=sum(scans) if scans else None,
        athena_queries_missing_scans=sum(
            type(query.get("scanned_bytes")) is not int for query in queries
        ),
    )
    return result


def build_paired_report(
    review: SharedReview,
    rows: list[dict[str, Any]],
    campaign: dict[str, object],
    suite: RetailSuite,
    goldens: RetailGolden,
    *,
    evidence: dict[str, object] | None = None,
) -> PairedReport:
    """Pure judging of an integrity-validated ledger snapshot against frozen literals."""
    if any(row.get("review_sha256") != review.sha256 for row in rows):
        raise UiError("Report rows belong to another review.")
    selected = {case.id: case for case in suite.cases if case.id in CASE_IDS}
    expected = {case.case_id: case for case in goldens.cases}
    if set(selected) != set(CASE_IDS) or not set(selected) <= expected.keys():
        raise UiError("Frozen questions/expectations do not cover the reviewed paired cases.")
    outcomes = {row["request_id"]: row for row in rows if row["event"] == "outcome"}
    reservations = [row for row in rows if row["event"] == "reserved"]
    consumed: set[str] = set()

    def match(case: RetailCase, mode: Mode, purpose: str) -> tuple[str | None, CaseResult]:
        checksum = _question_hash(mode, purpose, case.question)
        matches = [
            row
            for row in reservations
            if row["mode"] == mode
            and row["purpose"] == purpose
            and row["question_sha256"] == checksum
        ]
        consumed.update(row["request_id"] for row in matches)
        if len(matches) != 1:
            return None, _missing(
                case, expected[case.id], "requires exactly one matching saved attempt"
            )
        item = matches[0]
        return item["request_id"], _judge(
            review, case, expected[case.id], item, outcomes.get(item["request_id"])
        )

    _, verification = match(selected["Q18"], "live", "verification")
    paired = []
    for case_id in CASE_IDS:
        for mode in MODES:
            identifier, result = match(selected[case_id], mode, "question")
            paired.append(PairedCase(mode=mode, request_id=identifier, result=result))
    unexpected = [
        row["request_id"]
        for row in reservations
        if row["purpose"] != "rollback_smoke" and row["request_id"] not in consumed
    ]
    passed = verification.status == "passed" and all(
        item.result.status == "passed" for item in paired
    )
    return PairedReport(
        created_at=datetime.now(UTC),
        review_sha256=review.sha256,
        campaign=campaign,
        evidence=evidence or {},
        verification=verification,
        cases=tuple(paired),
        summary={
            "required_pairs": len(CASE_IDS),
            "required_regular_attempts": 18,
            "passed": sum(item.result.status == "passed" for item in paired),
            "failed": sum(item.result.status != "passed" for item in paired),
            "unexpected_request_ids": unexpected,
            "verification_passed": verification.status == "passed",
            "paired_gates_passed": passed
            and not unexpected
            and not campaign.get("failed")
            and not campaign.get("incomplete"),
            "by_mode": {
                mode: _metrics(tuple(item.result for item in paired if item.mode == mode))
                for mode in MODES
            },
            "deployment_readiness_claimed": False,
        },
    )


def read_report(root: Path, review: SharedReview) -> PairedReport:
    """Read receipts/journals under the existing ledger lock without changing them."""
    ledger = SharedLedger(root, review)
    ledger_sha256: str | None = None
    sdk_sha256: str | None = None
    if ledger.path.exists():
        with ledger._open(create=False) as stream:
            rows = ledger._read(stream)
            campaign = ledger._summary(rows)
            stream.seek(0)
            ledger_sha256 = hashlib.sha256(stream.read().encode()).hexdigest()
            sdk_sha256 = (
                hashlib.sha256(ledger.sdk_path.read_bytes()).hexdigest()
                if ledger.sdk_path.exists()
                else None
            )
    else:
        rows, campaign = [], ledger.summary()
    base = root / "evaluations/retail-v1"
    suite = load_suite(base / "questions.json")
    goldens = load_goldens(base / "expected-results.json", suite)
    frozen = verify_frozen_inputs(
        base / "questions.json",
        base / "expected-results.json",
        base / "oracle-provenance.json",
        goldens,
    )
    return build_paired_report(
        review,
        rows,
        campaign,
        suite,
        goldens,
        evidence={
            **frozen,
            "question_ledger_sha256": ledger_sha256,
            "sdk_ledger_sha256": sdk_sha256,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise UiError("Output already exists; preserve the previous report.")
        review = SharedReview.model_validate_json(args.review.read_bytes())
        root = Path(__file__).resolve().parents[3]
        report = read_report(root, review)
        encoded = json.dumps(_redact(report.model_dump(mode="json")), indent=2) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        print(f"Saved offline paired evaluation: {args.output}")
        return 0 if report.summary["paired_gates_passed"] else 1
    except Exception as exc:
        print(json.dumps(error_record(exc, "ui-paired-report")), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
