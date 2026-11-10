"""Explicitly gated repair operator AWS operations; no client is constructed on import."""

import base64
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3

from enterprise_analytics_agent.adapters.agentcore_invocation import create_runtime_invoker
from enterprise_analytics_agent.adapters.deployment_controller import DeploymentController
from enterprise_analytics_agent.adapters.operator_reads import READ_CONFIG, ReadPool, ReadSession
from enterprise_analytics_agent.adapters.retail_checkpoint import (
    restoration_proof,
    verify_candidate_checkpoint,
    verify_checkpoint,
    verify_restoration,
)
from enterprise_analytics_agent.retail_evaluation.campaign import CODE_VERSION, RestorationProof
from enterprise_analytics_agent.retail_evaluation.client import RuntimeInvoker
from enterprise_analytics_agent.retail_evaluation.deployment import (
    BASE_ASSEMBLY,
    TEMPLATE_NAME,
    candidate_review_templates,
    digest,
    review_assemblies,
    review_candidate_assemblies,
)
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    RepairReview,
)
from enterprise_analytics_agent.retail_evaluation.repair_workflow import RepairOperations


class _BudgetedSession(ReadSession):
    """Compatibility entry point; live operations share a persistent ReadPool."""

    def __init__(self, session: Any, deadline: float) -> None:
        super().__init__(ReadPool(session), deadline, "checkpoint")


def verify_uploaded_version(
    review: RepairReview, upload_response: dict[str, Any], *, session: Any = None
) -> CandidateVersionBinding:
    """Bind the upload-returned version to a version-specific read, never a guessed ID."""
    review_candidate_assemblies(review)
    version = upload_response.get("VersionId")
    if not isinstance(version, str) or version.casefold() in {"", "null", "pending", "unknown"}:
        raise ValueError("approved upload did not return an immutable candidate S3 VersionId")
    session = session or boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
    if not isinstance(session, ReadSession):
        session = _BudgetedSession(session, time.monotonic() + 120)
    if session.client("sts", config=READ_CONFIG).get_caller_identity()["Account"] != "453711491609":
        raise ValueError("operator account differs from the reviewed target")
    bucket = "enterprise-analytics-dev-453711491609-us-west-2-agent-code"
    key = f"releases/{review.candidate_sha256}/agent.zip"
    head = session.client("s3", config=READ_CONFIG).head_object(
        Bucket=bucket,
        Key=key,
        VersionId=version,
        ExpectedBucketOwner="453711491609",
        ChecksumMode="ENABLED",
    )
    if (
        head.get("VersionId") != version
        or head.get("ChecksumSHA256")
        != base64.b64encode(bytes.fromhex(review.candidate_sha256)).decode()
        or head.get("ContentLength") != Path(review.candidate_artifact_path).stat().st_size
    ):
        raise ValueError("uploaded version checksum, size or immutable identity differs")
    return CandidateVersionBinding(
        review_sha256=review.review_sha256,
        candidate_sha256=review.candidate_sha256,
        candidate_template_sha256=review.candidate_template_sha256,
        bucket=bucket,
        key=key,
        version_id=version,
        checksum_sha256=review.candidate_sha256,
        size_bytes=head["ContentLength"],
        verified_at=datetime.now(UTC),
    )


def operations_for(
    review: RepairReview,
    version: CandidateVersionBinding,
    directory: Path,
    *,
    restore_only: bool = False,
) -> RepairOperations:
    version.require_review(review)
    if restore_only:
        # Recovery must not depend on an inaccessible failed candidate object.
        review_assemblies()
    else:
        review_candidate_assemblies(review)
    session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
    # A sibling journal can preserve preflight failures without occupying the
    # workflow's exclusive report directory before prepare_run_directory.
    journal = directory.with_name(directory.name + ".operator-reads.jsonl")
    if journal.exists():
        raise ValueError("operator read evidence already exists; use a new report directory")
    reads = ReadPool(session, journal)
    preflight = reads.view(time.monotonic() + 120, "operator-preflight")
    if preflight.client("sts").get_caller_identity()["Account"] != "453711491609":
        raise ValueError("operator account differs from the reviewed target")
    # Re-read the uploaded immutable version before any CloudFormation mutation.
    if not restore_only:
        observed = verify_uploaded_version(
            review, {"VersionId": version.version_id}, session=preflight
        )
        if (observed.version_id, observed.size_bytes, observed.checksum_sha256) != (
            version.version_id,
            version.size_bytes,
            version.checksum_sha256,
        ):
            raise ValueError("candidate version record differs from current upload verification")

    def validate_baseline(stack: dict[str, Any], actual: dict[str, Any]) -> None:
        path = BASE_ASSEMBLY / TEMPLATE_NAME
        if digest(path) != review.restoration_template_sha256:
            raise ValueError("original baseline template differs from its reviewed pin")
        original = json.loads(path.read_bytes())
        parameters = {item["ParameterKey"]: item["ParameterValue"] for item in stack["Parameters"]}
        if actual == original:
            if parameters["ArtifactVersionId"] != CODE_VERSION:
                raise ValueError("original baseline template has an unreviewed artifact version")
        else:
            candidate_review_templates(original, actual, candidate_sha256=review.candidate_sha256)
            if parameters["ArtifactVersionId"] != version.version_id:
                raise ValueError("candidate baseline template has an unreviewed artifact version")

    cloudformation = preflight.client("cloudformation")
    controller = DeploymentController(
        directory,
        cloudformation,
        lock_path=Path("artifacts/milestone-5/runtime-deployment.lock"),
        baseline_validator=validate_baseline,
        read_client=lambda deadline: reads.view(deadline, "deployment-reconciliation").client(
            "cloudformation"
        ),
    )

    def candidate_checkpoint(deadline: float) -> dict[str, Any]:
        return verify_candidate_checkpoint(
            review, version, session=reads.view(deadline, "candidate-checkpoint")
        )

    def original_checkpoint(deadline: float) -> dict[str, Any]:
        return verify_checkpoint(
            scope="parity-v1", session=reads.view(deadline, "original-checkpoint")
        )

    restored: RestorationProof | None = None

    def verify_original() -> RestorationProof:
        # Cache only an accepted post-cleanup proof, never the starting proof.
        if restored is not None:
            age = (datetime.now(UTC) - restored.observed_at).total_seconds()
            if 0 <= age <= 60:
                return restored
        return verify_restoration(
            session=reads.view(time.monotonic() + 120, "original-verification")
        )

    def deploy_candidate() -> dict[str, Any]:
        nonlocal restored
        restored = None
        return controller.deploy(
            review.candidate_assembly_path,
            version.version_id,
            "candidate",
            candidate_checkpoint,
            template_sha256=review.candidate_template_sha256,
        )

    def restore_original() -> RestorationProof:
        nonlocal restored
        restored = None
        checkpoint = controller.deploy(
            review.restoration_assembly_path,
            CODE_VERSION,
            "restore",
            original_checkpoint,
            template_sha256=review.restoration_template_sha256,
        )
        restored = restoration_proof(checkpoint)
        return restored

    invokers: dict[str, RuntimeInvoker] = {}

    def invoker(target: RetailTarget) -> RuntimeInvoker:
        # STS is a read; InvokeAgentRuntime remains an unretried, counted call.
        key = target.model_dump_json()
        if key not in invokers:
            setup = reads.view(time.monotonic() + 120, "invocation-setup")
            invokers[key] = create_runtime_invoker(
                target,
                session=session,
                identity_session=setup,
                client_factory=lambda config: setup.invocation_client(
                    runtime_arn=target.runtime_arn, config=config
                ),
            )
        return invokers[key]

    return RepairOperations(
        verify_original=verify_original,
        deploy_candidate=deploy_candidate,
        verify_candidate=lambda: candidate_checkpoint(time.monotonic() + 120),
        restore_original=restore_original,
        invoker=invoker,
    )


def write_version_record(path: Path, version: CandidateVersionBinding) -> None:
    encoded = version.model_dump_json(indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(encoded)
