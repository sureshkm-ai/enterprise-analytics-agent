"""Continuation controller behavior with authored outcomes, never AWS clients."""

import json
import os
import signal
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import boto3
import pytest

from enterprise_analytics_agent.retail_evaluation.full_live import FullLiveContinuationReview
from infrastructure.agentcore import full_live
from infrastructure.agentcore import full_live_continuation as workflow


@pytest.fixture
def continuation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    root = tmp_path.resolve()
    review = FullLiveContinuationReview(
        parity_template_sha256="1" * 64,
        parent_inventory_sha256="2" * 64,
        prepared_inventory_sha256="3" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    review_path = root / "review.json"
    review_path.write_text(review.model_dump_json())
    state = SimpleNamespace(
        root=root,
        review=review,
        review_path=review_path,
        output=root / "artifacts/full-live/operations/continuation",
        events=[],
        fail={},
        initial_version="13",
        counts={"athena_parity": 0, "retail": 0, "agent_parity": 0, "restoration_smoke": 0},
        stopped=False,
        sdk_failed=False,
    )

    class Budget:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            if getattr(state, "constructor_failure", False):
                raise ValueError("authored unavailable parent accounting")

        def stop(self, reason: str) -> None:
            state.events.append("stop")
            state.stopped = True

        @contextmanager
        def counted_sdk(self, phase: str) -> Any:
            assert phase == "restoration_smoke"
            if getattr(state, "unreadable_accounting", False):
                raise ValueError("authored unreadable accounting; no smoke dispatch")
            state.events.append("reserve-smoke")
            state.counts[phase] += 1
            try:
                yield
            except BaseException:
                state.sdk_failed = True
                raise

        def summary(self) -> dict[str, Any]:
            if getattr(state, "unreadable_accounting", False):
                raise ValueError("authored unreadable accounting")
            used = sum(v for k, v in state.counts.items() if k != "athena_parity")
            result = {
                "runtime_used": used,
                "phases": state.counts.copy(),
                "direct_athena_submissions": state.counts["athena_parity"],
                "failed": state.sdk_failed,
                "incomplete": False,
                "stopped": state.stopped,
                "aggregate_runtime_used": 37 + used,
            }
            if flag := getattr(state, "invalid_budget_flag", None):
                result[flag] = True
            return result

    def action(name: str) -> None:
        state.events.append(name)
        if name in state.fail:
            raise state.fail[name]

    def verify(kind: str) -> dict[str, Any]:
        action("verify-" + kind)
        return {"runtime": {"agentRuntimeVersion": state.initial_version}}

    def deploy(kind: str) -> dict[str, Any]:
        action("deploy-" + kind)
        return {"runtime": {"agentRuntimeVersion": "14" if kind == "parity" else "15"}}

    def smoke() -> None:
        action("smoke")

    def phase(name: str, *args: Any) -> bool:
        action("phase-" + name)
        if name == "agent_parity":
            state.counts[name] += getattr(state, "reported_agent_calls", 19)
        return name != getattr(state, "failing_phase", None)

    state.ops = {"verify": verify, "deploy": deploy, "smoke": smoke}
    state.phase = phase
    state.budget_class = Budget
    monkeypatch.setattr(workflow, "ROOT", root)
    monkeypatch.setattr(workflow, "PREPARED", root / "artifacts/full-live/prepared-v2")
    monkeypatch.chdir(root)
    monkeypatch.setattr(workflow, "FullLiveBudget", Budget)
    monkeypatch.setattr(workflow, "_operator_lease", lambda root: nullcontext())
    monkeypatch.setattr(boto3, "Session", lambda *a, **k: pytest.fail("No AWS session allowed"))
    workflow._PHASE.clear()
    yield state
    workflow._PHASE.clear()


def execute(state: SimpleNamespace, *, restore_only: bool = False) -> dict[str, Any]:
    return workflow.execute(
        state.review,
        state.review_path,
        state.output,
        restore_only=restore_only,
        ops=state.ops,
        phase_runner=state.phase,
    )


def claim(state: SimpleNamespace, *, checksum: str | None = None) -> Path:
    path: Path = state.root / "artifacts/full-live/full-live-continuation-v1/execution-claim.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "review_sha256": checksum or state.review.sha256,
                "output": str(state.root / "artifacts/full-live/operations/prior"),
                "parent_pid": 0,
            }
        )
    )
    return path


def test_remaining_tests_run_once_and_restore_with_new_protected_slot(
    continuation: SimpleNamespace,
) -> None:
    result = execute(continuation)
    assert continuation.events == [
        "verify-retail",
        "phase-offline",
        "deploy-parity",
        "phase-agent_parity",
        "deploy-retail",
        "reserve-smoke",
        "smoke",
    ]
    assert result["accepted"] is True
    assert result["restored"] is result["restoration_smoke_passed"] is True
    assert result["budget"]["runtime_used"] == 20
    assert result["budget"]["aggregate_runtime_used"] == 57
    assert result["budget"]["direct_athena_submissions"] == 0
    assert result["phases"] == {"offline": True, "agent_parity": True}
    assert json.loads((continuation.output / "result.json").read_text()) == result


def test_fresh_v13_drift_stops_before_tests_or_deployment(continuation: SimpleNamespace) -> None:
    continuation.initial_version = "14"
    result = execute(continuation)
    assert continuation.events == ["verify-retail"]
    assert not result["accepted"] and not result["temporary_update_attempted"]
    assert result["budget"]["runtime_used"] == 0


def test_initial_cleanup_window_is_required_before_output_or_claim(
    continuation: SimpleNamespace,
) -> None:
    continuation.review = continuation.review.model_copy(
        update={"expires_at": datetime.now(UTC) + timedelta(hours=3)}
    )
    with pytest.raises(ValueError, match="four hours"):
        execute(continuation)
    assert continuation.events == [] and not continuation.output.exists()
    assert not (
        continuation.root / "artifacts/full-live/full-live-continuation-v1/execution-claim.json"
    ).exists()


def test_offline_failure_spends_nothing_and_does_not_change_runtime(
    continuation: SimpleNamespace,
) -> None:
    continuation.failing_phase = "offline"
    result = execute(continuation)
    assert continuation.events == ["verify-retail", "phase-offline", "stop"]
    assert not result["accepted"] and not result["temporary_update_attempted"]
    assert result["budget"]["runtime_used"] == 0


def test_switch_window_is_rechecked_after_offline_verification(
    continuation: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Clock:
        current = datetime.now(UTC)

        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return cls.current

    original = continuation.phase

    def phase(name: str, *args: Any) -> bool:
        passed = original(name, *args)
        Clock.current = continuation.review.expires_at - timedelta(minutes=90)
        return bool(passed)

    monkeypatch.setattr(workflow, "datetime", Clock)
    continuation.phase = phase
    result = execute(continuation)
    assert continuation.events == ["verify-retail", "phase-offline"]
    assert not result["accepted"] and not result["temporary_update_attempted"]


@pytest.mark.parametrize("point", ["deploy-parity", "phase-agent_parity"])
@pytest.mark.parametrize("failure", [ConnectionError, KeyboardInterrupt])
def test_failure_or_interruption_after_update_attempt_always_restores(
    continuation: SimpleNamespace, point: str, failure: type[BaseException]
) -> None:
    continuation.fail[point] = failure("authored failure")
    result = execute(continuation)
    assert not result["accepted"] and result["temporary_update_attempted"]
    assert result["restored"] and result["restoration_smoke_passed"]
    assert continuation.events[-3:] == ["deploy-retail", "reserve-smoke", "smoke"]
    assert result["error"]["causes"][0]["error_type"] == failure.__name__
    if failure is KeyboardInterrupt:
        assert result["interruption"] == "KeyboardInterrupt"


def test_agent_failure_is_not_retried_or_accepted_after_successful_restoration(
    continuation: SimpleNamespace,
) -> None:
    continuation.failing_phase = "agent_parity"
    result = execute(continuation)
    assert not result["accepted"] and result["restored"]
    assert result["phases"]["agent_parity"] is False
    assert continuation.events.count("phase-agent_parity") == 1
    assert continuation.events[-4:] == ["stop", "deploy-retail", "reserve-smoke", "smoke"]


def test_primary_failure_survives_failed_restoration(continuation: SimpleNamespace) -> None:
    continuation.fail["deploy-parity"] = ConnectionError("primary")
    continuation.fail["deploy-retail"] = TimeoutError("restoration")
    result = execute(continuation)
    assert not result["accepted"] and not result["restored"]
    assert result["error"]["causes"][0]["error_type"] == "ConnectionError"
    assert result["restoration_error"]["causes"][0]["error_type"] == "TimeoutError"
    assert "reserve-smoke" not in continuation.events


def test_failed_smoke_is_spent_once_and_never_retried(continuation: SimpleNamespace) -> None:
    continuation.fail["smoke"] = ValueError("wrong Q18 value")
    result = execute(continuation)
    assert not result["accepted"] and result["restored"]
    assert result["budget"]["failed"] is True
    assert result["budget"]["phases"]["restoration_smoke"] == 1
    assert continuation.events.count("smoke") == 1


@pytest.mark.parametrize("flag", ["failed", "incomplete", "stopped"])
def test_green_tests_cannot_override_invalid_budget_evidence(
    continuation: SimpleNamespace, flag: str
) -> None:
    continuation.invalid_budget_flag = flag
    result = execute(continuation)
    assert result["tests_passed"] and result["restoration_smoke_passed"]
    assert not result["accepted"] and result["budget"][flag]


@pytest.mark.parametrize("count", [0, 18, 20])
def test_green_agent_tests_require_exact_nineteen_runtime_attempts(
    continuation: SimpleNamespace, count: int
) -> None:
    continuation.reported_agent_calls = count
    result = execute(continuation)
    assert result["tests_passed"] and not result["accepted"]


def test_unavailable_accounting_after_tests_does_not_block_nonbillable_restoration(
    continuation: SimpleNamespace,
) -> None:
    original = continuation.phase

    def phase(name: str, *args: Any) -> bool:
        passed = original(name, *args)
        if name == "agent_parity":
            continuation.unreadable_accounting = True
        return bool(passed)

    continuation.phase = phase
    result = execute(continuation)
    assert result["restored"] and not result["accepted"]
    assert result["budget"]["runtime_used"] is None
    assert "budget_error" in result and "restoration_error" in result
    assert "smoke" not in continuation.events
    assert json.loads((continuation.output / "result.json").read_text()) == result


def test_duplicate_attempt_preserves_claim_and_never_dispatches(
    continuation: SimpleNamespace,
) -> None:
    path = claim(continuation)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        execute(continuation)
    assert path.read_bytes() == original and continuation.events == []


@pytest.mark.parametrize("kind", ["missing", "changed", "aliased", "outside-output"])
def test_restore_only_requires_matching_unaliased_retained_attempt(
    continuation: SimpleNamespace, kind: str
) -> None:
    if kind != "missing":
        path = claim(continuation, checksum="0" * 64 if kind == "changed" else None)
        if kind == "aliased":
            saved = path.with_suffix(".saved.json")
            path.rename(saved)
            path.symlink_to(saved)
        if kind == "outside-output":
            raw = json.loads(path.read_bytes())
            raw["output"] = str(continuation.root / "outside")
            path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        execute(continuation, restore_only=True)
    assert continuation.events == []


def test_restore_only_does_not_repeat_tests_or_reopen_ordinary_work(
    continuation: SimpleNamespace,
) -> None:
    claim(continuation)
    result = execute(continuation, restore_only=True)
    assert continuation.events == ["deploy-retail", "reserve-smoke", "smoke"]
    assert result["restored"] and result["restoration_smoke_passed"]
    assert not result["accepted"] and result["phases"] == {}


def test_restore_only_can_restore_without_trustworthy_parent_accounting(
    continuation: SimpleNamespace,
) -> None:
    claim(continuation)
    continuation.constructor_failure = True
    result = execute(continuation, restore_only=True)
    assert continuation.events == ["deploy-retail"]
    assert result["restored"] and not result["accepted"]
    assert result["budget"]["runtime_used"] is None
    assert "budget_setup_error" in result and "budget_error" in result
    assert not result.get("restoration_smoke_passed", False)


@pytest.mark.parametrize(
    "count,child,exitcode,expected",
    [
        (18, None, 0, True),
        (18, "skipped", 0, False),
        (18, "failure", 0, False),
        (18, "error", 0, False),
        (18, "duplicate", 0, False),
        (17, None, 0, False),
        (0, None, 0, False),
        (18, None, 1, False),
    ],
)
def test_agent_phase_accepts_only_all_eighteen_unique_executed_items(
    continuation: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    child: str | None,
    exitcode: int,
    expected: bool,
) -> None:
    import xml.etree.ElementTree as ET

    continuation.output.mkdir(parents=True)
    commands = []

    class Process:
        def __init__(self, command: list[str], **kwargs: Any) -> None:
            commands.append(command)
            assert "--fail-on-skip" in command and "--run-agent-live" in command
            assert "infrastructure.agentcore.full_live_continuation" in command
            assert kwargs["env"]["ANALYTICS_FULL_CONTINUATION_APPROVAL"] == (
                continuation.review.sha256
            )

        def wait(self, timeout: int) -> int:
            assert timeout == 1800
            report = ET.Element("testsuite")
            for index in range(count):
                name = "0" if child == "duplicate" and index == count - 1 else str(index)
                case = ET.SubElement(report, "testcase", classname="authored", name=name)
                if index == 0 and child in {"skipped", "failure", "error"}:
                    ET.SubElement(case, child)
            ET.ElementTree(report).write(continuation.output / "agent_parity/junit.xml")
            return exitcode

    monkeypatch.setattr(subprocess, "Popen", Process)
    assert (
        workflow.run_phase(
            "agent_parity", continuation.review, continuation.review_path, continuation.output
        )
        is expected
    )
    assert len(commands) == 1


@pytest.mark.parametrize(
    "interrupted", [subprocess.TimeoutExpired("pytest", 1800), KeyboardInterrupt()]
)
def test_phase_cleanup_signals_only_its_owned_group_and_preserves_interruption(
    continuation: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    interrupted: BaseException,
) -> None:
    continuation.output.mkdir(parents=True)
    signals = []
    waits = []

    class Process:
        pid = 12345

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            assert kwargs["start_new_session"] is True

        def poll(self) -> None:
            return None

        def wait(self, timeout: int) -> int:
            waits.append(timeout)
            if timeout == 1800:
                raise interrupted
            return -15

    monkeypatch.setattr(subprocess, "Popen", Process)
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(type(interrupted)):
        workflow.run_phase(
            "agent_parity", continuation.review, continuation.review_path, continuation.output
        )
    assert waits == [1800, 5]
    assert signals == [(12345, signal.SIGTERM)]


def test_phase_cleanup_escalates_only_its_owned_group_with_bounded_waits(
    continuation: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    continuation.output.mkdir(parents=True)
    signals = []
    waits = []
    original = subprocess.TimeoutExpired("pytest", 1800)

    class Process:
        pid = 12345

        def __init__(self, command: list[str], **kwargs: Any) -> None:
            assert kwargs["start_new_session"] is True

        def poll(self) -> None:
            return None

        def wait(self, timeout: int) -> int:
            waits.append(timeout)
            if len(waits) == 1:
                raise original
            if len(waits) == 2:
                raise subprocess.TimeoutExpired("owned-child", 5)
            return -9

    monkeypatch.setattr(subprocess, "Popen", Process)
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        workflow.run_phase(
            "agent_parity", continuation.review, continuation.review_path, continuation.output
        )
    assert caught.value is original
    assert waits == [1800, 5, 5]
    assert signals == [(12345, signal.SIGTERM), (12345, signal.SIGKILL)]


def test_operation_setup_failure_remains_diagnostic_without_mutation_or_invocation(
    continuation: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("authored operator-read setup failure")

    monkeypatch.setattr(full_live, "operations", unavailable)
    result = workflow.execute(
        continuation.review,
        continuation.review_path,
        continuation.output,
        phase_runner=continuation.phase,
    )
    assert continuation.events == []
    assert not result["accepted"] and not result["temporary_update_attempted"]
    assert result["error"]["causes"][0]["error_type"] == "ConnectionError"
    assert result["budget"]["runtime_used"] == 0
    assert json.loads((continuation.output / "result.json").read_text()) == result


def test_child_plugin_requires_review_path_config_and_parent_binding(
    continuation: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = claim(continuation)
    saved = json.loads(path.read_bytes())
    saved["parent_pid"] = os.getppid()
    path.write_text(json.dumps(saved))
    monkeypatch.setenv("ANALYTICS_FULL_CONTINUATION_REVIEW", str(continuation.review_path))
    monkeypatch.setenv("ANALYTICS_FULL_CONTINUATION_APPROVAL", continuation.review.sha256)
    checks = []
    monkeypatch.setattr(
        full_live,
        "verify_offline",
        lambda *a, **k: checks.append((a, k)),
    )
    config = cast(
        pytest.Config,
        SimpleNamespace(getoption=lambda option: str(workflow.PREPARED / "agent.parity.json")),
    )
    workflow.pytest_configure(config)
    assert "budget" in workflow._PHASE and len(checks) == 1
    assert checks[0][1]["prepared"] == workflow.PREPARED


@pytest.mark.parametrize("drift", ["approval", "config", "parent-review", "parent-pid"])
def test_child_plugin_rejects_mismatched_operator_bindings_before_sdk_guard(
    continuation: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    path = claim(continuation)
    saved = json.loads(path.read_bytes())
    saved["parent_pid"] = os.getppid()
    if drift == "parent-review":
        saved["review_sha256"] = "0" * 64
    elif drift == "parent-pid":
        saved["parent_pid"] = -1
    path.write_text(json.dumps(saved))
    monkeypatch.setenv("ANALYTICS_FULL_CONTINUATION_REVIEW", str(continuation.review_path))
    monkeypatch.setenv(
        "ANALYTICS_FULL_CONTINUATION_APPROVAL",
        "0" * 64 if drift == "approval" else continuation.review.sha256,
    )
    monkeypatch.setattr(full_live, "verify_offline", lambda *a, **k: {})
    selected = (
        continuation.root / "unreviewed.json"
        if drift == "config"
        else workflow.PREPARED / "agent.parity.json"
    )
    config = cast(pytest.Config, SimpleNamespace(getoption=lambda option: str(selected)))
    with pytest.raises(pytest.UsageError):
        workflow.pytest_configure(config)
    assert workflow._PHASE == {}


def test_live_cli_flag_is_required_before_any_operation(
    continuation: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        workflow,
        "execute",
        lambda *a, **k: pytest.fail("An execution flag is necessary before operator dispatch"),
    )
    assert (
        workflow.main(
            ["run", "--review", str(continuation.review_path), "--output", str(continuation.output)]
        )
        == 1
    )
    assert not continuation.output.exists()
