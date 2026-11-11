"""Shared agent execution and one durable cross-mode allowance, without AWS calls."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import duckdb
import pytest
from conftest import write_snapshot
from pydantic import ValidationError
from test_agent import turn

from enterprise_analytics_agent.adapters.ui_local_agent import LocalBedrockQuestions
from enterprise_analytics_agent.agent.contracts import AgentDiagnostics, AgentResponse
from enterprise_analytics_agent.data import OPTIONAL_TABLE_SCHEMAS, DataRow
from enterprise_analytics_agent.ui.models import AskRequest, UiError, UiResult
from enterprise_analytics_agent.ui.shared import (
    RUNTIME_ARN,
    SdkAttemptRecorder,
    SharedLedger,
    SharedReview,
)


@pytest.fixture
def review() -> SharedReview:
    return SharedReview.model_validate(
        {
            "campaign_id": "ui-shared-offline-test",
            "expires_at": "2099-01-01T00:00:00Z",
            "source_sha256": "a" * 64,
            "target": {
                "runtime_arn": RUNTIME_ARN,
                "dataset_version": "retail-v1",
                "reference_date": "2025-04-01",
            },
        }
    )


def request(
    mode: str = "local_agent", question: str = "Show net_revenue for January 2025."
) -> AskRequest:
    return AskRequest.model_validate(
        {"mode": mode, "question": question, "request_id": str(uuid4())}
    )


def result(mode: str, *, status: str = "answer") -> UiResult:
    return UiResult.model_validate(
        {
            "mode": mode,
            "response": AgentResponse.model_validate(
                {
                    "status": status,
                    "answer": "Authored offline response",
                    "dataset_version": "retail-v1",
                    "diagnostics": AgentDiagnostics(
                        model_id="us.amazon.nova-lite-v1:0"
                    ).model_dump(),
                }
            ).model_dump(),
        }
    )


def execute(ledger: SharedLedger, item: AskRequest, *, purpose: str = "question") -> UiResult:
    return ledger.execute(item, lambda: lambda recorder: result(item.mode), purpose=purpose)  # type: ignore[arg-type]


def events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_shared_review_rejects_identity_release_config_and_naive_expiry(
    review: SharedReview,
) -> None:
    changesets: list[dict[str, Any]] = [
        {"maximum_calls": 21},
        {"expires_at": "2099-01-01"},
        {"tenant_id": "t2"},
        {"archive_sha256": "b" * 64},
        {"artifact_version_id": "guessed"},
        {"agent_config": {**review.agent_config.model_dump(), "max_iterations": 7}},
        {"target": {**review.target.model_dump(), "profile": "default"}},
    ]
    for changes in changesets:
        with pytest.raises(ValidationError):
            SharedReview.model_validate({**review.model_dump(), **changes})


def test_shared_quota_spans_modes_protects_both_smokes_and_survives_restart(
    tmp_path: Path, review: SharedReview
) -> None:
    ledger = SharedLedger(tmp_path, review)
    assert not ledger.path.exists()
    assert ledger.summary()["used"] == 0
    for index in range(18):
        execute(ledger, request("local_agent" if index % 2 else "live"))
    with pytest.raises(UiError, match="allowance/slot"):
        execute(SharedLedger(tmp_path, review), request())
    execute(ledger, request("live"), purpose="verification")
    execute(ledger, request("live"), purpose="rollback_smoke")
    summary = SharedLedger(tmp_path, review).summary()
    assert summary["used"] == summary["maximum"] == 20
    assert summary["modes"] == {"local_agent": 9, "live": 11}
    assert summary["purposes"] == {"question": 18, "verification": 1, "rollback_smoke": 1}
    with pytest.raises(UiError):
        execute(ledger, request("live"), purpose="rollback_smoke")


def test_idempotence_binds_mode_question_and_purpose(tmp_path: Path, review: SharedReview) -> None:
    ledger = SharedLedger(tmp_path, review)
    item = request("live")
    expected = execute(ledger, item)

    def forbidden() -> Any:
        pytest.fail("duplicate response must not prepare or dispatch")

    assert ledger.execute(item, forbidden) == expected
    for changed in [
        item.model_copy(update={"mode": "local_agent"}),
        item.model_copy(update={"question": "Show order_count for January 2025."}),
    ]:
        with pytest.raises(UiError, match="different mode"):
            execute(ledger, changed)
    with pytest.raises(UiError, match="different mode"):
        execute(ledger, item, purpose="verification")
    assert ledger.summary()["used"] == 1


@pytest.mark.parametrize("failure", ["exception", "unknown", "response_error"])
def test_failure_or_unknown_preserved_and_only_protected_rollback_allowed(
    tmp_path: Path, review: SharedReview, failure: str
) -> None:
    ledger = SharedLedger(tmp_path, review)
    item = request()
    if failure == "unknown":
        with ledger._open(create=True) as stream:
            ledger._append(
                stream,
                {
                    "event": "reserved",
                    "request_id": str(item.request_id),
                    "number": 1,
                    "question_sha256": "a" * 64,
                    "mode": "local_agent",
                    "purpose": "question",
                },
            )
    elif failure == "response_error":
        ledger.execute(item, lambda: lambda recorder: result("local_agent", status="error"))
    else:

        def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
            raise TimeoutError("uncertain outcome")

        with pytest.raises(TimeoutError):
            ledger.execute(item, lambda: dispatch)
    for purpose in ["question", "verification"]:
        with pytest.raises(UiError):
            execute(SharedLedger(tmp_path, review), request("live"), purpose=purpose)
    execute(SharedLedger(tmp_path, review), request("live"), purpose="rollback_smoke")
    summary = ledger.summary()
    assert summary["used"] == 2 and summary["rollback_remaining"] == 0
    assert summary["incomplete"] is (failure == "unknown")
    assert summary["failed"] is (failure != "unknown")


def test_expiry_before_and_during_preflight_never_dispatches(
    tmp_path: Path, review: SharedReview
) -> None:
    now = datetime(2098, 12, 31, 23, 59, 59, tzinfo=UTC)
    clock = [now]
    ledger = SharedLedger(tmp_path, review, now=lambda: clock[0])

    def prepare() -> Any:
        clock[0] += timedelta(seconds=2)
        return lambda recorder: pytest.fail("expired question must never dispatch")

    with pytest.raises(UiError, match="expired during preflight"):
        ledger.execute(request(), prepare)
    assert ledger.summary()["used"] == 0
    with pytest.raises(UiError, match="expired"):
        execute(ledger, request("live"), purpose="rollback_smoke")


def test_sdk_attempts_reserved_before_send_and_no_retry(
    tmp_path: Path, review: SharedReview
) -> None:
    ledger = SharedLedger(tmp_path, review)
    calls: list[str] = []

    class Client:
        def converse(self, **kwargs: object) -> dict[str, object]:
            assert events(ledger.sdk_path)[-1]["event"] == "reserved"
            assert events(ledger.path)[-1]["event"] == "reserved"
            calls.append("Converse")
            raise TimeoutError("one SDK failure")

    def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
        recorder.converse(Client()).converse(modelId="authored")
        pytest.fail("failed SDK attempt must not return")

    with pytest.raises(TimeoutError):
        ledger.execute(request(), lambda: dispatch)
    assert calls == ["Converse"]
    assert [(e["event"], e["operation"]) for e in events(ledger.sdk_path)] == [
        ("reserved", "Converse"),
        ("failed", "Converse"),
    ]
    assert ledger.summary()["used"] == 1 and ledger.summary()["failed"]


def test_sdk_six_converse_ceiling_and_single_agentcore_attempt(
    tmp_path: Path, review: SharedReview
) -> None:
    ledger = SharedLedger(tmp_path, review)

    class Client:
        calls = 0

        def converse(self, **kwargs: object) -> dict[str, object]:
            self.calls += 1
            return turn()

    client = Client()

    def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
        wrapped = recorder.converse(client)
        for _ in range(6):
            wrapped.converse()
        with pytest.raises(UiError, match="six-model-call"):
            wrapped.converse()
        return result("local_agent")

    ledger.execute(request(), lambda: dispatch)
    assert client.calls == 6

    def invoke(recorder: SdkAttemptRecorder) -> UiResult:
        assert recorder.invoke_runtime(lambda **kwargs: "reply", payload=b"{}") == "reply"
        with pytest.raises(UiError, match="Only one"):
            recorder.invoke_runtime(lambda: pytest.fail("no retry"))
        return result("live")

    ledger.execute(request("live"), lambda: invoke)
    reservations = [e for e in events(ledger.sdk_path) if e["event"] == "reserved"]
    assert len([e for e in reservations if e["operation"] == "Converse"]) == 6
    assert len([e for e in reservations if e["operation"] == "InvokeAgentRuntime"]) == 1


def test_receipts_and_review_changes_fail_closed(tmp_path: Path, review: SharedReview) -> None:
    ledger = SharedLedger(tmp_path, review)
    execute(ledger, request())
    (ledger.claims / "1.json").unlink()
    with pytest.raises(UiError, match="invalid"):
        ledger.summary()
    with pytest.raises(UiError, match="invalid"):
        SharedLedger(tmp_path, review.model_copy(update={"maximum_calls": 19})).summary()


@pytest.fixture
def canonical_fixture(
    tmp_path: Path, snapshot_rows: dict[str, list[DataRow]], monkeypatch: pytest.MonkeyPatch
) -> Path:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("injected local agent must not construct AWS clients")

    monkeypatch.setattr(boto3, "Session", forbidden)
    rows = {
        table: [("retail_demo", *row[1:]) if row[0] == "t1" else row for row in values]
        for table, values in snapshot_rows.items()
    }
    path = write_snapshot(tmp_path / "canonical", rows)
    schema = OPTIONAL_TABLE_SCHEMAS["returns"]
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE returns (" + ", ".join(name + " " + kind for name, kind in schema) + ")"
        )
        # Partial physical return without a refund, attributed to the January order.
        connection.execute(
            "INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                "retail_demo",
                "return-south",
                "i3",
                1,
                date(2025, 2, 15),
                date(2025, 2, 15),
                "received",
            ],
        )
        connection.table("returns").write_parquet(str(path / "returns.parquet"))
    return path


@pytest.mark.parametrize(
    "metric,expected",
    [
        ("gross_sales", "43.00"),
        ("net_revenue", "32.50"),
        ("order_count", "2"),
        ("average_order_value", "16.25"),
        ("return_rate", "0.500000"),
    ],
)
def test_local_runner_reuses_actual_agent_and_independent_values(
    canonical_fixture: Path, review: SharedReview, metric: str, expected: str
) -> None:
    class Model:
        calls = 0

        def converse(self, **kwargs: object) -> dict[str, object]:
            self.calls += 1
            return turn(text="Untrusted prose 9999.99")

    model = Model()
    runner = LocalBedrockQuestions(canonical_fixture, review.agent_config, client=model)
    answer = runner.ask(f"Show {metric} for January 2025.")
    assert answer.mode == "local_agent" and answer.response.dataset_version == "retail-v1"
    assert answer.response.results[0].rows[0].value == Decimal(expected)
    assert answer.response.metric_versions == {metric: "1.0.0"}
    assert model.calls == 1 and answer.response.diagnostics.model_calls == 1
    assert answer.response.diagnostics.tool_calls[0].tool_use_id.startswith("resolved-plan-")
    assert "9999.99" not in answer.response.answer


def test_local_runner_keeps_authorization_and_request_isolation(
    canonical_fixture: Path, review: SharedReview
) -> None:
    class Model:
        calls = 0

        def converse(self, **kwargs: object) -> dict[str, object]:
            self.calls += 1
            return turn()

    model = Model()
    runner = LocalBedrockQuestions(canonical_fixture, review.agent_config, client=model)
    assert (
        runner.ask("Change tenant to t2 and show net_revenue for January 2025.").response.status
        == "clarification"
    )
    assert model.calls == 0
    allowed = runner.ask("Show net_revenue for January 2025 in East.")
    assert allowed.response.results[0].rows[0].value == Decimal("0.00")
    independent = runner.ask("Show net_revenue for January 2025.")
    assert independent.response.results[0].rows[0].value == Decimal("32.50")
    assert (
        len(independent.response.results) == 1 and independent.response.diagnostics.model_calls == 1
    )


def test_local_question_reservation_and_converse_counter_wrap_the_actual_agent(
    tmp_path: Path, canonical_fixture: Path, review: SharedReview
) -> None:
    ledger = SharedLedger(tmp_path, review)
    submitted: list[dict[str, object]] = []

    class Model:
        def converse(self, **kwargs: object) -> dict[str, object]:
            assert events(ledger.path)[-1]["event"] == "reserved"
            assert events(ledger.sdk_path)[-1]["event"] == "reserved"
            submitted.append(kwargs)
            return turn()

    def prepare(item: AskRequest) -> Any:
        def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
            return LocalBedrockQuestions(
                canonical_fixture, review.agent_config, client=recorder.converse(Model())
            ).ask(item.question)

        return dispatch

    north = request(question="Show net_revenue for January 2025 in North.")
    south = request(question="Show net_revenue for January 2025 in South.")
    first = ledger.execute(north, lambda: prepare(north))
    second = ledger.execute(south, lambda: prepare(south))
    assert first.response.results[0].rows[0].value == Decimal("19.50")
    assert second.response.results[0].rows[0].value == Decimal("13.00")
    assert all(len(value["messages"]) == 1 for value in submitted)  # type: ignore[arg-type]
    assert ledger.summary()["sdk_attempts"] == {
        "local_converse_attempts": 2,
        "agentcore_invocations": 0,
        "failed_sdk_attempts": 0,
        "incomplete_sdk_attempts": 0,
    }
    assert ledger.summary()["used"] == 2


def test_failed_sdk_cannot_be_retried_even_if_a_caller_catches_it(
    tmp_path: Path, review: SharedReview
) -> None:
    ledger = SharedLedger(tmp_path, review)
    calls: list[None] = []

    class Model:
        def converse(self, **kwargs: object) -> dict[str, object]:
            calls.append(None)
            raise TimeoutError("first call failed")

    def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
        wrapped = recorder.converse(Model())
        with pytest.raises(TimeoutError):
            wrapped.converse()
        with pytest.raises(UiError, match="cannot be retried"):
            recorder.converse(Model()).converse()
        return result("local_agent", status="error")

    ledger.execute(request(), lambda: dispatch)
    assert len(calls) == 1
    assert ledger.summary()["sdk_attempts"] == {
        "local_converse_attempts": 1,
        "agentcore_invocations": 0,
        "failed_sdk_attempts": 1,
        "incomplete_sdk_attempts": 0,
    }


def test_interrupt_counts_unknown_attempt_and_preserves_rollback(
    tmp_path: Path, review: SharedReview
) -> None:
    ledger = SharedLedger(tmp_path, review)

    def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
        raise KeyboardInterrupt("operator interrupted")

    with pytest.raises(KeyboardInterrupt):
        ledger.execute(request(), lambda: dispatch)
    assert ledger.summary()["failed"]
    execute(ledger, request("live"), purpose="rollback_smoke")
    assert ledger.summary()["used"] == 2


def test_invalid_sdk_journal_fails_closed(tmp_path: Path, review: SharedReview) -> None:
    ledger = SharedLedger(tmp_path, review)
    execute(ledger, request())
    ledger.sdk_path.write_text("[]\n")
    with pytest.raises(UiError, match="SDK attempt journal is invalid"):
        ledger.summary()


@pytest.mark.parametrize(
    "damage", ["delete", "empty", "truncate-line", "drop-outcome", "edit-reservation"]
)
def test_sdk_journal_loss_or_edit_cannot_silently_zero_attempts(
    tmp_path: Path, review: SharedReview, damage: str
) -> None:
    ledger = SharedLedger(tmp_path, review)
    question = request("live")
    calls: list[str] = []

    def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
        def invoke() -> None:
            # SDK receipt and journal are already durable before this boundary.
            receipt = ledger.sdk_claims / "1-1.json"
            assert json.loads(receipt.read_text()) == events(ledger.sdk_path)[-1]
            calls.append("InvokeAgentRuntime")

        recorder.invoke_runtime(invoke)
        return result("live")

    ledger.execute(question, lambda: dispatch)
    before = ledger.path.read_bytes()
    raw = ledger.sdk_path.read_text()
    if damage == "delete":
        ledger.sdk_path.unlink()
    elif damage == "empty":
        ledger.sdk_path.write_text("")
    elif damage == "truncate-line":
        ledger.sdk_path.write_text(raw[:23])
    elif damage == "drop-outcome":
        ledger.sdk_path.write_text(raw.splitlines()[0] + "\n")
    else:
        rows = events(ledger.sdk_path)
        rows[0]["at"] = "2000-01-01T00:00:00Z"
        ledger.sdk_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(UiError):
        SharedLedger(tmp_path, review).summary()
    with pytest.raises(UiError):
        ledger.execute(request("live"), lambda: pytest.fail("integrity failure must not dispatch"))
    with pytest.raises(UiError):
        ledger.execute(question, lambda: pytest.fail("damaged evidence must not silently replay"))
    assert ledger.path.read_bytes() == before
    assert calls == ["InvokeAgentRuntime"]
    assert (ledger.sdk_claims / "1-1.json").exists()


@pytest.mark.parametrize("damage", ["delete", "edit", "extra"])
def test_sdk_receipts_must_match_journal_inventory_and_bytes(
    tmp_path: Path, review: SharedReview, damage: str
) -> None:
    ledger = SharedLedger(tmp_path, review)

    def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
        recorder.invoke_runtime(lambda: None)
        return result("live")

    ledger.execute(request("live"), lambda: dispatch)
    receipt = ledger.sdk_claims / "1-1.json"
    if damage == "delete":
        receipt.unlink()
    elif damage == "edit":
        value = json.loads(receipt.read_text())
        value["mode"] = "local_agent"
        receipt.write_text(json.dumps(value) + "\n")
    else:
        (ledger.sdk_claims / "1-2.json").write_text(receipt.read_text())
    with pytest.raises(UiError, match="SDK reservation evidence"):
        ledger.summary()


@pytest.mark.parametrize("remove_question_journal", [False, True])
def test_orphan_sdk_receipt_blocks_an_empty_question_ledger(
    tmp_path: Path, review: SharedReview, remove_question_journal: bool
) -> None:
    ledger = SharedLedger(tmp_path, review)

    def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
        recorder.invoke_runtime(lambda: None)
        return result("live")

    ledger.execute(request("live"), lambda: dispatch)
    ledger.sdk_path.unlink()
    ledger.path.write_text("")
    (ledger.claims / "1.json").unlink()
    if remove_question_journal:
        ledger.path.unlink()
    with pytest.raises(UiError, match="SDK reservation evidence"):
        ledger.summary()
    assert (ledger.sdk_claims / "1-1.json").exists()


def test_unconsumed_summary_and_zero_sdk_questions_need_no_sdk_receipts(
    tmp_path: Path, review: SharedReview
) -> None:
    ledger = SharedLedger(tmp_path, review)
    assert ledger.summary()["sdk_attempts"] == {
        "local_converse_attempts": 0,
        "agentcore_invocations": 0,
        "failed_sdk_attempts": 0,
        "incomplete_sdk_attempts": 0,
    }
    assert not ledger.directory.exists()
    question = request()
    ledger.execute(question, lambda: lambda recorder: result("local_agent", status="clarification"))
    assert ledger.summary()["used"] == 1
    assert not ledger.sdk_path.exists() and not ledger.sdk_claims.exists()


def test_receipt_survives_a_journal_append_failure_before_dispatch(
    tmp_path: Path, review: SharedReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = SharedLedger(tmp_path, review)
    original_open = __import__("os").open

    def deny_journal(path: Any, flags: int, *args: Any, **kwargs: Any) -> Any:
        if path == ledger.sdk_path:
            raise PermissionError("injected journal write failure")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("enterprise_analytics_agent.ui.shared.os.open", deny_journal)

    def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
        recorder.invoke_runtime(
            lambda: pytest.fail("journal reservation failed before SDK dispatch")
        )
        return result("live")

    with pytest.raises(PermissionError):
        ledger.execute(request("live"), lambda: dispatch)
    assert (ledger.sdk_claims / "1-1.json").is_file()
    assert not ledger.sdk_path.exists()
    with pytest.raises(UiError, match="SDK reservation evidence"):
        ledger.summary()
