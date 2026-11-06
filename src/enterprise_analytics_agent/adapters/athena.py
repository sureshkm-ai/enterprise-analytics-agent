"""Governed Athena SQL execution behind the existing provider-independent interface."""

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import cast, overload
from urllib.parse import urlsplit

from enterprise_analytics_agent.adapters.athena_execution import (
    AthenaClient,
    AthenaDiagnostic,
    AthenaExecutor,
)
from enterprise_analytics_agent.adapters.aws_schema import glue_table_name
from enterprise_analytics_agent.catalog import MetricSpecification, get_metric, get_metrics
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
from enterprise_analytics_agent.data import OPTIONAL_TABLE_SCHEMAS, TABLE_SCHEMAS
from enterprise_analytics_agent.errors import (
    AuthorizationError,
    DataValidationError,
    InvalidDimensionError,
    MissingMetricDataError,
    SemanticError,
)
from enterprise_analytics_agent.snapshots import SnapshotManifest

_STORAGE_SCHEMAS = {**TABLE_SCHEMAS, **OPTIONAL_TABLE_SCHEMAS}
_NET = "sum(quantity * unit_price_cents - discount_cents - approved_refund_cents)"
_GROSS = "sum(quantity * unit_price_cents)"
_COUNT = "count_distinct_eligible_orders"
_AVERAGE = "aggregate_net_revenue / aggregate_order_count"
_RETURN = "returned_order_count / aggregate_order_count"
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,199}\Z", re.ASCII)


type QueryRequest = QueryMetricRequest | QueryMetricRequestV2


@dataclass(frozen=True)
class AthenaConfig:
    """Trusted application configuration; none of these fields are tool arguments."""

    profile: str
    region: str
    database: str
    workgroup: str
    output_location: str
    expected_bucket_owner: str
    table_prefix: str = "ea"
    timeout_seconds: float = 120.0
    poll_seconds: float = 0.25
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if not self.profile.strip() or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", self.region):
            raise ValueError("An explicit AWS profile and region are required")
        if (
            not _IDENTIFIER.fullmatch(self.database)
            or not _IDENTIFIER.fullmatch(self.table_prefix)
            or len(self.table_prefix) > 31
        ):
            raise ValueError("Database and table prefix must be safe lowercase SQL identifiers")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", self.workgroup):
            raise ValueError("Invalid Athena workgroup name")
        if not re.fullmatch(r"\d{12}", self.expected_bucket_owner, flags=re.ASCII):
            raise ValueError("An explicit 12-digit expected bucket owner is required")
        location = urlsplit(self.output_location)
        if (
            location.scheme != "s3"
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", location.netloc)
            or location.query
            or location.fragment
            or not location.path.endswith("/")
            or any(ord(character) <= 32 for character in self.output_location)
        ):
            raise ValueError("A full S3 query-results prefix ending in '/' is required")
        if (
            not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or not math.isfinite(self.poll_seconds)
            or self.poll_seconds <= 0
            or type(self.max_attempts) is not int
            or not 1 <= self.max_attempts <= 10
        ):
            raise ValueError("Positive finite deadlines, polling and 1-10 attempts are required")


def _column(entity: str, field: str, alias: str) -> str:
    if entity not in _STORAGE_SCHEMAS or field not in dict(_STORAGE_SCHEMAS[entity]):
        raise DataValidationError(f"Unsupported governed field: {entity}.{field}")
    return f'{alias}."{field}"'


def _placeholders(values: tuple[str, ...]) -> str:
    if not values:
        raise SemanticError("An empty value set cannot form a governed filter")
    return ", ".join("?" for _ in values)


def _relationship(
    metric: MetricSpecification, source: str, target: str, source_alias: str, target_alias: str
) -> str:
    for relationship in metric.relationships:
        if relationship.from_entity == source and relationship.to_entity == target:
            return " AND ".join(
                f"{_column(source, key, source_alias)} = {_column(target, key, target_alias)}"
                for key in relationship.keys
            )
    raise DataValidationError(f"No governed relationship from {source} to {target}")


def _integer(value: object) -> int:
    # Athena DECIMAL(38,0) sums arrive as Decimal. Convert only integral finite
    # values and never use Decimal arithmetic or the caller's Decimal context.
    if type(value) is int:
        return value
    if isinstance(value, Decimal) and value.is_finite() and value == int(value):
        return int(value)
    raise DataValidationError("Athena metric aggregate must be an exact integer")


def _decimal(numerator: int, denominator: int, places: int) -> Decimal | None:
    if denominator == 0:
        return None
    if denominator < 0:
        raise DataValidationError("Metric denominators cannot be negative")
    scale = 10**places
    rounded, remainder = divmod(abs(numerator) * scale, denominator)
    if remainder * 2 >= denominator:
        rounded += 1
    whole, fraction = divmod(rounded, scale)
    sign = "-" if numerator < 0 and rounded else ""
    return Decimal(f"{sign}{whole}.{fraction:0{places}d}")


class AthenaSemanticAdapter:
    """An application-enforced tenant/region filter, not database row security.

    Only ready, prevalidated immutable snapshots are accepted. The deployment's
    Glue tables must point to that exact version; publication verifies this before
    publishing its ready manifest. No AWS calls occur on construction or import.
    """

    def __init__(
        self,
        config: AthenaConfig,
        manifest: SnapshotManifest,
        *,
        client: AthenaClient,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if manifest.state != "ready":
            raise DataValidationError("Athena requires a ready snapshot manifest")
        if set(manifest.tables) - _STORAGE_SCHEMAS.keys():
            raise DataValidationError("Snapshot contains an unknown governed source table")
        if set(TABLE_SCHEMAS) - manifest.tables.keys():
            raise DataValidationError("Snapshot manifest lacks a required retail source table")
        for table, entry in manifest.tables.items():
            schema = tuple((column.name, column.type) for column in entry.columns)
            if schema != _STORAGE_SCHEMAS[table]:
                raise DataValidationError(f"Snapshot manifest has an invalid schema for {table}")
        self.config = config
        self.manifest = manifest.model_copy(deep=True)
        self._executor = AthenaExecutor(
            client,
            database=config.database,
            workgroup=config.workgroup,
            output_location=config.output_location,
            expected_bucket_owner=config.expected_bucket_owner,
            timeout_seconds=config.timeout_seconds,
            poll_seconds=config.poll_seconds,
            max_attempts=config.max_attempts,
            clock=clock,
            sleep=sleep,
        )

    @classmethod
    def from_profile(
        cls, config: AthenaConfig, manifest: SnapshotManifest
    ) -> "AthenaSemanticAdapter":
        """Verify the explicit profile's account before creating an Athena client.

        The read-only STS identity check prevents using same-named catalog or
        workgroup resources in an unintended account. Botocore retries are disabled
        because the bounded executor owns query retries; finite socket timeouts
        bound both the identity check and subsequent in-flight SDK requests.
        """
        import boto3
        from botocore.config import Config

        session = boto3.Session(profile_name=config.profile, region_name=config.region)
        sdk_config = Config(
            connect_timeout=min(5.0, config.timeout_seconds),
            read_timeout=min(10.0, config.timeout_seconds),
            retries={"total_max_attempts": 1, "mode": "standard"},
        )
        identity = session.client("sts", config=sdk_config).get_caller_identity()
        if identity["Account"] != config.expected_bucket_owner:
            raise AuthorizationError("Selected AWS profile resolves to a different account")
        client = session.client("athena", config=sdk_config)
        return cls(config, manifest, client=cast(AthenaClient, client))

    @property
    def diagnostics(self) -> tuple[AthenaDiagnostic, ...]:
        return tuple(self._executor.diagnostics)

    @staticmethod
    def _authorize(context: AuthorizationContext) -> None:
        if (
            not context.principal_id.strip()
            or not context.tenant_id.strip()
            or not context.allowed_regions
            or any(not region.strip() for region in context.allowed_regions)
        ):
            raise AuthorizationError("A principal, tenant and nonempty region scope are required")

    @staticmethod
    def _filters(
        metric: MetricSpecification, entity: str, alias: str
    ) -> tuple[list[str], list[object]]:
        predicates: list[str] = []
        parameters: list[object] = []
        for rule in metric.filters:
            if rule.entity == entity:
                predicates.append(
                    f"{_column(entity, rule.field, alias)} IN ({_placeholders(rule.values)})"
                )
                parameters.extend(rule.values)
        return predicates, parameters

    def _scope(
        self, metric: MetricSpecification, context: AuthorizationContext
    ) -> tuple[list[str], list[object]]:
        filters, values = self._filters(metric, "orders", "o")
        return [
            "o.tenant_id = ?",
            f"o.region IN ({_placeholders(context.allowed_regions)})",
            *filters,
        ], [context.tenant_id, *context.allowed_regions, *values]

    def _sources(
        self, tables: tuple[str, ...], context: AuthorizationContext
    ) -> tuple[list[str], list[object]]:
        ctes: list[str] = []
        for table in tables:
            if table not in self.manifest.tables:
                raise MissingMetricDataError(f"Snapshot requires source data: {table}.parquet")
            columns = ", ".join(f'"{name}"' for name, _ in _STORAGE_SCHEMAS[table])
            name = glue_table_name(
                self.manifest.dataset_version, table, prefix=self.config.table_prefix
            )
            if not _IDENTIFIER.fullmatch(name):
                raise DataValidationError("Invalid governed table identifier")
            ctes.append(
                f"{table} AS (SELECT DISTINCT {columns} "
                f'FROM "{self.config.database}"."{name}" WHERE tenant_id = ?)'
            )
        return ctes, [context.tenant_id] * len(tables)

    def _execute(
        self, sql: str, parameters: list[object], metric: MetricSpecification, operation: str
    ) -> list[tuple[object, ...]]:
        return self._executor.execute(
            sql,
            parameters,
            operation=operation,
            metric_id=metric.metric_id,
            metric_version=metric.definition_version,
            dataset_version=self.manifest.dataset_version,
        )

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
        metrics = tuple(
            metric
            for metric in get_metrics(request.api_version)
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
                    for metric in metrics
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
                for metric in metrics
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
        # Metadata discovery does not require refund/return data, matching DuckDB.
        sources, source_values = self._sources(("orders", "order_items"), context)
        predicates, parameters = self._scope(metric, context)
        join = _relationship(metric, "order_items", "orders", "i", "o")
        predicates.append(f"EXISTS (SELECT 1 FROM order_items i WHERE {join})")
        dimensions: list[DimensionValues] = []
        dimensions_v2: list[DimensionValuesV2] = []
        for dimension in metric.dimensions:
            if dimension.entity != "orders":
                raise DataValidationError("This adapter supports governed order dimensions only")
            field = _column(dimension.entity, dimension.field, "o")
            sql = (
                f'WITH {", ".join(sources)} SELECT DISTINCT {field} AS "dimension_value" '
                f"FROM orders o WHERE {' AND '.join(predicates)} ORDER BY {field}"
            )
            rows = self._execute(sql, [*source_values, *parameters], metric, "discover_dimensions")
            if any(len(row) != 1 or not isinstance(row[0], str) for row in rows):
                raise DataValidationError("Athena dimensions must contain one nonnull string")
            values = tuple(str(row[0]) for row in rows)
            if isinstance(request, DiscoverDimensionsRequestV2):
                dimensions_v2.append(
                    DimensionValuesV2(dimension=dimension.public_description_v2(), values=values)
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
        missing = set(metric.required_sources) - self.manifest.tables.keys()
        if missing:
            names = ", ".join(f"{table}.parquet" for table in sorted(missing))
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
        predicates, parameters = self._scope(metric, context)
        time_column = _column(metric.time_semantics.entity, metric.time_semantics.field, "o")
        predicates.extend((f"{time_column} >= ?", f"{time_column} < ?"))
        parameters.extend((request.time_range.start, request.time_range.end))
        for name, values in request.dimension_filters.items():
            predicates.append(f"{columns[name]} IN ({_placeholders(values)})")
            parameters.extend(values)
        rows = self._aggregate(metric, request, columns, predicates, parameters, context)
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
                        dimensions=self._dimensions(request, row), value=self._value(metric, row)
                    )
                    for row in rows
                ),
            )
        return QueryMetricResponse(
            metric_id=metric.metric_id,
            definition_version=metric.definition_version,
            time_range=request.time_range,
            group_by=request.group_by,
            rows=tuple(
                MetricRow(
                    dimensions=self._dimensions(request, row),
                    value=cast(Decimal, self._value(metric, row)),
                )
                for row in rows
            ),
        )

    @staticmethod
    def _dimensions(request: QueryRequest, row: tuple[object, ...]) -> dict[str, str]:
        if len(row) != len(request.group_by) + 4:
            raise DataValidationError("Athena returned an invalid metric result column count")
        if any(not isinstance(value, str) for value in row[:-4]):
            raise DataValidationError("Athena returned a null or invalid grouping dimension")
        return {name: str(value) for name, value in zip(request.group_by, row[:-4], strict=True)}

    @staticmethod
    def _value(metric: MetricSpecification, row: tuple[object, ...]) -> Decimal | int | None:
        gross, net, orders, returned = map(_integer, row[-4:])
        if orders < 0 or not 0 <= returned <= orders:
            raise DataValidationError("Athena returned invalid aggregate order counts")
        if metric.calculation == _GROSS:
            return _decimal(gross, 100, 2)
        if metric.calculation == _NET:
            return _decimal(net, 100, 2)
        if metric.calculation == _COUNT:
            return orders
        if metric.rounding != "ROUND_HALF_UP":
            raise SemanticError("Unsupported metric rounding policy")
        if metric.calculation == _AVERAGE:
            return _decimal(net, orders * 100, metric.decimal_places)
        if metric.calculation == _RETURN:
            return _decimal(returned, orders, metric.decimal_places)
        raise SemanticError("Unsupported governed metric calculation")

    def _aggregate(
        self,
        metric: MetricSpecification,
        request: QueryRequest,
        columns: dict[str, str],
        predicates: list[str],
        parameters: list[object],
        context: AuthorizationContext,
    ) -> list[tuple[object, ...]]:
        if metric.calculation not in {_NET, _GROSS, _COUNT, _AVERAGE, _RETURN}:
            raise SemanticError("Unsupported governed metric calculation")
        ctes, source_parameters = self._sources(metric.required_sources, context)
        joins: list[str] = []
        refund_amount = "CAST(0 AS DECIMAL(38,0))"
        returned_flag = "0"
        if metric.calculation in (_NET, _AVERAGE):
            filters, values = self._filters(metric, "refunds", "r")
            keys = next(
                relationship.keys
                for relationship in metric.relationships
                if relationship.from_entity == "refunds" and relationship.to_entity == "order_items"
            )
            grain = ", ".join(_column("refunds", key, "r") for key in keys)
            ctes.append(
                f"""approved_refunds AS (
                    SELECT {grain}, SUM(CAST(r.amount_cents AS DECIMAL(38,0)))
                        AS approved_refund_cents
                    FROM refunds r WHERE r.tenant_id = ? AND {" AND ".join(filters)}
                    GROUP BY {grain})"""
            )
            source_parameters.extend((context.tenant_id, *values))
            join = _relationship(metric, "refunds", "order_items", "r", "i")
            joins.append(f"LEFT JOIN approved_refunds r ON {join}")
            refund_amount = "COALESCE(r.approved_refund_cents, CAST(0 AS DECIMAL(38,0)))"
        if metric.calculation == _RETURN:
            filters, values = self._filters(metric, "returns", "r")
            join = _relationship(metric, "returns", "order_items", "r", "ri")
            ctes.append(
                f"""returned_orders AS (
                    SELECT DISTINCT r.tenant_id, ri.order_id, 1 AS has_return
                    FROM returns r JOIN order_items ri ON {join}
                    WHERE r.tenant_id = ? AND {" AND ".join(filters)})"""
            )
            source_parameters.extend((context.tenant_id, *values))
            joins.append(
                "LEFT JOIN returned_orders ro "
                "ON ro.tenant_id = o.tenant_id AND ro.order_id = o.order_id"
            )
            returned_flag = "COALESCE(ro.has_return, 0)"
        item_join = _relationship(metric, "order_items", "orders", "i", "o")
        fields = ", ".join(columns[name] for name in request.group_by)
        aliases = ", ".join(f'{columns[name]} AS "{name}"' for name in request.group_by)
        output = ", ".join(f'v."{name}"' for name in request.group_by)
        order_dimensions = f"{aliases}, " if aliases else ""
        order_group = f", {fields}" if fields else ""
        output_dimensions = f"{output}, " if output else ""
        final_group = f"GROUP BY {output} ORDER BY {output}" if output else ""
        # All financial operands and sums are DECIMAL(38,0), never BIGINT
        # multiplication, DuckDB HUGEINT, floating point or SQL ratio arithmetic.
        gross = "CAST(i.quantity AS DECIMAL(38,0)) * CAST(i.unit_price_cents AS DECIMAL(38,0))"
        ctes.append(
            f"""order_values AS (
                SELECT {order_dimensions}o.tenant_id, o.order_id,
                    SUM({gross}) AS gross_cents,
                    SUM({gross} - CAST(i.discount_cents AS DECIMAL(38,0))
                        - {refund_amount}) AS net_cents,
                    MAX({returned_flag}) AS has_return
                FROM orders o JOIN order_items i ON {item_join}
                {" ".join(joins)} WHERE {" AND ".join(predicates)}
                GROUP BY o.tenant_id, o.order_id{order_group})"""
        )
        sql = f"""WITH {", ".join(ctes)}
            SELECT {output_dimensions}
                COALESCE(SUM(v.gross_cents), CAST(0 AS DECIMAL(38,0))) AS gross_cents,
                COALESCE(SUM(v.net_cents), CAST(0 AS DECIMAL(38,0))) AS net_cents,
                COUNT(*) AS order_count,
                COALESCE(SUM(v.has_return), 0) AS returned_order_count
            FROM order_values v {final_group}"""
        return self._execute(sql, [*source_parameters, *parameters], metric, "query_metric")
