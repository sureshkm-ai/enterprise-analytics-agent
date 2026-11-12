"""Offline preservation checks for the reviewed streaming IAM document split."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from aws_cdk import App, Environment
from aws_cdk.assertions import Template

from infrastructure.cdk.streaming_app import (
    ACCOUNT,
    PREFIX,
    StreamingDeploymentConfig,
    StreamingRuntimeStack,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_ROOT = ROOT / "infrastructure" / "cdk"
AGGREGATE = POLICY_ROOT / "streaming-deployment-policy.proposed.json"
PARTS = (
    POLICY_ROOT / "streaming-deployment-policy.roles.proposed.json",
    POLICY_ROOT / "streaming-deployment-policy.agentcore.proposed.json",
)
TRUST = POLICY_ROOT / "streaming-query-trust-additions.proposed.json"
AGGREGATE_SHA256 = "9be307f2bf73232c6146a7cfda8eb90e31d4952af2eb0de5ce8eb79e51a8723f"
MANAGED_POLICY_CHARACTER_LIMIT = 6_144


def document(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@pytest.fixture(scope="module")
def reviewed_config() -> StreamingDeploymentConfig:
    return StreamingDeploymentConfig.model_validate_json(
        (POLICY_ROOT / "streaming.proposed.json").read_bytes()
    )


def test_split_preserves_every_reviewed_statement_exactly_once() -> None:
    assert hashlib.sha256(AGGREGATE.read_bytes()).hexdigest() == AGGREGATE_SHA256
    aggregate = document(AGGREGATE)
    expected = Counter(canonical(statement) for statement in aggregate["Statement"])
    actual: Counter[str] = Counter()
    for path in PARTS:
        part = document(path)
        assert set(part) == set(aggregate) == {"Version", "Statement"}
        assert part["Version"] == aggregate["Version"] == "2012-10-17"
        actual.update(canonical(statement) for statement in part["Statement"])
    # Comparing whole statements includes every action, resource, condition and Sid.
    assert actual == expected
    assert len(expected) == 8
    assert set(expected.values()) == set(actual.values()) == {1}


@pytest.mark.parametrize("path", PARTS, ids=("roles", "agentcore"))
def test_each_attachment_document_fits_managed_policy_limit(path: Path) -> None:
    compact = canonical(document(path))
    assert compact.isascii()
    assert len(compact) <= MANAGED_POLICY_CHARACTER_LIMIT


def test_packaging_manifest_binds_actual_files_names_and_execution_role() -> None:
    manifest = document(ROOT / "evaluations" / "bedrock-streaming" / "policy-packaging.json")
    assert manifest["schema_version"] == "bedrock-streaming-policy-packaging-v1"
    assert manifest["approved_aggregate_path"] == str(AGGREGATE.relative_to(ROOT))
    assert (
        manifest["approved_aggregate_sha256"] == hashlib.sha256(AGGREGATE.read_bytes()).hexdigest()
    )
    assert manifest["aggregate_iam_characters"] == len(canonical(document(AGGREGATE)))
    assert manifest["managed_policy_character_limit"] == MANAGED_POLICY_CHARACTER_LIMIT
    assert manifest["target_execution_role_arn"] == (
        f"arn:aws:iam::{ACCOUNT}:role/cdk-hnb659fds-cfn-exec-role-{ACCOUNT}-us-west-2"
    )
    assert manifest["same_permissions"] is True
    assert manifest["aws_policy_changes_applied"] is False
    expected_names = {
        str(PARTS[0].relative_to(ROOT)): "enterprise-analytics-stream-cdk-roles",
        str(PARTS[1].relative_to(ROOT)): "enterprise-analytics-stream-cdk-agentcore",
    }
    assert len(manifest["parts"]) == len(expected_names)
    assert {part["path"] for part in manifest["parts"]} == set(expected_names)
    for part in manifest["parts"]:
        path = ROOT / part["path"]
        actual = document(path)
        name = expected_names[part["path"]]
        assert part["policy_name"] == name
        assert part["policy_arn"] == f"arn:aws:iam::{ACCOUNT}:policy/{name}"
        assert part["file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert part["iam_characters"] == len(canonical(actual))
        assert part["statement_ids"] == [statement["Sid"] for statement in actual["Statement"]]
    assert set(manifest["preserve_attached_policies"]) == {
        "enterprise-analytics-dev-cdk-execution",
        "enterprise-analytics-dev-agentcore-cdk-execution",
    }


def test_both_role_grants_cover_only_the_ten_reviewed_runtime_roles(
    reviewed_config: StreamingDeploymentConfig,
) -> None:
    review = document(ROOT / "evaluations" / "bedrock-streaming" / "review.proposed.json")
    assert {model.key for model in reviewed_config.models} == {
        target["model_key"] for target in review["targets"]
    }
    expected = {
        f"arn:aws:iam::{ACCOUNT}:role/{PREFIX}-{model.key}" for model in reviewed_config.models
    }
    assert len(expected) == 10
    statements = {statement["Sid"]: statement for statement in document(PARTS[0])["Statement"]}
    for sid in ("TenStreamingRuntimeRoles", "PassOnlyTenStreamingRuntimeRoles"):
        resources = statements[sid]["Resource"]
        assert len(resources) == len(set(resources)) == 10
        assert set(resources) == expected
        assert not any("*" in resource or "?" in resource for resource in resources)
    assert statements["PassOnlyTenStreamingRuntimeRoles"]["Condition"] == {
        "StringEquals": {"iam:PassedToService": "bedrock-agentcore.amazonaws.com"}
    }


def test_consolidated_trust_matches_all_reviewed_template_outputs(
    reviewed_config: StreamingDeploymentConfig,
    tmp_path: Path,
) -> None:
    trust = document(TRUST)
    assert set(trust) == {"Version", "Statement"}
    assert trust["Version"] == "2012-10-17"
    assert len(trust["Statement"]) == 1
    consolidated = trust["Statement"][0]
    assert set(consolidated) == {"Sid", "Effect", "Principal", "Action"}
    assert consolidated["Effect"] == "Allow"
    assert consolidated["Action"] == "sts:AssumeRole"
    assert set(consolidated["Principal"]) == {"AWS"}
    principals = consolidated["Principal"]["AWS"]
    assert isinstance(principals, list)
    assert len(principals) == len(set(principals)) == 10
    assert not any("*" in principal or "?" in principal for principal in principals)

    app = App(outdir=str(tmp_path / "synth"), analytics_reporting=False)
    stacks = [
        StreamingRuntimeStack(
            app,
            f"{PREFIX}-{model.key}",
            config=reviewed_config,
            model=model,
            env=Environment(account=reviewed_config.account, region=reviewed_config.region),
            allow_unbound_artifact=True,
        )
        for model in reviewed_config.models
    ]
    app.synth()
    expected: Counter[str] = Counter()
    for stack in stacks:
        template = Template.from_stack(stack).to_json()
        output = json.loads(template["Outputs"]["QueryRoleTrustAdditionProposalOnly"]["Value"])
        assert set(output) == {"Sid", "Effect", "Principal", "Action"}
        assert output["Effect"] == consolidated["Effect"]
        assert output["Action"] == consolidated["Action"]
        assert set(output["Principal"]) == {"AWS"}
        expected[output["Principal"]["AWS"]] += 1
    assert Counter(principals) == expected
    assert set(expected) == {
        f"arn:aws:iam::{ACCOUNT}:role/{PREFIX}-{model.key}" for model in reviewed_config.models
    }
