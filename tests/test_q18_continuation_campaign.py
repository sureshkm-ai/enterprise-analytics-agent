"""Authored closed-parent histories prove continuation identity and the shared hard cap."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.retail_evaluation.campaign import (
    CODE_SHA256,
    CODE_VERSION,
    CONTINUATION_LEDGER,
    CampaignError,
    CampaignLedger,
    ContinuationCampaignBinding,
    RepairCampaignBinding,
    RestorationProof,
)
from enterprise_analytics_agent.retail_evaluation.deployment import canonical_hash
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    ContinuationReview,
    RepairReview,
    ReviewedStartingCheckpoint,
    require_starting_checkpoint,
    select_continuation,
)

RUNTIME = (
    "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
    "enterprise_analytics_dev_agent-HlWywlG60h"
)


def make_continuation_fixture(
    root: Path,
    *,
    repair_review: RepairReview | None = None,
    candidate_version: CandidateVersionBinding | None = None,
    proof: RestorationProof | None = None,
) -> tuple[RepairReview, CandidateVersionBinding, ContinuationReview, CampaignLedger]:
    """A tiny authored parent, not the real ignored ledger or production calculation.

    Workflow tests may supply their existing authored review/SDK fixture so both
    paths exercise the same strict identity instead of stubbing budget validation.
    """
    now = datetime.now(UTC)
    selected = repair_review or RepairReview(
        candidate_artifact_path="artifacts/milestone-5/q18-repair-v1/candidate/agent.zip",
        candidate_assembly_path="artifacts/milestone-5/q18-repair-v1/cdk.candidate.out",
        candidate_sha256="a" * 64,
        candidate_template_sha256="b" * 64,
        questions_sha256="c" * 64,
        expected_results_sha256="d" * 64,
        source_patch_sha256="e" * 64,
    )
    version = candidate_version or CandidateVersionBinding(
        review_sha256=selected.review_sha256,
        candidate_sha256=selected.candidate_sha256,
        candidate_template_sha256=selected.candidate_template_sha256,
        bucket="enterprise-analytics-dev-453711491609-us-west-2-agent-code",
        key=f"releases/{selected.candidate_sha256}/agent.zip",
        version_id="authored-immutable-version",
        checksum_sha256=selected.candidate_sha256,
        size_bytes=3,
        verified_at=now,
    )
    parent_binding = RepairCampaignBinding(
        campaign_id=selected.campaign_id,
        ledger_path=selected.ledger_path,
        maximum=40,
        review_sha256=selected.review_sha256,
        candidate_sha256=selected.candidate_sha256,
        candidate_template_sha256=selected.candidate_template_sha256,
        candidate_version_record_sha256=canonical_hash(version.model_dump(mode="json")),
    )
    original = proof or RestorationProof(
        observed_at=now,
        runtime_arn=RUNTIME,
        runtime_status="READY",
        endpoint_status="READY",
        runtime_version="8",
        endpoint_version="8",
        dataset_version="parity-v1",
        tenant_id="t1",
        allowed_regions=("North", "South"),
        reference_date=date(2025, 2, 1),
        configuration_sha256="1" * 64,
        expected_configuration_sha256="1" * 64,
        template_sha256="2" * 64,
        expected_template_sha256="2" * 64,
        code_sha256=CODE_SHA256,
        code_version_id=CODE_VERSION,
        resource_policies_verified=True,
        retention_days=7,
    )
    parent = CampaignLedger(binding=parent_binding, repository_root=root)
    reservation = parent.reserve(
        purpose="restoration_smoke",
        question="authored parity smoke",
        session_id="parent-session",
        runtime_arn=RUNTIME,
        restoration_proof=original,
    )
    parent.finish(reservation, outcome="answer", elapsed_ms=1)
    checkpoint = ReviewedStartingCheckpoint(
        runtime_arn=RUNTIME,
        configuration_sha256=original.configuration_sha256,
        template_sha256=original.template_sha256,
        source_proof_sha256=hashlib.sha256(original.model_dump_json().encode()).hexdigest(),
    )
    continuation = ContinuationReview(
        repair_review_sha256=selected.review_sha256,
        parent_ledger_sha256=hashlib.sha256(parent.path.read_bytes()).hexdigest(),
        parent_binding=parent_binding,
        candidate_sha256=version.candidate_sha256,
        candidate_template_sha256=version.candidate_template_sha256,
        candidate_version_id=version.version_id,
        candidate_version_record_sha256=canonical_hash(version.model_dump(mode="json")),
        starting_checkpoint=checkpoint,
    )
    ledger = CampaignLedger(
        binding=continuation.campaign_binding(selected, version), repository_root=root
    )
    return selected, version, continuation, ledger


def dispatch(ledger: CampaignLedger) -> None:
    ledger.reserve(purpose="case", question="a", session_id="s", runtime_arn=RUNTIME)


def test_continuation_starts_without_creating_ledger_or_modifying_closed_parent(
    tmp_path: Path,
) -> None:
    _, _, review, ledger = make_continuation_fixture(tmp_path)
    parent = tmp_path / review.parent_binding.ledger_path
    before = parent.read_bytes()
    summary = ledger.summary()
    assert summary["used"] == 0 and summary["maximum"] == 39
    assert summary["aggregate_used"] == 1 and summary["aggregate_remaining"] == 39
    assert summary["aggregate_maximum"] == 40
    assert not ledger.path.exists() and not ledger.attempt_path.exists()
    assert parent.read_bytes() == before


def test_claim_prevents_duplicate_candidate_attempt_even_with_no_calls(tmp_path: Path) -> None:
    _, _, _, ledger = make_continuation_fixture(tmp_path)
    with pytest.raises(CampaignError, match="no valid deployment attempt"):
        dispatch(ledger)
    claim = ledger.claim_attempt({"original_runtime_version": "8"})
    before = ledger.attempt_path.read_bytes()
    assert ledger.require_attempt() == claim
    assert ledger.summary()["used"] == 0
    with pytest.raises(CampaignError, match="already claimed"):
        ledger.claim_attempt()
    assert ledger.attempt_path.read_bytes() == before
    assert not ledger.path.exists()


def test_concurrent_claims_allow_only_one_candidate_attempt(tmp_path: Path) -> None:
    selected, version, review, _ = make_continuation_fixture(tmp_path)
    binding = review.campaign_binding(selected, version)

    def claim(_: int) -> bool:
        try:
            CampaignLedger(binding=binding, repository_root=tmp_path).claim_attempt()
            return True
        except CampaignError:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(claim, range(12)))
    assert results.count(True) == 1


def test_aggregate_cap_counts_incomplete_calls_and_keeps_last_for_restoration(
    tmp_path: Path,
) -> None:
    _, _, review, ledger = make_continuation_fixture(tmp_path)
    parent = tmp_path / review.parent_binding.ledger_path
    before = parent.read_bytes()
    ledger.claim_attempt()
    for _ in range(38):
        dispatch(ledger)
    summary = ledger.summary()
    assert summary["used"] == summary["incomplete_reservations"] == 38
    assert summary["aggregate_used"] == 39 and summary["aggregate_remaining"] == 1
    with pytest.raises(CampaignError, match="budget"):
        dispatch(ledger)
    now = datetime.now(UTC)
    proof = RestorationProof.model_validate(
        {
            **review.starting_checkpoint.model_dump(mode="json", exclude={"source_proof_sha256"}),
            "observed_at": now,
            "runtime_status": "READY",
            "endpoint_status": "READY",
            "expected_configuration_sha256": review.starting_checkpoint.configuration_sha256,
            "expected_template_sha256": review.starting_checkpoint.template_sha256,
        }
    )
    reservation = ledger.reserve(
        purpose="restoration_smoke",
        question="parity",
        session_id="s",
        runtime_arn=RUNTIME,
        restoration_proof=proof,
    )
    ledger.finish(reservation, outcome="answer", elapsed_ms=1)
    summary = ledger.summary()
    assert summary["used"] == 39 and summary["aggregate_used"] == 40
    assert summary["aggregate_remaining"] == 0 and summary["retail_closed"] is True
    with pytest.raises(CampaignError, match="budget"):
        ledger.reserve(
            purpose="restoration_smoke",
            question="again",
            session_id="s",
            runtime_arn=RUNTIME,
            restoration_proof=proof,
        )
    assert parent.read_bytes() == before


@pytest.mark.parametrize("action", ["summary", "reserve", "finish", "claim"])
def test_parent_drift_blocks_every_operation_without_touching_history(
    tmp_path: Path, action: str
) -> None:
    _, _, review, ledger = make_continuation_fixture(tmp_path)
    ledger.claim_attempt()
    reservation = ledger.reserve(purpose="case", question="q", session_id="s", runtime_arn=RUNTIME)
    parent = tmp_path / review.parent_binding.ledger_path
    parent.write_bytes(parent.read_bytes() + b"\n")
    tampered = parent.read_bytes()
    child_before = ledger.path.read_bytes()
    with pytest.raises(CampaignError, match="parent ledger hash"):
        if action == "summary":
            ledger.summary()
        elif action == "reserve":
            dispatch(ledger)
        elif action == "finish":
            ledger.finish(reservation, outcome="answer", elapsed_ms=1)
        else:
            ledger.claim_attempt()
    assert parent.read_bytes() == tampered
    assert ledger.path.read_bytes() == child_before


def test_missing_parent_is_not_created_and_historical_paths_cannot_be_reused(
    tmp_path: Path,
) -> None:
    _, _, review, ledger = make_continuation_fixture(tmp_path)
    parent = tmp_path / review.parent_binding.ledger_path
    parent.unlink()
    with pytest.raises(CampaignError, match="unavailable"):
        ledger.summary()
    assert not parent.exists() and not ledger.path.exists()
    for path in [
        review.parent_binding.ledger_path,
        "artifacts/milestone-5/runtime-invocations.jsonl",
    ]:
        with pytest.raises(CampaignError, match="reuse or redirect"):
            CampaignLedger(tmp_path / path, binding=ledger.binding, repository_root=tmp_path)
    with pytest.raises(CampaignError, match="explicitly pinned"):
        CampaignLedger(tmp_path / CONTINUATION_LEDGER)


@pytest.mark.parametrize("field", ["maximum", "prior_used", "aggregate_maximum"])
def test_continuation_cannot_expand_the_shared_allowance(tmp_path: Path, field: str) -> None:
    _, _, _, ledger = make_continuation_fixture(tmp_path)
    assert isinstance(ledger.binding, ContinuationCampaignBinding)
    value = ledger.binding.model_dump(mode="json")
    value[field] = 41
    with pytest.raises(ValidationError):
        ContinuationCampaignBinding.model_validate(value)


def test_v8_starting_checkpoint_rejects_stale_version_and_wrong_original_scope(
    tmp_path: Path,
) -> None:
    selected, _, review, _ = make_continuation_fixture(tmp_path)
    proof = RestorationProof.model_validate(
        {
            **review.starting_checkpoint.model_dump(mode="json", exclude={"source_proof_sha256"}),
            "observed_at": datetime.now(UTC),
            "runtime_status": "READY",
            "endpoint_status": "READY",
            "expected_configuration_sha256": review.starting_checkpoint.configuration_sha256,
            "expected_template_sha256": review.starting_checkpoint.template_sha256,
        }
    )
    require_starting_checkpoint(proof, selected, review)
    for change in [
        {"runtime_version": "6", "endpoint_version": "6"},
        {"runtime_version": "9", "endpoint_version": "9"},
        {"configuration_sha256": "f" * 64, "expected_configuration_sha256": "f" * 64},
        {"template_sha256": "f" * 64, "expected_template_sha256": "f" * 64},
        {"runtime_arn": "other-runtime"},
    ]:
        with pytest.raises(ValueError, match="v8 continuation"):
            require_starting_checkpoint(proof.model_copy(update=change), selected, review)


def test_explicit_selection_checks_parent_and_candidate_without_sdk_or_creating_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected, version, review, ledger = make_continuation_fixture(tmp_path)
    directory = tmp_path / "evaluations/retail-v1"
    directory.mkdir(parents=True)
    (directory / "q18-repair-review.json").write_text(selected.model_dump_json())
    (directory / "q18-continuation-review.json").write_text(review.model_dump_json())
    version_path = tmp_path / "version.json"
    version_path.write_text(version.model_dump_json())
    monkeypatch.setattr("boto3.Session", lambda **kwargs: pytest.fail("offline selection used AWS"))
    actual = select_continuation("q18-continuation-v1", version_path, repository_root=tmp_path)
    assert actual[0] == selected and actual[1] == version and actual[3] == review
    assert not ledger.path.exists() and not ledger.attempt_path.exists()
    changed = version.model_copy(update={"version_id": "another-immutable-version"})
    version_path.write_text(changed.model_dump_json())
    with pytest.raises(ValueError, match="existing reviewed candidate"):
        select_continuation("q18-continuation-v1", version_path, repository_root=tmp_path)


@pytest.mark.parametrize("seconds", [-1, 301])
def test_historical_or_future_observation_cannot_authorize_v8(tmp_path: Path, seconds: int) -> None:
    from datetime import timedelta

    _, _, review, _ = make_continuation_fixture(tmp_path)
    now = datetime.now(UTC)
    proof = RestorationProof.model_validate(
        {
            **review.starting_checkpoint.model_dump(mode="json", exclude={"source_proof_sha256"}),
            "observed_at": now - timedelta(seconds=seconds),
            "runtime_status": "READY",
            "endpoint_status": "READY",
            "expected_configuration_sha256": review.starting_checkpoint.configuration_sha256,
            "expected_template_sha256": review.starting_checkpoint.template_sha256,
        }
    )
    with pytest.raises(ValueError, match="fresh original checkpoint"):
        review.starting_checkpoint.require_proof(proof, now=now)


def test_candidate_parent_identity_and_attempt_binding_cannot_be_substituted(
    tmp_path: Path,
) -> None:
    selected, version, review, ledger = make_continuation_fixture(tmp_path)
    with pytest.raises(ValueError, match="existing reviewed candidate"):
        review.campaign_binding(
            selected, version.model_copy(update={"version_id": "replacement-version"})
        )
    ledger.claim_attempt()
    original = ledger.attempt_path.read_bytes()
    ledger.attempt_path.write_bytes(original.replace(review.review_sha256.encode(), b"f" * 64))
    with pytest.raises(CampaignError, match="attempt binding differs"):
        dispatch(ledger)
    assert not ledger.path.exists()


def test_parent_reads_use_no_write_or_create_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    _, _, review, ledger = make_continuation_fixture(tmp_path)
    parent = tmp_path / review.parent_binding.ledger_path
    before = parent.read_bytes()
    opened: list[int] = []
    original_open = os.open

    def track(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == parent:
            opened.append(flags)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", track)
    ledger.summary()
    ledger.claim_attempt()
    dispatch(ledger)
    assert opened
    assert all(not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND) for flags in opened)
    assert parent.read_bytes() == before


def test_claim_serialization_failure_happens_before_claim_or_ledger_creation(
    tmp_path: Path,
) -> None:
    _, _, _, ledger = make_continuation_fixture(tmp_path)
    with pytest.raises(TypeError):
        ledger.claim_attempt({"unsupported": object()})
    assert not ledger.attempt_path.exists() and not ledger.path.exists()


def test_operator_lease_excludes_concurrent_recovery_and_releases_after_interrupt(
    tmp_path: Path,
) -> None:
    selected, version, review, ledger = make_continuation_fixture(tmp_path)
    competing = CampaignLedger(
        binding=review.campaign_binding(selected, version), repository_root=tmp_path
    )
    parent = tmp_path / review.parent_binding.ledger_path
    before = parent.read_bytes()
    with pytest.raises(KeyboardInterrupt):
        with ledger.operator_lock():
            ledger.claim_attempt()
            with pytest.raises(CampaignError, match="another continuation operator"):
                with competing.operator_lock():
                    pytest.fail("a concurrent recovery entered the active evaluation window")
            raise KeyboardInterrupt()
    with competing.operator_lock():
        assert competing.require_attempt()["campaign"] == review.campaign_id
        with pytest.raises(CampaignError, match="already claimed"):
            competing.claim_attempt()
    assert parent.read_bytes() == before
    assert not ledger.path.exists()
