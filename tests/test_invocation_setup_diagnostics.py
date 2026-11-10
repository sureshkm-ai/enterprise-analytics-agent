"""Runtime client construction stays observable without retrying billable dispatch."""

import json
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ConnectTimeoutError
from test_q18_artifacts import ReviewedFixture
from test_q18_artifacts import reviewed_fixture as reviewed_fixture
from test_retail_client import target

from enterprise_analytics_agent.adapters import repair_operations
from enterprise_analytics_agent.adapters.operator_reads import OperatorReadError, ReadDeadlineError
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record


@pytest.mark.parametrize("failure", ["connect", "late", "invoke"])
def test_operator_records_runtime_client_setup_without_retrying_it_or_dispatch(
    reviewed_fixture: ReviewedFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    fixture = reviewed_fixture
    now = [0.0]
    constructions: list[str] = []
    dispatches: list[bytes] = []

    class RuntimeClient:
        class meta:
            endpoint_url = "https://bedrock-agentcore.us-west-2.amazonaws.com"

        def invoke_agent_runtime(self, **kwargs: Any) -> Any:
            dispatches.append(kwargs["payload"])
            raise ConnectTimeoutError(endpoint_url=self.meta.endpoint_url)

    class Session:
        def client(self, service: str, **kwargs: Any) -> Any:
            if service != "bedrock-agentcore":
                return fixture.session.client(service, **kwargs)
            constructions.append(service)
            assert kwargs["config"].retries["total_max_attempts"] == 1
            if failure == "connect":
                raise ConnectTimeoutError(
                    endpoint_url="https://portal.sso.us-west-2.amazonaws.com/?token=NEVER_LOG"
                )
            if failure == "late":
                now[0] = 121.0
            return RuntimeClient()

    monkeypatch.setattr("boto3.Session", lambda **kwargs: Session())
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.repair_operations.time.monotonic", lambda: now[0]
    )
    output = tmp_path / "run"
    operations = repair_operations.operations_for(fixture.review, fixture.version, output)
    if failure == "invoke":
        invoke = operations.invoker(target())
        assert operations.invoker(target()) is invoke, "reuse the configured client per target"
        with pytest.raises(TimeoutError):
            invoke(payload=b'{"question":"authored"}', session_id="s" * 36)
        assert dispatches == [b'{"question":"authored"}']
    else:
        expected = ReadDeadlineError if failure == "late" else OperatorReadError
        with pytest.raises(expected) as caught:
            operations.invoker(target())
        recorded = error_record(caught.value, "q18-probe")
        diagnostic = recorded["causes"][0]["operation"]  # type: ignore[index]
        assert diagnostic["phase"] == "invocation-setup"
        assert diagnostic["service"] == "bedrock-agentcore"
        assert diagnostic["operation"] == "create_client"
        assert diagnostic["target"] == {"agentRuntimeArn": target().runtime_arn}
        assert diagnostic["attempt"] == 1
        assert not dispatches
    assert constructions == ["bedrock-agentcore"], "client setup has no retry loop"
    raw = output.with_name("run.operator-reads.jsonl").read_text()
    assert "NEVER_LOG" not in raw and "token=" not in raw
    events = [json.loads(line) for line in raw.splitlines()]
    setup = [event for event in events if event["service"] == "bedrock-agentcore"]
    assert [event["event"] for event in setup] == [
        "started",
        "succeeded" if failure == "invoke" else "failed",
    ]
    if failure == "connect":
        assert setup[-1]["failure_endpoint_host"] == "portal.sso.us-west-2.amazonaws.com"
    if failure == "late":
        assert setup[-1]["endpoint_host"] == "bedrock-agentcore.us-west-2.amazonaws.com"
    assert all(event["attempt"] == 1 for event in setup)
    assert setup[-1]["elapsed_seconds"] >= 0
