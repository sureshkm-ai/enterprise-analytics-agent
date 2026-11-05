"""Independent multi-metric arithmetic and authorization examples for the v2 API."""

import json
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

import duckdb
import pytest
from conftest import write_snapshot

from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.contracts import AuthorizationContext, QueryMetricRequest, TimeRange
from enterprise_analytics_agent.contracts_v2 import (
    QueryMetricRequestV2,
    TimeRangeV2,
)
from enterprise_analytics_agent.data import OPTIONAL_TABLE_SCHEMAS, DataRow
from enterprise_analytics_agent.errors import (
    AuthorizationError,
    DataValidationError,
    InvalidDimensionError,
    MissingMetricDataError,
    SemanticError,
)

METRIC_TOTALS: dict[str, Decimal | int] = {
    "gross_sales": Decimal("53.00"),
    "net_revenue": Decimal("42.50"),
    "order_count": 3,
    "average_order_value": Decimal("14.17"),
    "return_rate": Decimal("0.333333"),
}


def query_v2(
    metric_id: str,
    *,
    group_by: tuple[str, ...] = (),
    filters: dict[str, tuple[str, ...]] | None = None,
    start: date = date(2025, 1, 1),
    end: date = date(2025, 2, 1),
) -> QueryMetricRequestV2:
    return QueryMetricRequestV2(
        metric_id=metric_id,
        time_range=TimeRangeV2(start=start, end=end),
        group_by=group_by,
        dimension_filters=filters or {},
    )


def write_returns(directory: Path, rows: list[DataRow]) -> None:
    """Write authored events only; no production generator or metric calculation."""
    schema = OPTIONAL_TABLE_SCHEMAS["returns"]
    definitions = ", ".join(f"{column} {kind}" for column, kind in schema)
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"CREATE TABLE returns ({definitions})")
        if rows:
            placeholders = ", ".join("?" for _ in schema)
            connection.executemany(f"INSERT INTO returns VALUES ({placeholders})", rows)
        connection.table("returns").write_parquet(str(directory / "returns.parquet"))


@pytest.fixture
def metric_rows(snapshot_rows: dict[str, list[DataRow]]) -> dict[str, list[DataRow]]:
    # Add North order B to A's two lines and South order C from the original fixture.
    snapshot_rows["orders"].extend(
        [
            ("t1", "o3", "c1", date(2025, 1, 3), "completed", "USD", "North", "online", 0, 0),
            (
                "t1",
                "o-no-items",
                "c1",
                date(2025, 1, 3),
                "completed",
                "USD",
                "North",
                "online",
                0,
                0,
            ),
        ]
    )
    snapshot_rows["order_items"].append(("t1", "i4", "o3", "p1", 1, 1000, 0))
    return snapshot_rows


@pytest.fixture
def return_rows() -> list[DataRow]:
    later = date(2025, 3, 1)
    received = date(2025, 3, 3)
    first: DataRow = ("t1", "ret1", "i1", 1, later, received, "received")
    return [
        first,
        first,  # An exact replay and two returned items still count order A once.
        ("t1", "ret2", "i2", 1, later, received, "received"),
        ("t1", "ret-pending", "i3", 1, later, None, "pending"),
        ("t1", "ret-rejected", "i4", 1, later, None, "rejected"),
        ("t1", "ret-cancel", "i-cancel", 1, later, received, "received"),
        ("t1", "ret-pending-order", "i-pending", 1, later, received, "received"),
        ("t1", "ret-eur", "i-eur", 1, later, received, "received"),
        ("t1", "ret-hidden", "i-hidden", 1, later, received, "received"),
        ("t2", "ret1", "i1", 1, later, received, "received"),
    ]


@pytest.fixture
def metrics_dir(
    tmp_path: Path, metric_rows: dict[str, list[DataRow]], return_rows: list[DataRow]
) -> Path:
    directory = write_snapshot(tmp_path / "metrics", metric_rows)
    write_returns(directory, return_rows)
    return directory


@pytest.mark.parametrize("metric_id", METRIC_TOTALS)
def test_independently_calculated_aggregate_values_and_json_types(
    metrics_dir: Path, context: AuthorizationContext, metric_id: str
) -> None:
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        result = adapter.query_metric(query_v2(metric_id), context=context)
    assert len(result.rows) == 1
    assert result.rows[0].dimensions == {}
    assert result.rows[0].value == METRIC_TOTALS[metric_id]
    payload = json.loads(result.model_dump_json())
    assert result.api_version == "v2"
    assert result.time_range.api_version == "v2"
    assert result.rows[0].api_version == "v2"
    if metric_id == "order_count":
        assert result.unit == "count"
        assert result.currency is None
        assert type(result.rows[0].value) is int
        assert type(payload["rows"][0]["value"]) is int
    elif metric_id == "return_rate":
        assert result.unit == "ratio"
        assert result.currency is None
        assert payload["rows"][0]["value"] == "0.333333"
    else:
        assert result.unit == "currency"
        assert result.currency == "USD"
        assert payload["rows"][0]["value"] == str(METRIC_TOTALS[metric_id])


@pytest.mark.parametrize(
    ("metric_id", "north", "south"),
    [
        ("gross_sales", Decimal("38.00"), Decimal("15.00")),
        ("net_revenue", Decimal("29.50"), Decimal("13.00")),
        ("order_count", 2, 1),
        ("average_order_value", Decimal("14.75"), Decimal("13.00")),
        ("return_rate", Decimal("0.500000"), Decimal("0.000000")),
    ],
)
def test_grouped_components_and_unweighted_total_are_distinct(
    metrics_dir: Path,
    context: AuthorizationContext,
    metric_id: str,
    north: Decimal | int,
    south: Decimal | int,
) -> None:
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        grouped = adapter.query_metric(query_v2(metric_id, group_by=("region",)), context=context)
        total = adapter.query_metric(query_v2(metric_id), context=context)
    assert [(row.dimensions, row.value) for row in grouped.rows] == [
        ({"region": "North"}, north),
        ({"region": "South"}, south),
    ]
    assert total.rows[0].value == METRIC_TOTALS[metric_id]


@pytest.mark.parametrize(
    ("metric_id", "north", "other_tenant"),
    [
        ("gross_sales", Decimal("38.00"), Decimal("1000.00")),
        ("net_revenue", Decimal("29.50"), Decimal("950.00")),
        ("order_count", 2, 1),
        ("average_order_value", Decimal("14.75"), Decimal("950.00")),
        ("return_rate", Decimal("0.500000"), Decimal("1.000000")),
    ],
)
def test_each_metric_obeys_trusted_regions_and_composite_tenant_keys(
    metrics_dir: Path,
    context: AuthorizationContext,
    metric_id: str,
    north: Decimal | int,
    other_tenant: Decimal | int,
) -> None:
    north_scope = context.model_copy(update={"allowed_regions": ("North",)})
    other_scope = context.model_copy(update={"tenant_id": "t2", "allowed_regions": ("North",)})
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        result = adapter.query_metric(query_v2(metric_id), context=north_scope)
        hidden = adapter.query_metric(
            query_v2(metric_id, group_by=("region",), filters={"region": ("South", "East")}),
            context=north_scope,
        )
        other = adapter.query_metric(query_v2(metric_id), context=other_scope)
        with pytest.raises(AuthorizationError):
            adapter.query_metric(
                query_v2(metric_id), context=context.model_copy(update={"allowed_regions": ()})
            )
    assert result.rows[0].value == north
    assert hidden.rows == ()
    assert other.rows[0].value == other_tenant


@pytest.mark.parametrize("metric_id", METRIC_TOTALS)
def test_each_metric_binds_filters_and_rejects_ungoverned_identifiers(
    metrics_dir: Path, context: AuthorizationContext, metric_id: str
) -> None:
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        injected = adapter.query_metric(
            query_v2(metric_id, group_by=("region",), filters={"region": ("North' OR 1=1 --",)}),
            context=context,
        )
        forged = context.model_copy(update={"tenant_id": "t1' OR 1=1 --"})
        assert (
            adapter.query_metric(query_v2(metric_id, group_by=("region",)), context=forged).rows
            == ()
        )
        with pytest.raises(InvalidDimensionError):
            adapter.query_metric(
                query_v2(metric_id, group_by=("region); DROP TABLE orders; --",)), context=context
            )
        with pytest.raises(InvalidDimensionError):
            adapter.query_metric(
                query_v2(metric_id, filters={"tenant_id": ("t2",)}), context=context
            )
        valid = adapter.query_metric(query_v2(metric_id), context=context)
    assert injected.rows == ()
    assert valid.rows[0].value == METRIC_TOTALS[metric_id]


@pytest.mark.parametrize(
    ("metric_id", "expected"),
    [
        ("gross_sales", Decimal("15.00")),
        ("net_revenue", Decimal("13.00")),
        ("order_count", 1),
        ("average_order_value", Decimal("13.00")),
        ("return_rate", Decimal("0.000000")),
    ],
)
def test_dimension_filters_apply_before_each_metrics_final_aggregation(
    metrics_dir: Path,
    context: AuthorizationContext,
    metric_id: str,
    expected: Decimal | int,
) -> None:
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        result = adapter.query_metric(
            query_v2(
                metric_id,
                group_by=("region", "channel"),
                filters={"region": ("North", "South"), "channel": ("store",)},
            ),
            context=context,
        )
    assert [(row.dimensions, row.value) for row in result.rows] == [
        ({"region": "South", "channel": "store"}, expected)
    ]


@pytest.mark.parametrize(
    ("metric_id", "jan1", "feb1"),
    [
        ("gross_sales", Decimal("28.00"), Decimal("7.00")),
        ("net_revenue", Decimal("19.50"), Decimal("7.00")),
        ("order_count", 1, 1),
        ("average_order_value", Decimal("19.50"), Decimal("7.00")),
        ("return_rate", Decimal("1.000000"), Decimal("0.000000")),
    ],
)
def test_original_order_attribution_and_adjacent_exclusive_boundaries(
    metrics_dir: Path,
    context: AuthorizationContext,
    metric_id: str,
    jan1: Decimal | int,
    feb1: Decimal | int,
) -> None:
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        first = adapter.query_metric(
            query_v2(metric_id, start=date(2025, 1, 1), end=date(2025, 1, 2)), context=context
        )
        boundary = adapter.query_metric(
            query_v2(metric_id, start=date(2025, 2, 1), end=date(2025, 2, 2)), context=context
        )
    # Jan 1 includes February refunds and March received returns from the same snapshot.
    assert first.rows[0].value == jan1
    assert boundary.rows[0].value == feb1


@pytest.mark.parametrize(
    ("metric_id", "expected"),
    [
        ("gross_sales", Decimal("0.00")),
        ("net_revenue", Decimal("0.00")),
        ("order_count", 0),
        ("average_order_value", None),
        ("return_rate", None),
    ],
)
def test_empty_metric_results_have_explicit_zero_or_null_denominators(
    metrics_dir: Path,
    context: AuthorizationContext,
    metric_id: str,
    expected: Decimal | int | None,
) -> None:
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        total = adapter.query_metric(
            query_v2(metric_id, start=date(2030, 1, 1), end=date(2030, 2, 1)), context=context
        )
        grouped = adapter.query_metric(
            query_v2(
                metric_id,
                group_by=("region",),
                start=date(2030, 1, 1),
                end=date(2030, 2, 1),
            ),
            context=context,
        )
    assert grouped.rows == ()
    assert len(total.rows) == 1
    assert total.rows[0].value == expected
    if expected is None:
        assert json.loads(total.model_dump_json())["rows"][0]["value"] is None


def test_refund_without_physical_return_does_not_count_returned_order(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    write_returns(metrics_dir, [])
    with DuckDBSemanticAdapter(metrics_dir) as adapter:
        net = adapter.query_metric(query_v2("net_revenue"), context=context)
        rate = adapter.query_metric(query_v2("return_rate"), context=context)
    assert net.rows[0].value == Decimal("42.50")
    assert rate.rows[0].value == Decimal("0.000000")


def test_received_return_without_refund_does_not_reduce_net_revenue(
    tmp_path: Path, metric_rows: dict[str, list[DataRow]], context: AuthorizationContext
) -> None:
    metric_rows["refunds"] = []
    directory = write_snapshot(tmp_path / "no-refund", metric_rows)
    write_returns(
        directory,
        [("t1", "only-return", "i4", 1, date(2025, 3, 1), date(2025, 3, 3), "received")],
    )
    with DuckDBSemanticAdapter(directory) as adapter:
        net = adapter.query_metric(query_v2("net_revenue"), context=context)
        rate = adapter.query_metric(query_v2("return_rate"), context=context)
    # $53 gross less $3 and $2 discounts; the physical return changes only the rate.
    assert net.rows[0].value == Decimal("48.00")
    assert rate.rows[0].value == Decimal("0.333333")


def test_returns_file_is_optional_for_the_four_other_metrics(
    tmp_path: Path, metric_rows: dict[str, list[DataRow]], context: AuthorizationContext
) -> None:
    directory = write_snapshot(tmp_path / "legacy", metric_rows)
    with DuckDBSemanticAdapter(directory) as adapter:
        for metric_id in ("gross_sales", "net_revenue", "order_count", "average_order_value"):
            assert (
                adapter.query_metric(query_v2(metric_id), context=context).rows[0].value
                == (METRIC_TOTALS[metric_id])
            )
        with pytest.raises(MissingMetricDataError, match="return"):
            adapter.query_metric(query_v2("return_rate"), context=context)


def test_exact_replays_do_not_multiply_any_metric(
    tmp_path: Path,
    metric_rows: dict[str, list[DataRow]],
    return_rows: list[DataRow],
    context: AuthorizationContext,
) -> None:
    for rows in metric_rows.values():
        rows.extend(rows[:1] * 2)
    directory = write_snapshot(tmp_path / "replays", metric_rows)
    write_returns(directory, return_rows + return_rows)
    with DuckDBSemanticAdapter(directory) as adapter:
        for metric_id, expected in METRIC_TOTALS.items():
            assert (
                adapter.query_metric(query_v2(metric_id), context=context).rows[0].value == expected
            )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [(2, "missing-item"), (3, 0), (3, -1), (3, 3), (5, None), (6, "unknown")],
)
def test_invalid_physical_returns_fail_snapshot_validation(
    metrics_dir: Path, field: int, replacement: str | int | None
) -> None:
    row: list[str | int | date | None] = [
        "t1",
        "bad-return",
        "i1",
        1,
        date(2025, 3, 1),
        date(2025, 3, 3),
        "received",
    ]
    row[field] = replacement
    write_returns(metrics_dir, [tuple(row)])
    with pytest.raises(DataValidationError):
        DuckDBSemanticAdapter(metrics_dir)


def test_conflicting_return_replay_fails_instead_of_selecting_one(metrics_dir: Path) -> None:
    first: DataRow = ("t1", "same-return", "i1", 1, date(2025, 3, 1), date(2025, 3, 3), "received")
    second: DataRow = ("t1", "same-return", "i1", 2, date(2025, 3, 1), date(2025, 3, 3), "received")
    write_returns(metrics_dir, [first, second])
    with pytest.raises(DataValidationError):
        DuckDBSemanticAdapter(metrics_dir)


def compact_rows(count: int, *, cents: int) -> dict[str, list[DataRow]]:
    """Small authored equal-price orders, independent of production generation."""
    return {
        "customers": [("t1", "c", "Customer", "North")],
        "products": [("t1", "p", "Product", "home", cents)],
        "orders": [
            ("t1", f"o{index}", "c", date(2025, 1, 1), "completed", "USD", "North", "online", 0, 0)
            for index in range(count)
        ],
        "order_items": [
            ("t1", f"i{index}", f"o{index}", "p", 1, cents, 0) for index in range(count)
        ],
        "payments": [],
        "refunds": [],
    }


def test_ratios_round_half_up_at_the_final_metric_precision(
    tmp_path: Path, context: AuthorizationContext
) -> None:
    tiny = compact_rows(2, cents=1)
    tiny["order_items"][0] = ("t1", "i0", "o0", "p", 1, 0, 0)
    directory = write_snapshot(tmp_path / "half-cent", tiny)
    with DuckDBSemanticAdapter(directory) as adapter:
        average = adapter.query_metric(query_v2("average_order_value"), context=context)
    assert average.rows[0].value == Decimal("0.01")  # $0.01 / 2 = $0.005.

    directory = write_snapshot(tmp_path / "ratio-tie", compact_rows(128, cents=1))
    write_returns(
        directory,
        [("t1", "r", "i0", 1, date(2025, 3, 1), date(2025, 3, 3), "received")],
    )
    with DuckDBSemanticAdapter(directory) as adapter:
        rate = adapter.query_metric(query_v2("return_rate"), context=context)
    assert rate.rows[0].value == Decimal("0.007813")  # 1 / 128 = 0.0078125.


def test_metric_arithmetic_is_independent_of_callers_decimal_context(
    metrics_dir: Path, context: AuthorizationContext
) -> None:
    with DuckDBSemanticAdapter(metrics_dir) as adapter, localcontext() as precision:
        precision.prec = 2
        for metric_id, expected in METRIC_TOTALS.items():
            assert (
                adapter.query_metric(query_v2(metric_id), context=context).rows[0].value == expected
            )


@pytest.mark.parametrize(
    "metric_id", ["gross_sales", "order_count", "average_order_value", "return_rate"]
)
def test_v1_new_metric_requests_raise_a_clear_version_error(
    metrics_dir: Path, context: AuthorizationContext, metric_id: str
) -> None:
    request = QueryMetricRequest(
        metric_id=metric_id,
        time_range=TimeRange(start=date(2025, 1, 1), end=date(2025, 2, 1)),
    )
    with DuckDBSemanticAdapter(metrics_dir) as adapter, pytest.raises(SemanticError, match="v2"):
        adapter.query_metric(request, context=context)
