"""Version migration preserves v1 and exposes only governed business metadata."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from enterprise_analytics_agent import contracts as v1
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.contracts_v2 import (
    DescribeMetricRequestV2,
    DescribeMetricResponseV2,
    DiscoverDimensionsRequestV2,
    DiscoverDimensionsResponseV2,
    DiscoverMetricsRequestV2,
    DiscoverMetricsResponseV2,
    MetricRowV2,
    QueryMetricRequestV2,
    QueryMetricResponseV2,
    TimeRangeV2,
)
from enterprise_analytics_agent.errors import AuthorizationError, SemanticError

# Captured from untouched v1 contracts at the local M1 checkpoint 64cbea4.
# This guards the complete published schemas, including all nested definitions.
V1_SCHEMA_HASHES = {
    "TimeRange": "ef51cc0efe4c58b924dceeb0e50f777536748c8671e6f3a538b0154ad2773eb8",
    "DiscoverMetricsRequest": "95d5df63f2328d238df3d85b1af38e53baf511306d2a632111da2d60e2fb80b2",
    "DescribeMetricRequest": "f5fe5ecc0b1697d2b6f7300ce2f7f69ad8d831f436f5200be0d8b8213b4f6a06",
    "DiscoverDimensionsRequest": "93fb1d27813f4e692ea2d25340307d56f980740688d0416d2b1b05ab4c26dcef",
    "QueryMetricRequest": "9a9104e7ffa43ea39094ca9d1264f0daec5d2c1c4abf07e24076cf1c14d5adab",
    "DiscoverMetricsResponse": "ea8156d5471c43c77322ecdc42201b77fd955488c980bc6e61d016da36617e8a",
    "DescribeMetricResponse": "ff4f13944bbade6430088700de047c52812a77c28ce4f3eef6e0912cf7ffc46d",
    "DiscoverDimensionsResponse": (
        "a69ebdf7f2113121f788b7a177e616609a8f5d55899738461634eb58199c1446"
    ),
    "QueryMetricResponse": "e44bdbe9a46581a383a9794410f37223c73d8c61025303aff590b4a0e487beea",
}

PRIVATE_EXECUTION_TERMS = (
    "unit_price_cents",
    "discount_cents",
    "approved_refund_cents",
    "ordered_at",
    "returned_at",
    "received_at",
    "tenant_id",
    "order_item_id",
    '"entity"',
    '"field"',
    '"keys"',
    "SELECT ",
    "duckdb",
    "athena",
    "boto3",
    "cube",
)


@pytest.mark.parametrize("name", V1_SCHEMA_HASHES)
def test_v1_schemas_match_the_milestone_one_checkpoint(name: str) -> None:
    schema = getattr(v1, name).model_json_schema()
    actual = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
    assert actual == V1_SCHEMA_HASHES[name]


def test_v1_net_revenue_golden_json_and_discovery_remain_unchanged(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    request = v1.QueryMetricRequest.model_validate_json(
        '{"api_version":"v1","metric_id":"net_revenue",'
        '"time_range":{"api_version":"v1","start":"2025-01-01","end":"2025-02-01"},'
        '"group_by":["region"],"dimension_filters":{}}'
    )
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        response = adapter.query_metric(request, context=context)
        discovery = adapter.discover_metrics(v1.DiscoverMetricsRequest(), context=context)
    assert [metric.metric_id for metric in discovery.metrics] == ["net_revenue"]
    assert response.model_dump_json() == (
        '{"api_version":"v1","metric_id":"net_revenue","definition_version":"1.0.0",'
        '"time_range":{"api_version":"v1","start":"2025-01-01","end":"2025-02-01"},'
        '"group_by":["region"],"unit":"currency","currency":"USD",'
        '"rows":[{"api_version":"v1","dimensions":{"region":"North"},"value":"19.50"},'
        '{"api_version":"v1","dimensions":{"region":"South"},"value":"13.00"}]}'
    )


@pytest.mark.parametrize("field", ["principal_id", "tenant_id", "allowed_regions", "context"])
@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (DiscoverMetricsRequestV2, {}),
        (DescribeMetricRequestV2, {"metric_id": "return_rate"}),
        (DiscoverDimensionsRequestV2, {"metric_id": "order_count"}),
        (
            QueryMetricRequestV2,
            {
                "metric_id": "gross_sales",
                "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
            },
        ),
    ],
)
def test_all_v2_tool_requests_reject_model_supplied_authorization(
    model: type[BaseModel], payload: dict[str, object], field: str
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: "forged"})


@pytest.mark.parametrize("version", ["v1", "v3"])
def test_v2_rejects_wrong_envelope_and_nested_versions(version: str) -> None:
    with pytest.raises(ValidationError):
        DiscoverMetricsRequestV2.model_validate({"api_version": version})
    with pytest.raises(ValidationError):
        QueryMetricRequestV2.model_validate(
            {
                "metric_id": "order_count",
                "time_range": {"api_version": version, "start": "2025-01-01", "end": "2025-02-01"},
            }
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2025-02-01", "2025-02-01"),
        ("2025-02-02", "2025-02-01"),
        ("2025-02-30", "2025-03-01"),
        ("20250101", "2025-02-01"),
        ("2025-01-01T00:00:00Z", "2025-02-01"),
        (datetime(2025, 1, 1), "2025-02-01"),
        (1735689600, "2025-02-01"),
        (True, "2025-02-01"),
    ],
)
def test_v2_dates_preserve_explicit_business_date_rules(start: object, end: object) -> None:
    with pytest.raises(ValidationError):
        TimeRangeV2.model_validate({"start": start, "end": end})


def test_v2_query_rejects_duplicate_grouping_empty_filters_and_expressions() -> None:
    payload: dict[str, object] = {
        "metric_id": "order_count",
        "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
    }
    invalid_overrides: tuple[dict[str, object], ...] = (
        {"group_by": ["region", "region"]},
        {"dimension_filters": {"region": []}},
        {"expression": "SUM(unit_price_cents)"},
        {"order_status": "pending"},
    )
    for overrides in invalid_overrides:
        with pytest.raises(ValidationError):
            QueryMetricRequestV2.model_validate({**payload, **overrides})


@pytest.mark.parametrize(
    ("unit", "currency", "value", "serialized"),
    [
        ("currency", "USD", Decimal("14.17"), "14.17"),
        ("count", None, 3, 3),
        ("ratio", None, Decimal("0.333333"), "0.333333"),
        ("ratio", None, None, None),
        ("currency", "USD", None, None),
    ],
)
def test_v2_result_round_trip_preserves_exact_values_and_nulls(
    unit: str, currency: str | None, value: Decimal | int | None, serialized: str | int | None
) -> None:
    response = QueryMetricResponseV2.model_validate(
        {
            "metric_id": "example",
            "definition_version": "1.0.0",
            "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
            "group_by": [],
            "unit": unit,
            "currency": currency,
            "rows": [{"dimensions": {}, "value": value}],
        }
    )
    encoded = response.model_dump_json()
    assert json.loads(encoded)["rows"][0]["value"] == serialized
    assert QueryMetricResponseV2.model_validate_json(encoded) == response
    assert_all_versions_v2(json.loads(encoded))


@pytest.mark.parametrize(
    ("unit", "currency", "value"),
    [
        ("count", None, "3"),
        ("count", None, Decimal("3")),
        ("count", None, -1),
        ("count", None, None),
        ("count", None, True),
        ("count", None, 3.0),
        ("count", "USD", 3),
        ("currency", None, "14.17"),
        ("currency", "USD", 14.17),
        ("currency", "USD", "14.170"),
        ("ratio", "USD", "0.333333"),
        ("ratio", None, "0.33333"),
        ("ratio", None, "1.000001"),
        ("ratio", None, "-0.000001"),
    ],
)
def test_v2_result_rejects_coercion_mismatched_units_and_wrong_precision(
    unit: str, currency: str | None, value: object
) -> None:
    with pytest.raises(ValidationError):
        QueryMetricResponseV2.model_validate(
            {
                "metric_id": "example",
                "definition_version": "1.0.0",
                "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
                "group_by": [],
                "unit": unit,
                "currency": currency,
                "rows": [{"dimensions": {}, "value": value}],
            }
        )


@pytest.mark.parametrize("value", [True, False, 0.1])
def test_v2_rows_reject_binary_floating_point_and_boolean_values(value: object) -> None:
    with pytest.raises(ValidationError):
        MetricRowV2.model_validate({"dimensions": {}, "value": value})


def assert_all_versions_v2(value: object) -> None:
    if isinstance(value, dict):
        for name, child in value.items():
            if name == "api_version":
                assert child == "v2"
            assert_all_versions_v2(child)
    elif isinstance(value, list):
        for child in value:
            assert_all_versions_v2(child)


@pytest.mark.parametrize(
    ("metric_id", "grain", "unit", "places", "nullable"),
    [
        ("gross_sales", "order_item", "currency", 2, False),
        ("net_revenue", "order_item", "currency", 2, False),
        ("order_count", "order", "count", 0, False),
        ("average_order_value", "order", "currency", 2, True),
        ("return_rate", "order", "ratio", 6, True),
    ],
)
def test_v2_discovery_describes_governed_grain_precision_and_authorized_dimensions(
    snapshot_dir: Path,
    context: AuthorizationContext,
    metric_id: str,
    grain: str,
    unit: str,
    places: int,
    nullable: bool,
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        discovered = adapter.discover_metrics(DiscoverMetricsRequestV2(), context=context)
        described = adapter.describe_metric(
            DescribeMetricRequestV2(metric_id=metric_id), context=context
        )
        dimensions = adapter.discover_dimensions(
            DiscoverDimensionsRequestV2(metric_id=metric_id), context=context
        )
    assert {metric.metric_id for metric in discovered.metrics} == {
        "gross_sales",
        "net_revenue",
        "order_count",
        "average_order_value",
        "return_rate",
    }
    definition = described.metric
    assert definition.base_grain == grain
    assert definition.unit == unit
    assert definition.decimal_places == places
    assert definition.nullable is nullable
    assert definition.rounding == "ROUND_HALF_UP"
    assert definition.currency == ("USD" if unit == "currency" else None)
    assert definition.time_semantics.time_dimension == "order_date"
    assert definition.time_semantics.interval == "[start, end)"
    assert definition.time_semantics.adjustment_attribution == "original_order_date"
    assert definition.time_semantics.as_of_cutoff is False
    assert {item.dimension.dimension_id: item.values for item in dimensions.dimensions} == {
        "region": ("North", "South"),
        "channel": ("online", "store"),
    }
    for response in (discovered, described, dimensions):
        assert_all_versions_v2(json.loads(response.model_dump_json()))
        for private in PRIVATE_EXECUTION_TERMS:
            assert private not in response.model_dump_json()


@pytest.mark.parametrize(
    "model",
    [
        DescribeMetricResponseV2,
        DiscoverDimensionsResponseV2,
        DiscoverMetricsResponseV2,
        QueryMetricResponseV2,
    ],
)
def test_v2_schemas_do_not_advertise_sql_or_provider_configuration(model: type[BaseModel]) -> None:
    for mode in ("validation", "serialization"):
        schema = model.model_json_schema(
            mode="validation" if mode == "validation" else "serialization"
        )
        encoded = json.dumps(schema)
        for private in PRIVATE_EXECUTION_TERMS:
            assert private not in encoded


def test_v2_discovery_methods_deny_empty_trusted_region_scope(
    snapshot_dir: Path, context: AuthorizationContext
) -> None:
    denied = context.model_copy(update={"allowed_regions": ()})
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        with pytest.raises(AuthorizationError):
            adapter.discover_metrics(DiscoverMetricsRequestV2(), context=denied)
        with pytest.raises(AuthorizationError):
            adapter.describe_metric(
                DescribeMetricRequestV2(metric_id="order_count"), context=denied
            )
        with pytest.raises(AuthorizationError):
            adapter.discover_dimensions(
                DiscoverDimensionsRequestV2(metric_id="return_rate"), context=denied
            )


@pytest.mark.parametrize(
    "metric_id", ["gross_sales", "order_count", "average_order_value", "return_rate"]
)
def test_v1_descriptions_and_dimensions_require_explicit_v2_for_new_metrics(
    snapshot_dir: Path, context: AuthorizationContext, metric_id: str
) -> None:
    with DuckDBSemanticAdapter(snapshot_dir) as adapter:
        with pytest.raises(SemanticError, match="v2"):
            adapter.describe_metric(v1.DescribeMetricRequest(metric_id=metric_id), context=context)
        with pytest.raises(SemanticError, match="v2"):
            adapter.discover_dimensions(
                v1.DiscoverDimensionsRequest(metric_id=metric_id), context=context
            )


def test_v2_iso_dates_are_accepted_without_v1_nesting() -> None:
    period = TimeRangeV2.model_validate({"start": "2025-01-01", "end": "2025-02-01"})
    assert period.start == date(2025, 1, 1)
    assert period.end == date(2025, 2, 1)
    assert period.api_version == "v2"
