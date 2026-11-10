"""Explicit local Bedrock agent execution over already verified canonical Parquet.

Client construction, provenance verification, authorization and the persistent
question allowance are handled by the operator boundary before this runner.
This runner reuses the deployed agent implementation; it has no separate planner.
"""

import time
from pathlib import Path

from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
    ConverseClient,
)
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.agent.contracts import AgentRequest
from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.ui.models import UiResult, unreported_diagnostics


class LocalBedrockQuestions:
    def __init__(
        self,
        directory: Path,
        config: BedrockAgentConfig,
        *,
        client: ConverseClient,
        dataset_version: str = "retail-v1",
    ) -> None:
        self.directory, self.config, self.client = directory, config, client
        self.dataset_version = dataset_version
        self.context = AuthorizationContext(
            principal_id="local-shared-ui-application",
            tenant_id="retail_demo",
            allowed_regions=("North", "South"),
        )

    def ask(self, question: str) -> UiResult:
        started = time.monotonic()
        with DuckDBSemanticAdapter(self.directory) as adapter:
            response = BedrockAnalyticsAgent(
                self.config,
                client=self.client,
                adapter=adapter,
                dataset_version=self.dataset_version,
            ).run(AgentRequest(question=question), context=self.context)
        return UiResult(
            mode="local_agent",
            response=response,
            elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
            unreported_diagnostics=unreported_diagnostics(response),
        )
