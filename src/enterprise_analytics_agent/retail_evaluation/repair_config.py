"""Reviewed repair artifacts and upload-version bindings, independent of AWS SDK types."""

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from enterprise_analytics_agent.retail_evaluation.campaign import (
    CODE_SHA256,
    RepairCampaignBinding,
)
from enterprise_analytics_agent.retail_evaluation.deployment import (
    canonical_hash,
)
from enterprise_analytics_agent.retail_evaluation.models import EvaluationModel

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REVIEW_PATH = Path("evaluations/retail-v1/q18-repair-review.json")
type Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class RepairReview(EvaluationModel):
    schema_version: Literal["q18-repair-review-v1"] = "q18-repair-review-v1"
    campaign_id: Literal["milestone-5-q18-repair-v1"] = "milestone-5-q18-repair-v1"
    ledger_path: Literal["artifacts/milestone-5/q18-repair-v1/runtime-invocations.jsonl"] = (
        "artifacts/milestone-5/q18-repair-v1/runtime-invocations.jsonl"
    )
    maximum: Literal[40] = 40
    runtime_arn: Literal[
        "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
        "enterprise_analytics_dev_agent-HlWywlG60h"
    ] = (
        "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
        "enterprise_analytics_dev_agent-HlWywlG60h"
    )
    candidate_artifact_path: Literal["artifacts/milestone-5/q18-repair-v1/candidate/agent.zip"]
    candidate_assembly_path: Literal["artifacts/milestone-5/q18-repair-v1/cdk.candidate.out"]
    candidate_sha256: Sha256
    candidate_template_sha256: Sha256
    restoration_artifact_path: Literal["artifacts/agentcore/agent.zip"] = (
        "artifacts/agentcore/agent.zip"
    )
    restoration_assembly_path: Literal["artifacts/milestone-5/cdk.restore.out"] = (
        "artifacts/milestone-5/cdk.restore.out"
    )
    restoration_sha256: Literal[
        "51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1"
    ] = "51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1"
    restoration_version_id: Literal["HSRXiFjg0w2W77InULH4.fn32Y.JH8b9"] = (
        "HSRXiFjg0w2W77InULH4.fn32Y.JH8b9"
    )
    restoration_template_sha256: Literal[
        "dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb"
    ] = "dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb"
    questions_sha256: Sha256
    expected_results_sha256: Sha256
    source_patch_sha256: Sha256

    @model_validator(mode="after")
    def changed_candidate(self) -> Self:
        if self.candidate_sha256 == CODE_SHA256:
            raise ValueError("Q18 candidate must differ from the original frozen runtime archive")
        return self

    @property
    def review_sha256(self) -> str:
        """Pin semantic review contents: SHA-256 of sorted compact UTF-8 JSON."""
        return canonical_hash(self.model_dump(mode="json"))


class CandidateVersionBinding(EvaluationModel):
    """Written after an approved upload and verified version-specific S3 HEAD, never invented."""

    schema_version: Literal["q18-candidate-version-v1"] = "q18-candidate-version-v1"
    campaign_id: Literal["milestone-5-q18-repair-v1"] = "milestone-5-q18-repair-v1"
    review_sha256: Sha256
    candidate_sha256: Sha256
    candidate_template_sha256: Sha256
    bucket: Literal["enterprise-analytics-dev-453711491609-us-west-2-agent-code"]
    key: str
    version_id: Annotated[str, Field(min_length=1, max_length=1024)]
    checksum_sha256: Sha256
    size_bytes: Annotated[int, Field(gt=0, strict=True)]
    verified_at: datetime
    account: Literal["453711491609"] = "453711491609"
    region: Literal["us-west-2"] = "us-west-2"
    profile: Literal["analytics-dev"] = "analytics-dev"

    @model_validator(mode="after")
    def immutable_version(self) -> Self:
        if self.version_id.casefold() in {"null", "pending", "unknown", "placeholder"}:
            raise ValueError("candidate requires the real version returned by the approved upload")
        if self.candidate_sha256 == CODE_SHA256 or self.checksum_sha256 != self.candidate_sha256:
            raise ValueError("candidate checksum differs from the reviewed new artifact")
        if self.key != f"releases/{self.candidate_sha256}/agent.zip":
            raise ValueError("candidate object key must be addressed by its exact checksum")
        if self.verified_at.tzinfo is None:
            raise ValueError("upload verification timestamp requires a timezone")
        return self

    def require_review(self, review: RepairReview) -> None:
        if (self.review_sha256, self.candidate_sha256, self.candidate_template_sha256) != (
            review.review_sha256,
            review.candidate_sha256,
            review.candidate_template_sha256,
        ):
            raise ValueError("uploaded candidate version does not bind the reviewed campaign")


def load_review(*, repository_root: Path = REPOSITORY_ROOT) -> RepairReview:
    return RepairReview.model_validate_json((repository_root / REVIEW_PATH).read_bytes())


def select_repair(
    name: str, version_path: Path | None, *, repository_root: Path = REPOSITORY_ROOT
) -> tuple[RepairReview, CandidateVersionBinding, RepairCampaignBinding]:
    """Unknown selection or absent version fails before any SDK client or reservation."""
    if name != "q18-repair-v1":
        raise ValueError("unknown reviewed campaign selection")
    if version_path is None:
        raise ValueError("repair campaign requires the verified post-upload version record")
    review = load_review(repository_root=repository_root)
    version = CandidateVersionBinding.model_validate_json(version_path.read_bytes())
    version.require_review(review)
    binding = RepairCampaignBinding(
        campaign_id=review.campaign_id,
        ledger_path=review.ledger_path,
        maximum=review.maximum,
        review_sha256=review.review_sha256,
        candidate_sha256=review.candidate_sha256,
        candidate_template_sha256=review.candidate_template_sha256,
        candidate_version_record_sha256=canonical_hash(version.model_dump(mode="json")),
    )
    return review, version, binding
