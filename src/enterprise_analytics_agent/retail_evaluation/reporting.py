"""Persist auditable reports without treating missing diagnostics as zero work."""

import json
import math
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Literal, cast

from pydantic import Field

from enterprise_analytics_agent.retail_evaluation.judge import CaseResult
from enterprise_analytics_agent.retail_evaluation.models import EvaluationModel, RetailTarget


class EvaluationReport(EvaluationModel):
    schema_version: Literal["retail-report-v1"] = "retail-report-v1"
    run_id: str
    created_at: str
    mode: Literal["replay", "live"]
    target: RetailTarget
    evidence: dict[str, object] = Field(default_factory=dict)
    cases: tuple[CaseResult, ...]
    summary: dict[str, object]
    athena_queries: tuple[dict[str, object], ...]
    campaign: dict[str, object] = Field(default_factory=dict)
    restoration: dict[str, object] = Field(default_factory=dict)


def latency_summary(values: list[int]) -> dict[str, object]:
    ordered = sorted(values)
    return {
        "sample_count": len(ordered),
        "median_ms": median(ordered) if ordered else None,
        "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None,
        "max_ms": max(ordered) if ordered else None,
        "percentile_convention": "nearest rank: sorted[ceil(0.95*n)-1]",
    }


def unique_athena_queries(cases: tuple[CaseResult, ...]) -> tuple[dict[str, object], ...]:
    queries: dict[str, dict[str, object]] = {}
    numeric = {"scanned_bytes", "engine_time_ms", "queue_time_ms", "total_time_ms"}
    for case in cases:
        for diagnostic in case.athena:
            identifier = diagnostic.get("query_id")
            if not isinstance(identifier, str) or not identifier:
                continue
            current = queries.setdefault(identifier, {"query_id": identifier, "case_ids": []})
            identifiers = current["case_ids"]
            assert isinstance(identifiers, list)
            if case.case_id not in identifiers:
                identifiers.append(case.case_id)
            for key, value in diagnostic.items():
                if value is None:
                    continue
                old = current.get(key)
                if key in numeric and type(value) is int and type(old) is int:
                    current[key] = max(old, value)
                elif key != "query_id":
                    current[key] = value
    return tuple(queries[key] for key in sorted(queries))


def _total(cases: tuple[CaseResult, ...], name: str) -> dict[str, object]:
    values = [getattr(case, name) for case in cases if case.status != "unrun"]
    reported = [value for value in values if value is not None]
    return {
        "reported_total": sum(reported) if reported else None,
        "reported_samples": len(reported),
        "missing_samples": len(values) - len(reported),
    }


def build_report(
    cases: tuple[CaseResult, ...],
    target: RetailTarget,
    *,
    run_id: str,
    mode: Literal["replay", "live"] = "replay",
    evidence: dict[str, object] | None = None,
    campaign: dict[str, object] | None = None,
    restoration: dict[str, object] | None = None,
) -> EvaluationReport:
    passing = sum(case.status == "passed" for case in cases)
    expected_clarifications = [case for case in cases if case.kind == "clarification"]
    numeric = [case for case in cases if case.kind == "metric"]
    answered = sum(
        case.response is not None and case.response.status == "answer" for case in numeric
    )
    false_clarifications = sum(
        case.response is not None and case.response.status == "clarification" for case in numeric
    )
    queries = unique_athena_queries(cases)
    scans = [
        cast(int, query["scanned_bytes"])
        for query in queries
        if type(query.get("scanned_bytes")) is int and cast(int, query["scanned_bytes"]) >= 0
    ]
    summary: dict[str, object] = {
        "required_cases": len(cases),
        "passed": passing,
        "failed": sum(case.status == "failed" for case in cases),
        "unrun": sum(case.status == "unrun" for case in cases),
        "correctness_fraction": passing / len(cases) if cases else None,
        "numeric_required": len(numeric),
        "numeric_correct": sum(case.status == "passed" for case in numeric),
        "successful_answer_coverage": answered / len(numeric) if numeric else None,
        "clarification_required": len(expected_clarifications),
        "clarification_correct": sum(case.status == "passed" for case in expected_clarifications),
        "correct_clarification_rate": (
            sum(case.status == "passed" for case in expected_clarifications)
            / len(expected_clarifications)
            if expected_clarifications
            else None
        ),
        "false_clarification_rate": false_clarifications / len(numeric) if numeric else None,
        "client_latency": latency_summary(
            [
                case.client_latency_ms
                for case in cases
                if case.client_latency_ms is not None and case.attempt_category != "warmup"
            ]
        ),
        "server_latency": latency_summary(
            [
                case.server_latency_ms
                for case in cases
                if case.server_latency_ms is not None and case.attempt_category != "warmup"
            ]
        ),
        "model_calls": _total(cases, "model_calls"),
        "input_tokens": _total(cases, "input_tokens"),
        "output_tokens": _total(cases, "output_tokens"),
        "athena_unique_queries": len(queries),
        "athena_scanned_bytes_reported": sum(scans) if scans else None,
        "athena_scan_missing_queries": sum(
            type(query.get("scanned_bytes")) is not int or cast(int, query["scanned_bytes"]) < 0
            for query in queries
        ),
        "diagnostic_missing_cases": [case.case_id for case in cases if case.diagnostic_missing],
        "live_acceptance_claimed": False,
    }
    complete = bool(cases) and passing == len(cases)
    timing = summary["client_latency"]
    assert isinstance(timing, dict)
    p95 = timing["p95_ms"]
    diagnostics_complete = not any(case.diagnostic_missing for case in cases)
    for case in cases:
        required = Counter(request.metric_id for request in case.observed_queries)
        succeeded = Counter(
            str(item.get("metric_id"))
            for item in unique_athena_queries((case,))
            if item.get("operation") == "query_metric"
            and item.get("state") == "SUCCEEDED"
            and item.get("dataset_version") == target.dataset_version
            and type(item.get("scanned_bytes")) is int
            and cast(int, item["scanned_bytes"]) >= 0
        )
        if required - succeeded:
            diagnostics_complete = False
    # Failed query attempts remain visible without disqualifying a legitimate successful retry.
    summary["athena_failed_queries"] = sum(query.get("state") == "FAILED" for query in queries)
    summary["authorization_required"] = sum(case.kind == "authorization" for case in cases)
    summary["authorization_correct"] = sum(
        case.kind == "authorization" and case.status == "passed" for case in cases
    )
    summary["metadata_required"] = sum(case.kind == "metadata" for case in cases)
    summary["metadata_correct"] = sum(
        case.kind == "metadata" and case.status == "passed" for case in cases
    )
    summary["failed_tool_repairs"] = sum(
        call.status == "error"
        for case in cases
        if case.response is not None
        for call in case.response.diagnostics.tool_calls
    )
    summary["diagnostics_complete"] = diagnostics_complete
    summary["latency_gate_passed"] = isinstance(p95, (int, float)) and p95 <= 90000
    summary["live_gates_passed"] = (
        mode == "live"
        and complete
        and diagnostics_complete
        and timing["sample_count"] == len(cases)
        and summary["latency_gate_passed"]
    )
    return EvaluationReport(
        run_id=run_id,
        created_at=datetime.now(UTC).isoformat(),
        mode=mode,
        target=target,
        evidence=evidence or {},
        cases=cases,
        summary=summary,
        athena_queries=queries,
        campaign=campaign or {},
        restoration=restoration or {},
    )


def _redact(value: object) -> object:
    """Redact sensitive evidence and encode timestamps without discarding their timezone."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        sensitive = {
            "sql",
            "query_string",
            "querystring",
            "credentials",
            "authorization",
            "accesskeyid",
            "secretaccesskey",
            "sessiontoken",
            "headers",
            "httpheaders",
            "responsemetadata",
        }
        return {
            key: "[redacted]" if str(key).casefold() in sensitive else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_redact(item) for item in value]
    if isinstance(value, str) and re.match(
        r"(?is)^\s*(?:select|with|insert|update|delete|drop|create|alter|grant|revoke)\b", value
    ):
        return "[redacted SQL-like text]"
    return value


def prepare_run_directory(directory: Path) -> None:
    """Reserve a unique output destination before any invocation can consume budget."""
    directory.mkdir(parents=True, exist_ok=False)
    (directory / ".retail-run").write_text("retail-report-v1\n")


def write_run_context(
    directory: Path,
    target: RetailTarget,
    evidence: dict[str, object],
    *,
    run_id: str,
    mode: Literal["replay", "live"],
) -> None:
    """Persist target/checkpoint provenance before spending a single invocation."""
    if not (directory / ".retail-run").is_file():
        raise ValueError("report directory was not prepared before dispatch")
    value = {
        "schema_version": "retail-run-context-v1",
        "run_id": run_id,
        "mode": mode,
        "target": target.model_dump(mode="json"),
        "evidence": evidence,
    }
    serialized = json.dumps(_redact(value), indent=2) + "\n"
    with (directory / "run-context.json").open("x") as stream:
        stream.write(serialized)
        stream.flush()
        os.fsync(stream.fileno())


def append_attempt(directory: Path, case: CaseResult) -> None:
    """Persist each completed case immediately, including before a later interruption."""
    if not (directory / ".retail-run").is_file():
        raise ValueError("report directory was not prepared before dispatch")
    with (directory / "attempts.jsonl").open("a") as stream:
        stream.write(json.dumps(_redact(case.model_dump(mode="json")), sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_report(report: EvaluationReport, directory: Path, *, prepared: bool = False) -> None:
    """Finalize a unique run; prepared runs already have durable per-attempt evidence."""
    if not prepared:
        prepare_run_directory(directory)
        for case in report.cases:
            append_attempt(directory, case)
    elif not (directory / ".retail-run").is_file():
        raise ValueError("report directory was not prepared before dispatch")
    body = _redact(report.model_dump(mode="json"))
    with (directory / "report.json").open("x") as stream:
        stream.write(json.dumps(body, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    lines = [
        f"# Retail evaluation {report.run_id}",
        "",
        f"Mode: {report.mode}; dataset: {report.target.dataset_version}; "
        f"model: {report.target.model_id}.",
        "",
        f"Required: {report.summary['required_cases']}; passed: {report.summary['passed']}; "
        f"failed: {report.summary['failed']}; unrun: {report.summary['unrun']}.",
        "",
        f"Correct clarification rate: {report.summary['correct_clarification_rate']}; "
        f"false clarification rate: {report.summary['false_clarification_rate']}.",
        "",
        f"Client timing: {json.dumps(report.summary['client_latency'], sort_keys=True)}.",
        f"Server timing: {json.dumps(report.summary['server_latency'], sort_keys=True)}.",
        "",
        f"Input tokens: {json.dumps(report.summary['input_tokens'], sort_keys=True)}; "
        f"output tokens: {json.dumps(report.summary['output_tokens'], sort_keys=True)}; "
        f"model calls: {json.dumps(report.summary['model_calls'], sort_keys=True)}.",
        "",
        f"Unique Athena queries: {report.summary['athena_unique_queries']}; "
        f"reported scanned bytes: {report.summary['athena_scanned_bytes_reported']}; "
        f"queries missing scans: {report.summary['athena_scan_missing_queries']}.",
        "",
        "Client latency includes dispatch/body read; server latency is reported separately. "
        "Warm-up samples are excluded. A warm-up does not prove subsequent sessions are warm.",
        "",
        "| Case | Outcome | Reason |",
        "| --- | --- | --- |",
    ]
    for case in report.cases:
        lines.append(f"| {case.case_id} | {case.status} | {'; '.join(case.reasons)} |")
    lines += [
        "",
        "Live acceptance and restoration require separate operator review; "
        "this report alone makes no milestone-completion claim.",
        "",
    ]
    with (directory / "summary.md").open("x") as stream:
        stream.write("\n".join(lines))
