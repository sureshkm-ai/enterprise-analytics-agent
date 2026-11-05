"""Independent edge cases for item grain, historical attribution, and date windows."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import write_snapshot

from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.contracts import AuthorizationContext, QueryMetricRequest, TimeRange
from enterprise_analytics_agent.data import DataRow


def _query(
    start: date = date(2025, 1, 1),
    end: date = date(2025, 2, 1),
    *,
    group_by: tuple[str, ...] = (),
) -> QueryMetricRequest:
    return QueryMetricRequest(
        metric_id="net_revenue",
        time_range=TimeRange(start=start, end=end),
        group_by=group_by,
    )


def test_distinct_equal_refunds_count_once_each_despite_replay(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]], context: AuthorizationContext
) -> None:
    first: DataRow = (
        "t1",
        "equal-a",
        "i1",
        date(2025, 2, 15),
        date(2025, 2, 15),
        "approved",
        150,
        "USD",
    )
    second: DataRow = (
        "t1",
        "equal-b",
        "i1",
        date(2025, 2, 15),
        date(2025, 2, 15),
        "approved",
        150,
        "USD",
    )
    snapshot_rows["refunds"].extend((first, second, first))
    directory = write_snapshot(tmp_path / "equal-refunds", snapshot_rows)
    with DuckDBSemanticAdapter(directory) as adapter:
        result = adapter.query_metric(_query(), context=context)
    # $32.50 baseline - two distinct $1.50 refunds; replaying equal-a adds nothing.
    assert len(result.rows) == 1
    assert result.rows[0].value == Decimal("29.50")


def test_multiple_refunds_on_multiple_items_preserve_item_grain(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]], context: AuthorizationContext
) -> None:
    snapshot_rows["refunds"].extend(
        [
            (
                "t1",
                refund_id,
                "i2",
                date(2025, 2, 15),
                date(2025, 2, 15),
                "approved",
                100,
                "USD",
            )
            for refund_id in ("second-item-a", "second-item-b")
        ]
    )
    directory = write_snapshot(tmp_path / "multiple-refunded-items", snapshot_rows)
    with DuckDBSemanticAdapter(directory) as adapter:
        result = adapter.query_metric(_query(), context=context)
    # The existing first-line refunds and two $1 second-line refunds each apply once.
    assert len(result.rows) == 1
    assert result.rows[0].value == Decimal("30.50")


def test_refund_during_january_stays_with_december_order(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]], context: AuthorizationContext
) -> None:
    snapshot_rows["refunds"] = [
        (
            "t1",
            "r-before",
            "i-before",
            date(2025, 1, 15),
            date(2025, 1, 15),
            "approved",
            200,
            "USD",
        )
        if record[1] == "r-before"
        else record
        for record in snapshot_rows["refunds"]
    ]
    directory = write_snapshot(tmp_path / "prior-period-refund", snapshot_rows)
    with DuckDBSemanticAdapter(directory) as adapter:
        december = adapter.query_metric(
            _query(date(2024, 12, 31), date(2025, 1, 1)), context=context
        )
        january = adapter.query_metric(_query(), context=context)
    # December's $9 order loses its $2 refund; January's $32.50 is unaffected.
    assert [row.value for row in december.rows] == [Decimal("7.00")]
    assert [row.value for row in january.rows] == [Decimal("32.50")]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2024, 12, 31), date(2025, 1, 1), Decimal("7.00")),
        (date(2025, 1, 1), date(2025, 2, 1), Decimal("32.50")),
        (date(2025, 2, 1), date(2025, 3, 1), Decimal("7.00")),
        (date(2024, 12, 31), date(2025, 3, 1), Decimal("46.50")),
    ],
)
def test_adjacent_periods_and_combined_range_have_literal_totals(
    snapshot_dir: Path,
    context: AuthorizationContext,
    start: date,
    end: date,
    expected: Decimal,
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        result = adapter.query_metric(_query(start, end), context=context)
    # Dec 31, Jan 1, and Feb 1 boundary orders belong to exactly one adjacent window.
    assert len(result.rows) == 1
    assert result.rows[0].value == expected


def test_customer_region_changes_do_not_restate_order_dimensions(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]], context: AuthorizationContext
) -> None:
    snapshot_rows["customers"] = [
        ("t1", "c1", "North customer", "East") if record[:2] == ("t1", "c1") else record
        for record in snapshot_rows["customers"]
    ]
    directory = write_snapshot(tmp_path / "customer-region-change", snapshot_rows)
    with DuckDBSemanticAdapter(directory) as adapter:
        result = adapter.query_metric(_query(group_by=("region",)), context=context)
    # Orders retain the purchase-time North region, including authorization and grouping.
    assert [(row.dimensions, row.value) for row in result.rows] == [
        ({"region": "North"}, Decimal("19.50")),
        ({"region": "South"}, Decimal("13.00")),
    ]
