"""Governed, backend-independent metric definitions, rather than user formulas."""

from dataclasses import dataclass, replace
from typing import Literal

from enterprise_analytics_agent.contracts import (
    DimensionDefinition,
    MetricDefinition,
    MetricFilter,
    TimeSemantics,
)
from enterprise_analytics_agent.contracts_v2 import (
    DimensionDefinitionV2,
    MetricDefinitionV2,
    MetricFilterV2,
    MetricGrain,
    MetricPrecision,
    MetricUnit,
    TimeSemanticsV2,
)
from enterprise_analytics_agent.errors import UnknownMetricError, UnsupportedMetricVersionError


@dataclass(frozen=True)
class CatalogDimension:
    dimension_id: str
    description: str
    entity: str
    field: str

    def public_description(self) -> DimensionDefinition:
        return DimensionDefinition(dimension_id=self.dimension_id, description=self.description)

    def public_description_v2(self) -> DimensionDefinitionV2:
        return DimensionDefinitionV2(dimension_id=self.dimension_id, description=self.description)


@dataclass(frozen=True)
class CatalogRelationship:
    from_entity: str
    to_entity: str
    keys: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class CatalogFilter:
    attribute: str
    entity: str
    field: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class CatalogTimeSemantics:
    entity: str
    field: str
    time_dimension: str
    grain: Literal["UTC business date"] = "UTC business date"
    interval: Literal["[start, end)"] = "[start, end)"
    refund_attribution: Literal["original_order_date"] = "original_order_date"


@dataclass(frozen=True)
class MetricSpecification:
    """Private execution configuration with an explicit public metadata projection."""

    metric_id: str
    display_name: str
    description: str
    definition_version: str
    calculation: str
    calculation_description: str
    base_grain: tuple[str, ...]
    dimensions: tuple[CatalogDimension, ...]
    relationships: tuple[CatalogRelationship, ...]
    filters: tuple[CatalogFilter, ...]
    time_semantics: CatalogTimeSemantics
    grain_name: MetricGrain = "order_item"
    unit: MetricUnit = "currency"
    currency: Literal["USD"] | None = "USD"
    decimal_places: MetricPrecision = 2
    rounding: Literal["ROUND_HALF_UP"] = "ROUND_HALF_UP"
    nullable: bool = False
    required_sources: tuple[str, ...] = ("orders", "order_items", "refunds")

    def public_description(self) -> MetricDefinition:
        if self.metric_id != "net_revenue":
            raise UnsupportedMetricVersionError(
                f"Metric '{self.metric_id}' requires api_version 'v2'"
            )
        return MetricDefinition(
            metric_id=self.metric_id,
            display_name=self.display_name,
            description=self.description,
            definition_version=self.definition_version,
            calculation=self.calculation_description,
            base_grain="order_item",
            dimensions=tuple(dimension.public_description() for dimension in self.dimensions),
            relationships=tuple(relationship.description for relationship in self.relationships),
            filters=tuple(
                MetricFilter(attribute=rule.attribute, values=rule.values) for rule in self.filters
            ),
            time_semantics=TimeSemantics(
                time_dimension=self.time_semantics.time_dimension,
                grain=self.time_semantics.grain,
                interval=self.time_semantics.interval,
                refund_attribution=self.time_semantics.refund_attribution,
            ),
            unit="currency",
            currency="USD",
        )

    def public_description_v2(self) -> MetricDefinitionV2:
        return MetricDefinitionV2(
            metric_id=self.metric_id,
            display_name=self.display_name,
            description=self.description,
            definition_version=self.definition_version,
            calculation=self.calculation_description,
            base_grain=self.grain_name,
            dimensions=tuple(dimension.public_description_v2() for dimension in self.dimensions),
            relationships=tuple(relationship.description for relationship in self.relationships),
            filters=tuple(
                MetricFilterV2(attribute=rule.attribute, values=rule.values)
                for rule in self.filters
            ),
            time_semantics=TimeSemanticsV2(time_dimension=self.time_semantics.time_dimension),
            unit=self.unit,
            currency=self.currency,
            decimal_places=self.decimal_places,
            rounding=self.rounding,
            nullable=self.nullable,
        )


NET_REVENUE = MetricSpecification(
    metric_id="net_revenue",
    display_name="Net revenue",
    description="Eligible merchandise sales less line discounts and approved item refunds.",
    definition_version="1.0.0",
    calculation="sum(quantity * unit_price_cents - discount_cents - approved_refund_cents)",
    calculation_description=(
        "Sum merchandise sales after line discounts, less approved merchandise refunds."
    ),
    base_grain=("tenant_id", "order_item_id"),
    dimensions=(
        CatalogDimension(
            dimension_id="region",
            description="Customer region recorded on the order at purchase time.",
            entity="orders",
            field="region",
        ),
        CatalogDimension(
            dimension_id="channel",
            description="Sales channel recorded on the order.",
            entity="orders",
            field="channel",
        ),
    ),
    relationships=(
        CatalogRelationship(
            from_entity="orders",
            to_entity="customers",
            keys=("tenant_id", "customer_id"),
            description="Each order belongs to one customer.",
        ),
        CatalogRelationship(
            from_entity="order_items",
            to_entity="orders",
            keys=("tenant_id", "order_id"),
            description="Each order item belongs to one order.",
        ),
        CatalogRelationship(
            from_entity="order_items",
            to_entity="products",
            keys=("tenant_id", "product_id"),
            description="Each order item references one product.",
        ),
        CatalogRelationship(
            from_entity="payments",
            to_entity="orders",
            keys=("tenant_id", "order_id"),
            description="Each payment belongs to one order; payments do not determine this metric.",
        ),
        CatalogRelationship(
            from_entity="refunds",
            to_entity="order_items",
            keys=("tenant_id", "order_item_id"),
            description="Each refund belongs to one order item; an item can have multiple refunds.",
        ),
    ),
    filters=(
        CatalogFilter(
            attribute="order_status",
            entity="orders",
            field="status",
            values=("completed", "shipped"),
        ),
        CatalogFilter(
            attribute="order_currency", entity="orders", field="currency", values=("USD",)
        ),
        CatalogFilter(
            attribute="refund_status", entity="refunds", field="status", values=("approved",)
        ),
        CatalogFilter(
            attribute="refund_currency", entity="refunds", field="currency", values=("USD",)
        ),
    ),
    time_semantics=CatalogTimeSemantics(
        entity="orders", field="ordered_at", time_dimension="order_date"
    ),
)


ORDER_FILTERS = tuple(rule for rule in NET_REVENUE.filters if rule.entity == "orders")
ORDER_RELATIONSHIPS = tuple(
    rule for rule in NET_REVENUE.relationships if rule.from_entity in ("orders", "order_items")
)

GROSS_SALES = replace(
    NET_REVENUE,
    metric_id="gross_sales",
    display_name="Gross sales",
    description="Eligible merchandise sales before discounts/refunds; tax and shipping excluded.",
    calculation="sum(quantity * unit_price_cents)",
    calculation_description="Sum item quantities times unit prices before discounts and refunds.",
    filters=ORDER_FILTERS,
    relationships=ORDER_RELATIONSHIPS,
    required_sources=("orders", "order_items"),
)

ORDER_COUNT = replace(
    NET_REVENUE,
    metric_id="order_count",
    display_name="Order count",
    description="Distinct eligible orders having at least one valid order item.",
    calculation="count_distinct_eligible_orders",
    calculation_description="Count eligible orders with at least one valid item once each.",
    base_grain=("tenant_id", "order_id"),
    grain_name="order",
    filters=ORDER_FILTERS,
    relationships=ORDER_RELATIONSHIPS,
    unit="count",
    currency=None,
    decimal_places=0,
    required_sources=("orders", "order_items"),
)

AVERAGE_ORDER_VALUE = replace(
    NET_REVENUE,
    metric_id="average_order_value",
    display_name="Average order value",
    description="Aggregate net revenue per eligible order; null when no orders qualify.",
    calculation="aggregate_net_revenue / aggregate_order_count",
    calculation_description="Divide aggregate net revenue by aggregate eligible order count.",
    base_grain=("tenant_id", "order_id"),
    grain_name="order",
    nullable=True,
)

RETURN_RATE = replace(
    ORDER_COUNT,
    metric_id="return_rate",
    display_name="Return rate",
    description="Fraction of eligible orders with received physical returns; null without orders.",
    calculation="returned_order_count / aggregate_order_count",
    calculation_description="Divide orders with received physical returns by all eligible orders.",
    unit="ratio",
    decimal_places=6,
    nullable=True,
    required_sources=("orders", "order_items", "returns"),
    filters=(
        *ORDER_FILTERS,
        CatalogFilter(
            attribute="return_status", entity="returns", field="status", values=("received",)
        ),
    ),
    relationships=(
        *ORDER_RELATIONSHIPS,
        CatalogRelationship(
            from_entity="returns",
            to_entity="order_items",
            keys=("tenant_id", "order_item_id"),
            description="Each physical return references one order item; orders count once.",
        ),
    ),
)

METRICS = (GROSS_SALES, NET_REVENUE, ORDER_COUNT, AVERAGE_ORDER_VALUE, RETURN_RATE)


def get_metrics(api_version: Literal["v1", "v2"] = "v1") -> tuple[MetricSpecification, ...]:
    return (NET_REVENUE,) if api_version == "v1" else METRICS


def get_metric(metric_id: str, *, api_version: Literal["v1", "v2"] = "v1") -> MetricSpecification:
    for metric in METRICS:
        if metric.metric_id == metric_id:
            if api_version == "v1" and metric_id != NET_REVENUE.metric_id:
                raise UnsupportedMetricVersionError(
                    f"Metric '{metric_id}' requires api_version 'v2'"
                )
            return metric
    raise UnknownMetricError(f"Unknown metric: {metric_id}")
