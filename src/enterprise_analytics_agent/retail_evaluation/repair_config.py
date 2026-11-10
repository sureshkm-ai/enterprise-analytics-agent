"""Reviewed repair artifacts and upload-version bindings, independent of AWS SDK types."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from enterprise_analytics_agent.retail_evaluation.campaign import (
    CODE_SHA256,
    CampaignLedger,
    ContinuationCampaignBinding,
    RecoveryCampaignBinding,
    RepairCampaignBinding,
    RestorationProof,
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


class _OriginalCheckpoint(EvaluationModel):
    """An explicit original checkpoint; fresh observations must match every pin."""

    runtime_arn: str
    runtime_version: str
    endpoint_version: str
    dataset_version: Literal["parity-v1"] = "parity-v1"
    tenant_id: Literal["t1"] = "t1"
    allowed_regions: tuple[Literal["North"], Literal["South"]] = ("North", "South")
    reference_date: Literal["2025-02-01"] = "2025-02-01"
    configuration_sha256: Sha256
    template_sha256: Sha256
    code_sha256: Literal["51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1"] = (
        "51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1"
    )
    code_version_id: Literal["HSRXiFjg0w2W77InULH4.fn32Y.JH8b9"] = (
        "HSRXiFjg0w2W77InULH4.fn32Y.JH8b9"
    )
    resource_policies_verified: Literal[True] = True
    retention_days: Literal[7] = 7

    def require_proof(self, proof: RestorationProof, *, now: datetime | None = None) -> None:
        proof = RestorationProof.model_validate(proof.model_dump())
        age = (now or datetime.now(UTC)) - proof.observed_at
        if not timedelta(0) <= age <= timedelta(minutes=5):
            raise ValueError(
                f"v{self.runtime_version} continuation requires a fresh original "
                "checkpoint observation"
            )
        expected = self.model_dump(
            mode="json", exclude={"source_proof_sha256", "source_checkpoint_commit"}
        )
        actual = proof.model_dump(mode="json")
        if (
            proof.runtime_status != "READY"
            or proof.endpoint_status != "READY"
            or any(actual.get(key) != value for key, value in expected.items())
        ):
            raise ValueError(
                f"original deployment differs from the reviewed v{self.runtime_version} "
                "continuation checkpoint"
            )


class ReviewedStartingCheckpoint(_OriginalCheckpoint):
    runtime_version: Literal["8"] = "8"
    endpoint_version: Literal["8"] = "8"
    source_proof_sha256: Sha256


class ReviewedRecoveryCheckpoint(_OriginalCheckpoint):
    runtime_version: Literal["10"] = "10"
    endpoint_version: Literal["10"] = "10"
    source_checkpoint_commit: Literal["75d7c9f688f8e0746b17b797016947e1ed41f4bb"] = (
        "75d7c9f688f8e0746b17b797016947e1ed41f4bb"
    )


class ContinuationReview(EvaluationModel):
    """A proposed continuation of one closed repair, never a reset of its ledger."""

    schema_version: Literal["q18-continuation-review-v1"] = "q18-continuation-review-v1"
    campaign_id: Literal["milestone-5-q18-continuation-v1"] = "milestone-5-q18-continuation-v1"
    ledger_path: Literal["artifacts/milestone-5/q18-continuation-v1/runtime-invocations.jsonl"] = (
        "artifacts/milestone-5/q18-continuation-v1/runtime-invocations.jsonl"
    )
    maximum: Literal[39] = 39
    aggregate_maximum: Literal[40] = 40
    prior_used: Literal[1] = 1
    repair_review_sha256: Sha256
    parent_ledger_sha256: Sha256
    parent_binding: RepairCampaignBinding
    candidate_sha256: Sha256
    candidate_template_sha256: Sha256
    candidate_version_id: str
    candidate_version_record_sha256: Sha256
    starting_checkpoint: ReviewedStartingCheckpoint

    @property
    def review_sha256(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def campaign_binding(
        self, review: RepairReview, version: CandidateVersionBinding
    ) -> ContinuationCampaignBinding:
        version.require_review(review)
        if (
            review.review_sha256,
            version.candidate_sha256,
            version.candidate_template_sha256,
            version.version_id,
            canonical_hash(version.model_dump(mode="json")),
            self.starting_checkpoint.runtime_arn,
        ) != (
            self.repair_review_sha256,
            self.candidate_sha256,
            self.candidate_template_sha256,
            self.candidate_version_id,
            self.candidate_version_record_sha256,
            review.runtime_arn,
        ):
            raise ValueError("continuation differs from the existing reviewed candidate/version")
        if self.parent_binding.review_sha256 != review.review_sha256:
            raise ValueError("continuation parent binding differs from the original repair review")
        return ContinuationCampaignBinding(
            review_sha256=self.review_sha256,
            candidate_sha256=self.candidate_sha256,
            candidate_template_sha256=self.candidate_template_sha256,
            candidate_version_record_sha256=self.candidate_version_record_sha256,
            parent_ledger_sha256=self.parent_ledger_sha256,
            parent_binding=self.parent_binding,
            starting_checkpoint_sha256=canonical_hash(
                self.starting_checkpoint.model_dump(mode="json")
            ),
        )

    def require_starting_proof(self, proof: RestorationProof) -> None:
        self.starting_checkpoint.require_proof(proof)


class RecoveryReview(EvaluationModel):
    """A proposed continuation of one closed repair, never a reset of its ledger."""

    schema_version: Literal["q18-recovery-review-v1"] = "q18-recovery-review-v1"
    campaign_id: Literal["milestone-5-q18-recovery-v1"] = "milestone-5-q18-recovery-v1"
    ledger_path: Literal["artifacts/milestone-5/q18-recovery-v1/runtime-invocations.jsonl"] = (
        "artifacts/milestone-5/q18-recovery-v1/runtime-invocations.jsonl"
    )
    maximum: Literal[38] = 38
    aggregate_maximum: Literal[40] = 40
    prior_used: Literal[2] = 2
    probe_is_warmup: Literal[True] = True
    repair_review_sha256: Sha256
    parent_ledger_sha256: Sha256
    parent_binding: ContinuationCampaignBinding
    parent_attempt_sha256: Sha256
    candidate_sha256: Sha256
    candidate_template_sha256: Sha256
    candidate_version_id: str
    candidate_version_record_sha256: Sha256
    starting_checkpoint: ReviewedRecoveryCheckpoint

    @property
    def review_sha256(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def campaign_binding(
        self, review: RepairReview, version: CandidateVersionBinding
    ) -> RecoveryCampaignBinding:
        version.require_review(review)
        if (
            review.review_sha256,
            version.candidate_sha256,
            version.candidate_template_sha256,
            version.version_id,
            canonical_hash(version.model_dump(mode="json")),
            self.starting_checkpoint.runtime_arn,
        ) != (
            self.repair_review_sha256,
            self.candidate_sha256,
            self.candidate_template_sha256,
            self.candidate_version_id,
            self.candidate_version_record_sha256,
            review.runtime_arn,
        ):
            raise ValueError("continuation differs from the existing reviewed candidate/version")
        if self.parent_binding.parent_binding.review_sha256 != review.review_sha256:
            raise ValueError("continuation parent binding differs from the original repair review")
        return RecoveryCampaignBinding(
            review_sha256=self.review_sha256,
            candidate_sha256=self.candidate_sha256,
            candidate_template_sha256=self.candidate_template_sha256,
            candidate_version_record_sha256=self.candidate_version_record_sha256,
            parent_ledger_sha256=self.parent_ledger_sha256,
            parent_binding=self.parent_binding,
            parent_attempt_sha256=self.parent_attempt_sha256,
            starting_checkpoint_sha256=canonical_hash(
                self.starting_checkpoint.model_dump(mode="json")
            ),
        )

    def require_starting_proof(self, proof: RestorationProof) -> None:
        self.starting_checkpoint.require_proof(proof)


def load_continuation(*, repository_root: Path = REPOSITORY_ROOT) -> ContinuationReview:
    return ContinuationReview.model_validate_json(
        (repository_root / "evaluations/retail-v1/q18-continuation-review.json").read_bytes()
    )


def select_continuation(
    name: str, version_path: Path | None, *, repository_root: Path = REPOSITORY_ROOT
) -> tuple[RepairReview, CandidateVersionBinding, ContinuationCampaignBinding, ContinuationReview]:
    """Pure local checks precede SDK construction; no counter or attempt file is created."""
    if name != "q18-continuation-v1":
        raise ValueError("unknown reviewed continuation selection")
    review, version, _ = select_repair(
        "q18-repair-v1", version_path, repository_root=repository_root
    )
    continuation = load_continuation(repository_root=repository_root)
    binding = continuation.campaign_binding(review, version)
    CampaignLedger(binding=binding, repository_root=repository_root).summary()
    return review, version, binding, continuation


def select_recovery(
    name: str, version_path: Path | None, *, repository_root: Path = REPOSITORY_ROOT
) -> tuple[RepairReview, CandidateVersionBinding, RecoveryCampaignBinding, RecoveryReview]:
    """Validate both closed histories locally without reopening either."""
    if name != "q18-recovery-v1":
        raise ValueError("unknown reviewed recovery selection")
    review, version, _ = select_repair(
        "q18-repair-v1", version_path, repository_root=repository_root
    )
    recovery = RecoveryReview.model_validate_json(
        (repository_root / "evaluations/retail-v1/q18-recovery-review.json").read_bytes()
    )
    previous = load_continuation(repository_root=repository_root)
    if recovery.parent_binding != previous.campaign_binding(review, version):
        raise ValueError("recovery parent differs from the historical continuation review")
    binding = recovery.campaign_binding(review, version)
    CampaignLedger(binding=binding, repository_root=repository_root).summary()
    return review, version, binding, recovery


def require_starting_checkpoint(
    proof: RestorationProof,
    review: RepairReview,
    continuation: ContinuationReview | RecoveryReview | None = None,
) -> None:
    """Historical v6/v8 reviews and proposed v10 recovery remain separate."""
    proof = RestorationProof.model_validate(proof.model_dump())
    if continuation is not None:
        continuation.require_starting_proof(proof)
    elif proof.runtime_version != "6" or proof.runtime_arn != review.runtime_arn:
        raise ValueError("original deployment version drifted from reviewed v6 checkpoint")
