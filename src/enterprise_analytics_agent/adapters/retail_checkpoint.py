"""Read-only AWS checkpoint verification for the operator retail workflow.

No mutation or invocation API is used here. A restoration proof is obtained fresh,
not accepted from a caller-supplied JSON file or runtime response.
"""

from __future__ import annotations

import argparse
import base64
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import boto3
from botocore.config import Config

from enterprise_analytics_agent.retail_evaluation.campaign import (
    CODE_SHA256,
    CODE_VERSION,
    RestorationProof,
)
from enterprise_analytics_agent.retail_evaluation.deployment import (
    BASE_ASSEMBLY,
    BASE_TEMPLATE_SHA256,
    RETAIL_ASSEMBLY,
    TEMPLATE_NAME,
    canonical_hash,
    digest,
    review_assemblies,
    review_candidate_assemblies,
)

if TYPE_CHECKING:
    from enterprise_analytics_agent.retail_evaluation.repair_config import (
        CandidateVersionBinding,
        RepairReview,
    )

ACCOUNT = "453711491609"
REGION = "us-west-2"
RUNTIME_ID = "enterprise_analytics_dev_agent-HlWywlG60h"
RUNTIME_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/{RUNTIME_ID}"
READ_CONFIG = Config(connect_timeout=5, read_timeout=20, retries={"total_max_attempts": 2})


def _resolve(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value == {"Fn::GetAtt": ["AnalyticsRuntime", "AgentRuntimeArn"]}:
        return RUNTIME_ARN
    if isinstance(value, dict) and set(value) == {"Fn::Join"}:
        separator, parts = value["Fn::Join"]
        return str(separator).join(_resolve(part) for part in parts)
    raise ValueError("Unexpected policy intrinsic in reviewed template")


def _normalize(policy: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(policy)
    for statement in result["Statement"]:
        principal = statement.get("Principal")
        if isinstance(principal, dict) and isinstance(principal.get("AWS"), str):
            principal["AWS"] = [principal["AWS"]]
        condition = statement.get("Condition", {}).get("ArnNotEquals", {})
        if isinstance(condition.get("aws:PrincipalArn"), str):
            condition["aws:PrincipalArn"] = [condition["aws:PrincipalArn"]]
    return result


def _verify_runtime(
    runtime: dict[str, Any],
    endpoint: dict[str, Any],
    template: dict[str, Any],
    *,
    artifact_sha256: str = CODE_SHA256,
    artifact_version_id: str = CODE_VERSION,
) -> dict[str, Any]:
    if runtime["status"] != "READY" or endpoint["status"] != "READY":
        raise ValueError("Runtime and DEFAULT must both be READY")
    version = runtime["agentRuntimeVersion"]
    if endpoint["liveVersion"] != version or endpoint.get("targetVersion", version) != version:
        raise ValueError("Runtime and DEFAULT versions differ or an update remains pending")
    if (
        runtime["agentRuntimeArn"] != RUNTIME_ARN
        or endpoint["agentRuntimeEndpointArn"] != RUNTIME_ARN + "/runtime-endpoint/DEFAULT"
    ):
        raise ValueError("Unexpected Runtime or endpoint identity")
    properties = template["Resources"]["AnalyticsRuntime"]["Properties"]
    if runtime["environmentVariables"] != properties["EnvironmentVariables"]:
        raise ValueError("Live trusted configuration differs from the reviewed template")
    for actual, expected in (
        ("roleArn", "RoleArn"),
        ("platformVersion", "PlatformVersion"),
        ("networkConfiguration", "NetworkConfiguration"),
    ):
        # CloudFormation's networking properties use capitalized field names.
        wanted = properties[expected]
        if actual == "networkConfiguration":
            wanted = {"networkMode": wanted["NetworkMode"]}
        if runtime[actual] != wanted:
            raise ValueError(f"Live Runtime {actual} differs from the checkpoint")
    expected_lifecycle = properties["LifecycleConfiguration"]
    if runtime["lifecycleConfiguration"] != {
        "idleRuntimeSessionTimeout": expected_lifecycle["IdleRuntimeSessionTimeout"],
        "maxLifetime": expected_lifecycle["MaxLifetime"],
    } or runtime["protocolConfiguration"] != {
        "serverProtocol": properties["ProtocolConfiguration"]
    }:
        raise ValueError("Live Runtime lifecycle/protocol differs from checkpoint")
    artifact = runtime["agentRuntimeArtifact"]["codeConfiguration"]
    if (
        artifact["entryPoint"]
        != properties["AgentRuntimeArtifact"]["CodeConfiguration"]["EntryPoint"]
    ):
        raise ValueError("Live Runtime entrypoint differs from checkpoint")
    code = artifact["code"]["s3"]
    if (
        artifact["runtime"] != "PYTHON_3_12"
        or code["versionId"] != artifact_version_id
        or code["bucket"] != f"enterprise-analytics-dev-{ACCOUNT}-{REGION}-agent-code"
        or code["prefix"] != f"releases/{artifact_sha256}/agent.zip"
    ):
        raise ValueError("Live Runtime uses a different artifact")
    return dict(code)


def verify_checkpoint(
    *, scope: Literal["parity-v1", "retail-v1"] = "parity-v1", session: Any = None
) -> dict[str, Any]:
    """Verify only the original reviewed artifact, including for restoration."""
    review = review_assemblies()
    path = (BASE_ASSEMBLY if scope == "parity-v1" else RETAIL_ASSEMBLY) / TEMPLATE_NAME
    return _verify_checkpoint(
        scope=scope,
        path=path,
        artifact_path=Path("artifacts/agentcore/agent.zip"),
        artifact_sha256=CODE_SHA256,
        artifact_version_id=CODE_VERSION,
        review=review,
        session=session,
    )


def verify_candidate_checkpoint(
    review: RepairReview, version: CandidateVersionBinding, *, session: Any = None
) -> dict[str, Any]:
    """Verify a separately reviewed candidate and its actual approved-upload VersionId.

    Candidate configuration never changes the original restoration constants or
    proof. All local review/version checks precede SDK construction and dispatch.
    """
    from enterprise_analytics_agent.retail_evaluation.repair_config import (
        CandidateVersionBinding,
        RepairReview,
    )

    review = RepairReview.model_validate(review.model_dump())
    version = CandidateVersionBinding.model_validate(version.model_dump())
    version.require_review(review)
    inspection = review_candidate_assemblies(review)
    artifact_path = Path(review.candidate_artifact_path)
    if artifact_path.stat().st_size != version.size_bytes:
        raise ValueError("Candidate upload record size differs from the reviewed local ZIP")
    return _verify_checkpoint(
        scope="retail-v1",
        path=Path(review.candidate_assembly_path) / TEMPLATE_NAME,
        artifact_path=artifact_path,
        artifact_sha256=review.candidate_sha256,
        artifact_version_id=version.version_id,
        expected_size=version.size_bytes,
        review=inspection,
        session=session,
    )


def _verify_checkpoint(
    *,
    scope: Literal["parity-v1", "retail-v1"],
    path: Path,
    artifact_path: Path,
    artifact_sha256: str,
    artifact_version_id: str,
    review: dict[str, object],
    session: Any = None,
    expected_size: int | None = None,
) -> dict[str, Any]:
    """Shared mechanics; public entry points select separate immutable artifact pins."""
    session = session or boto3.Session(profile_name="analytics-dev", region_name=REGION)
    identity = session.client("sts", config=READ_CONFIG).get_caller_identity()
    if identity.get("Account") != ACCOUNT:
        raise ValueError("analytics-dev account differs from the approved account")
    template = json.loads(path.read_text())
    control = session.client("bedrock-agentcore-control", config=READ_CONFIG)
    runtime = control.get_agent_runtime(agentRuntimeId=RUNTIME_ID)
    endpoint = control.get_agent_runtime_endpoint(agentRuntimeId=RUNTIME_ID, endpointName="DEFAULT")
    code = _verify_runtime(
        runtime,
        endpoint,
        template,
        artifact_sha256=artifact_sha256,
        artifact_version_id=artifact_version_id,
    )
    policies = {}
    for name, resource in template["Resources"].items():
        if resource["Type"] != "AWS::BedrockAgentCore::ResourcePolicy":
            continue
        arn = _resolve(resource["Properties"]["ResourceArn"])
        actual_policy = json.loads(control.get_resource_policy(resourceArn=arn)["policy"])
        expected_policy = json.loads(_resolve(resource["Properties"]["Policy"]))
        if _normalize(actual_policy) != _normalize(expected_policy):
            raise ValueError(f"Resource policy differs: {name}")
        policies[name] = actual_policy
    cloudformation = session.client("cloudformation", config=READ_CONFIG)
    stacks = {}
    for name, source in (
        ("enterprise-analytics-dev-agent-runtime", path),
        (
            "enterprise-analytics-dev-agent-foundation",
            BASE_ASSEMBLY / "enterprise-analytics-dev-agent-foundation.template.json",
        ),
        (
            "enterprise-analytics-dev-data-layer",
            Path("artifacts/cdk.m4-data-trust.cli.out")
            / "enterprise-analytics-dev-data-layer.template.json",
        ),
    ):
        stack = cloudformation.describe_stacks(StackName=name)["Stacks"][0]
        if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
            raise ValueError(f"Stack is not stable: {name}: {stack['StackStatus']}")
        body = cloudformation.get_template(StackName=name, TemplateStage="Original")["TemplateBody"]
        body = json.loads(body) if isinstance(body, str) else body
        if body != json.loads(source.read_text()):
            raise ValueError(f"Live stack template differs: {name}")
        if name.endswith("agent-runtime"):
            parameters = {
                item["ParameterKey"]: item["ParameterValue"] for item in stack["Parameters"]
            }
            if parameters.get("ArtifactVersionId") != artifact_version_id:
                raise ValueError("Stack artifact parameter differs")
        stacks[name] = stack["StackStatus"]
    log_name = f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-DEFAULT"
    logs = session.client("logs", config=READ_CONFIG).describe_log_groups(
        logGroupNamePrefix=log_name
    )
    if not any(
        item["logGroupName"] == log_name and item.get("retentionInDays") == 7
        for item in logs["logGroups"]
    ):
        raise ValueError("Expected seven-day Runtime log retention")
    head = session.client("s3", config=READ_CONFIG).head_object(
        Bucket=code["bucket"],
        Key=code["prefix"],
        VersionId=artifact_version_id,
        ExpectedBucketOwner=ACCOUNT,
        ChecksumMode="ENABLED",
    )
    if (
        head.get("ChecksumSHA256") != base64.b64encode(bytes.fromhex(artifact_sha256)).decode()
        or head.get("VersionId") != artifact_version_id
        or (expected_size is not None and head.get("ContentLength") != expected_size)
    ):
        raise ValueError("Pinned uploaded artifact checksum/version differs")
    if digest(artifact_path) != artifact_sha256:
        raise ValueError("Local reviewed ZIP checksum differs")
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "scope": scope,
        "identity": identity,
        "runtime": runtime,
        "endpoint": endpoint,
        "policies": policies,
        "stacks": stacks,
        "artifact_head": head,
        "template_sha256": digest(path),
        "review": review,
        "retention_days": 7,
        "artifact_sha256": artifact_sha256,
        "artifact_version_id": artifact_version_id,
    }


def verify_restoration(*, session: Any = None) -> RestorationProof:
    return restoration_proof(verify_checkpoint(scope="parity-v1", session=session))


def restoration_proof(record: dict[str, Any]) -> RestorationProof:
    """Convert an in-memory strict checkpoint after the caller verifies AWS state."""
    runtime, endpoint = record["runtime"], record["endpoint"]
    settings = json.loads(runtime["environmentVariables"]["ANALYTICS_RUNTIME_CONFIG"])
    configuration_sha = canonical_hash(settings)
    expected = json.loads((BASE_ASSEMBLY / TEMPLATE_NAME).read_text())
    expected_settings = json.loads(
        expected["Resources"]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"][
            "ANALYTICS_RUNTIME_CONFIG"
        ]
    )
    return RestorationProof(
        observed_at=record["observed_at"],
        runtime_arn=RUNTIME_ARN,
        runtime_status=runtime["status"],
        endpoint_status=endpoint["status"],
        runtime_version=runtime["agentRuntimeVersion"],
        endpoint_version=endpoint["liveVersion"],
        dataset_version=settings["dataset_version"],
        tenant_id=settings["tenant_id"],
        allowed_regions=tuple(settings["allowed_regions"]),
        reference_date=settings["reference_date"],
        configuration_sha256=configuration_sha,
        expected_configuration_sha256=canonical_hash(expected_settings),
        template_sha256=record["template_sha256"],
        expected_template_sha256=BASE_TEMPLATE_SHA256,
        code_sha256=CODE_SHA256,
        code_version_id=CODE_VERSION,
        resource_policies_verified=True,
        retention_days=7,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicit read-only Runtime checkpoint verification"
    )
    parser.add_argument("--scope", choices=("parity-v1", "retail-v1"), default="parity-v1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = verify_checkpoint(scope=args.scope)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(record, indent=2, default=str) + "\n")
    print(
        f"Verified {args.scope}, Runtime/DEFAULT READY version "
        f"{record['runtime']['agentRuntimeVersion']}; no invocation or mutation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
