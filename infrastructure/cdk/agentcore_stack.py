"""Two-phase AgentCore infrastructure; existing Athena resources are reused."""

from aws_cdk import CfnOutput, CfnParameter, Duration, Environment, RemovalPolicy, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct

from infrastructure.cdk.agentcore_config import AgentCoreDeploymentConfig


class AgentCoreFoundationStack(Stack):
    """Deploy role and upload destination before publishing the approved code archive."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: AgentCoreDeploymentConfig,
        env: Environment,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.code_bucket = s3.Bucket(
            self,
            "RuntimeCode",
            bucket_name=config.resolved_code_bucket_name,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="AbortIncompleteCodeUploads",
                    abort_incomplete_multipart_upload_after=Duration.days(1),
                )
            ],
        )
        self.code_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="RequireImmutableCodeCreation",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:PutObject"],
                resources=[self.code_bucket.arn_for_objects("releases/*")],
                conditions={
                    "Null": {"s3:if-none-match": "true"},
                    "Bool": {"s3:ObjectCreationOperation": "true"},
                },
            )
        )
        runtime_arn_prefix = self.format_arn(
            service="bedrock-agentcore",
            resource="runtime",
            resource_name=f"{config.runtime_name}-*",
        )
        self.runtime_role = iam.Role(
            self,
            "RuntimeExecutionRole",
            role_name=f"{config.resource_prefix}-agent-runtime",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": config.account},
                    "ArnLike": {"aws:SourceArn": runtime_arn_prefix},
                },
            ),
            description="Bedrock analytics runtime; Athena access only by assuming its query role",
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"], resources=list(config.model_resource_arns)
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(actions=["sts:AssumeRole"], resources=[config.query_role_arn])
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:GetObjectVersion"],
                resources=[self.code_bucket.arn_for_objects(config.artifact_key)],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetBucketLocation"], resources=[self.code_bucket.bucket_arn]
            )
        )
        # AgentCore chooses the ID suffix and owns the stdout/stderr log group.
        # The exact group is emitted by the runtime stack; retention is an approved
        # post-deployment command, avoiding an AlreadyExists race during creation.
        log_group_arn = (
            f"arn:aws:logs:{config.region}:{config.account}:log-group:{config.log_group_prefix}*"
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:DescribeLogStreams",
                ],
                resources=[log_group_arn],
            )
        )
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[f"{log_group_arn}:log-stream:*"],
            )
        )
        # DescribeLogGroups does not support resource-level IAM restrictions.
        self.runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:DescribeLogGroups"],
                resources=["*"],
                conditions={"StringEquals": {"aws:RequestedRegion": config.region}},
            )
        )
        CfnOutput(self, "CodeBucketName", value=self.code_bucket.bucket_name)
        CfnOutput(self, "CodeObjectKey", value=config.artifact_key)
        CfnOutput(self, "CodeSHA256", value=config.artifact_sha256)
        CfnOutput(self, "RuntimeRoleArn", value=self.runtime_role.role_arn)


class AnalyticsAgentRuntimeStack(Stack):
    """IAM-authenticated runtime with explicit deny for nonapproved callers."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: AgentCoreDeploymentConfig,
        env: Environment,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        environment = {"ANALYTICS_RUNTIME_CONFIG": config.runtime_settings_json()}
        if config.dataset_version_override is not None:
            environment["ANALYTICS_DATASET_VERSION"] = config.dataset_version_override
        version_id = (
            config.artifact_s3_version_id
            or CfnParameter(
                self,
                "ArtifactVersionId",
                type="String",
                min_length=1,
                allowed_pattern=r"[^\s]+",
                description="S3 VersionId returned by the approved immutable code upload",
            ).value_as_string
        )
        self.runtime = agentcore.CfnRuntime(
            self,
            "AnalyticsRuntime",
            agent_runtime_name=config.runtime_name,
            description="Development analytics; fixed trusted tenant/region scope; no agent memory",
            role_arn=config.runtime_role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                code_configuration=agentcore.CfnRuntime.CodeConfigurationProperty(
                    code=agentcore.CfnRuntime.CodeProperty(
                        s3=agentcore.CfnRuntime.S3LocationProperty(
                            bucket=config.resolved_code_bucket_name,
                            prefix=config.artifact_key,
                            version_id=version_id,
                        )
                    ),
                    runtime="PYTHON_3_12",
                    entry_point=["runtime_entry.py"],
                )
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            protocol_configuration="HTTP",
            platform_version="V1",
            environment_variables=environment,
            tags={"Project": config.resource_prefix, "Milestone": "4"},
            lifecycle_configuration=agentcore.CfnRuntime.LifecycleConfigurationProperty(
                idle_runtime_session_timeout=config.idle_session_timeout_seconds,
                max_lifetime=config.max_lifetime_seconds,
            ),
            # No custom/JWT authorizer: AWS defaults inbound authorization to SigV4.
        )
        runtime_arn = self.runtime.attr_agent_runtime_arn
        endpoint_arn = f"{runtime_arn}/runtime-endpoint/DEFAULT"
        self.resource_policies: list[agentcore.CfnResourcePolicy] = []
        for resource_id, resource_arn in (
            ("RuntimeInboundPolicy", runtime_arn),
            ("DefaultEndpointInboundPolicy", endpoint_arn),
        ):
            policy = agentcore.CfnResourcePolicy(
                self,
                resource_id,
                resource_arn=resource_arn,
                policy=self.to_json_string(invocation_policy(config, resource_arn)),
            )
            policy.add_dependency(self.runtime)
            self.resource_policies.append(policy)
        CfnOutput(self, "AgentRuntimeArn", value=runtime_arn)
        CfnOutput(self, "AgentRuntimeId", value=self.runtime.attr_agent_runtime_id)
        CfnOutput(self, "DefaultEndpointArn", value=endpoint_arn)
        CfnOutput(
            self,
            "RuntimeLogGroupName",
            value=f"/aws/bedrock-agentcore/runtimes/{self.runtime.attr_agent_runtime_id}-DEFAULT",
        )
        CfnOutput(self, "LogRetentionDays", value=str(config.log_retention_days))


def invocation_policy(config: AgentCoreDeploymentConfig, resource_arn: str) -> dict[str, object]:
    """Policies apply to each exact runtime/endpoint ARN, never Resource='*'."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowApprovedCallers",
                "Effect": "Allow",
                "Principal": {"AWS": list(config.approved_caller_arns)},
                "Action": "bedrock-agentcore:InvokeAgentRuntime",
                "Resource": resource_arn,
            },
            {
                "Sid": "DenyOtherPrincipals",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "bedrock-agentcore:InvokeAgentRuntime",
                "Resource": resource_arn,
                "Condition": {
                    "ArnNotEquals": {"aws:PrincipalArn": list(config.approved_caller_arns)}
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
                "Resource": resource_arn,
            },
        ],
    }
