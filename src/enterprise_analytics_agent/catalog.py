"""Governed, backend-independent metric definitions, rather than user formulas."""

from dataclasses import dataclass
from typing import Literal

from enterprise_analytics_agent.contracts import (
    DimensionDefinition,
    MetricDefinition,
    MetricFilter,
    TimeSemantics,
)
from enterprise_analytics_agent.errors import UnknownMetricError


@dataclass(frozen=True)
class CatalogDimension:
    dimension_id: str
    description: str
    entity: str
    field: str

    def public_description(self) -> DimensionDefinition:
        return DimensionDefinition(dimension_id=self.dimension_id, description=self.description)


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
    grain_name: Literal["order_item"] = "order_item"
    unit: Literal["currency"] = "currency"
    currency: Literal["USD"] = "USD"

    def public_description(self) -> MetricDefinition:
        return MetricDefinition(
            metric_id=self.metric_id,
            display_name=self.display_name,
            description=self.description,
            definition_version=self.definition_version,
            calculation=self.calculation_description,
            base_grain=self.grain_name,
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
            unit=self.unit,
            currency=self.currency,
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


def get_metric(metric_id: str) -> MetricSpecification:
    if metric_id != NET_REVENUE.metric_id:
        raise UnknownMetricError(f"Unknown metric: {metric_id}")
    return NET_REVENUE
