"""Exactly four semantic operations, validated against the existing v2 contracts."""

from copy import deepcopy
from typing import cast

from pydantic import BaseModel

from enterprise_analytics_agent.adapter import SemanticAdapter
from enterprise_analytics_agent.contracts import AuthorizationContext
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

type ToolRequest = (
    DiscoverMetricsRequestV2
    | DescribeMetricRequestV2
    | QueryMetricRequestV2
    | DiscoverDimensionsRequestV2
)
type ToolResponse = (
    DiscoverMetricsResponseV2
    | DescribeMetricResponseV2
    | QueryMetricResponseV2
    | DiscoverDimensionsResponseV2
)

REQUEST_MODELS: dict[str, type[BaseModel]] = {
    "discover_metrics": DiscoverMetricsRequestV2,
    "describe_metric": DescribeMetricRequestV2,
    "query_metric": QueryMetricRequestV2,
    "discover_dimensions": DiscoverDimensionsRequestV2,
}
DESCRIPTIONS = {
    "discover_metrics": "Discover the governed metrics supported by this semantic catalog.",
    "describe_metric": (
        "Describe one metric's business definition, units, precision and time rules."
    ),
    "query_metric": (
        "Query a governed metric. Dates are UTC business dates: inclusive start and exclusive end. "
        "Use only the metric, periods, grouping and filters explicitly requested by the user."
    ),
    "discover_dimensions": "Discover authorized values of a metric's allowed dimensions.",
}


def input_schema(name: str) -> dict[str, object]:
    """Inline Pydantic references for models supporting the ordinary JSON-schema subset."""
    schema = deepcopy(REQUEST_MODELS[name].model_json_schema())
    definitions = cast(dict[str, object], schema.pop("$defs", {}))

    def inline(value: object) -> object:
        if isinstance(value, list):
            return [inline(item) for item in value]
        if not isinstance(value, dict):
            return value
        node = cast(dict[str, object], value)
        if "$ref" in node:
            return inline(definitions[str(node["$ref"]).rsplit("/", 1)[-1]])
        output = {
            key: inline(item) for key, item in node.items() if key not in ("title", "default")
        }
        if "const" in output:
            output["enum"] = [output.pop("const")]
        return output

    return cast(dict[str, object], inline(schema))


def validate_tool_request(name: str, arguments: object) -> ToolRequest:
    if name not in REQUEST_MODELS:
        raise ValueError("Unknown semantic tool")
    return cast(ToolRequest, REQUEST_MODELS[name].model_validate(arguments))


def execute_tool(
    adapter: SemanticAdapter, request: ToolRequest, *, context: AuthorizationContext
) -> ToolResponse:
    if isinstance(request, DiscoverMetricsRequestV2):
        return adapter.discover_metrics(request, context=context)
    if isinstance(request, DescribeMetricRequestV2):
        return adapter.describe_metric(request, context=context)
    if isinstance(request, QueryMetricRequestV2):
        return adapter.query_metric(request, context=context)
    return adapter.discover_dimensions(request, context=context)
