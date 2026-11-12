"""Offline-only synthesis for isolated, fixed-model AgentCore streaming runtimes.

Existing data, code storage and query-role trust are never mutated by this app.
Mantle IAM reference:
https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-mantle.html
"""

import argparse
import json
import re
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from aws_cdk import App, CfnOutput, CfnParameter, Environment, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from constructs import Construct
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_analytics_agent.hosting.config import RuntimeSettings

ACCOUNT: Final = "453711491609"
REGION: Final = "us-west-2"
PREFIX: Final = "enterprise-analytics-stream"
CODE_BUCKET: Final = "enterprise-analytics-dev-453711491609-us-west-2-agent-code"
QUERY_ROLE = f"arn:aws:iam::{ACCOUNT}:role/enterprise-analytics-dev-query-executor"
DEFAULT_PROJECT = f"arn:aws:bedrock-mantle:{REGION}:{ACCOUNT}:project/default"


class StreamingModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,19}$")]
    runtime_name: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,47}$")]
    settings: RuntimeSettings
    model_resource_arns: tuple[str, ...] = ()
    transport: Literal["converse", "mantle_chat"] = "converse"
    mantle_project_arn: str = DEFAULT_PROJECT

    @field_validator("model_resource_arns")
    @classmethod
    def exact_model_resources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        pattern = (
            r"arn:aws:bedrock:[a-z0-9-]+:(?:[0-9]{12})?:"
            r"(?:foundation-model|inference-profile|application-inference-profile)/"
            r"[A-Za-z0-9._:-]+"
        )
        if len(values) != len(set(values)) or any(
            re.fullmatch(pattern, value) is None for value in values
        ):
            raise ValueError("Model permissions require unique, exact Bedrock resource ARNs")
        return values

    @field_validator("mantle_project_arn")
    @classmethod
    def exact_project(cls, value: str) -> str:
        if (
            re.fullmatch(
                rf"arn:aws:bedrock-mantle:{REGION}:{ACCOUNT}:project/[A-Za-z0-9_-]+", value
            )
            is None
        ):
            raise ValueError("Mantle permissions require an exact project in the approved target")
        return value

    @model_validator(mode="after")
    def fixed_model_scope(self) -> Self:
        if self.runtime_name != "enterprise_analytics_stream_" + self.key.replace("-", "_"):
            raise ValueError("Streaming runtime names must use the isolated model-key namespace")
        settings = self.settings
        if (
            settings.account != ACCOUNT
            or settings.region != REGION
            or settings.query_role_arn != QUERY_ROLE
            or settings.dataset_version != "retail-v1"
            or settings.tenant_id != "retail_demo"
            or settings.allowed_regions != ("North", "South")
            or settings.reference_date.isoformat() != "2025-04-01"
            or settings.max_iterations != 5
            or settings.max_total_tokens != 12_000
        ):
            raise ValueError(
                "Streaming runtimes must preserve the reviewed retail scope and bounds"
            )
        if self.transport == "converse":
            if not self.model_resource_arns:
                raise ValueError("Native Bedrock models require exact inference resources")
            identity = settings.model_id
            if identity.startswith("arn:"):
                expected = identity
            elif identity.startswith(("us.", "global.")):
                expected = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/{identity}"
            else:
                expected = f"arn:aws:bedrock:{REGION}::foundation-model/{identity}"
            if expected not in self.model_resource_arns:
                raise ValueError(
                    "Native model resources must include the configured inference target"
                )
            base_model = identity.removeprefix("us.").removeprefix("global.")
            if not identity.startswith("arn:") and any(
                arn != expected and not arn.endswith(f"::foundation-model/{base_model}")
                for arn in self.model_resource_arns
            ):
                raise ValueError("Native resources may authorize only this model and its routing")
        return self


class StreamingDeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["analytics-dev"] = "analytics-dev"
    account: Literal["453711491609"] = ACCOUNT
    region: Literal["us-west-2"] = REGION
    resource_prefix: Literal["enterprise-analytics-stream"] = PREFIX
    code_bucket: Literal["enterprise-analytics-dev-453711491609-us-west-2-agent-code"] = CODE_BUCKET
    artifact_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    artifact_key: Annotated[str, Field(pattern=r"^releases/[a-f0-9]{64}/agent\.zip$")]
    retained_artifact_keys: Annotated[tuple[str, ...], Field(max_length=1)] = ()
    artifact_version_id: str | None = None
    approved_caller_arns: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]
    models: Annotated[tuple[StreamingModelConfig, ...], Field(min_length=1, max_length=10)]
    log_retention_days: Literal[7] = 7
    idle_session_timeout_seconds: Annotated[int, Field(ge=60, le=900)] = 300
    max_lifetime_seconds: Annotated[int, Field(ge=60, le=1800)] = 900

    @field_validator("approved_caller_arns")
    @classmethod
    def exact_callers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(
            re.fullmatch(rf"arn:aws:iam::{ACCOUNT}:role/[A-Za-z0-9+=,.@_/-]+", value) is None
            for value in values
        ):
            raise ValueError("Approved callers must be exact IAM roles in the target account")
        return values

    @field_validator("artifact_version_id")
    @classmethod
    def actual_version(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip()
            or any(character.isspace() for character in value)
            or value.lower() in {"null", "unbound", "pending", "unknown"}
        ):
            raise ValueError(
                "Pin the real post-upload S3 VersionId, or use null for offline preview"
            )
        return value

    @field_validator("retained_artifact_keys")
    @classmethod
    def exact_retained_artifacts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            re.fullmatch(r"releases/[a-f0-9]{64}/agent\.zip", value) is None for value in values
        ):
            raise ValueError("Retained code must use an exact content-addressed artifact key")
        return values

    @model_validator(mode="after")
    def coherent_artifact_and_models(self) -> Self:
        if self.artifact_key != f"releases/{self.artifact_sha256}/agent.zip":
            raise ValueError("The candidate S3 key must bind the reviewed archive SHA-256")
        if self.artifact_key in self.retained_artifact_keys:
            raise ValueError("Retained code must differ from the current candidate artifact")
        if len({model.key for model in self.models}) != len(self.models):
            raise ValueError("Streaming model keys must be unique")
        baseline = self.models[0].settings.model_dump(mode="json")
        for model in self.models[1:]:
            candidate = model.settings.model_dump(mode="json")
            for field in ("model_id", "principal_id"):
                candidate.pop(field, None)
            expected = {
                key: value
                for key, value in baseline.items()
                if key not in {"model_id", "principal_id"}
            }
            if candidate != expected:
                raise ValueError("Model choices must share the same data, authorization and limits")
        if self.max_lifetime_seconds < self.idle_session_timeout_seconds:
            raise ValueError("Runtime max lifetime must cover its idle session timeout")
        return self

    def require_bound_artifact(self, *, allow_unbound_artifact: bool = False) -> None:
        if self.artifact_version_id is None and not allow_unbound_artifact:
            raise ValueError(
                "The candidate needs its actual S3 VersionId; use --allow-unbound-artifact "
                "only for an offline approval preview"
            )


def _inbound_policy(callers: tuple[str, ...], resource_arn: str) -> dict[str, object]:
    # AgentCore reads back a single ARN as a scalar. Emit that representation so
    # exact policy verification succeeds without normalizing or weakening it.
    caller_values: str | list[str] = callers[0] if len(callers) == 1 else list(callers)
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowApprovedCallers",
                "Effect": "Allow",
                "Principal": {"AWS": caller_values},
                "Action": "bedrock-agentcore:InvokeAgentRuntime",
                "Resource": resource_arn,
            },
            {
                "Sid": "DenyOtherPrincipals",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "bedrock-agentcore:InvokeAgentRuntime",
                "Resource": resource_arn,
                "Condition": {"ArnNotEquals": {"aws:PrincipalArn": caller_values}},
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


class StreamingRuntimeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: StreamingDeploymentConfig,
        model: StreamingModelConfig,
        env: Environment,
        allow_unbound_artifact: bool = False,
    ) -> None:
        config.require_bound_artifact(allow_unbound_artifact=allow_unbound_artifact)
        if model not in config.models:
            raise ValueError("Only reviewed models from this deployment config may be synthesized")
        super().__init__(scope, construct_id, env=env)
        role_name = f"{config.resource_prefix}-{model.key}"
        runtime_prefix = (
            f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/{model.runtime_name}-*"
        )
        self.role = iam.Role(
            self,
            "RuntimeRole",
            role_name=role_name,
            description="Streaming model; data access only through the retained query role",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": ACCOUNT},
                    "ArnLike": {"aws:SourceArn": runtime_prefix},
                },
            ),
        )
        statements = [
            iam.PolicyStatement(actions=["sts:AssumeRole"], resources=[QUERY_ROLE]),
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:GetObjectVersion"],
                resources=[
                    f"arn:aws:s3:::{config.code_bucket}/{key}"
                    for key in (config.artifact_key, *config.retained_artifact_keys)
                ],
            ),
            iam.PolicyStatement(
                actions=["s3:GetBucketLocation"], resources=[f"arn:aws:s3:::{config.code_bucket}"]
            ),
        ]
        if model.transport == "converse":
            statements.append(
                iam.PolicyStatement(
                    actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                    resources=list(model.model_resource_arns),
                )
            )
        else:
            statements.append(
                iam.PolicyStatement(
                    actions=["bedrock-mantle:CreateInference"],
                    resources=[model.mantle_project_arn],
                    conditions={
                        "StringEquals": {
                            "bedrock-mantle:Model": model.settings.model_id,
                            "aws:RequestedRegion": REGION,
                        }
                    },
                )
            )
        logs = (
            f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:"
            f"/aws/bedrock-agentcore/runtimes/{model.runtime_name}-*"
        )
        statements.extend(
            [
                iam.PolicyStatement(
                    actions=["logs:CreateLogGroup", "logs:DescribeLogStreams"], resources=[logs]
                ),
                iam.PolicyStatement(
                    actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                    resources=[f"{logs}:log-stream:*"],
                ),
                iam.PolicyStatement(
                    actions=["logs:PutResourcePolicy"],
                    resources=[logs],
                    conditions={"StringEquals": {"aws:RequestedRegion": REGION}},
                ),
                iam.PolicyStatement(
                    actions=["logs:DescribeLogGroups"],
                    resources=["*"],
                    conditions={"StringEquals": {"aws:RequestedRegion": REGION}},
                ),
            ]
        )
        permissions = iam.Policy(self, "RuntimePermissions", statements=statements)
        self.role.attach_inline_policy(permissions)
        version = (
            config.artifact_version_id
            or CfnParameter(
                self,
                "ArtifactVersionId",
                type="String",
                min_length=1,
                allowed_pattern=r"(?!null$|UNBOUND$|PENDING$)[^\s]+",
                description="Required real S3 VersionId; unbound templates are offline previews",
            ).value_as_string
        )
        self.runtime = agentcore.CfnRuntime(
            self,
            "StreamingRuntime",
            agent_runtime_name=model.runtime_name,
            description="Development streaming analytics; fixed model and trusted scope",
            role_arn=self.role.role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                code_configuration=agentcore.CfnRuntime.CodeConfigurationProperty(
                    code=agentcore.CfnRuntime.CodeProperty(
                        s3=agentcore.CfnRuntime.S3LocationProperty(
                            bucket=config.code_bucket,
                            prefix=config.artifact_key,
                            version_id=version,
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
            environment_variables={"ANALYTICS_RUNTIME_CONFIG": model.settings.model_dump_json()},
            lifecycle_configuration=agentcore.CfnRuntime.LifecycleConfigurationProperty(
                idle_runtime_session_timeout=config.idle_session_timeout_seconds,
                max_lifetime=config.max_lifetime_seconds,
            ),
            tags={
                "Project": config.resource_prefix,
                "Scope": "BedrockStreaming",
                "Model": model.key,
            },
        )
        # Creation may fetch code immediately; wait for all scoped permissions.
        self.runtime.node.add_dependency(permissions)
        runtime_arn = self.runtime.attr_agent_runtime_arn
        endpoint = f"{runtime_arn}/runtime-endpoint/DEFAULT"
        for name, arn in (
            ("RuntimeInboundPolicy", runtime_arn),
            ("EndpointInboundPolicy", endpoint),
        ):
            policy = agentcore.CfnResourcePolicy(
                self,
                name,
                resource_arn=arn,
                policy=self.to_json_string(_inbound_policy(config.approved_caller_arns, arn)),
            )
            policy.add_resource_dependency(self.runtime)
        role_arn = f"arn:aws:iam::{ACCOUNT}:role/{role_name}"
        trust_addition = {
            "Sid": "AllowStreamingRuntime" + model.key.replace("-", "").title(),
            "Effect": "Allow",
            "Principal": {"AWS": role_arn},
            "Action": "sts:AssumeRole",
        }
        CfnOutput(self, "RuntimeArn", value=runtime_arn)
        CfnOutput(self, "RuntimeId", value=self.runtime.attr_agent_runtime_id)
        CfnOutput(self, "DefaultEndpointArn", value=endpoint)
        CfnOutput(self, "RuntimeRoleArn", value=self.role.role_arn)
        CfnOutput(self, "ModelKey", value=model.key)
        CfnOutput(self, "ArtifactSHA256", value=config.artifact_sha256)
        CfnOutput(self, "LogRetentionDays", value=str(config.log_retention_days))
        CfnOutput(
            self,
            "RuntimeLogGroupName",
            value=f"/aws/bedrock-agentcore/runtimes/{self.runtime.attr_agent_runtime_id}-DEFAULT",
        )
        CfnOutput(self, "QueryRoleTrustAdditionProposalOnly", value=json.dumps(trust_addition))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument(
        "--allow-unbound-artifact",
        action="store_true",
        help="Offline approval preview only; never substitute a guessed S3 VersionId",
    )
    args = parser.parse_args()
    config = StreamingDeploymentConfig.model_validate_json(args.config.read_bytes())
    config.require_bound_artifact(allow_unbound_artifact=args.allow_unbound_artifact)
    app = App(outdir=args.outdir, analytics_reporting=False)
    environment = Environment(account=config.account, region=config.region)
    for model in config.models:
        StreamingRuntimeStack(
            app,
            f"{config.resource_prefix}-{model.key}",
            config=config,
            model=model,
            env=environment,
            allow_unbound_artifact=args.allow_unbound_artifact,
        )
    app.synth()


if __name__ == "__main__":
    main()
