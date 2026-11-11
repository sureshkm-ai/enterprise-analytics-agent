"""Browser input and presentation envelopes, separate from semantic contracts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse


class AskRequest(AgentRequest):
    mode: Literal["local", "local_agent", "live"] = "local"
    request_id: UUID


class UiResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["local", "local_agent", "replay", "live"]
    response: AgentResponse
    elapsed_ms: Annotated[int, Field(ge=0)] | None = None
    metadata: list[dict[str, object]] = Field(default_factory=list)
    unreported_diagnostics: tuple[str, ...] = ()


def unreported_diagnostics(response: AgentResponse) -> tuple[str, ...]:
    return tuple(
        field
        for field in ("model_calls", "input_tokens", "output_tokens", "latency_ms")
        if field not in response.diagnostics.model_fields_set
    )


class UiError(RuntimeError):
    """Only these authored messages may cross the browser error boundary."""
