"""Authored semantic plans and literal responses exercise the independent retail judge offline."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.agent.contracts import AgentResponse
from enterprise_analytics_agent.agent.questions import question_scope
from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2, QueryMetricResponseV2
from enterprise_analytics_agent.retail_evaluation.cases import load_goldens, load_suite
from enterprise_analytics_agent.retail_evaluation.judge import CaseResult, judge_response
from enterprise_analytics_agent.retail_evaluation.models import (
    GoldenCase,
    RetailCase,
    RetailGolden,
    RetailSuite,
    RetailTarget,
)
from enterprise_analytics_agent.retail_evaluation.reporting import build_report, write_report
from enterprise_analytics_agent.retail_evaluation.runner import run_suite

QUESTIONS = Path("evaluations/retail-v1/questions.json")


def target(**changes: object) -> RetailTarget:
    return RetailTarget.model_validate(
        {
            "runtime_arn": "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
            "enterprise_analytics_dev_agent-HlWywlG60h",
            "dataset_version": "retail-v1",
            "reference_date": "2025-04-01",
            **changes,
        }
    )


def request(**changes: object) -> QueryMetricRequestV2:
    return QueryMetricRequestV2.model_validate(
        {
            "metric_id": "net_revenue",
            "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
            **changes,
        }
    )


def result(query: QueryMetricRequestV2, value: str = "12.50") -> QueryMetricResponseV2:
    return QueryMetricResponseV2(
        metric_id=query.metric_id,
        definition_version="1.0.0",
        time_range=query.time_range,
        group_by=query.group_by,
        unit="currency",
        currency="USD",
        rows=({"dimensions": {}, "value": value},),
    )


def case_and_golden() -> tuple[RetailCase, GoldenCase]:
    query = request()
    return (
        RetailCase(
            id="Q01",
            question="Show net_revenue for January 2025.",
            kind="metric",
            expected_queries=(query,),
        ),
        GoldenCase(case_id="Q01", results=(result(query),)),
    )


def response(case: RetailCase, golden: GoldenCase, **changes: Any) -> AgentResponse:
    arguments = [query.model_dump(mode="json") for query in case.expected_queries]
    return AgentResponse.model_validate(
        {
            "status": "answer",
            "answer": "Validated answer",
            "dataset_version": "retail-v1",
            "results": [item.model_dump(mode="json") for item in golden.results],
            "metric_versions": {item.metric_id: "1.0.0" for item in golden.results},
            "diagnostics": {
                "model_id": "us.amazon.nova-lite-v1:0",
                "configuration": {"reference_date": "2025-04-01"},
                "model_calls": 2,
                "input_tokens": 10,
                "output_tokens": 5,
                "latency_ms": 80,
                "tool_calls": [
                    {
                        "tool_use_id": str(index),
                        "name": "query_metric",
                        "arguments": value,
                        "status": "success",
                    }
                    for index, value in enumerate(arguments)
                ],
                "athena": [],
            },
            **changes,
        }
    )


def test_versioned_inventory_and_supported_vocabulary() -> None:
    suite = load_suite(QUESTIONS)
    assert len(suite.cases) == 36
    assert [case.id for case in suite.cases[:34]] == [f"Q{i:02d}" for i in range(1, 35)]
    for case in suite.cases:
        scope = question_scope(case.question, suite.reference_date)
        if case.kind == "clarification" or case.id == "Q30":
            assert scope.clarification, case.id
        else:
            assert scope.clarification is None, (case.id, scope.clarification)
            for query in case.expected_queries:
                scope.validate_query(query)
    assert {case.session_group for case in suite.cases if case.id.startswith("S01")} == {"S01"}
    assert all(case.session_group is None for case in suite.cases[:34])


@pytest.mark.parametrize(
    "changes",
    [
        {"profile": "default"},
        {"account": "000000000000"},
        {"region": "us-east-1"},
        {"qualifier": "other"},
        {"model_id": "other"},
        {"tenant_id": "other_retail"},
        {"reference_date": "2025-02-01"},
        {"dataset_version": "parity-v1"},
    ],
)
def test_target_cannot_widen_approved_operator_configuration(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        target(**changes)


def test_no_goldens_can_be_silently_substituted(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unfrozen"):
        load_goldens(tmp_path / "missing.json", load_suite(QUESTIONS))


def test_exact_handwritten_answer_passes_and_failed_repair_is_retained() -> None:
    case, golden = case_and_golden()
    raw = response(case, golden).model_dump(mode="json")
    raw["diagnostics"]["tool_calls"].insert(
        0,
        {
            "tool_use_id": "failed",
            "name": "unknown",
            "arguments": {"bad": "repair"},
            "status": "error",
            "error_code": "unknown_tool",
        },
    )
    observed = AgentResponse.model_validate(raw)
    judged = judge_response(case, golden, observed, target(), elapsed_ms=100, raw_response=raw)
    assert judged.status == "passed" and judged.client_latency_ms == 100
    assert judged.server_latency_ms == 80 and judged.input_tokens == 10
    assert judged.response is not None and len(judged.response.diagnostics.tool_calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        "value",
        "dates",
        "filters",
        "extra-query",
        "missing-result",
        "extra-result",
        "dataset",
        "model",
        "metric-version",
    ],
)
def test_judge_rejects_incorrect_complete_requests_and_results(change: str) -> None:
    case, golden = case_and_golden()
    raw = response(case, golden).model_dump(mode="json")
    if change == "value":
        raw["results"][0]["rows"][0]["value"] = "12.51"
    elif change == "dates":
        raw["diagnostics"]["tool_calls"][0]["arguments"]["time_range"]["end"] = "2025-02-02"
    elif change == "filters":
        raw["diagnostics"]["tool_calls"][0]["arguments"]["dimension_filters"] = {
            "region": ["North"]
        }
    elif change == "extra-query":
        call = deepcopy(raw["diagnostics"]["tool_calls"][0])
        call["tool_use_id"] = "extra"
        raw["diagnostics"]["tool_calls"].append(call)
    elif change == "missing-result":
        raw["results"] = []
    elif change == "extra-result":
        raw["results"].append(deepcopy(raw["results"][0]))
    elif change == "dataset":
        raw["dataset_version"] = "parity-v1"
    elif change == "model":
        raw["diagnostics"]["model_id"] = "other"
    else:
        raw["metric_versions"]["net_revenue"] = "2.0.0"
    assert (
        judge_response(case, golden, AgentResponse.model_validate(raw), target()).status == "failed"
    )


@pytest.mark.parametrize("value", ["12.5", "12.500", 12.5])
def test_noncanonical_monetary_precision_is_rejected_before_judging(value: object) -> None:
    case, golden = case_and_golden()
    raw = response(case, golden).model_dump(mode="json")
    raw["results"][0]["rows"][0]["value"] = value
    with pytest.raises(ValidationError):
        AgentResponse.model_validate(raw)


def test_complete_multi_metric_and_multi_period_plans_are_required() -> None:
    query = request()
    gross = request(metric_id="gross_sales")
    march = request(time_range={"start": "2025-03-01", "end": "2025-04-01"})
    case = RetailCase(
        id="Q24",
        question="Authored complete plan",
        kind="metric",
        expected_queries=(query, gross, march),
    )
    golden = GoldenCase(
        case_id=case.id, results=(result(query), result(gross, "15.00"), result(march))
    )
    complete = response(case, golden)
    assert judge_response(case, golden, complete, target()).status == "passed"
    raw = complete.model_dump(mode="json")
    raw["diagnostics"]["tool_calls"].pop()
    raw["results"].pop()
    assert (
        judge_response(case, golden, AgentResponse.model_validate(raw), target()).status == "failed"
    )


def test_ordering_does_not_change_semantic_plan_or_rows() -> None:
    query = request(
        group_by=["region", "channel"], dimension_filters={"region": ["North", "South"]}
    )
    case = RetailCase(
        id="Q12", question="Authored grouping", kind="metric", expected_queries=(query,)
    )
    expected = result(query).model_copy(
        update={
            "rows": (
                result(query)
                .rows[0]
                .model_copy(update={"dimensions": {"region": "North", "channel": "online"}}),
                result(query)
                .rows[0]
                .model_copy(update={"dimensions": {"region": "South", "channel": "store"}}),
            )
        }
    )
    golden = GoldenCase(case_id=case.id, results=(expected,))
    raw = response(case, golden).model_dump(mode="json")
    raw["results"][0]["rows"].reverse()
    raw["results"][0]["group_by"].reverse()
    raw["diagnostics"]["tool_calls"][0]["arguments"]["group_by"].reverse()
    raw["diagnostics"]["tool_calls"][0]["arguments"]["dimension_filters"]["region"].reverse()
    assert (
        judge_response(case, golden, AgentResponse.model_validate(raw), target()).status == "passed"
    )


@pytest.mark.parametrize(
    "error_code",
    [
        None,
        "AuthorizationError",
        "invalid_tool_arguments",
        "runtime_unavailable",
        "unexpected_failure",
    ],
)
def test_authorization_rejection_does_not_grade_infrastructure_errors_as_safe(
    error_code: str | None,
) -> None:
    case = next(case for case in load_suite(QUESTIONS).cases if case.id == "Q30")
    golden = GoldenCase(case_id=case.id)
    observed = response(
        case,
        golden,
        status="clarification" if error_code is None else "error",
        error_code=error_code,
    )
    expected = "failed" if error_code in {"runtime_unavailable", "unexpected_failure"} else "passed"
    assert judge_response(case, golden, observed, target()).status == expected


def test_clarification_cannot_hide_successful_query_or_identity_leak() -> None:
    case = RetailCase(id="Q26", question="Show sales for January 2025.", kind="clarification")
    golden = GoldenCase(case_id=case.id)
    raw = response(case, golden, status="clarification").model_dump(mode="json")
    raw["diagnostics"]["tool_calls"] = [
        {
            "tool_use_id": "leak",
            "name": "query_metric",
            "status": "error",
            "arguments": {"tenant_id": "other_retail"},
            "error_code": "invalid_tool_arguments",
        }
    ]
    assert (
        judge_response(case, golden, AgentResponse.model_validate(raw), target()).status == "failed"
    )
    raw["diagnostics"]["tool_calls"][0].update(
        status="success", arguments=request().model_dump(mode="json")
    )
    assert (
        judge_response(case, golden, AgentResponse.model_validate(raw), target()).status == "failed"
    )


def test_metadata_grades_operation_and_metric_without_parsing_prose() -> None:
    case = next(case for case in load_suite(QUESTIONS).cases if case.id == "Q33")
    golden = GoldenCase(case_id=case.id)
    raw = response(case, golden).model_dump(mode="json")
    raw["diagnostics"]["tool_calls"] = [
        {
            "tool_use_id": "metadata",
            "name": "describe_metric",
            "status": "success",
            "arguments": {"api_version": "v2", "metric_id": "average_order_value"},
        }
    ]
    assert (
        judge_response(case, golden, AgentResponse.model_validate(raw), target()).status == "passed"
    )
    raw["diagnostics"]["tool_calls"][0]["arguments"]["metric_id"] = "net_revenue"
    assert (
        judge_response(case, golden, AgentResponse.model_validate(raw), target()).status == "failed"
    )


def test_missing_diagnostics_remain_missing_and_athena_scans_deduplicate(tmp_path: Path) -> None:
    case, golden = case_and_golden()
    raw = response(case, golden).model_dump(mode="json")
    for key in ["input_tokens", "output_tokens", "model_calls", "latency_ms"]:
        raw["diagnostics"].pop(key)
    raw["diagnostics"]["athena"] = [
        {"query_id": "same", "state": "RUNNING", "scanned_bytes": None},
        {"query_id": "same", "state": "SUCCEEDED", "scanned_bytes": 1024},
        {"query_id": "missing", "state": "FAILED"},
    ]
    judged = judge_response(
        case, golden, AgentResponse.model_validate(raw), target(), raw_response=raw
    )
    assert judged.model_calls is judged.input_tokens is judged.server_latency_ms is None
    report = build_report(
        (judged, judged.model_copy(update={"case_id": "Q02"})), target(), run_id="offline"
    )
    assert report.summary["athena_unique_queries"] == 2
    assert report.summary["athena_scanned_bytes_reported"] == 1024
    assert report.summary["input_tokens"] == {
        "reported_total": None,
        "reported_samples": 0,
        "missing_samples": 2,
    }
    write_report(report, tmp_path / "run")
    assert len((tmp_path / "run" / "attempts.jsonl").read_text().splitlines()) == 2
    assert (
        json.loads((tmp_path / "run" / "report.json").read_text())["schema_version"]
        == "retail-report-v1"
    )
    with pytest.raises(FileExistsError):
        write_report(report, tmp_path / "run")


def test_failure_unrun_and_clarification_denominators_are_complete() -> None:
    rows = tuple(
        CaseResult(case_id=f"Q{i:02d}", question="authored", kind=kind, status=status)
        for i, (kind, status) in enumerate(
            [
                ("metric", "passed"),
                ("metric", "failed"),
                ("metric", "unrun"),
                ("clarification", "passed"),
                ("clarification", "failed"),
            ],
            start=1,
        )
    )
    summary = build_report(rows, target(), run_id="all").summary
    assert summary["required_cases"] == 5 and summary["correctness_fraction"] == 2 / 5
    assert summary["numeric_required"] == 3 and summary["correct_clarification_rate"] == 0.5


def test_runner_shares_only_the_authored_session_pair_and_rejects_carried_filter() -> None:
    from enterprise_analytics_agent.retail_evaluation.client import InvocationResult

    suite = load_suite(QUESTIONS)
    selected = (suite.cases[0], suite.cases[-2], suite.cases[-1])
    mini = RetailSuite(cases=selected)
    goldens = RetailGolden(
        manifest_sha256="a" * 64,
        cases=tuple(
            GoldenCase(
                case_id=case.id, results=tuple(result(query) for query in case.expected_queries)
            )
            for case in selected
        ),
    )
    sessions: list[str | None] = []
    calls = iter(zip(selected, goldens.cases, strict=True))

    def invoke(question: str, *, session_id: str | None = None) -> InvocationResult:
        case, golden = next(calls)
        sessions.append(session_id)
        raw = response(case, golden).model_dump(mode="json")
        if case.id == "S01B":
            raw["diagnostics"]["tool_calls"][0]["arguments"]["dimension_filters"] = {
                "region": ["North"]
            }
        return InvocationResult(
            response=AgentResponse.model_validate(raw),
            elapsed_ms=100,
            invocation_id=None,
            raw_response=raw,
        )

    report = run_suite(mini, goldens, target(), invoke)
    assert report.cases[-1].status == "failed"
    assert sessions[0] != sessions[1] and sessions[1] == sessions[2]


def test_runner_stops_after_transport_failure_and_keeps_unrun_cases() -> None:
    case, golden = case_and_golden()
    other = case.model_copy(update={"id": "Q02"})
    suite = RetailSuite(cases=(case, other))
    goldens = RetailGolden(
        manifest_sha256="a" * 64, cases=(golden, golden.model_copy(update={"case_id": "Q02"}))
    )
    calls = []

    def invoke(question: str, *, session_id: str | None = None) -> Any:
        calls.append(question)
        raise TimeoutError("private transport details")

    report = run_suite(suite, goldens, target(), invoke)
    assert [case.status for case in report.cases] == ["failed", "unrun"]
    assert len(calls) == 1 and report.cases[0].error_type == "TimeoutError"


def test_null_ratio_is_distinct_from_zero_and_money_from_count() -> None:
    query = request(metric_id="return_rate")
    case = RetailCase(
        id="Q20", question="Authored zero denominator", kind="metric", expected_queries=(query,)
    )
    expected = QueryMetricResponseV2(
        metric_id="return_rate",
        definition_version="1.0.0",
        time_range=query.time_range,
        group_by=(),
        unit="ratio",
        currency=None,
        rows=({"dimensions": {}, "value": None},),
    )
    golden = GoldenCase(case_id=case.id, results=(expected,))
    raw = response(case, golden).model_dump(mode="json")
    assert (
        judge_response(case, golden, AgentResponse.model_validate(raw), target()).status == "passed"
    )
    raw["results"][0]["rows"][0]["value"] = "0.000000"
    assert (
        judge_response(case, golden, AgentResponse.model_validate(raw), target()).status == "failed"
    )
    money_case, money_golden = case_and_golden()
    raw = response(money_case, money_golden).model_dump(mode="json")
    raw["results"][0].update(unit="count", currency=None)
    raw["results"][0]["rows"][0]["value"] = 12
    assert (
        judge_response(money_case, money_golden, AgentResponse.model_validate(raw), target()).status
        == "failed"
    )


def test_frozen_evidence_binds_questions_goldens_and_canonical_manifest(tmp_path: Path) -> None:
    from enterprise_analytics_agent.retail_evaluation.cases import verify_frozen_inputs

    expected = QUESTIONS.with_name("expected-results.json")
    provenance = QUESTIONS.with_name("oracle-provenance.json")
    suite = load_suite(QUESTIONS)
    golden = load_goldens(expected, suite)
    assert verify_frozen_inputs(QUESTIONS, expected, provenance, golden)["questions_sha256"]
    changed = tmp_path / "questions.json"
    changed.write_bytes(QUESTIONS.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="questions_sha256"):
        verify_frozen_inputs(changed, expected, provenance, golden)
    with pytest.raises(ValueError, match="another canonical manifest"):
        verify_frozen_inputs(
            QUESTIONS, expected, provenance, golden.model_copy(update={"manifest_sha256": "0" * 64})
        )


def test_cli_replay_and_help_never_construct_aws_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from enterprise_analytics_agent.retail_evaluation.runner import main

    # Empty replay evidence fails honestly; help needs no target/client/credentials.
    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    config = tmp_path / "target.json"
    config.write_text(target().model_dump_json())
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    assert (
        main(
            [
                "--target-config",
                str(config),
                "--response-dir",
                str(tmp_path),
                "--report-dir",
                str(tmp_path / "report"),
            ]
        )
        == 1
    )
    report = json.loads((tmp_path / "report" / "report.json").read_text())
    assert report["mode"] == "replay"
    assert report["summary"]["failed"] == 1 and report["summary"]["unrun"] == 35
    assert report["summary"]["live_gates_passed"] is False


def test_reports_remove_executable_sql_from_failed_tool_arguments(tmp_path: Path) -> None:
    case, golden = case_and_golden()
    raw = response(case, golden).model_dump(mode="json")
    raw["diagnostics"]["tool_calls"].insert(
        0,
        {
            "tool_use_id": "bad",
            "name": "unknown",
            "status": "error",
            "error_code": "unknown_tool",
            "arguments": {
                "sql": "SELECT * FROM secret",
                "other": "SELECT 1",
                "headers": {"Authorization": "secret"},
            },
        },
    )
    judged = judge_response(case, golden, AgentResponse.model_validate(raw), target())
    write_report(build_report((judged,), target(), run_id="redacted"), tmp_path / "redacted")
    text = (tmp_path / "redacted" / "report.json").read_text()
    assert "SELECT" not in text and "secret" not in text


def test_preexisting_output_directory_dispatches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from enterprise_analytics_agent.retail_evaluation.runner import main

    config = tmp_path / "target.json"
    config.write_text(target().model_dump_json())
    existing = tmp_path / "existing"
    existing.mkdir()
    calls: list[object] = []
    monkeypatch.setattr(
        "enterprise_analytics_agent.retail_evaluation.runner.ReplayInvoker",
        lambda *args: calls.append(args),
    )
    assert (
        main(
            [
                "--target-config",
                str(config),
                "--response-dir",
                str(tmp_path),
                "--report-dir",
                str(existing),
            ]
        )
        == 1
    )
    assert calls == []


def test_completed_attempt_is_durable_before_a_later_keyboard_interrupt(tmp_path: Path) -> None:
    from enterprise_analytics_agent.retail_evaluation.client import InvocationResult
    from enterprise_analytics_agent.retail_evaluation.reporting import (
        append_attempt,
        prepare_run_directory,
    )

    case, golden = case_and_golden()
    other = case.model_copy(update={"id": "Q02"})
    suite = RetailSuite(cases=(case, other))
    goldens = RetailGolden(
        manifest_sha256="a" * 64, cases=(golden, golden.model_copy(update={"case_id": "Q02"}))
    )
    directory = tmp_path / "interrupted"
    prepare_run_directory(directory)
    calls = 0

    def invoke(question: str, *, session_id: str | None = None) -> InvocationResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt()
        observed = response(case, golden)
        return InvocationResult(observed, 10, "first", observed.model_dump(mode="json"))

    with pytest.raises(KeyboardInterrupt):
        run_suite(
            suite, goldens, target(), invoke, on_case=lambda row: append_attempt(directory, row)
        )
    lines = (directory / "attempts.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["case_id"] == "Q01"
    assert not (directory / "report.json").exists()


def test_all_frozen_cases_can_be_replayed_with_complete_structured_evidence() -> None:
    from enterprise_analytics_agent.retail_evaluation.client import InvocationResult

    suite = load_suite(QUESTIONS)
    goldens = load_goldens(QUESTIONS.with_name("expected-results.json"), suite)
    rows = iter(zip(suite.cases, goldens.cases, strict=True))

    def invoke(question: str, *, session_id: str | None = None) -> InvocationResult:
        case, golden = next(rows)
        raw = response(
            case,
            golden,
            status="clarification"
            if case.kind == "clarification" or case.id == "Q30"
            else "answer",
        ).model_dump(mode="json")
        if case.kind == "metadata":
            raw["diagnostics"]["tool_calls"] = [
                {
                    "tool_use_id": "metadata",
                    "name": case.operation,
                    "status": "success",
                    "arguments": {
                        "api_version": "v2",
                        **({"metric_id": case.metric_id} if case.metric_id else {}),
                    },
                }
            ]
        return InvocationResult(AgentResponse.model_validate(raw), 25, None, raw)

    report = run_suite(suite, goldens, target(), invoke)
    assert (
        report.summary["passed"] == 36 and report.summary["failed"] == report.summary["unrun"] == 0
    )
    assert report.summary["live_gates_passed"] is False


@pytest.mark.parametrize("scans", ["unknown", True, -1, None])
def test_live_report_cannot_pass_with_invalid_scan_counters(scans: object) -> None:
    case, golden = case_and_golden()
    raw = response(case, golden).model_dump(mode="json")
    raw["diagnostics"]["athena"] = [
        {
            "query_id": "q1",
            "operation": "query_metric",
            "metric_id": "net_revenue",
            "dataset_version": "retail-v1",
            "state": "SUCCEEDED",
            "scanned_bytes": scans,
        }
    ]
    judged = judge_response(
        case, golden, AgentResponse.model_validate(raw), target(), elapsed_ms=10
    )
    summary = build_report((judged,), target(), run_id="bad-diagnostics", mode="live").summary
    assert summary["diagnostics_complete"] is False and summary["live_gates_passed"] is False
    assert summary["athena_scan_missing_queries"] == 1
    assert summary["athena_scanned_bytes_reported"] is None


def test_legitimate_query_retry_preserves_failed_evidence_without_failing_quality_gate() -> None:
    case, golden = case_and_golden()
    raw = response(case, golden).model_dump(mode="json")
    raw["diagnostics"]["athena"] = [
        {
            "query_id": "failed",
            "operation": "query_metric",
            "metric_id": "net_revenue",
            "dataset_version": "retail-v1",
            "state": "FAILED",
            "scanned_bytes": None,
        },
        {
            "query_id": "success",
            "operation": "query_metric",
            "metric_id": "net_revenue",
            "dataset_version": "retail-v1",
            "state": "SUCCEEDED",
            "scanned_bytes": 0,
        },
    ]
    judged = judge_response(
        case, golden, AgentResponse.model_validate(raw), target(), elapsed_ms=10
    )
    summary = build_report((judged,), target(), run_id="retry", mode="live").summary
    assert summary["diagnostics_complete"] is True and summary["live_gates_passed"] is True
    assert summary["athena_failed_queries"] == 1
    assert summary["athena_scanned_bytes_reported"] == 0


@pytest.mark.parametrize(
    "error_code", ["AthenaExecutionError", "AthenaTimeoutError", "tool_error", "unclassified"]
)
def test_backend_errors_stop_dispatch_instead_of_burning_the_remaining_budget(
    error_code: str,
) -> None:
    from enterprise_analytics_agent.retail_evaluation.client import InvocationResult

    case, golden = case_and_golden()
    other = case.model_copy(update={"id": "Q02"})
    suite = RetailSuite(cases=(case, other))
    goldens = RetailGolden(
        manifest_sha256="a" * 64, cases=(golden, golden.model_copy(update={"case_id": "Q02"}))
    )
    calls: list[str] = []

    def invoke(question: str, *, session_id: str | None = None) -> InvocationResult:
        calls.append(question)
        observed = response(case, golden, status="error", error_code=error_code, results=[])
        return InvocationResult(observed, 10, None, observed.model_dump(mode="json"))

    report = run_suite(suite, goldens, target(), invoke)
    assert len(calls) == 1 and [row.status for row in report.cases] == ["failed", "unrun"]


def test_live_preflight_failure_is_sanitized_and_never_constructs_invocation_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from enterprise_analytics_agent.retail_evaluation.runner import main

    config = tmp_path / "target.json"
    config.write_text(target().model_dump_json())
    constructed: list[object] = []

    def fail_verification(**kwargs: object) -> Any:
        raise RuntimeError("sensitive AWS SDK failure details")

    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.retail_checkpoint.verify_checkpoint",
        fail_verification,
    )
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.agentcore_invocation.create_runtime_invoker",
        lambda selected: constructed.append(selected),
    )
    assert (
        main(
            [
                "--target-config",
                str(config),
                "--invoke-live",
                "--report-dir",
                str(tmp_path / "failed-preflight"),
            ]
        )
        == 1
    )
    assert constructed == []
    output = capsys.readouterr()
    assert "RuntimeError" in output.err and "sensitive" not in output.err
    assert not (tmp_path / "failed-preflight" / "attempts.jsonl").exists()
