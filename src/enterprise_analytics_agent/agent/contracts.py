"""Application contracts; authorization is deliberately absent from request payloads."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from enterprise_analytics_agent.contracts_v2 import QueryMetricResponseV2


class AgentContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentRequest(AgentContract):
    question: Annotated[str, Field(min_length=1, max_length=4000)]

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class ToolCallRecord(AgentContract):
    tool_use_id: str
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    status: Literal["success", "error"]
    error_code: str | None = None


class AgentDiagnostics(AgentContract):
    """Operational evidence, never accepted as semantic or authorization arguments."""

    model_id: str
    configuration: dict[str, object] = Field(default_factory=dict)
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    tool_calls: tuple[ToolCallRecord, ...] = ()
    athena: tuple[dict[str, object], ...] = ()


class AgentResponse(AgentContract):
    api_version: Literal["agent-v1"] = "agent-v1"
    status: Literal["answer", "clarification", "error"]
    answer: str
    results: tuple[QueryMetricResponseV2, ...] = ()
    dataset_version: str
    metric_versions: dict[str, str] = Field(default_factory=dict)
    error_code: str | None = None
    diagnostics: AgentDiagnostics
