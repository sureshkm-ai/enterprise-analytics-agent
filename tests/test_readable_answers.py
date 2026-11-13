"""Readable values stay exact and survive the same local/Runtime streaming boundary."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_metrics_v2 import metric_rows as metric_rows
from test_metrics_v2 import metrics_dir as metrics_dir
from test_metrics_v2 import return_rows as return_rows
from test_model_stream_ui import Body, metric_answer
from test_model_streams_review import target
from test_streaming_agent import Planner, Presenter, configured, events, final_turn, tool_turn

from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.adapters.model_stream_ui import read_runtime_stream
from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
from enterprise_analytics_agent.agent.presentation import readable_answer
from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.contracts_v2 import MetricRowV2
from enterprise_analytics_agent.ui.models import UiError


def test_q18_exact_readable_amount_and_inclusive_human_date_without_mutation() -> None:
    response = metric_answer()
    original = response.model_dump_json()
    assert readable_answer(response) == "Net revenue: **110.25 USD** for **March 31, 2025**."
    assert response.model_dump_json() == original


def test_grouped_answers_escape_data_and_preserve_decimal_strings() -> None:
    base = metric_answer()
    result = base.results[0].model_copy(
        update={
            "group_by": ("region",),
            "rows": (
                MetricRowV2(
                    dimensions={"region": "North | **<script>"},
                    value=Decimal("9007199254740993.01"),
                ),
                MetricRowV2(dimensions={"region": "South"}, value=Decimal("0.00")),
            ),
        }
    )
    output = readable_answer(base.model_copy(update={"results": (result,)}))
    assert "| Region | Net revenue |" in output
    assert "9007199254740993.01 USD" in output and "0.00 USD" in output
    assert r"North \| \*\*\<script\>" in output


def test_empty_null_error_and_multiple_metrics_are_explicit() -> None:
    base = metric_answer()
    empty = base.results[0].model_copy(update={"rows": ()})
    assert "No eligible results" in readable_answer(base.model_copy(update={"results": (empty,)}))
    null = base.results[0].model_copy(
        update={
            "metric_id": "return_rate",
            "unit": "ratio",
            "currency": None,
            "rows": (MetricRowV2(dimensions={}, value=None),),
        }
    )
    output = readable_answer(base.model_copy(update={"results": (base.results[0], null)}))
    assert "### Net revenue" in output and "### Return rate" in output
    assert "Not defined (zero denominator)" in output
    error = AgentResponse(
        status="error",
        answer="Access unavailable.",
        error_code="model_error",
        dataset_version="retail-v1",
        diagnostics=base.diagnostics,
    )
    assert readable_answer(error) == "Access unavailable."


@pytest.mark.parametrize("change", [None, "wrong_amount", "changed_final"])
def test_runtime_independently_recomputes_readable_prelude_and_final(change: str | None) -> None:
    value = metric_answer()
    text = readable_answer(value)
    prelude: dict[str, Any] = {
        "type": "verified",
        "response": value.model_dump(mode="json"),
        "display_answer": text,
    }
    final: dict[str, Any] = {
        "type": "result",
        "response": value.model_dump(mode="json"),
        "display_answer": text,
        "presentation_status": "streamed",
    }
    if change == "wrong_amount":
        prelude["display_answer"] = text.replace("110.25", "9999.99")
    if change == "changed_final":
        final["display_answer"] = text + " invented conclusion"
    body = Body(
        [
            prelude,
            *[
                {
                    "type": "answer_delta",
                    "text": text[i : i + 3],
                    "validated": True,
                    "source": "bedrock",
                }
                for i in range(0, len(text), 3)
            ],
            final,
        ]
    )
    published: list[dict[str, object]] = []
    if change:
        with pytest.raises(UiError):
            read_runtime_stream(body, target(), published.append)
    else:
        result = read_runtime_stream(body, target(), published.append)
        assert result.display_answer == "".join(str(event["text"]) for event in published) == text
        assert result.response == value
    assert body.closed == 1


def test_real_semantic_loop_streams_readable_provider_chunks_not_invented_model_amount(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    text = "Net revenue: **42.50 USD** for **January 1, 2025 to January 31, 2025**."
    presenter = Presenter(events(text))
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        runner = configured(
            adapter, Planner(tool_turn("net_revenue"), final_turn()), presenter, readable=True
        )
        words: list[str] = []
        result = runner.run(
            AgentRequest(question="Show net_revenue for January 2025."),
            context=context,
            on_word=words.append,
        )
    assert result.presentation == "streamed"
    assert result.display_answer == "".join(words) == text
    assert "9999.99" not in result.display_answer
    assert "definition 1.0.0" in result.response.answer
