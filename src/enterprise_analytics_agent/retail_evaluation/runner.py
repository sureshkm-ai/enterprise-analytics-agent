"""Injectable suite runner; saved-response replay is the default and never creates an SDK client."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, cast
from uuid import uuid4

from enterprise_analytics_agent.agent.contracts import AgentResponse
from enterprise_analytics_agent.retail_evaluation.cases import (
    file_sha256,
    load_goldens,
    load_suite,
    verify_frozen_inputs,
)
from enterprise_analytics_agent.retail_evaluation.judge import CaseResult, judge_response
from enterprise_analytics_agent.retail_evaluation.models import (
    RetailGolden,
    RetailSuite,
    RetailTarget,
)
from enterprise_analytics_agent.retail_evaluation.reporting import (
    EvaluationReport,
    append_attempt,
    build_report,
    prepare_run_directory,
    write_report,
    write_run_context,
)

if TYPE_CHECKING:
    from enterprise_analytics_agent.retail_evaluation.client import InvocationResult


class Invoker(Protocol):
    def __call__(self, question: str, *, session_id: str | None = None) -> InvocationResult: ...


def run_suite(
    suite: RetailSuite,
    goldens: RetailGolden,
    target: RetailTarget,
    invoker: Invoker,
    *,
    run_id: str | None = None,
    mode: Literal["replay", "live"] = "replay",
    evidence: dict[str, object] | None = None,
    campaign: dict[str, object] | None = None,
    restoration: dict[str, object] | None = None,
    on_case: Callable[[CaseResult], None] | None = None,
) -> EvaluationReport:
    """Keep failures in denominators and stop dispatch after an infrastructure failure."""
    if target.dataset_version != suite.dataset_version:
        raise ValueError("retail suite cannot run against a non-retail deployment target")
    expected = {golden.case_id: golden for golden in goldens.cases}
    if set(expected) != {case.id for case in suite.cases}:
        raise ValueError("frozen expectations do not cover the complete suite")
    results: list[CaseResult] = []
    sessions: dict[str, str] = {}
    stopped = False
    for case in suite.cases:
        if stopped:
            results.append(
                CaseResult(
                    case_id=case.id,
                    question=case.question,
                    kind=case.kind,
                    status="unrun",
                    reasons=("dispatch stopped after an infrastructure failure",),
                    expected_queries=case.expected_queries,
                    expected_results=expected[case.id].results,
                )
            )
            if on_case is not None:
                on_case(results[-1])
            continue
        session_id = (
            sessions.setdefault(case.session_group, str(uuid4()))
            if case.session_group
            else str(uuid4())
        )
        try:
            invocation = invoker(case.question, session_id=session_id)
            result = judge_response(
                case,
                expected[case.id],
                invocation.response,
                target,
                elapsed_ms=invocation.elapsed_ms,
                raw_response=invocation.raw_response,
                invocation_id=invocation.invocation_id,
            )
            stopped = invocation.response.status == "error" and not (
                case.kind == "authorization"
                and invocation.response.error_code in case.safe_error_codes
            )
        except Exception as error:
            # Retain the failure category without leaking request headers, SQL or SDK credentials.
            result = CaseResult(
                case_id=case.id,
                question=case.question,
                kind=case.kind,
                status="failed",
                reasons=("invocation/body/configuration failed; inspect the reserved attempt",),
                expected_queries=case.expected_queries,
                expected_results=expected[case.id].results,
                error_type=type(error).__name__,
                extras={"dispatch_error_code": getattr(error, "code", None)},
            )
            stopped = True
        results.append(result)
        if on_case is not None:
            on_case(result)
    return build_report(
        tuple(results),
        target,
        run_id=run_id or str(uuid4()),
        mode=mode,
        evidence=evidence,
        campaign=campaign,
        restoration=restoration,
    )


class ReplayInvoker:
    """One saved response per case in suite order; no network-capable dependencies are used."""

    def __init__(self, suite: RetailSuite, directory: Path) -> None:
        self.cases = iter(suite.cases)
        self.directory = directory

    def __call__(self, question: str, *, session_id: str | None = None) -> InvocationResult:
        from enterprise_analytics_agent.retail_evaluation.client import InvocationResult

        case = next(self.cases)
        if question != case.question:
            raise ValueError("replay question/order differs from the reviewed suite")
        value = json.loads((self.directory / f"{case.id}.json").read_text())
        if not isinstance(value, dict):
            raise ValueError("saved response must be a JSON object")
        response_raw = value.get("response", value)
        if not isinstance(response_raw, dict):
            raise ValueError("saved response body must be a JSON object")
        raw = cast(dict[str, object], response_raw)
        elapsed = value.get("elapsed_ms")
        if elapsed is not None and (type(elapsed) is not int or elapsed < 0):
            raise ValueError("saved client latency must be a nonnegative integer")
        return InvocationResult(
            response=AgentResponse.model_validate(raw),
            elapsed_ms=elapsed,
            invocation_id=None,
            raw_response=raw,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", type=Path, default=Path("evaluations/retail-v1/questions.json")
    )
    parser.add_argument(
        "--expected", type=Path, default=Path("evaluations/retail-v1/expected-results.json")
    )
    parser.add_argument("--target-config", type=Path, required=True)
    parser.add_argument(
        "--provenance", type=Path, default=Path("evaluations/retail-v1/oracle-provenance.json")
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--response-dir", type=Path, help="saved responses; no AWS operations")
    mode.add_argument("--invoke-live", action="store_true", help="requires separate live approval")
    parser.add_argument(
        "--report-dir", type=Path, required=True, help="new, unique output directory"
    )
    parser.add_argument("--run-id", default=None)
    arguments = parser.parse_args(argv)
    try:
        suite = load_suite(arguments.questions)
        goldens = load_goldens(arguments.expected, suite)
        target = RetailTarget.model_validate_json(arguments.target_config.read_bytes())
        evidence: dict[str, object] = {
            "questions_sha256": file_sha256(arguments.questions),
            "expected_sha256": file_sha256(arguments.expected),
            "manifest_sha256": goldens.manifest_sha256,
            "target_sha256": file_sha256(arguments.target_config),
        }
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        evidence["git_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
        prepare_run_directory(arguments.report_dir)
        ledger = None
        if arguments.invoke_live:
            # All AWS-capable imports and calls sit behind this explicit gate.
            from enterprise_analytics_agent.adapters.agentcore_invocation import (
                create_runtime_invoker,
            )
            from enterprise_analytics_agent.adapters.retail_checkpoint import verify_checkpoint
            from enterprise_analytics_agent.retail_evaluation.campaign import CampaignLedger
            from enterprise_analytics_agent.retail_evaluation.client import CountedAgentClient

            evidence.update(
                verify_frozen_inputs(
                    arguments.questions,
                    arguments.expected,
                    arguments.provenance,
                    goldens,
                )
            )
            checkpoint = verify_checkpoint(scope="retail-v1")
            if checkpoint["runtime"]["agentRuntimeArn"] != target.runtime_arn:
                raise ValueError("verified Runtime differs from the approved target")
            evidence["checkpoint"] = checkpoint
            ledger = CampaignLedger()
            evidence["campaign_before"] = ledger.summary()
            client = CountedAgentClient(target, ledger, create_runtime_invoker(target))
            invoke: Invoker = client.invoke
        else:
            invoke = ReplayInvoker(suite, arguments.response_dir)
        run_identifier = arguments.run_id or str(uuid4())
        write_run_context(
            arguments.report_dir,
            target,
            evidence,
            run_id=run_identifier,
            mode="live" if arguments.invoke_live else "replay",
        )
        report = run_suite(
            suite,
            goldens,
            target,
            invoke,
            run_id=run_identifier,
            mode="live" if arguments.invoke_live else "replay",
            evidence=evidence,
            on_case=lambda case: append_attempt(arguments.report_dir, case),
        )
        if ledger is not None:
            report = report.model_copy(update={"campaign": ledger.summary()})
        write_report(report, arguments.report_dir, prepared=True)
        print(json.dumps(report.summary, indent=2))
        if arguments.invoke_live:
            return 0 if report.summary["live_gates_passed"] else 1
        return 0 if report.summary["failed"] == report.summary["unrun"] == 0 else 1
    except Exception as error:
        print(
            f"evaluation configuration/preflight/replay error: {type(error).__name__}",
            file=sys.stderr,
        )
        return 1
