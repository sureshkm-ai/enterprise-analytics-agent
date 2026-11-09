"""Explicitly gated repair operator AWS operations; no client is constructed on import."""

import base64
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from enterprise_analytics_agent.adapters.agentcore_invocation import create_runtime_invoker
from enterprise_analytics_agent.adapters.deployment_controller import DeploymentController
from enterprise_analytics_agent.adapters.retail_checkpoint import (
    verify_candidate_checkpoint,
    verify_checkpoint,
    verify_restoration,
)
from enterprise_analytics_agent.retail_evaluation.campaign import CODE_VERSION
from enterprise_analytics_agent.retail_evaluation.deployment import (
    BASE_ASSEMBLY,
    TEMPLATE_NAME,
    candidate_review_templates,
    digest,
    review_assemblies,
    review_candidate_assemblies,
)
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    RepairReview,
)
from enterprise_analytics_agent.retail_evaluation.repair_workflow import RepairOperations

READ_CONFIG = Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 1})


class _BudgetedClient:
    def __init__(self, client: Any, deadline: float) -> None:
        self.client = client
        self.deadline = deadline

    def __getattr__(self, name: str) -> Any:
        method = getattr(self.client, name)

        def bounded_read(*args: Any, **kwargs: Any) -> Any:
            if time.monotonic() >= self.deadline:
                raise TimeoutError("checkpoint read budget exhausted")
            result = method(*args, **kwargs)
            if time.monotonic() >= self.deadline:
                raise TimeoutError("checkpoint read exceeded its budget")
            return result

        return bounded_read


class _BudgetedSession:
    """Finite SDK timeouts plus a deadline checked before each checkpoint read."""

    def __init__(self, session: Any, deadline: float) -> None:
        self.session = session
        self.deadline = deadline

    def client(self, name: str, **kwargs: Any) -> Any:
        if time.monotonic() >= self.deadline:
            raise TimeoutError("checkpoint client budget exhausted")
        kwargs["config"] = READ_CONFIG
        client = self.session.client(name, **kwargs)
        if time.monotonic() >= self.deadline:
            raise TimeoutError("checkpoint client exceeded its budget")
        return _BudgetedClient(client, self.deadline)


def verify_uploaded_version(
    review: RepairReview, upload_response: dict[str, Any], *, session: Any = None
) -> CandidateVersionBinding:
    """Bind the upload-returned version to a version-specific read, never a guessed ID."""
    review_candidate_assemblies(review)
    version = upload_response.get("VersionId")
    if not isinstance(version, str) or version.casefold() in {"", "null", "pending", "unknown"}:
        raise ValueError("approved upload did not return an immutable candidate S3 VersionId")
    session = session or boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
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
    if session.client("sts", config=READ_CONFIG).get_caller_identity()["Account"] != "453711491609":
        raise ValueError("operator account differs from the reviewed target")
    # Re-read the uploaded immutable version before any CloudFormation mutation.
    if not restore_only:
        observed = verify_uploaded_version(
            review, {"VersionId": version.version_id}, session=session
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

    cloudformation = session.client("cloudformation", config=READ_CONFIG)
    controller = DeploymentController(
        directory,
        cloudformation,
        lock_path=Path("artifacts/milestone-5/runtime-deployment.lock"),
        baseline_validator=validate_baseline,
    )

    def candidate_checkpoint(deadline: float) -> dict[str, Any]:
        return verify_candidate_checkpoint(
            review, version, session=_BudgetedSession(session, deadline)
        )

    def original_checkpoint(deadline: float) -> dict[str, Any]:
        return verify_checkpoint(scope="parity-v1", session=_BudgetedSession(session, deadline))

    return RepairOperations(
        verify_original=lambda: verify_restoration(
            session=_BudgetedSession(session, time.monotonic() + 120)
        ),
        deploy_candidate=lambda: controller.deploy(
            review.candidate_assembly_path,
            version.version_id,
            "candidate",
            candidate_checkpoint,
            template_sha256=review.candidate_template_sha256,
        ),
        verify_candidate=lambda: candidate_checkpoint(time.monotonic() + 120),
        restore_original=lambda: controller.deploy(
            review.restoration_assembly_path,
            CODE_VERSION,
            "restore",
            original_checkpoint,
            template_sha256=review.restoration_template_sha256,
        ),
        invoker=create_runtime_invoker,
    )


def write_version_record(path: Path, version: CandidateVersionBinding) -> None:
    encoded = version.model_dump_json(indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(encoded)
