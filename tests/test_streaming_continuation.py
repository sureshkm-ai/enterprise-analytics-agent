"""A continuation spends only pinned remaining quota, never a reopened parent."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.hosting.config import RuntimeSettings
from enterprise_analytics_agent.ui.model_streams import (
    StreamingLedger,
    StreamingParent,
    StreamingReview,
    StreamTarget,
)
from enterprise_analytics_agent.ui.models import UiError


@pytest.fixture(autouse=True)
def no_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("continuation preparation must not create AWS sessions")

    monkeypatch.setattr(boto3, "Session", forbidden)


def original_review() -> StreamingReview:
    settings = RuntimeSettings(
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
        principal_id="authored-streaming-application",
        tenant_id="retail_demo",
        allowed_regions=("North", "South"),
        max_iterations=5,
    )
    return StreamingReview(
        campaign_id="bedrock-stream-authored-parent",
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        artifact_sha256="a" * 64,
        artifact_bytes=12345,
        artifact_path="artifacts/authored-parent/agent.zip",
        artifact_key="releases/" + "a" * 64 + "/agent.zip",
        source_sha256="b" * 64,
        canonical_manifest_sha256=(
            "99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797"
        ),
        targets=(
            StreamTarget(
                model_key="nova-lite",
                runtime_name="enterprise_analytics_stream_nova_lite",
                settings=settings,
                template_sha256="c" * 64,
            ),
        ),
    )


def dispatch(ledger: StreamingLedger, *, cleanup: bool = False, fail: bool = False) -> None:
    with ledger.attempt(str(uuid4()), "nova-lite", mode="live", cleanup=cleanup) as record:
        record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
        record({"event": "returned", "operation": "InvokeAgentRuntime", "number": 1})
        if fail:
            record({"event": "question_failed"})


def snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def inventory_hash(files: dict[str, bytes]) -> str:
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


@pytest.fixture
def history(tmp_path: Path) -> tuple[StreamingLedger, StreamingReview, dict[str, bytes]]:
    review = original_review()
    path = tmp_path / "evaluations/parent.json"
    path.parent.mkdir()
    path.write_text(review.model_dump_json(indent=2))
    parent = StreamingLedger(tmp_path, review)
    dispatch(parent)
    dispatch(parent, fail=True)
    dispatch(parent, cleanup=True)
    (parent.directory / "acceptance-claim.json").write_text(
        json.dumps({"review_sha256": review.sha256, "at": "2026-11-12T20:00:00+00:00"})
    )
    files = snapshot(parent.directory)
    binding = StreamingParent(
        campaign_id=review.campaign_id,
        review_path="evaluations/parent.json",
        review_sha256=review.sha256,
        journal_sha256=hashlib.sha256(files["attempts.jsonl"]).hexdigest(),
        acceptance_claim_sha256=hashlib.sha256(files["acceptance-claim.json"]).hexdigest(),
        inventory_sha256=inventory_hash(files),
    )
    child = StreamingReview.model_validate(
        {
            **review.model_dump(mode="json"),
            "schema_version": "bedrock-model-stream-continuation-v1",
            "campaign_id": "bedrock-stream-authored-child",
            "maximum_attempts": 37,
            "ordinary_limit": 35,
            "parent": binding.model_dump(mode="json"),
            "artifact_sha256": "d" * 64,
            "artifact_key": "releases/" + "d" * 64 + "/agent.zip",
            "artifact_path": "artifacts/authored-child/agent.zip",
            "source_sha256": "e" * 64,
        }
    )
    return parent, child, files


def approval(review: StreamingReview) -> dict[str, object]:
    return {
        "approved": True,
        "review_sha256": review.sha256,
        "maximum_attempts": review.maximum_attempts,
        "expires_at": review.expires_at.isoformat(),
    }


@pytest.mark.parametrize(
    ("name", "digest"),
    [
        (
            "review.proposed.json",
            "cf222d7e870e0d033a5b65d4f74876a581b83f237f651c0eaa6033745b86c76d",
        ),
        (
            "review.recovery.proposed.json",
            "10433404c65249308e326a5867d499cabe4fab24c43201a6639a29c769b946c4",
        ),
    ],
)
def test_committed_v1_serialization_and_review_hashes_are_unchanged(name: str, digest: str) -> None:
    path = Path(__file__).resolve().parents[1] / "evaluations/bedrock-streaming" / name
    review = StreamingReview.model_validate_json(path.read_bytes())
    assert "parent" not in review.model_dump(mode="json")
    assert "parent" not in json.loads(review.model_dump_json())
    assert review.sha256 == digest


def test_offline_status_creates_no_child_or_claim_and_parent_is_unchanged(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, preserved = history
    child = StreamingLedger(parent.root, review)
    state = child.summary()
    assert state["used"] == 0 and state["maximum"] == 37
    assert state["prior_used"] == state["aggregate_used"] == 3
    assert state["aggregate_maximum"] == 40 and state["regular_remaining"] == 35
    assert state["protected_cleanup"] == state["unapproved_reserve"] == 1
    assert state["continuation_claimed"] is False
    assert not child.directory.exists()
    assert child.continuation_claim_path is not None
    assert not child.continuation_claim_path.exists()
    assert snapshot(parent.directory) == preserved


def test_approved_operator_claim_is_separate_and_stable_before_deployment(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, preserved = history
    child = StreamingLedger(parent.root, review)
    with pytest.raises(UiError, match="approval"):
        child.claim_continuation({})
    assert not child.directory.exists()
    child.claim_continuation(approval(review))
    path = child.continuation_claim_path
    assert path is not None and not path.is_relative_to(parent.directory)
    content = path.read_bytes()
    with pytest.raises(UiError, match="already claimed"):
        child.claim_continuation(approval(review))
    assert path.read_bytes() == content
    assert child.summary()["continuation_claimed"] is True
    assert not child.directory.exists()
    assert snapshot(parent.directory) == preserved


def test_twenty_checks_and_fifteen_questions_preserve_cleanup_and_unapproved_reserve(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, preserved = history
    child = StreamingLedger(parent.root, review)
    for _ in range(20):
        dispatch(child)
    assert child.summary()["aggregate_used"] == 23
    assert child.summary()["regular_remaining"] == 15
    for _ in range(15):
        dispatch(child)
    assert child.summary()["used"] == 35
    assert child.summary()["aggregate_used"] == 38
    before = child.path.read_bytes()
    with pytest.raises(UiError, match="allowance is closed"):
        dispatch(child)
    assert child.path.read_bytes() == before
    dispatch(child, cleanup=True)
    state = child.summary()
    assert state["used"] == 36 and state["aggregate_used"] == 39
    assert state["protected_cleanup"] == 0 and state["unapproved_reserve"] == 1
    for cleanup in (False, True):
        with pytest.raises(UiError, match="allowance is closed"):
            dispatch(child, cleanup=cleanup)
    assert snapshot(parent.directory) == preserved


def test_another_child_cannot_claim_or_spend_the_same_parent(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, preserved = history
    first = StreamingLedger(parent.root, review)
    first.claim_continuation(approval(review))
    other_review = StreamingReview.model_validate(
        {**review.model_dump(mode="json"), "campaign_id": "bedrock-stream-another-child"}
    )
    other = StreamingLedger(parent.root, other_review)
    for operation in (
        other.summary,
        lambda: other.claim_continuation(approval(other_review)),
        lambda: dispatch(other),
    ):
        with pytest.raises(UiError, match="different or damaged"):
            operation()
    assert not other.directory.exists()
    assert snapshot(parent.directory) == preserved


@pytest.mark.parametrize("kind", ["review", "journal", "claim", "receipt", "added", "missing"])
def test_parent_drift_blocks_before_child_claim_or_reservation(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]], kind: str
) -> None:
    parent, review, _ = history
    child = StreamingLedger(parent.root, review)
    if kind == "review":
        (parent.root / "evaluations/parent.json").write_text("{}")
    elif kind == "journal":
        parent.path.write_bytes(parent.path.read_bytes() + b" ")
    elif kind == "claim":
        (parent.directory / "acceptance-claim.json").write_text("{}")
    elif kind == "receipt":
        next(parent.claims.glob("*.json")).write_text("{}")
    elif kind == "added":
        (parent.directory / "unexpected.json").write_text("{}")
    else:
        parent.path.unlink()
    with pytest.raises(UiError, match="parent requires inspection"):
        dispatch(child)
    assert not child.directory.exists()
    assert child.continuation_claim_path is not None
    assert not child.continuation_claim_path.exists()


def test_parent_drift_after_question_reservation_prevents_sdk_dispatch(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, _ = history
    child = StreamingLedger(parent.root, review)
    with pytest.raises(UiError, match="parent requires inspection"):
        with child.attempt(str(uuid4()), "nova-lite", mode="live") as record:
            (parent.directory / "late-drift.json").write_text("{}")
            record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
    assert not child.sdk_claims.exists()
    assert "sdk_reserved" not in child.path.read_text()


def test_missing_global_claim_cannot_be_recreated_to_reopen_existing_child(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, _ = history
    child = StreamingLedger(parent.root, review)
    dispatch(child)
    path = child.continuation_claim_path
    assert path is not None
    path.unlink()
    before = child.path.read_bytes()
    for operation in (child.summary, lambda: dispatch(child)):
        with pytest.raises(UiError, match="claim is missing"):
            operation()
    assert child.path.read_bytes() == before
    assert not path.exists()


def test_failed_or_interrupted_child_keeps_only_one_cleanup_slot(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, preserved = history
    child = StreamingLedger(parent.root, review)
    with pytest.raises(KeyboardInterrupt):
        with child.attempt(str(uuid4()), "nova-lite", mode="live") as record:
            record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
            raise KeyboardInterrupt
    state = child.summary()
    assert state["aggregate_used"] == 4 and state["incomplete"] and state["blocked"]
    with pytest.raises(UiError):
        dispatch(child)
    dispatch(child, cleanup=True)
    assert child.summary()["aggregate_used"] == 5
    assert child.summary()["protected_cleanup"] == 0
    with pytest.raises(UiError):
        dispatch(child, cleanup=True)
    assert snapshot(parent.directory) == preserved


@pytest.mark.parametrize(
    "change",
    [
        {"maximum_attempts": 38},
        {"ordinary_limit": 36},
        {"parent": None},
        {"schema_version": "bedrock-model-stream-v1"},
        {"campaign_id": "bedrock-stream-authored-parent"},
    ],
)
def test_continuation_cannot_expand_or_disguise_its_remaining_scope(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
    change: dict[str, object],
) -> None:
    _, review, _ = history
    with pytest.raises(ValidationError):
        StreamingReview.model_validate({**review.model_dump(mode="json"), **change})


@pytest.mark.parametrize("path", ["../parent.json", "/tmp/parent.json", "./parent.json"])
def test_parent_review_path_cannot_escape_or_alias_the_checkout(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]], path: str
) -> None:
    _, review, _ = history
    assert review.parent is not None
    with pytest.raises(ValidationError):
        StreamingParent.model_validate({**review.parent.model_dump(), "review_path": path})


def test_repinning_a_failed_cleanup_does_not_make_the_parent_resumable(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, _ = history
    rows = [json.loads(line) for line in parent.path.read_text().splitlines()]
    identifier = next(
        row["request_id"]
        for row in rows
        if row["event"] == "reserved" and row["purpose"] == "cleanup"
    )
    for row in rows:
        if row["request_id"] == identifier and row["event"] == "outcome":
            row["status"] = "failed"
    parent.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert review.parent is not None
    binding = {
        **review.parent.model_dump(mode="json"),
        "journal_sha256": hashlib.sha256(parent.path.read_bytes()).hexdigest(),
        "inventory_sha256": inventory_hash(snapshot(parent.directory)),
    }
    child_review = StreamingReview.model_validate(
        {**review.model_dump(mode="json"), "parent": binding}
    )
    child = StreamingLedger(parent.root, child_review)
    with pytest.raises(UiError, match="parent requires inspection"):
        child.summary()
    assert not child.directory.exists()


@pytest.mark.parametrize("change", ["expiry", "target"])
def test_parent_limits_and_fixed_targets_are_preserved(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]], change: str
) -> None:
    parent, review, preserved = history
    payload = review.model_dump(mode="json")
    if change == "expiry":
        payload["expires_at"] = "2100-01-01T00:00:00+00:00"
    else:
        payload["targets"][0]["runtime_name"] = "enterprise_analytics_stream_other"
    child = StreamingLedger(parent.root, StreamingReview.model_validate(payload))
    with pytest.raises(UiError, match="parent requires inspection"):
        dispatch(child)
    assert not child.directory.exists()
    assert snapshot(parent.directory) == preserved


def test_changed_review_cannot_reuse_the_same_child_claim(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, _ = history
    original = StreamingLedger(parent.root, review)
    original.claim_continuation(approval(review))
    changed = StreamingReview.model_validate(
        {**review.model_dump(mode="json"), "source_sha256": "f" * 64}
    )
    child = StreamingLedger(parent.root, changed)
    with pytest.raises(UiError, match="different or damaged"):
        dispatch(child)
    assert not child.directory.exists()


def test_parent_review_symlink_is_rejected_before_creating_child_evidence(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, _ = history
    path = parent.root / "evaluations/parent.json"
    actual = path.with_name("actual.json")
    path.rename(actual)
    path.symlink_to(actual)
    child = StreamingLedger(parent.root, review)
    with pytest.raises(UiError, match="parent requires inspection"):
        dispatch(child)
    assert not child.directory.exists()


def test_expiry_never_reopens_remaining_parent_allowance(
    history: tuple[StreamingLedger, StreamingReview, dict[str, bytes]],
) -> None:
    parent, review, _ = history
    expired = StreamingReview.model_validate(
        {**review.model_dump(mode="json"), "expires_at": "2000-01-01T00:00:00+00:00"}
    )
    child = StreamingLedger(parent.root, expired)
    assert child.summary()["expired"] and not child.directory.exists()
    with pytest.raises(UiError, match="approval"):
        child.claim_continuation(approval(expired))
    with pytest.raises(UiError, match="allowance is closed"):
        dispatch(child)
    assert child.continuation_claim_path is not None
    assert not child.continuation_claim_path.exists()
