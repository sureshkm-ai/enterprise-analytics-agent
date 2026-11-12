"""Authored streaming review, exact approval and durable budgets without AWS calls."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import boto3
import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.hosting.config import RuntimeSettings
from enterprise_analytics_agent.ui.model_streams import (
    StreamingLedger,
    StreamingReleases,
    StreamingReview,
    StreamRelease,
    StreamTarget,
    verify_approval,
)
from enterprise_analytics_agent.ui.models import UiError


@pytest.fixture(autouse=True)
def forbid_aws_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("review and ledger verification must remain offline")

    monkeypatch.setattr(boto3, "Session", forbidden)


def settings() -> RuntimeSettings:
    return RuntimeSettings(
        account="453711491609",
        region="us-west-2",
        model_id="us.amazon.nova-lite-v1:0",
        query_role_arn="arn:aws:iam::453711491609:role/enterprise-analytics-dev-query-executor",
        database="enterprise_analytics_dev",
        workgroup="enterprise-analytics-dev",
        source_bucket="enterprise-analytics-dev-453711491609-us-west-2-data",
        results_bucket="enterprise-analytics-dev-453711491609-us-west-2-results",
        dataset_version="retail-v1",
        table_prefix="ea",
        reference_date="2025-04-01",
        principal_id="offline-stream-test-application",
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
        max_iterations=5,
    )


def target() -> StreamTarget:
    return StreamTarget(
        model_key="nova-lite",
        runtime_name="enterprise_analytics_stream_nova_lite",
        settings=settings(),
        template_sha256="c" * 64,
    )


@pytest.fixture
def review() -> StreamingReview:
    return StreamingReview(
        campaign_id="bedrock-stream-authored-offline",
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        artifact_sha256="a" * 64,
        artifact_bytes=12345,
        artifact_path="artifacts/bedrock-streaming/new-candidate/agent.zip",
        artifact_key="releases/" + "a" * 64 + "/agent.zip",
        source_sha256="b" * 64,
        canonical_manifest_sha256=(
            "99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797"
        ),
        targets=(target(),),
    )


def rows(ledger: StreamingLedger) -> list[dict[str, Any]]:
    return [json.loads(line) for line in ledger.path.read_text().splitlines()]


def sdk(
    record: Any,
    operation: str,
    number: int,
    *,
    failure: bool = False,
) -> None:
    record({"event": "reserved", "operation": operation, "number": number})
    record({"event": "failed" if failure else "returned", "operation": operation, "number": number})


def complete(
    ledger: StreamingLedger,
    *,
    mode: Literal["local_agent", "live"] = "live",
    cleanup: bool = False,
    identifier: str | None = None,
) -> str:
    identifier = identifier or str(uuid4())
    with ledger.attempt(identifier, "nova-lite", mode=mode, cleanup=cleanup) as record:
        sdk(record, "InvokeAgentRuntime" if mode == "live" else "Converse", 1)
    return identifier


def releases(review: StreamingReview) -> StreamingReleases:
    configuration = hashlib.sha256(
        json.dumps(review.targets[0].settings.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    return StreamingReleases(
        review_sha256=review.sha256,
        artifact_version_id="authored-returned-object-version",
        models=(
            StreamRelease(
                model_key="nova-lite",
                runtime_arn=(
                    "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
                    "enterprise_analytics_stream_nova_lite-Abc123"
                ),
                runtime_version="1",
                configuration_sha256=configuration,
                template_sha256="c" * 64,
            ),
        ),
    )


def test_review_and_status_do_not_create_a_ledger_or_touch_historical_files(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    history = tmp_path / "artifacts/ui-shared/ui-shared-retail-v1-02/question-attempts.jsonl"
    history.parent.mkdir(parents=True)
    historical_bytes = b"authored historical journal must remain unchanged\n"
    history.write_bytes(historical_bytes)
    ledger = StreamingLedger(tmp_path, review)
    initial = ledger.summary()
    assert initial["used"] == 0 and initial["regular_remaining"] == 38
    assert initial["protected_cleanup"] == initial["unapproved_reserve"] == 1
    assert not ledger.directory.exists()
    assert history.read_bytes() == historical_bytes
    complete(ledger)
    assert ledger.directory.is_relative_to(tmp_path / "artifacts/bedrock-streaming")
    assert history.read_bytes() == historical_bytes


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "another-tenant"},
        {"allowed_regions": ["North", "West"]},
        {"dataset_version": "parity-v1"},
        {"reference_date": "2025-04-02"},
        {"max_iterations": 6},
        {"max_total_tokens": 12001},
        {"model_id": "an-arbitrary-model"},
        {"query_role_arn": "arn:aws:iam::453711491609:role/another-role"},
    ],
)
def test_target_preserves_fixed_model_and_trusted_scope(changes: dict[str, object]) -> None:
    payload = settings().model_dump(mode="json")
    with pytest.raises(ValidationError):
        StreamTarget.model_validate(
            {
                "model_key": "nova-lite",
                "runtime_name": target().runtime_name,
                "template_sha256": target().template_sha256,
                "settings": {**payload, **changes},
            }
        )


def test_review_pins_artifact_budget_canonical_data_and_unique_targets(
    review: StreamingReview,
) -> None:
    for change in (
        {"maximum_attempts": 41},
        {"ordinary_limit": 39},
        {"artifact_key": "releases/unpinned/agent.zip"},
        {"canonical_manifest_sha256": "d" * 64},
        {"profile": "default"},
        {"expires_at": "2099-01-01T00:00:00"},
        {"targets": [target().model_dump(), target().model_dump()]},
    ):
        with pytest.raises(ValidationError):
            StreamingReview.model_validate({**review.model_dump(mode="json"), **change})


def test_approval_requires_exact_explicit_scope_not_an_enabled_toggle(
    review: StreamingReview,
) -> None:
    now = datetime(2026, 11, 11, tzinfo=UTC)
    approval = {
        "review_sha256": review.sha256,
        "approved": True,
        "maximum_attempts": 40,
        "expires_at": review.expires_at.isoformat(),
    }
    verify_approval(review, approval, now=now)
    for invalid in (
        None,
        True,
        {"allow_live": True},
        {**approval, "approved": "true"},
        {**approval, "review_sha256": "e" * 64},
        {**approval, "maximum_attempts": 41},
        {**approval, "expires_at": "2099-01-02T00:00:00+00:00"},
    ):
        with pytest.raises(UiError):
            verify_approval(review, invalid, now=now)
    with pytest.raises(UiError):
        verify_approval(review, approval, now=review.expires_at)


def test_actual_release_records_require_exact_configuration_and_target_binding(
    review: StreamingReview,
) -> None:
    actual = releases(review)
    actual.validate_review(review)
    changes: tuple[dict[str, Any], ...] = (
        {"review_sha256": "f" * 64},
        {"models": []},
        {"models": actual.models * 2},
        {"models": [actual.models[0].model_copy(update={"configuration_sha256": "d" * 64})]},
        {"models": [actual.models[0].model_copy(update={"template_sha256": "d" * 64})]},
        {
            "models": [
                actual.models[0].model_copy(
                    update={
                        "runtime_arn": "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
                        "enterprise_analytics_stream_other-Abc123"
                    }
                )
            ]
        },
    )
    for change in changes:
        modified = StreamingReleases.model_validate({**actual.model_dump(), **change})
        with pytest.raises(UiError):
            modified.validate_review(review)


def test_all_38_ordinary_slots_and_one_cleanup_leave_40th_unapproved(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    for _ in range(38):
        complete(ledger)
    state = ledger.summary()
    assert state["used"] == 38 and state["regular_remaining"] == 0
    assert state["protected_cleanup"] == 1 and state["unapproved_reserve"] == 1
    before = ledger.path.read_bytes()
    with pytest.raises(UiError, match="allowance is closed"):
        complete(ledger)
    assert ledger.path.read_bytes() == before
    complete(ledger, cleanup=True)
    state = ledger.summary()
    assert state["used"] == 39 and state["protected_cleanup"] == 0
    assert state["unapproved_reserve"] == 1
    before = ledger.path.read_bytes()
    for cleanup in (False, True):
        with pytest.raises(UiError, match="allowance is closed"):
            complete(ledger, cleanup=cleanup)
    assert ledger.path.read_bytes() == before


def test_failure_stays_spent_and_cleanup_is_once_only(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    with pytest.raises(RuntimeError, match="authored operation failure"):
        with ledger.attempt(str(uuid4()), "nova-lite", mode="local_agent") as record:
            sdk(record, "Converse", 1, failure=True)
            raise RuntimeError("authored operation failure")
    assert ledger.summary()["used"] == 1 and ledger.summary()["failed"] is True
    with pytest.raises(UiError):
        complete(ledger)
    complete(ledger, cleanup=True)
    assert ledger.summary()["used"] == 2 and ledger.summary()["protected_cleanup"] == 0
    with pytest.raises(UiError):
        complete(ledger, cleanup=True)


def test_interruption_is_spent_and_cannot_fund_an_ordinary_replay(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    interruption = KeyboardInterrupt("offline interrupted attempt")
    with pytest.raises(KeyboardInterrupt) as caught:
        with ledger.attempt(str(uuid4()), "nova-lite", mode="local_agent") as record:
            record({"event": "reserved", "operation": "Converse", "number": 1})
            raise interruption
    assert caught.value is interruption
    state = ledger.summary()
    assert state["used"] == 1 and state["failed"] and state["incomplete"] and state["blocked"]
    with pytest.raises(UiError):
        complete(ledger)
    complete(ledger, cleanup=True)
    assert ledger.summary()["used"] == 2 and ledger.summary()["protected_cleanup"] == 0


def test_another_question_is_rejected_instead_of_queued(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    with ledger.attempt(str(uuid4()), "nova-lite", mode="live") as record:
        before = ledger.path.read_bytes()
        with pytest.raises(UiError, match="Another streaming question"):
            complete(StreamingLedger(tmp_path, review))
        assert ledger.path.read_bytes() == before
        sdk(record, "InvokeAgentRuntime", 1)
    assert ledger.summary()["used"] == 1


def test_failed_sdk_cannot_reserve_an_automatic_retry(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    with pytest.raises(UiError):
        with ledger.attempt(str(uuid4()), "nova-lite", mode="local_agent") as record:
            sdk(record, "Converse", 1, failure=True)
            record({"event": "reserved", "operation": "Converse", "number": 2})
    starts = [row for row in rows(ledger) if row["event"] == "sdk_reserved"]
    assert len(starts) == 1 and starts[0]["number"] == 1
    assert ledger.summary()["failed"] is True


def test_sdk_numbers_and_mode_binding_cannot_add_a_retry(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    with ledger.attempt(str(uuid4()), "nova-lite", mode="local_agent") as record:
        for number in range(1, 6):
            sdk(record, "Converse", number)
        sdk(record, "ConverseStream", 6)
    assert len([row for row in rows(ledger) if row["event"] == "sdk_reserved"]) == 6
    with pytest.raises(UiError):
        with ledger.attempt(str(uuid4()), "nova-lite", mode="live") as record:
            sdk(record, "InvokeAgentRuntime", 1)
            sdk(record, "InvokeAgentRuntime", 2)


def test_duplicate_request_id_does_not_write_or_dispatch_twice(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    identifier = complete(ledger)
    before = ledger.path.read_bytes()
    with pytest.raises((UiError, FileExistsError)):
        complete(ledger, identifier=identifier)
    assert ledger.path.read_bytes() == before
    assert ledger.summary()["used"] == 1


def test_missing_journal_or_modified_receipt_cannot_restart_budget(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    identifier = complete(ledger)
    journal = ledger.path.read_bytes()
    ledger.path.unlink()
    with pytest.raises(UiError, match="journal is missing"):
        ledger.summary()
    ledger.path.write_bytes(journal)
    receipt = ledger.claims / f"{identifier}.json"
    value = json.loads(receipt.read_bytes())
    receipt.write_text(json.dumps({**value, "model_key": "unreviewed"}))
    with pytest.raises(UiError, match="receipt differs"):
        ledger.summary()


def test_sdk_history_removal_cannot_reopen_the_same_sdk_number(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    with pytest.raises(UiError):
        with ledger.attempt(str(uuid4()), "nova-lite", mode="local_agent") as record:
            sdk(record, "Converse", 1)
            # Removing SDK journal rows must not erase its independent reservations.
            kept = [row for row in rows(ledger) if not row["event"].startswith("sdk_")]
            ledger.path.write_text("".join(json.dumps(row) + "\n" for row in kept))
            record({"event": "reserved", "operation": "Converse", "number": 1})


def test_outcome_before_its_reservation_is_invalid_history(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    complete(ledger)
    existing = rows(ledger)
    outcome = next(row for row in existing if row["event"] == "outcome")
    others = [row for row in existing if row is not outcome]
    ledger.path.write_text("".join(json.dumps(row) + "\n" for row in [outcome, *others]))
    with pytest.raises(UiError):
        ledger.summary()


def test_finished_callback_cannot_rewrite_a_completed_journal(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    with ledger.attempt(str(uuid4()), "nova-lite", mode="local_agent") as record:
        sdk(record, "Converse", 1)
    before = ledger.path.read_bytes()
    with pytest.raises(UiError):
        record({"event": "reserved", "operation": "Converse", "number": 2})
    assert ledger.path.read_bytes() == before
    assert ledger.summary()["incomplete"] is False


def test_expired_review_is_rejected_without_reserving_an_attempt(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    expired = StreamingReview.model_validate(
        {**review.model_dump(), "expires_at": datetime(2020, 1, 1, tzinfo=UTC)}
    )
    ledger = StreamingLedger(tmp_path, expired)
    assert ledger.summary()["expired"] is True
    with pytest.raises(UiError, match="allowance is closed"):
        complete(ledger)
    assert not ledger.path.exists() and not ledger.claims.exists()


def test_aliased_evidence_paths_cannot_write_outside_the_campaign(
    tmp_path: Path,
    review: StreamingReview,
) -> None:
    outside = tmp_path / "unrelated"
    outside.mkdir()
    ledger = StreamingLedger(tmp_path, review)
    ledger.directory.parent.mkdir(parents=True)
    ledger.directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(UiError, match="must not be aliased"):
        complete(ledger)
    assert list(outside.iterdir()) == []
