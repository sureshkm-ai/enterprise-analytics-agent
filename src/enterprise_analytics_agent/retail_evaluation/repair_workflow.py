"""Repeatable repair campaign with injected operations and mandatory original restoration."""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from enterprise_analytics_agent.retail_evaluation.agent_cli import _check_restoration_smoke
from enterprise_analytics_agent.retail_evaluation.campaign import (
    CampaignLedger,
    RepairCampaignBinding,
    RestorationProof,
)
from enterprise_analytics_agent.retail_evaluation.cases import (
    file_sha256,
    load_goldens,
    load_suite,
    verify_frozen_inputs,
)
from enterprise_analytics_agent.retail_evaluation.client import CountedAgentClient, RuntimeInvoker
from enterprise_analytics_agent.retail_evaluation.judge import judge_response
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    REPOSITORY_ROOT,
    CandidateVersionBinding,
    RepairReview,
)
from enterprise_analytics_agent.retail_evaluation.reporting import (
    append_attempt,
    prepare_run_directory,
    write_report,
    write_run_context,
)
from enterprise_analytics_agent.retail_evaluation.runner import run_suite

WARMUP = "Show net_revenue for January 2025 by region."


@dataclass(frozen=True)
class RepairOperations:
    """AWS operations are supplied by the adapter, never by model/tool arguments."""

    verify_original: Callable[[], RestorationProof]
    deploy_candidate: Callable[[], None]
    verify_candidate: Callable[[], dict[str, Any]]
    restore_original: Callable[[], None]
    invoker: Callable[[RetailTarget], RuntimeInvoker]


def campaign_binding(
    review: RepairReview, version: CandidateVersionBinding
) -> RepairCampaignBinding:
    version.require_review(review)
    from enterprise_analytics_agent.retail_evaluation.deployment import canonical_hash

    return RepairCampaignBinding(
        campaign_id=review.campaign_id,
        ledger_path=review.ledger_path,
        maximum=review.maximum,
        review_sha256=review.review_sha256,
        candidate_sha256=review.candidate_sha256,
        candidate_template_sha256=review.candidate_template_sha256,
        candidate_version_record_sha256=canonical_hash(version.model_dump(mode="json")),
    )


def _write(path: Path, value: object) -> None:
    # Complete encoding before creating write-once operator evidence.
    encoded = json.dumps(value, indent=2) + "\n"
    with path.open("x") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def run_repair(
    review: RepairReview,
    version: CandidateVersionBinding,
    operations: RepairOperations,
    directory: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    restore_only: bool = False,
) -> dict[str, object]:
    """No automatic invocation retries; failed probe stops the suite and always restores.

    Resuming a partly used campaign runs restoration only. Re-running the whole
    campaign cannot silently consume the protected quota or reset its history.
    """
    binding = campaign_binding(review, version)
    evidence_root = repository_root / "evaluations/retail-v1"
    restored_target = RetailTarget(
        runtime_arn=review.runtime_arn, dataset_version="parity-v1", reference_date="2025-02-01"
    )
    suite = goldens = None
    frozen: dict[str, object] = {}
    target = restored_target
    if not restore_only:
        suite = load_suite(evidence_root / "questions.json")
        goldens = load_goldens(evidence_root / "expected-results.json", suite)
        if (
            file_sha256(evidence_root / "questions.json"),
            file_sha256(evidence_root / "expected-results.json"),
        ) != (review.questions_sha256, review.expected_results_sha256):
            raise ValueError("repair questions or independent frozen answers changed")
        frozen = verify_frozen_inputs(
            evidence_root / "questions.json",
            evidence_root / "expected-results.json",
            evidence_root / "oracle-provenance.json",
            goldens,
        )
        target = RetailTarget.model_validate_json((evidence_root / "target.json").read_bytes())
        if target.runtime_arn != review.runtime_arn or target.dataset_version != "retail-v1":
            raise ValueError("retail target differs from the reviewed Runtime/scope")
    ledger = CampaignLedger(binding=binding, repository_root=repository_root)
    initial = ledger.summary()
    if not restore_only and initial["used"] != 0:
        raise ValueError("repair campaign already used; resume restoration without resetting it")
    prepare_run_directory(directory)
    write_run_context(
        directory,
        target,
        {
            "review": review.model_dump(mode="json"),
            "candidate_version": version.model_dump(mode="json"),
            "frozen": frozen,
            "campaign_before": initial,
        },
        run_id=str(uuid4()),
        mode="live",
    )
    state: dict[str, object] = {
        "campaign_id": review.campaign_id,
        "accepted": False,
        "candidate_attempted": restore_only,
        "probe_passed": False,
        "suite_passed": False,
        "restored": False,
        "smoke_passed": False,
    }
    interrupted: BaseException | None = None
    try:
        if not restore_only:
            assert suite is not None and goldens is not None
            original = operations.verify_original()
            if original.runtime_version != "6" or original.runtime_arn != review.runtime_arn:
                raise ValueError("original deployment version drifted from reviewed v6 checkpoint")
            _write(directory / "original-proof.json", original.model_dump(mode="json"))
            state["candidate_attempted"] = True
            operations.deploy_candidate()
            checkpoint = operations.verify_candidate()
            if checkpoint["runtime"]["agentRuntimeArn"] != target.runtime_arn:
                raise ValueError("candidate checkpoint differs from invocation target")
            # Reuse the context encoder for nested AWS timestamps and redaction.
            ready = directory / "candidate-ready"
            prepare_run_directory(ready)
            write_run_context(
                ready, target, {"checkpoint": checkpoint}, run_id="candidate-ready", mode="live"
            )
            warmup = CountedAgentClient(
                target, ledger, operations.invoker(target), purpose="warmup"
            )
            warm = warmup.invoke(WARMUP)
            _write(directory / "warmup.json", warm.response.model_dump(mode="json"))
            if warm.response.status != "answer":
                raise ValueError("warm-up did not produce an answer")
            case = next(case for case in suite.cases if case.id == "Q18")
            golden = next(row for row in goldens.cases if row.case_id == "Q18")
            probe = CountedAgentClient(target, ledger, operations.invoker(target), purpose="probe")
            reply = probe.invoke(case.question)
            assessed = judge_response(
                case,
                golden,
                reply.response,
                target,
                elapsed_ms=reply.elapsed_ms,
                raw_response=reply.raw_response,
                invocation_id=reply.invocation_id,
            )
            _write(directory / "probe.json", assessed.model_dump(mode="json"))
            if assessed.status != "passed":
                raise ValueError("Q18 probe failed its complete frozen plan/result criteria")
            state["probe_passed"] = True
            client = CountedAgentClient(target, ledger, operations.invoker(target), purpose="case")
            suite_directory = directory / "suite"
            prepare_run_directory(suite_directory)
            write_run_context(
                suite_directory,
                target,
                {
                    "checkpoint": checkpoint,
                    "review_sha256": review.review_sha256,
                    "frozen": frozen,
                    "campaign_before": ledger.summary(),
                },
                run_id="repair-suite",
                mode="live",
            )
            report = run_suite(
                suite,
                goldens,
                target,
                client.invoke,
                mode="live",
                run_id="repair-suite",
                evidence={
                    "review_sha256": review.review_sha256,
                    "candidate_sha256": review.candidate_sha256,
                    "frozen": frozen,
                },
                on_case=lambda result: append_attempt(suite_directory, result),
            )
            report = report.model_copy(update={"campaign": ledger.summary()})
            write_report(report, suite_directory, prepared=True)
            state["suite_passed"] = bool(report.summary["live_gates_passed"])
    except BaseException as exc:
        state["error_type"] = type(exc).__name__
        if not isinstance(exc, Exception):
            interrupted = exc
    finally:
        if state["candidate_attempted"]:
            try:
                operations.restore_original()
                proof = operations.verify_original()
                if proof.runtime_arn != restored_target.runtime_arn:
                    raise ValueError("restoration checkpoint differs from invocation target")
                _write(directory / "restored-proof.json", proof.model_dump(mode="json"))
                state["restored"] = True
                smoke = CountedAgentClient(
                    restored_target,
                    ledger,
                    operations.invoker(restored_target),
                    purpose="restoration_smoke",
                    restoration_verifier=operations.verify_original,
                )
                response = smoke.invoke(WARMUP)
                _write(directory / "smoke.json", response.response.model_dump(mode="json"))
                _check_restoration_smoke(response.response)
                state["smoke_passed"] = True
            except BaseException as exc:
                state["restoration_error_type"] = type(exc).__name__
                if not isinstance(exc, Exception):
                    interrupted = exc
        state["campaign"] = ledger.summary()
        state["accepted"] = bool(
            state["probe_passed"]
            and state["suite_passed"]
            and state["restored"]
            and state["smoke_passed"]
        )
        _write(directory / "campaign-result.json", state)
    if interrupted is not None:
        raise interrupted
    return state
