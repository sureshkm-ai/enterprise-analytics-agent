"""Candidate code is a separate pin; restoration continues requiring the original code."""

import base64
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from enterprise_analytics_agent.adapters import retail_checkpoint
from enterprise_analytics_agent.adapters.retail_checkpoint import (
    RUNTIME_ARN,
    _verify_runtime,
    verify_candidate_checkpoint,
)
from enterprise_analytics_agent.retail_evaluation.campaign import CODE_SHA256, CODE_VERSION
from enterprise_analytics_agent.retail_evaluation.deployment import (
    BASE_ASSEMBLY,
    BASE_TEMPLATE_SHA256,
    CHANGES,
    TEMPLATE_NAME,
    candidate_review_templates,
)
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    RepairReview,
)

CODE_BUCKET = "enterprise-analytics-dev-453711491609-us-west-2-agent-code"
CANDIDATE_SHA = "b" * 64
CANDIDATE_VERSION = "actual-version-from-approved-upload"


def templates() -> tuple[dict[str, Any], dict[str, Any]]:
    settings: dict[str, Any] = {name: before for name, (before, _) in CHANGES.items()}
    settings["allowed_regions"] = ["North", "South"]
    base: dict[str, Any] = {
        "Parameters": {"ArtifactVersionId": {"Type": "String"}},
        "Resources": {
            "AnalyticsRuntime": {
                "Type": "AWS::BedrockAgentCore::Runtime",
                "Properties": {
                    "EnvironmentVariables": {"ANALYTICS_RUNTIME_CONFIG": json.dumps(settings)},
                    "RoleArn": "reviewed-role",
                    "PlatformVersion": "V1",
                    "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
                    "LifecycleConfiguration": {
                        "IdleRuntimeSessionTimeout": 300,
                        "MaxLifetime": 900,
                    },
                    "ProtocolConfiguration": "HTTP",
                    "AgentRuntimeArtifact": {
                        "CodeConfiguration": {
                            "Runtime": "PYTHON_3_12",
                            "EntryPoint": ["runtime_entry.py"],
                            "Code": {
                                "S3": {
                                    "Bucket": CODE_BUCKET,
                                    "Prefix": f"releases/{CODE_SHA256}/agent.zip",
                                    "VersionId": {"Ref": "ArtifactVersionId"},
                                }
                            },
                        }
                    },
                },
            },
            "RuntimeInboundPolicy": {
                "Type": "AWS::BedrockAgentCore::ResourcePolicy",
                "Properties": {
                    "ResourceArn": {"Fn::GetAtt": ["AnalyticsRuntime", "AgentRuntimeArn"]},
                    "Policy": json.dumps({"Statement": [{"Principal": {"AWS": "approved"}}]}),
                },
            },
            "DefaultEndpointInboundPolicy": {
                "Type": "AWS::BedrockAgentCore::ResourcePolicy",
                "Properties": {
                    "ResourceArn": {
                        "Fn::Join": [
                            "",
                            [
                                {"Fn::GetAtt": ["AnalyticsRuntime", "AgentRuntimeArn"]},
                                "/runtime-endpoint/DEFAULT",
                            ],
                        ]
                    },
                    "Policy": json.dumps({"Statement": [{"Principal": {"AWS": "approved"}}]}),
                },
            },
        },
    }
    candidate = deepcopy(base)
    properties = candidate["Resources"]["AnalyticsRuntime"]["Properties"]
    settings.update({name: after for name, (_, after) in CHANGES.items()})
    properties["EnvironmentVariables"]["ANALYTICS_RUNTIME_CONFIG"] = json.dumps(settings)
    properties["AgentRuntimeArtifact"]["CodeConfiguration"]["Code"]["S3"]["Prefix"] = (
        f"releases/{CANDIDATE_SHA}/agent.zip"
    )
    return base, candidate


def runtime_for(template: dict[str, Any], *, version: str) -> tuple[dict[str, Any], dict[str, Any]]:
    properties = template["Resources"]["AnalyticsRuntime"]["Properties"]
    code = properties["AgentRuntimeArtifact"]["CodeConfiguration"]
    runtime = {
        "status": "READY",
        "agentRuntimeArn": RUNTIME_ARN,
        "agentRuntimeVersion": "9",
        "environmentVariables": properties["EnvironmentVariables"],
        "roleArn": properties["RoleArn"],
        "platformVersion": properties["PlatformVersion"],
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 300, "maxLifetime": 900},
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        "agentRuntimeArtifact": {
            "codeConfiguration": {
                "runtime": code["Runtime"],
                "entryPoint": code["EntryPoint"],
                "code": {
                    "s3": {
                        "bucket": code["Code"]["S3"]["Bucket"],
                        "prefix": code["Code"]["S3"]["Prefix"],
                        "versionId": version,
                    }
                },
            }
        },
    }
    endpoint = {
        "status": "READY",
        "liveVersion": "9",
        "agentRuntimeEndpointArn": RUNTIME_ARN + "/runtime-endpoint/DEFAULT",
    }
    return runtime, endpoint


def test_candidate_delta_is_exactly_new_key_plus_three_settings() -> None:
    base, candidate = templates()
    changes = candidate_review_templates(base, candidate, candidate_sha256=CANDIDATE_SHA)
    assert set(changes) == {*CHANGES, "artifact_key"}
    assert changes["artifact_key"] == {
        "before": f"releases/{CODE_SHA256}/agent.zip",
        "after": f"releases/{CANDIDATE_SHA}/agent.zip",
    }


@pytest.mark.parametrize("change", ["bucket", "version", "role", "policy", "scope", "resource"])
def test_candidate_review_rejects_every_unapproved_delta(change: str) -> None:
    base, candidate = templates()
    properties = candidate["Resources"]["AnalyticsRuntime"]["Properties"]
    s3 = properties["AgentRuntimeArtifact"]["CodeConfiguration"]["Code"]["S3"]
    if change == "bucket":
        s3["Bucket"] = "another-code-bucket"
    elif change == "version":
        s3["VersionId"] = "invented-before-upload"
    elif change == "role":
        properties["RoleArn"] = "more-powerful-role"
    elif change == "policy":
        candidate["Resources"]["RuntimeInboundPolicy"]["Policy"] = "weakened"
    elif change == "scope":
        properties["EnvironmentVariables"]["ANALYTICS_DATASET_VERSION"] = "retail-v1"
    else:
        candidate["Resources"]["ExtraRole"] = {"Type": "AWS::IAM::Role"}
    with pytest.raises(ValueError):
        candidate_review_templates(base, candidate, candidate_sha256=CANDIDATE_SHA)


def test_original_restoration_check_does_not_accept_candidate_even_with_parity_scope() -> None:
    base, candidate = templates()
    # Giving the candidate the old scope cannot make it pass the original artifact pin.
    candidate["Resources"]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"] = deepcopy(
        base["Resources"]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"]
    )
    runtime, endpoint = runtime_for(candidate, version=CANDIDATE_VERSION)
    with pytest.raises(ValueError, match="different artifact"):
        _verify_runtime(runtime, endpoint, candidate)
    original, endpoint = runtime_for(base, version=CODE_VERSION)
    assert _verify_runtime(original, endpoint, base)["versionId"] == CODE_VERSION


def test_explicit_candidate_pin_rejects_original_or_another_version() -> None:
    _, candidate = templates()
    runtime, endpoint = runtime_for(candidate, version=CANDIDATE_VERSION)
    assert (
        _verify_runtime(
            runtime,
            endpoint,
            candidate,
            artifact_sha256=CANDIDATE_SHA,
            artifact_version_id=CANDIDATE_VERSION,
        )["versionId"]
        == CANDIDATE_VERSION
    )
    with pytest.raises(ValueError, match="different artifact"):
        _verify_runtime(
            runtime,
            endpoint,
            candidate,
            artifact_sha256=CANDIDATE_SHA,
            artifact_version_id="another-upload",
        )


@dataclass
class ReviewedFixture:
    review: RepairReview
    version: CandidateVersionBinding
    runtime: dict[str, Any]
    endpoint: dict[str, Any]
    candidate: dict[str, Any]
    infrastructure: dict[str, dict[str, Any]]
    calls: list[tuple[str, dict[str, Any]]]
    head: dict[str, Any]
    session: Any


@pytest.fixture
def reviewed_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReviewedFixture:
    from enterprise_analytics_agent.retail_evaluation import deployment

    monkeypatch.chdir(tmp_path)
    base, candidate = templates()
    content = b"independently authored candidate archive bytes"
    candidate_sha = hashlib.sha256(content).hexdigest()
    candidate["Resources"]["AnalyticsRuntime"]["Properties"]["AgentRuntimeArtifact"][
        "CodeConfiguration"
    ]["Code"]["S3"]["Prefix"] = f"releases/{candidate_sha}/agent.zip"
    candidate_dir = Path("artifacts/milestone-5/q18-repair-v1")
    candidate_zip = candidate_dir / "candidate/agent.zip"
    candidate_template = candidate_dir / "cdk.candidate.out" / TEMPLATE_NAME
    original_zip = Path("artifacts/agentcore/agent.zip")
    base_template = BASE_ASSEMBLY / TEMPLATE_NAME
    restore_template = Path("artifacts/milestone-5/cdk.restore.out") / TEMPLATE_NAME
    infrastructure = {
        "enterprise-analytics-dev-agent-foundation": {"reviewed": "foundation"},
        "enterprise-analytics-dev-data-layer": {"reviewed": "data"},
    }
    for path, blob in ((candidate_zip, content), (original_zip, b"original reviewed code")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    for path, value in (
        (candidate_template, candidate),
        (base_template, base),
        (restore_template, base),
        (
            BASE_ASSEMBLY / "enterprise-analytics-dev-agent-foundation.template.json",
            infrastructure["enterprise-analytics-dev-agent-foundation"],
        ),
        (
            Path(
                "artifacts/cdk.m4-data-trust.cli.out/enterprise-analytics-dev-data-layer.template.json"
            ),
            infrastructure["enterprise-analytics-dev-data-layer"],
        ),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    # The original fixture stands in for historical immutable bytes. Candidate hashes,
    # size, object key, VersionId and live responses are verified by production code.
    real_digest = deployment.digest

    def fixture_digest(path: Path) -> str:
        if path == original_zip:
            return CODE_SHA256
        if path in {base_template, restore_template}:
            return BASE_TEMPLATE_SHA256
        return real_digest(path)

    monkeypatch.setattr(deployment, "digest", fixture_digest)
    monkeypatch.setattr(retail_checkpoint, "digest", fixture_digest)
    review = RepairReview(
        candidate_artifact_path=str(candidate_zip),
        candidate_assembly_path=str(candidate_template.parent),
        candidate_sha256=candidate_sha,
        candidate_template_sha256=real_digest(candidate_template),
        questions_sha256="1" * 64,
        expected_results_sha256="2" * 64,
        source_patch_sha256="3" * 64,
    )
    version = CandidateVersionBinding(
        review_sha256=review.review_sha256,
        candidate_sha256=candidate_sha,
        candidate_template_sha256=review.candidate_template_sha256,
        bucket="enterprise-analytics-dev-453711491609-us-west-2-agent-code",
        key=f"releases/{candidate_sha}/agent.zip",
        version_id=CANDIDATE_VERSION,
        checksum_sha256=candidate_sha,
        size_bytes=len(content),
        verified_at=datetime.now(UTC),
    )
    runtime, endpoint = runtime_for(candidate, version=CANDIDATE_VERSION)
    runtime["createdAt"] = endpoint["createdAt"] = datetime(2026, 11, 9, tzinfo=UTC)
    calls: list[tuple[str, dict[str, Any]]] = []
    head = {
        "VersionId": CANDIDATE_VERSION,
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(candidate_sha)).decode(),
        "ContentLength": len(content),
        "LastModified": datetime(2026, 11, 9, tzinfo=UTC),
    }

    class Service:
        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": "453711491609"}

        def get_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(("runtime", kwargs))
            return runtime

        def get_agent_runtime_endpoint(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(("endpoint", kwargs))
            return endpoint

        def get_resource_policy(self, **kwargs: Any) -> dict[str, str]:
            calls.append(("policy", kwargs))
            return {"policy": json.dumps({"Statement": [{"Principal": {"AWS": ["approved"]}}]})}

        def describe_stacks(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "Stacks": [
                    {
                        "StackStatus": "UPDATE_COMPLETE",
                        "Parameters": [
                            {
                                "ParameterKey": "ArtifactVersionId",
                                "ParameterValue": CANDIDATE_VERSION,
                            }
                        ],
                    }
                ]
            }

        def get_template(self, **kwargs: Any) -> dict[str, Any]:
            body = (
                candidate
                if kwargs["StackName"].endswith("agent-runtime")
                else infrastructure[kwargs["StackName"]]
            )
            return {"TemplateBody": body}

        def describe_log_groups(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "logGroups": [{"logGroupName": kwargs["logGroupNamePrefix"], "retentionInDays": 7}]
            }

        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(("head", kwargs))
            return head

    class Session:
        def client(self, name: str, **kwargs: Any) -> Service:
            calls.append(("client", {"name": name}))
            return Service()

    return ReviewedFixture(
        review, version, runtime, endpoint, candidate, infrastructure, calls, head, Session()
    )


def test_candidate_checkpoint_uses_only_reviewed_new_artifact_pin(
    reviewed_fixture: ReviewedFixture,
) -> None:
    fixture = reviewed_fixture
    record = verify_candidate_checkpoint(fixture.review, fixture.version, session=fixture.session)
    assert record["artifact_sha256"] == fixture.review.candidate_sha256
    assert record["artifact_version_id"] == CANDIDATE_VERSION
    assert len([call for call in fixture.calls if call[0] == "policy"]) == 2
    head = next(arguments for operation, arguments in fixture.calls if operation == "head")
    assert head["VersionId"] == CANDIDATE_VERSION and head["Key"] == fixture.version.key
    assert isinstance(record["runtime"]["createdAt"], datetime)


@pytest.mark.parametrize(
    "failure", ["local_zip", "local_template", "review_binding", "size_binding"]
)
def test_unpinned_candidate_fails_before_sdk_construction(
    reviewed_fixture: ReviewedFixture, failure: str
) -> None:
    fixture = reviewed_fixture
    version = fixture.version
    if failure == "local_zip":
        Path(fixture.review.candidate_artifact_path).write_bytes(b"different ZIP")
    elif failure == "local_template":
        (Path(fixture.review.candidate_assembly_path) / TEMPLATE_NAME).write_text("{}")
    elif failure == "review_binding":
        version = version.model_copy(update={"review_sha256": "0" * 64})
    else:
        version = version.model_copy(update={"size_bytes": version.size_bytes + 1})
    with pytest.raises(ValueError):
        verify_candidate_checkpoint(fixture.review, version, session=fixture.session)
    assert fixture.calls == []


@pytest.mark.parametrize(
    "failure", ["live_version", "live_prefix", "head_version", "head_checksum", "head_size"]
)
def test_live_candidate_mismatch_never_counts_as_verified(
    reviewed_fixture: ReviewedFixture, failure: str
) -> None:
    fixture = reviewed_fixture
    if failure == "live_version":
        fixture.runtime["agentRuntimeArtifact"]["codeConfiguration"]["code"]["s3"]["versionId"] = (
            CODE_VERSION
        )
    elif failure == "live_prefix":
        fixture.runtime["agentRuntimeArtifact"]["codeConfiguration"]["code"]["s3"]["prefix"] = (
            f"releases/{CODE_SHA256}/agent.zip"
        )
    elif failure == "head_version":
        fixture.head["VersionId"] = CODE_VERSION
    elif failure == "head_checksum":
        fixture.head["ChecksumSHA256"] = base64.b64encode(bytes.fromhex(CODE_SHA256)).decode()
    else:
        fixture.head["ContentLength"] += 1
    with pytest.raises(ValueError):
        verify_candidate_checkpoint(fixture.review, fixture.version, session=fixture.session)
