"""Explicit deployment inputs; synthesis never discovers account configuration."""

import re
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_analytics_agent.snapshots import validate_dataset_version


class SnapshotDefinition(BaseModel):
    """One immutable table set, with absent returns distinct from an empty table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str
    include_returns: bool = True

    @field_validator("dataset_version")
    @classmethod
    def require_snapshot_version(cls, value: str) -> str:
        return validate_dataset_version(value)


class DeploymentConfig(BaseModel):
    """Nonsecret, reviewed inputs shared by synth and deploy commands."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account: Annotated[str, Field(pattern=r"^\d{12}$")]
    profile: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
    region: Annotated[str, Field(pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-\d+$")]
    resource_prefix: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,31}$")]
    database_name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")]
    workgroup_name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9._-]{1,128}$")]
    trusted_loader_principal_arn: str
    trusted_query_principal_arn: str
    trusted_query_principal_arns: tuple[str, ...] = ()
    snapshots: Annotated[tuple[SnapshotDefinition, ...], Field(min_length=1)]
    data_bucket_name: str | None = None
    results_bucket_name: str | None = None
    table_prefix: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,15}$")] = "ea"
    bytes_scanned_cutoff_per_query: Annotated[
        int, Field(ge=10_485_760, le=7_000_000_000_000_000_000)
    ] = 10_485_760
    results_retention_days: Annotated[int, Field(ge=1, le=3650)] = 7
    incomplete_upload_cleanup_days: Annotated[int, Field(ge=1, le=7)] = 1
    scan_alarm_threshold_bytes: Annotated[int, Field(ge=1)] = 104_857_600

    @field_validator("trusted_loader_principal_arn", "trusted_query_principal_arn")
    @classmethod
    def require_specific_iam_principal(cls, value: str) -> str:
        """Never create an account-root, wildcard, or transient-session trust."""
        pattern = r"arn:aws(?:-us-gov|-cn)?:iam::\d{12}:(?:role|user)/[\w+=,.@/-]+"
        if not re.fullmatch(pattern, value):
            raise ValueError("trust must name one stable IAM role or user ARN")
        return value

    @field_validator("trusted_query_principal_arns")
    @classmethod
    def require_specific_additional_principals(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            cls.require_specific_iam_principal(value)
        if len(set(values)) != len(values):
            raise ValueError("additional query principals must be unique")
        return values

    @field_validator("data_bucket_name", "results_bucket_name")
    @classmethod
    def require_dns_bucket_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", value):
            raise ValueError("bucket names must be 3-63 lowercase letters, numbers, and hyphens")
        return value

    @model_validator(mode="after")
    def validate_snapshot_and_storage_scope(self) -> Self:
        if self.trusted_query_principal_arn in self.trusted_query_principal_arns:
            raise ValueError("additional query principals must not repeat the developer principal")
        versions = [snapshot.dataset_version for snapshot in self.snapshots]
        if len(set(versions)) != len(versions):
            raise ValueError("snapshot versions must be unique")
        if self.resolved_data_bucket_name == self.resolved_results_bucket_name:
            raise ValueError("source and Athena result buckets must be separate")
        self.require_dns_bucket_name(self.resolved_data_bucket_name)
        self.require_dns_bucket_name(self.resolved_results_bucket_name)
        return self

    @property
    def resolved_data_bucket_name(self) -> str:
        return self.data_bucket_name or f"{self.resource_prefix}-{self.account}-{self.region}-data"

    @property
    def resolved_results_bucket_name(self) -> str:
        return self.results_bucket_name or (
            f"{self.resource_prefix}-{self.account}-{self.region}-results"
        )
