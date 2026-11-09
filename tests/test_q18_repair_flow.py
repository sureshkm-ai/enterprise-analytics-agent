"""Exercise the whole candidate/probe/suite/restore workflow without AWS or real ledgers."""

import io
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from test_retail_reporting import authored_response

from enterprise_analytics_agent.agent.contracts import AgentDiagnostics, AgentRequest, AgentResponse
from enterprise_analytics_agent.contracts_v2 import QueryMetricResponseV2, TimeRangeV2
from enterprise_analytics_agent.retail_evaluation.campaign import (
    CODE_SHA256,
    CODE_VERSION,
    CampaignLedger,
    RestorationProof,
)
from enterprise_analytics_agent.retail_evaluation.cases import file_sha256, load_goldens, load_suite
from enterprise_analytics_agent.retail_evaluation.client import RuntimeInvoker, RuntimeReply
from enterprise_analytics_agent.retail_evaluation.deployment import BASE_TEMPLATE_SHA256
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    RepairReview,
)
from enterprise_analytics_agent.retail_evaluation.repair_workflow import (
    WARMUP,
    RepairOperations,
    campaign_binding,
    run_repair,
)

SOURCE_EVIDENCE = Path(__file__).resolve().parents[1] / "evaluations/retail-v1"


def parity_response(target: RetailTarget) -> AgentResponse:
    """Independently authored original-parity smoke operands, never a repair oracle."""
    result = QueryMetricResponseV2(
        metric_id="net_revenue",
        definition_version="1.0.0",
        time_range=TimeRangeV2(start=date(2025, 1, 1), end=date(2025, 2, 1)),
        group_by=("region",),
        unit="currency",
        currency="USD",
        rows=(
            {"dimensions": {"region": "North"}, "value": "28.50"},
            {"dimensions": {"region": "South"}, "value": "13.00"},
        ),
    )
    return AgentResponse(
        status="answer",
        answer="Independently authored parity restoration result.",
        dataset_version="parity-v1",
        metric_versions={"net_revenue": "1.0.0"},
        results=(result,),
        diagnostics=AgentDiagnostics(
            model_id=target.model_id,
            configuration={"reference_date": "2025-02-01"},
            model_calls=2,
            input_tokens=10,
            output_tokens=5,
            latency_ms=10,
        ),
    )


@dataclass
class Flow:
    root: Path
    review: RepairReview
    version: CandidateVersionBinding
    events: list[str] = field(default_factory=list)
    calls: list[tuple[str, str, str]] = field(default_factory=list)
    restored: bool = False
    suite_index: int = 0
    failure: str | None = None

    @property
    def ledger(self) -> CampaignLedger:
        return CampaignLedger(
            binding=campaign_binding(self.review, self.version), repository_root=self.root
        )

    def proof(self) -> RestorationProof:
        self.events.append("verify-original")
        if self.restored and self.failure == "restored-proof":
            raise ValueError("restored artifact/version does not match original pins")
        target = RetailTarget.model_validate_json(
            (SOURCE_EVIDENCE / "target.restore.json").read_text()
        )
        version = "8" if self.restored else "6"
        return RestorationProof(
            observed_at=datetime.now(UTC),
            runtime_arn=target.runtime_arn,
            runtime_status="READY",
            endpoint_status="READY",
            runtime_version=version,
            endpoint_version=version,
            dataset_version="parity-v1",
            tenant_id="t1",
            allowed_regions=("North", "South"),
            reference_date=date(2025, 2, 1),
            configuration_sha256="c" * 64,
            expected_configuration_sha256="c" * 64,
            template_sha256=BASE_TEMPLATE_SHA256,
            expected_template_sha256=BASE_TEMPLATE_SHA256,
            code_sha256=CODE_SHA256,
            code_version_id=CODE_VERSION,
            resource_policies_verified=True,
            retention_days=7,
        )

    def deploy(self) -> None:
        self.events.append("deploy-candidate")
        if self.failure == "deployment":
            raise RuntimeError("candidate update failed")

    def candidate(self) -> dict[str, Any]:
        self.events.append("verify-candidate")
        if self.failure == "candidate-check":
            raise ValueError("candidate version differs")
        return {
            "runtime": {
                "agentRuntimeArn": self.review.runtime_arn,
                "status": "READY",
                "agentRuntimeVersion": "7",
                "createdAt": datetime(2026, 11, 8, 19, 47, 45, tzinfo=UTC),
                "lastUpdatedAt": datetime(2026, 11, 9, 17, 17, 41, tzinfo=UTC),
            },
            "endpoint": {"status": "READY", "liveVersion": "7"},
            "artifact_head": {"LastModified": datetime(2026, 11, 9, 17, 1, tzinfo=UTC)},
            "ResponseMetadata": {"HTTPHeaders": {"Authorization": "secret-header"}},
        }

    def restore(self) -> None:
        self.events.append("restore-original")
        if self.failure == "restoration":
            raise RuntimeError("original restore update failed")
        self.restored = True

    def invoker(self, target: RetailTarget) -> RuntimeInvoker:
        suite = load_suite(SOURCE_EVIDENCE / "questions.json")
        goldens = load_goldens(SOURCE_EVIDENCE / "expected-results.json", suite)
        cases = {
            case.id: (case, golden) for case, golden in zip(suite.cases, goldens.cases, strict=True)
        }

        def invoke(*, payload: bytes, session_id: str) -> RuntimeReply:
            request = AgentRequest.model_validate_json(payload)
            assert set(json.loads(payload)) == {"question"}
            records = [json.loads(line) for line in self.ledger.path.read_text().splitlines()]
            reservation = records[-1]
            assert reservation["event"] == "reserved"
            assert reservation["session_id"] == session_id
            assert reservation["runtime_arn"] == target.runtime_arn
            purpose = reservation["purpose"]
            if purpose == "restoration_smoke":
                assert self.restored and target.dataset_version == "parity-v1"
                assert request.question == WARMUP
                case_id = "smoke"
                response = parity_response(target)
            else:
                assert not self.restored and target.dataset_version == "retail-v1"
                if purpose == "warmup":
                    case_id = "Q02"
                elif purpose == "probe":
                    case_id = "Q18"
                else:
                    assert purpose == "case"
                    case_id = suite.cases[self.suite_index].id
                    self.suite_index += 1
                case, golden = cases[case_id]
                assert request.question == case.question
                response = authored_response(case, golden)
                if purpose == "probe" and self.failure in {
                    "probe",
                    "restored-proof",
                    "restoration",
                }:
                    response = response.model_copy(
                        update={"status": "clarification", "results": ()}
                    )
            self.calls.append((purpose, case_id, session_id))
            self.events.append("invoke-" + purpose)
            if purpose == "probe" and self.failure == "interruption":
                raise KeyboardInterrupt("simulated interrupted probe")
            return RuntimeReply(
                io.BytesIO(response.model_dump_json().encode()), f"fake-{len(self.calls)}"
            )

        return invoke

    @property
    def operations(self) -> RepairOperations:
        return RepairOperations(self.proof, self.deploy, self.candidate, self.restore, self.invoker)

    def run(self, directory: str = "run", *, restore_only: bool = False) -> dict[str, object]:
        return run_repair(
            self.review,
            self.version,
            self.operations,
            self.root / directory,
            repository_root=self.root,
            restore_only=restore_only,
        )


@pytest.fixture
def flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Flow:
    def forbid_aws(*args: object, **kwargs: object) -> Any:
        raise AssertionError("Repair flow regressions must never construct AWS sessions")

    monkeypatch.setattr("boto3.Session", forbid_aws)
    evidence = tmp_path / "evaluations/retail-v1"
    evidence.mkdir(parents=True)
    for name in (
        "questions.json",
        "expected-results.json",
        "oracle-provenance.json",
        "contributions.csv",
        "target.json",
        "target.restore.json",
    ):
        shutil.copyfile(SOURCE_EVIDENCE / name, evidence / name)
    review = RepairReview(
        candidate_artifact_path="artifacts/milestone-5/q18-repair-v1/candidate/agent.zip",
        candidate_assembly_path="artifacts/milestone-5/q18-repair-v1/cdk.candidate.out",
        candidate_sha256="a" * 64,
        candidate_template_sha256="b" * 64,
        questions_sha256=file_sha256(evidence / "questions.json"),
        expected_results_sha256=file_sha256(evidence / "expected-results.json"),
        source_patch_sha256="d" * 64,
    )
    version = CandidateVersionBinding(
        review_sha256=review.review_sha256,
        candidate_sha256=review.candidate_sha256,
        candidate_template_sha256=review.candidate_template_sha256,
        bucket="enterprise-analytics-dev-453711491609-us-west-2-agent-code",
        key=f"releases/{review.candidate_sha256}/agent.zip",
        version_id="fake-approved-upload-version-only-in-tests",
        checksum_sha256=review.candidate_sha256,
        size_bytes=123,
        verified_at=datetime.now(UTC),
    )
    return Flow(tmp_path, review, version)


def test_complete_repair_campaign_keeps_probe_suite_and_original_restore_distinct(
    flow: Flow,
) -> None:
    result = flow.run()
    assert result["accepted"] is True
    assert result["probe_passed"] is result["suite_passed"] is True
    assert result["restored"] is result["smoke_passed"] is True
    summary = flow.ledger.summary()
    assert summary["used"] == summary["completed"] == 39
    assert summary["purposes"] == {"warmup": 1, "probe": 1, "case": 36, "restoration_smoke": 1}
    assert summary["retail_closed"] is True and summary["remaining"] == 1
    assert flow.events.index("restore-original") > flow.events.index("invoke-case")
    cases = {case_id: session for purpose, case_id, session in flow.calls if purpose == "case"}
    assert len(cases) == 36 and cases["S01A"] == cases["S01B"]
    assert len(set(cases.values())) == 35
    assert sum(case_id == "Q18" for _, case_id, _ in flow.calls) == 2
    context = json.loads((flow.root / "run/candidate-ready/run-context.json").read_text())
    checkpoint = context["evidence"]["checkpoint"]
    assert checkpoint["runtime"]["lastUpdatedAt"] == "2026-11-09T17:17:41+00:00"
    assert checkpoint["artifact_head"]["LastModified"] == "2026-11-09T17:01:00+00:00"
    assert checkpoint["ResponseMetadata"] == "[redacted]"
    proof = json.loads((flow.root / "run/restored-proof.json").read_text())
    assert proof["runtime_version"] == "8" and proof["code_sha256"] == CODE_SHA256
    assert proof["code_version_id"] == CODE_VERSION
    records = [json.loads(line) for line in flow.ledger.path.read_text().splitlines()]
    assert len(records) == 78
    assert all(record["campaign"] == flow.review.campaign_id for record in records)
    assert all(record["campaign_binding"]["candidate_sha256"] == "a" * 64 for record in records)


def test_failed_q18_probe_restores_and_does_not_start_full_suite(flow: Flow) -> None:
    flow.failure = "probe"
    result = flow.run()
    assert result["accepted"] is result["probe_passed"] is result["suite_passed"] is False
    assert result["restored"] is result["smoke_passed"] is True
    assert [purpose for purpose, _, _ in flow.calls] == ["warmup", "probe", "restoration_smoke"]
    assert flow.ledger.summary()["used"] == 3
    assert not (flow.root / "run/suite").exists()
    assert json.loads((flow.root / "run/probe.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("failure", ["deployment", "candidate-check"])
def test_candidate_update_or_readiness_failure_still_restores_original(
    flow: Flow, failure: str
) -> None:
    flow.failure = failure
    result = flow.run()
    assert result["accepted"] is False and result["smoke_passed"] is True
    assert [purpose for purpose, _, _ in flow.calls] == ["restoration_smoke"]
    assert flow.ledger.summary()["used"] == 1
    assert "restore-original" in flow.events


def test_interrupt_is_counted_then_restoration_finishes_before_it_is_reraised(flow: Flow) -> None:
    flow.failure = "interruption"
    with pytest.raises(KeyboardInterrupt, match="simulated interrupted probe"):
        flow.run()
    result = json.loads((flow.root / "run/campaign-result.json").read_text())
    assert result["restored"] is result["smoke_passed"] is True
    assert result["error_type"] == "KeyboardInterrupt" and result["accepted"] is False
    assert flow.ledger.summary()["used"] == flow.ledger.summary()["completed"] == 3
    assert flow.ledger.summary()["failures"] == 1
    assert flow.events.index("restore-original") > flow.events.index("invoke-probe")


@pytest.mark.parametrize("failure", ["restoration", "restored-proof"])
def test_restore_failure_or_mismatched_original_proof_prevents_smoke(
    flow: Flow, failure: str
) -> None:
    flow.failure = failure
    result = flow.run()
    assert result["accepted"] is result["restored"] is result["smoke_passed"] is False
    assert "restoration_error_type" in result
    assert [purpose for purpose, _, _ in flow.calls] == ["warmup", "probe"]
    assert flow.ledger.summary()["used"] == 2
    assert flow.ledger.summary()["protected_restoration_slots"] == 1


def test_version_record_for_another_review_fails_before_deployment_or_reservation(
    flow: Flow,
) -> None:
    flow.version = flow.version.model_copy(update={"review_sha256": "e" * 64})
    with pytest.raises(ValueError, match="does not bind"):
        flow.run()
    assert not flow.events and not flow.calls
    assert not (flow.root / flow.review.ledger_path).exists()
    assert not (flow.root / "run").exists()


def test_used_campaign_refuses_a_rerun_but_allows_counted_restoration_only_resume(
    flow: Flow,
) -> None:
    seed = flow.ledger.reserve(
        purpose="probe",
        question="Show net_revenue for yesterday.",
        session_id="a" * 36,
        runtime_arn=RetailTarget.model_validate_json(
            (SOURCE_EVIDENCE / "target.json").read_text()
        ).runtime_arn,
    )
    before = flow.ledger.path.read_bytes()
    with pytest.raises(ValueError, match="already used"):
        flow.run()
    assert flow.ledger.path.read_bytes() == before
    assert not flow.events and not flow.calls
    result = flow.run("resume", restore_only=True)
    assert result["restored"] is result["smoke_passed"] is True
    assert result["accepted"] is False
    assert "deploy-candidate" not in flow.events
    assert flow.ledger.path.read_bytes().startswith(before)
    assert flow.ledger.summary()["used"] == 2
    assert flow.ledger.summary()["completed"] == 1
    assert flow.ledger.summary()["incomplete_reservations"] == 1
    records = [json.loads(line) for line in flow.ledger.path.read_text().splitlines()]
    assert records[0]["reservation_id"] == seed.reservation_id


def test_restoration_only_does_not_depend_on_retail_goldens_or_targets(flow: Flow) -> None:
    # Operator evidence can be unavailable after an interrupted candidate update.
    # Restoring the pinned original must not depend on reloading retail answers.
    shutil.rmtree(flow.root / "evaluations/retail-v1")
    result = flow.run("missing-retail-evidence", restore_only=True)
    assert result["restored"] is result["smoke_passed"] is True
    assert result["accepted"] is False
    assert "deploy-candidate" not in flow.events
    assert [purpose for purpose, _, _ in flow.calls] == ["restoration_smoke"]
    assert flow.ledger.summary()["used"] == flow.ledger.summary()["completed"] == 1


def test_alternate_valid_runtime_target_fails_before_deployment_or_reservation(flow: Flow) -> None:
    path = flow.root / "evaluations/retail-v1/target.json"
    target = json.loads(path.read_text())
    target["runtime_arn"] = (
        "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
        "enterprise_analytics_dev_agent-ABCDEFGHIJ"
    )
    path.write_text(json.dumps(target))
    # This ARN is valid for the ordinary target schema but not the reviewed runtime.
    RetailTarget.model_validate_json(path.read_text())
    with pytest.raises(ValueError, match="retail target differs"):
        flow.run()
    assert not flow.events and not flow.calls
    assert not (flow.root / flow.review.ledger_path).exists()
    assert not (flow.root / "run").exists()


def test_sigterm_restores_before_propagating_and_restores_the_previous_handler(
    flow: Flow, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signal

    from enterprise_analytics_agent.retail_evaluation.repair_cli import interruption_guard

    previous = object()
    active: list[Any] = [previous]
    changes: list[tuple[int, Any]] = []

    def install(signum: int, handler: Any) -> Any:
        old = active[0]
        active[0] = handler
        changes.append((signum, handler))
        return old

    monkeypatch.setattr(signal, "signal", install)
    original_invoker = flow.invoker
    terminated = False

    def invoker(target: RetailTarget) -> RuntimeInvoker:
        underlying = original_invoker(target)

        def invoke(*, payload: bytes, session_id: str) -> RuntimeReply:
            nonlocal terminated
            reply = underlying(payload=payload, session_id=session_id)
            if target.dataset_version == "retail-v1" and not terminated:
                terminated = True
                reply.body.close()
                flow.events.append("simulate-sigterm")
                handler = active[0]
                assert callable(handler)
                handler(signal.SIGTERM, None)
            return reply

        return invoke

    monkeypatch.setattr(flow, "invoker", invoker)
    with pytest.raises(KeyboardInterrupt, match="termination requested"):
        with interruption_guard():
            flow.run("sigterm")
    result = json.loads((flow.root / "sigterm/campaign-result.json").read_text())
    assert result["restored"] is result["smoke_passed"] is True
    assert result["accepted"] is False and result["error_type"] == "KeyboardInterrupt"
    assert flow.events.index("restore-original") > flow.events.index("simulate-sigterm")
    assert [purpose for purpose, _, _ in flow.calls] == ["warmup", "restoration_smoke"]
    assert flow.ledger.summary()["used"] == flow.ledger.summary()["completed"] == 2
    assert flow.ledger.summary()["failures"] == 1
    assert len(changes) == 2 and changes[0][0] == changes[1][0] == signal.SIGTERM
    assert active[0] is previous and changes[-1][1] is previous


def test_complete_operator_command_uses_explicit_review_and_bound_temporary_campaign(
    flow: Flow, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import signal

    from enterprise_analytics_agent.retail_evaluation import (
        repair_cli,
        repair_config,
        repair_workflow,
    )

    review_file = flow.root / repair_config.REVIEW_PATH
    review_file.write_text(flow.review.model_dump_json())
    version_file = flow.root / "fake-uploaded-version.json"
    version_file.write_text(flow.version.model_dump_json())
    directory = flow.root / "command"
    original_run = repair_workflow.run_repair

    def select(name: str, path: Path | None) -> Any:
        return repair_config.select_repair(name, path, repository_root=flow.root)

    def operations(
        review: RepairReview,
        version: CandidateVersionBinding,
        output: Path,
        *,
        restore_only: bool,
    ) -> RepairOperations:
        assert review == flow.review and version == flow.version
        assert output == directory and restore_only is False
        return flow.operations

    def execute(
        review: RepairReview,
        version: CandidateVersionBinding,
        selected: RepairOperations,
        output: Path,
        *,
        restore_only: bool,
    ) -> dict[str, object]:
        return original_run(
            review,
            version,
            selected,
            output,
            repository_root=flow.root,
            restore_only=restore_only,
        )

    monkeypatch.setattr(
        repair_cli, "load_review", lambda: repair_config.load_review(repository_root=flow.root)
    )
    monkeypatch.setattr(repair_cli, "select_repair", select)
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.repair_operations.operations_for", operations
    )
    monkeypatch.setattr(repair_workflow, "run_repair", execute)
    original_handler = signal.getsignal(signal.SIGTERM)
    result = repair_cli.main(
        [
            "--campaign",
            "q18-repair-v1",
            "run",
            "--invoke-live",
            "--version-record",
            str(version_file),
            "--report-dir",
            str(directory),
        ]
    )
    assert result == 0 and signal.getsignal(signal.SIGTERM) is original_handler
    state = json.loads(capsys.readouterr().out)
    assert state["accepted"] is state["restored"] is state["smoke_passed"] is True
    assert state["campaign"]["used"] == state["campaign"]["completed"] == 39
    assert flow.ledger.summary()["campaign"] == "milestone-5-q18-repair-v1"
    assert (directory / "suite/report.json").is_file()
