"""Versioned semantic tool contracts. No backend or provider types belong here."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonEmpty = Annotated[str, Field(min_length=1, max_length=200)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_version: Literal["v1"] = "v1"


class AuthorizationContext(BaseModel):
    """Trusted application input, never a semantic tool argument or model output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: NonEmpty
    tenant_id: NonEmpty
    allowed_regions: tuple[NonEmpty, ...]


class TimeRange(Contract):
    start: date
    end: date

    @field_validator("start", "end", mode="before")
    @classmethod
    def dates_only(cls, value: object) -> object:
        if type(value) is date:
            return value
        if isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("use an ISO date in YYYY-MM-DD format") from exc
            if parsed.isoformat() == value:
                return parsed
        if isinstance(value, datetime):
            raise ValueError("timestamps are not supported; use a UTC business date")
        raise ValueError("use a date or an ISO date in YYYY-MM-DD format")

    @model_validator(mode="after")
    def increasing_dates(self) -> Self:
        if self.start >= self.end:
            raise ValueError("start must be before exclusive end")
        return self


class DiscoverMetricsRequest(Contract):
    search: NonEmpty | None = None


class DescribeMetricRequest(Contract):
    metric_id: NonEmpty


class DiscoverDimensionsRequest(Contract):
    metric_id: NonEmpty


class QueryMetricRequest(Contract):
    metric_id: NonEmpty
    time_range: TimeRange
    group_by: tuple[NonEmpty, ...] = ()
    dimension_filters: dict[str, tuple[NonEmpty, ...]] = Field(default_factory=dict)

    @field_validator("group_by")
    @classmethod
    def unique_dimensions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("group_by must contain unique dimensions")
        return value

    @field_validator("dimension_filters")
    @classmethod
    def nonempty_filter_values(
        cls, value: dict[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        if any(not values for values in value.values()):
            raise ValueError("each dimension filter must contain at least one value")
        return value


class DimensionDefinition(Contract):
    dimension_id: NonEmpty
    description: NonEmpty


class MetricFilter(Contract):
    """Fixed business eligibility, separate from caller-supplied dimension filters."""

    attribute: NonEmpty
    values: tuple[NonEmpty, ...]


class TimeSemantics(Contract):
    time_dimension: NonEmpty
    grain: Literal["UTC business date"] = "UTC business date"
    interval: Literal["[start, end)"] = "[start, end)"
    refund_attribution: Literal["original_order_date"] = "original_order_date"


class MetricSummary(Contract):
    metric_id: NonEmpty
    display_name: NonEmpty
    description: str
    definition_version: NonEmpty


class MetricDefinition(MetricSummary):
    """Business-facing metadata; execution expressions and bindings stay in the catalog."""

    calculation: str
    base_grain: Literal["order_item"]
    dimensions: tuple[DimensionDefinition, ...]
    relationships: tuple[NonEmpty, ...]
    filters: tuple[MetricFilter, ...]
    unit: Literal["currency"] = "currency"
    currency: Literal["USD"] = "USD"
    time_semantics: TimeSemantics


class DiscoverMetricsResponse(Contract):
    metrics: tuple[MetricSummary, ...]


class DescribeMetricResponse(Contract):
    metric: MetricDefinition


class DimensionValues(Contract):
    dimension: DimensionDefinition
    values: tuple[str, ...]


class DiscoverDimensionsResponse(Contract):
    metric_id: NonEmpty
    dimensions: tuple[DimensionValues, ...]


class MetricRow(Contract):
    dimensions: dict[str, str]
    value: Decimal


class QueryMetricResponse(Contract):
    metric_id: NonEmpty
    definition_version: NonEmpty
    time_range: TimeRange
    group_by: tuple[str, ...]
    unit: Literal["currency"] = "currency"
    currency: Literal["USD"] = "USD"
    rows: tuple[MetricRow, ...]
