from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.contracts import (
    DescribeMetricRequest,
    DiscoverDimensionsRequest,
    DiscoverMetricsRequest,
    MetricRow,
    QueryMetricRequest,
    QueryMetricResponse,
    TimeRange,
)


def test_query_json_round_trip_preserves_version_and_exact_money() -> None:
    period = TimeRange(start=date(2025, 1, 1), end=date(2025, 2, 1))
    response = QueryMetricResponse(
        metric_id="net_revenue",
        definition_version="1.0.0",
        time_range=period,
        group_by=("region",),
        rows=(MetricRow(dimensions={"region": "North"}, value=Decimal("19.50")),),
    )
    payload = response.model_dump_json()
    assert '"api_version":"v1"' in payload
    assert '"value":"19.50"' in payload
    assert QueryMetricResponse.model_validate_json(payload) == response


@pytest.mark.parametrize("field", ["principal_id", "tenant_id", "allowed_regions", "context"])
@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (DiscoverMetricsRequest, {}),
        (DescribeMetricRequest, {"metric_id": "net_revenue"}),
        (DiscoverDimensionsRequest, {"metric_id": "net_revenue"}),
        (
            QueryMetricRequest,
            {
                "metric_id": "net_revenue",
                "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
            },
        ),
    ],
)
def test_tool_requests_reject_model_supplied_identity(
    model: type[
        DiscoverMetricsRequest
        | DescribeMetricRequest
        | DiscoverDimensionsRequest
        | QueryMetricRequest
    ],
    payload: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: "forged"})


def test_unknown_contract_version_rejected() -> None:
    with pytest.raises(ValidationError):
        DiscoverMetricsRequest.model_validate({"api_version": "v2"})


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2025-02-01", "2025-02-01"),
        ("2025-02-02", "2025-02-01"),
        ("2025-02-30", "2025-03-01"),
        ("20250101", "2025-02-01"),
        ("2025-01-01T00:00:00Z", "2025-02-01"),
        (1735689600, "2025-02-01"),
        (datetime(2025, 1, 1), "2025-02-01"),
        (True, "2025-02-01"),
    ],
)
def test_date_contract_rejects_invalid_ranges_and_timestamp_coercion(
    start: object, end: object
) -> None:
    with pytest.raises(ValidationError):
        TimeRange.model_validate({"start": start, "end": end})


def test_iso_dates_are_accepted() -> None:
    period = TimeRange.model_validate({"start": "2025-01-01", "end": "2025-02-01"})
    assert period.start == date(2025, 1, 1)
    assert period.end == date(2025, 2, 1)


def test_duplicate_grouping_and_empty_filter_are_rejected() -> None:
    payload: dict[str, object] = {
        "metric_id": "net_revenue",
        "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
    }
    with pytest.raises(ValidationError):
        QueryMetricRequest.model_validate({**payload, "group_by": ["region", "region"]})
    with pytest.raises(ValidationError):
        QueryMetricRequest.model_validate({**payload, "dimension_filters": {"region": []}})
