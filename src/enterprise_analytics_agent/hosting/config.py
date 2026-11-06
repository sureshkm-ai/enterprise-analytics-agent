"""Server-owned development scope and workload configuration, never tool arguments."""

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.snapshots import validate_dataset_version


class RuntimeSettings(BaseModel):
    """An IAM-authenticated development endpoint serves one fixed authorization scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account: Annotated[str, Field(pattern=r"^[0-9]{12}$")]
    region: Annotated[str, Field(pattern=r"^[a-z]{2}-[a-z]+-[0-9]+$")]
    model_id: Annotated[str, Field(min_length=1, max_length=2048)]
    query_role_arn: Annotated[str, Field(pattern=r"^arn:aws:iam::[0-9]{12}:role/[\w+=,.@/-]+$")]
    database: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")]
    workgroup: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
    source_bucket: str
    results_bucket: str
    dataset_version: str = "parity-v1"
    table_prefix: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,15}$")] = "ea"
    reference_date: date
    principal_id: Annotated[str, Field(min_length=1, max_length=200)]
    tenant_id: Annotated[str, Field(min_length=1, max_length=200)]
    allowed_regions: Annotated[tuple[str, ...], Field(min_length=1, max_length=100)]
    max_iterations: Annotated[int, Field(ge=1, le=20)] = 6
    max_tool_calls: Annotated[int, Field(ge=1, le=50)] = 16
    max_output_tokens: Annotated[int, Field(ge=1, le=4096)] = 1024
    max_total_tokens: Annotated[int, Field(ge=1, le=100000)] = 12000
    timeout_seconds: Annotated[float, Field(gt=0, le=300, allow_inf_nan=False)] = 90.0
    query_timeout_seconds: Annotated[float, Field(gt=0, le=120, allow_inf_nan=False)] = 60.0
    max_payload_bytes: Annotated[int, Field(ge=1, le=65536)] = 16384

    @field_validator("source_bucket", "results_bucket")
    @classmethod
    def safe_bucket(cls, value: str) -> str:
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", value) is None:
            raise ValueError("bucket names must be lowercase DNS names without dots")
        return value

    @field_validator("dataset_version")
    @classmethod
    def safe_version(cls, value: str) -> str:
        return validate_dataset_version(value)

    @field_validator("principal_id", "tenant_id")
    @classmethod
    def meaningful_scope(cls, value: str) -> str:
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("authorization scope must contain meaningful text")
        return value

    @field_validator("allowed_regions")
    @classmethod
    def meaningful_regions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(not region.strip() for region in value):
            raise ValueError("regions must be nonempty and unique")
        return value

    @model_validator(mode="after")
    def consistent_target(self) -> Self:
        if self.query_role_arn.split(":")[4] != self.account:
            raise ValueError("query role must belong to the configured development account")
        if self.source_bucket == self.results_bucket:
            raise ValueError("source and results buckets must be separate")
        if self.query_timeout_seconds > self.timeout_seconds:
            raise ValueError("query timeout must not exceed the agent timeout")
        return self

    def authorization_context(self) -> AuthorizationContext:
        return AuthorizationContext(
            principal_id=self.principal_id,
            tenant_id=self.tenant_id,
            allowed_regions=self.allowed_regions,
        )


def load_settings(value: str | None = None) -> RuntimeSettings:
    """Read only trusted deployment configuration, not invocation headers/payloads."""
    source = (
        value
        if value is not None
        else os.environ.get("ANALYTICS_RUNTIME_CONFIG", "runtime-config.json")
    )
    content = source if source.lstrip().startswith("{") else Path(source).read_text()
    payload = json.loads(content)
    # This environment is deployment-owned, never populated from a request.
    override = os.environ.get("ANALYTICS_DATASET_VERSION")
    if override is not None:
        payload["dataset_version"] = validate_dataset_version(override)
    return RuntimeSettings.model_validate(payload)
