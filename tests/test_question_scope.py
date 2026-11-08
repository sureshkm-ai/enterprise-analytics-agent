"""Whole-question scope regressions; expectations are authored semantic plans."""

from datetime import date

import pytest

from enterprise_analytics_agent.agent.questions import question_scope
from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2

REPRODUCTIONS: tuple[tuple[str, dict[str, object]], ...] = (
    (
        "Show net_revenue for January 2025 in North or online.",
        {"dimension_filters": {"region": ["North"], "channel": ["online"]}},
    ),
    ("Show net_revenue for January 2025 by region and product.", {"group_by": ["region"]}),
    ("Show net_revenue for January 2025 before January 15.", {}),
    ("Show net_revenue and refund amount for January 2025.", {}),
)


@pytest.mark.parametrize(("question", "partial"), REPRODUCTIONS)
def test_scope_requires_the_complete_request(question: str, partial: dict[str, object]) -> None:
    scope = question_scope(question, date(2025, 2, 1))
    assert scope.clarification, "A partial semantic plan must not stand in for the whole question"


@pytest.mark.parametrize(("question", "partial"), REPRODUCTIONS)
def test_clarified_scope_cannot_validate_a_partial_model_plan(
    question: str, partial: dict[str, object]
) -> None:
    scope = question_scope(question, date(2025, 2, 1))
    request = QueryMetricRequestV2.model_validate(
        {
            "metric_id": "net_revenue",
            "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
            **partial,
        }
    )
    with pytest.raises(ValueError):
        scope.validate_query(request)


@pytest.mark.parametrize(
    "question",
    [
        "Show net_revenue for January 2025 in online or North.",
        "Show net_revenue for January 2025 in North or channel=online.",
        "Show net_revenue for January 2025 in North or South and online.",
        "Show net_revenue for January 2025 by product and region.",
        "Show net_revenue for January 2025 by region, channel, and category.",
        "Show net_revenue for January 2025 by region and customer.",
        "Show net_revenue for January 2025 for each region and product.",
        "Show net_revenue for January 2025 in (North or online).",
        "Show net_revenue for January 2025 after January 15.",
        "Show net_revenue for January 2025 until January 15.",
        "Show net_revenue for January 2025 since January 15.",
        "Show net_revenue for January 2025 on January 15.",
        "Show refund amount and net_revenue for January 2025.",
        "Show net_revenue, gross_sales, and invoice value for January 2025.",
        "Show net_revenue for January 2025 with at least two orders.",
    ],
)
def test_unsupported_clause_variations_are_not_discarded(question: str) -> None:
    assert question_scope(question, date(2025, 2, 1)).clarification


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Show net_revenue for January 2025 in North or South.",
            {"dimension_filters": {"region": ["North", "South"]}},
        ),
        (
            "Show net_revenue for January 2025 in North and online.",
            {"dimension_filters": {"region": ["North"], "channel": ["online"]}},
        ),
        (
            "Show net_revenue for January 2025 in (North or South) and online.",
            {"dimension_filters": {"region": ["North", "South"], "channel": ["online"]}},
        ),
        (
            "Show net_revenue for January 2025 by region and channel.",
            {"group_by": ["region", "channel"]},
        ),
        (
            "Show net_revenue for January 2025 by channel and region.",
            {"group_by": ["region", "channel"]},
        ),
        (
            "Show net_revenue for January 2025 for each region and channel.",
            {"group_by": ["region", "channel"]},
        ),
        (
            "Show net_revenue for January 2025 by region and by channel.",
            {"group_by": ["region", "channel"]},
        ),
        (
            "Show net_revenue for January 2025 grouped by region.",
            {"group_by": ["region"]},
        ),
        ("Please show me the total net revenue for January 2025.", {}),
        (
            "Show net_revenue for [2025-01-01, 2025-01-15).",
            {"time_range": {"start": "2025-01-01", "end": "2025-01-15"}},
        ),
        (
            "Show net_revenue from 2025-01-01 to 2025-01-15 exclusive.",
            {"time_range": {"start": "2025-01-01", "end": "2025-01-15"}},
        ),
        ("Show net_revenue for last month.", {}),
    ],
)
def test_supported_neighbor_questions_retain_their_complete_plan(
    question: str, expected: dict[str, object]
) -> None:
    scope = question_scope(question, date(2025, 2, 1))
    assert scope.clarification is None
    request = QueryMetricRequestV2.model_validate(
        {
            "metric_id": "net_revenue",
            "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
            **expected,
        }
    )
    scope.validate_query(request)


def test_supported_multiple_metrics_and_periods_are_preserved() -> None:
    scope = question_scope(
        "Compare net_revenue and gross_sales for each metric in each period: "
        "January 2025 versus February 2025.",
        date(2025, 2, 1),
    )
    assert scope.clarification is None
    assert set(scope.metric_ids) == {"net_revenue", "gross_sales"}
    assert {(period.start, period.end) for period in scope.periods} == {
        (date(2025, 1, 1), date(2025, 2, 1)),
        (date(2025, 2, 1), date(2025, 3, 1)),
    }


def test_supported_catalog_discovery_wording_is_preserved() -> None:
    scope = question_scope("Which metrics are supported?", date(2025, 2, 1))
    assert scope.clarification is None and scope.metadata
