"""Complete v8 continuation commands use new quota and always restore the original."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from test_q18_continuation_campaign import make_continuation_fixture
from test_q18_repair_flow import Flow
from test_q18_repair_flow import flow as flow

from enterprise_analytics_agent.retail_evaluation.campaign import (
    CODE_SHA256,
    CODE_VERSION,
    CampaignError,
    CampaignLedger,
    RestorationProof,
)
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    ContinuationReview,
    RepairReview,
)
from enterprise_analytics_agent.retail_evaluation.repair_workflow import (
    RepairOperations,
    run_repair,
)


@dataclass
class ContinuationFlow(Flow):
    continuation: ContinuationReview | None = None
    starting_version: str = "8"
    candidate_version: str = "9"

    @property
    def ledger(self) -> CampaignLedger:
        assert self.continuation is not None
        return CampaignLedger(
            binding=self.continuation.campaign_binding(self.review, self.version),
            repository_root=self.root,
        )

    def proof(self) -> RestorationProof:
        proof = super().proof()
        version = "10" if self.restored else self.starting_version
        return proof.model_copy(update={"runtime_version": version, "endpoint_version": version})

    def candidate(self) -> dict[str, Any]:
        checkpoint = super().candidate()
        checkpoint["runtime"]["agentRuntimeVersion"] = self.candidate_version
        checkpoint["endpoint"]["liveVersion"] = self.candidate_version
        return checkpoint

    def run(self, directory: str = "run", *, restore_only: bool = False) -> dict[str, object]:
        assert self.continuation is not None
        return run_repair(
            self.review,
            self.version,
            self.operations,
            self.root / directory,
            repository_root=self.root,
            restore_only=restore_only,
            continuation=self.continuation,
        )


@pytest.fixture
def continued(flow: Flow) -> ContinuationFlow:
    selected = ContinuationFlow(flow.root, flow.review, flow.version)
    _, _, selected.continuation, _ = make_continuation_fixture(
        flow.root,
        repair_review=flow.review,
        candidate_version=flow.version,
        proof=selected.proof(),
    )
    selected.events.clear()
    return selected


def test_complete_continuation_consumes_exactly_remaining39_with_shared_session(
    continued: ContinuationFlow,
) -> None:
    parent = continued.root / continued.review.ledger_path
    before = parent.read_bytes()
    result = continued.run()
    assert result["accepted"] is result["restored"] is result["smoke_passed"] is True
    assert result["campaign_id"] == "milestone-5-q18-continuation-v1"
    summary = continued.ledger.summary()
    assert summary["used"] == summary["completed"] == summary["maximum"] == 39
    assert summary["aggregate_used"] == summary["aggregate_maximum"] == 40
    assert summary["aggregate_remaining"] == 0 and summary["remaining"] == 0
    assert summary["retail_closed"] is True and summary["incomplete_reservations"] == 0
    assert summary["purposes"] == {"warmup": 1, "probe": 1, "case": 36, "restoration_smoke": 1}
    assert parent.read_bytes() == before
    cases = {case: session for purpose, case, session in continued.calls if purpose == "case"}
    assert len(cases) == 36 and cases["S01A"] == cases["S01B"]
    assert len(set(cases.values())) == 35
    proof = json.loads((continued.root / "run/original-proof.json").read_text())
    assert proof["runtime_version"] == "8"
    restored = json.loads((continued.root / "run/restored-proof.json").read_text())
    assert restored["runtime_version"] == "10"
    assert restored["code_sha256"] == CODE_SHA256 and restored["code_version_id"] == CODE_VERSION
    assert (continued.root / "run/suite/report.json").is_file()


@pytest.mark.parametrize("version", ["6", "7", "9"])
def test_incorrect_starting_version_prevents_deployment_and_leaves_claim(
    continued: ContinuationFlow, version: str
) -> None:
    continued.starting_version = version
    result = continued.run()
    assert result["accepted"] is result["candidate_attempted"] is False
    assert result["error_type"] == "ValueError"
    assert continued.events == ["verify-original"] and not continued.calls
    assert continued.ledger.attempt_path.exists() and not continued.ledger.path.exists()
    again = continued.run("duplicate")
    assert again["candidate_attempted"] is False and again["error_type"] == "CampaignError"
    assert continued.events == ["verify-original"]


@pytest.mark.parametrize("failure", ["deployment", "candidate-check", "probe"])
def test_failure_always_restores_without_reopening_parent(
    continued: ContinuationFlow, failure: str
) -> None:
    parent = continued.root / continued.review.ledger_path
    before = parent.read_bytes()
    continued.failure = failure
    result = continued.run()
    assert result["accepted"] is False
    assert result["restored"] is result["smoke_passed"] is True
    assert continued.calls[-1][0] == "restoration_smoke"
    assert parent.read_bytes() == before
    assert continued.ledger.summary()["retail_closed"] is True
    assert not (continued.root / "run/suite").exists()


def test_interruption_releases_operator_lease_after_mandatory_restore(
    continued: ContinuationFlow,
) -> None:
    continued.failure = "interruption"
    with pytest.raises(KeyboardInterrupt, match="simulated interrupted probe"):
        continued.run()
    result = json.loads((continued.root / "run/campaign-result.json").read_text())
    assert result["restored"] is result["smoke_passed"] is True
    assert result["error_type"] == "KeyboardInterrupt"
    assert continued.ledger.summary()["used"] == continued.ledger.summary()["completed"] == 3
    assert continued.ledger.summary()["aggregate_used"] == 4
    with continued.ledger.operator_lock():
        pass


@pytest.mark.parametrize("version", ["7", "8", "unknown"])
def test_old_candidate_runtime_from_prior_attempt_is_never_invoked(
    continued: ContinuationFlow, version: str
) -> None:
    continued.candidate_version = version
    result = continued.run()
    assert result["error_type"] == "ValueError" and result["accepted"] is False
    assert result["restored"] is result["smoke_passed"] is True
    assert [call[0] for call in continued.calls] == ["restoration_smoke"]


def test_duplicate_zero_call_attempt_cannot_start_candidate_but_can_restore(
    continued: ContinuationFlow,
) -> None:
    ledger = continued.ledger
    ledger.claim_attempt({"simulated_host_loss_before_dispatch": True})
    before = ledger.attempt_path.read_bytes()
    duplicate = continued.run()
    assert duplicate["candidate_attempted"] is False
    assert duplicate["error_type"] == "CampaignError"
    assert not continued.events and not continued.calls
    assert ledger.attempt_path.read_bytes() == before
    result = continued.run("restoration-only", restore_only=True)
    assert result["accepted"] is False
    assert result["restored"] is result["smoke_passed"] is True
    assert [call[0] for call in continued.calls] == ["restoration_smoke"]
    assert "deploy-candidate" not in continued.events
    assert ledger.attempt_path.read_bytes() == before


def test_active_evaluation_excludes_restoration_only_in_another_process(
    continued: ContinuationFlow,
) -> None:
    continued.ledger.claim_attempt()
    with continued.ledger.operator_lock():
        with pytest.raises(CampaignError, match="active"):
            continued.run("overlapping-recovery", restore_only=True)
    assert not continued.events and not continued.calls


def test_restoration_without_a_valid_attempt_claim_never_mutates(
    continued: ContinuationFlow,
) -> None:
    result = continued.run("unclaimed-restoration", restore_only=True)
    assert result["candidate_attempted"] is result["restored"] is False
    assert result["error_type"] == "CampaignError"
    assert not continued.events and not continued.calls


def test_complete_continuation_cli_path_and_duplicate_fail_before_aws_boundary(
    continued: ContinuationFlow,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from enterprise_analytics_agent.retail_evaluation import repair_cli, repair_workflow

    assert continued.continuation is not None
    binding = continued.continuation.campaign_binding(continued.review, continued.version)
    selected = continued.continuation
    monkeypatch.setattr(repair_cli, "load_review", lambda: continued.review)
    monkeypatch.setattr(
        repair_cli,
        "select_continuation",
        lambda name, path: (continued.review, continued.version, binding, selected),
    )
    monkeypatch.setattr(repair_cli, "CampaignLedger", lambda **kwargs: continued.ledger)
    boundary_calls: list[str] = []

    def operations(
        review: RepairReview,
        version: CandidateVersionBinding,
        output: Path,
        *,
        restore_only: bool,
    ) -> RepairOperations:
        boundary_calls.append("read-only-operator-boundary")
        assert review == continued.review and version == continued.version
        assert not restore_only
        return continued.operations

    original = repair_workflow.run_repair

    def execute(*args: Any, **kwargs: Any) -> dict[str, object]:
        return original(*args, repository_root=continued.root, **kwargs)

    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.repair_operations.operations_for", operations
    )
    monkeypatch.setattr(repair_workflow, "run_repair", execute)
    arguments = [
        "--campaign",
        "q18-continuation-v1",
        "run",
        "--invoke-live",
        "--version-record",
        str(continued.root / "authored-version-record.json"),
        "--report-dir",
        str(continued.root / "command"),
    ]
    assert repair_cli.main(arguments) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["accepted"] is True and state["campaign"]["aggregate_used"] == 40
    assert boundary_calls == ["read-only-operator-boundary"]
    arguments[-1] = str(continued.root / "duplicate-command")
    assert repair_cli.main(arguments) == 1
    assert json.loads(capsys.readouterr().err)["causes"][0]["error_type"] == "ValueError"
    assert boundary_calls == ["read-only-operator-boundary"]
