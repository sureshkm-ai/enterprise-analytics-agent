"""Explicit development sessions; importing this module never contacts AWS."""

import json
from pathlib import Path
from typing import Annotated, Literal

import boto3
from botocore.config import Config
from pydantic import BaseModel, ConfigDict, Field, field_validator

from enterprise_analytics_agent.errors import SemanticError
from enterprise_analytics_agent.snapshots import validate_dataset_version

SDK_CONFIG = Config(
    connect_timeout=5,
    read_timeout=15,
    retries={"mode": "standard", "total_max_attempts": 3},
)
ATHENA_SDK_CONFIG = Config(
    connect_timeout=5, read_timeout=10, retries={"mode": "standard", "total_max_attempts": 1}
)


class AWSConfigurationError(SemanticError):
    """An explicit development configuration or account check failed."""


class SnapshotTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str
    include_returns: bool = True

    @field_validator("dataset_version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        return validate_dataset_version(value)


class AWSRuntimeConfig(BaseModel):
    """Read the nonsecret deployment inputs without importing CDK into the adapter."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    profile: Annotated[str, Field(min_length=1, pattern=r"^\S+$")]
    account: Annotated[str, Field(pattern=r"^[0-9]{12}$")]
    region: Annotated[str, Field(pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+$")]
    resource_prefix: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,31}$")]
    database_name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")]
    workgroup_name: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
    snapshots: Annotated[tuple[SnapshotTarget, ...], Field(min_length=1)]
    data_bucket_name: str | None = None
    results_bucket_name: str | None = None
    table_prefix: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,15}$")] = "ea"
    bytes_scanned_cutoff_per_query: Annotated[int, Field(ge=10_485_760)] = 10_485_760

    @property
    def source_bucket(self) -> str:
        return self.data_bucket_name or f"{self.resource_prefix}-{self.account}-{self.region}-data"

    @property
    def results_bucket(self) -> str:
        return (
            self.results_bucket_name
            or f"{self.resource_prefix}-{self.account}-{self.region}-results"
        )

    def role_arn(self, purpose: Literal["loader", "query"]) -> str:
        role = "dataset-loader" if purpose == "loader" else "query-executor"
        return f"arn:aws:iam::{self.account}:role/{self.resource_prefix}-{role}"

    def target(self, dataset_version: str) -> SnapshotTarget:
        validate_dataset_version(dataset_version)
        for snapshot in self.snapshots:
            if snapshot.dataset_version == dataset_version:
                return snapshot
        raise AWSConfigurationError("Dataset version is not in the reviewed deployment inventory")


def load_runtime_config(path: Path) -> AWSRuntimeConfig:
    """Require a file and explicit profile; environment/default profile is never used."""
    try:
        return AWSRuntimeConfig.model_validate(json.loads(path.read_text()))
    except (OSError, ValueError) as exc:
        raise AWSConfigurationError(f"Invalid AWS development configuration: {path}") from exc


def session_for_role(
    config: AWSRuntimeConfig, purpose: Literal["loader", "query"]
) -> boto3.Session:
    """Verify the selected account, then assume only the corresponding narrow role.

    Credentials remain in SDK memory and are never logged or returned to a tool.
    The 15-minute session is sufficient for small development publication/parity runs.
    """
    base = boto3.Session(profile_name=config.profile, region_name=config.region)
    sts = base.client("sts", config=SDK_CONFIG)
    identity = sts.get_caller_identity()
    if identity["Account"] != config.account:
        raise AWSConfigurationError("Selected AWS profile resolves to a different account")
    assumed = sts.assume_role(
        RoleArn=config.role_arn(purpose),
        RoleSessionName=f"analytics-{purpose}",
        DurationSeconds=900,
    )["Credentials"]
    return boto3.Session(
        aws_access_key_id=assumed["AccessKeyId"],
        aws_secret_access_key=assumed["SecretAccessKey"],
        aws_session_token=assumed["SessionToken"],
        region_name=config.region,
    )
