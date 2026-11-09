"""Exercise real agent orchestration when a model ends without selecting a tool.

Authored Converse turns reproduce the recorded Q18 response shape, not its unavailable
raw model transcript. Frozen responses below test routing, not live answer quality.
"""

from datetime import date
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import duckdb
import pytest
from aws_fixture_data import write_parity_snapshot
from test_agent import Model, config, execute, query, tool, turn

from enterprise_analytics_agent.adapter import SemanticAdapter
from enterprise_analytics_agent.adapters.bedrock_agent import BedrockAnalyticsAgent
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.agent.contracts import AgentRequest
from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2, QueryMetricResponseV2
from enterprise_analytics_agent.data import OPTIONAL_TABLE_SCHEMAS, TABLE_SCHEMAS
from enterprise_analytics_agent.errors import AuthorizationError
from enterprise_analytics_agent.retail_evaluation.cases import load_goldens, load_suite
from enterprise_analytics_agent.retail_evaluation.judge import judge_response
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget

EVIDENCE = Path(__file__).resolve().parents[1] / "evaluations/retail-v1"
SUITE = load_suite(EVIDENCE / "questions.json")
GOLDENS = load_goldens(EVIDENCE / "expected-results.json", SUITE)


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_parity_snapshot(tmp_path_factory.mktemp("resolved-plan"))


@pytest.fixture
def context() -> AuthorizationContext:
    return AuthorizationContext(
        principal_id="trusted-app", tenant_id="t1", allowed_regions=("North", "South")
    )


def test_yesterday_no_tool_turn_executes_exact_resolved_dates_and_real_arithmetic(
    tmp_path: Path, context: AuthorizationContext
) -> None:
    # Independently authored: $120.25 - $10.00 = $110.25. April 1, March 30,
    # another tenant and an unauthorized region must not enter the March 31 answer.
    rows: dict[str, list[tuple[object, ...]]] = {
        "customers": [
            ("t1", "c1", "North customer", "North"),
            ("t1", "c2", "East customer", "East"),
            ("t2", "c1", "Other tenant", "North"),
        ],
        "products": [("t1", "p1", "Item", "home", 12025), ("t2", "p1", "Item", "home", 99999)],
        "orders": [
            (
                "t1",
                "selected",
                "c1",
                date(2025, 3, 31),
                "completed",
                "USD",
                "North",
                "online",
                0,
                0,
            ),
            ("t1", "end", "c1", date(2025, 4, 1), "completed", "USD", "North", "online", 0, 0),
            ("t1", "before", "c1", date(2025, 3, 30), "completed", "USD", "North", "online", 0, 0),
            ("t1", "hidden", "c2", date(2025, 3, 31), "completed", "USD", "East", "online", 0, 0),
            (
                "t2",
                "selected",
                "c1",
                date(2025, 3, 31),
                "completed",
                "USD",
                "North",
                "online",
                0,
                0,
            ),
        ],
        "order_items": [
            ("t1", "selected", "selected", "p1", 1, 12025, 1000),
            *[("t1", name, name, "p1", 1, 99999, 0) for name in ("end", "before", "hidden")],
            ("t2", "selected", "selected", "p1", 1, 99999, 0),
        ],
        "payments": [],
        "refunds": [],
        "returns": [],
    }
    with duckdb.connect(":memory:") as connection:
        for table, schema in (TABLE_SCHEMAS | OPTIONAL_TABLE_SCHEMAS).items():
            columns = ", ".join(f'"{name}" {kind}' for name, kind in schema)
            connection.execute(f'CREATE TABLE "{table}" ({columns})')
            if rows[table]:
                placeholders = ", ".join("?" for _ in schema)
                connection.executemany(
                    f'INSERT INTO "{table}" VALUES ({placeholders})', rows[table]
                )
            connection.table(table).write_parquet(str(tmp_path / f"{table}.parquet"))
    model = Model(turn(text="Please provide a calendar date. Invented revenue is 9999.99."))
    response = execute(
        tmp_path, context, model, "Show net_revenue for yesterday.", reference_date="2025-04-01"
    )
    assert response.status == "answer"
    assert response.model_dump(mode="json")["results"][0]["rows"][0]["value"] == "110.25"
    assert response.results[0].time_range.start == date(2025, 3, 31)
    assert response.results[0].time_range.end == date(2025, 4, 1)
    assert "110.25 USD" in response.answer and "9999.99" not in response.answer
    assert len(model.calls) == response.diagnostics.model_calls == 1
    assert len(response.diagnostics.tool_calls) == 1
    assert response.diagnostics.tool_calls[0].tool_use_id.startswith("resolved-plan-")
    assert response.diagnostics.tool_calls[0].status == "success"


@pytest.mark.parametrize("case_id", [case.id for case in SUITE.cases])
def test_every_frozen_case_through_agent_with_no_tool_numeric_turn(
    source: Path, case_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Put the stub at the model/adapter boundaries, not at AgentResponse: the real
    # question guard, agent loop, typed tool validation and result renderer all run.
    def forbid_aws(*args: object, **kwargs: object) -> Any:
        raise AssertionError("Offline agent regression must not construct AWS clients")

    monkeypatch.setattr("boto3.Session", forbid_aws)
    case = next(case for case in SUITE.cases if case.id == case_id)
    golden = next(item for item in GOLDENS.cases if item.case_id == case_id)
    target = RetailTarget.model_validate_json((EVIDENCE / "target.json").read_text())
    trusted = AuthorizationContext(
        principal_id="trusted-app", tenant_id="retail_demo", allowed_regions=("North", "South")
    )
    requested: list[QueryMetricRequestV2] = []

    def query_metric(
        request: QueryMetricRequestV2, *, context: AuthorizationContext
    ) -> QueryMetricResponseV2:
        assert context == trusted
        assert request in case.expected_queries
        requested.append(request)
        return golden.results[case.expected_queries.index(request)]

    model = Model(turn(text="Please clarify the requested metric or period."))
    if case.kind == "metadata":
        assert case.operation is not None
        model = Model(
            turn(
                tool(
                    case.operation,
                    {
                        "api_version": "v2",
                        **({"metric_id": case.metric_id} if case.metric_id else {}),
                    },
                )
            ),
            turn(),
        )
    with DuckDBSemanticAdapter(source) as underlying:
        adapter = Mock(spec=SemanticAdapter, wraps=underlying)
        adapter.diagnostics = ()
        adapter.query_metric.side_effect = query_metric
        response = BedrockAnalyticsAgent(
            config(model_id=target.model_id, reference_date=target.reference_date),
            client=model,
            adapter=cast(SemanticAdapter, adapter),
            dataset_version=target.dataset_version,
        ).run(AgentRequest(question=case.question), context=trusted)
    result = judge_response(case, golden, response, target)
    assert result.status == "passed", (case.id, result.reasons)
    assert requested == list(case.expected_queries)
    if case.kind == "clarification" or case.id == "Q30":
        assert not model.calls and not requested
    elif case.kind != "metadata":
        assert len(model.calls) == 1


@pytest.mark.parametrize(
    ("reference", "start", "end"),
    [
        ("2025-04-01", "2025-03-31", "2025-04-01"),
        ("2024-03-01", "2024-02-29", "2024-03-01"),
        ("2025-03-01", "2025-02-28", "2025-03-01"),
        ("2025-01-01", "2024-12-31", "2025-01-01"),
    ],
)
def test_resolved_yesterday_boundaries(
    source: Path, context: AuthorizationContext, reference: str, start: str, end: str
) -> None:
    response = execute(
        source, context, Model(turn()), "Show gross_sales for yesterday.", reference_date=reference
    )
    assert response.status == "answer"
    assert response.results[0].time_range.start.isoformat() == start
    assert response.results[0].time_range.end.isoformat() == end


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        ("gross_sales", "53.00"),
        ("net_revenue", "41.50"),
        ("order_count", 3),
        ("average_order_value", "13.83"),
        ("return_rate", "0.666667"),
    ],
)
def test_resolved_query_uses_real_adapter_for_all_five_metrics(
    source: Path, context: AuthorizationContext, metric: str, expected: str | int
) -> None:
    response = execute(source, context, Model(turn()), f"Show {metric} for January 2025.")
    assert response.status == "answer"
    assert response.model_dump(mode="json")["results"][0]["rows"][0]["value"] == expected


def test_resolved_plan_refuses_over_budget_before_any_query(
    source: Path, context: AuthorizationContext
) -> None:
    response = execute(
        source,
        context,
        Model(turn()),
        "Show net_revenue and gross_sales for January 2025.",
        max_tool_calls=1,
    )
    assert response.error_code == "tool_limit"
    assert not response.results and not response.diagnostics.tool_calls


@pytest.mark.parametrize("failure", [AuthorizationError("denied"), RuntimeError("private detail")])
def test_resolved_tool_failure_is_recorded_and_never_retried(
    context: AuthorizationContext, failure: Exception
) -> None:
    adapter = Mock(spec=SemanticAdapter)
    adapter.diagnostics = ()
    adapter.query_metric.side_effect = failure
    model = Model(turn())
    response = BedrockAnalyticsAgent(
        config(), client=model, adapter=cast(SemanticAdapter, adapter), dataset_version="parity-v1"
    ).run(
        AgentRequest(question="Show net_revenue and gross_sales for January 2025."), context=context
    )
    assert response.status == "error"
    assert response.error_code == (
        "AuthorizationError" if isinstance(failure, AuthorizationError) else "tool_error"
    )
    assert adapter.query_metric.call_count == 1 and len(model.calls) == 1
    assert len(response.diagnostics.tool_calls) == 1
    assert response.diagnostics.tool_calls[0].status == "error"
    assert "private detail" not in response.answer


def test_invalid_model_query_is_not_replaced_by_a_resolved_plan(
    source: Path, context: AuthorizationContext
) -> None:
    model = Model(turn(tool(arguments={**query(), "tenant_id": "other"})), turn())
    response = execute(source, context, model, "Show net_revenue for January 2025.")
    assert response.error_code == "invalid_tool_arguments"
    assert len(response.diagnostics.tool_calls) == 1 and not response.results


def test_resolved_plan_does_not_run_after_model_filter_or_timeout(
    source: Path, context: AuthorizationContext
) -> None:
    blocked = execute(
        source,
        context,
        Model({**turn(), "stopReason": "content_filtered"}),
        "Show net_revenue for January 2025.",
    )
    assert blocked.error_code == "model_stopped" and not blocked.diagnostics.tool_calls
    now = [0.0]

    class SlowModel:
        def converse(self, **kwargs: object) -> dict[str, object]:
            now[0] = 1.0
            return turn()

    with DuckDBSemanticAdapter(source) as adapter:
        timed_out = BedrockAnalyticsAgent(
            config(timeout_seconds=0.5),
            client=SlowModel(),
            adapter=adapter,
            dataset_version="parity-v1",
            clock=lambda: now[0],
        ).run(AgentRequest(question="Show net_revenue for January 2025."), context=context)
    assert timed_out.error_code == "time_limit" and not timed_out.diagnostics.tool_calls


def test_metadata_then_no_query_preserves_evidence_and_avoids_id_collision(
    source: Path, context: AuthorizationContext
) -> None:
    model = Model(
        turn(tool("describe_metric", {"metric_id": "net_revenue"}, "resolved-plan-2")),
        turn(),
    )
    response = execute(source, context, model, "Show net_revenue for January 2025.")
    assert response.status == "answer"
    assert [call.tool_use_id for call in response.diagnostics.tool_calls] == [
        "resolved-plan-2",
        "resolved-plan-3",
    ]
    assert len(model.calls) == 2
    assert len(cast(list[object], model.calls[1]["messages"])) == 3
    assert response.model_dump(mode="json")["results"][0]["rows"][0]["value"] == "41.50"


def test_resolved_plan_has_no_cross_request_filter_or_conversation_state(
    source: Path, context: AuthorizationContext
) -> None:
    model = Model(turn(), turn())
    with DuckDBSemanticAdapter(source) as adapter:
        agent = BedrockAnalyticsAgent(
            config(), client=model, adapter=adapter, dataset_version="parity-v1"
        )
        north = agent.run(
            AgentRequest(question="Show net_revenue for January 2025 in North."), context=context
        )
        south = agent.run(
            AgentRequest(question="Show net_revenue for January 2025 in South."), context=context
        )
    assert north.status == south.status == "answer"
    assert str(north.results[0].rows[0].value) == "28.50"
    assert str(south.results[0].rows[0].value) == "13.00"
    assert south.diagnostics.tool_calls[0].arguments["dimension_filters"] == {"region": ["South"]}
    assert north.diagnostics.model_calls == south.diagnostics.model_calls == 1
    assert len(cast(list[object], model.calls[1]["messages"])) == 1


def test_resolved_missing_returns_remains_an_error(
    tmp_path: Path, context: AuthorizationContext
) -> None:
    write_parity_snapshot(tmp_path, returns="absent")
    response = execute(tmp_path, context, Model(turn()), "Show return_rate for January 2025.")
    assert response.error_code == "MissingMetricDataError" and not response.results
    assert len(response.diagnostics.tool_calls) == 1
    assert response.diagnostics.tool_calls[0].status == "error"


def test_resolved_multimetric_multiperiod_plan_keeps_all_four_results(
    source: Path, context: AuthorizationContext
) -> None:
    response = execute(
        source,
        context,
        Model(turn()),
        "Compare net_revenue and gross_sales for each metric in each period: "
        "January 2025 versus February 2025.",
    )
    assert response.status == "answer"
    assert {
        (result.metric_id, result.time_range.start.isoformat(), str(result.rows[0].value))
        for result in response.results
    } == {
        ("gross_sales", "2025-01-01", "53.00"),
        ("gross_sales", "2025-02-01", "7.00"),
        ("net_revenue", "2025-01-01", "41.50"),
        ("net_revenue", "2025-02-01", "7.00"),
    }
    assert len(response.diagnostics.tool_calls) == 4
