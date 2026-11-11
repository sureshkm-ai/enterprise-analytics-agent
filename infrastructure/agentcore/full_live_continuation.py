"""Offline-prepared continuation of the incomplete full-live run; new approval required."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from enterprise_analytics_agent.retail_evaluation.full_live import (
    FullLiveBudget,
    FullLiveContinuationReview,
)
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record
from enterprise_analytics_agent.retail_evaluation.reporting import _redact
from infrastructure.agentcore import full_live
from infrastructure.agentcore.ui_workflow import _operator_lease

ROOT = full_live.ROOT
PREPARED = ROOT / "artifacts/full-live/prepared-v2"
REVIEW_PATH = ROOT / "evaluations/full-live/continuation.proposed.json"
_PHASE: dict[str, Any] = {}


def run_phase(
    phase: str, review: FullLiveContinuationReview, review_path: Path, output: Path
) -> bool:
    if phase == "offline":
        return full_live.run_phase(phase, review, review_path, output)
    if phase != "agent_parity":
        raise ValueError("Continuation permits only offline and remaining agent tests")
    reports = output / phase
    reports.mkdir()
    env = dict(os.environ)
    env.update(
        ANALYTICS_FULL_CONTINUATION_REVIEW=str(review_path.resolve()),
        ANALYTICS_FULL_CONTINUATION_APPROVAL=review.sha256,
    )
    args = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "-p",
        "infrastructure.agentcore.full_live_continuation",
        "--fail-on-skip",
        "-x",
        "-q",
        "-m",
        "agent_live",
        "--run-agent-live",
        "--agent-config=" + str(PREPARED / "agent.parity.json"),
        "--junitxml=" + str(reports / "junit.xml"),
    ]
    with (reports / "pytest.log").open("x") as log:
        process = subprocess.Popen(
            args, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            status = process.wait(timeout=1800)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            raise
    if status != 0:
        return False
    import xml.etree.ElementTree as ET

    cases = list(ET.parse(reports / "junit.xml").getroot().iter("testcase"))
    return (
        len(cases) == 18
        and len({(case.get("classname"), case.get("name")) for case in cases}) == 18
        and not any(
            case.find(tag) is not None for case in cases for tag in ("skipped", "failure", "error")
        )
    )


def execute(
    review: FullLiveContinuationReview,
    review_path: Path,
    output: Path,
    *,
    restore_only: bool = False,
    ops: dict[str, Callable[..., Any]] | None = None,
    phase_runner: Callable[..., bool] = run_phase,
) -> dict[str, Any]:
    if Path.cwd().resolve() != ROOT.resolve():
        raise ValueError("Use the reviewed repository root")
    if output.exists():
        raise ValueError("Preserve earlier continuation evidence")
    if (
        not restore_only
        and (review.expires_at - datetime.now(UTC)).total_seconds() < full_live.MIN_START_SECONDS
    ):
        raise ValueError("Less than four hours remain for tests and restoration")
    output.mkdir(parents=True)
    budget = None
    result: dict[str, Any] = {
        "review_sha256": review.sha256,
        "accepted": False,
        "phases": {},
        "temporary_update_attempted": False,
        "restored": False,
    }
    try:
        budget = FullLiveBudget(review, repository_root=ROOT)
    except Exception as exc:
        if not restore_only:
            raise
        result["budget_setup_error"] = error_record(exc, "continuation-budget-setup")
    calls = None
    claim = ROOT / "artifacts/full-live/full-live-continuation-v1/execution-claim.json"
    with _operator_lease(ROOT):
        if restore_only:
            if not claim.exists() or claim.is_symlink():
                raise ValueError("No valid retained continuation claim to restore")
            retained = json.loads(claim.read_bytes())
            if retained.get("review_sha256") != review.sha256:
                raise ValueError("Retained continuation review differs")
            previous = Path(retained.get("output", "")).resolve()
            if not previous.is_relative_to(ROOT / "artifacts/full-live"):
                raise ValueError("Retained continuation output differs")
        else:
            full_live.write(
                claim,
                {"review_sha256": review.sha256, "output": str(output), "parent_pid": os.getpid()},
            )
        try:
            calls = ops or full_live.operations(
                review, output, restore_only=restore_only, prepared=PREPARED
            )
            if not restore_only:
                assert budget is not None
                proof = calls["verify"]("retail")
                if proof["runtime"]["agentRuntimeVersion"] != review.starting_runtime_version:
                    raise ValueError("Fresh accepted-retail starting version differs")
                full_live.write(output / "starting-checkpoint.json", proof)
                result["phases"]["offline"] = phase_runner("offline", review, review_path, output)
                if not result["phases"]["offline"]:
                    budget.stop("continuation_offline_failed")
                    raise RuntimeError("Offline verification failed; no deployment")
                if (
                    review.expires_at - datetime.now(UTC)
                ).total_seconds() < full_live.MIN_SWITCH_SECONDS:
                    raise ValueError("Less than two hours remain for parity and restoration")
                result["temporary_update_attempted"] = True
                full_live.write(output / "parity-checkpoint.json", calls["deploy"]("parity"))
                result["phases"]["agent_parity"] = phase_runner(
                    "agent_parity", review, review_path, output
                )
                if not result["phases"]["agent_parity"]:
                    budget.stop("continuation_agent_parity_failed")
                    raise RuntimeError("Remaining agent tests failed; no billable retry")
                result["tests_passed"] = True
        except BaseException as exc:
            result["error"] = error_record(exc, "full-live-continuation")
            if not isinstance(exc, Exception):
                result["interruption"] = type(exc).__name__
        finally:
            if calls is not None and (restore_only or result["temporary_update_attempted"]):
                try:
                    full_live.write(output / "restored-checkpoint.json", calls["deploy"]("retail"))
                    result["restored"] = True
                    if budget is None:
                        raise ValueError("Accounting unavailable; no smoke dispatch")
                    with budget.counted_sdk("restoration_smoke"):
                        calls["smoke"]()
                    result["restoration_smoke_passed"] = True
                except BaseException as exc:
                    result["restoration_error"] = error_record(exc, "continuation-restoration")
            try:
                if budget is None:
                    raise ValueError("Accounting unavailable")
                result["budget"] = budget.summary()
            except Exception as exc:
                result["budget"] = {"runtime_used": None}
                result["budget_error"] = error_record(exc, "continuation-accounting")
            state = result["budget"]
            result["accepted"] = bool(
                result.get("tests_passed")
                and result["restored"]
                and result.get("restoration_smoke_passed")
                and not result.get("error")
                and state["runtime_used"] == 20
                and state["phases"]["agent_parity"] == 19
                and state["phases"]["restoration_smoke"] == 1
                and state["direct_athena_submissions"] == 0
                and not state["failed"]
                and not state["incomplete"]
                and not state["stopped"]
            )
            full_live.write(output / "result.json", result)
    return result


def pytest_configure(config: pytest.Config) -> None:
    path = os.environ.get("ANALYTICS_FULL_CONTINUATION_REVIEW")
    if not path:
        return
    review = FullLiveContinuationReview.model_validate_json(Path(path).read_bytes())
    if os.environ.get("ANALYTICS_FULL_CONTINUATION_APPROVAL") != review.sha256:
        raise pytest.UsageError("Continuation approval binding differs")
    full_live.verify_offline(review, prepared=PREPARED)
    selected = config.getoption("agent_config")
    if not selected or Path(selected).resolve() != (PREPARED / "agent.parity.json").resolve():
        raise pytest.UsageError("Continuation agent configuration differs")
    claim = ROOT / "artifacts/full-live/full-live-continuation-v1/execution-claim.json"
    retained = json.loads(claim.read_bytes())
    if retained.get("review_sha256") != review.sha256 or retained.get("parent_pid") != os.getppid():
        raise pytest.UsageError("No matching reviewed parent continuation attempt")
    _PHASE["budget"] = FullLiveBudget(review, repository_root=ROOT)


def pytest_sessionstart(session: pytest.Session) -> None:
    if _PHASE:
        context = _PHASE["budget"].counted_sdk("agent_parity")
        context.__enter__()
        _PHASE["context"] = context


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _PHASE.get("context"):
        _PHASE["context"].__exit__(None, None, None)
        _PHASE.clear()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify-offline", "preflight", "run", "restore"))
    parser.add_argument("--review", type=Path, default=REVIEW_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        review = FullLiveContinuationReview.model_validate_json(args.review.read_bytes())
        if args.action == "verify-offline":
            value = full_live.verify_offline(review, prepared=PREPARED)
            full_live.write(args.output, value)
        elif args.action == "preflight":
            with _operator_lease(ROOT):
                value = full_live.operations(review, args.output, prepared=PREPARED)["verify"](
                    "retail"
                )
                if value["runtime"]["agentRuntimeVersion"] != review.starting_runtime_version:
                    raise ValueError("Fresh v13 starting checkpoint differs")
                full_live.write(args.output / "preflight.json", value)
        else:
            if not args.execute_approved:
                raise ValueError("New continuation approval is required")
            from enterprise_analytics_agent.retail_evaluation.repair_cli import interruption_guard

            with interruption_guard():
                value = execute(
                    review, args.review, args.output, restore_only=args.action == "restore"
                )
        print(json.dumps(_redact(value), indent=2))
        return (
            0
            if args.action not in {"run", "restore"}
            or value.get("accepted")
            or (args.action == "restore" and value.get("restoration_smoke_passed"))
            else 1
        )
    except Exception as exc:
        print(json.dumps(error_record(exc, "continuation-command"), indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
