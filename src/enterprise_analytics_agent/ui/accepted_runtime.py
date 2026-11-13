"""Explicit AWS-only rebinding of the accepted Nova release; no new allowance."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_analytics_agent.ui.models import UiError

type Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
SHARED_REVIEW_SHA256 = "385f936a719ca17ee09fe4c62af7d7153d04e8cc9d6ee3e2aaf7bd7defa8bbc8"


class AcceptedRuntimeReview(BaseModel):
    """Trusted operator configuration, never a browser payload or new live quota.

    This separate approval changes the source-evidence requirement for AWS-only
    transport. The old shared review, release record and ledger remain unchanged.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ui-accepted-runtime-v1"] = "ui-accepted-runtime-v1"
    binding_id: Literal["accepted-nova-interactive02-v1"] = "accepted-nova-interactive02-v1"
    evidence_mode: Literal["aws-only-frozen-archive"] = "aws-only-frozen-archive"
    profile: Literal["analytics-dev"] = "analytics-dev"
    account: Literal["453711491609"] = "453711491609"
    region: Literal["us-west-2"] = "us-west-2"
    shared_review_path: Literal["evaluations/ui-shared/interactive-02.proposed.json"]
    shared_review_file_sha256: Sha256
    shared_review_sha256: Literal[
        "385f936a719ca17ee09fe4c62af7d7153d04e8cc9d6ee3e2aaf7bd7defa8bbc8"
    ] = "385f936a719ca17ee09fe4c62af7d7153d04e8cc9d6ee3e2aaf7bd7defa8bbc8"
    release_record_path: Literal[
        "artifacts/ui-shared/interactive-02-preparation/release-record.json"
    ]
    release_record_file_sha256: Sha256
    runtime_version: Literal["15"] = "15"
    archive_path: Literal["artifacts/milestone-5/q18-repair-v1/candidate/agent.zip"]
    archive_sha256: Literal["398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1"]
    archive_bytes: Annotated[int, Field(strict=True, gt=0)]
    archive_source_sha256: Literal[
        "aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be"
    ]
    archive_manifest_sha256: Sha256
    operator_source_sha256: Sha256
    canonical_directory: Literal["artifacts/milestone-5/canonical/retail-v1"]
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("accepted runtime expiry requires a timezone")
        return value.astimezone(UTC)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()


class AcceptedRuntimeApproval(BaseModel):
    """A separately supplied approval; preparation does not manufacture this file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ui-accepted-runtime-approval-v1"] = "ui-accepted-runtime-approval-v1"
    approved: Literal[True]
    scope: Literal["aws-only-existing-interactive02-questions"]
    review_sha256: Sha256
    approved_at: datetime
    expires_at: datetime

    @field_validator("approved_at", "expires_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approval timestamps require a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.approved_at >= self.expires_at:
            raise ValueError("approval must precede its expiry")
        return self


def checked_path(root: Path, value: str) -> Path:
    path = root / value
    if path.resolve() != path or not path.is_relative_to(root):
        raise UiError("Accepted-runtime inputs must be unaliased checkout paths.")
    return path


def verify_approval(
    review: AcceptedRuntimeReview, approval: AcceptedRuntimeApproval, now: datetime
) -> None:
    if (
        approval.review_sha256 != review.sha256
        or approval.expires_at != review.expires_at
        or now < approval.approved_at
        or now >= review.expires_at
    ):
        raise UiError("The separate AWS-only runtime approval is missing, changed or expired.")
