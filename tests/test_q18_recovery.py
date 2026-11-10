"""Authored v10 recovery histories exercise all 36 cases within 38 new calls."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_q18_continuation_campaign import make_continuation_fixture
from test_q18_repair_flow import Flow
from test_q18_repair_flow import flow as flow

from enterprise_analytics_agent.adapters.operator_reads import OperatorReadError
from enterprise_analytics_agent.retail_evaluation.campaign import (
    CampaignError,
    CampaignLedger,
    RestorationProof,
)
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    RecoveryReview,
    ReviewedRecoveryCheckpoint,
    select_recovery,
)
from enterprise_analytics_agent.retail_evaluation.repair_workflow import run_repair


@dataclass
class RecoveryFlow(Flow):
    recovery: RecoveryReview | None = None
    starting_version: str = "10"
    candidate_version: str = "11"
    receipt_age: int = 0

    @property
    def ledger(self) -> CampaignLedger:
        assert self.recovery is not None
        return CampaignLedger(
            binding=self.recovery.campaign_binding(self.review, self.version),
            repository_root=self.root,
        )

    def proof(self) -> RestorationProof:
        proof = super().proof()
        version = "12" if self.restored else self.starting_version
        return proof.model_copy(update={"runtime_version": version, "endpoint_version": version})

    def candidate(self) -> dict[str, Any]:
        checkpoint = super().candidate()
        checkpoint["runtime"]["agentRuntimeVersion"] = self.candidate_version
        checkpoint["endpoint"]["liveVersion"] = self.candidate_version
        checkpoint["observed_at"] = (
            datetime.now(UTC) - timedelta(seconds=self.receipt_age)
        ).isoformat()
        return checkpoint

    def deploy(self) -> dict[str, Any]:
        # Same returned-proof contract as the production controller/adapter.
        super().deploy()
        if self.failure in {"transport", "double-failure"}:
            raise OperatorReadError(
                {
                    "phase": "candidate-checkpoint",
                    "service": "s3",
                    "operation": "head_object",
                    "attempt": 3,
                    "error_type": "ConnectTimeoutError",
                }
            )
        return self.candidate()

    def restore(self) -> None:
        if self.failure == "double-failure":
            raise OperatorReadError(
                {
                    "phase": "original-checkpoint",
                    "service": "logs",
                    "operation": "describe_log_groups",
                    "attempt": 3,
                    "error_type": "ReadTimeoutError",
                }
            )
        super().restore()

    def run(self, directory: str = "run", *, restore_only: bool = False) -> dict[str, object]:
        assert self.recovery is not None
        return run_repair(
            self.review,
            self.version,
            self.operations,
            self.root / directory,
            repository_root=self.root,
            continuation=self.recovery,
            restore_only=restore_only,
        )


@pytest.fixture
def recovery(flow: Flow) -> RecoveryFlow:
    selected = RecoveryFlow(flow.root, flow.review, flow.version)
    _, _, old, parent = make_continuation_fixture(
        flow.root,
        repair_review=flow.review,
        candidate_version=flow.version,
        proof=selected.proof().model_copy(update={"runtime_version": "8", "endpoint_version": "8"}),
    )
    parent.claim_attempt({"authored": "closed continuation"})
    reservation = parent.reserve(
        purpose="restoration_smoke",
        question="authored",
        session_id="historical",
        runtime_arn=flow.review.runtime_arn,
        restoration_proof=selected.proof(),
    )
    parent.finish(reservation, outcome="answer", elapsed_ms=1)
    selected.recovery = RecoveryReview(
        repair_review_sha256=old.repair_review_sha256,
        parent_binding=old.campaign_binding(flow.review, flow.version),
        parent_ledger_sha256=hashlib.sha256(parent.path.read_bytes()).hexdigest(),
        parent_attempt_sha256=hashlib.sha256(parent.attempt_path.read_bytes()).hexdigest(),
        candidate_sha256=old.candidate_sha256,
        candidate_template_sha256=old.candidate_template_sha256,
        candidate_version_id=old.candidate_version_id,
        candidate_version_record_sha256=old.candidate_version_record_sha256,
        starting_checkpoint=ReviewedRecoveryCheckpoint(
            **old.starting_checkpoint.model_dump(
                exclude={"runtime_version", "endpoint_version", "source_proof_sha256"}
            )
        ),
    )
    directory = flow.root / "evaluations/retail-v1"
    (directory / "q18-repair-review.json").write_text(flow.review.model_dump_json())
    (directory / "q18-continuation-review.json").write_text(old.model_dump_json())
    (directory / "q18-recovery-review.json").write_text(selected.recovery.model_dump_json())
    (flow.root / "version.json").write_text(flow.version.model_dump_json())
    selected.events.clear()
    return selected


def protected(flow: RecoveryFlow) -> dict[Path, bytes]:
    assert flow.recovery is not None
    paths = [
        flow.root / flow.review.ledger_path,
        flow.root / flow.recovery.parent_binding.ledger_path,
    ]
    paths.append(paths[-1].with_name("attempt-claim.json"))
    return {p: p.read_bytes() for p in paths}


def test_full_recovery_consumes38_preserving_two_histories_and_all_cases(
    recovery: RecoveryFlow,
) -> None:
    before = protected(recovery)
    result = recovery.run()
    assert result["accepted"] is True and result["warmup_mode"] == "q18-probe"
    summary = recovery.ledger.summary()
    assert summary["used"] == summary["completed"] == summary["maximum"] == 38
    assert summary["aggregate_used"] == summary["aggregate_maximum"] == 40
    assert summary["purposes"] == {"probe": 1, "case": 36, "restoration_smoke": 1}
    assert summary["aggregate_remaining"] == summary["incomplete_reservations"] == 0
    assert protected(recovery) == before
    assert recovery.events.count("verify-candidate") == 1, "no post-controller checkpoint repeat"
    cases = {case: session for purpose, case, session in recovery.calls if purpose == "case"}
    assert len(cases) == 36 and cases["S01A"] == cases["S01B"]
    assert recovery.calls[0][1] == "Q18"
    assert (recovery.root / "run/suite/report.json").exists()
    with pytest.raises(CampaignError, match="budget exhausted"):
        recovery.ledger.reserve(
            purpose="restoration_smoke",
            question="extra",
            session_id="s",
            runtime_arn=recovery.review.runtime_arn,
            restoration_proof=recovery.proof(),
        )


@pytest.mark.parametrize(
    "failure,used", [("deployment", 1), ("candidate-check", 1), ("transport", 1), ("probe", 2)]
)
def test_failure_restores_and_stops_suite_without_reset(
    recovery: RecoveryFlow,
    failure: str,
    used: int,
) -> None:
    before = protected(recovery)
    recovery.failure = failure
    result = recovery.run()
    assert result["accepted"] is False and result["smoke_passed"] is True
    assert recovery.ledger.summary()["used"] == used
    assert recovery.ledger.summary()["aggregate_used"] == used + 2
    assert not (recovery.root / "run/suite").exists()
    assert protected(recovery) == before
    with pytest.raises(ValueError, match="already used"):
        recovery.run("duplicate")
    if failure == "transport":
        operation = result["error"]["causes"][0]["operation"]  # type: ignore[index]
        assert operation["operation"] == "head_object" and operation["attempt"] == 3


def test_primary_and_restoration_errors_survive_together(recovery: RecoveryFlow) -> None:
    recovery.failure = "double-failure"
    result = recovery.run()
    assert result["accepted"] is result["restored"] is False
    content = (recovery.root / "run/campaign-result.json").read_text()
    assert "head_object" in content and "describe_log_groups" in content
    assert recovery.ledger.summary()["used"] == 0


@pytest.mark.parametrize("age", [61, -2])
def test_stale_or_future_controller_receipt_cannot_authorize_invocation(
    recovery: RecoveryFlow,
    age: int,
) -> None:
    recovery.receipt_age = age
    result = recovery.run()
    assert result["accepted"] is False and result["smoke_passed"] is True
    assert [p for p, _, _ in recovery.calls] == ["restoration_smoke"]


@pytest.mark.parametrize("version", ["8", "9", "11"])
def test_only_reviewed_v10_start_can_deploy(recovery: RecoveryFlow, version: str) -> None:
    recovery.starting_version = version
    result = recovery.run()
    assert result["candidate_attempted"] is False and not recovery.calls


def test_parent_drift_or_claim_drift_blocks_before_deployment(recovery: RecoveryFlow) -> None:
    before = protected(recovery)
    for path, content in before.items():
        path.write_bytes(content + b" ")
        with pytest.raises(CampaignError):
            recovery.run(path.parent.name + "-drift")
        assert not recovery.calls
        path.write_bytes(content)


def test_global_operator_lease_excludes_older_selector(recovery: RecoveryFlow) -> None:
    assert recovery.recovery is not None
    older = CampaignLedger(binding=recovery.recovery.parent_binding, repository_root=recovery.root)
    with older.operator_lock():
        with pytest.raises(CampaignError, match="active"):
            recovery.run()
    with recovery.ledger.operator_lock():
        with pytest.raises(CampaignError, match="active"):
            with older.operator_lock():
                pytest.fail("older restore must not replace an active new candidate")


def test_recovery_selection_is_offline_and_does_not_create_claim(recovery: RecoveryFlow) -> None:
    before = protected(recovery)
    chosen = select_recovery(
        "q18-recovery-v1", recovery.root / "version.json", repository_root=recovery.root
    )
    assert chosen[3] == recovery.recovery
    assert not recovery.ledger.path.exists() and not recovery.ledger.attempt_path.exists()
    assert protected(recovery) == before


def test_interrupted_probe_restores_before_reraising(recovery: RecoveryFlow) -> None:
    recovery.failure = "interruption"
    with pytest.raises(KeyboardInterrupt):
        recovery.run()
    result = json.loads((recovery.root / "run/campaign-result.json").read_text())
    assert result["smoke_passed"] is True and result["error_type"] == "KeyboardInterrupt"
    assert recovery.ledger.summary()["used"] == 2


def test_restoration_only_reuses_claim_without_candidate_dispatch(recovery: RecoveryFlow) -> None:
    recovery.ledger.claim_attempt({"authored": "process died after starting deployment"})
    before = recovery.ledger.attempt_path.read_bytes()
    result = recovery.run(restore_only=True)
    assert result["accepted"] is False and result["smoke_passed"] is True
    assert "deploy-candidate" not in recovery.events
    assert [p for p, _, _ in recovery.calls] == ["restoration_smoke"]
    assert recovery.ledger.attempt_path.read_bytes() == before


def test_accounting_error_cannot_erase_failure_evidence_or_claim_success(
    recovery: RecoveryFlow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = CampaignLedger.summary

    def summary(ledger: CampaignLedger) -> dict[str, object]:
        if recovery.restored:
            raise CampaignError("authored final audit failure")
        return original(ledger)

    monkeypatch.setattr(CampaignLedger, "summary", summary)
    result = recovery.run()
    assert result["accepted"] is False and result["smoke_passed"] is True
    assert result["probe_passed"] is result["suite_passed"] is True
    assert (
        result["accounting_error"]
        == json.loads((recovery.root / "run/campaign-result.json").read_text())["accounting_error"]
    )


def test_cli_routes_recovery_and_refuses_duplicate_before_aws(
    recovery: RecoveryFlow,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from enterprise_analytics_agent.retail_evaluation import repair_cli, repair_workflow

    assert recovery.recovery is not None
    chosen = select_recovery(
        "q18-recovery-v1", recovery.root / "version.json", repository_root=recovery.root
    )
    monkeypatch.setattr(repair_cli, "load_review", lambda: recovery.review)
    monkeypatch.setattr(repair_cli, "select_recovery", lambda *args: chosen)
    monkeypatch.setattr(repair_cli, "CampaignLedger", lambda **kwargs: recovery.ledger)
    boundaries: list[str] = []

    def operations(*args: Any, **kwargs: Any) -> Any:
        boundaries.append("read-boundary")
        return recovery.operations

    execute = repair_workflow.run_repair
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.repair_operations.operations_for", operations
    )
    monkeypatch.setattr(
        repair_workflow,
        "run_repair",
        lambda *args, **kwargs: execute(*args, repository_root=recovery.root, **kwargs),
    )
    command = [
        "--campaign",
        "q18-recovery-v1",
        "run",
        "--invoke-live",
        "--version-record",
        str(recovery.root / "version.json"),
        "--report-dir",
        str(recovery.root / "cli"),
    ]
    assert repair_cli.main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["accepted"] is True and result["campaign"]["aggregate_used"] == 40
    command[-1] = str(recovery.root / "duplicate-cli")
    assert repair_cli.main(command) == 1
    assert boundaries == ["read-boundary"]
    assert json.loads(capsys.readouterr().err)["causes"][0]["error_type"] == "ValueError"
