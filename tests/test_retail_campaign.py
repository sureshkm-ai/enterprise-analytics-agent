"""Quota invariants use temporary ledgers and never touch the M4/M5 real ledgers."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.retail_evaluation.campaign import (
    CampaignError,
    CampaignLedger,
    RestorationProof,
)

RUNTIME = (
    "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
    "enterprise_analytics_dev_agent-HlWywlG60h"
)
NOW = datetime(2026, 11, 8, tzinfo=UTC)


def proof() -> RestorationProof:
    return RestorationProof(
        observed_at=NOW,
        runtime_arn=RUNTIME,
        runtime_status="READY",
        endpoint_status="READY",
        runtime_version="6",
        endpoint_version="6",
        dataset_version="parity-v1",
        tenant_id="t1",
        allowed_regions=("North", "South"),
        reference_date=date(2025, 2, 1),
        configuration_sha256="a" * 64,
        expected_configuration_sha256="a" * 64,
        template_sha256="b" * 64,
        expected_template_sha256="b" * 64,
        code_sha256="51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1",
        code_version_id="HSRXiFjg0w2W77InULH4.fn32Y.JH8b9",
        resource_policies_verified=True,
        retention_days=7,
    )


def reserve(ledger: CampaignLedger) -> None:
    ledger.reserve(purpose="case", question="a question", session_id="s" * 36, runtime_arn=RUNTIME)


def test_retail_cap_preserves_final_restoration_slot_and_resumes(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = CampaignLedger(path, now=lambda: NOW)
    for _ in range(39):
        reserve(ledger)
    resumed = CampaignLedger(path, now=lambda: NOW)
    assert resumed.summary()["used"] == 39
    with pytest.raises(CampaignError, match="budget"):
        reserve(resumed)
    reservation = resumed.reserve(
        purpose="restoration_smoke",
        question="parity query",
        session_id="s" * 36,
        runtime_arn=RUNTIME,
        restoration_proof=proof(),
    )
    assert reservation.number == 40
    assert resumed.summary()["used"] == 40
    with pytest.raises(CampaignError, match="budget"):
        resumed.reserve(
            purpose="restoration_smoke",
            question="again",
            session_id="s" * 36,
            runtime_arn=RUNTIME,
            restoration_proof=proof(),
        )


def test_reserved_but_interrupted_calls_count_and_outcomes_are_append_only(tmp_path: Path) -> None:
    ledger = CampaignLedger(tmp_path / "ledger.jsonl")
    reservation = ledger.reserve(
        purpose="case", question="a", session_id="s" * 36, runtime_arn=RUNTIME
    )
    reserved_bytes = ledger.path.read_bytes()
    ledger.finish(reservation, outcome="failed", elapsed_ms=1, error_code="sdk_error")
    assert ledger.path.read_bytes().startswith(reserved_bytes)
    assert ledger.summary()["used"] == 1
    assert ledger.summary()["completed"] == 1
    with pytest.raises(CampaignError, match="already completed"):
        ledger.finish(reservation, outcome="answer", elapsed_ms=2)


def test_concurrent_reservations_are_serialized_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: reserve(CampaignLedger(path)), range(32)))
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [record["number"] for record in records] == list(range(1, 33))
    assert len({record["reservation_id"] for record in records}) == 32


def test_restoration_requires_fresh_matching_proof_and_closes_retail(tmp_path: Path) -> None:
    ledger = CampaignLedger(tmp_path / "ledger.jsonl", now=lambda: NOW)
    with pytest.raises(CampaignError, match="freshly"):
        ledger.reserve(
            purpose="restoration_smoke",
            question="parity query",
            session_id="s" * 36,
            runtime_arn=RUNTIME,
        )
    with pytest.raises(CampaignError, match="stale"):
        ledger.reserve(
            purpose="restoration_smoke",
            restoration_proof=proof().model_copy(
                update={"observed_at": NOW - timedelta(minutes=6)}
            ),
            question="parity query",
            session_id="s" * 36,
            runtime_arn=RUNTIME,
        )
    with pytest.raises(CampaignError, match="different Runtime"):
        ledger.reserve(
            purpose="restoration_smoke",
            restoration_proof=proof().model_copy(update={"runtime_arn": "another"}),
            question="parity query",
            session_id="s" * 36,
            runtime_arn=RUNTIME,
        )
    assert not ledger.path.exists()
    ledger.reserve(
        purpose="restoration_smoke",
        restoration_proof=proof(),
        question="parity query",
        session_id="s" * 36,
        runtime_arn=RUNTIME,
    )
    with pytest.raises(CampaignError, match="closed"):
        reserve(ledger)
    assert ledger.summary()["retail_closed"] is True


@pytest.mark.parametrize(
    "update",
    [
        {"runtime_version": "5"},
        {"configuration_sha256": "c" * 64},
        {"template_sha256": "c" * 64},
        {"tenant_id": "retail_demo"},
        {"reference_date": "2025-04-01"},
        {"resource_policies_verified": False},
    ],
)
def test_restoration_proof_rejects_incomplete_or_wrong_state(update: dict[str, object]) -> None:
    document = proof().model_dump(mode="json") | update
    with pytest.raises(ValidationError):
        RestorationProof.model_validate(document)


@pytest.mark.parametrize("payload", ["partial", '{"campaign":"other"}\n', "{}\n"])
def test_corrupt_ledger_blocks_dispatch(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text(payload)
    with pytest.raises(CampaignError):
        reserve(CampaignLedger(path))
    assert path.read_text() == payload


def test_m4_ledger_path_and_symlink_alias_are_refused(tmp_path: Path) -> None:
    historical = tmp_path / "artifacts/agentcore/runtime-invocations.jsonl"
    historical.parent.mkdir(parents=True)
    historical.write_text("original M4 evidence")
    with pytest.raises(CampaignError, match="Milestone 4"):
        CampaignLedger(historical)
    alias = tmp_path / "m5-alias.jsonl"
    alias.symlink_to(historical)
    with pytest.raises(CampaignError, match="Milestone 4"):
        CampaignLedger(alias)
    assert historical.read_text() == "original M4 evidence"


def test_status_does_not_create_a_ledger(tmp_path: Path) -> None:
    ledger = CampaignLedger(tmp_path / "ledger.jsonl")
    assert ledger.summary()["used"] == 0
    assert not ledger.path.exists()


def test_default_ledger_is_independent_of_report_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = CampaignLedger().path
    monkeypatch.chdir(tmp_path)
    assert CampaignLedger().path == original


def test_summary_reports_failures_remaining_and_unfinished_reservations(tmp_path: Path) -> None:
    ledger = CampaignLedger(tmp_path / "ledger.jsonl")
    reservation = ledger.reserve(
        purpose="retry", question="q", session_id="s" * 36, runtime_arn=RUNTIME
    )
    ledger.finish(reservation, outcome="failed", elapsed_ms=1, error_code="sdk_error")
    reserve(ledger)
    report = ledger.summary()
    assert report["remaining"] == 38
    assert report["incomplete_reservations"] == 1
    assert report["failures"] == 1
    assert report["purposes"] == {"retry": 1, "case": 1}
    assert report["error_codes"] == {"sdk_error": 1}
    assert report["protected_restoration_slots"] == 1
    assert isinstance(report["ledger_sha256"], str)
