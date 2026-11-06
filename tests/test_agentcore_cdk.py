"""Offline assertions for the specific AgentCore/IAM approval boundary."""

import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from aws_cdk import App, Environment
from aws_cdk.assertions import Template
from pydantic import ValidationError

from infrastructure.cdk.agentcore_config import AgentCoreDeploymentConfig
from infrastructure.cdk.agentcore_stack import (
    AgentCoreFoundationStack,
    AnalyticsAgentRuntimeStack,
    invocation_policy,
)
from infrastructure.cdk.config import DeploymentConfig
from infrastructure.cdk.stack import AnalyticsDataStack

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def agentcore_config(tmp_path_factory: pytest.TempPathFactory) -> AgentCoreDeploymentConfig:
    payload = json.loads((ROOT / "infrastructure/cdk/agentcore.config.example.json").read_text())
    artifact = tmp_path_factory.mktemp("runtime-artifact") / "agent.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        for name in (
            "runtime_entry.py",
            "runtime-config.json",
            "enterprise_analytics_agent/__init__.py",
        ):
            archive.writestr(name, "offline fixture")
    payload["artifact_path"] = str(artifact)
    payload["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return AgentCoreDeploymentConfig.model_validate(payload)


@pytest.fixture(scope="module")
def agentcore_templates(
    tmp_path_factory: pytest.TempPathFactory, agentcore_config: AgentCoreDeploymentConfig
) -> tuple[Template, Template, dict[str, Any]]:
    outdir = tmp_path_factory.mktemp("agentcore-cdk")
    app = App(outdir=str(outdir), analytics_reporting=False)
    env = Environment(account=agentcore_config.account, region=agentcore_config.region)
    foundation = AgentCoreFoundationStack(app, "AgentFoundation", config=agentcore_config, env=env)
    agentcore_config.validate_artifact()
    runtime = AnalyticsAgentRuntimeStack(app, "AgentRuntime", config=agentcore_config, env=env)
    app.synth()
    assembly = json.loads((outdir / "manifest.json").read_text())
    return Template.from_stack(foundation), Template.from_stack(runtime), assembly


def test_synthesis_uses_no_account_lookups(
    agentcore_templates: tuple[Template, Template, dict[str, Any]],
) -> None:
    assert not agentcore_templates[2].get("missing")


def test_code_bucket_is_private_versioned_encrypted_retained_and_conditional(
    agentcore_templates: tuple[Template, Template, dict[str, Any]],
) -> None:
    template = agentcore_templates[0]
    template.resource_count_is("AWS::S3::Bucket", 1)
    bucket = next(iter(template.find_resources("AWS::S3::Bucket").values()))
    assert bucket["DeletionPolicy"] == "Retain"
    assert bucket["UpdateReplacePolicy"] == "Retain"
    properties = bucket["Properties"]
    assert properties["VersioningConfiguration"] == {"Status": "Enabled"}
    assert all(properties["PublicAccessBlockConfiguration"].values())
    assert properties["BucketEncryption"]["ServerSideEncryptionConfiguration"] == [
        {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
    ]
    assert properties["LifecycleConfiguration"]["Rules"][0]["AbortIncompleteMultipartUpload"] == {
        "DaysAfterInitiation": 1
    }
    policy = next(iter(template.find_resources("AWS::S3::BucketPolicy").values()))
    statements = policy["Properties"]["PolicyDocument"]["Statement"]
    assert any(statement.get("Sid") == "RequireImmutableCodeCreation" for statement in statements)
    assert any("aws:SecureTransport" in json.dumps(statement) for statement in statements)
    template.resource_count_is("Custom::S3AutoDeleteObjects", 0)


def test_execution_role_has_scoped_bedrock_code_logging_and_assume_role_permissions(
    agentcore_templates: tuple[Template, Template, dict[str, Any]],
    agentcore_config: AgentCoreDeploymentConfig,
) -> None:
    template = agentcore_templates[0]
    role = next(iter(template.find_resources("AWS::IAM::Role").values()))
    trust = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    assert trust["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert trust["Condition"]["StringEquals"] == {"aws:SourceAccount": agentcore_config.account}
    assert "runtime/analytics_dev_agent-*" in json.dumps(trust["Condition"]["ArnLike"])
    policies = template.find_resources("AWS::IAM::Policy")
    statements = [
        statement
        for policy in policies.values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    actions = {action for statement in statements for action in _actions(statement)}
    assert "bedrock:InvokeModel" in actions
    assert "bedrock:InvokeModelWithResponseStream" not in actions
    assert "logs:PutResourcePolicy" not in actions
    assert not any(action.startswith(("athena:", "glue:")) for action in actions)
    for statement in statements:
        current = _actions(statement)
        resources = statement["Resource"]
        if "sts:AssumeRole" in current:
            assert resources == agentcore_config.query_role_arn
        if "bedrock:InvokeModel" in current:
            assert resources == list(agentcore_config.model_resource_arns)
        if "s3:GetObject" in current:
            assert agentcore_config.artifact_key in json.dumps(resources)
            assert "snapshots/" not in json.dumps(resources)
        if resources == "*":
            assert current == ["logs:DescribeLogGroups"]
            assert statement["Condition"] == {
                "StringEquals": {"aws:RequestedRegion": agentcore_config.region}
            }
        if "logs:PutLogEvents" in current:
            assert agentcore_config.log_group_prefix in json.dumps(resources)
            assert ":log-stream:*" in json.dumps(resources)


def _actions(statement: dict[str, Any]) -> list[str]:
    value = statement["Action"]
    return [value] if isinstance(value, str) else value


def test_runtime_is_python312_http_iam_only_with_server_config(
    agentcore_templates: tuple[Template, Template, dict[str, Any]],
    agentcore_config: AgentCoreDeploymentConfig,
) -> None:
    template = agentcore_templates[1]
    runtime = next(iter(template.find_resources("AWS::BedrockAgentCore::Runtime").values()))
    properties = runtime["Properties"]
    assert properties["RoleArn"] == agentcore_config.runtime_role_arn
    assert properties["NetworkConfiguration"] == {"NetworkMode": "PUBLIC"}
    assert properties["ProtocolConfiguration"] == "HTTP"
    assert properties["PlatformVersion"] == "V1"
    assert properties["Tags"] == {"Project": agentcore_config.resource_prefix, "Milestone": "4"}
    assert "AuthorizerConfiguration" not in properties
    assert "RequestHeaderConfiguration" not in properties
    code = properties["AgentRuntimeArtifact"]["CodeConfiguration"]
    assert code["Runtime"] == "PYTHON_3_12"
    assert code["EntryPoint"] == ["runtime_entry.py"]
    assert code["Code"]["S3"]["Prefix"] == agentcore_config.artifact_key
    assert code["Code"]["S3"]["VersionId"] == {"Ref": "ArtifactVersionId"}
    parameter = template.to_json()["Parameters"]["ArtifactVersionId"]
    assert parameter["MinLength"] == 1
    assert "Default" not in parameter
    assert "ContainerConfiguration" not in properties["AgentRuntimeArtifact"]
    settings = json.loads(properties["EnvironmentVariables"]["ANALYTICS_RUNTIME_CONFIG"])
    assert settings["tenant_id"] == "t1"
    assert settings["allowed_regions"] == ["North", "South"]
    assert settings["dataset_version"] == "parity-v1"
    assert settings["reference_date"] == "2025-02-01"
    assert "profile" not in settings
    assert "AWS_PROFILE" not in properties["EnvironmentVariables"]
    assert properties["LifecycleConfiguration"] == {
        "IdleRuntimeSessionTimeout": 300,
        "MaxLifetime": 900,
    }
    template.resource_count_is("AWS::BedrockAgentCore::RuntimeEndpoint", 0)


def test_proposed_cfn_execution_policy_has_only_documented_creation_wildcard() -> None:
    path = ROOT / "infrastructure/cdk/agentcore-deployment-policy.development.json"
    policy = json.loads(path.read_text())
    config = AgentCoreDeploymentConfig.model_validate_json(
        (ROOT / "infrastructure/cdk/agentcore.config.development.json").read_text()
    )
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}
    wildcard = [statement for statement in statements.values() if statement["Resource"] == "*"]
    assert len(wildcard) == 1
    assert wildcard[0]["Action"] == ["bedrock-agentcore:CreateAgentRuntime"]
    assert wildcard[0]["Condition"]["StringEquals"] == {
        "aws:RequestedRegion": config.region,
        "aws:PrincipalAccount": config.account,
        "aws:RequestTag/Project": config.resource_prefix,
    }
    pass_role = statements["PassOnlyRuntimeExecutionRole"]
    assert pass_role["Resource"] == config.runtime_role_arn
    assert pass_role["Condition"] == {
        "StringEquals": {"iam:PassedToService": "bedrock-agentcore.amazonaws.com"}
    }
    assert statements["RuntimeExecutionRoleLifecycle"]["Resource"] == config.runtime_role_arn
    assert statements["RuntimeCodeBucketLifecycle"]["Resource"] == (
        f"arn:aws:s3:::{config.resolved_code_bucket_name}"
    )
    actions = {action for statement in statements.values() for action in _actions(statement)}
    assert not any(action.startswith(("bedrock:", "athena:", "glue:")) for action in actions)
    assert not any("InvokeAgentRuntime" in action for action in actions)
    assert "iam:AttachRolePolicy" not in actions
    assert "bedrock-agentcore:PassCapacityProvider" not in actions
    assert "s3:DeleteBucketOwnershipControls" not in actions
    assert "s3:PutBucketOwnershipControls" in actions
    assert "s3:GetBucketDefaultStorageClass" not in actions
    encoded = json.dumps(policy)
    assert "-data/" not in encoded
    assert "-results/" not in encoded
    assert "-query-executor" not in encoded


def test_proposed_cfn_execution_policy_covers_native_resource_policy_and_identity() -> None:
    policy = json.loads(
        (ROOT / "infrastructure/cdk/agentcore-deployment-policy.development.json").read_text()
    )
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}
    lifecycle = statements["NamedDevelopmentRuntimeLifecycle"]
    assert {
        "bedrock-agentcore:PutResourcePolicy",
        "bedrock-agentcore:GetResourcePolicy",
        "bedrock-agentcore:DeleteResourcePolicy",
        "bedrock-agentcore:CreateAgentRuntimeEndpoint",
        "bedrock-agentcore:DeleteAgentRuntimeEndpoint",
    }.issubset(lifecycle["Action"])
    assert lifecycle["Resource"] == [
        "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/enterprise_analytics_dev_agent-*",
    ]
    identity = statements["AutomaticRuntimeWorkloadIdentity"]
    assert set(identity["Action"]) == {
        "bedrock-agentcore:CreateWorkloadIdentity",
        "bedrock-agentcore:GetWorkloadIdentity",
        "bedrock-agentcore:DeleteWorkloadIdentity",
    }
    assert all("workload-identity-directory/default" in arn for arn in identity["Resource"])
    for suffix, service in (("RuntimeIdentity", "runtime-identity"), ("Network", "network")):
        slr = statements[f"CreateAgentCore{suffix}ServiceLinkedRole"]
        assert slr["Action"] == ["iam:CreateServiceLinkedRole"]
        assert slr["Condition"] == {
            "StringEquals": {"iam:AWSServiceName": f"{service}.bedrock-agentcore.amazonaws.com"}
        }
        assert slr["Resource"].endswith(f"/AWSServiceRoleForBedrockAgentCore{suffix}")


def test_resource_policies_restrict_both_runtime_and_default_endpoint(
    agentcore_templates: tuple[Template, Template, dict[str, Any]],
    agentcore_config: AgentCoreDeploymentConfig,
) -> None:
    template = agentcore_templates[1]
    policies = template.find_resources("AWS::BedrockAgentCore::ResourcePolicy")
    assert len(policies) == 2
    encoded = json.dumps(policies)
    assert "/endpoint/DEFAULT" in encoded
    assert "DenyOtherPrincipals" in encoded
    assert "ArnNotEquals" in encoded
    assert "DenyDelegationAndInteractiveProtocols" in encoded
    policy = invocation_policy(
        agentcore_config, "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/test"
    )
    statements = policy["Statement"]
    assert isinstance(statements, list)
    assert statements[0]["Principal"] == {"AWS": list(agentcore_config.approved_caller_arns)}
    assert statements[1]["Effect"] == "Deny"
    assert statements[1]["Condition"]["ArnNotEquals"]["aws:PrincipalArn"] == list(
        agentcore_config.approved_caller_arns
    )
    assert "bedrock-agentcore:InvokeAgentRuntimeForUser" in statements[2]["Action"]
    assert all(statement["Resource"] != "*" for statement in statements)


def test_log_output_refers_to_agentcore_managed_stdout_group(
    agentcore_templates: tuple[Template, Template, dict[str, Any]],
) -> None:
    foundation, runtime, _ = agentcore_templates
    foundation.resource_count_is("AWS::Logs::LogGroup", 0)
    runtime.resource_count_is("AWS::Logs::LogGroup", 0)
    output = runtime.to_json()["Outputs"]["RuntimeLogGroupName"]["Value"]
    assert "/aws/bedrock-agentcore/runtimes/" in json.dumps(output)
    assert "-DEFAULT" in json.dumps(output)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("approved_caller_arns", ["*"]),
        ("approved_caller_arns", ["arn:aws:iam::111122223333:root"]),
        ("model_resource_arns", ["arn:aws:bedrock:us-west-2::foundation-model/*"]),
        ("query_role_arn", "arn:aws:iam::999900001111:role/OtherAccount"),
        ("artifact_sha256", "not-a-checksum"),
        ("runtime_name", "bad/name"),
    ],
)
def test_rejects_unsafe_approval_scope(
    agentcore_config: AgentCoreDeploymentConfig, field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        AgentCoreDeploymentConfig.model_validate(agentcore_config.model_dump() | {field: value})


def test_runtime_synthesis_requires_reviewed_archive_checksum(
    agentcore_config: AgentCoreDeploymentConfig,
) -> None:
    bad = agentcore_config.model_copy(update={"artifact_sha256": "f" * 64})
    with pytest.raises(ValueError, match="checksum"):
        bad.validate_artifact()


def test_runtime_scope_must_match_infrastructure(
    agentcore_config: AgentCoreDeploymentConfig,
) -> None:
    bad = agentcore_config.model_copy(update={"model_id": "some-other-model"})
    with pytest.raises(ValueError, match="differ"):
        bad.runtime_settings_json()


def test_dataset_override_is_trusted_deployment_environment(
    tmp_path: Path, agentcore_config: AgentCoreDeploymentConfig
) -> None:
    config = agentcore_config.model_copy(update={"dataset_version_override": "parity-legacy-v1"})
    app = App(outdir=str(tmp_path), analytics_reporting=False)
    stack = AnalyticsAgentRuntimeStack(
        app,
        "LegacyDatasetRuntime",
        config=config,
        env=Environment(account=config.account, region=config.region),
    )
    app.synth()
    runtime = next(
        iter(Template.from_stack(stack).find_resources("AWS::BedrockAgentCore::Runtime").values())
    )
    assert runtime["Properties"]["EnvironmentVariables"]["ANALYTICS_DATASET_VERSION"] == (
        "parity-legacy-v1"
    )
    assert "RequestHeaderConfiguration" not in runtime["Properties"]


def test_athena_stack_update_only_extends_query_trust_and_preserves_developer(
    tmp_path: Path,
) -> None:
    config = DeploymentConfig.model_validate_json(
        (ROOT / "infrastructure/cdk/config.example.json").read_text()
    )
    runtime_arn = f"arn:aws:iam::{config.account}:role/enterprise-analytics-dev-agent-runtime"
    templates: list[dict[str, Any]] = []
    for index, current in enumerate(
        (config, config.model_copy(update={"trusted_query_principal_arns": (runtime_arn,)}))
    ):
        app = App(outdir=str(tmp_path / str(index)), analytics_reporting=False)
        stack = AnalyticsDataStack(
            app,
            "SameDataLayer",
            config=current,
            env=Environment(account=config.account, region=config.region),
        )
        app.synth()
        templates.append(dict(Template.from_stack(stack).to_json()))
    original, updated = deepcopy(templates)
    role_id = next(
        name
        for name, resource in original["Resources"].items()
        if resource["Type"] == "AWS::IAM::Role"
        and resource["Properties"]["RoleName"].endswith("query-executor")
    )
    old_trust = original["Resources"][role_id]["Properties"].pop("AssumeRolePolicyDocument")
    new_trust = updated["Resources"][role_id]["Properties"].pop("AssumeRolePolicyDocument")
    assert config.trusted_query_principal_arn in json.dumps(new_trust)
    assert runtime_arn in json.dumps(new_trust)
    assert runtime_arn not in json.dumps(old_trust)
    assert original == updated


@pytest.mark.parametrize(
    "principals",
    [("*",), ("arn:aws:iam::111122223333:root",), ("arn:aws:iam::111122223333:role/A",) * 2],
)
def test_query_trust_extension_rejects_broad_or_duplicate_principals(
    principals: tuple[str, ...],
) -> None:
    payload = json.loads((ROOT / "infrastructure/cdk/config.example.json").read_text())
    payload["trusted_query_principal_arns"] = principals
    with pytest.raises(ValidationError):
        DeploymentConfig.model_validate(payload)
