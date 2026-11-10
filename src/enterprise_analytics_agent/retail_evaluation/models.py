"""Versioned operator-side cases and expectations, separate from public agent contracts."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enterprise_analytics_agent.agent.contracts import AgentRequest
from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2, QueryMetricResponseV2

PROFILE = "analytics-dev"
ACCOUNT = "453711491609"
REGION = "us-west-2"
MODEL_ID = "us.amazon.nova-lite-v1:0"
type CaseKind = Literal["metric", "clarification", "authorization", "metadata"]


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetailTarget(EvaluationModel):
    """Local operator selection; never sent as part of a question or authorization payload."""

    profile: Literal["analytics-dev"] = "analytics-dev"
    account: Literal["453711491609"] = "453711491609"
    region: Literal["us-west-2"] = "us-west-2"
    runtime_arn: Annotated[
        str,
        Field(
            pattern=r"^arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
            r"enterprise_analytics_dev_agent-[A-Za-z0-9]{10}$"
        ),
    ]
    qualifier: Literal["DEFAULT"] = "DEFAULT"
    model_id: Literal["us.amazon.nova-lite-v1:0"] = "us.amazon.nova-lite-v1:0"
    dataset_version: Literal["retail-v1", "parity-v1"]
    reference_date: date

    @model_validator(mode="after")
    def approved_reference_date(self) -> Self:
        expected = date(2025, 4, 1) if self.dataset_version == "retail-v1" else date(2025, 2, 1)
        if self.reference_date != expected:
            raise ValueError("reference_date differs from the reviewed dataset configuration")
        return self


class RetailCase(EvaluationModel):
    id: Annotated[str, Field(pattern=r"^(Q[0-9]{2}|S01[AB])$")]
    question: str
    kind: CaseKind
    expected_queries: tuple[QueryMetricRequestV2, ...] = ()
    operation: Literal["discover_metrics", "describe_metric", "discover_dimensions"] | None = None
    metric_id: str | None = None
    session_group: Literal["S01"] | None = None
    tags: tuple[str, ...] = ()
    safe_error_codes: tuple[str, ...] = ("invalid_tool_arguments", "AuthorizationError")

    @model_validator(mode="after")
    def complete_case(self) -> Self:
        AgentRequest(question=self.question)
        if self.kind == "metric" and not self.expected_queries:
            raise ValueError("a metric case requires complete structured requests")
        if self.kind in {"clarification", "metadata"} and self.expected_queries:
            raise ValueError("clarification/metadata cases cannot require metric queries")
        if (self.kind == "metadata") != (self.operation is not None):
            raise ValueError("only metadata cases require a metadata operation")
        if self.operation in {"describe_metric", "discover_dimensions"} and not self.metric_id:
            raise ValueError("this metadata operation requires an intended metric")
        if bool(self.session_group) != self.id.startswith("S01"):
            raise ValueError("only the two S01 cases share a session")
        return self


class RetailSuite(EvaluationModel):
    schema_version: Literal["retail-suite-v1"] = "retail-suite-v1"
    suite_version: Literal["retail-v1"] = "retail-v1"
    dataset_version: Literal["retail-v1"] = "retail-v1"
    reference_date: date = date(2025, 4, 1)
    cases: tuple[RetailCase, ...]

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("case IDs must be unique")
        if self.reference_date != date(2025, 4, 1):
            raise ValueError("retail suite uses the pinned April 1 reference date")
        return self


class GoldenCase(EvaluationModel):
    case_id: str
    results: tuple[QueryMetricResponseV2, ...] = ()


class RetailGolden(EvaluationModel):
    schema_version: Literal["retail-golden-v1"] = "retail-golden-v1"
    dataset_version: Literal["retail-v1"] = "retail-v1"
    manifest_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    cases: tuple[GoldenCase, ...]

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("golden case IDs must be unique")
        return self
