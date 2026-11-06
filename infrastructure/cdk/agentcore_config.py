"""Explicit, nonsecret inputs for the reviewed AgentCore development resources."""

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_analytics_agent.snapshots import validate_dataset_version
from infrastructure.cdk.config import DeploymentConfig


class AgentCoreDeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account: Annotated[str, Field(pattern=r"^[0-9]{12}$")]
    profile: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
    region: Annotated[str, Field(pattern=r"^[a-z]{2}-[a-z]+-[0-9]+$")]
    resource_prefix: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,31}$")]
    runtime_name: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,47}$")]
    approved_caller_arns: Annotated[tuple[str, ...], Field(min_length=1)]
    model_id: Annotated[str, Field(min_length=1, max_length=256)]
    model_resource_arns: Annotated[tuple[str, ...], Field(min_length=1)]
    query_role_arn: str
    artifact_path: str
    artifact_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    runtime_config_path: str
    artifact_s3_version_id: str | None = None
    dataset_version_override: str | None = None
    code_bucket_name: str | None = None
    idle_session_timeout_seconds: Annotated[int, Field(ge=60, le=900)] = 300
    max_lifetime_seconds: Annotated[int, Field(ge=60, le=3600)] = 900
    log_retention_days: Annotated[int, Field(ge=1, le=365)] = 7

    @field_validator("dataset_version_override")
    @classmethod
    def safe_snapshot_override(cls, value: str | None) -> str | None:
        return validate_dataset_version(value) if value is not None else None

    @field_validator("query_role_arn")
    @classmethod
    def specific_query_role(cls, value: str) -> str:
        DeploymentConfig.require_specific_iam_principal(value)
        if ":role/" not in value:
            raise ValueError("query access must name an IAM role")
        return value

    @field_validator("approved_caller_arns")
    @classmethod
    def specific_callers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            DeploymentConfig.require_specific_iam_principal(value)
        if len(set(values)) != len(values):
            raise ValueError("approved callers must be unique")
        return values

    @field_validator("model_resource_arns")
    @classmethod
    def exact_model_resources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        pattern = (
            r"arn:aws:bedrock:[a-z]{2}-[a-z]+-[0-9]+:(?:[0-9]{12})?:"
            r"(?:foundation-model|inference-profile|application-inference-profile)/[A-Za-z0-9._:-]+"
        )
        if any(re.fullmatch(pattern, value) is None for value in values):
            raise ValueError("model permissions must name exact Bedrock resource ARNs")
        if len(set(values)) != len(values):
            raise ValueError("model resource ARNs must be unique")
        return values

    @model_validator(mode="after")
    def valid_scope(self) -> Self:
        DeploymentConfig.require_dns_bucket_name(self.resolved_code_bucket_name)
        if not self.query_role_arn.startswith(f"arn:aws:iam::{self.account}:role/"):
            raise ValueError("query role must belong to the configured account")
        if self.idle_session_timeout_seconds > self.max_lifetime_seconds:
            raise ValueError("idle timeout cannot exceed session lifetime")
        return self

    @property
    def resolved_code_bucket_name(self) -> str:
        return self.code_bucket_name or (
            f"{self.resource_prefix}-{self.account}-{self.region}-agent-code"
        )

    @property
    def artifact_key(self) -> str:
        return f"releases/{self.artifact_sha256}/agent.zip"

    @property
    def runtime_role_arn(self) -> str:
        return f"arn:aws:iam::{self.account}:role/{self.resource_prefix}-agent-runtime"

    @property
    def log_group_prefix(self) -> str:
        return f"/aws/bedrock-agentcore/runtimes/{self.runtime_name}-"

    def validate_artifact(self) -> Path:
        """Runtime synthesis requires the actual reviewed archive, never a placeholder."""
        path = Path(self.artifact_path)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != self.artifact_sha256:
            raise ValueError("runtime archive checksum differs from the reviewed configuration")
        if len(content) > 250_000_000:
            raise ValueError("runtime archive exceeds AgentCore's compressed size limit")
        with zipfile.ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist()) > 750_000_000:
                raise ValueError("runtime archive exceeds AgentCore's unpacked size limit")
            required = {
                "runtime_entry.py",
                "runtime-config.json",
                "enterprise_analytics_agent/__init__.py",
            }
            if not required <= set(archive.namelist()):
                raise ValueError("runtime archive lacks the required entry point/config/package")
        return path

    def runtime_settings_json(self) -> str:
        """Cross-check deployment policy inputs against the server-only runtime scope."""
        from enterprise_analytics_agent.hosting.config import RuntimeSettings

        settings = RuntimeSettings.model_validate_json(Path(self.runtime_config_path).read_text())
        expected = (self.account, self.region, self.model_id, self.query_role_arn)
        actual = (settings.account, settings.region, settings.model_id, settings.query_role_arn)
        if actual != expected:
            raise ValueError("runtime account/region/model/query role differ from infrastructure")
        # JSON, not model-visible arguments; it contains no profile or credentials.
        return json.dumps(settings.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
