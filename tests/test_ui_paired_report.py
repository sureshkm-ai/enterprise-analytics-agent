"""Judge exact saved plans/values without dispatching or changing campaign evidence."""

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import boto3
import pytest
from test_ui_release import review

from enterprise_analytics_agent.agent.contracts import AgentResponse
from enterprise_analytics_agent.retail_evaluation.cases import load_goldens, load_suite
from enterprise_analytics_agent.retail_evaluation.models import RetailCase
from enterprise_analytics_agent.ui import paired_report
from enterprise_analytics_agent.ui.models import AskRequest, UiResult
from enterprise_analytics_agent.ui.shared import SharedLedger, SharedReview

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluations/retail-v1"


def response(case: RetailCase, mode: str, reviewed: SharedReview) -> UiResult:
    suite = load_suite(BASE / "questions.json")
    golden = next(
        item
        for item in load_goldens(BASE / "expected-results.json", suite).cases
        if item.case_id == case.id
    )
    queries = case.expected_queries
    diagnostics = {
        "model_id": reviewed.target.model_id,
        "configuration": reviewed.agent_config.model_dump(mode="json"),
        "model_calls": 1,
        "input_tokens": 100,
        "output_tokens": 50,
        "latency_ms": 200,
        "tool_calls": [
            {
                "tool_use_id": f"tool-{index}",
                "name": "query_metric",
                "status": "success",
                "arguments": query.model_dump(mode="json"),
            }
            for index, query in enumerate(queries)
        ],
        "athena": [
            {
                "query_id": f"{case.id}-{mode}-{index}",
                "metric_id": query.metric_id,
                "operation": "query_metric",
                "state": "SUCCEEDED",
                "dataset_version": "retail-v1",
                "scanned_bytes": 64,
            }
            for index, query in enumerate(queries)
        ]
        if mode == "live"
        else [],
    }
    value = AgentResponse.model_validate(
        {
            "status": "answer" if queries else "clarification",
            "answer": "Authored prose may vary; values come from independently frozen literals.",
            "dataset_version": "retail-v1",
            "metric_versions": {item.metric_id: item.definition_version for item in golden.results},
            "results": [item.model_dump(mode="json") for item in golden.results],
            "diagnostics": diagnostics,
        }
    )
    return UiResult.model_validate({"mode": mode, "response": value, "elapsed_ms": 300})


@pytest.fixture
def evidence() -> SimpleNamespace:
    reviewed = review()
    suite = load_suite(BASE / "questions.json")
    golden = load_goldens(BASE / "expected-results.json", suite)
    rows = []
    cases = {case.id: case for case in suite.cases}
    work = [("Q18", "live", "verification")] + [
        (identifier, mode, "question")
        for identifier in paired_report.CASE_IDS
        for mode in paired_report.MODES
    ]
    for number, (identifier, mode, purpose) in enumerate(work, 1):
        case = cases[identifier]
        request_id = str(uuid4())
        result = response(case, mode, reviewed)
        rows.extend(
            [
                {
                    "review_sha256": reviewed.sha256,
                    "event": "reserved",
                    "request_id": request_id,
                    "number": number,
                    "question_sha256": hashlib.sha256(
                        json.dumps([mode, purpose, case.question]).encode()
                    ).hexdigest(),
                    "mode": mode,
                    "purpose": purpose,
                },
                {
                    "review_sha256": reviewed.sha256,
                    "event": "outcome",
                    "request_id": request_id,
                    "status": result.response.status,
                    "result": result.model_dump(mode="json"),
                },
            ]
        )
    return SimpleNamespace(
        review=reviewed,
        suite=suite,
        golden=golden,
        rows=rows,
        campaign={
            "used": 19,
            "maximum": 20,
            "failed": False,
            "incomplete": False,
            "sdk_attempts": {"local_converse_attempts": 9, "agentcore_invocations": 10},
        },
    )


def build(state: SimpleNamespace) -> paired_report.PairedReport:
    return paired_report.build_paired_report(
        state.review, state.rows, state.campaign, state.suite, state.golden
    )


def test_complete_paired_report_judges_all_five_metrics_and_separate_verification(
    evidence: SimpleNamespace,
) -> None:
    report = build(evidence)
    assert report.summary["paired_gates_passed"] is True
    assert report.summary["passed"] == 18 and len(report.cases) == 18
    assert report.verification.case_id == "Q18" and report.verification.status == "passed"
    assert report.summary["deployment_readiness_claimed"] is False
    modes = cast(dict[str, Any], report.summary["by_mode"])
    assert modes["local_agent"]["athena_bytes_scanned"] is None
    assert modes["live"]["athena_bytes_scanned"] == 7 * 64
    assert modes["live"]["input_tokens"]["reported_total"] == 900
    assert report.campaign["sdk_attempts"] == {
        "local_converse_attempts": 9,
        "agentcore_invocations": 10,
    }
    assert not any(item.result.diagnostic_missing for item in report.cases)


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "duplicate",
        "wrong_question",
        "wrong_mode",
        "wrong_value",
        "wrong_plan",
        "verification",
        "diagnostics",
        "athena",
        "clarification",
        "failed",
        "unknown",
    ],
)
def test_incomplete_or_incorrect_evidence_never_passes(
    evidence: SimpleNamespace, corruption: str
) -> None:
    outcome = evidence.rows[3]
    if corruption == "missing":
        del evidence.rows[2:4]
    elif corruption == "duplicate":
        pair = deepcopy(evidence.rows[2:4])
        for row in pair:
            row["request_id"] = "different-attempt"
        evidence.rows.extend(pair)
    elif corruption == "wrong_question":
        evidence.rows[2]["question_sha256"] = "0" * 64
    elif corruption == "wrong_mode":
        outcome["result"]["mode"] = "live"
    elif corruption == "wrong_value":
        outcome["result"]["response"]["results"][0]["rows"][0]["value"] = "0.01"
    elif corruption == "wrong_plan":
        outcome["result"]["response"]["diagnostics"]["tool_calls"][0]["arguments"]["group_by"] = []
    elif corruption == "verification":
        evidence.rows[1]["result"]["response"]["results"][0]["rows"][0]["value"] = "110.26"
    elif corruption == "diagnostics":
        outcome["result"]["unreported_diagnostics"] = ["input_tokens"]
    elif corruption == "athena":
        evidence.rows[5]["result"]["response"]["diagnostics"]["athena"] = []
    elif corruption == "clarification":
        evidence.rows[-7]["status"] = "answer"
        evidence.rows[-7]["result"]["response"]["status"] = "answer"
    elif corruption == "failed":
        outcome.update(status="failed")
        outcome.pop("result")
        evidence.campaign["failed"] = True
    else:
        del evidence.rows[3]
        evidence.campaign["incomplete"] = True
    report = build(evidence)
    assert report.summary["paired_gates_passed"] is False
    assert report.summary["failed"] or not report.summary["verification_passed"]
    if corruption == "diagnostics":
        totals = cast(dict[str, Any], report.summary["by_mode"])["local_agent"]["input_tokens"]
        assert totals == {"reported_total": 800, "reported_samples": 8, "missing_samples": 1}


def test_exact_prose_is_not_the_judging_target(evidence: SimpleNamespace) -> None:
    for outcome in evidence.rows[1::2]:
        outcome["result"]["response"]["answer"] = "Different authored prose."
    assert build(evidence).summary["paired_gates_passed"] is True


def test_cli_reads_integrity_checked_ledger_and_only_creates_report(
    tmp_path: Path,
    evidence: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Report generation must not create an AWS session")

    monkeypatch.setattr(boto3, "Session", forbidden)
    destination = tmp_path / "evaluations/retail-v1"
    destination.mkdir(parents=True)
    for name in (
        "questions.json",
        "expected-results.json",
        "oracle-provenance.json",
        "contributions.csv",
    ):
        shutil.copyfile(BASE / name, destination / name)
    ledger = SharedLedger(tmp_path, evidence.review)
    for reserved, outcome in zip(evidence.rows[::2], evidence.rows[1::2], strict=True):
        case = next(
            case
            for case in evidence.suite.cases
            if paired_report._question_hash(reserved["mode"], reserved["purpose"], case.question)
            == reserved["question_sha256"]
        )
        item = AskRequest(
            mode=reserved["mode"], question=case.question, request_id=reserved["request_id"]
        )

        def dispatch(
            recorder: Any, outcome: dict[str, Any] = outcome, mode: str = item.mode
        ) -> UiResult:
            if mode == "local_agent":
                recorder.converse(SimpleNamespace(converse=lambda **kwargs: {})).converse()
            else:
                recorder.invoke_runtime(lambda: None)
            return UiResult.model_validate(outcome["result"])

        ledger.execute(item, lambda: dispatch, purpose=reserved["purpose"])
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    before_paths = set(tmp_path.rglob("*"))
    read = paired_report.read_report
    monkeypatch.setattr(paired_report, "read_report", lambda root, review: read(tmp_path, review))
    review_path = tmp_path / "review.json"
    review_path.write_text(evidence.review.model_dump_json())
    output = tmp_path / "report.json"
    arguments = ["--review", str(review_path), "--output", str(output)]
    assert paired_report.main(arguments) == 0
    report = paired_report.PairedReport.model_validate_json(output.read_bytes())
    assert report.campaign["used"] == 19
    sdk = cast(dict[str, int], report.campaign["sdk_attempts"])
    assert sdk["local_converse_attempts"] == 9
    assert sdk["agentcore_invocations"] == 10
    assert (
        report.evidence["question_ledger_sha256"]
        == hashlib.sha256(ledger.path.read_bytes()).hexdigest()
    )
    assert (
        report.evidence["sdk_ledger_sha256"]
        == hashlib.sha256(ledger.sdk_path.read_bytes()).hexdigest()
    )
    assert {path: path.read_bytes() for path in before} == before
    assert set(tmp_path.rglob("*")) - before_paths == {review_path, output}
    assert paired_report.main(arguments) == 1
    assert "ui-paired-report" in capsys.readouterr().err
    ledger.sdk_path.write_bytes(b"")
    damaged_output = tmp_path / "damaged-evidence-report.json"
    assert paired_report.main(["--review", str(review_path), "--output", str(damaged_output)]) == 1
    assert not damaged_output.exists()


def test_missing_campaign_is_reported_without_creating_ledger(
    tmp_path: Path, evidence: SimpleNamespace
) -> None:
    directory = tmp_path / "evaluations"
    shutil.copytree(ROOT / "evaluations/retail-v1", directory / "retail-v1")
    report = paired_report.read_report(tmp_path, evidence.review)
    assert report.summary["paired_gates_passed"] is False
    assert report.summary["failed"] == 18
    assert report.campaign["used"] == 0
    assert not (tmp_path / "artifacts").exists()
