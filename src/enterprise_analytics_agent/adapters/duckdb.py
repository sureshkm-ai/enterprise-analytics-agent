"""Governed local snapshot execution; no user-supplied SQL or identity arguments."""

from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import Self, cast, overload

import duckdb

from enterprise_analytics_agent.catalog import (
    NET_REVENUE,
    MetricSpecification,
    get_metric,
    get_metrics,
)
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
from enterprise_analytics_agent.contracts_v2 import (
    DescribeMetricRequestV2,
    DescribeMetricResponseV2,
    DimensionDefinitionV2,
    DimensionValuesV2,
    DiscoverDimensionsRequestV2,
    DiscoverDimensionsResponseV2,
    DiscoverMetricsRequestV2,
    DiscoverMetricsResponseV2,
    MetricRowV2,
    MetricSummaryV2,
    QueryMetricRequestV2,
    QueryMetricResponseV2,
)
from enterprise_analytics_agent.data import (
    BUSINESS_KEYS,
    OPTIONAL_BUSINESS_KEYS,
    OPTIONAL_TABLE_SCHEMAS,
    TABLE_SCHEMAS,
)
from enterprise_analytics_agent.errors import (
    AuthorizationError,
    DataValidationError,
    InvalidDimensionError,
    MissingMetricDataError,
    SemanticError,
)

_STORAGE_SCHEMAS = {**TABLE_SCHEMAS, **OPTIONAL_TABLE_SCHEMAS}
_STORAGE_KEYS = {**BUSINESS_KEYS, **OPTIONAL_BUSINESS_KEYS}
_NET_CALCULATION = "sum(quantity * unit_price_cents - discount_cents - approved_refund_cents)"
_GROSS_CALCULATION = "sum(quantity * unit_price_cents)"
_COUNT_CALCULATION = "count_distinct_eligible_orders"
_AVERAGE_CALCULATION = "aggregate_net_revenue / aggregate_order_count"
_RETURN_CALCULATION = "returned_order_count / aggregate_order_count"

type QueryRequest = QueryMetricRequest | QueryMetricRequestV2


def _column(entity: str, field: str, alias: str) -> str:
    """Only trusted catalog fields that exist in the local schema become SQL."""
    if entity not in _STORAGE_SCHEMAS or field not in dict(_STORAGE_SCHEMAS[entity]):
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


def _integer(value: object) -> int:
    if type(value) is not int:
        raise DataValidationError("Metric execution did not return an integer aggregate")
    return value


def _rounded_ratio(numerator: int, denominator: int, places: int) -> Decimal | None:
    """Round an exact rational with ROUND_HALF_UP, independently of Decimal context."""
    if denominator == 0:
        return None
    if denominator < 0:
        raise DataValidationError("A metric denominator cannot be negative")
    scale = 10**places
    rounded, remainder = divmod(abs(numerator) * scale, denominator)
    if remainder * 2 >= denominator:
        rounded += 1
    whole, fraction = divmod(rounded, scale)
    sign = "-" if numerator < 0 and rounded else ""
    if places == 0:
        return Decimal(f"{sign}{whole}")
    return Decimal(f"{sign}{whole}.{fraction:0{places}d}")


class DuckDBSemanticAdapter:
    """An application-owned retail snapshot with optional physical-return events."""

    def __init__(self, data_dir: Path) -> None:
        self._connection = duckdb.connect(":memory:")
        self._closed = False
        self._loaded_tables: set[str] = set()
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
        for table, expected_schema in _STORAGE_SCHEMAS.items():
            path = data_dir / f"{table}.parquet"
            if not path.is_file():
                if table in OPTIONAL_TABLE_SCHEMAS:
                    continue
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
            keys = ", ".join(_STORAGE_KEYS[table])
            if self._exists(f"SELECT 1 FROM {table} GROUP BY {keys} HAVING count(*) > 1 LIMIT 1"):
                raise DataValidationError(f"Conflicting duplicate business key in {table}")
            required = [
                name
                for name, _ in expected_schema
                if (table, name) not in (("refunds", "approved_at"), ("returns", "received_at"))
            ]
            null_predicate = " OR ".join(f'"{name}" IS NULL' for name in required)
            if self._exists(f"SELECT 1 FROM {table} WHERE {null_predicate} LIMIT 1"):
                raise DataValidationError(f"Null required field in {table}")
            self._loaded_tables.add(table)
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
        if "returns" in self._loaded_tables:
            self._validate_returns()

    def _validate_returns(self) -> None:
        if self._exists(
            "SELECT 1 FROM returns WHERE quantity <= 0 "
            "OR status NOT IN ('received', 'pending', 'rejected') "
            "OR trim(tenant_id) = '' OR trim(return_id) = '' OR trim(order_item_id) = '' LIMIT 1"
        ):
            raise DataValidationError("Invalid physical return quantity, status, or identifier")
        metric = get_metric("return_rate", api_version="v2")
        filters, parameters = self._metric_filters(metric, "returns", "r")
        if self._exists(
            "SELECT 1 FROM returns r WHERE "
            f"{' AND '.join(filters)} AND r.received_at IS NULL LIMIT 1",
            parameters,
        ):
            raise DataValidationError("Received physical returns require a received date")
        join = _relationship_join(metric, "returns", "order_items", "r", "i")
        if self._exists(
            f"SELECT 1 FROM returns r JOIN order_items i ON {join} "
            "WHERE r.quantity > i.quantity LIMIT 1"
        ):
            raise DataValidationError("Physical return quantity exceeds purchased item quantity")

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
        if "returns" in self._loaded_tables:
            metric = get_metric("return_rate", api_version="v2")
            join = _relationship_join(metric, "returns", "order_items", "r", "i")
            if self._exists(
                "SELECT 1 FROM returns r WHERE NOT EXISTS "
                f"(SELECT 1 FROM order_items i WHERE {join}) LIMIT 1"
            ):
                raise DataValidationError("Broken relationship from returns to order_items")

    def _fetch(self, sql: str, parameters: list[object] | None = None) -> list[tuple[object, ...]]:
        return cast(
            list[tuple[object, ...]], self._connection.execute(sql, parameters or []).fetchall()
        )

    def _exists(self, sql: str, parameters: list[object] | None = None) -> bool:
        return self._connection.execute(sql, parameters or []).fetchone() is not None

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

    @overload
    def discover_metrics(
        self, request: DiscoverMetricsRequest, *, context: AuthorizationContext
    ) -> DiscoverMetricsResponse: ...

    @overload
    def discover_metrics(
        self, request: DiscoverMetricsRequestV2, *, context: AuthorizationContext
    ) -> DiscoverMetricsResponseV2: ...

    def discover_metrics(
        self,
        request: DiscoverMetricsRequest | DiscoverMetricsRequestV2,
        *,
        context: AuthorizationContext,
    ) -> DiscoverMetricsResponse | DiscoverMetricsResponseV2:
        self._authorize(context)
        metrics = get_metrics(request.api_version)
        matched = tuple(
            metric
            for metric in metrics
            if request.search is None
            or request.search.casefold()
            in f"{metric.metric_id} {metric.display_name} {metric.description}".casefold()
        )
        if isinstance(request, DiscoverMetricsRequestV2):
            return DiscoverMetricsResponseV2(
                metrics=tuple(
                    MetricSummaryV2(
                        metric_id=metric.metric_id,
                        display_name=metric.display_name,
                        description=metric.description,
                        definition_version=metric.definition_version,
                    )
                    for metric in matched
                )
            )
        return DiscoverMetricsResponse(
            metrics=tuple(
                MetricSummary(
                    metric_id=metric.metric_id,
                    display_name=metric.display_name,
                    description=metric.description,
                    definition_version=metric.definition_version,
                )
                for metric in matched
            )
        )

    @overload
    def describe_metric(
        self, request: DescribeMetricRequest, *, context: AuthorizationContext
    ) -> DescribeMetricResponse: ...

    @overload
    def describe_metric(
        self, request: DescribeMetricRequestV2, *, context: AuthorizationContext
    ) -> DescribeMetricResponseV2: ...

    def describe_metric(
        self,
        request: DescribeMetricRequest | DescribeMetricRequestV2,
        *,
        context: AuthorizationContext,
    ) -> DescribeMetricResponse | DescribeMetricResponseV2:
        self._authorize(context)
        metric = get_metric(request.metric_id, api_version=request.api_version)
        if isinstance(request, DescribeMetricRequestV2):
            return DescribeMetricResponseV2(metric=metric.public_description_v2())
        return DescribeMetricResponse(metric=metric.public_description())

    @overload
    def discover_dimensions(
        self, request: DiscoverDimensionsRequest, *, context: AuthorizationContext
    ) -> DiscoverDimensionsResponse: ...

    @overload
    def discover_dimensions(
        self, request: DiscoverDimensionsRequestV2, *, context: AuthorizationContext
    ) -> DiscoverDimensionsResponseV2: ...

    def discover_dimensions(
        self,
        request: DiscoverDimensionsRequest | DiscoverDimensionsRequestV2,
        *,
        context: AuthorizationContext,
    ) -> DiscoverDimensionsResponse | DiscoverDimensionsResponseV2:
        self._authorize(context)
        metric = get_metric(request.metric_id, api_version=request.api_version)
        predicates, parameters = self._order_scope(metric, context)
        item_join = _relationship_join(metric, "order_items", "orders", "i", "o")
        predicates.append(f"EXISTS (SELECT 1 FROM order_items i WHERE {item_join})")
        where = " AND ".join(predicates)
        dimensions: list[DimensionValues] = []
        dimensions_v2: list[DimensionValuesV2] = []
        for dimension in metric.dimensions:
            if dimension.entity != "orders":
                raise DataValidationError("This adapter supports order dimensions only")
            field = _column(dimension.entity, dimension.field, "o")
            rows = self._fetch(
                f"SELECT DISTINCT {field} FROM orders o WHERE {where} ORDER BY {field}",
                parameters,
            )
            values = tuple(str(row[0]) for row in rows)
            if isinstance(request, DiscoverDimensionsRequestV2):
                dimensions_v2.append(
                    DimensionValuesV2(
                        dimension=DimensionDefinitionV2(
                            dimension_id=dimension.dimension_id,
                            description=dimension.description,
                        ),
                        values=values,
                    )
                )
            else:
                dimensions.append(
                    DimensionValues(dimension=dimension.public_description(), values=values)
                )
        if isinstance(request, DiscoverDimensionsRequestV2):
            return DiscoverDimensionsResponseV2(
                metric_id=metric.metric_id, dimensions=tuple(dimensions_v2)
            )
        return DiscoverDimensionsResponse(metric_id=metric.metric_id, dimensions=tuple(dimensions))

    @overload
    def query_metric(
        self, request: QueryMetricRequest, *, context: AuthorizationContext
    ) -> QueryMetricResponse: ...

    @overload
    def query_metric(
        self, request: QueryMetricRequestV2, *, context: AuthorizationContext
    ) -> QueryMetricResponseV2: ...

    def query_metric(
        self, request: QueryRequest, *, context: AuthorizationContext
    ) -> QueryMetricResponse | QueryMetricResponseV2:
        self._authorize(context)
        metric = get_metric(request.metric_id, api_version=request.api_version)
        missing = set(metric.required_sources) - self._loaded_tables
        if missing:
            names = ", ".join(f"{name}.parquet" for name in sorted(missing))
            raise MissingMetricDataError(f"Metric {metric.metric_id} requires source data: {names}")
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
        results = self._aggregate(metric, request, columns, predicates, parameters, context)
        if isinstance(request, QueryMetricRequestV2):
            return QueryMetricResponseV2(
                metric_id=metric.metric_id,
                definition_version=metric.definition_version,
                time_range=request.time_range,
                group_by=request.group_by,
                unit=metric.unit,
                currency=metric.currency,
                rows=tuple(
                    MetricRowV2(
                        dimensions=self._row_dimensions(request, row),
                        value=self._metric_value(metric, row),
                    )
                    for row in results
                ),
            )
        # V1 is deliberately limited to unchanged net-revenue money responses.
        return QueryMetricResponse(
            metric_id=metric.metric_id,
            definition_version=metric.definition_version,
            time_range=request.time_range,
            group_by=request.group_by,
            unit="currency",
            currency="USD",
            rows=tuple(
                MetricRow(dimensions=self._row_dimensions(request, row), value=_dollars(row[-3]))
                for row in results
            ),
        )

    @staticmethod
    def _row_dimensions(request: QueryRequest, row: tuple[object, ...]) -> dict[str, str]:
        return {name: str(value) for name, value in zip(request.group_by, row[:-4], strict=True)}

    @staticmethod
    def _metric_value(metric: MetricSpecification, row: tuple[object, ...]) -> Decimal | int | None:
        gross, net, orders, returned = map(_integer, row[-4:])
        if metric.calculation == _GROSS_CALCULATION:
            return _dollars(gross)
        if metric.calculation == _NET_CALCULATION:
            return _dollars(net)
        if metric.calculation == _COUNT_CALCULATION:
            return orders
        if metric.rounding != "ROUND_HALF_UP":
            raise SemanticError("The metric rounding policy is not supported by this adapter")
        if metric.calculation == _AVERAGE_CALCULATION:
            return _rounded_ratio(net, orders * 100, metric.decimal_places)
        if metric.calculation == _RETURN_CALCULATION:
            return _rounded_ratio(returned, orders, metric.decimal_places)
        raise SemanticError("The metric calculation is not supported by this adapter")

    def _aggregate(
        self,
        metric: MetricSpecification,
        request: QueryRequest,
        columns: dict[str, str],
        predicates: list[str],
        parameters: list[object],
        context: AuthorizationContext,
    ) -> list[tuple[object, ...]]:
        """Build integer order facts first; aggregate requested groups only afterward."""
        supported = {
            _NET_CALCULATION,
            _GROSS_CALCULATION,
            _COUNT_CALCULATION,
            _AVERAGE_CALCULATION,
            _RETURN_CALCULATION,
        }
        if metric.calculation not in supported:
            raise SemanticError("The metric calculation is not supported by this adapter")
        needs_net = metric.calculation in (_NET_CALCULATION, _AVERAGE_CALCULATION)
        needs_returns = metric.calculation == _RETURN_CALCULATION
        item_join = _relationship_join(metric, "order_items", "orders", "i", "o")
        ctes: list[str] = []
        source_parameters: list[object] = []
        joins: list[str] = []
        refund_amount = "0"
        returned_flag = "0"
        if needs_net:
            filters, values = self._metric_filters(metric, "refunds", "r")
            refund_join = _relationship_join(metric, "refunds", "order_items", "r", "i")
            refund_keys = next(
                relationship.keys
                for relationship in metric.relationships
                if relationship.from_entity == "refunds" and relationship.to_entity == "order_items"
            )
            grain = ", ".join(_column("refunds", key, "r") for key in refund_keys)
            ctes.append(
                f"""approved_refunds AS (
                    SELECT {grain}, SUM(CAST(r.amount_cents AS HUGEINT)) AS approved_refund_cents
                    FROM refunds r
                    WHERE r.tenant_id = ? AND {" AND ".join(filters)}
                    GROUP BY {grain}
                )"""
            )
            source_parameters.extend((context.tenant_id, *values))
            joins.append(f"LEFT JOIN approved_refunds r ON {refund_join}")
            refund_amount = "COALESCE(r.approved_refund_cents, 0)"
        if needs_returns:
            filters, values = self._metric_filters(metric, "returns", "r")
            return_join = _relationship_join(metric, "returns", "order_items", "r", "ri")
            ctes.append(
                f"""returned_orders AS (
                    SELECT DISTINCT r.tenant_id, ri.order_id, 1 AS has_return
                    FROM returns r JOIN order_items ri ON {return_join}
                    WHERE r.tenant_id = ? AND {" AND ".join(filters)}
                )"""
            )
            source_parameters.extend((context.tenant_id, *values))
            joins.append(
                "LEFT JOIN returned_orders ro "
                "ON ro.tenant_id = o.tenant_id AND ro.order_id = o.order_id"
            )
            returned_flag = "COALESCE(ro.has_return, 0)"
        group_fields = ", ".join(columns[name] for name in request.group_by)
        output_fields = ", ".join(f'v."{name}"' for name in request.group_by)
        output_selected = f"{output_fields}, " if output_fields else ""
        aliases = ", ".join(f'{columns[name]} AS "{name}"' for name in request.group_by)
        order_dimensions = f"{aliases}, " if aliases else ""
        order_groups = f", {group_fields}" if group_fields else ""
        final_group = f"GROUP BY {output_fields} ORDER BY {output_fields}" if output_fields else ""
        ctes.append(
            f"""order_values AS (
                SELECT {order_dimensions}o.tenant_id, o.order_id,
                       SUM(CAST(i.quantity AS HUGEINT) * i.unit_price_cents) AS gross_cents,
                       SUM(CAST(i.quantity AS HUGEINT) * i.unit_price_cents
                           - i.discount_cents - {refund_amount}) AS net_cents,
                       MAX({returned_flag}) AS has_return
                FROM orders o JOIN order_items i ON {item_join}
                {" ".join(joins)}
                WHERE {" AND ".join(predicates)}
                GROUP BY o.tenant_id, o.order_id{order_groups}
            )"""
        )
        sql = f"""
            WITH {", ".join(ctes)}
            SELECT {output_selected}
                   COALESCE(SUM(v.gross_cents), 0),
                   COALESCE(SUM(v.net_cents), 0),
                   COUNT(*),
                   COALESCE(SUM(v.has_return), 0)
            FROM order_values v
            {final_group}
        """
        return self._fetch(sql, [*source_parameters, *parameters])
