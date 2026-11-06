"""Offline audit of acceptance judges and authored case inventories."""

from decimal import Decimal

import pytest

from enterprise_analytics_agent.agent.contracts import (
    AgentDiagnostics,
    AgentResponse,
    ToolCallRecord,
)
from enterprise_analytics_agent.agent.evaluation import (
    LiveAgentConfig,
    assert_evaluation,
    evaluation_cases,
)
from enterprise_analytics_agent.contracts_v2 import (
    MetricRowV2,
    QueryMetricRequestV2,
    QueryMetricResponseV2,
    TimeRangeV2,
)


def config() -> LiveAgentConfig:
    return LiveAgentConfig(
        profile="explicit-development",
        account="111122223333",
        region="us-west-2",
        runtime_arn="arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/analytics_agent-0123456789",
    )


def response() -> AgentResponse:
    period = TimeRangeV2(start="2025-01-01", end="2025-02-01")
    request = QueryMetricRequestV2(metric_id="gross_sales", time_range=period, group_by=("region",))
    result = QueryMetricResponseV2(
        metric_id="gross_sales",
        definition_version="1.0.0",
        time_range=period,
        group_by=("region",),
        unit="currency",
        currency="USD",
        rows=(
            MetricRowV2(dimensions={"region": "North"}, value=Decimal("38.00")),
            MetricRowV2(dimensions={"region": "South"}, value=Decimal("15.00")),
        ),
    )
    return AgentResponse(
        status="answer",
        answer="Exact words are deliberately not an acceptance oracle.",
        results=(result,),
        dataset_version="parity-v1",
        metric_versions={"gross_sales": "1.0.0"},
        diagnostics=AgentDiagnostics(
            model_id=config().model_id,
            configuration={"reference_date": config().reference_date.isoformat()},
            tool_calls=(
                ToolCallRecord(
                    tool_use_id="q1",
                    name="query_metric",
                    arguments=request.model_dump(mode="json"),
                    status="success",
                ),
            ),
        ),
    )


def test_judge_accepts_semantics_without_grading_exact_prose() -> None:
    assert_evaluation(response(), evaluation_cases()[0], config())


@pytest.mark.parametrize(
    "mutation", ["number", "filter", "period", "tool", "dataset", "version", "reference_date"]
)
def test_judge_rejects_numerical_or_tool_plan_regressions(mutation: str) -> None:
    payload = response().model_dump(mode="json")
    if mutation == "number":
        payload["results"][0]["rows"][0]["value"] = "999.00"
    elif mutation == "filter":
        payload["diagnostics"]["tool_calls"][0]["arguments"]["dimension_filters"] = {
            "region": ["East"]
        }
    elif mutation == "period":
        payload["diagnostics"]["tool_calls"][0]["arguments"]["time_range"]["end"] = "2025-01-31"
    elif mutation == "tool":
        payload["diagnostics"]["tool_calls"] = []
    elif mutation == "dataset":
        payload["dataset_version"] = "other-v1"
    elif mutation == "reference_date":
        payload["diagnostics"]["configuration"]["reference_date"] = "2025-02-02"
    else:
        payload["metric_versions"]["gross_sales"] = "changed"
    with pytest.raises(AssertionError):
        assert_evaluation(AgentResponse.model_validate(payload), evaluation_cases()[0], config())


def test_judge_accepts_repaired_tool_arguments_with_successful_evidence() -> None:
    payload = response().model_dump(mode="json")
    failed = {
        "tool_use_id": "bad",
        "name": "query_metric",
        "arguments": {},
        "status": "error",
        "error_code": "invalid_tool_arguments",
    }
    payload["diagnostics"]["tool_calls"].insert(0, failed)
    assert_evaluation(AgentResponse.model_validate(payload), evaluation_cases()[0], config())


def test_judge_requires_successful_metadata_tool_evidence() -> None:
    payload = response().model_dump(mode="json")
    payload.update(results=[], metric_versions={})
    payload["diagnostics"]["tool_calls"][0].update(
        name="discover_metrics", arguments={}, status="error", error_code="tool_error"
    )
    case = next(case for case in evaluation_cases() if case.name == "discover")
    with pytest.raises(AssertionError):
        assert_evaluation(AgentResponse.model_validate(payload), case, config())


def test_missing_source_cannot_pass_as_an_unrelated_runtime_error() -> None:
    case = evaluation_cases("parity-legacy-v1")[1]
    original = response().model_dump(mode="json")
    original.update(
        status="error", error_code="model_error", results=[], dataset_version="parity-legacy-v1"
    )
    original["diagnostics"]["tool_calls"][0]["arguments"].update(
        metric_id="return_rate", group_by=[]
    )
    with pytest.raises(AssertionError):
        assert_evaluation(
            AgentResponse.model_validate(original),
            case,
            config().model_copy(update={"dataset_version": "parity-legacy-v1"}),
        )


def test_live_case_inventory_covers_all_metrics_and_parity_source_variants() -> None:
    cases = evaluation_cases()
    assert len(cases) == 17
    assert {case.metric_id for case in cases[:5]} == {
        "gross_sales",
        "net_revenue",
        "order_count",
        "average_order_value",
        "return_rate",
    }
    assert len(evaluation_cases("parity-legacy-v1")) == 2
    assert len(evaluation_cases("parity-no-returns-v1")) == 2
    with pytest.raises(ValueError):
        evaluation_cases("retail-v1")
