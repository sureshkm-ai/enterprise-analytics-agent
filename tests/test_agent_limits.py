"""Fault and budget tests for the offline Bedrock lifecycle."""

from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from test_agent import Model, config, execute, query, tool, turn

from enterprise_analytics_agent.adapter import SemanticAdapter
from enterprise_analytics_agent.adapters.bedrock_agent import BedrockAnalyticsAgent, ConverseClient
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.agent.contracts import AgentRequest
from enterprise_analytics_agent.contracts import AuthorizationContext


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from aws_fixture_data import write_parity_snapshot

    return write_parity_snapshot(tmp_path_factory.mktemp("agent-errors"))


@pytest.fixture
def context() -> AuthorizationContext:
    return AuthorizationContext(
        principal_id="app", tenant_id="t1", allowed_regions=("North", "South")
    )


@pytest.mark.parametrize(
    "broken",
    [
        {},
        {"usage": {}},
        {**turn(), "usage": {"inputTokens": True, "outputTokens": 10, "totalTokens": 11}},
        {**turn(), "usage": {"inputTokens": -1, "outputTokens": 10, "totalTokens": 9}},
        {**turn(), "usage": {"inputTokens": 20, "outputTokens": 10, "totalTokens": 31}},
        {**turn(), "output": {}},
        {**turn(), "output": {"message": {"role": "user", "content": [{"text": "wrong"}]}}},
        {**turn(), "output": {"message": {"role": "assistant", "content": []}}},
        {**turn(), "output": {"message": {"role": "assistant", "content": [{"text": 1}]}}},
    ],
)
def test_malformed_model_response_returns_typed_error_without_tool(
    source: Path, context: AuthorizationContext, broken: dict[str, object]
) -> None:
    response = execute(source, context, Model(broken), "net_revenue January 2025")
    assert response.status == "error" and response.error_code == "malformed_model_response"
    assert not response.diagnostics.tool_calls and not response.results


def test_nonobject_sdk_response_is_rejected(source: Path, context: AuthorizationContext) -> None:
    client = Mock()
    client.converse.return_value = None
    response = execute(source, context, cast(Model, client), "net_revenue January 2025")
    assert response.status == "error" and response.error_code == "malformed_model_response"


@pytest.mark.parametrize(
    "calls",
    [
        [tool(identifier="duplicate"), tool(identifier="duplicate")],
        [tool(identifier="")],
        [tool(identifier="not valid")],
        [{"toolUseId": "one", "name": "query_metric"}],
        [{"toolUseId": "one", "name": "", "input": query()}],
    ],
)
def test_malformed_or_duplicate_tool_ids_fail_before_dispatch(
    source: Path, context: AuthorizationContext, calls: list[dict[str, object]]
) -> None:
    response = execute(source, context, Model(turn(*calls)), "net_revenue January 2025")
    assert response.status == "error" and response.error_code == "malformed_tool_use"
    assert not response.results and not response.diagnostics.tool_calls


def test_reused_id_across_turns_is_rejected(source: Path, context: AuthorizationContext) -> None:
    response = execute(
        source, context, Model(turn(tool()), turn(tool())), "net_revenue January 2025"
    )
    assert response.status == "error" and response.error_code == "malformed_tool_use"
    assert len(response.diagnostics.tool_calls) == 1


def test_model_error_is_not_retried_or_exposed(source: Path, context: AuthorizationContext) -> None:
    client = Model(RuntimeError("provider credentials or secret error"), turn(tool()))
    response = execute(source, context, client, "net_revenue January 2025")
    assert response.status == "error" and response.error_code == "model_error"
    assert "secret" not in response.answer and len(client.calls) == 1


@pytest.mark.parametrize(
    ("settings", "model", "expected", "calls"),
    [
        ({"max_iterations": 1}, Model(turn(tool())), "iteration_limit", 1),
        (
            {"max_tool_calls": 1},
            Model(turn(tool(identifier="a"), tool(identifier="b"))),
            "tool_limit",
            1,
        ),
        ({"max_total_tokens": 1}, Model(turn()), "token_limit", 0),
        ({}, Model({**turn(), "stopReason": "max_tokens"}), "token_limit", 1),
        ({}, Model({**turn(), "stopReason": "content_filtered"}), "model_stopped", 1),
    ],
)
def test_execution_limits_stop_without_additional_model_or_tool_work(
    source: Path,
    context: AuthorizationContext,
    settings: dict[str, object],
    model: Model,
    expected: str,
    calls: int,
) -> None:
    response = execute(source, context, model, "net_revenue January 2025", **settings)
    assert response.status == "error" and response.error_code == expected
    assert len(model.calls) == calls
    if expected == "tool_limit":
        assert not response.diagnostics.tool_calls


def test_provider_usage_over_total_budget_stops_before_dispatch(
    source: Path, context: AuthorizationContext
) -> None:
    response = turn(tool())
    response["usage"] = {"inputTokens": 11999, "outputTokens": 2, "totalTokens": 12001}
    result = execute(source, context, Model(response), "net_revenue January 2025")
    assert result.error_code == "token_limit" and not result.diagnostics.tool_calls
    assert result.diagnostics.input_tokens == 11999 and result.diagnostics.output_tokens == 2


def test_timeout_after_response_records_tokens_without_dispatch(
    source: Path, context: AuthorizationContext
) -> None:
    timer = [0.0]

    class SlowModel:
        def converse(self, **kwargs: object) -> dict[str, object]:
            timer[0] = 1.0
            return turn(tool())

    with DuckDBSemanticAdapter(source) as adapter:
        response = BedrockAnalyticsAgent(
            config(timeout_seconds=0.5),
            client=SlowModel(),
            adapter=adapter,
            dataset_version="parity-v1",
            clock=lambda: timer[0],
        ).run(AgentRequest(question="net_revenue January 2025"), context=context)
    assert response.error_code == "time_limit"
    assert not response.diagnostics.tool_calls and response.diagnostics.input_tokens == 20


def test_timeout_after_tool_preserves_the_executed_trace(
    source: Path, context: AuthorizationContext
) -> None:
    timer = [0.0]
    with DuckDBSemanticAdapter(source) as underlying:
        adapter = Mock(wraps=underlying)
        adapter.diagnostics = ()

        def query_slow(*args: Any, **kwargs: Any) -> Any:
            timer[0] = 1.0
            return underlying.query_metric(*args, **kwargs)

        adapter.query_metric.side_effect = query_slow
        result = BedrockAnalyticsAgent(
            config(timeout_seconds=0.5),
            client=Model(turn(tool())),
            adapter=cast(SemanticAdapter, adapter),
            dataset_version="parity-v1",
            clock=lambda: timer[0],
        ).run(AgentRequest(question="net_revenue January 2025"), context=context)
    assert result.error_code == "time_limit"
    assert len(result.diagnostics.tool_calls) == 1
    assert result.diagnostics.tool_calls[0].status == "success"


def test_partial_comparison_does_not_masquerade_as_complete_answer(
    source: Path, context: AuthorizationContext
) -> None:
    result = execute(
        source, context, Model(turn(tool()), turn()), "net_revenue and gross_sales January 2025"
    )
    assert result.error_code == "incomplete_tool_results"
    assert len(result.results) == 1


def test_wrong_metric_result_is_not_accepted_as_evidence(
    source: Path, context: AuthorizationContext
) -> None:
    from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2, TimeRangeV2

    with DuckDBSemanticAdapter(source) as underlying:
        wrong = underlying.query_metric(
            QueryMetricRequestV2(
                metric_id="gross_sales",
                time_range=TimeRangeV2(start="2025-01-01", end="2025-02-01"),
            ),
            context=context,
        )
        adapter = Mock()
        adapter.diagnostics = ()
        adapter.query_metric.return_value = wrong
        result = BedrockAnalyticsAgent(
            config(),
            client=Model(turn(tool())),
            adapter=cast(SemanticAdapter, adapter),
            dataset_version="parity-v1",
        ).run(AgentRequest(question="net_revenue January 2025"), context=context)
    assert result.error_code == "invalid_tool_response"
    assert not result.results


def test_model_cannot_query_while_answering_a_metadata_question(
    source: Path, context: AuthorizationContext
) -> None:
    result = execute(source, context, Model(turn(tool()), turn()), "Describe net_revenue")
    assert result.status == "error" and result.error_code == "invalid_tool_arguments"


def test_comparison_retains_each_original_period_without_calculating_new_metric(
    source: Path, context: AuthorizationContext
) -> None:
    february = query(time_range={"start": "2025-02-01", "end": "2025-03-01"})
    result = execute(
        source,
        context,
        Model(turn(tool(), tool(arguments=february, identifier="feb")), turn()),
        "Compare net_revenue January 2025 versus February 2025",
    )
    assert result.status == "answer"
    assert [item.model_dump(mode="json")["rows"][0]["value"] for item in result.results] == [
        "41.50",
        "7.00",
    ]
    assert "[2025-02-01, 2025-03-01)" in result.answer


def test_exact_iso_range_boundaries_supported(source: Path, context: AuthorizationContext) -> None:
    result = execute(
        source, context, Model(turn(tool()), turn()), "net_revenue [2025-01-01, 2025-02-01)"
    )
    assert result.status == "answer"


def test_complete_converse_request_uses_official_sdk_shape_offline(
    source: Path, context: AuthorizationContext
) -> None:
    import boto3
    from botocore.stub import Stubber

    captured = Model(turn(tool()), turn())
    execute(source, context, captured, "net_revenue January 2025")
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-west-2",
        aws_access_key_id="offline",
        aws_secret_access_key="offline",
    )
    with Stubber(client) as stubber, DuckDBSemanticAdapter(source) as adapter:
        stubber.add_response(
            "converse", cast(Any, turn(tool())), cast(Any, deepcopy(captured.calls[0]))
        )
        stubber.add_response("converse", cast(Any, turn()), cast(Any, deepcopy(captured.calls[1])))
        response = BedrockAnalyticsAgent(
            config(),
            client=cast(ConverseClient, client),
            adapter=adapter,
            dataset_version="parity-v1",
        ).run(AgentRequest(question="net_revenue January 2025"), context=context)
        assert response.status == "answer"
