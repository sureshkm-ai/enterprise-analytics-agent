"""Production adapter plumbing must not re-read an already accepted checkpoint."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_q18_artifacts import ReviewedFixture
from test_q18_artifacts import reviewed_fixture as reviewed_fixture
from test_retail_campaign import proof

from enterprise_analytics_agent.adapters import repair_operations
from enterprise_analytics_agent.retail_evaluation.campaign import RestorationProof


def test_operation_setup_preserves_exclusive_workflow_directory(
    reviewed_fixture: ReviewedFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reviewed_fixture
    monkeypatch.setattr("boto3.Session", lambda **kwargs: fixture.session)
    output = tmp_path / "run"
    repair_operations.operations_for(fixture.review, fixture.version, output)
    assert not output.exists(), "preflight evidence must not break prepare_run_directory"
    journal = tmp_path / "run.operator-reads.jsonl"
    assert journal.is_file()
    with pytest.raises(ValueError, match="evidence already exists"):
        repair_operations.operations_for(fixture.review, fixture.version, output)


def test_receipt_reuse_expiry_and_invalidation(
    reviewed_fixture: ReviewedFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = reviewed_fixture
    original = proof().model_copy(update={"observed_at": datetime.now(UTC)})
    checks: list[str] = []
    restored_record: dict[str, Any] = {"authored": "strict original checkpoint"}
    current_proof = [original]

    class Controller:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def deploy(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            if args[2] == "restore":
                return restored_record
            return {"authored": "strict final candidate checkpoint"}

    def verify(*, session: Any) -> RestorationProof:
        checks.append("fresh-original-read")
        return original

    monkeypatch.setattr("boto3.Session", lambda **kwargs: fixture.session)
    monkeypatch.setattr(repair_operations, "DeploymentController", Controller)
    monkeypatch.setattr(repair_operations, "verify_restoration", verify)
    monkeypatch.setattr(repair_operations, "restoration_proof", lambda record: current_proof[0])
    operations = repair_operations.operations_for(fixture.review, fixture.version, tmp_path / "run")
    operations.verify_original()
    assert checks == ["fresh-original-read"]
    assert operations.deploy_candidate() == {"authored": "strict final candidate checkpoint"}
    assert operations.restore_original() is original
    operations.verify_original()
    operations.verify_original()  # The smoke gate consumes the same fresh verified proof.
    assert len(checks) == 1
    operations.deploy_candidate()  # Never reuse an earlier original proof across mutation.
    operations.verify_original()
    assert len(checks) == 2
    current_proof[0] = original.model_copy(
        update={"observed_at": datetime.now(UTC) - timedelta(seconds=61)}
    )
    operations.restore_original()
    operations.verify_original()
    assert len(checks) == 3
