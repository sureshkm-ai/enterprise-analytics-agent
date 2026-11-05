from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from conftest import write_snapshot

from enterprise_analytics_agent.adapter import SemanticAdapter
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.contracts import (
    AuthorizationContext,
    DescribeMetricRequest,
    DiscoverDimensionsRequest,
    DiscoverMetricsRequest,
    QueryMetricRequest,
    TimeRange,
)
from enterprise_analytics_agent.data import DataRow
from enterprise_analytics_agent.errors import (
    AuthorizationError,
    DataValidationError,
    InvalidDimensionError,
    UnknownMetricError,
)


def query(
    *,
    group_by: tuple[str, ...] = ("region",),
    filters: dict[str, tuple[str, ...]] | None = None,
    start: date = date(2025, 1, 1),
    end: date = date(2025, 2, 1),
) -> QueryMetricRequest:
    return QueryMetricRequest(
        metric_id="net_revenue",
        time_range=TimeRange(start=start, end=end),
        group_by=group_by,
        dimension_filters=filters or {},
    )


def test_net_revenue_independent_worked_example(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        result = adapter.query_metric(query(), context=context)
    # North: (2*$10-$3) + $8 - $4 - $1.50 = $19.50.
    # South: 3*$5-$2 = $13.00. Pending/rejected refunds do not reduce revenue.
    # Canceled, pending, EUR, other-tenant, and unauthorized East orders do not count.
    assert [(row.dimensions, row.value) for row in result.rows] == [
        ({"region": "North"}, Decimal("19.50")),
        ({"region": "South"}, Decimal("13.00")),
    ]
    assert result.currency == "USD"
    assert result.unit == "currency"
    assert result.definition_version == "1.0.0"
    assert result.api_version == "v1"


def test_multiple_items_and_payment_events_do_not_multiply_sales(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        result = adapter.query_metric(query(group_by=()), context=context)
    assert len(result.rows) == 1
    assert result.rows[0].dimensions == {}
    assert result.rows[0].value == Decimal("32.50")


def test_refunds_are_attributed_to_original_order_date_after_query_end(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        result = adapter.query_metric(
            query(start=date(2025, 1, 1), end=date(2025, 1, 2)), context=context
        )
    # The Jan 1 order retains both refunds approved Feb 15, outside this interval.
    assert [(row.dimensions, row.value) for row in result.rows] == [
        ({"region": "North"}, Decimal("19.50"))
    ]


def test_start_inclusive_end_exclusive(snapshot_dir: Path, context: AuthorizationContext) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        before = adapter.query_metric(
            query(start=date(2024, 12, 31), end=date(2025, 1, 1)), context=context
        )
        february = adapter.query_metric(
            query(start=date(2025, 2, 1), end=date(2025, 2, 2)), context=context
        )
    assert [row.value for row in before.rows] == [Decimal("7.00")]
    assert [row.value for row in february.rows] == [Decimal("7.00")]


def test_identical_replayed_events_are_idempotent(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]], context: AuthorizationContext
) -> None:
    for records in snapshot_rows.values():
        records.extend([records[0], records[0]])
    directory = write_snapshot(tmp_path / "replays", snapshot_rows)
    with DuckDBSemanticAdapter(directory) as adapter:
        result = adapter.query_metric(query(group_by=()), context=context)
    assert result.rows[0].value == Decimal("32.50")


@pytest.mark.parametrize(
    ("table", "field_index", "replacement"),
    [("orders", 4, "canceled"), ("order_items", 6, 301), ("refunds", 6, 401)],
)
def test_conflicting_duplicate_business_keys_are_rejected(
    tmp_path: Path,
    snapshot_rows: dict[str, list[DataRow]],
    table: str,
    field_index: int,
    replacement: str | int,
) -> None:
    changed = list(snapshot_rows[table][0])
    changed[field_index] = replacement
    snapshot_rows[table].append(tuple(changed))
    directory = write_snapshot(tmp_path / "conflicts", snapshot_rows)
    with pytest.raises(DataValidationError):
        DuckDBSemanticAdapter(directory)


def test_empty_results_are_explicit(snapshot_dir: Path, context: AuthorizationContext) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        grouped = adapter.query_metric(
            query(start=date(2030, 1, 1), end=date(2030, 2, 1)), context=context
        )
        total = adapter.query_metric(
            query(group_by=(), start=date(2030, 1, 1), end=date(2030, 2, 1)), context=context
        )
    assert grouped.rows == ()
    assert len(total.rows) == 1
    assert total.rows[0].value == Decimal("0.00")
    assert '"value":"0.00"' in total.model_dump_json()


def test_zero_revenue_group_is_retained(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]], context: AuthorizationContext
) -> None:
    refund = list(snapshot_rows["refunds"][0])
    refund[6] = 2350
    snapshot_rows["refunds"][0] = tuple(refund)
    directory = write_snapshot(tmp_path / "zero", snapshot_rows)
    with DuckDBSemanticAdapter(directory) as adapter:
        result = adapter.query_metric(query(filters={"region": ("North",)}), context=context)
    # $25 net merchandise - $23.50 - $1.50 = $0, with an existing eligible group.
    assert len(result.rows) == 1
    assert result.rows[0].value == Decimal("0.00")


def test_negative_revenue_is_supported(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]], context: AuthorizationContext
) -> None:
    refund = list(snapshot_rows["refunds"][0])
    refund[6] = 2450
    snapshot_rows["refunds"][0] = tuple(refund)
    directory = write_snapshot(tmp_path / "negative", snapshot_rows)
    with DuckDBSemanticAdapter(directory) as adapter:
        result = adapter.query_metric(query(filters={"region": ("North",)}), context=context)
    assert result.rows[0].value == Decimal("-1.00")


def test_trusted_region_scope_cannot_be_widened(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    north_only = context.model_copy(update={"allowed_regions": ("North",)})
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        result = adapter.query_metric(query(), context=north_only)
        hidden = adapter.query_metric(
            query(filters={"region": ("South", "East")}), context=north_only
        )
    assert [(row.dimensions, row.value) for row in result.rows] == [
        ({"region": "North"}, Decimal("19.50"))
    ]
    assert hidden.rows == ()


def test_composite_tenant_keys_prevent_cross_tenant_sales_and_refunds(
    snapshot_dir: Path,
) -> None:
    other_tenant = AuthorizationContext(
        principal_id="other-app", tenant_id="t2", allowed_regions=("North",)
    )
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        result = adapter.query_metric(query(), context=other_tenant)
    # t2 deliberately reuses t1's o1, i1, and r1 identifiers: $1000 - $50.
    assert [row.value for row in result.rows] == [Decimal("950.00")]


def test_dimension_filters_are_and_across_dimensions_and_or_within_values(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        result = adapter.query_metric(
            query(
                group_by=("region", "channel"),
                filters={"region": ("North", "South"), "channel": ("store",)},
            ),
            context=context,
        )
    assert [(row.dimensions, row.value) for row in result.rows] == [
        ({"region": "South", "channel": "store"}, Decimal("13.00"))
    ]


@pytest.mark.parametrize("dimension", ["product_id", "region); DROP TABLE orders; --"])
def test_ungoverned_dimensions_are_rejected(
    snapshot_dir: Path, context: AuthorizationContext, dimension: str
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        with pytest.raises(InvalidDimensionError):
            adapter.query_metric(query(group_by=(dimension,)), context=context)
        with pytest.raises(InvalidDimensionError):
            adapter.query_metric(query(filters={dimension: ("North",)}), context=context)


def test_filter_and_context_values_are_bound_not_executed(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        injected = adapter.query_metric(
            query(filters={"region": ("North' OR 1=1 --",)}), context=context
        )
        tenant_injection = context.model_copy(update={"tenant_id": "t1' OR 1=1 --"})
        unauthorized = adapter.query_metric(query(), context=tenant_injection)
        still_valid = adapter.query_metric(query(group_by=()), context=context)
    assert injected.rows == ()
    assert unauthorized.rows == ()
    assert still_valid.rows[0].value == Decimal("32.50")


def test_semantic_discovery_matches_governed_catalog_and_authorized_data(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as local:
        adapter: SemanticAdapter = local
        discovered = adapter.discover_metrics(DiscoverMetricsRequest(), context=context)
        searched = adapter.discover_metrics(
            DiscoverMetricsRequest(search="revenue"), context=context
        )
        missing = adapter.discover_metrics(
            DiscoverMetricsRequest(search="unknown metric"), context=context
        )
        described = adapter.describe_metric(
            DescribeMetricRequest(metric_id="net_revenue"), context=context
        )
        dimensions = adapter.discover_dimensions(
            DiscoverDimensionsRequest(metric_id="net_revenue"), context=context
        )
    assert [metric.metric_id for metric in discovered.metrics] == ["net_revenue"]
    assert searched.metrics == discovered.metrics
    assert missing.metrics == ()
    assert described.metric.base_grain == "order_item"
    assert described.metric.time_semantics.refund_attribution == "original_order_date"
    assert {
        dimension.dimension.dimension_id: dimension.values for dimension in dimensions.dimensions
    } == {
        "region": ("North", "South"),
        "channel": ("online", "store"),
    }


def test_all_semantic_methods_deny_empty_region_scope(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    denied = context.model_copy(update={"allowed_regions": ()})
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        with pytest.raises(AuthorizationError):
            adapter.discover_metrics(DiscoverMetricsRequest(), context=denied)
        with pytest.raises(AuthorizationError):
            adapter.describe_metric(DescribeMetricRequest(metric_id="net_revenue"), context=denied)
        with pytest.raises(AuthorizationError):
            adapter.discover_dimensions(
                DiscoverDimensionsRequest(metric_id="net_revenue"), context=denied
            )
        with pytest.raises(AuthorizationError):
            adapter.query_metric(query(), context=denied)


def test_unknown_metrics_are_rejected(snapshot_dir: Path, context: AuthorizationContext) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        with pytest.raises(UnknownMetricError):
            adapter.describe_metric(DescribeMetricRequest(metric_id="made_up"), context=context)
        with pytest.raises(UnknownMetricError):
            adapter.discover_dimensions(
                DiscoverDimensionsRequest(metric_id="made_up"), context=context
            )
        with pytest.raises(UnknownMetricError):
            adapter.query_metric(
                query().model_copy(update={"metric_id": "made_up"}), context=context
            )


def test_missing_table_is_validation_error(snapshot_dir: Path) -> None:
    (snapshot_dir / "refunds.parquet").unlink()
    with pytest.raises(DataValidationError):
        DuckDBSemanticAdapter(snapshot_dir)


def test_money_cannot_be_loaded_from_floating_point_schema(snapshot_dir: Path) -> None:
    with duckdb.connect(":memory:") as connection:
        relation = connection.read_parquet(str(snapshot_dir / "order_items.parquet"))
        relation.project("* REPLACE (unit_price_cents::DOUBLE AS unit_price_cents)").write_parquet(
            str(snapshot_dir / "replacement.parquet")
        )
    (snapshot_dir / "replacement.parquet").replace(snapshot_dir / "order_items.parquet")
    with pytest.raises(DataValidationError):
        DuckDBSemanticAdapter(snapshot_dir)


def test_approved_refund_needs_approval_date(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]]
) -> None:
    refund = list(snapshot_rows["refunds"][0])
    refund[4] = None
    snapshot_rows["refunds"][0] = tuple(refund)
    directory = write_snapshot(tmp_path / "missing-approval", snapshot_rows)
    with pytest.raises(DataValidationError):
        DuckDBSemanticAdapter(directory)
