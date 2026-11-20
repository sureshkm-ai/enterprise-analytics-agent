"""Offline assertions for isolated streaming infrastructure and explicit artifact pins."""

import json
from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import boto3
import pytest
from aws_cdk import App, Environment
from aws_cdk.assertions import Template
from pydantic import ValidationError

from infrastructure.agentcore import package
from infrastructure.cdk.streaming_app import (
    ACCOUNT,
    CODE_BUCKET,
    DEFAULT_PROJECT,
    PREFIX,
    QUERY_ROLE,
    REGION,
    StreamingDeploymentConfig,
    StreamingRuntimeStack,
    _inbound_policy,
)

AUTHORED_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
    "enterprise_analytics_stream_nova_lite-AuthoredFixture"
)
AUTHORED_CALLER = "arn:aws:iam::453711491609:role/ApprovedDeveloper"
SECOND_AUTHORED_CALLER = "arn:aws:iam::453711491609:role/SecondApprovedDeveloper"
# AWS's single-caller readback shape uses scalar ARN values in these two
# locations. This independently authored response protects exact comparison
# without teaching the runtime verifier to weaken or normalize policy equality.
AUTHORED_SINGLE_CALLER_READBACK: dict[str, Any] = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowApprovedCallers",
            "Effect": "Allow",
            "Principal": {"AWS": "arn:aws:iam::453711491609:role/ApprovedDeveloper"},
            "Action": "bedrock-agentcore:InvokeAgentRuntime",
            "Resource": AUTHORED_RUNTIME_ARN,
        },
        {
            "Sid": "DenyOtherPrincipals",
            "Effect": "Deny",
            "Principal": "*",
            "Action": "bedrock-agentcore:InvokeAgentRuntime",
            "Resource": AUTHORED_RUNTIME_ARN,
            "Condition": {
                "ArnNotEquals": {
                    "aws:PrincipalArn": "arn:aws:iam::453711491609:role/ApprovedDeveloper"
                }
            },
        },
        {
            "Sid": "DenyDelegationAndInteractiveProtocols",
            "Effect": "Deny",
            "Principal": "*",
            "Action": [
                "bedrock-agentcore:InvokeAgentRuntimeForUser",
                "bedrock-agentcore:InvokeAgentRuntimeCommand",
                "bedrock-agentcore:InvokeAgentRuntimeCommandShell",
                "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream",
                "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStreamForUser",
            ],
            "Resource": AUTHORED_RUNTIME_ARN,
        },
    ],
}


@pytest.mark.parametrize("endpoint", [False, True], ids=("runtime", "DEFAULT"))
def test_single_caller_policy_matches_authored_aws_readback(endpoint: bool) -> None:
    resource = AUTHORED_RUNTIME_ARN + ("/runtime-endpoint/DEFAULT" if endpoint else "")
    expected = deepcopy(AUTHORED_SINGLE_CALLER_READBACK)
    for statement in expected["Statement"]:
        statement["Resource"] = resource
    assert _inbound_policy((AUTHORED_CALLER,), resource) == expected


@pytest.mark.parametrize("endpoint", [False, True], ids=("runtime", "DEFAULT"))
def test_multiple_callers_keep_exact_allow_and_deny_arn_lists(endpoint: bool) -> None:
    resource = AUTHORED_RUNTIME_ARN + ("/runtime-endpoint/DEFAULT" if endpoint else "")
    expected = deepcopy(AUTHORED_SINGLE_CALLER_READBACK)
    for statement in expected["Statement"]:
        statement["Resource"] = resource
    expected["Statement"][0]["Principal"] = {"AWS": [AUTHORED_CALLER, SECOND_AUTHORED_CALLER]}
    expected["Statement"][1]["Condition"] = {
        "ArnNotEquals": {"aws:PrincipalArn": [AUTHORED_CALLER, SECOND_AUTHORED_CALLER]}
    }
    assert _inbound_policy((AUTHORED_CALLER, SECOND_AUTHORED_CALLER), resource) == expected


@pytest.mark.parametrize("multiple_callers", [False, True], ids=("one-caller", "two-callers"))
def test_synthesized_runtime_and_endpoint_policies_match_service_shape(
    tmp_path: Path, multiple_callers: bool
) -> None:
    raw = configuration()
    if multiple_callers:
        raw["approved_caller_arns"].append(SECOND_AUTHORED_CALLER)
    config = StreamingDeploymentConfig.model_validate(raw)
    app = App(outdir=str(tmp_path / "service-readback-shape"), analytics_reporting=False)
    stack = StreamingRuntimeStack(
        app,
        "PolicyReadbackShape",
        config=config,
        model=config.models[0],
        env=Environment(account=ACCOUNT, region=REGION),
    )
    app.synth()
    template = Template.from_stack(stack).to_json()
    for logical_id, resource_arn in (
        ("RuntimeInboundPolicy", AUTHORED_RUNTIME_ARN),
        ("EndpointInboundPolicy", AUTHORED_RUNTIME_ARN + "/runtime-endpoint/DEFAULT"),
    ):
        # Resolve only the authored Runtime ARN placeholder in CDK's serialized
        # JSON. The expected policy remains the literal AWS response above.
        serialized = template["Resources"][logical_id]["Properties"]["Policy"]
        assert set(serialized) == {"Fn::Join"}
        separator, parts = serialized["Fn::Join"]
        assert separator == ""
        resolved = []
        for part in parts:
            if isinstance(part, str):
                resolved.append(part)
            else:
                assert part == {"Fn::GetAtt": ["StreamingRuntime", "AgentRuntimeArn"]}
                resolved.append(AUTHORED_RUNTIME_ARN)
        actual = json.loads("".join(resolved))
        expected = deepcopy(AUTHORED_SINGLE_CALLER_READBACK)
        for statement in expected["Statement"]:
            statement["Resource"] = resource_arn
        if multiple_callers:
            expected["Statement"][0]["Principal"] = {
                "AWS": [AUTHORED_CALLER, SECOND_AUTHORED_CALLER]
            }
            expected["Statement"][1]["Condition"] = {
                "ArnNotEquals": {"aws:PrincipalArn": [AUTHORED_CALLER, SECOND_AUTHORED_CALLER]}
            }
        assert actual == expected


def configuration(*, bound: bool = True) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "account": ACCOUNT,
        "region": REGION,
        "model_id": "us.amazon.nova-lite-v1:0",
        "query_role_arn": QUERY_ROLE,
        "database": "analytics",
        "workgroup": "analytics-dev",
        "source_bucket": "retail-source",
        "results_bucket": "retail-results",
        "dataset_version": "retail-v1",
        "reference_date": "2025-04-01",
        "principal_id": "streaming-application",
        "tenant_id": "retail_demo",
        "allowed_regions": ["North", "South"],
        "max_iterations": 5,
        "max_total_tokens": 12000,
    }
    native = {
        "key": "nova-lite",
        "runtime_name": "enterprise_analytics_stream_nova_lite",
        "settings": settings,
        "transport": "converse",
        "model_resource_arns": [
            f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/us.amazon.nova-lite-v1:0",
            f"arn:aws:bedrock:{REGION}::foundation-model/amazon.nova-lite-v1:0",
            "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
            "arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-lite-v1:0",
        ],
    }
    mantle = {
        "key": "gemma-27b",
        "runtime_name": "enterprise_analytics_stream_gemma_27b",
        "settings": {**settings, "model_id": "google.gemma-3-27b-it"},
        "transport": "mantle_chat",
    }
    return {
        "profile": "analytics-dev",
        "account": ACCOUNT,
        "region": REGION,
        "resource_prefix": PREFIX,
        "code_bucket": CODE_BUCKET,
        "artifact_sha256": "a" * 64,
        "artifact_key": "releases/" + "a" * 64 + "/agent.zip",
        "artifact_version_id": "AUTHORED-OFFLINE-VERSION" if bound else None,
        "approved_caller_arns": [f"arn:aws:iam::{ACCOUNT}:role/ApprovedDeveloper"],
        "models": [native, mantle],
    }


@pytest.fixture(scope="module")
def templates(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], ...]:
    config = StreamingDeploymentConfig.model_validate(configuration())
    outdir = tmp_path_factory.mktemp("streaming-synth")
    app = App(outdir=str(outdir), analytics_reporting=False)
    stacks = []
    for model in config.models:
        stack = StreamingRuntimeStack(
            app,
            f"{PREFIX}-{model.key}",
            config=config,
            model=model,
            env=Environment(account=config.account, region=config.region),
        )
        stacks.append(stack)
    app.synth()
    assert not json.loads((outdir / "manifest.json").read_text()).get("missing")
    return tuple(dict(Template.from_stack(stack).to_json()) for stack in stacks)


def statements(template: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        statement
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::IAM::Policy"
        for statement in resource["Properties"]["PolicyDocument"]["Statement"]
    ]


def actions(statement: dict[str, Any]) -> list[str]:
    value = statement["Action"]
    return value if isinstance(value, list) else [value]


def test_synthesis_reuses_data_storage_and_does_not_change_query_trust(
    templates: tuple[dict[str, Any], ...],
) -> None:
    for template in templates:
        types = [resource["Type"] for resource in template["Resources"].values()]
        assert types.count("AWS::BedrockAgentCore::Runtime") == 1
        assert types.count("AWS::IAM::Role") == 1
        assert types.count("AWS::BedrockAgentCore::ResourcePolicy") == 2
        assert not any(
            value.startswith(("AWS::S3::", "AWS::Glue::", "AWS::Athena::")) for value in types
        )
        assert not any(value.startswith("Custom::") for value in types)
        roles = [r for r in template["Resources"].values() if r["Type"] == "AWS::IAM::Role"]
        assert roles[0]["Properties"]["RoleName"].startswith(PREFIX + "-")
        proposal = json.loads(template["Outputs"]["QueryRoleTrustAdditionProposalOnly"]["Value"])
        assert proposal["Action"] == "sts:AssumeRole"
        assert proposal["Principal"]["AWS"].startswith(f"arn:aws:iam::{ACCOUNT}:role/{PREFIX}-")
        assert "enterprise-analytics-dev-query-executor" not in json.dumps(roles)


def test_native_permissions_scope_model_code_query_and_logs(
    templates: tuple[dict[str, Any], ...],
) -> None:
    native = templates[0]
    grants = statements(native)
    inference = next(value for value in grants if "bedrock:InvokeModel" in actions(value))
    assert actions(inference) == ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    assert inference["Resource"] == configuration()["models"][0]["model_resource_arns"]
    assert not any("bedrock-mantle:CreateInference" in actions(value) for value in grants)
    query = next(value for value in grants if "sts:AssumeRole" in actions(value))
    assert query["Resource"] == QUERY_ROLE
    code = next(value for value in grants if "s3:GetObject" in actions(value))
    assert code["Resource"] == f"arn:aws:s3:::{CODE_BUCKET}/releases/" + "a" * 64 + "/agent.zip"
    for value in grants:
        assert not any(
            action.startswith(("athena:", "glue:", "iam:", "s3:Put")) for action in actions(value)
        )
        if value["Resource"] == "*":
            assert actions(value) == ["logs:DescribeLogGroups"]
            assert value["Condition"] == {"StringEquals": {"aws:RequestedRegion": REGION}}
    role = next(r for r in native["Resources"].values() if r["Type"] == "AWS::IAM::Role")
    trust = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    assert trust["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert trust["Condition"]["StringEquals"] == {"aws:SourceAccount": ACCOUNT}
    assert "enterprise_analytics_stream_nova_lite-*" in json.dumps(trust)


@pytest.mark.parametrize(
    ("index", "own_log_group"),
    [
        (
            0,
            "arn:aws:logs:us-west-2:453711491609:log-group:"
            "/aws/bedrock-agentcore/runtimes/enterprise_analytics_stream_nova_lite-*",
        ),
        (
            1,
            "arn:aws:logs:us-west-2:453711491609:log-group:"
            "/aws/bedrock-agentcore/runtimes/enterprise_analytics_stream_gemma_27b-*",
        ),
    ],
    ids=("nova", "gemma"),
)
def test_runtime_can_configure_only_its_own_scoped_log_resource_policy(
    templates: tuple[dict[str, Any], ...], index: int, own_log_group: str
) -> None:
    grants = statements(templates[index])
    resource_policy_grants = [
        grant for grant in grants if "logs:PutResourcePolicy" in actions(grant)
    ]
    assert resource_policy_grants == [
        {
            "Action": "logs:PutResourcePolicy",
            "Effect": "Allow",
            "Resource": own_log_group,
            "Condition": {"StringEquals": {"aws:RequestedRegion": "us-west-2"}},
        }
    ]
    assert {
        action for grant in grants for action in actions(grant) if action.startswith("logs:")
    } == {
        "logs:CreateLogGroup",
        "logs:DescribeLogStreams",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:PutResourcePolicy",
    }


@pytest.mark.parametrize(
    ("resource", "expected_match"),
    [
        (
            "arn:aws:logs:us-west-2:453711491609:log-group:"
            "/aws/bedrock-agentcore/runtimes/enterprise_analytics_stream_nova_lite-Authored-DEFAULT",
            True,
        ),
        (
            "arn:aws:logs:us-west-2:453711491609:log-group:"
            "/aws/bedrock-agentcore/runtimes/enterprise_analytics_stream_gemma_27b-Authored-DEFAULT",
            False,
        ),
        (
            "arn:aws:logs:us-west-2:453711491609:log-group:"
            "/aws/bedrock-agentcore/runtimes/enterprise_analytics_dev_agent-Authored-DEFAULT",
            False,
        ),
        (
            "arn:aws:logs:us-east-1:453711491609:log-group:"
            "/aws/bedrock-agentcore/runtimes/enterprise_analytics_stream_nova_lite-Authored-DEFAULT",
            False,
        ),
        (
            "arn:aws:logs:us-west-2:111122223333:log-group:"
            "/aws/bedrock-agentcore/runtimes/enterprise_analytics_stream_nova_lite-Authored-DEFAULT",
            False,
        ),
        (
            "arn:aws:logs:us-west-2:453711491609:log-group:/aws/unrelated/application",
            False,
        ),
        (
            "arn:aws:logs:us-west-2:453711491609:resource-policy:AccountWidePolicy",
            False,
        ),
    ],
    ids=("own", "other-model", "legacy", "region", "account", "unrelated", "account-policy"),
)
def test_log_resource_policy_grant_excludes_other_roles_and_account_policies(
    templates: tuple[dict[str, Any], ...], resource: str, expected_match: bool
) -> None:
    grant = next(
        grant for grant in statements(templates[0]) if "logs:PutResourcePolicy" in actions(grant)
    )
    assert fnmatchcase(resource, grant["Resource"]) is expected_match


def test_mantle_permissions_use_exact_project_and_model_condition(
    templates: tuple[dict[str, Any], ...],
) -> None:
    grants = statements(templates[1])
    inference = next(
        value for value in grants if "bedrock-mantle:CreateInference" in actions(value)
    )
    assert inference["Resource"] == DEFAULT_PROJECT
    assert inference["Condition"] == {
        "StringEquals": {
            "bedrock-mantle:Model": "google.gemma-3-27b-it",
            "aws:RequestedRegion": REGION,
        }
    }
    assert not any(
        any(action.startswith("bedrock:") for action in actions(value)) for value in grants
    )
    assert not any("bedrock-mantle:CreateProject" in actions(value) for value in grants)


def test_runtime_is_version_pinned_and_fixed_scope_with_correct_endpoint_policy(
    templates: tuple[dict[str, Any], ...],
) -> None:
    for template in templates:
        runtime_id, resource = next(
            (name, value)
            for name, value in template["Resources"].items()
            if value["Type"] == "AWS::BedrockAgentCore::Runtime"
        )
        properties = resource["Properties"]
        code = properties["AgentRuntimeArtifact"]["CodeConfiguration"]
        assert code["Runtime"] == "PYTHON_3_12" and code["EntryPoint"] == ["runtime_entry.py"]
        assert code["Code"]["S3"]["VersionId"] == "AUTHORED-OFFLINE-VERSION"
        assert code["Code"]["S3"]["Bucket"] == CODE_BUCKET
        assert properties["NetworkConfiguration"] == {"NetworkMode": "PUBLIC"}
        assert properties["ProtocolConfiguration"] == "HTTP"
        assert "AuthorizerConfiguration" not in properties
        settings = json.loads(properties["EnvironmentVariables"]["ANALYTICS_RUNTIME_CONFIG"])
        assert settings["tenant_id"] == "retail_demo"
        assert settings["allowed_regions"] == ["North", "South"]
        assert settings["query_role_arn"] == QUERY_ROLE
        assert settings["max_iterations"] == 5 and settings["max_total_tokens"] == 12000
        policy_id = next(
            name
            for name, value in template["Resources"].items()
            if value["Type"] == "AWS::IAM::Policy"
        )
        assert policy_id in resource["DependsOn"]
        policies = [
            value
            for value in template["Resources"].values()
            if value["Type"] == "AWS::BedrockAgentCore::ResourcePolicy"
        ]
        assert len(policies) == 2
        assert any("/runtime-endpoint/DEFAULT" in json.dumps(value) for value in policies)
        assert all(":runtime-endpoint" not in json.dumps(value) for value in policies)
        for policy in policies:
            assert runtime_id in policy["DependsOn"]
            text = json.dumps(policy)
            assert "AllowApprovedCallers" in text and "DenyOtherPrincipals" in text
            assert "ApprovedDeveloper" in text


def test_unbound_artifact_is_explicit_offline_preview_with_required_parameter(
    tmp_path: Path,
) -> None:
    config = StreamingDeploymentConfig.model_validate(configuration(bound=False))
    with pytest.raises(ValueError, match="actual S3 VersionId"):
        config.require_bound_artifact()
    app = App(outdir=str(tmp_path / "preview"), analytics_reporting=False)
    env = Environment(account=ACCOUNT, region=REGION)
    with pytest.raises(ValueError, match="actual S3 VersionId"):
        StreamingRuntimeStack(app, "Rejected", config=config, model=config.models[0], env=env)
    stack = StreamingRuntimeStack(
        app,
        "ReviewedPreview",
        config=config,
        model=config.models[0],
        env=env,
        allow_unbound_artifact=True,
    )
    template = Template.from_stack(stack).to_json()
    parameter = template["Parameters"]["ArtifactVersionId"]
    assert parameter["MinLength"] == 1 and "Default" not in parameter
    runtime = next(
        r for r in template["Resources"].values() if r["Type"] == "AWS::BedrockAgentCore::Runtime"
    )
    assert runtime["Properties"]["AgentRuntimeArtifact"]["CodeConfiguration"]["Code"]["S3"][
        "VersionId"
    ] == {"Ref": "ArtifactVersionId"}


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "default"},
        {"account": "111122223333"},
        {"region": "us-east-1"},
        {"code_bucket": "unreviewed-bucket"},
        {"artifact_key": "releases/" + "b" * 64 + "/agent.zip"},
        {"artifact_version_id": "UNBOUND"},
        {"approved_caller_arns": ["*"]},
    ],
)
def test_configuration_rejects_scope_and_artifact_drift(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        StreamingDeploymentConfig.model_validate(configuration() | change)


@pytest.mark.parametrize(
    "change", ["tenant", "runtime", "resources", "other-model", "duplicate", "data"]
)
def test_models_cannot_expand_scope_or_inference_permissions(change: str) -> None:
    value = configuration()
    model = value["models"][0]
    if change == "tenant":
        model["settings"]["tenant_id"] = "other_tenant"
    elif change == "runtime":
        model["runtime_name"] = "enterprise_analytics_dev_agent"
    elif change == "resources":
        model["model_resource_arns"] = ["arn:aws:bedrock:*:*:foundation-model/*"]
    elif change == "other-model":
        model["model_resource_arns"].append(
            "arn:aws:bedrock:us-west-2::foundation-model/unreviewed.other"
        )
    elif change == "duplicate":
        value["models"].append(deepcopy(model))
    else:
        value["models"][1]["settings"]["source_bucket"] = "different-retail-source"
    with pytest.raises(ValidationError):
        StreamingDeploymentConfig.model_validate(value)


def test_offline_construction_never_creates_an_aws_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("offline streaming synthesis must not construct an AWS session")

    monkeypatch.setattr(boto3, "Session", forbidden)
    config = StreamingDeploymentConfig.model_validate(configuration())
    app = App(outdir=str(tmp_path / "offline"), analytics_reporting=False)
    StreamingRuntimeStack(
        app,
        "Offline",
        config=config,
        model=config.models[0],
        env=Environment(account=ACCOUNT, region=REGION),
    )
    app.synth()
    assert not json.loads((tmp_path / "offline/manifest.json").read_text()).get("missing")


@pytest.mark.parametrize("custom", [False, True])
def test_packaging_cli_forwards_opt_in_entrypoint_without_changing_legacy_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, custom: bool
) -> None:
    seen: dict[str, Any] = {}

    def build(**kwargs: Any) -> dict[str, object]:
        seen.update(kwargs)
        return {"scope": "offline CLI forwarding fixture"}

    args = [
        "package",
        "--config",
        "fixture-config.json",
        "--project-wheel",
        "fixture.whl",
        "--offline",
    ]
    if custom:
        args.extend(
            (
                "--entrypoint",
                "infrastructure/agentcore/streaming_entry.py",
                "--output",
                str(tmp_path / "new-candidate/agent.zip"),
            )
        )
    monkeypatch.setattr("sys.argv", args)
    monkeypatch.setattr(package, "write_requirements", lambda *args: None)
    monkeypatch.setattr(package, "build_archive", build)
    monkeypatch.setattr(
        package, "download_wheels", lambda *args: pytest.fail("offline CLI downloaded wheels")
    )
    package.main()
    expected = "streaming_entry.py" if custom else "runtime_entry.py"
    assert seen["entrypoint"] == Path("infrastructure/agentcore") / expected


def test_new_entrypoint_cannot_overwrite_a_frozen_zip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frozen = tmp_path / "frozen.zip"
    frozen.write_bytes(b"preserve original artifact")
    args = [
        "package",
        "--config",
        "unused.json",
        "--entrypoint",
        "infrastructure/agentcore/streaming_entry.py",
        "--output",
        str(frozen),
    ]
    monkeypatch.setattr("sys.argv", args)
    monkeypatch.setattr(
        package,
        "write_requirements",
        lambda *args: pytest.fail("Preservation check must run first"),
    )
    with pytest.raises(ValueError, match="non-existing"):
        package.main()
    assert frozen.read_bytes() == b"preserve original artifact"
