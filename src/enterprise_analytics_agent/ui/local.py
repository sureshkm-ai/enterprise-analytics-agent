"""Execute fresh local questions with the existing guard and real DuckDB calculations.

This is a deterministic semantic playground, not a simulated Bedrock conversation.
No model response, golden answer or AWS SDK client supplies the numeric results.
"""

import time
from datetime import date
from pathlib import Path
from typing import Literal

from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.agent.contracts import (
    AgentDiagnostics,
    AgentRequest,
    AgentResponse,
    ToolCallRecord,
)
from enterprise_analytics_agent.agent.questions import question_scope
from enterprise_analytics_agent.agent.tools import ToolRequest, execute_tool
from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.contracts_v2 import (
    DescribeMetricRequestV2,
    DiscoverDimensionsRequestV2,
    DiscoverMetricsRequestV2,
    QueryMetricRequestV2,
    QueryMetricResponseV2,
)
from enterprise_analytics_agent.data import DEFAULT_SEED, DEMO_TENANT, generate_retail_data
from enterprise_analytics_agent.errors import SemanticError
from enterprise_analytics_agent.ui.models import UiResult

REFERENCE_DATE = date(2025, 4, 1)
LOCAL_DATASET = f"local-sample-seed-{DEFAULT_SEED}"
SAMPLES = (
    "Show net_revenue for January 2025 by region.",
    "Show order_count for January 2025 by region and channel.",
    "Show average_order_value for March 2025 by channel.",
    "Show return_rate for January 2025 by region.",
    "Show gross_sales and net_revenue for January 2025 by region.",
    "Show net_revenue for yesterday.",
    "List available metrics.",
    "Describe average_order_value.",
    "List dimensions for net_revenue.",
)


class LocalQuestions:
    def __init__(self, directory: Path) -> None:
        # The server supplies a new temporary directory, never a retained snapshot.
        generate_retail_data(directory, seed=DEFAULT_SEED)
        self.directory = directory
        self.context = AuthorizationContext(
            principal_id="local-browser-application",
            tenant_id=DEMO_TENANT,
            allowed_regions=("North", "South"),
        )

    def ask(self, question: str) -> UiResult:
        request = AgentRequest(question=question)
        started = time.monotonic()
        scope = question_scope(request.question, REFERENCE_DATE)
        records: list[ToolCallRecord] = []
        results: list[QueryMetricResponseV2] = []
        metadata: list[dict[str, object]] = []
        response_status: Literal["answer", "clarification", "error"] = "answer"
        answer = "Results calculated from local sample data."
        error_code = None
        requests: list[tuple[str, ToolRequest]] = []
        if scope.clarification:
            response_status, answer = "clarification", scope.clarification
        elif scope.metadata:
            if not scope.metric_ids:
                requests.append(("discover_metrics", DiscoverMetricsRequestV2()))
            else:
                for metric in scope.metric_ids:
                    dimensions = any(
                        word in question.casefold()
                        for word in ("dimensions", "regions", "channels")
                    )
                    requests.append(
                        (
                            "discover_dimensions" if dimensions else "describe_metric",
                            DiscoverDimensionsRequestV2(metric_id=metric)
                            if dimensions
                            else DescribeMetricRequestV2(metric_id=metric),
                        )
                    )
            answer = "Governed catalog information for your local scope."
        else:
            for metric in scope.metric_ids:
                for period in scope.periods:
                    query = QueryMetricRequestV2(
                        metric_id=metric,
                        time_range=period,
                        group_by=scope.group_by,
                        dimension_filters=scope.filters,
                    )
                    scope.validate_query(query)
                    requests.append(("query_metric", query))
        if len(requests) > 8:
            response_status, answer = (
                "clarification",
                "Please request at most eight metric periods.",
            )
            requests.clear()
        with DuckDBSemanticAdapter(self.directory) as adapter:
            for index, (name, operation) in enumerate(requests):
                try:
                    result = execute_tool(adapter, operation, context=self.context)
                except SemanticError as exc:
                    error_code = type(exc).__name__
                    response_status, answer = "error", "The request is outside the supported scope."
                    records.append(
                        ToolCallRecord(
                            tool_use_id=f"local-{index}",
                            name=name,
                            arguments=operation.model_dump(mode="json"),
                            status="error",
                            error_code=error_code,
                        )
                    )
                    results.clear()
                    break
                records.append(
                    ToolCallRecord(
                        tool_use_id=f"local-{index}",
                        name=name,
                        arguments=operation.model_dump(mode="json"),
                        status="success",
                    )
                )
                if isinstance(result, QueryMetricResponseV2):
                    results.append(result)
                else:
                    metadata.append(result.model_dump(mode="json"))
        elapsed = max(0, int((time.monotonic() - started) * 1000))
        return UiResult(
            mode="local",
            elapsed_ms=elapsed,
            metadata=metadata,
            response=AgentResponse(
                status=response_status,
                answer=answer,
                results=tuple(results),
                dataset_version=LOCAL_DATASET,
                metric_versions={item.metric_id: item.definition_version for item in results},
                error_code=error_code,
                diagnostics=AgentDiagnostics(
                    model_id="local-deterministic-planner",
                    model_calls=0,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=elapsed,
                    configuration={"reference_date": REFERENCE_DATE.isoformat()},
                    tool_calls=tuple(records),
                    athena=(),
                ),
            ),
        )
