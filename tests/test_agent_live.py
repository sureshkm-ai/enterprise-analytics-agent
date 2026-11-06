"""Explicitly approved AgentCore/Bedrock evaluations; default collection never creates clients."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config

from enterprise_analytics_agent.agent.contracts import AgentResponse
from enterprise_analytics_agent.agent.evaluation import (
    AgentEvaluationCase,
    LiveAgentConfig,
    assert_evaluation,
    evaluation_cases,
)

pytestmark = pytest.mark.agent_live


class AgentInvoker(Protocol):
    def __call__(self, question: str, *, session_id: str | None = None) -> AgentResponse: ...


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "case" not in metafunc.fixturenames:
        return
    version = "parity-v1"
    if metafunc.config.getoption("run_agent_live"):
        path = metafunc.config.getoption("agent_config")
        version = LiveAgentConfig.model_validate_json(Path(path).read_text()).dataset_version
    cases = evaluation_cases(version)
    metafunc.parametrize("case", cases, ids=[case.name for case in cases])


@pytest.fixture(scope="session")
def live_agent(pytestconfig: pytest.Config) -> tuple[LiveAgentConfig, AgentInvoker]:
    config = LiveAgentConfig.model_validate_json(
        Path(pytestconfig.getoption("agent_config")).read_text()
    )
    session = boto3.Session(profile_name=config.profile, region_name=config.region)
    sdk_config = Config(
        connect_timeout=5, read_timeout=150, retries={"total_max_attempts": 1, "mode": "standard"}
    )
    assert (
        session.client("sts", config=sdk_config).get_caller_identity()["Account"] == config.account
    )
    assert config.runtime_arn.startswith(
        f"arn:aws:bedrock-agentcore:{config.region}:{config.account}:runtime/"
    )
    client = session.client("bedrock-agentcore", config=sdk_config)

    def invoke(question: str, *, session_id: str | None = None) -> AgentResponse:
        session_id = session_id or str(uuid4())
        result = client.invoke_agent_runtime(
            agentRuntimeArn=config.runtime_arn,
            runtimeSessionId=session_id,
            qualifier=config.qualifier,
            contentType="application/json",
            accept="application/json",
            payload=json.dumps({"question": question}).encode(),
        )
        body = result["response"]
        try:
            response = AgentResponse.model_validate_json(body.read())
        finally:
            body.close()
        output = Path("artifacts/agent-live-evaluations.jsonl")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "case_question": question,
                        "runtime_session_id": session_id,
                        "runtime_arn": config.runtime_arn,
                        "reference_date": config.reference_date.isoformat(),
                        "response": response.model_dump(mode="json"),
                    }
                )
                + "\n"
            )
        return response

    return config, invoke


def test_deployed_agent_matches_independent_expectations(
    live_agent: tuple[LiveAgentConfig, AgentInvoker], case: AgentEvaluationCase
) -> None:
    config, invoke = live_agent
    assert_evaluation(invoke(case.question), case, config)


def test_deployed_agent_does_not_carry_filters_between_requests_in_one_session(
    live_agent: tuple[LiveAgentConfig, AgentInvoker],
) -> None:
    config, invoke = live_agent
    session_id = str(uuid4())
    for region, expected in (("North", Decimal("28.50")), ("South", Decimal("13.00"))):
        case = AgentEvaluationCase(
            f"same-session-{region}",
            f"Show net_revenue for January 2025 in {region}.",
            "net_revenue",
            (({}, expected),),
            filters=(("region", (region,)),),
        )
        assert_evaluation(invoke(case.question, session_id=session_id), case, config)
