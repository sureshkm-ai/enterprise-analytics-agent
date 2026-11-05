"""The provider-independent semantic boundary consumed by the future agent."""

from typing import Protocol, overload

from enterprise_analytics_agent.contracts import (
    AuthorizationContext,
    DescribeMetricRequest,
    DescribeMetricResponse,
    DiscoverDimensionsRequest,
    DiscoverDimensionsResponse,
    DiscoverMetricsRequest,
    DiscoverMetricsResponse,
    QueryMetricRequest,
    QueryMetricResponse,
)
from enterprise_analytics_agent.contracts_v2 import (
    DescribeMetricRequestV2,
    DescribeMetricResponseV2,
    DiscoverDimensionsRequestV2,
    DiscoverDimensionsResponseV2,
    DiscoverMetricsRequestV2,
    DiscoverMetricsResponseV2,
    QueryMetricRequestV2,
    QueryMetricResponseV2,
)


class SemanticAdapter(Protocol):
    @overload
    def discover_metrics(
        self, request: DiscoverMetricsRequest, *, context: AuthorizationContext
    ) -> DiscoverMetricsResponse: ...

    @overload
    def discover_metrics(
        self, request: DiscoverMetricsRequestV2, *, context: AuthorizationContext
    ) -> DiscoverMetricsResponseV2: ...

    @overload
    def describe_metric(
        self, request: DescribeMetricRequest, *, context: AuthorizationContext
    ) -> DescribeMetricResponse: ...

    @overload
    def describe_metric(
        self, request: DescribeMetricRequestV2, *, context: AuthorizationContext
    ) -> DescribeMetricResponseV2: ...

    @overload
    def query_metric(
        self, request: QueryMetricRequest, *, context: AuthorizationContext
    ) -> QueryMetricResponse: ...

    @overload
    def query_metric(
        self, request: QueryMetricRequestV2, *, context: AuthorizationContext
    ) -> QueryMetricResponseV2: ...

    @overload
    def discover_dimensions(
        self, request: DiscoverDimensionsRequest, *, context: AuthorizationContext
    ) -> DiscoverDimensionsResponse: ...

    @overload
    def discover_dimensions(
        self, request: DiscoverDimensionsRequestV2, *, context: AuthorizationContext
    ) -> DiscoverDimensionsResponseV2: ...
