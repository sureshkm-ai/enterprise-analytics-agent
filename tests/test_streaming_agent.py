"""Real semantic results with authored provider streams and request-local accounting."""

from collections.abc import Callable, Iterator
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from test_metrics_v2 import metric_rows as metric_rows
from test_metrics_v2 import metrics_dir as metrics_dir
from test_metrics_v2 import return_rows as return_rows

from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
)
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.adapters.streaming_agent import (
    StreamingAnalyticsAgent,
    StreamingLimitError,
    StreamingLimits,
)
from enterprise_analytics_agent.agent.contracts import AgentRequest
from enterprise_analytics_agent.contracts import AuthorizationContext


def tool_turn(metric: str) -> dict[str, object]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "query-1",
                            "name": "query_metric",
                            "input": {
                                "metric_id": metric,
                                "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
                            },
                        }
                    }
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 20, "outputTokens": 10, "totalTokens": 30},
    }


def final_turn() -> dict[str, object]:
    # The semantic renderer must ignore this deliberately incorrect model number.
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": "9999.99 USD"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 20, "outputTokens": 10, "totalTokens": 30},
    }


class Planner:
    def __init__(self, *responses: dict[str, object] | BaseException) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []
        self.before: Callable[[], None] = lambda: None
        self.after: Callable[[], None] = lambda: None

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.before()
        self.calls.append(deepcopy(kwargs))
        response = self.responses.pop(0)
        self.after()
        if isinstance(response, BaseException):
            raise response
        return response


class ProviderEvents(Iterator[dict[str, object]]):
    def __init__(self, events: list[dict[str, object]]) -> None:
        self.events = iter(events)
        self.received = ""
        self.closed = 0
        self.before: Callable[[], None] = lambda: None

    def __iter__(self) -> "ProviderEvents":
        return self

    def __next__(self) -> dict[str, object]:
        self.before()
        event = next(self.events)
        delta = cast(dict[str, Any], event.get("contentBlockDelta", {})).get("delta", {})
        self.received += delta.get("text", "")
        return event

    def close(self) -> None:
        self.closed += 1


def events(text: str, *, usage: object = None) -> ProviderEvents:
    # Tiny provider chunks deliberately split words, decimals and date boundaries.
    blocks: list[dict[str, object]] = [{"messageStart": {"role": "assistant"}}]
    blocks.extend(
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": text[i : i + 3]}}}
        for i in range(0, len(text), 3)
    )
    blocks.extend(
        [
            {"contentBlockStop": {"contentBlockIndex": 0}},
            {"messageStop": {"stopReason": "end_turn"}},
            {
                "metadata": {
                    "usage": usage
                    if usage is not None
                    else {"inputTokens": 11, "outputTokens": 12, "totalTokens": 23}
                }
            },
        ]
    )
    return ProviderEvents(blocks)


class Presenter:
    def __init__(self, stream: ProviderEvents) -> None:
        self.stream = stream
        self.calls: list[dict[str, object]] = []
        self.before: Callable[[], None] = lambda: None

    def converse_stream(self, **kwargs: object) -> dict[str, object]:
        self.before()
        self.calls.append(deepcopy(kwargs))
        return {"stream": self.stream}


def canonical(metric: str, value: str, unit: str) -> str:
    return f"{metric} [2025-01-01, 2025-02-01); definition 1.0.0:\ntotal: {value} {unit}"


def configured(
    adapter: DuckDBSemanticAdapter, planner: Planner, presenter: Presenter, **kwargs: Any
) -> StreamingAnalyticsAgent:
    config = BedrockAgentConfig(
        model_id="configured-bedrock-model", reference_date=date(2025, 4, 1)
    )
    agent = BedrockAnalyticsAgent(
        config, client=planner, adapter=adapter, dataset_version="authored-seven-table-fixture"
    )
    return StreamingAnalyticsAgent(agent, presentation_client=presenter, **kwargs)


@pytest.mark.parametrize(
    ("metric", "expected", "unit"),
    [
        ("gross_sales", Decimal("53.00"), "USD"),
        ("net_revenue", Decimal("42.50"), "USD"),
        ("order_count", 3, "count"),
        ("average_order_value", Decimal("14.17"), "USD"),
        ("return_rate", Decimal("0.333333"), "ratio"),
    ],
)
def test_all_metrics_stream_only_actual_provider_characters_and_preserve_exact_results(
    metrics_dir: Path,
    context: AuthorizationContext,
    metric: str,
    expected: Decimal | int,
    unit: str,
) -> None:
    # Handwritten fixture arithmetic: gross 28+10+15; discounts 3+2; refunds 5.50;
    # three orders, one returned order. Ratios round only their final aggregate.
    answer = canonical(metric, str(expected), unit)
    stream = events(answer)
    planner, presenter = Planner(tool_turn(metric), final_turn()), Presenter(stream)
    records: list[dict[str, object]] = []
    words: list[str] = []

    def require_reservation() -> None:
        assert records[-1]["event"] == "reserved"

    def publish(word: str) -> None:
        words.append(word)
        assert stream.received.startswith("".join(words))
        assert answer.startswith("".join(words))

    planner.before = presenter.before = require_reservation
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        runner = configured(adapter, planner, presenter)
        original = runner.agent.config.model_dump()
        outcome = runner.run(
            AgentRequest(question=f"Show {metric} for January 2025."),
            context=context,
            on_word=publish,
            record=records.append,
        )
        assert runner.agent.config.model_dump() == original
    assert outcome.response.status == "answer"
    assert outcome.response.answer == answer == "".join(words)
    assert outcome.response.results[0].rows[0].value == expected
    assert type(outcome.response.results[0].rows[0].value) is type(expected)
    assert outcome.response.results[0].time_range.start == date(2025, 1, 1)
    assert outcome.response.results[0].time_range.end == date(2025, 2, 1)
    assert outcome.response.dataset_version == "authored-seven-table-fixture"
    assert outcome.response.metric_versions == {metric: "1.0.0"}
    assert outcome.presentation == "streamed" and outcome.words == len(words) > 1
    assert len(planner.calls) == 2 and len(presenter.calls) == 1
    assert "toolConfig" not in presenter.calls[0]
    assert stream.closed == 1
    assert [record["event"] for record in records] == ["reserved", "returned"] * 3
    assert [record["operation"] for record in outcome.calls] == [
        "Converse",
        "Converse",
        "ConverseStream",
    ]
    assert outcome.response.diagnostics.model_calls == 3
    assert outcome.response.diagnostics.input_tokens == 51
    assert outcome.response.diagnostics.output_tokens == 32


@pytest.mark.parametrize("failure", ["wrong_amount", "truncated", "missing_usage", "bad_usage"])
def test_rejected_presentation_retains_canonical_answer_without_retry(
    metrics_dir: Path, context: AuthorizationContext, failure: str
) -> None:
    answer = canonical("net_revenue", "42.50", "USD")
    if failure == "wrong_amount":
        stream = events(answer.replace("42.50", "99.99"))
    elif failure == "truncated":
        stream = events(answer[:-2])
    elif failure == "missing_usage":
        original = events(answer)
        stream = ProviderEvents(list(original.events)[:-1])
    else:
        stream = events(answer, usage={"inputTokens": True, "outputTokens": 1, "totalTokens": 2})
    planner = Planner(tool_turn("net_revenue"), final_turn())
    presenter = Presenter(stream)
    published: list[str] = []
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(adapter, planner, presenter).run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=published.append,
        )
    assert outcome.presentation == "fallback"
    assert outcome.reason == "presentation_stream_rejected"
    assert outcome.response.answer == answer
    assert outcome.response.results[0].rows[0].value == Decimal("42.50")
    assert answer.startswith("".join(published))
    assert "99.99" not in "".join(published)
    assert len(planner.calls) == 2 and len(presenter.calls) == 1
    assert stream.closed == 1 and outcome.calls[-1]["status"] == "failed"


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"inputTokens": True, "outputTokens": 1, "totalTokens": 2},
        {"inputTokens": 0, "outputTokens": 1, "totalTokens": True},
        {"inputTokens": 1, "outputTokens": 1, "totalTokens": 3},
    ],
)
def test_unknown_or_invalid_planning_usage_stops_before_another_billable_call(
    metrics_dir: Path, context: AuthorizationContext, usage: object
) -> None:
    response = tool_turn("net_revenue")
    response["usage"] = usage
    planner = Planner(response)
    presenter = Presenter(events("must not be requested"))
    records: list[dict[str, object]] = []
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(adapter, planner, presenter).run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=lambda _: pytest.fail("No unvalidated answer may be streamed"),
            record=records.append,
        )
    assert outcome.response.status == "error"
    assert outcome.presentation == "not_needed"
    assert len(planner.calls) == 1 and presenter.calls == []
    assert [item["event"] for item in records] == ["reserved", "failed"]


@pytest.mark.parametrize("metric", ["average_order_value", "return_rate"])
def test_empty_ratio_result_preserves_null_without_model_substitution(
    metrics_dir: Path, context: AuthorizationContext, metric: str
) -> None:
    question = f"Show {metric} for January 2026."
    unit = "currency" if metric == "average_order_value" else "ratio"
    label = "USD" if unit == "currency" else "ratio"
    answer = (
        f"{metric} [2026-01-01, 2026-02-01); definition 1.0.0:\n"
        f"total: null (zero denominator) {label}"
    )
    response = tool_turn(metric)
    arguments = cast(dict[str, Any], response["output"])["message"]["content"][0]["toolUse"][
        "input"
    ]
    arguments["time_range"] = {"start": "2026-01-01", "end": "2026-02-01"}
    planner, presenter = Planner(response, final_turn()), Presenter(events(answer))
    words: list[str] = []
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(adapter, planner, presenter).run(
            AgentRequest(question=question), context=context, on_word=words.append
        )
    assert outcome.response.status == "answer" and outcome.presentation == "streamed"
    assert outcome.response.answer == answer == "".join(words)
    assert outcome.response.results[0].rows[0].value is None
    assert outcome.response.results[0].unit == unit


def test_grouped_stream_preserves_each_scope_and_amount(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    answer = (
        "net_revenue [2025-01-01, 2025-02-01); definition 1.0.0:\n"
        "region=North: 29.50 USD\nregion=South: 13.00 USD"
    )
    response = tool_turn("net_revenue")
    arguments = cast(dict[str, Any], response["output"])["message"]["content"][0]["toolUse"][
        "input"
    ]
    arguments["group_by"] = ["region"]
    planner, presenter = Planner(response, final_turn()), Presenter(events(answer))
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(adapter, planner, presenter).run(
            AgentRequest(question="Show net_revenue for January 2025 by region."),
            context=context,
            on_word=lambda _: None,
        )
    assert outcome.response.status == "answer" and outcome.presentation == "streamed"
    assert outcome.response.answer == answer
    assert [(row.dimensions, row.value) for row in outcome.response.results[0].rows] == [
        ({"region": "North"}, Decimal("29.50")),
        ({"region": "South"}, Decimal("13.00")),
    ]


def test_reservation_failure_prevents_any_sdk_dispatch(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    planner = Planner(tool_turn("net_revenue"))
    presenter = Presenter(events("not requested"))

    def unavailable_sink(_: dict[str, object]) -> None:
        raise OSError("offline journal unavailable")

    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(adapter, planner, presenter).run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=lambda _: None,
            record=unavailable_sink,
        )
    assert outcome.response.status == "error"
    assert planner.calls == presenter.calls == []
    assert outcome.calls == ()


@pytest.mark.parametrize(
    "question",
    [
        "Show revenue.",
        "Show net_revenue for January 2025 by region and product.",
        "Show net_revenue and refund amount for January 2025.",
    ],
)
def test_clarification_dispatches_neither_planning_nor_presentation(
    metrics_dir: Path, context: AuthorizationContext, question: str
) -> None:
    planner, presenter = Planner(), Presenter(events("not requested"))
    records: list[dict[str, object]] = []
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(adapter, planner, presenter).run(
            AgentRequest(question=question),
            context=context,
            on_word=lambda _: pytest.fail("Unresolved questions do not have a numeric stream"),
            record=records.append,
        )
    assert outcome.response.status == "clarification"
    assert outcome.presentation == "not_needed"
    assert outcome.response.results == ()
    assert planner.calls == presenter.calls == records == []


def test_callback_failure_closes_stream_and_never_retries(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    stream = events(canonical("net_revenue", "42.50", "USD"))
    planner, presenter = Planner(tool_turn("net_revenue"), final_turn()), Presenter(stream)

    def disconnected(_: str) -> None:
        raise RuntimeError("browser disconnected")

    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(adapter, planner, presenter).run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=disconnected,
        )
    assert outcome.presentation == "fallback" and stream.closed == 1
    assert len(presenter.calls) == 1
    assert outcome.calls[-1]["status"] == "failed"


def test_interrupted_callback_closes_stream_and_records_failed_sdk_attempt(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    stream = events(canonical("net_revenue", "42.50", "USD"))
    planner, presenter = Planner(tool_turn("net_revenue"), final_turn()), Presenter(stream)
    records: list[dict[str, object]] = []

    def interrupted(_: str) -> None:
        raise KeyboardInterrupt

    with DuckDBSemanticAdapter(metrics_dir) as adapter, pytest.raises(KeyboardInterrupt):
        configured(adapter, planner, presenter).run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=interrupted,
            record=records.append,
        )
    assert stream.closed == 1 and len(presenter.calls) == 1
    assert records[-1]["event"] == "failed"
    assert records[-1]["operation"] == "ConverseStream"
    assert records[-1]["error_type"] == "KeyboardInterrupt"


def test_planning_token_usage_cannot_consume_the_presentation_reservation(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    response = final_turn()
    response["usage"] = {"inputTokens": 9990, "outputTokens": 0, "totalTokens": 9990}
    planner, presenter = Planner(response), Presenter(events("must not be requested"))
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(
            adapter,
            planner,
            presenter,
            limits=StreamingLimits(total_tokens=10001, planning_tokens=10000),
        ).run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=lambda _: pytest.fail("No tokens remain for a presentation dispatch"),
        )
    assert outcome.response.status == "answer"
    assert outcome.response.results[0].rows[0].value == Decimal("42.50")
    assert outcome.presentation == "fallback"
    assert outcome.reason == "presentation_budget_unavailable"
    assert len(planner.calls) == 1 and presenter.calls == []


def test_reported_presentation_usage_above_combined_limit_closes_attempt(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    stream = events(
        canonical("net_revenue", "42.50", "USD"),
        usage={"inputTokens": 12000, "outputTokens": 1, "totalTokens": 12001},
    )
    planner, presenter = Planner(tool_turn("net_revenue"), final_turn()), Presenter(stream)
    records: list[dict[str, object]] = []
    with (
        DuckDBSemanticAdapter(metrics_dir) as adapter,
        pytest.raises(StreamingLimitError, match="combined token ceiling"),
    ):
        configured(adapter, planner, presenter).run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=lambda _: None,
            record=records.append,
        )
    assert len(presenter.calls) == 1 and stream.closed == 1
    assert records[-1]["event"] == "failed"
    assert records[-1]["error_type"] == "token_limit"
    assert records[-1]["input_tokens"] == 12000


def test_incomplete_planner_cannot_exceed_the_reviewed_call_ceiling(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    responses = []
    for number in range(5):
        response = tool_turn("net_revenue")
        content = cast(dict[str, Any], response["output"])["message"]["content"]
        content[0]["toolUse"].update(
            toolUseId=f"unknown-{number}", name="unsupported_tool", input={}
        )
        responses.append(response)
    planner, presenter = Planner(*responses), Presenter(events("must not be requested"))
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(adapter, planner, presenter).run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=lambda _: pytest.fail("No answer was validated"),
        )
    assert outcome.response.status == "error"
    assert outcome.response.error_code == "iteration_limit"
    assert len(planner.calls) == 5 and presenter.calls == []
    assert outcome.response.diagnostics.model_calls == 5


def test_stream_deadline_closes_stream_and_retains_authoritative_final_result(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    now = [0.0]
    stream = events(canonical("net_revenue", "42.50", "USD"))
    stream.before = lambda: now.__setitem__(0, 91.0)
    planner, presenter = Planner(tool_turn("net_revenue"), final_turn()), Presenter(stream)
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        outcome = configured(adapter, planner, presenter, clock=lambda: now[0]).run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=lambda _: pytest.fail("Expired stream must not publish text"),
        )
    assert outcome.presentation == "fallback" and stream.closed == 1
    assert outcome.response.results[0].rows[0].value == Decimal("42.50")
    assert len(presenter.calls) == 1


def test_each_run_has_fresh_history_and_separate_trusted_tenant_scope(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    planner = Planner(
        tool_turn("net_revenue"), final_turn(), tool_turn("net_revenue"), final_turn()
    )
    presenter = Presenter(events(canonical("net_revenue", "42.50", "USD")))
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        runner = configured(adapter, planner, presenter, allow_temperature=False)
        first = runner.run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=lambda _: None,
        )
        presenter.stream = events(canonical("net_revenue", "950.00", "USD"))
        second = runner.run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context.model_copy(update={"tenant_id": "t2"}),
            on_word=lambda _: None,
        )
    assert first.response.results[0].rows[0].value == Decimal("42.50")
    assert second.response.results[0].rows[0].value == Decimal("950.00")
    for index in (0, 2):
        assert len(cast(list[object], planner.calls[index]["messages"])) == 1
    for call in planner.calls + presenter.calls:
        assert "temperature" not in cast(dict[str, object], call["inferenceConfig"])
    assert [call["number"] for call in second.calls] == [1, 2, 3]


@pytest.mark.parametrize(
    "settings",
    [
        {"planning_calls": 6},
        {"total_calls": 7},
        {"planning_calls": 0},
        {"total_tokens": 12001},
        {"planning_tokens": 12000},
        {"presentation_output_tokens": 0},
    ],
)
def test_unreviewed_call_or_token_limits_are_rejected(settings: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        StreamingLimits(**settings)
