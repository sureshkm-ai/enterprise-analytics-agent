"""Repair reservations have their own reviewed identity and never reuse historical quota."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.retail_evaluation.campaign import (
    CAMPAIGN_ID,
    CODE_SHA256,
    CODE_VERSION,
    REPAIR_CAMPAIGN_ID,
    REPAIR_LEDGER,
    CampaignError,
    CampaignLedger,
    RepairCampaignBinding,
    RestorationProof,
)

RUNTIME = (
    "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
    "enterprise_analytics_dev_agent-HlWywlG60h"
)
NOW = datetime(2026, 11, 9, tzinfo=UTC)


def binding(**changes: object) -> RepairCampaignBinding:
    return RepairCampaignBinding.model_validate(
        {
            "campaign_id": REPAIR_CAMPAIGN_ID,
            "ledger_path": REPAIR_LEDGER,
            "maximum": 40,
            "review_sha256": "1" * 64,
            "candidate_sha256": "2" * 64,
            "candidate_template_sha256": "3" * 64,
            "candidate_version_record_sha256": "4" * 64,
            **changes,
        }
    )


def proof() -> RestorationProof:
    return RestorationProof(
        observed_at=NOW,
        runtime_arn=RUNTIME,
        runtime_status="READY",
        endpoint_status="READY",
        runtime_version="8",
        endpoint_version="8",
        dataset_version="parity-v1",
        tenant_id="t1",
        allowed_regions=("North", "South"),
        reference_date=date(2025, 2, 1),
        configuration_sha256="a" * 64,
        expected_configuration_sha256="a" * 64,
        template_sha256="b" * 64,
        expected_template_sha256="b" * 64,
        code_sha256=CODE_SHA256,
        code_version_id=CODE_VERSION,
        resource_policies_verified=True,
        retention_days=7,
    )


def ledger(root: Path, selected: RepairCampaignBinding | None = None) -> CampaignLedger:
    return CampaignLedger(binding=selected or binding(), repository_root=root, now=lambda: NOW)


def reserve(selected: CampaignLedger) -> None:
    selected.reserve(
        purpose="case", question="reviewed question", session_id="s" * 36, runtime_arn=RUNTIME
    )


def test_separately_selected_campaign_starts_empty_without_creating_its_file(
    tmp_path: Path,
) -> None:
    selected = ledger(tmp_path)
    assert selected.path == tmp_path / REPAIR_LEDGER
    result = selected.summary()
    assert result["campaign"] == REPAIR_CAMPAIGN_ID
    assert result["maximum"] == 40 and result["used"] == 0
    assert result["campaign_binding_sha256"] == binding().sha256
    assert not selected.path.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"campaign_id": CAMPAIGN_ID},
        {"campaign_id": "unknown"},
        {"ledger_path": "artifacts/milestone-5/runtime-invocations.jsonl"},
        {"ledger_path": "artifacts/agentcore/runtime-invocations.jsonl"},
        {"ledger_path": "../alternate/runtime-invocations.jsonl"},
        {"maximum": 41},
        {"candidate_sha256": CODE_SHA256},
        {"candidate_version_record_sha256": "not-pinned"},
        {"credentials": "must-not-be-accepted"},
    ],
)
def test_unknown_or_unpinned_campaign_binding_is_rejected(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        binding(**change)


def test_version_record_is_required() -> None:
    value = binding().model_dump(mode="json")
    del value["candidate_version_record_sha256"]
    with pytest.raises(ValidationError):
        RepairCampaignBinding.model_validate(value)


def test_old_ledger_reuse_is_rejected_without_touching_old_evidence(tmp_path: Path) -> None:
    paths = [
        tmp_path / "artifacts/agentcore/runtime-invocations.jsonl",
        tmp_path / "artifacts/milestone-5/runtime-invocations.jsonl",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"historical evidence\n")
        with pytest.raises(CampaignError, match="reuse or redirect"):
            CampaignLedger(path, binding=binding(), repository_root=tmp_path)
        assert path.read_bytes() == b"historical evidence\n"
    assert not (tmp_path / REPAIR_LEDGER).exists()


def test_repair_path_requires_explicit_binding_and_forbids_aliases(tmp_path: Path) -> None:
    path = tmp_path / REPAIR_LEDGER
    with pytest.raises(CampaignError, match="explicitly pinned"):
        CampaignLedger(path)
    old = tmp_path / "historical"
    old.mkdir()
    path.parent.parent.mkdir(parents=True)
    path.parent.symlink_to(old)
    with pytest.raises(CampaignError, match="alias"):
        ledger(tmp_path)
    assert list(old.iterdir()) == []


def test_repair_entries_and_outcomes_bind_exact_review_artifact_and_upload_record(
    tmp_path: Path,
) -> None:
    selected = ledger(tmp_path)
    reservation = selected.reserve(
        purpose="probe", question="yesterday question", session_id="s" * 36, runtime_arn=RUNTIME
    )
    selected.finish(reservation, outcome="answer", elapsed_ms=3)
    records = [json.loads(line) for line in selected.path.read_text().splitlines()]
    assert [row["event"] for row in records] == ["reserved", "outcome"]
    for row in records:
        assert row["campaign"] == REPAIR_CAMPAIGN_ID
        assert row["campaign_binding"] == binding().model_dump(mode="json")
        assert row["campaign_binding_sha256"] == binding().sha256
    resumed = ledger(tmp_path)
    assert resumed.summary()["used"] == resumed.summary()["completed"] == 1
    assert resumed.summary()["purposes"] == {"probe": 1}


@pytest.mark.parametrize(
    "field",
    [
        "review_sha256",
        "candidate_sha256",
        "candidate_template_sha256",
        "candidate_version_record_sha256",
    ],
)
def test_resuming_with_changed_review_or_artifact_cannot_reset_or_append(
    tmp_path: Path, field: str
) -> None:
    original = ledger(tmp_path)
    reserve(original)
    old = original.path.read_bytes()
    changed = ledger(tmp_path, binding(**{field: "f" * 64}))
    with pytest.raises(CampaignError, match="binding differs"):
        reserve(changed)
    assert original.path.read_bytes() == old
    assert original.summary()["used"] == 1


def test_loading_historical_records_as_repair_records_fails_before_append(tmp_path: Path) -> None:
    selected = ledger(tmp_path)
    selected.path.parent.mkdir(parents=True)
    selected.path.write_text(json.dumps({"campaign": CAMPAIGN_ID, "event": "reserved"}) + "\n")
    original = selected.path.read_bytes()
    with pytest.raises(CampaignError, match="different campaign"):
        reserve(selected)
    assert selected.path.read_bytes() == original


@pytest.mark.parametrize("key", ["campaign_binding", "campaign_binding_sha256"])
def test_tampered_identity_is_rejected_on_outcome_and_resume(tmp_path: Path, key: str) -> None:
    selected = ledger(tmp_path)
    reservation = selected.reserve(
        purpose="case", question="q", session_id="s" * 36, runtime_arn=RUNTIME
    )
    row = json.loads(selected.path.read_text())
    del row[key]
    selected.path.write_text(json.dumps(row) + "\n")
    old = selected.path.read_bytes()
    with pytest.raises(CampaignError, match="binding differs"):
        selected.finish(reservation, outcome="answer", elapsed_ms=1)
    assert selected.path.read_bytes() == old


def test_repair_cap_keeps_original_artifact_restoration_slot_and_counts_interruptions(
    tmp_path: Path,
) -> None:
    selected = ledger(tmp_path)
    for _ in range(39):
        reserve(selected)
    assert selected.summary()["incomplete_reservations"] == 39
    with pytest.raises(CampaignError, match="budget"):
        reserve(ledger(tmp_path))
    with pytest.raises(ValidationError):
        selected.reserve(
            purpose="restoration_smoke",
            question="parity query",
            session_id="s" * 36,
            runtime_arn=RUNTIME,
            restoration_proof=proof().model_copy(
                update={"code_sha256": binding().candidate_sha256}
            ),
        )
    reservation = selected.reserve(
        purpose="restoration_smoke",
        question="parity query",
        session_id="s" * 36,
        runtime_arn=RUNTIME,
        restoration_proof=proof(),
    )
    assert reservation.number == 40
    selected.finish(reservation, outcome="answer", elapsed_ms=1)
    result = ledger(tmp_path).summary()
    assert result["used"] == 40 and result["completed"] == 1
    assert result["retail_closed"] is True
    with pytest.raises(CampaignError, match="budget"):
        ledger(tmp_path).reserve(
            purpose="restoration_smoke",
            question="again",
            session_id="s" * 36,
            runtime_arn=RUNTIME,
            restoration_proof=proof(),
        )


def test_repair_failure_is_durable_and_restoration_closes_remaining_retail(tmp_path: Path) -> None:
    selected = ledger(tmp_path)
    reservation = selected.reserve(
        purpose="probe", question="q", session_id="s" * 36, runtime_arn=RUNTIME
    )
    selected.finish(reservation, outcome="failed", elapsed_ms=1, error_code="sdk_timeout")
    original = selected.path.read_bytes()
    selected.reserve(
        purpose="restoration_smoke",
        question="parity",
        session_id="s" * 36,
        runtime_arn=RUNTIME,
        restoration_proof=proof(),
    )
    assert selected.path.read_bytes().startswith(original)
    result = selected.summary()
    assert result["used"] == 2 and result["failures"] == result["timeouts"] == 1
    assert result["retail_closed"] is True
    with pytest.raises(CampaignError, match="closed"):
        reserve(ledger(tmp_path))


def test_concurrent_bound_reservations_share_one_durable_cap(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: reserve(ledger(tmp_path)), range(24)))
    selected = ledger(tmp_path)
    records = [json.loads(line) for line in selected.path.read_text().splitlines()]
    assert [row["number"] for row in records] == list(range(1, 25))
    assert selected.summary()["used"] == 24


def test_legacy_records_keep_original_identity_and_do_not_accept_probe(tmp_path: Path) -> None:
    selected = CampaignLedger(tmp_path / "legacy-fixture.jsonl")
    with pytest.raises(CampaignError, match="unrecognized"):
        selected.reserve(purpose="probe", question="q", session_id="s" * 36, runtime_arn=RUNTIME)
    assert not selected.path.exists()
    reserve(selected)
    row = json.loads(selected.path.read_text())
    assert row["campaign"] == CAMPAIGN_ID
    assert "campaign_binding" not in row and "campaign_binding_sha256" not in row
