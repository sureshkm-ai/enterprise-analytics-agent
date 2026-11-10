"""Review configuration changes without AWS, CDK lookups, or local artifact dependencies."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from enterprise_analytics_agent.adapters.retail_checkpoint import (
    RUNTIME_ARN,
    _normalize,
    _resolve,
    _verify_runtime,
)
from enterprise_analytics_agent.retail_evaluation.campaign import CODE_SHA256, CODE_VERSION
from enterprise_analytics_agent.retail_evaluation.deployment import CHANGES, review_templates


def templates() -> tuple[dict[str, Any], dict[str, Any]]:
    settings: dict[str, Any] = {key: old for key, (old, _) in CHANGES.items()}
    settings.update(model_id="reviewed-model", allowed_regions=["North", "South"])
    base: dict[str, Any] = {
        "Resources": {
            "AnalyticsRuntime": {
                "Properties": {
                    "EnvironmentVariables": {"ANALYTICS_RUNTIME_CONFIG": json.dumps(settings)},
                    "RoleArn": "reviewed-role",
                }
            },
            "InboundPolicy": {"reviewed": True},
        }
    }
    retail = deepcopy(base)
    settings.update({key: new for key, (_, new) in CHANGES.items()})
    retail["Resources"]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"][
        "ANALYTICS_RUNTIME_CONFIG"
    ] = json.dumps(settings)
    return base, retail


def test_only_three_trusted_settings_may_change() -> None:
    base, retail = templates()
    assert set(review_templates(base, retail)) == {"dataset_version", "tenant_id", "reference_date"}


@pytest.mark.parametrize("change", ["scope", "role", "policy", "override", "resource"])
def test_deployment_review_rejects_scope_or_infrastructure_expansion(change: str) -> None:
    base, retail = templates()
    properties = retail["Resources"]["AnalyticsRuntime"]["Properties"]
    if change == "scope":
        settings = json.loads(properties["EnvironmentVariables"]["ANALYTICS_RUNTIME_CONFIG"])
        settings["allowed_regions"].append("East")
        properties["EnvironmentVariables"]["ANALYTICS_RUNTIME_CONFIG"] = json.dumps(settings)
    elif change == "role":
        properties["RoleArn"] = "broader-role"
    elif change == "policy":
        retail["Resources"]["InboundPolicy"]["reviewed"] = False
    elif change == "override":
        properties["EnvironmentVariables"]["ANALYTICS_DATASET_VERSION"] = "retail-v1"
    else:
        retail["Resources"]["NewResource"] = {"Type": "AWS::IAM::Role"}
    with pytest.raises(ValueError):
        review_templates(base, retail)


def test_configuration_copies_preserve_all_other_settings() -> None:
    root = Path(__file__).resolve().parents[1]
    before = json.loads((root / "infrastructure/agentcore/runtime.development.json").read_text())
    after = json.loads(
        (root / "infrastructure/agentcore/runtime.retail-evaluation.json").read_text()
    )
    for key, (old, new) in CHANGES.items():
        assert before[key] == old
        assert after.pop(key) == new
        before.pop(key)
    assert after == before
    base_config = json.loads(
        (root / "infrastructure/cdk/agentcore.config.development.json").read_text()
    )
    retail_config = json.loads(
        (root / "infrastructure/cdk/agentcore.config.retail-evaluation.json").read_text()
    )
    assert (
        retail_config.pop("runtime_config_path")
        == "infrastructure/agentcore/runtime.retail-evaluation.json"
    )
    base_config.pop("runtime_config_path")
    assert retail_config == base_config


def test_resource_policy_normalization_does_not_weaken_conditions() -> None:
    policy: dict[str, Any] = {
        "Statement": [
            {
                "Principal": {"AWS": "caller"},
                "Condition": {
                    "ArnNotEquals": {"aws:PrincipalArn": "caller"},
                    "StringEquals": {"scope": "fixed"},
                },
            }
        ]
    }
    normalized = _normalize(policy)
    assert normalized["Statement"][0]["Principal"]["AWS"] == ["caller"]
    assert normalized["Statement"][0]["Condition"]["StringEquals"] == {"scope": "fixed"}
    assert policy["Statement"][0]["Principal"]["AWS"] == "caller"
    assert _resolve(
        {
            "Fn::Join": [
                "",
                [
                    {"Fn::GetAtt": ["AnalyticsRuntime", "AgentRuntimeArn"]},
                    "/runtime-endpoint/DEFAULT",
                ],
            ]
        }
    ).endswith("/runtime-endpoint/DEFAULT")
    with pytest.raises(ValueError):
        _resolve({"Ref": "UnreviewedResource"})


def checkpoint_values() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    properties = {
        "EnvironmentVariables": {"ANALYTICS_RUNTIME_CONFIG": "reviewed"},
        "RoleArn": "reviewed-role",
        "PlatformVersion": "V1",
        "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
        "LifecycleConfiguration": {"IdleRuntimeSessionTimeout": 300, "MaxLifetime": 900},
        "ProtocolConfiguration": "HTTP",
        "AgentRuntimeArtifact": {"CodeConfiguration": {"EntryPoint": ["runtime_entry.py"]}},
    }
    runtime = {
        "status": "READY",
        "agentRuntimeArn": RUNTIME_ARN,
        "agentRuntimeVersion": "7",
        "environmentVariables": properties["EnvironmentVariables"],
        "roleArn": "reviewed-role",
        "platformVersion": "V1",
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 300, "maxLifetime": 900},
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        "agentRuntimeArtifact": {
            "codeConfiguration": {
                "runtime": "PYTHON_3_12",
                "entryPoint": ["runtime_entry.py"],
                "code": {
                    "s3": {
                        "versionId": CODE_VERSION,
                        "prefix": f"releases/{CODE_SHA256}/agent.zip",
                        "bucket": "enterprise-analytics-dev-453711491609-us-west-2-agent-code",
                    }
                },
            }
        },
    }
    endpoint = {
        "status": "READY",
        "liveVersion": "7",
        "agentRuntimeEndpointArn": RUNTIME_ARN + "/runtime-endpoint/DEFAULT",
    }
    return runtime, endpoint, {"Resources": {"AnalyticsRuntime": {"Properties": properties}}}


def test_restoration_accepts_later_matching_version_without_optional_target_version() -> None:
    runtime, endpoint, template = checkpoint_values()
    assert _verify_runtime(runtime, endpoint, template)["versionId"] == CODE_VERSION


@pytest.mark.parametrize(
    "change",
    ["not_ready", "version", "pending", "scope", "entrypoint", "artifact", "lifecycle", "protocol"],
)
def test_restoration_rejects_drift_before_a_smoke_call_can_be_reserved(change: str) -> None:
    runtime, endpoint, template = checkpoint_values()
    if change == "not_ready":
        runtime["status"] = "UPDATING"
    elif change == "version":
        endpoint["liveVersion"] = "4"
    elif change == "pending":
        endpoint["targetVersion"] = "8"
    elif change == "scope":
        runtime["environmentVariables"] = {"ANALYTICS_RUNTIME_CONFIG": "other-tenant"}
    elif change == "entrypoint":
        runtime["agentRuntimeArtifact"]["codeConfiguration"]["entryPoint"] = ["other.py"]
    elif change == "artifact":
        runtime["agentRuntimeArtifact"]["codeConfiguration"]["code"]["s3"]["versionId"] = "new"
    elif change == "lifecycle":
        runtime["lifecycleConfiguration"]["maxLifetime"] = 10000
    else:
        runtime["protocolConfiguration"] = {"serverProtocol": "MCP"}
    with pytest.raises(ValueError):
        _verify_runtime(runtime, endpoint, template)
