"""Development data layer, with distinct loading and query capabilities."""

from aws_cdk import CfnOutput, Duration, Environment, RemovalPolicy, Stack
from aws_cdk import aws_athena as athena
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct

from enterprise_analytics_agent.adapters.aws_schema import glue_table_name
from enterprise_analytics_agent.data import OPTIONAL_TABLE_SCHEMAS, TABLE_SCHEMAS
from enterprise_analytics_agent.snapshots import table_key as snapshot_object_key

from .config import DeploymentConfig

_GLUE_TYPES = {"VARCHAR": "string", "BIGINT": "bigint", "INTEGER": "int", "DATE": "date"}
_RESULT_PREFIX = "queries/"


class AnalyticsDataStack(Stack):
    """No lookups, custom resources, automatic deletion, or runtime AWS calls."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        env: Environment,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.config = config
        self.data_bucket = s3.Bucket(
            self,
            "SyntheticDatasets",
            bucket_name=config.resolved_data_bucket_name,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="AbortIncompleteUploads",
                    abort_incomplete_multipart_upload_after=Duration.days(
                        config.incomplete_upload_cleanup_days
                    ),
                )
            ],
        )
        self.data_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="RequireConditionalSnapshotCreation",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:PutObject"],
                resources=[
                    self.data_bucket.arn_for_objects("snapshots/*"),
                    self.data_bucket.arn_for_objects("manifests/*"),
                ],
                conditions={
                    "Null": {"s3:if-none-match": "true"},
                    "Bool": {"s3:ObjectCreationOperation": "true"},
                },
            )
        )
        self.results_bucket = s3.Bucket(
            self,
            "AthenaQueryResults",
            bucket_name=config.resolved_results_bucket_name,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="ExpireQueryResults",
                    prefix=_RESULT_PREFIX,
                    expiration=Duration.days(config.results_retention_days),
                    noncurrent_version_expiration=Duration.days(config.results_retention_days),
                    abort_incomplete_multipart_upload_after=Duration.days(
                        config.incomplete_upload_cleanup_days
                    ),
                )
            ],
        )
        database = glue.CfnDatabase(
            self,
            "GovernedDatabase",
            catalog_id=config.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=config.database_name,
                description="Versioned retail snapshots; application-scoped authorization",
                create_table_default_permissions=[
                    glue.CfnDatabase.PrincipalPrivilegesProperty(
                        permissions=["ALL"],
                        principal=glue.CfnDatabase.DataLakePrincipalProperty(
                            data_lake_principal_identifier="IAM_ALLOWED_PRINCIPALS"
                        ),
                    )
                ],
            ),
        )
        database.apply_removal_policy(RemovalPolicy.RETAIN)
        self.tables: list[glue.CfnTable] = []
        table_arns: list[str] = []
        source_object_keys: list[str] = []
        source_listing_prefixes: list[str] = []
        for snapshot in config.snapshots:
            schemas = TABLE_SCHEMAS | (OPTIONAL_TABLE_SCHEMAS if snapshot.include_returns else {})
            snapshot_prefix = f"snapshots/{snapshot.dataset_version}/"
            source_listing_prefixes.extend([snapshot_prefix, f"{snapshot_prefix}*"])
            for table_name, schema in schemas.items():
                physical_name = glue_table_name(
                    snapshot.dataset_version, table_name, prefix=config.table_prefix
                )
                table_key = f"snapshots/{snapshot.dataset_version}/{table_name}/"
                table = glue.CfnTable(
                    self,
                    f"Table{physical_name}",
                    catalog_id=config.account,
                    database_name=config.database_name,
                    table_input=glue.CfnTable.TableInputProperty(
                        name=physical_name,
                        description=f"Immutable {snapshot.dataset_version}: {table_name}",
                        table_type="EXTERNAL_TABLE",
                        parameters={
                            "classification": "parquet",
                            "EXTERNAL": "TRUE",
                            "dataset_version": snapshot.dataset_version,
                        },
                        partition_keys=[],
                        storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                            columns=[
                                glue.CfnTable.ColumnProperty(name=name, type=_GLUE_TYPES[sql_type])
                                for name, sql_type in schema
                            ],
                            location=self.data_bucket.s3_url_for_object(table_key),
                            input_format="org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                            output_format="org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                            serde_info=glue.CfnTable.SerdeInfoProperty(
                                serialization_library="org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                                parameters={"serialization.format": "1"},
                            ),
                        ),
                    ),
                )
                table.add_resource_dependency(database)
                table.apply_removal_policy(RemovalPolicy.RETAIN)
                self.tables.append(table)
                table_arns.append(
                    self.format_arn(
                        service="glue",
                        resource="table",
                        resource_name=f"{config.database_name}/{physical_name}",
                    )
                )
                source_object_keys.append(snapshot_object_key(snapshot.dataset_version, table_name))
            manifest_key = f"manifests/{snapshot.dataset_version}.json"
            source_object_keys.append(manifest_key)
            source_listing_prefixes.append(manifest_key)

        self.workgroup = athena.CfnWorkGroup(
            self,
            "SemanticQueries",
            name=config.workgroup_name,
            description="Development SQL; tenant restrictions enforced by the application",
            state="ENABLED",
            recursive_delete_option=False,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                bytes_scanned_cutoff_per_query=config.bytes_scanned_cutoff_per_query,
                publish_cloud_watch_metrics_enabled=True,
                requester_pays_enabled=False,
                engine_version=athena.CfnWorkGroup.EngineVersionProperty(
                    selected_engine_version="Athena engine version 3"
                ),
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=self.results_bucket.s3_url_for_object(_RESULT_PREFIX),
                    expected_bucket_owner=config.account,
                    encryption_configuration=athena.CfnWorkGroup.EncryptionConfigurationProperty(
                        encryption_option="SSE_S3"
                    ),
                ),
            ),
        )
        self.workgroup.apply_removal_policy(RemovalPolicy.RETAIN)
        self.loader_role = iam.Role(
            self,
            "DatasetLoader",
            role_name=f"{config.resource_prefix}-dataset-loader",
            assumed_by=iam.ArnPrincipal(config.trusted_loader_principal_arn),
            description="Publish configured snapshots; no query or Glue metadata mutations",
        )
        self.query_role = iam.Role(
            self,
            "SemanticQueryExecutor",
            role_name=f"{config.resource_prefix}-query-executor",
            assumed_by=iam.ArnPrincipal(config.trusted_query_principal_arn),
            description="Query configured snapshots through the dedicated Athena workgroup",
        )
        source_objects = [self.data_bucket.arn_for_objects(key) for key in source_object_keys]
        self._grant_bucket_listing(self.loader_role, self.data_bucket, source_listing_prefixes)
        self._grant_bucket_listing(self.query_role, self.data_bucket, source_listing_prefixes)
        self.loader_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                ],
                resources=source_objects,
            )
        )
        self.query_role.add_to_policy(
            iam.PolicyStatement(actions=["s3:GetObject"], resources=source_objects)
        )
        self._grant_bucket_listing(
            self.query_role, self.results_bucket, [_RESULT_PREFIX, f"{_RESULT_PREFIX}*"]
        )
        self.query_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucketMultipartUploads"],
                resources=[self.results_bucket.bucket_arn],
            )
        )
        self.query_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                ],
                resources=[self.results_bucket.arn_for_objects(f"{_RESULT_PREFIX}*")],
            )
        )
        catalog_arn = self.format_arn(service="glue", resource="catalog")
        database_arn = self.format_arn(
            service="glue", resource="database", resource_name=config.database_name
        )
        for role in (self.loader_role, self.query_role):
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["glue:GetDatabase"], resources=[catalog_arn, database_arn]
                )
            )
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["glue:GetTable"], resources=[catalog_arn, database_arn, *table_arns]
                )
            )
        self.query_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetPartitions",
                    "glue:GetPartition",
                    "glue:BatchGetPartition",
                ],
                resources=[catalog_arn, database_arn, *table_arns],
            )
        )
        self.query_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "athena:StartQueryExecution",
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:StopQueryExecution",
                    "athena:GetWorkGroup",
                ],
                resources=[
                    self.format_arn(
                        service="athena", resource="workgroup", resource_name=config.workgroup_name
                    )
                ],
            )
        )
        self.query_role.add_to_policy(
            iam.PolicyStatement(
                actions=["athena:GetDataCatalog"],
                resources=[
                    self.format_arn(
                        service="athena", resource="datacatalog", resource_name="AwsDataCatalog"
                    )
                ],
            )
        )
        self._add_scan_monitoring(config)
        for name, value in {
            "DataBucketName": self.data_bucket.bucket_name,
            "ResultsBucketName": self.results_bucket.bucket_name,
            "GlueDatabaseName": config.database_name,
            "AthenaWorkgroupName": config.workgroup_name,
            "DatasetLoaderRoleArn": self.loader_role.role_arn,
            "QueryExecutorRoleArn": self.query_role.role_arn,
        }.items():
            CfnOutput(self, name, value=value)

    @staticmethod
    def _grant_bucket_listing(role: iam.Role, bucket: s3.Bucket, prefixes: list[str]) -> None:
        role.add_to_policy(
            iam.PolicyStatement(actions=["s3:GetBucketLocation"], resources=[bucket.bucket_arn])
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[bucket.bucket_arn],
                conditions={"StringLike": {"s3:prefix": prefixes}},
            )
        )

    def _add_scan_monitoring(self, config: DeploymentConfig) -> None:
        metrics = {
            state.lower(): cloudwatch.Metric(
                namespace="AWS/Athena",
                metric_name="ProcessedBytes",
                dimensions_map={
                    "WorkGroup": config.workgroup_name,
                    "QueryType": "DML",
                    "QueryState": state,
                },
                statistic="Sum",
                unit=cloudwatch.Unit.BYTES,
            )
            for state in ("SUCCEEDED", "FAILED", "CANCELED")
        }
        cloudwatch.Alarm(
            self,
            "ScannedBytesAlarm",
            alarm_name=f"{config.resource_prefix}-scanned-bytes",
            alarm_description="5-minute scan warning; no automated notification actions",
            metric=cloudwatch.MathExpression(
                expression="SUM([succeeded,failed,canceled])",
                using_metrics=metrics,
                period=Duration.minutes(5),
            ),
            threshold=config.scan_alarm_threshold_bytes,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
