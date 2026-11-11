"""New proposed allowance accounting against immutable synthetic parent evidence."""

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.retail_evaluation.full_live import (
    PARENT_REVIEW_SHA256,
    RUNTIME_ARN,
    FullLiveBudget,
    FullLiveBudgetError,
    FullLiveContinuationReview,
    FullLivePhase,
    FullLiveReview,
    validate_parent_preservation,
)

NOW = datetime(2026, 11, 11, 18, tzinfo=UTC)
PARENT_REVIEW = Path(__file__).resolve().parents[1] / "evaluations/full-live/review.proposed.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(
    budget: FullLiveBudget,
    phase: FullLivePhase = "agent_parity",
    *,
    transport: Any = lambda: {"accepted": True},
) -> Any:
    return budget.call(
        phase,
        "bedrock-agentcore",
        "InvokeAgentRuntime",
        {
            "agentRuntimeArn": RUNTIME_ARN,
            "qualifier": "DEFAULT",
            "runtimeSessionId": "3391f160-3208-4e34-839f-40b6c9015720",
            "payload": b'{"question":"Show net_revenue for January 2025."}',
        },
        transport,
    )


@pytest.fixture(scope="module")
def frozen_parent(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build fake SDK receipts once; no actual data or AWS clients are involved."""
    root = tmp_path_factory.mktemp("full-live-parent")
    path = root / "evaluations/full-live/review.proposed.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(PARENT_REVIEW.read_bytes())
    original = FullLiveReview.model_validate_json(path.read_bytes())
    assert original.sha256 == PARENT_REVIEW_SHA256
    budget = FullLiveBudget(original, repository_root=root, now=lambda: NOW)
    for _ in range(67):
        budget.call(
            "athena_parity",
            "athena",
            "StartQueryExecution",
            {"WorkGroup": "enterprise-analytics-dev"},
            lambda: {"QueryExecutionId": "fake-query"},
        )
    for _ in range(36):
        invoke(budget, "retail")
    invoke(budget, "restoration_smoke")
    (budget.directory / "execution-claim.json").write_text('{"test_claim":true}\n')
    files = [*budget.directory.rglob("*"), budget.sdk_claim, path]
    inventory = {
        "roots": ["artifacts/full-live/full-live-v1"],
        "parent_review_sha256": original.sha256,
        "runtime_used": 37,
        "direct_athena_submissions": 67,
        "files": {
            str(file.relative_to(root)): {
                "sha256": digest(file),
                "size_bytes": file.stat().st_size,
            }
            for file in files
            if file.is_file()
        },
    }
    inventory_path = root / "artifacts/full-live/verification/failed-run-preservation.json"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n")
    return root


@pytest.fixture
def parent_root(tmp_path: Path, frozen_parent: Path) -> Path:
    shutil.copytree(frozen_parent, tmp_path, dirs_exist_ok=True)
    return tmp_path


def review(root: Path, **changes: Any) -> FullLiveContinuationReview:
    return FullLiveContinuationReview.model_validate(
        {
            "parity_template_sha256": "b" * 64,
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
            "parent_inventory_sha256": digest(
                root / "artifacts/full-live/verification/failed-run-preservation.json"
            ),
            "prepared_inventory_sha256": "c" * 64,
            **changes,
        }
    )


def budget(root: Path, **changes: Any) -> FullLiveBudget:
    return FullLiveBudget(review(root, **changes), repository_root=root, now=lambda: NOW)


def parent_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "artifacts/full-live/full-live-v1").rglob("*")
        if path.is_file()
    }


def test_unused_new_allowance_preserves_closed_parent_and_creates_nothing(
    parent_root: Path,
) -> None:
    before = parent_bytes(parent_root)
    selected = budget(parent_root)
    result = selected.summary()
    assert result["runtime_used"] == result["direct_athena_submissions"] == 0
    assert result["runtime_remaining"] == result["runtime_maximum"] == 20
    assert result["prior_runtime_invocations"] == result["aggregate_runtime_used"] == 37
    assert result["aggregate_runtime_maximum"] == 57
    assert result["aggregate_runtime_remaining"] == 20
    assert result["phase_remaining"] == {
        "athena_parity": 0,
        "agent_parity": 19,
        "retail": 0,
        "restoration_smoke": 1,
    }
    assert not selected.directory.exists() and not selected.sdk_claim.exists()
    assert parent_bytes(parent_root) == before


@pytest.mark.parametrize(
    "change",
    [
        {"campaign_id": "full-live-v1"},
        {"profile": "default"},
        {"region": "us-east-1"},
        {"starting_runtime_version": "14"},
        {"maximum_runtime_invocations": 21},
        {"maximum_direct_athena_submissions": 1},
        {"retail_invocations": 1},
        {"agent_parity_invocations": 20},
        {"protected_restoration_invocations": 0},
        {"prior_runtime_invocations": 36},
        {"aggregate_runtime_maximum": 56},
        {"parent_review_sha256": "a" * 64},
        {"parent_inventory_sha256": "0" * 64},
        {"prepared_inventory_sha256": "0" * 64},
        {"artifact_version_id": "new-object-version"},
        {"expires_at": "2026-11-13T23:59:00"},
    ],
)
def test_review_rejects_reopened_parent_or_unreviewed_scope(
    parent_root: Path, change: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        review(parent_root, **change)


def test_copied_review_cannot_bypass_strict_validation(parent_root: Path) -> None:
    changed = review(parent_root).model_copy(update={"maximum_runtime_invocations": 999})
    with pytest.raises(ValidationError):
        FullLiveBudget(changed, repository_root=parent_root)
    assert not (parent_root / "artifacts/full-live/full-live-continuation-v1").exists()


def test_twenty_calls_include_protected_smoke_and_aggregate_57(parent_root: Path) -> None:
    before = parent_bytes(parent_root)
    selected = budget(parent_root)
    for _ in range(19):
        invoke(selected)
    with pytest.raises(FullLiveBudgetError, match="phase allowance"):
        invoke(selected)
    assert selected.summary()["aggregate_runtime_used"] == 56
    assert selected.summary()["runtime_remaining"] == 1
    invoke(selected, "restoration_smoke")
    assert selected.summary()["runtime_used"] == 20
    assert selected.summary()["aggregate_runtime_used"] == 57
    assert selected.summary()["ordinary_blocked"] is True
    assert selected.summary()["runtime_remaining"] == 0
    with pytest.raises(FullLiveBudgetError, match="closed"):
        invoke(selected, "restoration_smoke")
    assert parent_bytes(parent_root) == before


@pytest.mark.parametrize("phase", ["athena_parity", "retail"])
def test_completed_cohorts_have_no_continuation_allowance(
    parent_root: Path, phase: FullLivePhase
) -> None:
    selected = budget(parent_root)
    with pytest.raises(FullLiveBudgetError, match="phase allowance"):
        if phase == "athena_parity":
            selected.call(
                phase,
                "athena",
                "StartQueryExecution",
                {"WorkGroup": "enterprise-analytics-dev"},
                lambda: pytest.fail("must not dispatch"),
            )
        else:
            invoke(selected, phase, transport=lambda: pytest.fail("must not dispatch"))
    assert selected.summary()["runtime_used"] == 0
    assert selected.summary()["direct_athena_submissions"] == 0


@pytest.mark.parametrize(
    "relative",
    [
        "artifacts/full-live/full-live-v1/sdk-attempts.jsonl",
        "artifacts/full-live/full-live-v1/reservations/1.json",
        "artifacts/full-live/full-live-v1/execution-claim.json",
        "artifacts/full-live/full-live-v1.sdk-claim.json",
        "evaluations/full-live/review.proposed.json",
    ],
)
def test_preservation_rejects_changed_or_missing_parent_evidence(
    parent_root: Path, relative: str
) -> None:
    selected = review(parent_root)
    path = parent_root / relative
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(FullLiveBudgetError, match="parent preservation"):
        FullLiveBudget(selected, repository_root=parent_root)
    path.unlink()
    with pytest.raises(FullLiveBudgetError, match="parent preservation"):
        FullLiveBudget(selected, repository_root=parent_root)


def test_parent_new_file_is_not_silently_ignored(parent_root: Path) -> None:
    selected = review(parent_root)
    (parent_root / "artifacts/full-live/full-live-v1/another-claim.json").write_text("{}\n")
    with pytest.raises(FullLiveBudgetError, match="parent preservation"):
        validate_parent_preservation(selected, parent_root)


def test_rehashed_inventory_claim_cannot_replace_actual_closed_parent_usage(
    parent_root: Path,
) -> None:
    directory = parent_root / "artifacts/full-live/full-live-v1"
    ledger = directory / "sdk-attempts.jsonl"
    lines = ledger.read_text().splitlines(keepends=True)
    # Remove the final fake smoke pair and receipt, keeping a self-consistent ledger
    # with36 Runtime calls. An inventory claiming37 cannot turn that into evidence.
    ledger.write_text("".join(lines[:-2]))
    receipt = directory / "reservations/104.json"
    receipt.unlink()
    inventory_path = parent_root / "artifacts/full-live/verification/failed-run-preservation.json"
    inventory = json.loads(inventory_path.read_bytes())
    inventory["files"].pop(str(receipt.relative_to(parent_root)))
    inventory["files"][str(ledger.relative_to(parent_root))] = {
        "size_bytes": ledger.stat().st_size,
        "sha256": digest(ledger),
    }
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n")
    with pytest.raises(FullLiveBudgetError, match="parent preservation"):
        budget(parent_root)


@pytest.mark.parametrize("field", ["roots", "runtime_used", "direct_athena_submissions"])
def test_new_inventory_hash_does_not_allow_unreviewed_parent_scope(
    parent_root: Path, field: str
) -> None:
    path = parent_root / "artifacts/full-live/verification/failed-run-preservation.json"
    inventory = json.loads(path.read_bytes())
    inventory[field] = [] if field == "roots" else 999
    path.write_text(json.dumps(inventory) + "\n")
    with pytest.raises(FullLiveBudgetError, match="parent preservation"):
        budget(parent_root)


def test_aliased_inventory_is_rejected(parent_root: Path) -> None:
    selected = review(parent_root)
    path = parent_root / "artifacts/full-live/verification/failed-run-preservation.json"
    elsewhere = parent_root / "inventory-copy.json"
    elsewhere.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(elsewhere)
    with pytest.raises(FullLiveBudgetError, match="parent preservation"):
        FullLiveBudget(selected, repository_root=parent_root)


def test_parent_alias_is_rejected_even_with_identical_bytes(parent_root: Path) -> None:
    selected = review(parent_root)
    path = parent_root / "artifacts/full-live/full-live-v1/reservations/1.json"
    elsewhere = parent_root / "receipt-copy.json"
    elsewhere.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(elsewhere)
    with pytest.raises(FullLiveBudgetError, match="parent preservation"):
        budget(parent_root)
    assert selected.parent_inventory_sha256 == review(parent_root).parent_inventory_sha256


def test_parent_is_rechecked_before_each_dispatch_and_summary(parent_root: Path) -> None:
    selected = budget(parent_root)
    invoke(selected)
    path = parent_root / "artifacts/full-live/full-live-v1/execution-claim.json"
    path.write_text("{}\n")
    with pytest.raises(FullLiveBudgetError, match="parent preservation"):
        invoke(selected, transport=lambda: pytest.fail("must not dispatch"))
    with pytest.raises(FullLiveBudgetError, match="parent preservation"):
        selected.summary()
    assert len(list(selected.claims.iterdir())) == 1


def test_failed_invocation_is_spent_without_retry_and_smoke_remains(parent_root: Path) -> None:
    selected = budget(parent_root)
    dispatched = []

    def failure() -> None:
        dispatched.append(True)
        raise ConnectionError("uncertain delivery")

    with pytest.raises(ConnectionError):
        invoke(selected, transport=failure)
    assert dispatched == [True]
    with pytest.raises(FullLiveBudgetError, match="blocked"):
        invoke(selected)
    assert selected.summary()["runtime_used"] == 1
    assert selected.summary()["aggregate_runtime_used"] == 38
    assert selected.summary()["phase_remaining"] == {
        "athena_parity": 0,
        "agent_parity": 18,
        "retail": 0,
        "restoration_smoke": 1,
    }
    invoke(selected, "restoration_smoke")
    assert selected.summary()["runtime_used"] == 2
    assert selected.summary()["failed"] is True


def test_missing_new_ledger_never_resets_claimed_usage(parent_root: Path) -> None:
    selected = budget(parent_root)
    invoke(selected)
    selected.path.unlink()
    reopened = budget(parent_root)
    with pytest.raises(FullLiveBudgetError, match="ledger missing"):
        reopened.summary()
    with pytest.raises(FullLiveBudgetError):
        invoke(reopened)


def test_changed_new_review_cannot_start_duplicate_sdk_claim(parent_root: Path) -> None:
    selected = budget(parent_root)
    invoke(selected)
    changed = budget(parent_root, prepared_inventory_sha256="d" * 64)
    with pytest.raises(FullLiveBudgetError, match="ledger/receipts"):
        changed.summary()
    with pytest.raises(FullLiveBudgetError):
        invoke(changed)


def test_expiry_blocks_new_calls_without_writing_ledger(parent_root: Path) -> None:
    selected = FullLiveBudget(
        review(parent_root, expires_at=NOW), repository_root=parent_root, now=lambda: NOW
    )
    with pytest.raises(FullLiveBudgetError, match="expired"):
        invoke(selected)
    with pytest.raises(FullLiveBudgetError, match="expired"):
        invoke(selected, "restoration_smoke")
    assert not selected.directory.exists()
