"""Model-visible schemas and payloads must not expose execution configuration."""

import json
from pathlib import Path

import pytest

from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.contracts import (
    AuthorizationContext,
    DescribeMetricRequest,
    DescribeMetricResponse,
    DiscoverDimensionsRequest,
    DiscoverDimensionsResponse,
)

PRIVATE_EXECUTION_TERMS = (
    "unit_price_cents",
    "discount_cents",
    "approved_refund_cents",
    "ordered_at",
    "tenant_id",
    "order_item_id",
    '"entity"',
    '"field"',
    '"keys"',
)


def assert_business_metadata(payload: str) -> None:
    for term in PRIVATE_EXECUTION_TERMS:
        assert term not in payload, f"Execution configuration leaked: {term}"


def test_description_exposes_business_rules_without_execution_bindings(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        response = adapter.describe_metric(
            DescribeMetricRequest(metric_id="net_revenue"), context=context
        )
    assert_business_metadata(response.model_dump_json())
    assert response.metric.base_grain == "order_item"
    assert response.metric.calculation == (
        "Sum merchandise sales after line discounts, less approved merchandise refunds."
    )
    assert response.metric.time_semantics.time_dimension == "order_date"
    assert response.metric.time_semantics.interval == "[start, end)"
    assert response.metric.time_semantics.refund_attribution == "original_order_date"
    assert {rule.attribute: rule.values for rule in response.metric.filters} == {
        "order_status": ("completed", "shipped"),
        "order_currency": ("USD",),
        "refund_status": ("approved",),
        "refund_currency": ("USD",),
    }


def test_dimension_discovery_exposes_names_and_scoped_values_only(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        response = adapter.discover_dimensions(
            DiscoverDimensionsRequest(metric_id="net_revenue"), context=context
        )
    assert_business_metadata(response.model_dump_json())
    assert {
        dimension.dimension.dimension_id: dimension.values for dimension in response.dimensions
    } == {"region": ("North", "South"), "channel": ("online", "store")}


@pytest.mark.parametrize("response_type", [DescribeMetricResponse, DiscoverDimensionsResponse])
def test_response_schemas_do_not_advertise_private_execution_configuration(
    response_type: type[DescribeMetricResponse | DiscoverDimensionsResponse],
) -> None:
    for mode in ("validation", "serialization"):
        # Check schemas too: excluding fields only during JSON output is insufficient.
        schema = (
            response_type.model_json_schema(mode="validation")
            if mode == "validation"
            else response_type.model_json_schema(mode="serialization")
        )
        assert_business_metadata(json.dumps(schema))
