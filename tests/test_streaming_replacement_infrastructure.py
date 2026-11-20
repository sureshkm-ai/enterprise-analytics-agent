"""Authored offline proofs for narrowly scoped replacement-code rollback access."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

import boto3
import pytest
from aws_cdk import App, Environment
from aws_cdk.assertions import Template
from pydantic import ValidationError

from infrastructure.cdk.streaming_app import (
    ACCOUNT,
    CODE_BUCKET,
    REGION,
    StreamingDeploymentConfig,
    StreamingRuntimeStack,
)

CURRENT_KEY = "releases/" + "a" * 64 + "/agent.zip"
RETAINED_KEY = "releases/" + "b" * 64 + "/agent.zip"
CURRENT_ARN = f"arn:aws:s3:::{CODE_BUCKET}/{CURRENT_KEY}"
RETAINED_ARN = f"arn:aws:s3:::{CODE_BUCKET}/{RETAINED_KEY}"


@pytest.fixture(autouse=True)
def no_aws_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("Replacement infrastructure verification must remain offline")

    monkeypatch.setattr(boto3, "Session", forbidden)
    monkeypatch.setattr(boto3, "client", forbidden)


def authored_config(*, mantle: bool = False) -> dict[str, Any]:
    key = "gemma-4-31b" if mantle else "nova-lite"
    settings = {
        "account": ACCOUNT,
        "region": REGION,
        "model_id": "google.gemma-4-31b" if mantle else "us.amazon.nova-lite-v1:0",
        "query_role_arn": f"arn:aws:iam::{ACCOUNT}:role/enterprise-analytics-dev-query-executor",
        "database": "enterprise_analytics_dev",
        "workgroup": "enterprise-analytics-dev",
        "source_bucket": "enterprise-analytics-dev-453711491609-us-west-2-data",
        "results_bucket": "enterprise-analytics-dev-453711491609-us-west-2-results",
        "dataset_version": "retail-v1",
        "reference_date": "2025-04-01",
        "principal_id": "offline-streaming-fixture",
        "tenant_id": "retail_demo",
        "allowed_regions": ["North", "South"],
        "max_iterations": 5,
        "max_total_tokens": 12000,
    }
    model: dict[str, Any] = {
        "key": key,
        "runtime_name": "enterprise_analytics_stream_" + key.replace("-", "_"),
        "settings": settings,
        "transport": "mantle_chat" if mantle else "converse",
    }
    if not mantle:
        model["model_resource_arns"] = [
            f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/us.amazon.nova-lite-v1:0",
            f"arn:aws:bedrock:{REGION}::foundation-model/amazon.nova-lite-v1:0",
            "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
            "arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-lite-v1:0",
        ]
    return {
        "artifact_sha256": "a" * 64,
        "artifact_key": CURRENT_KEY,
        "artifact_version_id": "AUTHORED-EXACT-NEW-VERSION",
        "approved_caller_arns": [f"arn:aws:iam::{ACCOUNT}:role/ApprovedDeveloper"],
        "models": [model],
    }


def synthesize(raw: dict[str, Any], outdir: Path) -> dict[str, Any]:
    config = StreamingDeploymentConfig.model_validate(raw)
    app = App(outdir=str(outdir), analytics_reporting=False)
    stack = StreamingRuntimeStack(
        app,
        "AuthoredStreamingReplacement",
        config=config,
        model=config.models[0],
        env=Environment(account=ACCOUNT, region=REGION),
    )
    app.synth()
    return dict(Template.from_stack(stack).to_json())


def code_read_statement(template: dict[str, Any]) -> dict[str, Any]:
    matches = [
        statement
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::IAM::Policy"
        for statement in resource["Properties"]["PolicyDocument"]["Statement"]
        if statement["Action"] == ["s3:GetObject", "s3:GetObjectVersion"]
    ]
    assert len(matches) == 1
    statement: dict[str, Any] = matches[0]
    return statement


@pytest.mark.parametrize("mantle", [False, True], ids=("native", "mantle"))
def test_omitted_retained_keys_preserve_original_single_key_template(
    tmp_path: Path, mantle: bool
) -> None:
    original = authored_config(mantle=mantle)
    config = StreamingDeploymentConfig.model_validate(original)
    assert config.retained_artifact_keys == ()
    baseline = synthesize(original, tmp_path / "omitted")
    explicit_empty = synthesize(
        {**original, "retained_artifact_keys": []}, tmp_path / "explicit-empty"
    )
    assert json.dumps(baseline, sort_keys=True) == json.dumps(explicit_empty, sort_keys=True)
    assert code_read_statement(baseline) == {
        "Action": ["s3:GetObject", "s3:GetObjectVersion"],
        "Effect": "Allow",
        "Resource": CURRENT_ARN,
    }


@pytest.mark.parametrize("mantle", [False, True], ids=("native", "mantle"))
def test_replacement_retains_only_exact_previous_key_without_other_template_changes(
    tmp_path: Path, mantle: bool
) -> None:
    raw = authored_config(mantle=mantle)
    baseline = synthesize(raw, tmp_path / "current-only")
    replacement = synthesize(
        {**raw, "retained_artifact_keys": [RETAINED_KEY]}, tmp_path / "current-and-rollback"
    )
    expected = deepcopy(baseline)
    code_read_statement(expected)["Resource"] = [CURRENT_ARN, RETAINED_ARN]
    assert replacement == expected
    assert code_read_statement(replacement) == {
        "Action": ["s3:GetObject", "s3:GetObjectVersion"],
        "Effect": "Allow",
        "Resource": [CURRENT_ARN, RETAINED_ARN],
    }


@pytest.mark.parametrize(
    "retained",
    [
        [CURRENT_KEY],
        [RETAINED_KEY, "releases/" + "c" * 64 + "/agent.zip"],
        [RETAINED_KEY, RETAINED_KEY],
        ["releases/*/agent.zip"],
        ["releases/" + "B" * 64 + "/agent.zip"],
        ["releases/" + "b" * 63 + "/agent.zip"],
        ["s3://foreign-bucket/" + RETAINED_KEY],
        ["arn:aws:s3:::foreign-bucket/" + RETAINED_KEY],
        ["/" + RETAINED_KEY],
        ["releases/../" + "b" * 64 + "/agent.zip"],
        [RETAINED_KEY + "?versionId=unreviewed"],
        None,
    ],
    ids=(
        "duplicates-current",
        "more-than-one-rollback",
        "duplicate-rollback",
        "wildcard",
        "uppercase-hash",
        "short-hash",
        "foreign-bucket-url",
        "foreign-bucket-arn",
        "absolute-path",
        "traversal",
        "unreviewed-query",
        "null",
    ),
)
def test_retained_artifact_keys_reject_unreviewed_scope(retained: object) -> None:
    with pytest.raises(ValidationError):
        StreamingDeploymentConfig.model_validate(
            {**authored_config(), "retained_artifact_keys": retained}
        )
