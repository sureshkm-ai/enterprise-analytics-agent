"""V2 semantic contracts; the published v1 models remain unchanged."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_analytics_agent.contracts import NonEmpty, QueryMetricRequest, TimeRange

type MetricUnit = Literal["currency", "count", "ratio"]
type MetricGrain = Literal["order_item", "order"]
type MetricPrecision = Literal[0, 2, 6]


class ContractV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_version: Literal["v2"] = "v2"


class TimeRangeV2(ContractV2):
    start: date
    end: date

    @field_validator("start", "end", mode="before")
    @classmethod
    def dates_only(cls, value: object) -> object:
        return TimeRange.dates_only(value)

    @model_validator(mode="after")
    def increasing_dates(self) -> Self:
        if self.start >= self.end:
            raise ValueError("start must be before exclusive end")
        return self


class DiscoverMetricsRequestV2(ContractV2):
    search: NonEmpty | None = None


class DescribeMetricRequestV2(ContractV2):
    metric_id: NonEmpty


class DiscoverDimensionsRequestV2(ContractV2):
    metric_id: NonEmpty


class QueryMetricRequestV2(ContractV2):
    metric_id: NonEmpty
    time_range: TimeRangeV2
    group_by: tuple[NonEmpty, ...] = ()
    dimension_filters: dict[str, tuple[NonEmpty, ...]] = Field(default_factory=dict)

    @field_validator("group_by")
    @classmethod
    def unique_dimensions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return QueryMetricRequest.unique_dimensions(value)

    @field_validator("dimension_filters")
    @classmethod
    def nonempty_filter_values(
        cls, value: dict[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        return QueryMetricRequest.nonempty_filter_values(value)


class DimensionDefinitionV2(ContractV2):
    dimension_id: NonEmpty
    description: NonEmpty


class MetricFilterV2(ContractV2):
    """Fixed business eligibility; it cannot be overridden by a tool request."""

    attribute: NonEmpty
    values: tuple[NonEmpty, ...]


class TimeSemanticsV2(ContractV2):
    time_dimension: NonEmpty
    grain: Literal["UTC business date"] = "UTC business date"
    interval: Literal["[start, end)"] = "[start, end)"
    adjustment_attribution: Literal["original_order_date"] = "original_order_date"
    as_of_cutoff: Literal[False] = False


class MetricSummaryV2(ContractV2):
    metric_id: NonEmpty
    display_name: NonEmpty
    description: str
    definition_version: NonEmpty


class MetricDefinitionV2(MetricSummaryV2):
    calculation: str
    base_grain: MetricGrain
    dimensions: tuple[DimensionDefinitionV2, ...]
    relationships: tuple[NonEmpty, ...]
    filters: tuple[MetricFilterV2, ...]
    unit: MetricUnit
    currency: Literal["USD"] | None = None
    decimal_places: MetricPrecision
    rounding: Literal["ROUND_HALF_UP"] = "ROUND_HALF_UP"
    nullable: bool = False
    time_semantics: TimeSemanticsV2

    @model_validator(mode="after")
    def consistent_units(self) -> Self:
        expected_places = {"currency": 2, "count": 0, "ratio": 6}
        if self.decimal_places != expected_places[self.unit]:
            raise ValueError("decimal_places must match the metric unit")
        if self.currency != ("USD" if self.unit == "currency" else None):
            raise ValueError("only monetary metrics carry USD currency")
        return self


class DiscoverMetricsResponseV2(ContractV2):
    metrics: tuple[MetricSummaryV2, ...]


class DescribeMetricResponseV2(ContractV2):
    metric: MetricDefinitionV2


class DimensionValuesV2(ContractV2):
    dimension: DimensionDefinitionV2
    values: tuple[str, ...]


class DiscoverDimensionsResponseV2(ContractV2):
    metric_id: NonEmpty
    dimensions: tuple[DimensionValuesV2, ...]


class MetricRowV2(ContractV2):
    dimensions: dict[str, str]
    value: Decimal | Annotated[int, Field(strict=True)] | None

    @field_validator("value", mode="before")
    @classmethod
    def exact_values_only(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("use exact decimal strings/Decimal values or integer counts")
        return value


class QueryMetricResponseV2(ContractV2):
    metric_id: NonEmpty
    definition_version: NonEmpty
    time_range: TimeRangeV2
    group_by: tuple[str, ...]
    unit: MetricUnit
    currency: Literal["USD"] | None = None
    rows: tuple[MetricRowV2, ...]

    @model_validator(mode="after")
    def consistent_result_types(self) -> Self:
        if self.currency != ("USD" if self.unit == "currency" else None):
            raise ValueError("only monetary results carry USD currency")
        for row in self.rows:
            if self.unit == "count":
                if type(row.value) is not int or row.value < 0:
                    raise ValueError("counts must be nonnegative integers")
                continue
            if row.value is None:
                continue
            if not isinstance(row.value, Decimal):
                raise ValueError("currency and ratio results must be exact decimals or null")
            places = 2 if self.unit == "currency" else 6
            if row.value.as_tuple().exponent != -places:
                raise ValueError(f"{self.unit} results must have exactly {places} decimal places")
            if self.unit == "ratio" and not Decimal(0) <= row.value <= Decimal(1):
                raise ValueError("a return-rate fraction must be between zero and one")
        return self
