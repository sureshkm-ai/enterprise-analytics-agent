"""Client repair recovers proved request failures without resetting deployed evidence."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

import boto3
import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from test_model_stream_ui import Body, metric_answer, operator, wire_events
from test_model_streams_review import review as review

from enterprise_analytics_agent.ui import model_streams
from enterprise_analytics_agent.ui.model_streams import StreamingLedger, StreamingReview
from enterprise_analytics_agent.ui.models import AskRequest, UiError, UiResult
from enterprise_analytics_agent.ui.streaming_health import acceptance_failure_message
from enterprise_analytics_agent.ui.workbench_repair import (
    OperatorRepair,
    source_inventory,
    verify_operator_repair,
    verify_retained_attempts,
)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(boto3, "Session", lambda **kwargs: pytest.fail("No real AWS session"))


def workbench(review: StreamingReview) -> StreamingReview:
    return review.model_copy(update={"schema_version": "bedrock-model-workbench-v1"})


def accept(ledger: StreamingLedger) -> None:
    path = ledger.directory / "acceptance/nova-lite.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "review_sha256": ledger.review.sha256,
                "model_key": "nova-lite",
                "passed": True,
                "cases": ["Q18", "all-five-regionals"],
            }
        )
    )


def clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Self:
            return cls.fromtimestamp(now.timestamp(), tz=UTC)

    monkeypatch.setattr(model_streams, "datetime", Frozen)


def failed_call(ledger: StreamingLedger, error_type: str = "ReadTimeoutError") -> str:
    identifier = str(uuid4())
    with ledger.attempt(identifier, "nova-lite", mode="live") as record:
        record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
        record(
            {
                "event": "failed",
                "operation": "InvokeAgentRuntime",
                "number": 1,
                "error_type": error_type,
            }
        )
    return identifier


def test_existing_timeout_recovers_only_after_settling_with_identical_ledger(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    clock(monkeypatch, now)
    old = StreamingLedger(tmp_path, workbench(review))
    accept(old)
    failed_call(old)
    original = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    fixed = StreamingLedger(tmp_path, old.review, recover_requests=True)
    waiting = fixed.summary()
    assert waiting["used"] == 1 and waiting["blocked_models"] == ["nova-lite"]
    failures = waiting["request_failures"]
    assert isinstance(failures, list) and failures[0]["wait_seconds"] == 300
    with pytest.raises(UiError, match="closed"):
        with fixed.attempt(str(uuid4()), "nova-lite", mode="local_agent"):
            pytest.fail("No overlap after an uncertain remote outcome")
    clock(monkeypatch, now + timedelta(seconds=301))
    recovered = fixed.summary()
    assert recovered["blocked_models"] == [] and recovered["failed"] is True
    assert recovered["used"] == 1 and recovered["regular_remaining"] == 37
    assert original == {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
    assert old.summary()["blocked_models"] == ["nova-lite"]
    # A later explicit submission is a different counted attempt, not a retry.
    with fixed.attempt(str(uuid4()), "nova-lite", mode="live") as record:
        record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
        record({"event": "returned", "operation": "InvokeAgentRuntime", "number": 1})
    assert fixed.summary()["used"] == 2


@pytest.mark.parametrize(
    "error_type", ["ClientError", "ValueError", "StreamProtocolError", "RuntimeError"]
)
def test_unknown_access_and_correctness_errors_do_not_reenable_models(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch, error_type: str
) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    clock(monkeypatch, now)
    ledger = StreamingLedger(tmp_path, workbench(review), recover_requests=True)
    accept(ledger)
    failed_call(ledger, error_type)
    clock(monkeypatch, now + timedelta(hours=1))
    assert ledger.summary()["blocked_models"] == ["nova-lite"]


def test_timeout_does_not_override_failed_acceptance_or_reopen_history(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(UiError, match="historical"):
        StreamingLedger(tmp_path, review, recover_requests=True)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    clock(monkeypatch, now)
    ledger = StreamingLedger(tmp_path, workbench(review), recover_requests=True)
    failed_call(ledger)
    clock(monkeypatch, now + timedelta(hours=1))
    assert ledger.summary()["blocked_models"] == ["nova-lite"]


@pytest.mark.parametrize("kind", ["fallback", "token_limit", "invalid_tool_response"])
def test_verified_fallback_and_question_limits_are_not_model_availability_failures(
    tmp_path: Path, review: StreamingReview, kind: str
) -> None:
    ledger = StreamingLedger(tmp_path, workbench(review), recover_requests=True)
    accept(ledger)
    identifier = str(uuid4())
    with ledger.attempt(identifier, "nova-lite", mode="live") as record:
        record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
        record({"event": "returned", "operation": "InvokeAgentRuntime", "number": 1})
        record({"event": "question_failed"})
    response = metric_answer()
    if kind != "fallback":
        response = response.model_copy(update={"status": "error", "error_code": kind})
    result = UiResult(
        mode="live",
        response=response,
        presentation_status="fallback" if kind == "fallback" else "not_needed",
    )
    (ledger.directory / f"result-{identifier}.json").write_text(result.model_dump_json())
    assert ledger.summary()["used"] == 1
    assert ledger.summary()["blocked_models"] == (
        ["nova-lite"] if kind == "invalid_tool_response" else []
    )


def test_repair_never_clears_incomplete_accounting_expiry_or_exhaustion(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = StreamingLedger(tmp_path, workbench(review), recover_requests=True)
    accept(ledger)
    with ledger.attempt(str(uuid4()), "nova-lite", mode="live") as record:
        record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
    assert ledger.summary()["incomplete"] and ledger.summary()["blocked"]
    clock(monkeypatch, datetime(2100, 1, 1, tzinfo=UTC))
    assert ledger.summary()["expired"] and ledger.summary()["blocked"]


def test_recovered_model_cannot_spend_reserved_slots(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    clock(monkeypatch, now)
    bounded = workbench(review).model_copy(update={"maximum_attempts": 3, "ordinary_limit": 1})
    ledger = StreamingLedger(tmp_path, bounded, recover_requests=True)
    accept(ledger)
    failed_call(ledger)
    clock(monkeypatch, now + timedelta(hours=1))
    state = ledger.summary()
    assert state["blocked_models"] == [] and state["blocked"] is True
    assert state["regular_remaining"] == 0 and state["protected_cleanup"] == 1
    assert state["unapproved_reserve"] == 1
    with pytest.raises(UiError, match="closed"):
        with ledger.attempt(str(uuid4()), "nova-lite", mode="live"):
            pytest.fail("Recovery must not increase the approved budget")


def test_account_unavailability_label_requires_matching_retained_evidence(tmp_path: Path) -> None:
    path = tmp_path / "evaluations/bedrock-streaming/workbench.model-diagnostics.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "review_sha256": "a" * 64,
                "models": [
                    {
                        "model_key": "example",
                        "service_error": {
                            "code": "AccessDeniedException",
                            "message": "example is not available for this account.",
                        },
                    }
                ],
            }
        )
    )
    label, message = acceptance_failure_message(tmp_path, "a" * 64, "example")
    assert label == "Account access unavailable" and "during acceptance" in message
    assert acceptance_failure_message(tmp_path, "b" * 64, "example")[0] == "Acceptance failed"


def repair_fixture(root: Path, review: StreamingReview) -> tuple[StreamingReview, OperatorRepair]:
    base = root / "src/enterprise_analytics_agent"
    (base / "ui").mkdir(parents=True)
    (base / "agent.py").write_text("immutable semantic code\n")
    (base / "ui/model_streams.py").write_text("old operator\n")
    inventory = source_inventory(root)
    reviewed = workbench(review).model_copy(
        update={
            "source_sha256": hashlib.sha256(
                json.dumps(inventory, sort_keys=True).encode()
            ).hexdigest()
        }
    )
    (base / "ui/model_streams.py").write_text("fixed operator\n")
    modified = {
        key: value for key, value in source_inventory(root).items() if inventory.get(key) != value
    }
    return reviewed, OperatorRepair(
        schema_version="workbench-client-repair-v1",
        review_sha256=reviewed.sha256,
        baseline_source_files=inventory,
        operator_source_files=modified,
    )


def test_client_binding_preserves_agent_source_and_rejects_drift(
    tmp_path: Path, review: StreamingReview
) -> None:
    reviewed, repair = repair_fixture(tmp_path, review)
    verify_operator_repair(tmp_path, reviewed, repair)
    (tmp_path / "src/enterprise_analytics_agent/agent.py").write_text("changed agent")
    with pytest.raises(UiError, match="Current source"):
        verify_operator_repair(tmp_path, reviewed, repair)
    forged = repair.model_copy(update={"operator_source_files": source_inventory(tmp_path)})
    with pytest.raises(UiError, match="cannot change"):
        verify_operator_repair(tmp_path, reviewed, forged)


def test_missing_or_old_journal_cannot_be_recreated_by_client_repair(
    tmp_path: Path, review: StreamingReview
) -> None:
    reviewed, repair = repair_fixture(tmp_path, review)
    ledger = StreamingLedger(tmp_path, reviewed)
    with pytest.raises(UiError, match="missing"):
        verify_retained_attempts(ledger, repair)
    failed_call(ledger)
    verify_retained_attempts(ledger, repair)
    with pytest.raises(UiError, match="predates"):
        verify_retained_attempts(
            ledger, repair.model_copy(update={"minimum_recorded_attempts": 24})
        )


def test_invocation_waits_for_cold_start_but_keeps_one_sdk_attempt(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions, state = operator(tmp_path, review, monkeypatch)
    real_session: Any = boto3.Session
    configurations = {}

    def session(**kwargs: object) -> Any:
        instance = real_session(**kwargs)
        client = instance.client

        def checked(name: str, *, config: Any) -> Any:
            configurations[name] = config
            # Simulate first response headers arriving after 45s. The former 30s
            # client would fail before it could read any Runtime heartbeat.
            if name == "bedrock-agentcore" and config.read_timeout < 45:
                raise ReadTimeoutError(endpoint_url="https://example.invalid")
            return client(name, config=config)

        instance.client = checked
        return instance

    monkeypatch.setattr(boto3, "Session", session)
    result = questions.ask(
        AskRequest(
            question="Show net_revenue for January 2025 by region.", mode="live", request_id=uuid4()
        )
    )
    assert result.response.status == "answer" and len(state.invocations) == 1
    assert configurations["bedrock-agentcore"].read_timeout == 300
    assert configurations["bedrock-agentcore"].retries["total_max_attempts"] == 1
    assert configurations["sts"].read_timeout == 30


@pytest.mark.parametrize(
    "error",
    [
        ReadTimeoutError(endpoint_url="https://example.invalid"),
        ClientError(
            {
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "account unavailable token=secret",
                },
                "ResponseMetadata": {
                    "RequestId": "aws-error-123",
                    "HTTPStatusCode": 403,
                    "HostId": "",
                    "HTTPHeaders": {},
                    "RetryAttempts": 0,
                },
            },
            "InvokeAgentRuntime",
        ),
    ],
)
def test_failure_has_actionable_public_error_and_private_redacted_diagnostics(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    questions, state = operator(tmp_path, workbench(review), monkeypatch, failure=error)
    # Dispatch fixture replaces all local proof boundaries; real proof is tested above.
    questions.operator_repair = OperatorRepair(
        schema_version="workbench-client-repair-v1",
        review_sha256=questions.review.sha256,
        baseline_source_files={},
        operator_source_files={},
    )
    # This operator fixture creates a fresh fake ledger; the deployment path
    # instead requires the real pre-existing journal, tested independently above.
    monkeypatch.setattr(questions, "_verify_inputs", lambda: None)
    request = AskRequest(question="private question", mode="live", request_id=uuid4())
    with pytest.raises(UiError, match="Diagnostic:") as caught:
        questions.ask(request)
    assert "private question" not in str(caught.value) and "secret" not in str(caught.value)
    path = questions.ledger.directory / f"error-{request.request_id}.json"
    evidence = json.loads(path.read_bytes())
    assert evidence["phase"] == "Runtime invocation / first response"
    assert evidence["error_type"] == type(error).__name__
    assert evidence["runtime_session_id"] == state.invocations[0]["runtimeSessionId"]
    assert "secret" not in path.read_text()
    assert questions.ledger.summary()["used"] == 1 and not questions.ledger.summary()["incomplete"]
    assert len(state.invocations) == 1


def test_malformed_stream_stays_paused_in_repaired_ui(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions, _ = operator(tmp_path, workbench(review), monkeypatch, body=Body(wire_events()[:-1]))
    questions.ledger.recover_requests = True
    accept(questions.ledger)
    with pytest.raises(UiError):
        questions.ask(AskRequest(question="Q18", mode="live", request_id=uuid4()))
    assert (
        questions.public_state("live")["availability_label"] == "Request failed — inspect details"
    )
    assert questions.public_state("live")["enabled"] is False
