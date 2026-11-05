"""The provider-independent semantic boundary consumed by the future agent."""

from typing import Protocol

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


class SemanticAdapter(Protocol):
    def discover_metrics(
        self, request: DiscoverMetricsRequest, *, context: AuthorizationContext
    ) -> DiscoverMetricsResponse: ...

    def describe_metric(
        self, request: DescribeMetricRequest, *, context: AuthorizationContext
    ) -> DescribeMetricResponse: ...

    def query_metric(
        self, request: QueryMetricRequest, *, context: AuthorizationContext
    ) -> QueryMetricResponse: ...

    def discover_dimensions(
        self, request: DiscoverDimensionsRequest, *, context: AuthorizationContext
    ) -> DiscoverDimensionsResponse: ...
