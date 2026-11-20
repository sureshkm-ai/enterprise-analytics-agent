"""Authored complete-plan regressions; no generated reports, data or AWS clients."""

from collections.abc import Callable, Iterator
from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.adapter import SemanticAdapter
from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
)
from enterprise_analytics_agent.adapters.streaming_agent import (
    StreamingAnalyticsAgent,
    StreamingLimitError,
    StreamingLimits,
    StreamingOutcome,
)
from enterprise_analytics_agent.agent.contracts import AgentRequest
from enterprise_analytics_agent.agent.questions import question_scope
from enterprise_analytics_agent.catalog import get_metrics
from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.contracts_v2 import (
    DiscoverMetricsRequestV2,
    DiscoverMetricsResponseV2,
    MetricSummaryV2,
    QueryMetricRequestV2,
    QueryMetricResponseV2,
)
from enterprise_analytics_agent.errors import AuthorizationError, MissingMetricDataError

METRICS = ("gross_sales", "net_revenue", "order_count", "average_order_value", "return_rate")
QUESTION = (
    "Show gross_sales, net_revenue, order_count, average_order_value and return_rate "
    "for January 2025 by region."
)
REQUEST = AgentRequest(question=QUESTION)
CONTEXT = AuthorizationContext(
    principal_id="authored-application",
    tenant_id="authored-tenant",
    allowed_regions=("North", "South"),
)
# North: gross28+10, discount3, refund5.50, two orders/one returned order.
# South: gross15, discount2, no refunds, one order/no physical return.
# Ratios and final formatting below are handwritten independently of adapters.
VALUES: dict[str, tuple[str, str | None, tuple[Decimal | int, Decimal | int]]] = {
    "gross_sales": ("currency", "USD", (Decimal("38.00"), Decimal("15.00"))),
    "net_revenue": ("currency", "USD", (Decimal("29.50"), Decimal("13.00"))),
    "order_count": ("count", None, (2, 1)),
    "average_order_value": ("currency", "USD", (Decimal("14.75"), Decimal("13.00"))),
    "return_rate": ("ratio", None, (Decimal("0.500000"), Decimal("0.000000"))),
}
ANSWER = (
    "gross_sales [2025-01-01, 2025-02-01); definition 1.0.0:\n"
    "region=North: 38.00 USD\nregion=South: 15.00 USD\n"
    "net_revenue [2025-01-01, 2025-02-01); definition 1.0.0:\n"
    "region=North: 29.50 USD\nregion=South: 13.00 USD\n"
    "order_count [2025-01-01, 2025-02-01); definition 1.0.0:\n"
    "region=North: 2 count\nregion=South: 1 count\n"
    "average_order_value [2025-01-01, 2025-02-01); definition 1.0.0:\n"
    "region=North: 14.75 USD\nregion=South: 13.00 USD\n"
    "return_rate [2025-01-01, 2025-02-01); definition 1.0.0:\n"
    "region=North: 0.500000 ratio\nregion=South: 0.000000 ratio"
)


def result(metric: str) -> QueryMetricResponseV2:
    unit, currency, values = VALUES[metric]
    return QueryMetricResponseV2.model_validate(
        {
            "metric_id": metric,
            "definition_version": "1.0.0",
            "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
            "group_by": ["region"],
            "unit": unit,
            "currency": currency,
            "rows": [
                {"dimensions": {"region": region}, "value": value}
                for region, value in zip(("North", "South"), values, strict=True)
            ],
        }
    )


class AuthoredAdapter:
    def __init__(
        self, failure: str = "", after_query: Callable[[int], None] = lambda _: None
    ) -> None:
        self.failure, self.after_query = failure, after_query
        self.queries: list[QueryMetricRequestV2] = []

    def discover_metrics(
        self, request: DiscoverMetricsRequestV2, *, context: AuthorizationContext
    ) -> DiscoverMetricsResponseV2:
        assert context is CONTEXT
        assert request.search is None
        if self.failure == "failed_discovery":
            raise MissingMetricDataError("Authored unavailable catalog")
        return DiscoverMetricsResponseV2(
            metrics=tuple(
                MetricSummaryV2(
                    metric_id=metric.metric_id,
                    display_name=metric.display_name,
                    description=metric.description,
                    definition_version=metric.definition_version,
                )
                for metric in get_metrics("v2")
            )
        )

    def query_metric(
        self, request: QueryMetricRequestV2, *, context: AuthorizationContext
    ) -> QueryMetricResponseV2:
        assert context is CONTEXT
        self.queries.append(request)
        if self.failure == "authorization" and request.metric_id == "return_rate":
            raise AuthorizationError("Authored application scope denies remaining query")
        if self.failure == "failed_query" and request.metric_id == "return_rate":
            raise MissingMetricDataError("Authored missing physical-return source")
        self.after_query(len(self.queries))
        return result(request.metric_id)


def tool(metric: str, identifier: str) -> dict[str, object]:
    return {
        "toolUse": {
            "toolUseId": identifier,
            "name": "query_metric",
            "input": {
                "api_version": "v2",
                "metric_id": metric,
                "time_range": {
                    "api_version": "v2",
                    "start": "2025-01-01",
                    "end": "2025-02-01",
                },
                "group_by": ["region"],
                "dimension_filters": {},
            },
        }
    }


def turn(content: list[dict[str, object]], incoming: int, outgoing: int) -> dict[str, object]:
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": "tool_use",
        "usage": {
            "inputTokens": incoming,
            "outputTokens": outgoing,
            "totalTokens": incoming + outgoing,
        },
    }


class Planner:
    def __init__(self, variant: str = "complete") -> None:
        self.variant = variant
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(deepcopy(kwargs))
        if len(self.calls) == 1:
            return turn(
                [{"toolUse": {"toolUseId": "discover", "name": "discover_metrics", "input": {}}}],
                1176,
                78,
            )
        if len(self.calls) > 2:
            raise AssertionError("No unnecessary third planning call may be dispatched")
        calls = [tool(metric, f"query-{index}") for index, metric in enumerate(METRICS)]
        if self.variant == "partial":
            calls.pop()
        elif self.variant == "duplicate":
            calls.append(tool("return_rate", "duplicate"))
        elif self.variant == "invalid_query":
            body = cast(dict[str, object], cast(dict[str, object], calls[-1]["toolUse"])["input"])
            body["group_by"] = ["product"]
        elif self.variant == "failed_tool_after_complete":
            calls.append({"toolUse": {"toolUseId": "unknown", "name": "unknown_tool", "input": {}}})
        incoming, outgoing = 1583, 378
        if self.variant == "planning_usage_overrun":
            incoming = 9000
        elif self.variant == "combined_usage_overrun":
            incoming = 12000
        elif self.variant == "tight_presentation":
            incoming = 8358
        response = turn(calls, incoming, outgoing)
        if self.variant == "provider_max_tokens":
            response["stopReason"] = "max_tokens"
        return response


class Presenter:
    def __init__(self, *, overrun: bool = False, answer: str = ANSWER) -> None:
        self.calls: list[dict[str, object]] = []
        self.overrun = overrun
        self.answer = answer

    def converse_stream(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(deepcopy(kwargs))

        def stream() -> Iterator[dict[str, object]]:
            yield {"messageStart": {"role": "assistant"}}
            for position in range(0, len(self.answer), 7):
                yield {
                    "contentBlockDelta": {
                        "contentBlockIndex": 0,
                        "delta": {"text": self.answer[position : position + 7]},
                    }
                }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            incoming = 12000 if self.overrun else 250
            yield {
                "metadata": {
                    "usage": {
                        "inputTokens": incoming,
                        "outputTokens": 250,
                        "totalTokens": incoming + 250,
                    }
                }
            }

        return {"stream": stream()}


def configured(
    variant: str = "complete", *, presenter_overrun: bool = False
) -> tuple[StreamingAnalyticsAgent, Planner, Presenter, AuthoredAdapter]:
    adapter = AuthoredAdapter(variant)
    planner, presenter = Planner(variant), Presenter(overrun=presenter_overrun)
    agent = BedrockAnalyticsAgent(
        BedrockAgentConfig(model_id="authored-nova", reference_date=date(2025, 4, 1)),
        client=planner,
        adapter=cast(SemanticAdapter, adapter),
        dataset_version="authored-seven-table-snapshot",
    )
    limits = (
        StreamingLimits(total_tokens=10001)
        if variant == "tight_presentation"
        else StreamingLimits()
    )
    return (
        StreamingAnalyticsAgent(agent, presentation_client=presenter, limits=limits),
        planner,
        presenter,
        adapter,
    )


def execute(
    variant: str = "complete",
) -> tuple[StreamingOutcome, Planner, Presenter, list[str], list[dict[str, object]]]:
    runner, planner, presenter, _ = configured(variant)
    words: list[str] = []
    records: list[dict[str, object]] = []
    outcome = runner.run(REQUEST, context=CONTEXT, on_word=words.append, record=records.append)
    return outcome, planner, presenter, words, records


def test_complete_five_metric_plan_streams_without_another_planning_reservation() -> None:
    outcome, planner, presenter, words, records = execute()
    assert outcome.response.status == "answer"
    assert outcome.response.error_code is None
    assert outcome.presentation == "streamed"
    assert outcome.response.answer == ANSWER == "".join(words)
    assert [item.metric_id for item in outcome.response.results] == list(METRICS)
    assert tuple(outcome.response.results) == tuple(result(metric) for metric in METRICS)
    assert outcome.response.dataset_version == "authored-seven-table-snapshot"
    assert outcome.response.metric_versions == dict.fromkeys(METRICS, "1.0.0")
    assert len(planner.calls) == 2 and len(presenter.calls) == 1
    assert outcome.response.diagnostics.model_calls == 3
    assert (
        outcome.response.diagnostics.input_tokens + outcome.response.diagnostics.output_tokens
        == 3715
    )
    assert [record["operation"] for record in records if record["event"] == "reserved"] == [
        "Converse",
        "Converse",
        "ConverseStream",
    ]
    assert "toolConfig" not in presenter.calls[0]
    assert cast(dict[str, object], presenter.calls[0]["inferenceConfig"])["maxTokens"] == 1024


@pytest.mark.parametrize(
    "variant",
    [
        "duplicate",
        "invalid_query",
        "failed_query",
        "failed_discovery",
        "failed_tool_after_complete",
    ],
)
def test_incomplete_or_unsuccessful_work_cannot_be_promoted_to_a_streamed_answer(
    variant: str,
) -> None:
    outcome, planner, presenter, words, _ = execute(variant)
    assert outcome.response.status == "error"
    assert outcome.presentation == "not_needed"
    assert len(planner.calls) == 2
    assert not presenter.calls and not words
    assert not any(
        call.tool_use_id.startswith("resolved-plan-")
        for call in outcome.response.diagnostics.tool_calls
    )


@pytest.mark.parametrize(
    "variant", ["provider_max_tokens", "planning_usage_overrun", "combined_usage_overrun"]
)
def test_token_and_provider_failures_are_never_promoted(variant: str) -> None:
    outcome, planner, presenter, words, records = execute(variant)
    assert outcome.response.status == "error"
    assert len(planner.calls) == 2
    assert not presenter.calls and not words
    if variant == "combined_usage_overrun":
        assert any(record.get("error_type") == "token_limit" for record in records)
    else:
        assert outcome.response.error_code == "token_limit"


def test_deadline_after_fifth_result_cannot_be_promoted() -> None:
    runner, planner, presenter, adapter = configured()
    now = [0.0]
    adapter.after_query = lambda count: now.__setitem__(0, 91.0) if count == 5 else None
    runner.clock = runner.agent.clock = lambda: now[0]
    outcome = runner.run(
        REQUEST, context=CONTEXT, on_word=lambda _: pytest.fail("Expired work cannot stream")
    )
    assert outcome.response.status == "error" and outcome.response.error_code == "time_limit"
    assert len(planner.calls) == 2 and not presenter.calls


def test_complete_plan_keeps_presentation_reservation_when_no_budget_remains() -> None:
    outcome, planner, presenter, words, _ = execute("tight_presentation")
    assert outcome.response.status == "answer"
    assert outcome.response.answer == ANSWER
    assert (
        outcome.presentation == "fallback" and outcome.reason == "presentation_budget_unavailable"
    )
    assert (
        outcome.response.diagnostics.input_tokens + outcome.response.diagnostics.output_tokens
        == 9990
    )
    assert len(planner.calls) == 2 and not presenter.calls and not words


def test_reported_presentation_overrun_still_closes_attempt() -> None:
    runner, planner, presenter, _ = configured(presenter_overrun=True)
    records: list[dict[str, object]] = []
    with pytest.raises(StreamingLimitError, match="combined token ceiling"):
        runner.run(REQUEST, context=CONTEXT, on_word=lambda _: None, record=records.append)
    assert len(planner.calls) == 2 and len(presenter.calls) == 1
    assert records[-1]["event"] == "failed" and records[-1]["error_type"] == "token_limit"


def test_default_base_agent_retains_the_original_bounded_loop_behavior() -> None:
    planner = Planner()
    agent = BedrockAnalyticsAgent(
        BedrockAgentConfig(
            model_id="authored-nova", reference_date=date(2025, 4, 1), max_total_tokens=10000
        ),
        client=planner,
        adapter=cast(SemanticAdapter, AuthoredAdapter()),
        dataset_version="authored-seven-table-snapshot",
    )
    response = agent.run(REQUEST, context=CONTEXT)
    assert response.status == "error" and response.error_code == "token_limit"
    assert len(planner.calls) == 2
    assert tuple(response.results) == tuple(result(metric) for metric in METRICS)
    assert response.api_version == "agent-v1"
    assert all(item.api_version == "v2" for item in response.results)
    assert response.diagnostics.input_tokens + response.diagnostics.output_tokens == 3215


def test_completion_control_is_not_a_model_or_request_argument() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentRequest.model_validate({"question": QUESTION, "complete_on_planning_limit": True})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        BedrockAgentConfig.model_validate(
            {
                "model_id": "authored-nova",
                "reference_date": "2025-04-01",
                "complete_on_planning_limit": True,
            }
        )


class SequentialPlanner:
    def __init__(self, *, discovery: bool = False) -> None:
        self.discovery = discovery
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(deepcopy(kwargs))
        index = len(self.calls) - 1
        if self.discovery and index == 0:
            return turn(
                [{"toolUse": {"toolUseId": "discovery", "name": "discover_metrics", "input": {}}}],
                20,
                10,
            )
        metric_index = index - int(self.discovery)
        assert metric_index < len(METRICS), "No extra planning turn may be requested"
        return turn(
            [tool(METRICS[metric_index], f"sequential-{index}")],
            20 if self.discovery else 1000,
            10 if self.discovery else 100,
        )


def sequential_runner(
    *, discovery: bool = False, failure: str = "", max_tool_calls: int = 16
) -> tuple[StreamingAnalyticsAgent, SequentialPlanner, Presenter, AuthoredAdapter]:
    adapter = AuthoredAdapter(failure)
    planner, presenter = SequentialPlanner(discovery=discovery), Presenter()
    agent = BedrockAnalyticsAgent(
        BedrockAgentConfig(
            model_id="authored-sequential-model",
            reference_date=date(2025, 4, 1),
            max_tool_calls=max_tool_calls,
        ),
        client=planner,
        adapter=cast(SemanticAdapter, adapter),
        dataset_version="authored-seven-table-snapshot",
    )
    return (
        StreamingAnalyticsAgent(agent, presentation_client=presenter),
        planner,
        presenter,
        adapter,
    )


def test_sequential_model_resolves_only_missing_fifth_query_before_token_reservation() -> None:
    runner, planner, presenter, adapter = sequential_runner()
    words: list[str] = []
    outcome = runner.run(REQUEST, context=CONTEXT, on_word=words.append)
    assert outcome.response.status == "answer" and outcome.response.error_code is None
    assert outcome.presentation == "streamed"
    assert outcome.response.answer == ANSWER == "".join(words)
    assert tuple(outcome.response.results) == tuple(result(metric) for metric in METRICS)
    assert [query.metric_id for query in adapter.queries] == list(METRICS)
    assert len(planner.calls) == 4 and len(presenter.calls) == 1
    assert outcome.response.diagnostics.model_calls == 5
    assert outcome.response.diagnostics.tool_calls[-1].tool_use_id.startswith("resolved-plan-")
    assert outcome.response.diagnostics.tool_calls[-1].arguments["metric_id"] == "return_rate"


def test_valid_partial_at_capacity_executes_the_missing_query_before_rendering() -> None:
    runner, planner, presenter, adapter = configured("partial")
    words: list[str] = []
    outcome = runner.run(REQUEST, context=CONTEXT, on_word=words.append)
    assert outcome.response.status == "answer" and outcome.presentation == "streamed"
    assert outcome.response.answer == ANSWER == "".join(words)
    assert [query.metric_id for query in adapter.queries] == list(METRICS)
    assert tuple(outcome.response.results) == tuple(result(metric) for metric in METRICS)
    assert len(planner.calls) == 2 and len(presenter.calls) == 1
    assert outcome.response.diagnostics.tool_calls[-1].tool_use_id.startswith("resolved-plan-")
    assert outcome.response.diagnostics.tool_calls[-1].status == "success"


def test_discovery_and_four_queries_resolve_last_metric_at_five_round_limit() -> None:
    runner, planner, presenter, adapter = sequential_runner(discovery=True)
    words: list[str] = []
    outcome = runner.run(REQUEST, context=CONTEXT, on_word=words.append)
    assert outcome.response.status == "answer" and outcome.presentation == "streamed"
    assert outcome.response.answer == ANSWER == "".join(words)
    assert [query.metric_id for query in adapter.queries] == list(METRICS)
    assert tuple(outcome.response.results) == tuple(result(metric) for metric in METRICS)
    assert len(planner.calls) == 5 and len(presenter.calls) == 1
    assert outcome.response.diagnostics.model_calls == 6
    assert outcome.response.diagnostics.tool_calls[-1].tool_use_id.startswith("resolved-plan-")
    assert outcome.response.diagnostics.tool_calls[-1].arguments["metric_id"] == "return_rate"


@pytest.mark.parametrize("failure", ["failed_query", "authorization"])
def test_server_resolved_remaining_query_errors_prevent_an_answer(failure: str) -> None:
    runner, planner, presenter, adapter = sequential_runner(failure=failure)
    outcome = runner.run(
        REQUEST,
        context=CONTEXT,
        on_word=lambda _: pytest.fail("Failed remaining work cannot stream"),
    )
    assert outcome.response.status == "error" and outcome.presentation == "not_needed"
    assert len(planner.calls) == 4 and not presenter.calls
    assert [query.metric_id for query in adapter.queries] == list(METRICS)
    assert [item.metric_id for item in outcome.response.results] == list(METRICS[:-1])
    last = outcome.response.diagnostics.tool_calls[-1]
    assert last.tool_use_id.startswith("resolved-plan-") and last.status == "error"
    assert last.error_code == (
        "MissingMetricDataError" if failure == "failed_query" else "AuthorizationError"
    )


def test_tool_ceiling_blocks_before_dispatching_the_remaining_server_query() -> None:
    runner, planner, presenter, adapter = sequential_runner(max_tool_calls=4)
    outcome = runner.run(
        REQUEST, context=CONTEXT, on_word=lambda _: pytest.fail("No complete answer is available")
    )
    assert outcome.response.status == "error" and outcome.response.error_code == "tool_limit"
    assert len(planner.calls) == 4 and not presenter.calls
    assert [query.metric_id for query in adapter.queries] == list(METRICS[:-1])
    assert len(outcome.response.diagnostics.tool_calls) == 4


def test_deadline_during_remaining_server_query_never_promotes_complete_values() -> None:
    runner, planner, presenter, adapter = sequential_runner()
    now = [0.0]
    runner.clock = runner.agent.clock = lambda: now[0]
    adapter.after_query = lambda count: now.__setitem__(0, 91.0) if count == 5 else None
    outcome = runner.run(
        REQUEST, context=CONTEXT, on_word=lambda _: pytest.fail("Expired values cannot stream")
    )
    assert outcome.response.status == "error" and outcome.response.error_code == "time_limit"
    assert len(planner.calls) == 4 and not presenter.calls
    assert [query.metric_id for query in adapter.queries] == list(METRICS)
    assert tuple(outcome.response.results) == tuple(result(metric) for metric in METRICS)


def test_supported_group_and_filter_reordering_preserves_the_complete_numeric_answer() -> None:
    question = "Show net_revenue for January 2025 in North or South by region and channel."
    query = QueryMetricRequestV2.model_validate(
        {
            "metric_id": "net_revenue",
            "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
            "group_by": ["channel", "region"],
            "dimension_filters": {"region": ["South", "North"]},
        }
    )
    scope = question_scope(question, date(2025, 4, 1))
    assert scope.clarification is None
    assert scope.group_by == ("region", "channel")
    assert scope.filters == {"region": ("North", "South")}
    scope.validate_query(query)  # Both orderings describe exactly the same requested scope.
    expected = QueryMetricResponseV2.model_validate(
        {
            "metric_id": "net_revenue",
            "definition_version": "1.0.0",
            "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
            "group_by": ["channel", "region"],
            "unit": "currency",
            "currency": "USD",
            # Authored orders: North online28-3-5.50, North store10, South store15-2.
            "rows": [
                {"dimensions": {"channel": "online", "region": "North"}, "value": "19.50"},
                {"dimensions": {"channel": "store", "region": "North"}, "value": "10.00"},
                {"dimensions": {"channel": "store", "region": "South"}, "value": "13.00"},
            ],
        }
    )
    answer = (
        "net_revenue [2025-01-01, 2025-02-01); definition 1.0.0:\n"
        "channel=online, region=North: 19.50 USD\n"
        "channel=store, region=North: 10.00 USD\n"
        "channel=store, region=South: 13.00 USD"
    )

    class Adapter:
        def query_metric(
            self, request: QueryMetricRequestV2, *, context: AuthorizationContext
        ) -> QueryMetricResponseV2:
            assert request == query and context is CONTEXT
            return expected

    class Model:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def converse(self, **kwargs: object) -> dict[str, object]:
            self.calls.append(deepcopy(kwargs))
            if len(self.calls) == 1:
                return turn(
                    [
                        {
                            "toolUse": {
                                "toolUseId": "permuted-query",
                                "name": "query_metric",
                                "input": query.model_dump(mode="json"),
                            }
                        }
                    ],
                    20,
                    10,
                )
            assert len(self.calls) == 2
            return {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "Invented value9999.99 must not be rendered"}],
                    }
                },
                "stopReason": "end_turn",
                "usage": {"inputTokens": 20, "outputTokens": 10, "totalTokens": 30},
            }

    model, presenter = Model(), Presenter(answer=answer)
    agent = BedrockAnalyticsAgent(
        BedrockAgentConfig(model_id="authored-reordered-model", reference_date=date(2025, 4, 1)),
        client=model,
        adapter=cast(SemanticAdapter, Adapter()),
        dataset_version="authored-seven-table-snapshot",
    )
    words: list[str] = []
    outcome = StreamingAnalyticsAgent(agent, presentation_client=presenter).run(
        AgentRequest(question=question), context=CONTEXT, on_word=words.append
    )
    assert outcome.response.status == "answer" and outcome.response.error_code is None
    assert outcome.presentation == "streamed"
    assert outcome.response.results == (expected,)
    assert outcome.response.answer == answer == "".join(words)
    assert len(model.calls) == 2 and len(presenter.calls) == 1
    assert outcome.response.diagnostics.tool_calls[0].arguments == query.model_dump(mode="json")
    assert outcome.response.diagnostics.model_calls == 3
