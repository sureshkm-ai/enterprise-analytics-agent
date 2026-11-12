"""Five sequential tool rounds can finish only a complete, proven numeric plan."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import boto3
import pytest
from test_metrics_v2 import metric_rows as metric_rows
from test_metrics_v2 import metrics_dir as metrics_dir
from test_metrics_v2 import return_rows as return_rows
from test_streaming_agent import Planner, Presenter, canonical, events, tool_turn

from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
)
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.adapters.streaming_agent import StreamingAnalyticsAgent
from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
from enterprise_analytics_agent.contracts import AuthorizationContext

METRICS = ("gross_sales", "net_revenue", "order_count", "average_order_value", "return_rate")
VALUES = (Decimal("53.00"), Decimal("42.50"), 3, Decimal("14.17"), Decimal("0.333333"))
QUESTION = (
    "Show gross_sales, net_revenue, order_count, average_order_value and return_rate "
    "for January 2025."
)
ANSWER = "\n".join(
    canonical(
        metric,
        str(value),
        "count" if metric == "order_count" else "ratio" if metric == "return_rate" else "USD",
    )
    for metric, value in zip(METRICS, VALUES, strict=True)
)


@pytest.fixture(autouse=True)
def no_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("guarded streaming completion must remain offline")

    monkeypatch.setattr(boto3, "Session", forbidden)


def turn(metric: str, number: int) -> dict[str, object]:
    result = deepcopy(tool_turn(metric))
    call = cast(dict[str, Any], result)["output"]["message"]["content"][0]["toolUse"]
    call["toolUseId"] = f"query-{number}"
    return result


def runner(
    adapter: DuckDBSemanticAdapter,
    planner: Planner,
    presenter: Presenter,
    **kwargs: Any,
) -> StreamingAnalyticsAgent:
    return StreamingAnalyticsAgent(
        BedrockAnalyticsAgent(
            BedrockAgentConfig(model_id="google.gemma-4-31b", reference_date=date(2025, 4, 1)),
            client=planner,
            adapter=adapter,
            dataset_version="handwritten-seven-table-fixture",
            **kwargs,
        ),
        presentation_client=presenter,
        **kwargs,
    )


def test_five_sequential_tool_rounds_finish_exact_plan_without_a_sixth_planning_call(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    planner = Planner(*(turn(metric, index) for index, metric in enumerate(METRICS, 1)))
    stream = events(ANSWER)
    presenter = Presenter(stream)
    words: list[str] = []
    records: list[dict[str, object]] = []
    verified: list[AgentResponse] = []
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = runner(adapter, planner, presenter).run(
            AgentRequest(question=QUESTION),
            context=context,
            on_word=words.append,
            on_verified=verified.append,
            record=records.append,
        )
    # Fixture arithmetic is independent: gross 28+10+15, discounts 3+2, refunds
    # 5.50; three orders, one physical return; final aggregate rounding only.
    assert outcome.response.status == "answer" and outcome.response.error_code is None
    assert [item.metric_id for item in outcome.response.results] == list(METRICS)
    assert [item.rows[0].value for item in outcome.response.results] == list(VALUES)
    assert outcome.response.answer == ANSWER == "".join(words)
    assert len(planner.calls) == 5 and len(presenter.calls) == 1
    assert outcome.response.diagnostics.model_calls == 6
    assert len([event for event in records if event["event"] == "reserved"]) == 6
    assert all(record.status == "success" for record in outcome.response.diagnostics.tool_calls)
    assert len(verified) == 1 and verified[0].results == outcome.response.results
    assert outcome.presentation == "streamed" and stream.closed == 1


def test_unchanged_legacy_loop_still_requires_a_final_turn_after_five_tool_rounds(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    planner = Planner(*(turn(metric, index) for index, metric in enumerate(METRICS, 1)))
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        legacy = BedrockAnalyticsAgent(
            BedrockAgentConfig(
                model_id="google.gemma-4-31b", reference_date=date(2025, 4, 1), max_iterations=5
            ),
            client=planner,
            adapter=adapter,
            dataset_version="handwritten-seven-table-fixture",
        ).run(AgentRequest(question=QUESTION), context=context)
    assert legacy.status == "error" and legacy.error_code == "iteration_limit"
    assert [result.rows[0].value for result in legacy.results] == list(VALUES)
    assert len(planner.calls) == 5


@pytest.mark.parametrize("last", ["duplicate", "metadata", "missing-source", "invalid-filter"])
def test_incomplete_or_failed_five_round_plan_never_becomes_an_answer(
    metrics_dir: Path, context: AuthorizationContext, last: str
) -> None:
    turns = [turn(metric, index) for index, metric in enumerate(METRICS, 1)]
    if last == "duplicate":
        turns[-1] = turn("gross_sales", 5)
    elif last == "metadata":
        call = cast(dict[str, Any], turns[-1])["output"]["message"]["content"][0]["toolUse"]
        call["name"], call["input"] = "describe_metric", {"metric_id": "return_rate"}
    elif last == "missing-source":
        (metrics_dir / "returns.parquet").unlink()
    else:
        cast(dict[str, Any], turns[-1])["output"]["message"]["content"][0]["toolUse"]["input"][
            "dimension_filters"
        ] = {"region": ["North"]}
    planner, presenter = Planner(*turns), Presenter(events(ANSWER))
    words: list[str] = []
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = runner(adapter, planner, presenter).run(
            AgentRequest(question=QUESTION), context=context, on_word=words.append
        )
    assert outcome.response.status == "error"
    assert outcome.response.error_code == "iteration_limit"
    assert len(planner.calls) == 5 and presenter.calls == [] and words == []


def test_duplicate_results_do_not_satisfy_complete_five_metric_identity_set(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    turns = [turn(metric, index) for index, metric in enumerate(METRICS, 1)]
    first = cast(dict[str, Any], turns[0])["output"]["message"]["content"]
    duplicate = deepcopy(first[0])
    duplicate["toolUse"]["toolUseId"] = "duplicate-gross-sales"
    first.append(duplicate)
    planner, presenter = Planner(*turns), Presenter(events(ANSWER))
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = runner(adapter, planner, presenter).run(
            AgentRequest(question=QUESTION), context=context, on_word=lambda word: None
        )
    assert outcome.response.status == "error" and outcome.response.error_code == "iteration_limit"
    assert len(outcome.response.results) == 6 and presenter.calls == []


@pytest.mark.parametrize("tamper", ["filter", "period", "metric", "grouping", "status"])
def test_complete_values_cannot_override_inconsistent_query_diagnostics(
    metrics_dir: Path,
    context: AuthorizationContext,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    original = BedrockAnalyticsAgent.run

    def altered(self: BedrockAnalyticsAgent, *args: Any, **kwargs: Any) -> AgentResponse:
        result = original(self, *args, **kwargs)
        record = result.diagnostics.tool_calls[-1]
        arguments = deepcopy(record.arguments)
        if tamper == "filter":
            arguments["dimension_filters"] = {"region": ["North"]}
        elif tamper == "period":
            arguments["time_range"] = {"start": "2025-02-01", "end": "2025-03-01"}
        elif tamper == "metric":
            arguments["metric_id"] = "gross_sales"
        elif tamper == "grouping":
            arguments["group_by"] = ["region"]
        modified = record.model_copy(
            update={"arguments": arguments, **({"status": "error"} if tamper == "status" else {})}
        )
        diagnostics = result.diagnostics.model_copy(
            update={"tool_calls": (*result.diagnostics.tool_calls[:-1], modified)}
        )
        return result.model_copy(update={"diagnostics": diagnostics})

    monkeypatch.setattr(BedrockAnalyticsAgent, "run", altered)
    planner = Planner(*(turn(metric, index) for index, metric in enumerate(METRICS, 1)))
    presenter = Presenter(events(ANSWER))
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = runner(adapter, planner, presenter).run(
            AgentRequest(question=QUESTION), context=context, on_word=lambda word: None
        )
    assert outcome.response.status == "error" and outcome.response.error_code == "iteration_limit"
    assert len(outcome.response.results) == 5 and presenter.calls == []


@pytest.mark.parametrize("failure", ["deadline", "tokens", "model"])
def test_time_token_or_model_failure_cannot_be_promoted(
    metrics_dir: Path, context: AuthorizationContext, failure: str
) -> None:
    clock = [0.0]
    turns: list[dict[str, object] | BaseException] = [
        turn(metric, index) for index, metric in enumerate(METRICS, 1)
    ]
    if failure == "tokens":
        cast(dict[str, Any], turns[-1])["usage"] = {
            "inputTokens": 10001,
            "outputTokens": 10,
            "totalTokens": 10011,
        }
    elif failure == "model":
        turns[-1] = ConnectionError("authored unavailable model")
    planner, presenter = Planner(*turns), Presenter(events(ANSWER))
    if failure == "deadline":
        planner.after = lambda: clock.__setitem__(0, 90.0) if len(planner.calls) == 5 else None
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = runner(adapter, planner, presenter, clock=lambda: clock[0]).run(
            AgentRequest(question=QUESTION), context=context, on_word=lambda word: None
        )
    assert outcome.response.status == "error"
    assert (
        outcome.response.error_code
        == {"deadline": "time_limit", "tokens": "token_limit", "model": "model_error"}[failure]
    )
    assert presenter.calls == [] and len(planner.calls) <= 5


def test_unrepresentable_clause_never_enters_completion_or_model_execution(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    planner, presenter = Planner(), Presenter(events(ANSWER))
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = runner(adapter, planner, presenter).run(
            AgentRequest(question=QUESTION + " By product."),
            context=context,
            on_word=lambda word: None,
        )
    assert outcome.response.status == "clarification"
    assert outcome.response.results == () and planner.calls == presenter.calls == []
