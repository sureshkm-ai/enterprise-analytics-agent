"""A bounded Bedrock Converse tool loop over the provider-independent semantic interface."""

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import date
from typing import Annotated, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from enterprise_analytics_agent.adapter import SemanticAdapter
from enterprise_analytics_agent.agent.contracts import (
    AgentDiagnostics,
    AgentRequest,
    AgentResponse,
    ToolCallRecord,
)
from enterprise_analytics_agent.agent.questions import QuestionScope, question_scope
from enterprise_analytics_agent.agent.tools import (
    DESCRIPTIONS,
    REQUEST_MODELS,
    ToolResponse,
    execute_tool,
    input_schema,
    validate_tool_request,
)
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
from enterprise_analytics_agent.errors import AuthorizationError, SemanticError


class ConverseClient(Protocol):
    def converse(self, **kwargs: object) -> dict[str, object]: ...


class BedrockAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: Annotated[str, Field(min_length=1, max_length=2048)]
    reference_date: date
    max_iterations: Annotated[int, Field(strict=True, ge=1, le=20)] = 6
    max_tool_calls: Annotated[int, Field(strict=True, ge=1, le=50)] = 16
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=4096)] = 1024
    max_total_tokens: Annotated[int, Field(strict=True, ge=1, le=100_000)] = 12000
    timeout_seconds: Annotated[float, Field(gt=0, le=300, allow_inf_nan=False)] = 90.0


class _LoopFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _LoopFailure("malformed_model_response")
    return cast(dict[str, object], value)


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _LoopFailure("malformed_model_response")
    return value


def _tool_configuration() -> dict[str, object]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": name,
                    "description": DESCRIPTIONS[name],
                    "inputSchema": {"json": input_schema(name)},
                }
            }
            for name in REQUEST_MODELS
        ],
        "toolChoice": {"auto": {}},
    }


def _render(results: list[QueryMetricResponseV2]) -> str:
    lines = []
    for result in results:
        period = f"[{result.time_range.start.isoformat()}, {result.time_range.end.isoformat()})"
        lines.append(f"{result.metric_id} {period}; definition {result.definition_version}:")
        if not result.rows:
            lines.append("No eligible results in the requested scope and period.")
        for row in result.rows:
            dimensions = (
                ", ".join(f"{key}={value}" for key, value in row.dimensions.items()) or "total"
            )
            value = "null (zero denominator)" if row.value is None else str(row.value)
            unit = result.currency if result.unit == "currency" else result.unit
            lines.append(f"{dimensions}: {value} {unit}")
    return "\n".join(lines)


def _render_metadata(responses: list[ToolResponse]) -> str:
    lines = []
    for result in responses:
        if isinstance(result, DiscoverMetricsResponseV2):
            lines.append(
                "Available metrics: " + ", ".join(item.metric_id for item in result.metrics)
                if result.metrics
                else "No governed metrics match the requested search."
            )
        elif isinstance(result, DescribeMetricResponseV2):
            metric = result.metric
            lines.append(f"{metric.metric_id}: {metric.description} {metric.calculation}")
        elif isinstance(result, DiscoverDimensionsResponseV2):
            for dimension in result.dimensions:
                values = ", ".join(dimension.values) or "no authorized values"
                lines.append(f"{dimension.dimension.dimension_id}: {values}")
    return "\n".join(lines) or "No matching metadata was found."


class BedrockAnalyticsAgent:
    """Each run has isolated conversation/evidence; authorization is a separate trusted input."""

    def __init__(
        self,
        config: BedrockAgentConfig,
        *,
        client: ConverseClient,
        adapter: SemanticAdapter,
        dataset_version: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.client = client
        self.adapter = adapter
        self.dataset_version = dataset_version
        self.clock = clock

    def run(self, request: AgentRequest, *, context: AuthorizationContext) -> AgentResponse:
        if (
            not context.principal_id.strip()
            or not context.tenant_id.strip()
            or not context.allowed_regions
        ):
            raise AuthorizationError(
                "A trusted principal, tenant and nonempty region scope are required"
            )
        started = self.clock()
        deadline = started + self.config.timeout_seconds
        records: list[ToolCallRecord] = []
        results: list[QueryMetricResponseV2] = []
        metadata: list[ToolResponse] = []
        model_calls = input_tokens = output_tokens = 0
        last_tool_error: str | None = None
        diagnostic_start = len(getattr(self.adapter, "diagnostics", ()))

        def finish(
            status: Literal["answer", "clarification", "error"],
            answer: str,
            code: str | None = None,
        ) -> AgentResponse:
            diagnostics = getattr(self.adapter, "diagnostics", ())[diagnostic_start:]
            athena = tuple(
                cast(dict[str, object], asdict(item))
                for item in diagnostics
                if is_dataclass(item) and not isinstance(item, type)
            )
            versions = {result.metric_id: result.definition_version for result in results}
            for item in metadata:
                if isinstance(item, DescribeMetricResponseV2):
                    versions[item.metric.metric_id] = item.metric.definition_version
                elif isinstance(item, DiscoverMetricsResponseV2):
                    versions.update(
                        {metric.metric_id: metric.definition_version for metric in item.metrics}
                    )
            return AgentResponse(
                status=status,
                answer=answer,
                results=tuple(results),
                dataset_version=self.dataset_version,
                metric_versions=versions,
                error_code=code,
                diagnostics=AgentDiagnostics(
                    model_id=self.config.model_id,
                    configuration=self.config.model_dump(mode="json"),
                    model_calls=model_calls,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=max(0, int((self.clock() - started) * 1000)),
                    tool_calls=tuple(records),
                    athena=athena,
                ),
            )

        scope = question_scope(request.question, self.config.reference_date)
        if scope.clarification:
            return finish("clarification", scope.clarification)
        messages: list[dict[str, object]] = [
            {"role": "user", "content": [{"text": request.question}]}
        ]
        system = (
            "You are a governed retail analytics planner. Use only the supplied semantic tools. "
            "Never supply SQL, identity, tenant, or authorization arguments. Never guess a metric, "
            "period, grouping, filter, or comparison. Ask for clarification when uncertain. "
            "Use v2. Dates are UTC business dates, inclusive start and exclusive end. "
            f"Reference date: {self.config.reference_date.isoformat()}. "
            "A named calendar month spans its first day through the next month's first day. "
            "Financial/physical adjustments use the original order period with no as-of cutoff. "
            "Call tools for authoritative answers; do not calculate or invent numeric answers."
            " For discover_metrics, omit search: this agent returns the full catalog only."
        )
        system += " Validated request interpretation: " + json.dumps(
            {
                "metric_ids": scope.metric_ids,
                "periods": [period.model_dump(mode="json") for period in scope.periods],
                "group_by": scope.group_by,
                "dimension_filters": scope.filters,
                "metadata_question": scope.metadata,
            },
            separators=(",", ":"),
        )
        seen_ids: set[str] = set()

        def check_time() -> None:
            if self.clock() >= deadline:
                raise _LoopFailure("time_limit")

        def execute_call(name: str, identifier: str, supplied: object) -> dict[str, object]:
            """Use the same authorization, validation and evidence path for every tool."""
            nonlocal last_tool_error
            check_time()
            arguments: dict[str, object] = {}
            error_code: str | None = None
            try:
                parsed = validate_tool_request(name, supplied)
                arguments = parsed.model_dump(mode="json")
                self._validate_scope(parsed, scope)
                response_model = execute_tool(self.adapter, parsed, context=context)
                # Reject model_construct/adapter corruption at this boundary too.
                response_model = type(response_model).model_validate_json(
                    response_model.model_dump_json()
                )
                if isinstance(parsed, QueryMetricRequestV2) and (
                    not isinstance(response_model, QueryMetricResponseV2)
                    or response_model.metric_id != parsed.metric_id
                    or response_model.time_range != parsed.time_range
                    or response_model.group_by != parsed.group_by
                ):
                    raise _LoopFailure("invalid_tool_response")
                if isinstance(response_model, QueryMetricResponseV2):
                    results.append(response_model)
                else:
                    metadata.append(response_model)
                payload_result: dict[str, object] = response_model.model_dump(mode="json")
            except _LoopFailure as exc:
                records.append(
                    ToolCallRecord(
                        tool_use_id=identifier,
                        name=name,
                        arguments=arguments,
                        status="error",
                        error_code=exc.code,
                    )
                )
                raise
            except (ValidationError, ValueError):
                error_code = "invalid_tool_arguments" if name in REQUEST_MODELS else "unknown_tool"
                payload_result = {
                    "error": error_code,
                    "message": (
                        "Use a listed tool and its v2 schema, matching the user's "
                        "metric, period, grouping and filters."
                    ),
                }
            except SemanticError as exc:
                error_code = type(exc).__name__
                payload_result = {
                    "error": error_code,
                    "message": (
                        "The governed request could not be completed; missing sources, "
                        "unsupported metrics and authorization restrictions must "
                        "not be bypassed."
                    ),
                }
            except Exception:
                error_code = "tool_error"
                payload_result = {
                    "error": error_code,
                    "message": "The governed tool failed; no result is available.",
                }
            records.append(
                ToolCallRecord(
                    tool_use_id=identifier,
                    name=name,
                    arguments=arguments,
                    status="error" if error_code else "success",
                    error_code=error_code,
                )
            )
            check_time()
            if error_code:
                last_tool_error = error_code
            return {
                "toolResult": {
                    "toolUseId": identifier,
                    "status": "error" if error_code else "success",
                    "content": [{"json": payload_result}],
                }
            }

        try:
            for _ in range(self.config.max_iterations):
                check_time()
                payload: dict[str, object] = {
                    "modelId": self.config.model_id,
                    "messages": messages,
                    "system": [{"text": system}],
                    "toolConfig": _tool_configuration(),
                }
                # Reserve a conservative UTF-8 byte bound for input plus protocol overhead.
                # Reported provider usage remains authoritative and is checked after each call.
                reserve = (
                    len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
                    + 256
                )
                remaining = self.config.max_total_tokens - input_tokens - output_tokens - reserve
                if remaining <= 0:
                    raise _LoopFailure("token_limit")
                payload["inferenceConfig"] = {
                    "maxTokens": min(self.config.max_output_tokens, remaining),
                    "temperature": 0,
                }
                model_calls += 1
                try:
                    response = _mapping(self.client.converse(**payload))
                except _LoopFailure:
                    raise
                except Exception as exc:
                    raise _LoopFailure("model_error") from exc
                usage = _mapping(response.get("usage"))
                current_input = _integer(usage.get("inputTokens"))
                current_output = _integer(usage.get("outputTokens"))
                if _integer(usage.get("totalTokens")) != current_input + current_output:
                    raise _LoopFailure("malformed_model_response")
                input_tokens += current_input
                output_tokens += current_output
                check_time()
                if current_output > min(self.config.max_output_tokens, remaining):
                    raise _LoopFailure("token_limit")
                if input_tokens + output_tokens > self.config.max_total_tokens:
                    raise _LoopFailure("token_limit")
                output = _mapping(response.get("output"))
                message = _mapping(output.get("message"))
                content = message.get("content")
                if (
                    message.get("role") != "assistant"
                    or not isinstance(content, list)
                    or not content
                ):
                    raise _LoopFailure("malformed_model_response")
                calls: list[dict[str, object]] = []
                for raw in content:
                    block = _mapping(raw)
                    if set(block) == {"toolUse"}:
                        call = _mapping(block["toolUse"])
                        identifier, name = call.get("toolUseId"), call.get("name")
                        if (
                            not isinstance(identifier, str)
                            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier)
                            or identifier in seen_ids
                        ):
                            raise _LoopFailure("malformed_tool_use")
                        if not isinstance(name, str) or not name or "input" not in call:
                            raise _LoopFailure("malformed_tool_use")
                        seen_ids.add(identifier)
                        calls.append(call)
                    elif set(block) != {"text"} or not isinstance(block["text"], str):
                        raise _LoopFailure("malformed_model_response")
                stop = response.get("stopReason")
                if stop == "tool_use":
                    if not calls:
                        raise _LoopFailure("malformed_tool_use")
                    if len(records) + len(calls) > self.config.max_tool_calls:
                        raise _LoopFailure("tool_limit")
                    messages.append(message)
                    tool_results: list[dict[str, object]] = []
                    for call in calls:
                        tool_results.append(
                            execute_call(str(call["name"]), str(call["toolUseId"]), call["input"])
                        )
                    messages.append({"role": "user", "content": tool_results})
                elif stop == "end_turn" and not calls:
                    if results:
                        actual = {
                            (item.metric_id, item.time_range.start, item.time_range.end)
                            for item in results
                        }
                        required = {
                            (metric, period.start, period.end)
                            for metric in scope.metric_ids
                            for period in scope.periods
                        }
                        if not required <= actual:
                            return finish(
                                "error",
                                "Some requested metric or comparison results are unavailable.",
                                "incomplete_tool_results",
                            )
                        return finish("answer", _render(results))
                    if scope.metadata and metadata:
                        return finish("answer", _render_metadata(metadata))
                    if last_tool_error:
                        return finish(
                            "error",
                            "The governed request could not be completed: " + last_tool_error,
                            last_tool_error,
                        )
                    if not scope.metadata and scope.metric_ids and scope.periods:
                        # The question guard already resolved the complete numeric plan.
                        # A model's text-only turn is not evidence of user ambiguity.
                        # Execute that plan once, without another model call or guessed values.
                        planned = tuple(
                            QueryMetricRequestV2(
                                metric_id=metric,
                                time_range=period,
                                group_by=scope.group_by,
                                dimension_filters=scope.filters,
                            )
                            for metric in scope.metric_ids
                            for period in scope.periods
                        )
                        if len(records) + len(planned) > self.config.max_tool_calls:
                            raise _LoopFailure("tool_limit")
                        for parsed in planned:
                            number = len(records) + 1
                            identifier = f"resolved-plan-{number}"
                            while identifier in seen_ids:
                                number += 1
                                identifier = f"resolved-plan-{number}"
                            seen_ids.add(identifier)
                            # These IDs identify actual server-planned work, not model toolUse
                            # messages. Do not append fabricated model turns to conversation.
                            execute_call("query_metric", identifier, parsed.model_dump(mode="json"))
                            if last_tool_error:
                                return finish(
                                    "error",
                                    "The governed request could not be completed: "
                                    + last_tool_error,
                                    last_tool_error,
                                )
                        return finish("answer", _render(results))
                    return finish(
                        "clarification",
                        "Please clarify the requested metric, period, grouping, or comparison.",
                    )
                else:
                    raise _LoopFailure("token_limit" if stop == "max_tokens" else "model_stopped")
            raise _LoopFailure("iteration_limit")
        except _LoopFailure as exc:
            return finish("error", "The analytics request stopped safely: " + exc.code, exc.code)

    @staticmethod
    def _validate_scope(request: BaseModel, scope: QuestionScope) -> None:
        if isinstance(request, DiscoverMetricsRequestV2) and request.search is not None:
            raise ValueError("Agent catalog discovery requires an unfiltered request")
        if isinstance(request, QueryMetricRequestV2):
            scope.validate_query(request)
        elif isinstance(request, (DescribeMetricRequestV2, DiscoverDimensionsRequestV2)):
            if scope.metric_ids and request.metric_id not in scope.metric_ids:
                raise ValueError("Metadata metric was not requested")
