"""Question operator tests use injected transports and saved bodies only."""

import io
import json
from pathlib import Path
from typing import Any

import boto3
import pytest

from enterprise_analytics_agent.adapters import agentcore_invocation, retail_checkpoint
from enterprise_analytics_agent.agent.contracts import AgentResponse
from enterprise_analytics_agent.retail_evaluation import agent_cli
from enterprise_analytics_agent.retail_evaluation.campaign import CampaignLedger
from enterprise_analytics_agent.retail_evaluation.client import (
    CountedAgentClient,
    InvocationError,
    RuntimeReply,
)
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget

RUNTIME = (
    "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
    "enterprise_analytics_dev_agent-HlWywlG60h"
)


def target() -> RetailTarget:
    return RetailTarget(
        runtime_arn=RUNTIME, dataset_version="retail-v1", reference_date="2025-04-01"
    )


def response_document() -> dict[str, Any]:
    return {
        "status": "answer",
        "answer": "Exact result follows.",
        "dataset_version": "retail-v1",
        "metric_versions": {"net_revenue": "1.0.0"},
        "results": [
            {
                "metric_id": "net_revenue",
                "definition_version": "1.0.0",
                "time_range": {"start": "2025-01-01", "end": "2025-02-01"},
                "group_by": ["region"],
                "unit": "currency",
                "currency": "USD",
                "rows": [
                    {"dimensions": {"region": "North"}, "value": "123456789012345.67"},
                    {"dimensions": {"region": "South"}, "value": None},
                ],
            }
        ],
        "diagnostics": {
            "model_id": "us.amazon.nova-lite-v1:0",
            "configuration": {"reference_date": "2025-04-01"},
        },
    }


def test_reservation_is_durable_before_dispatch_and_only_question_is_sent(tmp_path: Path) -> None:
    ledger = CampaignLedger(tmp_path / "ledger.jsonl")
    body = io.BytesIO(json.dumps(response_document()).encode())
    observed_sessions: list[str] = []

    def invoke(*, payload: bytes, session_id: str) -> RuntimeReply:
        assert json.loads(payload) == {"question": "Show net_revenue for January 2025."}
        assert ledger.summary()["used"] == 1
        assert ledger.summary()["completed"] == 0
        observed_sessions.append(session_id)
        return RuntimeReply(body, "trace-id")

    ticks = iter([0.0, 0.125])
    result = CountedAgentClient(target(), ledger, invoke, clock=lambda: next(ticks)).invoke(
        "Show net_revenue for January 2025.", session_id="s" * 36
    )
    assert body.closed
    assert result.elapsed_ms == 125
    assert result.invocation_id == "trace-id"
    assert observed_sessions == ["s" * 36]
    diagnostics = result.raw_response["diagnostics"]
    assert isinstance(diagnostics, dict)
    assert "input_tokens" not in diagnostics
    assert ledger.summary()["completed"] == 1


@pytest.mark.parametrize(
    "failure",
    [
        "sdk",
        "read",
        "sdk_timeout",
        "body_timeout",
        "malformed",
        "wrong_dataset",
        "wrong_model",
        "wrong_date",
    ],
)
def test_every_dispatch_failure_consumes_quota_and_closes_body(
    tmp_path: Path, failure: str
) -> None:
    ledger = CampaignLedger(tmp_path / "ledger.jsonl")
    document = response_document()
    if failure == "wrong_dataset":
        document["dataset_version"] = "parity-v1"
    if failure == "wrong_model":
        document["diagnostics"]["model_id"] = "another-model"
    if failure == "wrong_date":
        document["diagnostics"]["configuration"]["reference_date"] = "2025-02-01"

    class Body(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            if failure == "read":
                raise OSError("connection reset")
            if failure == "body_timeout":
                raise TimeoutError("body read timed out")
            return super().read(size)

    body = Body(b"bad" if failure == "malformed" else json.dumps(document).encode())

    def invoke(*, payload: bytes, session_id: str) -> RuntimeReply:
        if failure == "sdk":
            raise RuntimeError("private SDK details not printed")
        if failure == "sdk_timeout":
            raise TimeoutError("SDK timed out")
        return RuntimeReply(body)

    with pytest.raises(InvocationError) as error:
        CountedAgentClient(target(), ledger, invoke).invoke("question")
    assert error.value.__cause__ is not None
    assert ledger.summary()["used"] == 1
    records = [json.loads(line) for line in ledger.path.read_text().splitlines()]
    assert records[-1]["outcome"] == "failed"
    assert records[-1]["error_code"] == {
        "sdk": "sdk_error",
        "read": "body_error",
        "sdk_timeout": "sdk_timeout",
        "body_timeout": "body_timeout",
    }.get(failure, "response_validation_error")
    assert "private SDK" not in ledger.path.read_text()
    assert body.closed or failure in {"sdk", "sdk_timeout"}


def test_invalid_input_never_reserves_or_dispatches(tmp_path: Path) -> None:
    ledger = CampaignLedger(tmp_path / "ledger.jsonl")

    def forbidden(*, payload: bytes, session_id: str) -> RuntimeReply:
        pytest.fail("must not dispatch")

    client = CountedAgentClient(target(), ledger, forbidden)
    with pytest.raises(ValueError):
        client.invoke(" ")
    with pytest.raises(ValueError, match="session ID"):
        client.invoke("question", session_id="short")
    assert not ledger.path.exists()


def test_shared_session_contains_no_mutable_payload_or_scope_state(tmp_path: Path) -> None:
    sent: list[dict[str, str]] = []
    sessions: list[str] = []

    def invoke(*, payload: bytes, session_id: str) -> RuntimeReply:
        sent.append(json.loads(payload))
        sessions.append(session_id)
        return RuntimeReply(io.BytesIO(json.dumps(response_document()).encode()))

    ledger = CampaignLedger(tmp_path / "ledger.jsonl")
    client = CountedAgentClient(target(), ledger, invoke)
    client.invoke("North", session_id="same-session-id-with-more-than-33-characters")
    client.invoke("South", session_id="same-session-id-with-more-than-33-characters")
    assert sent == [{"question": "North"}, {"question": "South"}]
    assert sessions[0] == sessions[1]
    assert ledger.summary()["used"] == 2


def test_sdk_factory_verifies_account_and_disables_all_hidden_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[str, dict[str, Any]]] = []

    class FakeSession:
        def __init__(self, **kwargs: str) -> None:
            assert kwargs == {"profile_name": "analytics-dev", "region_name": "us-west-2"}

        def client(self, service: str, **kwargs: Any) -> object:
            config = kwargs["config"]
            assert config.retries == {"total_max_attempts": 1, "mode": "standard"}
            assert config.connect_timeout == 5
            assert config.read_timeout == 150
            constructed.append((service, kwargs))
            return self

        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": "wrong"}

    monkeypatch.setattr(boto3, "Session", FakeSession)
    with pytest.raises(ValueError, match="account"):
        agentcore_invocation.create_runtime_invoker(target())
    assert [service for service, _ in constructed] == ["sts"]


@pytest.mark.parametrize("status,exit_code", [("answer", 0), ("clarification", 2), ("error", 1)])
def test_cli_replay_exact_output_exit_codes_and_never_constructs_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    exit_code: int,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("offline replay created a client")

    monkeypatch.setattr(agentcore_invocation, "create_runtime_invoker", forbidden)
    document = response_document()
    document["status"] = status
    path = tmp_path / "response.json"
    path.write_text(json.dumps(document))
    assert agent_cli.main(["--response-file", str(path), "--format", "json"]) == exit_code
    output = capsys.readouterr()
    parsed = AgentResponse.model_validate_json(output.out)
    assert parsed.results[0].rows[0].value is not None
    assert "123456789012345.67" in output.out
    assert '"model_id"' in output.err
    assert "client_elapsed_ms" not in json.loads(output.out)


def test_cli_human_output_preserves_nulls_exact_values_units_boundaries_versions() -> None:
    output = agent_cli.render_text(AgentResponse.model_validate(response_document()))
    assert "North: 123456789012345.67" in output
    assert "South: null" in output
    assert "[2025-01-01, 2025-02-01)" in output
    assert "unit=currency currency=USD" in output
    assert "net_revenue v1.0.0" in output
    assert "dataset: retail-v1" in output


def test_cli_live_missing_config_fails_before_any_transport_construction(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert agent_cli.main(["--invoke-live", "--question", "question"]) == 1
    assert "ValueError" in capsys.readouterr().err


def test_cli_rejects_model_identity_and_history_flags() -> None:
    with pytest.raises(SystemExit) as error:
        agent_cli.main(["--invoke-live", "--tenant", "other_retail"])
    assert error.value.code == 2


def test_cli_rejects_parity_target_without_restoration_before_aws(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("parity demo attempted to construct an AWS client")

    monkeypatch.setattr(agentcore_invocation, "create_runtime_invoker", forbidden)
    document = target().model_dump(mode="json")
    document.update(dataset_version="parity-v1", reference_date="2025-02-01")
    path = tmp_path / "target.json"
    path.write_text(json.dumps(document))
    assert (
        agent_cli.main(["--invoke-live", "--target-config", str(path), "--question", "question"])
        == 1
    )


def test_sdk_success_passes_exact_target_and_only_allowed_request_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    class FakeSession:
        def __init__(self, **kwargs: str) -> None:
            pass

        def client(self, service: str, **kwargs: Any) -> object:
            return self

        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": "453711491609"}

        def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]:
            observed.append(kwargs)
            return {"response": io.BytesIO(b"{}"), "statusCode": 200, "traceId": "trace"}

    monkeypatch.setattr(boto3, "Session", FakeSession)
    transport = agentcore_invocation.create_runtime_invoker(target())
    reply = transport(payload=b'{"question":"question"}', session_id="s" * 36)
    assert reply.invocation_id == "trace"
    assert observed == [
        {
            "agentRuntimeArn": RUNTIME,
            "runtimeSessionId": "s" * 36,
            "qualifier": "DEFAULT",
            "contentType": "application/json",
            "accept": "application/json",
            "payload": b'{"question":"question"}',
        }
    ]
    reply.body.close()


def test_restoration_client_requires_fresh_verifier_before_any_reservation(tmp_path: Path) -> None:
    parity_target = RetailTarget.model_validate(
        target().model_dump(mode="json")
        | {"dataset_version": "parity-v1", "reference_date": "2025-02-01"}
    )
    ledger = CampaignLedger(tmp_path / "ledger.jsonl")

    def forbidden(*, payload: bytes, session_id: str) -> RuntimeReply:
        pytest.fail("failed restoration verification must block invocation")

    with pytest.raises(ValueError, match="verifier"):
        CountedAgentClient(parity_target, ledger, forbidden, purpose="restoration_smoke")

    def failed_verification() -> Any:
        raise ValueError("Runtime not restored")

    client = CountedAgentClient(
        parity_target,
        ledger,
        forbidden,
        purpose="restoration_smoke",
        restoration_verifier=failed_verification,
    )
    with pytest.raises(ValueError, match="Runtime not restored"):
        client.invoke("Show net_revenue for January 2025 by region.")
    assert not ledger.path.exists()


def test_restoration_smoke_independent_expected_values_reject_wrong_results() -> None:
    document = response_document()
    document["results"][0]["rows"] = [
        {"dimensions": {"region": "North"}, "value": "28.50"},
        {"dimensions": {"region": "South"}, "value": "13.00"},
    ]
    agent_cli._check_restoration_smoke(AgentResponse.model_validate(document))
    document["results"][0]["rows"][0]["value"] = "28.51"
    with pytest.raises(ValueError, match="independent"):
        agent_cli._check_restoration_smoke(AgentResponse.model_validate(document))


def test_cli_retail_readiness_failure_does_not_dispatch_or_reserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "target.json"
    path.write_text(target().model_dump_json())

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("unready retail checkpoint must not construct an invocation transport")

    def unready(**kwargs: object) -> dict[str, object]:
        assert kwargs == {"scope": "retail-v1"}
        raise ValueError("actual Runtime still parity-v1")

    monkeypatch.setattr(retail_checkpoint, "verify_checkpoint", unready)
    monkeypatch.setattr(agentcore_invocation, "create_runtime_invoker", forbidden)
    assert (
        agent_cli.main(["--invoke-live", "--target-config", str(path), "--question", "question"])
        == 1
    )


def test_cli_warmup_uses_separate_label_and_verified_retail_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "target.json"
    path.write_text(target().model_dump_json())
    ledger = CampaignLedger(tmp_path / "ledger.jsonl")
    checked: list[str] = []

    def checkpoint(**kwargs: object) -> dict[str, object]:
        assert kwargs == {"scope": "retail-v1"}
        checked.append("verified")
        return {"runtime": {"agentRuntimeArn": RUNTIME}}

    def transport(*, payload: bytes, session_id: str) -> RuntimeReply:
        assert checked == ["verified"]
        assert ledger.summary()["purposes"] == {"warmup": 1}
        return RuntimeReply(io.BytesIO(json.dumps(response_document()).encode()))

    monkeypatch.setattr(retail_checkpoint, "verify_checkpoint", checkpoint)
    monkeypatch.setattr(agentcore_invocation, "create_runtime_invoker", lambda _: transport)
    monkeypatch.setattr(agent_cli, "CampaignLedger", lambda: ledger)
    assert (
        agent_cli.main(
            [
                "--invoke-live",
                "--warmup",
                "--target-config",
                str(path),
                "--question",
                "Show net_revenue for January 2025 by region.",
            ]
        )
        == 0
    )
    assert ledger.summary()["used"] == 1
