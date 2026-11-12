"""Opt-in Bedrock presentation streaming over the unchanged governed agent loop.

Planning text is private. Only real provider characters matching the independently
rendered, validated answer may be published. The extra presentation call is explicit
and shares the per-question call/token/deadline budget, with no retries.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
    ConverseClient,
    _complete_numeric_plan,
    _render,
)
from enterprise_analytics_agent.adapters.bedrock_word_stream import (
    ConverseStreamClient,
    ProfiledConverseClient,
    consume_presentation,
)
from enterprise_analytics_agent.agent.contracts import AgentDiagnostics, AgentRequest, AgentResponse
from enterprise_analytics_agent.agent.questions import question_scope
from enterprise_analytics_agent.contracts import AuthorizationContext


class StreamingLimitError(RuntimeError):
    """Authored error; never embeds a prompt, provider response or credentials."""


@dataclass(frozen=True)
class StreamingLimits:
    planning_calls: int = 5
    total_calls: int = 6
    total_tokens: int = 12000
    planning_tokens: int = 10000
    presentation_output_tokens: int = 1024

    def __post_init__(self) -> None:
        if (
            not 1 <= self.planning_calls < self.total_calls <= 6
            or not 256 <= self.planning_tokens < self.total_tokens <= 12000
            or not 1 <= self.presentation_output_tokens <= 4096
        ):
            raise ValueError(
                "Streaming limits must reserve one presentation call and token budget."
            )


@dataclass
class CallTrace:
    """Request-local accounting; an operator may inject a durable reserve/event sink."""

    limits: StreamingLimits
    deadline: float
    clock: Callable[[], float] = time.monotonic
    record: Callable[[dict[str, object]], None] = lambda event: None
    calls: list[dict[str, object]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    failed: bool = False

    def begin(self, operation: str, *, presentation: bool = False) -> int:
        if self.failed or self.clock() >= self.deadline:
            raise StreamingLimitError("The model attempt or deadline is closed; no call was sent.")
        ceiling = self.limits.total_calls if presentation else self.limits.planning_calls
        if len(self.calls) >= ceiling:
            raise StreamingLimitError("The reviewed model-call ceiling was reached.")
        number = len(self.calls) + 1
        event = {"event": "reserved", "operation": operation, "number": number}
        self.record(event)  # Must succeed durably before any billable dispatch.
        self.calls.append({**event, "status": "reserved"})
        return number

    def finish(
        self, number: int, *, input_tokens: int, output_tokens: int, error: str | None = None
    ) -> None:
        if any(type(value) is not int or value < 0 for value in (input_tokens, output_tokens)):
            error = "invalid_usage"
            input_tokens = output_tokens = 0
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        if self.input_tokens + self.output_tokens > self.limits.total_tokens:
            error = "token_limit"
        self.failed = self.failed or error is not None
        event: dict[str, object] = {
            "event": "failed" if error else "returned",
            "number": number,
            "operation": self.calls[number - 1]["operation"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "usage_complete": error is None,
        }
        if error:
            event["error_type"] = error
        self.record(event)
        self.calls[number - 1].update(event, status=event["event"])
        if error == "token_limit":
            raise StreamingLimitError("The reviewed combined token ceiling was reached.")


class _CountedPlanner:
    def __init__(self, client: ConverseClient, trace: CallTrace, operation: str) -> None:
        self.client, self.trace, self.operation = client, trace, operation

    def converse(self, **kwargs: object) -> dict[str, object]:
        number = self.trace.begin(self.operation)
        try:
            response = self.client.converse(**kwargs)
            usage = response.get("usage")
            if not isinstance(usage, dict):
                raise StreamingLimitError("The model omitted its usage record.")
            incoming, outgoing = usage.get("inputTokens"), usage.get("outputTokens")
            if (
                type(incoming) is not int
                or incoming < 0
                or type(outgoing) is not int
                or outgoing < 0
                or usage.get("totalTokens") != incoming + outgoing
            ):
                raise StreamingLimitError("The model returned an invalid usage record.")
        except BaseException as exc:
            self.trace.finish(number, input_tokens=0, output_tokens=0, error=type(exc).__name__)
            raise
        self.trace.finish(number, input_tokens=incoming, output_tokens=outgoing)
        return response


@dataclass(frozen=True)
class StreamingOutcome:
    response: AgentResponse
    presentation: Literal["streamed", "fallback", "not_needed"]
    reason: str | None
    words: int
    calls: tuple[dict[str, object], ...]


class StreamingAnalyticsAgent:
    """One existing semantic loop plus a bounded, canonical-prefix-checked stream."""

    def __init__(
        self,
        agent: BedrockAnalyticsAgent,
        *,
        presentation_client: ConverseStreamClient,
        allow_temperature: bool = True,
        planner_operation: str = "Converse",
        presentation_operation: str = "ConverseStream",
        limits: StreamingLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.agent, self.presentation_client = agent, presentation_client
        self.allow_temperature = allow_temperature
        self.planner_operation, self.presentation_operation = (
            planner_operation,
            presentation_operation,
        )
        self.limits, self.clock = limits or StreamingLimits(), clock

    def run(
        self,
        request: AgentRequest,
        *,
        context: AuthorizationContext,
        on_word: Callable[[str], None],
        record: Callable[[dict[str, object]], None] = lambda event: None,
        on_verified: Callable[[AgentResponse], None] | None = None,
    ) -> StreamingOutcome:
        started = self.clock()
        trace = CallTrace(
            self.limits, started + self.agent.config.timeout_seconds, self.clock, record
        )
        config = BedrockAgentConfig.model_validate(
            {
                **self.agent.config.model_dump(),
                "max_iterations": self.limits.planning_calls,
                "max_total_tokens": self.limits.planning_tokens,
            }
        )
        # Fresh wrapper/history for every run. Never mutate/reconfigure the shared
        # original instance or carry private provider reasoning between sessions.
        client = ProfiledConverseClient(self.agent.client, allow_temperature=self.allow_temperature)
        planner = BedrockAnalyticsAgent(
            config,
            client=_CountedPlanner(client, trace, self.planner_operation),
            adapter=self.agent.adapter,
            dataset_version=self.agent.dataset_version,
            clock=self.clock,
            complete_on_planning_limit=True,
        )
        response = planner.run(request, context=context)
        response = AgentResponse.model_validate(response.model_dump(mode="python", warnings=False))
        # Sequential-tool models may use their fifth planning turn to obtain
        # the fifth metric. Do not spend a sixth planning call just to request
        # end_turn. Complete only an exact, wholly successful governed plan;
        # every other exhausted/error/partial response remains an error.
        if (
            response.error_code == "iteration_limit"
            and not trace.failed
            and self.clock() < trace.deadline
        ):
            response = self._complete_plan(request, response)
        if (
            response.status == "answer"
            and response.results
            and not _complete_numeric_plan(
                question_scope(request.question, config.reference_date),
                response.diagnostics.tool_calls,
                response.results,
            )
        ):
            response = AgentResponse.model_validate(
                {
                    **response.model_dump(mode="python"),
                    "status": "error",
                    "error_code": "invalid_tool_response",
                    "answer": "The semantic evidence does not match the complete governed request.",
                }
            )
        if (
            response.status == "answer"
            and response.results
            and response.answer != _render(list(response.results))
        ):
            raise StreamingLimitError("The numeric answer differs from validated semantic results.")
        if on_verified is not None:
            on_verified(response)
        words = 0

        def publish(text: str) -> None:
            nonlocal words
            on_word(text)
            words += 1

        presentation: Literal["streamed", "fallback", "not_needed"] = "not_needed"
        reason = None
        if response.status == "answer" and response.answer:
            payload: dict[str, object] = {
                "modelId": config.model_id,
                "system": [
                    {
                        "text": (
                            "Copy the supplied verified answer exactly, "
                            "preserving every character, "
                            "number, unit, date, space and newline. Output only that text. "
                            "Do not add commentary, markdown fences or calculations."
                        )
                    }
                ],
                "messages": [{"role": "user", "content": [{"text": response.answer}]}],
            }
            reserved_input = len(json.dumps(payload, ensure_ascii=False).encode()) + 256
            remaining = self.limits.total_tokens - trace.input_tokens - trace.output_tokens
            maximum = min(self.limits.presentation_output_tokens, remaining - reserved_input)
            if maximum <= 0 or trace.failed or self.clock() >= trace.deadline:
                presentation, reason = "fallback", "presentation_budget_unavailable"
            else:
                inference: dict[str, Any] = {"maxTokens": maximum}
                if self.allow_temperature:
                    inference["temperature"] = 0
                payload["inferenceConfig"] = inference
                number = trace.begin(self.presentation_operation, presentation=True)
                try:
                    streamed = consume_presentation(
                        self.presentation_client,
                        payload,
                        response.answer,
                        publish,
                        clock=self.clock,
                        deadline=trace.deadline,
                    )
                except BaseException as exc:
                    trace.finish(number, input_tokens=0, output_tokens=0, error=type(exc).__name__)
                    if not isinstance(exc, Exception):
                        raise
                    presentation, reason = "fallback", "presentation_stream_rejected"
                else:
                    trace.finish(
                        number,
                        input_tokens=streamed.input_tokens,
                        output_tokens=streamed.output_tokens,
                    )
                    presentation = "streamed"
        diagnostic = AgentDiagnostics.model_validate(
            {
                **response.diagnostics.model_dump(mode="python"),
                "model_calls": len(trace.calls),
                "input_tokens": trace.input_tokens,
                "output_tokens": trace.output_tokens,
                "latency_ms": max(0, int((self.clock() - started) * 1000)),
                "configuration": {
                    **config.model_dump(mode="json"),
                    "streaming_total_calls": self.limits.total_calls,
                    "streaming_total_tokens": self.limits.total_tokens,
                    "presentation_output_tokens": self.limits.presentation_output_tokens,
                },
            }
        )
        # The canonical answer/results stay authoritative even when a stream fails.
        # No failed stream is retried, replaced by another model, or faked in the UI.
        final = AgentResponse.model_validate(
            {**response.model_dump(mode="python"), "diagnostics": diagnostic.model_dump()}
        )
        return StreamingOutcome(final, presentation, reason, words, tuple(trace.calls))

    def _complete_plan(self, request: AgentRequest, response: AgentResponse) -> AgentResponse:
        scope = question_scope(request.question, self.agent.config.reference_date)
        if not _complete_numeric_plan(scope, response.diagnostics.tool_calls, response.results):
            return response
        return AgentResponse.model_validate(
            {
                **response.model_dump(mode="python"),
                "status": "answer",
                "error_code": None,
                "answer": _render(list(response.results)),
            }
        )
