"""Security and storage invariants checked against offline CloudFormation synthesis."""

import json
from pathlib import Path
from typing import Any

import pytest
from aws_cdk import App, Environment
from aws_cdk.assertions import Match, Template
from pydantic import ValidationError

from infrastructure.cdk.config import DeploymentConfig
from infrastructure.cdk.stack import AnalyticsDataStack

_EXAMPLE = Path(__file__).parents[1] / "infrastructure/cdk/config.example.json"


@pytest.fixture(scope="module")
def deployment_config() -> DeploymentConfig:
    return DeploymentConfig.model_validate_json(_EXAMPLE.read_text())


@pytest.fixture(scope="module")
def cdk_template(
    tmp_path_factory: pytest.TempPathFactory, deployment_config: DeploymentConfig
) -> Template:
    outdir = tmp_path_factory.mktemp("cdk")
    app = App(outdir=str(outdir), analytics_reporting=False)
    stack = AnalyticsDataStack(
        app,
        "OfflineTestDataLayer",
        config=deployment_config,
        env=Environment(account=deployment_config.account, region=deployment_config.region),
    )
    app.synth()
    assert not json.loads((outdir / "manifest.json").read_text()).get("missing")
    return Template.from_stack(stack)


def _policy_for_role(template: Template, role_name: str) -> list[dict[str, Any]]:
    roles = template.find_resources("AWS::IAM::Role", {"Properties": {"RoleName": role_name}})
    assert len(roles) == 1
    role_ref = {"Ref": next(iter(roles))}
    policies = dict(template.find_resources("AWS::IAM::Policy")) | dict(
        template.find_resources("AWS::IAM::ManagedPolicy")
    )
    matches = [
        policy["Properties"]["PolicyDocument"]["Statement"]
        for policy in policies.values()
        if role_ref in policy["Properties"]["Roles"]
    ]
    assert matches
    statements: list[dict[str, Any]] = [statement for match in matches for statement in match]
    return statements


def _actions(statement: dict[str, Any]) -> list[str]:
    value = statement["Action"]
    return [value] if isinstance(value, str) else list(value)


def test_storage_is_private_encrypted_versioned_and_retained(cdk_template: Template) -> None:
    cdk_template.resource_count_is("AWS::S3::Bucket", 2)
    for bucket in cdk_template.find_resources("AWS::S3::Bucket").values():
        assert bucket["DeletionPolicy"] == "Retain"
        assert bucket["UpdateReplacePolicy"] == "Retain"
        props = bucket["Properties"]
        assert props["VersioningConfiguration"] == {"Status": "Enabled"}
        assert props["PublicAccessBlockConfiguration"] == {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }
        assert props["BucketEncryption"] == {
            "ServerSideEncryptionConfiguration": [
                {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
            ]
        }
        assert props["OwnershipControls"] == {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
    cdk_template.resource_count_is("Custom::S3AutoDeleteObjects", 0)


def test_both_buckets_deny_plain_http(cdk_template: Template) -> None:
    policies = cdk_template.find_resources("AWS::S3::BucketPolicy")
    assert len(policies) == 2
    for policy in policies.values():
        statements = policy["Properties"]["PolicyDocument"]["Statement"]
        assert any(
            statement["Effect"] == "Deny"
            and statement["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
            for statement in statements
        )


def test_source_writes_require_create_only_condition(cdk_template: Template) -> None:
    statements = [
        statement
        for policy in cdk_template.find_resources("AWS::S3::BucketPolicy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if statement.get("Sid") == "RequireConditionalSnapshotCreation"
    ]
    assert len(statements) == 1
    statement = statements[0]
    assert statement["Effect"] == "Deny"
    assert statement["Action"] == "s3:PutObject"
    assert statement["Condition"] == {
        "Null": {"s3:if-none-match": "true"},
        "Bool": {"s3:ObjectCreationOperation": "true"},
    }
    resources = json.dumps(statement["Resource"])
    assert "/snapshots/*" in resources
    assert "/manifests/*" in resources
    assert "AthenaQueryResults" not in resources


def test_data_is_retained_while_results_have_bounded_retention(cdk_template: Template) -> None:
    buckets = list(cdk_template.find_resources("AWS::S3::Bucket").values())
    source = next(
        bucket for bucket in buckets if bucket["Properties"]["BucketName"].endswith("-data")
    )
    results = next(
        bucket for bucket in buckets if bucket["Properties"]["BucketName"].endswith("-results")
    )
    source_rules = source["Properties"]["LifecycleConfiguration"]["Rules"]
    assert all("ExpirationInDays" not in rule for rule in source_rules)
    assert all("NoncurrentVersionExpiration" not in rule for rule in source_rules)
    assert source_rules[0]["AbortIncompleteMultipartUpload"] == {"DaysAfterInitiation": 1}
    result_rules = results["Properties"]["LifecycleConfiguration"]["Rules"]
    assert result_rules == [
        {
            "Id": "ExpireQueryResults",
            "Status": "Enabled",
            "Prefix": "queries/",
            "ExpirationInDays": 7,
            "NoncurrentVersionExpiration": {"NoncurrentDays": 7},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
        }
    ]


def test_external_tables_have_explicit_types_and_separate_version_locations(
    cdk_template: Template,
) -> None:
    tables = cdk_template.find_resources("AWS::Glue::Table")
    assert len(tables) == 27
    inventory: dict[str, set[str]] = {}
    locations: set[str] = set()
    for table in tables.values():
        props = table["Properties"]
        table_input = props["TableInput"]
        assert table_input["TableType"] == "EXTERNAL_TABLE"
        assert table_input["PartitionKeys"] == []
        version = table_input["Parameters"]["dataset_version"]
        logical_table = table_input["Description"].split(": ", 1)[1]
        inventory.setdefault(version, set()).add(logical_table)
        location = json.dumps(table_input["StorageDescriptor"]["Location"])
        assert f"/snapshots/{version}/{logical_table}/" in location
        assert "/queries/" not in location
        assert "/manifests/" not in location
        assert location not in locations
        locations.add(location)
        columns = {
            column["Name"]: column["Type"] for column in table_input["StorageDescriptor"]["Columns"]
        }
        assert columns["tenant_id"] == "string"
        if logical_table == "order_items":
            assert columns["quantity"] == "int"
            assert columns["unit_price_cents"] == "bigint"
            assert columns["discount_cents"] == "bigint"
        if logical_table == "orders":
            assert columns["ordered_at"] == "date"
            assert columns["tax_cents"] == "bigint"
        assert table["DeletionPolicy"] == "Retain"
    assert "returns" not in inventory["parity-legacy-v1"]
    assert all(
        "returns" in inventory[v] for v in ("retail-v1", "parity-v1", "parity-no-returns-v1")
    )


def test_only_new_database_uses_iam_catalog_authorization(cdk_template: Template) -> None:
    cdk_template.has_resource_properties(
        "AWS::Glue::Database",
        {
            "CatalogId": "111122223333",
            "DatabaseInput": {
                "Name": "enterprise_analytics_dev",
                "Description": Match.any_value(),
                "CreateTableDefaultPermissions": [
                    {
                        "Permissions": ["ALL"],
                        "Principal": {"DataLakePrincipalIdentifier": "IAM_ALLOWED_PRINCIPALS"},
                    }
                ],
            },
        },
    )
    assert not cdk_template.find_resources("AWS::LakeFormation::DataLakeSettings")


def test_workgroup_enforces_engine_results_encryption_and_scan_limit(
    cdk_template: Template,
) -> None:
    cdk_template.has_resource_properties(
        "AWS::Athena::WorkGroup",
        {
            "Name": "enterprise-analytics-dev",
            "State": "ENABLED",
            "RecursiveDeleteOption": False,
            "WorkGroupConfiguration": {
                "EnforceWorkGroupConfiguration": True,
                "BytesScannedCutoffPerQuery": 10_485_760,
                "PublishCloudWatchMetricsEnabled": True,
                "RequesterPaysEnabled": False,
                "EngineVersion": {"SelectedEngineVersion": "Athena engine version 3"},
                "ResultConfiguration": {
                    "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"},
                    "ExpectedBucketOwner": "111122223333",
                    "OutputLocation": Match.any_value(),
                },
            },
        },
    )
    workgroup = next(iter(cdk_template.find_resources("AWS::Athena::WorkGroup").values()))
    output = json.dumps(workgroup["Properties"]["WorkGroupConfiguration"]["ResultConfiguration"])
    assert "/queries/" in output
    assert "AthenaQueryResults" in output
    assert "SyntheticDatasets" not in output
    assert workgroup["DeletionPolicy"] == "Retain"


def test_monitoring_uses_documented_scan_metric_and_all_query_states(
    cdk_template: Template,
) -> None:
    alarms = cdk_template.find_resources("AWS::CloudWatch::Alarm")
    assert len(alarms) == 1
    props = next(iter(alarms.values()))["Properties"]
    assert props["TreatMissingData"] == "notBreaching"
    assert props["Threshold"] == 104_857_600
    metrics = [metric["MetricStat"] for metric in props["Metrics"] if "MetricStat" in metric]
    assert len(metrics) == 3
    states: set[str] = set()
    for metric in metrics:
        assert metric["Metric"]["Namespace"] == "AWS/Athena"
        assert metric["Metric"]["MetricName"] == "ProcessedBytes"
        assert metric["Stat"] == "Sum"
        assert metric["Period"] == 300
        dimensions = {item["Name"]: item["Value"] for item in metric["Metric"]["Dimensions"]}
        assert dimensions["WorkGroup"] == "enterprise-analytics-dev"
        assert dimensions["QueryType"] == "DML"
        states.add(dimensions["QueryState"])
    assert states == {"SUCCEEDED", "FAILED", "CANCELED"}
    assert not props.get("AlarmActions")


def test_roles_trust_only_explicit_stable_principals(cdk_template: Template) -> None:
    roles = cdk_template.find_resources("AWS::IAM::Role")
    assert len(roles) == 2
    for role in roles.values():
        assert role["Properties"]["AssumeRolePolicyDocument"]["Statement"] == [
            {
                "Action": "sts:AssumeRole",
                "Effect": "Allow",
                "Principal": {"AWS": "arn:aws:iam::111122223333:role/EnterpriseAnalyticsDeveloper"},
            }
        ]


def test_loader_has_no_query_or_catalog_mutation_permissions(cdk_template: Template) -> None:
    statements = _policy_for_role(cdk_template, "enterprise-analytics-dev-dataset-loader")
    actions = {action for statement in statements for action in _actions(statement)}
    assert "s3:PutObject" in actions
    assert "glue:GetTable" in actions
    assert "glue:GetDatabase" in actions
    assert not any(action.startswith("athena:") for action in actions)
    assert not any(
        action.startswith(("glue:Create", "glue:Update", "glue:Delete")) for action in actions
    )
    assert "s3:DeleteObject" not in actions
    for statement in statements:
        if "s3:PutObject" in _actions(statement):
            resources = json.dumps(statement["Resource"])
            assert "SyntheticDatasets" in resources
            assert "AthenaQueryResults" not in resources
            for version in ("retail-v1", "parity-v1", "parity-legacy-v1", "parity-no-returns-v1"):
                assert f"/snapshots/{version}/" in resources
                assert f"/manifests/{version}.json" in resources


def test_query_role_cannot_write_source_or_change_workgroup(cdk_template: Template) -> None:
    statements = _policy_for_role(cdk_template, "enterprise-analytics-dev-query-executor")
    actions = {action for statement in statements for action in _actions(statement)}
    assert {
        "athena:StartQueryExecution",
        "athena:StopQueryExecution",
        "athena:GetQueryResults",
    } <= actions
    assert "s3:DeleteObject" not in actions
    assert "athena:UpdateWorkGroup" not in actions
    assert "glue:CreateTable" not in actions
    assert "s3:ListBucketMultipartUploads" in actions
    assert "athena:GetDataCatalog" in actions
    for statement in statements:
        statement_actions = _actions(statement)
        if "s3:PutObject" in statement_actions:
            resources = json.dumps(statement["Resource"])
            assert "AthenaQueryResults" in resources
            assert "SyntheticDatasets" not in resources
            assert "/queries/*" in resources
        if "athena:StartQueryExecution" in statement_actions:
            resources = json.dumps(statement["Resource"])
            assert "workgroup/enterprise-analytics-dev" in resources
            assert "workgroup/*" not in resources
        if "s3:ListBucketMultipartUploads" in statement_actions:
            assert "AthenaQueryResults" in json.dumps(statement["Resource"])
            assert "SyntheticDatasets" not in json.dumps(statement["Resource"])
        if "athena:GetDataCatalog" in statement_actions:
            resources = json.dumps(statement["Resource"])
            assert "datacatalog/AwsDataCatalog" in resources
            assert "datacatalog/*" not in resources
        assert statement["Resource"] != "*"


def test_source_object_permissions_cannot_append_files_after_readiness(
    cdk_template: Template,
) -> None:
    for role in ("dataset-loader", "query-executor"):
        statements = _policy_for_role(cdk_template, f"enterprise-analytics-dev-{role}")
        object_scopes = [
            resource
            for statement in statements
            if "s3:GetObject" in _actions(statement)
            for resource in statement["Resource"]
            if "SyntheticDatasets" in json.dumps(resource)
        ]
        assert len(object_scopes) == 31  # 27 exact Parquet objects and four ready manifests.
        for resource in object_scopes:
            encoded = json.dumps(resource)
            assert "*" not in encoded
            assert "part-00000.parquet" in encoded or "/manifests/" in encoded
        encoded_scopes = json.dumps(object_scopes)
        assert "/snapshots/parity-v1/returns/part-00000.parquet" in encoded_scopes
        assert "/snapshots/parity-legacy-v1/returns/" not in encoded_scopes
        if role == "dataset-loader":
            for statement in statements:
                if "s3:PutObject" in _actions(statement):
                    assert "*" not in json.dumps(statement["Resource"])


def test_bucket_listing_is_prefix_scoped(cdk_template: Template) -> None:
    for role in ("dataset-loader", "query-executor"):
        for statement in _policy_for_role(cdk_template, f"enterprise-analytics-dev-{role}"):
            if "s3:ListBucket" in _actions(statement):
                prefixes = statement["Condition"]["StringLike"]["s3:prefix"]
                assert prefixes
                assert "*" not in prefixes
                assert all(
                    prefix.startswith(("snapshots/", "manifests/", "queries/"))
                    for prefix in prefixes
                )
                if any(prefix.startswith("snapshots/") for prefix in prefixes):
                    assert "snapshots/parity-v1/" in prefixes
                    assert "snapshots/parity-v1/*" in prefixes
                    assert "manifests/parity-v1.json" in prefixes


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("account", "not-an-account", "String should match pattern"),
        ("region", "", "String should match pattern"),
        ("resource_prefix", "UNSAFE PREFIX", "String should match pattern"),
        ("database_name", "database;drop", "String should match pattern"),
        ("trusted_query_principal_arn", "arn:aws:iam::111122223333:root", "stable IAM"),
        ("trusted_loader_principal_arn", "*", "stable IAM"),
        (
            "trusted_query_principal_arn",
            "arn:aws:sts::111122223333:assumed-role/Developer/session",
            "stable IAM",
        ),
        ("bytes_scanned_cutoff_per_query", 10_000, "greater than or equal"),
        ("results_retention_days", 0, "greater than or equal"),
        ("data_bucket_name", "public.unsafe.bucket", "bucket names"),
    ],
)
def test_reject_invalid_deployment_inputs(
    deployment_config: DeploymentConfig, field: str, value: object, message: str
) -> None:
    inputs = deployment_config.model_dump() | {field: value}
    with pytest.raises(ValidationError, match=message):
        DeploymentConfig.model_validate(inputs)


def test_reject_duplicate_snapshot_versions(deployment_config: DeploymentConfig) -> None:
    inputs = deployment_config.model_dump()
    inputs["snapshots"] = [inputs["snapshots"][0], inputs["snapshots"][0]]
    with pytest.raises(ValidationError, match="versions must be unique"):
        DeploymentConfig.model_validate(inputs)


def test_reject_shared_source_result_bucket(deployment_config: DeploymentConfig) -> None:
    inputs = deployment_config.model_dump() | {
        "data_bucket_name": "shared-development-bucket",
        "results_bucket_name": "shared-development-bucket",
    }
    with pytest.raises(ValidationError, match="must be separate"):
        DeploymentConfig.model_validate(inputs)
