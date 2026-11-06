"""Offline authored-model conversations and independent retail expected values."""

from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from aws_fixture_data import write_parity_snapshot
from pydantic import ValidationError

from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
)
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.agent.contracts import AgentRequest
from enterprise_analytics_agent.agent.tools import REQUEST_MODELS, input_schema
from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.errors import AuthorizationError


class Model:
    def __init__(self, *responses: dict[str, object] | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(deepcopy(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def turn(*calls: dict[str, object], text: str = "Invented answer 9999.99") -> dict[str, object]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": call} for call in calls] if calls else [{"text": text}],
            }
        },
        "stopReason": "tool_use" if calls else "end_turn",
        "usage": {"inputTokens": 20, "outputTokens": 10, "totalTokens": 30},
        "metrics": {"latencyMs": 3},
    }


def query(metric: str = "net_revenue", **changes: object) -> dict[str, object]:
    return {
        "metric_id": metric,
        "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
        **changes,
    }


def tool(
    name: str = "query_metric", arguments: object = None, identifier: str = "call-1"
) -> dict[str, object]:
    return {
        "toolUseId": identifier,
        "name": name,
        "input": query() if arguments is None else arguments,
    }


def messages(client: Model, index: int) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], client.calls[index]["messages"])


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_parity_snapshot(tmp_path_factory.mktemp("agent-fixture"))


@pytest.fixture
def context() -> AuthorizationContext:
    return AuthorizationContext(
        principal_id="trusted-app", tenant_id="t1", allowed_regions=("North", "South")
    )


def config(**changes: object) -> BedrockAgentConfig:
    return BedrockAgentConfig.model_validate(
        {"model_id": "configured-model", "reference_date": "2025-02-15", **changes}
    )


def execute(
    source: Path, context: AuthorizationContext, client: Model, question: str, **settings: object
) -> Any:
    with DuckDBSemanticAdapter(source) as adapter:
        return BedrockAnalyticsAgent(
            config(**settings), client=client, adapter=adapter, dataset_version="parity-v1"
        ).run(AgentRequest(question=question), context=context)


@pytest.mark.parametrize(
    ("metric", "expected", "unit"),
    [
        ("gross_sales", "53.00", "USD"),
        ("net_revenue", "41.50", "USD"),
        ("order_count", 3, "count"),
        ("average_order_value", "13.83", "USD"),
        ("return_rate", "0.666667", "ratio"),
    ],
)
def test_each_metric_uses_only_validated_tool_numbers(
    source: Path, context: AuthorizationContext, metric: str, expected: str | int, unit: str
) -> None:
    client = Model(turn(tool(arguments=query(metric))), turn())
    response = execute(source, context, client, f"Show {metric} for January 2025")
    assert response.status == "answer"
    assert response.model_dump(mode="json")["results"][0]["rows"][0]["value"] == expected
    assert f"{expected} {unit}" in response.answer
    assert "9999.99" not in response.answer
    assert "[2025-01-01, 2025-02-01)" in response.answer
    assert response.dataset_version == "parity-v1" and response.metric_versions[metric]
    assert (
        response.diagnostics.model_calls,
        response.diagnostics.input_tokens,
        response.diagnostics.output_tokens,
    ) == (2, 40, 20)
    assert client.calls[0]["modelId"] == "configured-model"


def test_multiple_tools_have_matching_ids_and_independent_values(
    source: Path, context: AuthorizationContext
) -> None:
    metrics = ("gross_sales", "net_revenue", "order_count", "average_order_value", "return_rate")
    client = Model(
        turn(
            *(
                tool(arguments=query(metric), identifier=f"call-{index}")
                for index, metric in enumerate(metrics)
            )
        ),
        turn(),
    )
    response = execute(source, context, client, "Show " + ", ".join(metrics) + " January 2025")
    assert response.status == "answer"
    assert [row.model_dump(mode="json")["rows"][0]["value"] for row in response.results] == [
        "53.00",
        "41.50",
        3,
        "13.83",
        "0.666667",
    ]
    returned = messages(client, 1)[-1]["content"]
    assert [block["toolResult"]["toolUseId"] for block in returned] == [
        f"call-{i}" for i in range(5)
    ]
    assert all(block["toolResult"]["status"] == "success" for block in returned)


@pytest.mark.parametrize(
    "question",
    [
        "sales January 2025",
        "net revenue",
        "profit January 2025",
        "Compare net revenue January 2025",
        "net revenue between 2025-01-01 and 2025-02-01",
        "net revenue percentage growth January 2025",
        "net_revenue January 2025 by product",
        "net_revenue January 2025 by customer",
        "net_revenue January 2025 channel=wholesale",
        "net_revenue January 2025 region=Northeast",
        "net_revenue January 2025 for Northeast",
        "Compare gross_sales January 2025 versus net_revenue February 2025",
        "net_revenue from January 2025 to March 2025",
        "net_revenue January 2025 excluding North",
        "net_revenue January 2025 without South",
        "net_revenue January 2025 not in North",
        "net_revenue January 2025 in regions other than North",
        "net_revenue January 2025 outside North",
        "net_revenue January 2025 by region except South",
        "net_revenue January 2025 don't include North",
        "Show net revenue and profit for January 2025",
        "Show net revenue for January 2025 broken down daily",
    ],
)
def test_ambiguous_or_unsupported_question_clarifies_without_model(
    source: Path, context: AuthorizationContext, question: str
) -> None:
    client = Model()
    response = execute(source, context, client, question)
    assert response.status == "clarification" and not response.results and not client.calls


@pytest.mark.parametrize(
    "field",
    ["tenant_id", "principal_id", "allowed_regions", "session_id", "history", "reference_date"],
)
def test_payload_cannot_supply_identity_history_or_calendar(field: str) -> None:
    with pytest.raises(ValidationError):
        AgentRequest.model_validate({"question": "net revenue January 2025", field: "override"})


@pytest.mark.parametrize(
    "arguments",
    [
        {**query(), "tenant_id": "t2"},
        {**query(), "allowed_regions": ["East"]},
        {**query(), "api_version": "v1"},
        {**query(), "sql": "SELECT * FROM orders"},
        query("gross_sales"),
        query(time_range={"start": "2025-02-01", "end": "2025-03-01"}),
        query(group_by=["region"]),
        query(dimension_filters={"region": ["North"]}),
        [],
        "not an object",
    ],
)
def test_tool_arguments_cannot_override_question_or_contract(
    source: Path, context: AuthorizationContext, arguments: object
) -> None:
    client = Model(turn(tool(arguments=arguments)), turn())
    response = execute(source, context, client, "net revenue January 2025")
    assert response.status == "error" and response.error_code == "invalid_tool_arguments"
    assert not response.results
    assert response.diagnostics.tool_calls[0].status == "error"


def test_bad_tool_can_be_repaired_using_a_new_id(
    source: Path, context: AuthorizationContext
) -> None:
    client = Model(turn(tool("unknown_tool")), turn(tool(identifier="fixed")), turn())
    response = execute(source, context, client, "net revenue January 2025")
    assert response.status == "answer"
    assert [item.status for item in response.diagnostics.tool_calls] == ["error", "success"]
    assert response.diagnostics.tool_calls[0].error_code == "unknown_tool"


def test_exactly_four_v2_tool_schemas_never_expose_identity() -> None:
    assert set(REQUEST_MODELS) == {
        "discover_metrics",
        "describe_metric",
        "query_metric",
        "discover_dimensions",
    }
    for name in REQUEST_MODELS:
        schema = input_schema(name)
        assert schema["additionalProperties"] is False
        properties = cast(dict[str, object], schema["properties"])
        assert not {"tenant_id", "principal_id", "allowed_regions", "sql"} & properties.keys()
        assert "$ref" not in repr(schema)


def test_unrequested_catalog_search_cannot_silently_hide_metrics(
    source: Path, context: AuthorizationContext
) -> None:
    client = Model(
        turn(tool("discover_metrics", {"search": "net_revenue"})),
        turn(tool("discover_metrics", {}, identifier="all-metrics")),
        turn(),
    )
    response = execute(source, context, client, "List all available metrics")
    assert response.status == "answer"
    assert [record.status for record in response.diagnostics.tool_calls] == ["error", "success"]
    assert response.diagnostics.tool_calls[0].error_code == "invalid_tool_arguments"
    assert set(response.metric_versions) == {
        "gross_sales",
        "net_revenue",
        "order_count",
        "average_order_value",
        "return_rate",
    }
    returned = messages(client, 1)[-1]["content"][0]["toolResult"]
    assert returned["status"] == "error"
    assert "metrics" not in returned["content"][0]["json"]


@pytest.mark.parametrize(
    ("question", "name", "arguments", "expected"),
    [
        ("List available metrics", "discover_metrics", {}, "net_revenue"),
        ("Describe net revenue", "describe_metric", {"metric_id": "net_revenue"}, "net_revenue"),
        (
            "Discover regions for net revenue",
            "discover_dimensions",
            {"metric_id": "net_revenue"},
            "North",
        ),
    ],
)
def test_metadata_tools_do_not_need_an_invented_period(
    source: Path,
    context: AuthorizationContext,
    question: str,
    name: str,
    arguments: dict[str, object],
    expected: str,
) -> None:
    response = execute(source, context, Model(turn(tool(name, arguments)), turn()), question)
    assert response.status == "answer" and expected in response.answer and not response.results


@pytest.mark.parametrize("grouped", [True, False])
def test_empty_groups_and_zero_denominator_null_preserved(
    source: Path, context: AuthorizationContext, grouped: bool
) -> None:
    arguments = query("return_rate", time_range={"start": "2030-01-01", "end": "2030-02-01"})
    if grouped:
        arguments["group_by"] = ["region"]
    response = execute(
        source,
        context,
        Model(turn(tool(arguments=arguments)), turn()),
        "return_rate " + ("by region " if grouped else "") + "January 2030",
    )
    assert response.status == "answer"
    if grouped:
        assert response.results[0].rows == () and "No eligible results" in response.answer
    else:
        assert response.results[0].rows[0].value is None
        assert "null (zero denominator)" in response.answer


def test_missing_source_is_explicit(tmp_path: Path, context: AuthorizationContext) -> None:
    source = write_parity_snapshot(tmp_path, returns="absent")
    response = execute(
        source,
        context,
        Model(turn(tool(arguments=query("return_rate"))), turn()),
        "return_rate January 2025",
    )
    assert response.status == "error" and response.error_code == "MissingMetricDataError"
    assert not response.results


def test_grouped_north_filter_preserves_exact_value(
    source: Path, context: AuthorizationContext
) -> None:
    response = execute(
        source,
        context,
        Model(
            turn(
                tool(arguments=query(group_by=["region"], dimension_filters={"region": ["North"]}))
            ),
            turn(),
        ),
        "net_revenue by region for North January 2025",
    )
    assert response.model_dump(mode="json")["results"][0]["rows"] == [
        {"api_version": "v2", "dimensions": {"region": "North"}, "value": "28.50"}
    ]


def test_unapproved_region_cannot_expand_scope(source: Path, context: AuthorizationContext) -> None:
    response = execute(
        source,
        context,
        Model(
            turn(
                tool(arguments=query(group_by=["region"], dimension_filters={"region": ["East"]}))
            ),
            turn(),
        ),
        "net_revenue by region for East January 2025",
    )
    assert response.status == "answer" and response.results[0].rows == ()


def test_requests_share_neither_history_nor_results_nor_trusted_identity(
    source: Path, context: AuthorizationContext
) -> None:
    client = Model(turn(tool()), turn(), turn(tool()), turn())
    with DuckDBSemanticAdapter(source) as adapter:
        agent = BedrockAnalyticsAgent(
            config(), client=client, adapter=adapter, dataset_version="parity-v1"
        )
        first = agent.run(AgentRequest(question="net_revenue January 2025"), context=context)
        second = agent.run(
            AgentRequest(question="net_revenue January 2025"),
            context=context.model_copy(update={"tenant_id": "t2"}),
        )
    assert first.model_dump(mode="json")["results"][0]["rows"][0]["value"] == "41.50"
    assert second.model_dump(mode="json")["results"][0]["rows"][0]["value"] == "950.00"
    assert len(messages(client, 0)) == len(messages(client, 2)) == 1
    assert len(first.diagnostics.tool_calls) == len(second.diagnostics.tool_calls) == 1


def test_relative_month_uses_configured_calendar(
    source: Path, context: AuthorizationContext
) -> None:
    response = execute(source, context, Model(turn(tool()), turn()), "net_revenue last month")
    assert response.status == "answer"
    assert response.results[0].time_range.start == date(2025, 1, 1)


def test_invalid_trusted_scope_fails_before_model(
    source: Path, context: AuthorizationContext
) -> None:
    client = Model()
    with pytest.raises(AuthorizationError):
        execute(
            source,
            context.model_copy(update={"allowed_regions": ()}),
            client,
            "net_revenue January 2025",
        )
    assert not client.calls


@pytest.mark.parametrize("grouped", [True, False])
def test_compared_regions_cannot_be_replaced_with_a_combined_total(
    source: Path, context: AuthorizationContext, grouped: bool
) -> None:
    request = query(dimension_filters={"region": ["North", "South"]})
    if grouped:
        request["group_by"] = ["region"]
    response = execute(
        source,
        context,
        Model(turn(tool(arguments=request)), turn()),
        "How much net revenue did North make in January 2025 compared with South?",
    )
    if grouped:
        assert response.status == "answer"
        assert [row.model_dump(mode="json")["value"] for row in response.results[0].rows] == [
            "28.50",
            "13.00",
        ]
    else:
        assert response.status == "error" and not response.results
