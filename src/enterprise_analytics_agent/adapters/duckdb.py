"""Governed local snapshot execution; no user-supplied SQL or identity arguments."""

from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import Self, cast

import duckdb

from enterprise_analytics_agent.catalog import NET_REVENUE, MetricSpecification, get_metric
from enterprise_analytics_agent.contracts import (
    AuthorizationContext,
    DescribeMetricRequest,
    DescribeMetricResponse,
    DimensionValues,
    DiscoverDimensionsRequest,
    DiscoverDimensionsResponse,
    DiscoverMetricsRequest,
    DiscoverMetricsResponse,
    MetricRow,
    MetricSummary,
    QueryMetricRequest,
    QueryMetricResponse,
)
from enterprise_analytics_agent.data import BUSINESS_KEYS, TABLE_SCHEMAS
from enterprise_analytics_agent.errors import (
    AuthorizationError,
    DataValidationError,
    InvalidDimensionError,
    SemanticError,
)


def _column(entity: str, field: str, alias: str) -> str:
    """Only trusted catalog fields that exist in the local schema become SQL."""
    if entity not in TABLE_SCHEMAS or field not in dict(TABLE_SCHEMAS[entity]):
        raise DataValidationError(f"Unsupported catalog field: {entity}.{field}")
    return f'{alias}."{field}"'


def _placeholders(values: tuple[str, ...]) -> str:
    if not values:
        raise SemanticError("An empty value set cannot form a governed filter")
    return ", ".join("?" for _ in values)


def _relationship_join(
    metric: MetricSpecification,
    source: str,
    target: str,
    source_alias: str,
    target_alias: str,
) -> str:
    for relationship in metric.relationships:
        if relationship.from_entity == source and relationship.to_entity == target:
            return " AND ".join(
                f"{_column(source, key, source_alias)} = {_column(target, key, target_alias)}"
                for key in relationship.keys
            )
    raise DataValidationError(f"No governed relationship from {source} to {target}")


def _dollars(cents: object) -> Decimal:
    if not isinstance(cents, int):
        raise DataValidationError("Revenue execution did not return integer cents")
    dollars, remainder = divmod(abs(cents), 100)
    # Building an exact decimal string avoids both floats and Decimal context rounding.
    return Decimal(f"{'-' if cents < 0 else ''}{dollars}.{remainder:02d}")


class DuckDBSemanticAdapter:
    """An application-owned, in-memory copy of six trusted Parquet source tables."""

    def __init__(self, data_dir: Path) -> None:
        self._connection = duckdb.connect(":memory:")
        self._closed = False
        try:
            self._load_snapshot(data_dir)
        except (duckdb.Error, OSError) as exc:
            self.close()
            raise DataValidationError("Could not load the local retail snapshot") from exc
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> Self:
        if self._closed:
            raise SemanticError("The adapter is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def _load_snapshot(self, data_dir: Path) -> None:
        for table, expected_schema in TABLE_SCHEMAS.items():
            path = data_dir / f"{table}.parquet"
            if not path.is_file():
                raise DataValidationError(f"Missing source table: {table}.parquet")
            raw = f"_raw_{table}"
            self._connection.read_parquet(str(path)).create_view(raw)
            schema_rows = self._fetch(f"DESCRIBE {raw}")
            actual_schema = {str(row[0]): str(row[1]) for row in schema_rows}
            if actual_schema != dict(expected_schema):
                raise DataValidationError(f"Invalid schema for source table: {table}")
            columns = ", ".join(f'"{name}"' for name, _ in expected_schema)
            self._connection.execute(
                f"CREATE TABLE {table} AS SELECT DISTINCT {columns} FROM {raw}"
            )
            self._connection.execute(f"DROP VIEW {raw}")
            keys = ", ".join(BUSINESS_KEYS[table])
            if self._exists(f"SELECT 1 FROM {table} GROUP BY {keys} HAVING count(*) > 1 LIMIT 1"):
                raise DataValidationError(f"Conflicting duplicate business key in {table}")
            required = [
                name for name, _ in expected_schema if (table, name) != ("refunds", "approved_at")
            ]
            null_predicate = " OR ".join(f'"{name}" IS NULL' for name in required)
            if self._exists(f"SELECT 1 FROM {table} WHERE {null_predicate} LIMIT 1"):
                raise DataValidationError(f"Null required field in {table}")
        self._validate_values()
        self._validate_relationships()

    def _validate_values(self) -> None:
        for table, schema in TABLE_SCHEMAS.items():
            amounts = [name for name, _ in schema if name.endswith("_cents")]
            if amounts:
                negative = " OR ".join(f'"{name}" < 0' for name in amounts)
                if self._exists(f"SELECT 1 FROM {table} WHERE {negative} LIMIT 1"):
                    raise DataValidationError(f"Negative source amount in {table}")
        if self._exists(
            "SELECT 1 FROM order_items WHERE quantity <= 0 OR "
            "discount_cents > CAST(quantity AS HUGEINT) * unit_price_cents LIMIT 1"
        ):
            raise DataValidationError("Invalid item quantity or line discount")
        if self._exists(
            "SELECT 1 FROM refunds WHERE status = 'approved' AND approved_at IS NULL LIMIT 1"
        ):
            raise DataValidationError("Approved refunds require an approval date")

    def _validate_relationships(self) -> None:
        for relationship in NET_REVENUE.relationships:
            source = relationship.from_entity
            target = relationship.to_entity
            join = _relationship_join(NET_REVENUE, source, target, "s", "t")
            if self._exists(
                f"SELECT 1 FROM {source} s WHERE NOT EXISTS "
                f"(SELECT 1 FROM {target} t WHERE {join}) LIMIT 1"
            ):
                raise DataValidationError(f"Broken relationship from {source} to {target}")

    def _fetch(self, sql: str, parameters: list[object] | None = None) -> list[tuple[object, ...]]:
        return cast(
            list[tuple[object, ...]], self._connection.execute(sql, parameters or []).fetchall()
        )

    def _exists(self, sql: str) -> bool:
        return self._connection.execute(sql).fetchone() is not None

    def _authorize(self, context: AuthorizationContext) -> None:
        if self._closed:
            raise SemanticError("The adapter is closed")
        if (
            not context.principal_id.strip()
            or not context.tenant_id.strip()
            or not context.allowed_regions
            or any(not region.strip() for region in context.allowed_regions)
        ):
            raise AuthorizationError("A principal, tenant, and nonempty region scope are required")

    @staticmethod
    def _metric_filters(
        metric: MetricSpecification, entity: str, alias: str
    ) -> tuple[list[str], list[object]]:
        predicates: list[str] = []
        parameters: list[object] = []
        for rule in metric.filters:
            if rule.entity == entity:
                field = _column(entity, rule.field, alias)
                predicates.append(f"{field} IN ({_placeholders(rule.values)})")
                parameters.extend(rule.values)
        return predicates, parameters

    def _order_scope(
        self, metric: MetricSpecification, context: AuthorizationContext
    ) -> tuple[list[str], list[object]]:
        predicates = [
            "o.tenant_id = ?",
            f"o.region IN ({_placeholders(context.allowed_regions)})",
        ]
        parameters: list[object] = [context.tenant_id, *context.allowed_regions]
        filters, values = self._metric_filters(metric, "orders", "o")
        return predicates + filters, parameters + values

    def discover_metrics(
        self, request: DiscoverMetricsRequest, *, context: AuthorizationContext
    ) -> DiscoverMetricsResponse:
        self._authorize(context)
        metric = NET_REVENUE
        haystack = f"{metric.metric_id} {metric.display_name} {metric.description}".casefold()
        if request.search is not None and request.search.casefold() not in haystack:
            return DiscoverMetricsResponse(metrics=())
        summary = MetricSummary(
            metric_id=metric.metric_id,
            display_name=metric.display_name,
            description=metric.description,
            definition_version=metric.definition_version,
        )
        return DiscoverMetricsResponse(metrics=(summary,))

    def describe_metric(
        self, request: DescribeMetricRequest, *, context: AuthorizationContext
    ) -> DescribeMetricResponse:
        self._authorize(context)
        return DescribeMetricResponse(metric=get_metric(request.metric_id).public_description())

    def discover_dimensions(
        self, request: DiscoverDimensionsRequest, *, context: AuthorizationContext
    ) -> DiscoverDimensionsResponse:
        self._authorize(context)
        metric = get_metric(request.metric_id)
        predicates, parameters = self._order_scope(metric, context)
        item_join = _relationship_join(metric, "order_items", "orders", "i", "o")
        predicates.append(f"EXISTS (SELECT 1 FROM order_items i WHERE {item_join})")
        where = " AND ".join(predicates)
        dimensions: list[DimensionValues] = []
        for dimension in metric.dimensions:
            if dimension.entity != "orders":
                raise DataValidationError("This adapter supports order dimensions only")
            field = _column(dimension.entity, dimension.field, "o")
            rows = self._fetch(
                f"SELECT DISTINCT {field} FROM orders o WHERE {where} ORDER BY {field}",
                parameters,
            )
            dimensions.append(
                DimensionValues(
                    dimension=dimension.public_description(),
                    values=tuple(str(row[0]) for row in rows),
                )
            )
        return DiscoverDimensionsResponse(metric_id=metric.metric_id, dimensions=tuple(dimensions))

    def query_metric(
        self, request: QueryMetricRequest, *, context: AuthorizationContext
    ) -> QueryMetricResponse:
        self._authorize(context)
        metric = get_metric(request.metric_id)
        allowed = {dimension.dimension_id: dimension for dimension in metric.dimensions}
        for name in (*request.group_by, *request.dimension_filters):
            if name not in allowed:
                raise InvalidDimensionError(
                    f"Dimension is not allowed for {metric.metric_id}: {name}"
                )
        columns = {
            name: _column(dimension.entity, dimension.field, "o")
            for name, dimension in allowed.items()
        }
        predicates, parameters = self._order_scope(metric, context)
        time_field = _column(metric.time_semantics.entity, metric.time_semantics.field, "o")
        predicates.extend((f"{time_field} >= ?", f"{time_field} < ?"))
        parameters.extend((request.time_range.start, request.time_range.end))
        for name, values in request.dimension_filters.items():
            predicates.append(f"{columns[name]} IN ({_placeholders(values)})")
            parameters.extend(values)

        refund_filters, refund_values = self._metric_filters(metric, "refunds", "r")
        refund_where = " AND ".join(["r.tenant_id = ?", *refund_filters])
        refund_grain = ", ".join(_column("refunds", key, "r") for key in metric.base_grain)
        item_join = _relationship_join(metric, "order_items", "orders", "i", "o")
        refund_join = _relationship_join(metric, "refunds", "order_items", "r", "i")
        group_columns = ", ".join(columns[name] for name in request.group_by)
        select_dimensions = f"{group_columns}, " if group_columns else ""
        group_and_sort = (
            f"GROUP BY {group_columns} ORDER BY {group_columns}" if group_columns else ""
        )
        # Translation of the governed catalog calculation; never evaluate a request expression.
        if metric.calculation != (
            "sum(quantity * unit_price_cents - discount_cents - approved_refund_cents)"
        ):
            raise SemanticError("The metric calculation is not supported by this adapter")
        sql = f"""
            WITH approved_refunds AS (
                SELECT {refund_grain},
                       SUM(CAST(r.amount_cents AS HUGEINT)) AS approved_refund_cents
                FROM refunds r
                WHERE {refund_where}
                GROUP BY {refund_grain}
            )
            SELECT {select_dimensions}
                   COALESCE(SUM(CAST(i.quantity AS HUGEINT) * i.unit_price_cents
                                - i.discount_cents
                                - COALESCE(r.approved_refund_cents, 0)), 0) AS net_revenue_cents
            FROM orders o
            JOIN order_items i ON {item_join}
            LEFT JOIN approved_refunds r ON {refund_join}
            WHERE {" AND ".join(predicates)}
            {group_and_sort}
        """
        results = self._fetch(sql, [context.tenant_id, *refund_values, *parameters])
        rows = tuple(
            MetricRow(
                dimensions={
                    name: str(value) for name, value in zip(request.group_by, row[:-1], strict=True)
                },
                value=_dollars(row[-1]),
            )
            for row in results
        )
        return QueryMetricResponse(
            metric_id=metric.metric_id,
            definition_version=metric.definition_version,
            time_range=request.time_range,
            group_by=request.group_by,
            unit=metric.unit,
            currency=metric.currency,
            rows=rows,
        )
