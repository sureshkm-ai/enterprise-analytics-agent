"""Stateless trusted request boundary and production SDK construction."""

import json
from collections.abc import Callable
from typing import Protocol, cast

from botocore.config import Config

from enterprise_analytics_agent.adapters.athena import AthenaConfig, AthenaSemanticAdapter
from enterprise_analytics_agent.adapters.athena_execution import AthenaClient
from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
    ConverseClient,
)
from enterprise_analytics_agent.adapters.s3_publication import S3Client, get_ready_manifest
from enterprise_analytics_agent.agent.contracts import AgentDiagnostics, AgentRequest, AgentResponse
from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.hosting.config import RuntimeSettings
from enterprise_analytics_agent.hosting.workload import QueryRoleCredentials, workload_session


class AgentRunner(Protocol):
    def run(self, request: AgentRequest, *, context: AuthorizationContext) -> AgentResponse: ...


def build_agent(settings: RuntimeSettings) -> AgentRunner:
    """Use workload credentials and a separate refreshed narrow query role.

    Only an actual invocation constructs SDK clients. Health checks/imports never
    resolve credentials. AthenaConfig's profile label is metadata only here:
    injected workload clients are used, never its local-profile factory.
    """
    workload = workload_session(settings)
    query_credentials = QueryRoleCredentials(settings, workload)
    manifest = get_ready_manifest(
        s3=cast(S3Client, query_credentials.client("s3")),
        bucket=settings.source_bucket,
        dataset_version=settings.dataset_version,
        expected_account_id=settings.account,
    )
    adapter = AthenaSemanticAdapter(
        AthenaConfig(
            profile="agentcore-workload",
            region=settings.region,
            database=settings.database,
            workgroup=settings.workgroup,
            output_location=f"s3://{settings.results_bucket}/queries/",
            expected_bucket_owner=settings.account,
            table_prefix=settings.table_prefix,
            timeout_seconds=settings.query_timeout_seconds,
        ),
        manifest,
        client=cast(AthenaClient, query_credentials.client("athena")),
    )
    bedrock_config = Config(
        connect_timeout=min(5.0, settings.timeout_seconds),
        read_timeout=min(30.0, settings.timeout_seconds),
        retries={"mode": "standard", "total_max_attempts": 1},
    )
    client = cast(ConverseClient, workload.client("bedrock-runtime", config=bedrock_config))
    return BedrockAnalyticsAgent(
        BedrockAgentConfig(
            model_id=settings.model_id,
            reference_date=settings.reference_date,
            max_iterations=settings.max_iterations,
            max_tool_calls=settings.max_tool_calls,
            max_output_tokens=settings.max_output_tokens,
            max_total_tokens=settings.max_total_tokens,
            timeout_seconds=settings.timeout_seconds,
        ),
        client=client,
        adapter=adapter,
        dataset_version=manifest.dataset_version,
    )


class RuntimeApplication:
    """One fixed server scope; session IDs, headers, and history are not identity."""

    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        factory: Callable[[RuntimeSettings], AgentRunner] = build_agent,
        log: Callable[[str], None] = print,
    ) -> None:
        self.settings = settings
        self.factory = factory
        self.log = log

    def invoke(self, payload: object) -> AgentResponse:
        # Validate before constructing clients. Identity/config/history payload
        # fields are rejected rather than ignored or passed to a model.
        request = AgentRequest.model_validate(payload)
        try:
            agent = self.factory(self.settings)
            result = agent.run(request, context=self.settings.authorization_context())
        except Exception as exc:
            self.log(json.dumps({"event": "runtime_error", "error_type": type(exc).__name__}))
            return AgentResponse(
                status="error",
                answer="The analytics runtime is unavailable. Please retry later.",
                dataset_version=self.settings.dataset_version,
                error_code="runtime_unavailable",
                diagnostics=AgentDiagnostics(model_id=self.settings.model_id),
            )
        diagnostic = result.diagnostics
        self.log(
            json.dumps(
                {
                    "event": "analytics_invocation",
                    "status": result.status,
                    "dataset_version": result.dataset_version,
                    "metric_versions": result.metric_versions,
                    "model_id": diagnostic.model_id,
                    "model_configuration": diagnostic.configuration,
                    "model_calls": diagnostic.model_calls,
                    "input_tokens": diagnostic.input_tokens,
                    "output_tokens": diagnostic.output_tokens,
                    "latency_ms": diagnostic.latency_ms,
                    "tool_calls": [
                        {"name": call.name, "status": call.status, "error_code": call.error_code}
                        for call in diagnostic.tool_calls
                    ],
                    "athena": diagnostic.athena,
                }
            )
        )
        return result
