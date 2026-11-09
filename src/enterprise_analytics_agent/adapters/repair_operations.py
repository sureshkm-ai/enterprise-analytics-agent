"""Explicitly gated repair operator AWS operations; no client is constructed on import."""

import base64
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from enterprise_analytics_agent.adapters.agentcore_invocation import create_runtime_invoker
from enterprise_analytics_agent.adapters.retail_checkpoint import (
    RUNTIME_ID,
    verify_candidate_checkpoint,
    verify_restoration,
)
from enterprise_analytics_agent.retail_evaluation.campaign import CODE_VERSION
from enterprise_analytics_agent.retail_evaluation.deployment import (
    review_assemblies,
    review_candidate_assemblies,
)
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    RepairReview,
)
from enterprise_analytics_agent.retail_evaluation.repair_workflow import RepairOperations

READ_CONFIG = Config(connect_timeout=5, read_timeout=20, retries={"total_max_attempts": 2})


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
    control = session.client("bedrock-agentcore-control", config=READ_CONFIG)
    cloudformation = session.client("cloudformation", config=READ_CONFIG)

    def wait_stable() -> None:
        deadline = time.monotonic() + 900
        while True:
            status = cloudformation.describe_stacks(
                StackName="enterprise-analytics-dev-agent-runtime"
            )["Stacks"][0]["StackStatus"]
            if not status.endswith("_IN_PROGRESS"):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Runtime stack did not settle for supervised restoration")
            time.sleep(5)

    def wait_ready() -> None:
        deadline = time.monotonic() + 300
        while True:
            runtime = control.get_agent_runtime(agentRuntimeId=RUNTIME_ID)
            endpoint = control.get_agent_runtime_endpoint(
                agentRuntimeId=RUNTIME_ID, endpointName="DEFAULT"
            )
            live = runtime["agentRuntimeVersion"]
            if (
                runtime["status"] == endpoint["status"] == "READY"
                and endpoint["liveVersion"] == endpoint.get("targetVersion", live) == live
            ):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Runtime/DEFAULT did not become READY")
            time.sleep(3)

    def deploy(assembly: str, artifact_version: str, name: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with (
            (directory / f"{name}.stdout.log").open("x") as out,
            (directory / f"{name}.stderr.log").open("x") as err,
        ):
            result = subprocess.run(
                [
                    "infrastructure/cdk/tooling/node_modules/.bin/cdk",
                    "deploy",
                    "--app",
                    assembly,
                    "enterprise-analytics-dev-agent-runtime",
                    "--parameters",
                    "ArtifactVersionId=" + artifact_version,
                    "--profile",
                    "analytics-dev",
                    "--region",
                    "us-west-2",
                    "--require-approval",
                    "never",
                    "--no-telemetry",
                    "--no-notices",
                    "--outputs-file",
                    str(directory / f"{name}.outputs.json"),
                ],
                stdout=out,
                stderr=err,
                check=False,
                timeout=1800,
            )
        if result.returncode:
            raise RuntimeError(f"{name} failed; retain full logs and inspect before retrying")
        wait_ready()

    def restore() -> None:
        wait_stable()
        deploy(review.restoration_assembly_path, CODE_VERSION, "restore")

    return RepairOperations(
        verify_original=verify_restoration,
        deploy_candidate=lambda: deploy(
            review.candidate_assembly_path, version.version_id, "candidate"
        ),
        verify_candidate=lambda: verify_candidate_checkpoint(review, version),
        restore_original=restore,
        invoker=create_runtime_invoker,
    )


def write_version_record(path: Path, version: CandidateVersionBinding) -> None:
    encoded = version.model_dump_json(indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(encoded)
