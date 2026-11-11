"""Full validation orchestration with authored phases and no cloud clients."""

import hashlib
import json
import subprocess
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from test_ui_release import template_for

from enterprise_analytics_agent.agent.contracts import AgentResponse
from enterprise_analytics_agent.retail_evaluation.client import RuntimeReply
from enterprise_analytics_agent.retail_evaluation.deployment import TEMPLATE_NAME
from enterprise_analytics_agent.retail_evaluation.full_live import FullLiveReview
from infrastructure.agentcore import full_live


@pytest.fixture
def workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    review = FullLiveReview(
        parity_template_sha256="1" * 64, expires_at=datetime.now(UTC) + timedelta(days=1)
    )
    root = tmp_path.resolve()
    review_path = root / "review.json"
    review_path.write_text(review.model_dump_json())
    state = SimpleNamespace(
        root=root,
        review=review,
        review_path=review_path,
        output=root / "artifacts/full-live/operations/attempt",
        events=[],
        fail={},
        initial_version="13",
        counts={"athena_parity": 0, "retail": 0, "agent_parity": 0, "restoration_smoke": 0},
        stopped=False,
        sdk_failed=False,
    )

    class Budget:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def stop(self, reason: str) -> None:
            state.events.append("stop")
            state.stopped = True

        @contextmanager
        def counted_sdk(self, phase: str) -> Any:
            assert phase == "restoration_smoke"
            if getattr(state, "unreadable_budget", False):
                raise RuntimeError("authored unreadable accounting; no SDK dispatched")
            state.events.append("reserve-smoke")
            state.counts[phase] += 1
            try:
                yield
            except BaseException:
                state.sdk_failed = True
                raise

        def summary(self) -> dict[str, Any]:
            if getattr(state, "unreadable_budget", False):
                raise RuntimeError("authored unreadable accounting")
            result = {
                "runtime_used": sum(v for k, v in state.counts.items() if k != "athena_parity"),
                "direct_athena_submissions": getattr(
                    state, "reported_athena", state.counts["athena_parity"]
                ),
                "phases": state.counts.copy(),
                "failed": state.sdk_failed,
                "incomplete": False,
                "stopped": state.stopped,
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
        limits = {"athena_parity": 67, "retail": 36, "agent_parity": 19}
        if name in limits:
            state.counts[name] += limits[name]
        return name != getattr(state, "failing_phase", None)

    state.ops = {"verify": verify, "deploy": deploy, "smoke": smoke}
    state.phase = phase
    monkeypatch.setattr(full_live, "ROOT", root)
    monkeypatch.chdir(root)
    monkeypatch.setattr(full_live, "FullLiveBudget", Budget)
    monkeypatch.setattr(full_live, "_operator_lease", lambda root: nullcontext())
    monkeypatch.setattr(boto3, "Session", lambda *a, **k: pytest.fail("No AWS session is allowed"))
    return state


def execute(state: SimpleNamespace, *, restore_only: bool = False) -> dict[str, Any]:
    return full_live.execute(
        state.review,
        state.review_path,
        state.output,
        restore_only=restore_only,
        ops=state.ops,
        phase_runner=state.phase,
    )


def claim(state: SimpleNamespace, *, checksum: str | None = None) -> Path:
    path: Path = state.root / "artifacts/full-live/full-live-v1/execution-claim.json"
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


def test_full_workflow_runs_every_phase_then_restores_and_uses_only_protected_smoke(
    workflow: SimpleNamespace,
) -> None:
    result = execute(workflow)
    assert workflow.events == [
        "verify-retail",
        "phase-offline",
        "phase-athena_parity",
        "phase-retail",
        "deploy-parity",
        "phase-agent_parity",
        "deploy-retail",
        "reserve-smoke",
        "smoke",
    ]
    assert result["accepted"] is True
    assert result["restored"] is True
    assert result["restoration_smoke_passed"] is True
    assert result["budget"]["runtime_used"] == 56
    assert result["budget"]["direct_athena_submissions"] == 67
    assert json.loads((workflow.output / "result.json").read_text()) == result
    assert (
        json.loads((workflow.output / "restored-checkpoint.json").read_text())["runtime"][
            "agentRuntimeVersion"
        ]
        == "15"
    )


def test_starting_version_drift_stops_before_any_test_or_mutation(
    workflow: SimpleNamespace,
) -> None:
    workflow.initial_version = "14"
    result = execute(workflow)
    assert workflow.events == ["verify-retail"]
    assert result["accepted"] is False
    assert result["temporary_update_attempted"] is False
    assert result["budget"]["runtime_used"] == 0
    assert "error" in result


def test_insufficient_initial_window_stops_before_claim_or_operations(
    workflow: SimpleNamespace,
) -> None:
    workflow.review = workflow.review.model_copy(
        update={"expires_at": datetime.now(UTC) + timedelta(hours=3)}
    )
    with pytest.raises(ValueError):
        execute(workflow)
    assert workflow.events == []
    assert not workflow.output.exists()
    assert not (workflow.root / "artifacts/full-live/full-live-v1/execution-claim.json").exists()


@pytest.mark.parametrize("submissions", [0, 66, 202])
def test_green_pytest_reports_cannot_accept_missing_or_excess_athena_accounting(
    workflow: SimpleNamespace, submissions: int
) -> None:
    workflow.reported_athena = submissions
    result = execute(workflow)
    assert result["tests_passed"] is True
    assert result["restoration_smoke_passed"] is True
    assert result["accepted"] is False


@pytest.mark.parametrize("flag", ["failed", "incomplete", "stopped"])
def test_green_pytest_reports_cannot_override_incomplete_or_failed_budget_evidence(
    workflow: SimpleNamespace, flag: str
) -> None:
    workflow.invalid_budget_flag = flag
    result = execute(workflow)
    assert result["tests_passed"] is True
    assert result["budget"][flag] is True
    assert result["accepted"] is False


@pytest.mark.parametrize("phase", ["offline", "athena_parity"])
def test_failed_phase_before_runtime_calls_does_not_deploy_or_spend_smoke(
    workflow: SimpleNamespace, phase: str
) -> None:
    workflow.failing_phase = phase
    result = execute(workflow)
    assert result["accepted"] is False
    assert result["temporary_update_attempted"] is False
    assert not any(event.startswith("deploy-") for event in workflow.events)
    assert "smoke" not in workflow.events
    assert "reserve-smoke" not in workflow.events
    assert workflow.events[-1] == "stop"


def test_failed_retail_after_runtime_calls_verifies_retained_retail_and_spends_only_smoke(
    workflow: SimpleNamespace,
) -> None:
    workflow.failing_phase = "retail"
    result = execute(workflow)
    assert result["accepted"] is False
    assert result["temporary_update_attempted"] is False
    assert result["restored"] is True
    assert result["restoration_smoke_passed"] is True
    assert result["budget"]["runtime_used"] == 37
    assert not any(event.startswith("deploy-") for event in workflow.events)
    assert workflow.events[-4:] == ["stop", "verify-retail", "reserve-smoke", "smoke"]


def test_failed_retail_before_any_runtime_call_keeps_protected_slot_unspent(
    workflow: SimpleNamespace,
) -> None:
    def phase(name: str, *args: Any) -> bool:
        workflow.events.append("phase-" + name)
        return name != "retail"

    workflow.phase = phase
    result = execute(workflow)
    assert result["accepted"] is False
    assert result["temporary_update_attempted"] is False
    assert result["budget"]["runtime_used"] == 0
    assert "reserve-smoke" not in workflow.events
    assert "smoke" not in workflow.events
    assert not any(event.startswith("deploy-") for event in workflow.events)


def test_insufficient_window_after_retail_preserves_retained_state_and_protected_smoke(
    workflow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Clock:
        current = datetime.now(UTC)

        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return cls.current

    original = workflow.phase

    def phase(name: str, *args: Any) -> bool:
        passed = original(name, *args)
        if name == "retail":
            Clock.current = workflow.review.expires_at - timedelta(minutes=90)
        return bool(passed)

    monkeypatch.setattr(full_live, "datetime", Clock)
    workflow.phase = phase
    result = execute(workflow)
    assert result["accepted"] is False
    assert result["temporary_update_attempted"] is False
    assert not any(event.startswith("deploy-") for event in workflow.events)
    assert workflow.events[-3:] == ["verify-retail", "reserve-smoke", "smoke"]


def test_unreadable_budget_does_not_erase_primary_error_or_block_state_verification(
    workflow: SimpleNamespace,
) -> None:
    workflow.failing_phase = "offline"
    workflow.unreadable_budget = True
    result = execute(workflow)
    assert result["accepted"] is False
    assert workflow.events.count("verify-retail") == 2
    assert not any(event.startswith("deploy-") for event in workflow.events)
    assert "smoke" not in workflow.events
    assert result["error"]["causes"][0]["error_type"] == "RuntimeError"
    assert result["budget_error"]["causes"][0]["error_type"] == "RuntimeError"
    assert result["budget"]["runtime_used"] is None
    assert json.loads((workflow.output / "result.json").read_text()) == result


def test_failed_parity_update_still_restores_original_candidate_retail(
    workflow: SimpleNamespace,
) -> None:
    workflow.fail["deploy-parity"] = ConnectionError("authored deployment failure")
    result = execute(workflow)
    assert result["accepted"] is False
    assert result["temporary_update_attempted"] is True
    assert result["restored"] is True
    assert result["restoration_smoke_passed"] is True
    assert "phase-agent_parity" not in workflow.events
    assert workflow.events[-3:] == ["deploy-retail", "reserve-smoke", "smoke"]
    assert result["error"]["causes"][0]["error_type"] == "ConnectionError"


def test_failed_agent_tests_restore_and_preserve_failure_not_acceptance(
    workflow: SimpleNamespace,
) -> None:
    workflow.failing_phase = "agent_parity"
    result = execute(workflow)
    assert result["accepted"] is False
    assert result["restored"] is True
    assert result["restoration_smoke_passed"] is True
    assert result["phases"]["agent_parity"] is False
    assert workflow.events[-4:] == ["stop", "deploy-retail", "reserve-smoke", "smoke"]


@pytest.mark.parametrize("interrupted", ["deploy-parity", "phase-agent_parity"])
def test_interruption_after_attempted_update_requires_restoration(
    workflow: SimpleNamespace, interrupted: str
) -> None:
    workflow.fail[interrupted] = KeyboardInterrupt()
    result = execute(workflow)
    assert result["accepted"] is False
    assert result["interruption"] == "KeyboardInterrupt"
    assert result["restored"] is True
    assert workflow.events[-3:] == ["deploy-retail", "reserve-smoke", "smoke"]


def test_failed_restoration_keeps_primary_and_cleanup_error_separate(
    workflow: SimpleNamespace,
) -> None:
    workflow.failing_phase = "agent_parity"
    workflow.fail["deploy-retail"] = TimeoutError("authored cleanup failure")
    result = execute(workflow)
    assert result["accepted"] is False
    assert result["restored"] is False
    assert result["error"]["causes"][0]["error_type"] == "RuntimeError"
    assert result["restoration_error"]["causes"][0]["error_type"] == "TimeoutError"
    assert "reserve-smoke" not in workflow.events


def test_failed_smoke_spends_its_slot_and_never_retries(workflow: SimpleNamespace) -> None:
    workflow.fail["smoke"] = ValueError("authored wrong Q18 value")
    result = execute(workflow)
    assert result["accepted"] is False
    assert result["restored"] is True
    assert result["budget"]["phases"]["restoration_smoke"] == 1
    assert result["budget"]["failed"] is True
    assert workflow.events.count("smoke") == 1


@pytest.mark.parametrize("present", [False, True])
def test_restoration_only_requires_a_matching_retained_attempt(
    workflow: SimpleNamespace, present: bool
) -> None:
    if present:
        claim(workflow, checksum="0" * 64)
    with pytest.raises(ValueError):
        execute(workflow, restore_only=True)
    assert workflow.events == []


def test_restoration_only_does_not_rerun_tests_or_reopen_ordinary_dispatch(
    workflow: SimpleNamespace,
) -> None:
    claim(workflow)
    result = execute(workflow, restore_only=True)
    assert workflow.events == ["deploy-retail", "reserve-smoke", "smoke"]
    assert result["restored"] is True
    assert result["restoration_smoke_passed"] is True
    assert result["accepted"] is False
    assert result["phases"] == {}


def test_restoration_does_not_depend_on_constructible_accounting(
    workflow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim(workflow)

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("authored unreadable or aliased accounting")

    monkeypatch.setattr(full_live, "FullLiveBudget", unavailable)
    result = execute(workflow, restore_only=True)
    assert workflow.events == ["deploy-retail"]
    assert result["accepted"] is False
    assert result["restored"] is True
    assert not result.get("restoration_smoke_passed", False)
    assert "budget_error" in result
    assert result["budget"]["runtime_used"] is None
    assert json.loads((workflow.output / "result.json").read_text()) == result


def test_existing_output_is_preserved_and_no_operation_runs(workflow: SimpleNamespace) -> None:
    workflow.output.mkdir(parents=True)
    path = workflow.output / "retained.txt"
    path.write_text("preserve this evidence")
    with pytest.raises(ValueError, match="Preserve"):
        execute(workflow)
    assert path.read_text() == "preserve this evidence"
    assert workflow.events == []


def test_changed_athena_profile_config_fails_before_clients_sources_or_budget(
    workflow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = workflow.root / "infrastructure/cdk/config.development.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"profile": "default"}))
    monkeypatch.setattr(
        full_live,
        "local_review",
        lambda *a, **k: pytest.fail("Source inspection must follow configuration verification"),
    )
    monkeypatch.setattr(
        full_live,
        "FullLiveBudget",
        lambda *a, **k: pytest.fail("No campaign may be opened for a changed profile"),
    )
    with pytest.raises(ValueError, match="Athena development configuration differs"):
        full_live.verify_offline(workflow.review, root=workflow.root)
    assert workflow.events == []
    assert not (workflow.root / "artifacts").exists()


def restoration_provider(
    state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    """Real provider closure, fake only configuration proofs and SDK boundaries."""
    retail = template_for("candidate")
    parity = deepcopy(retail)
    environment = parity["Resources"]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"]
    settings = json.loads(environment["ANALYTICS_RUNTIME_CONFIG"])
    settings.update(dataset_version="parity-v1", tenant_id="t1", reference_date="2025-02-01")
    environment["ANALYTICS_RUNTIME_CONFIG"] = json.dumps(settings, sort_keys=True)
    checksum = hashlib.sha256((json.dumps(parity, indent=2) + "\n").encode()).hexdigest()
    state.review = state.review.model_copy(update={"parity_template_sha256": checksum})
    prepared = state.root / "artifacts/full-live/prepared"
    directory = prepared / "retail"
    directory.mkdir(parents=True)
    (directory / TEMPLATE_NAME).write_text(json.dumps(retail, indent=2) + "\n")
    # Deliberately omit the parity assembly, retail.json, source and canonical
    # files: none is needed to restore the frozen retail configuration.
    monkeypatch.setattr(full_live, "PREPARED", prepared)
    metadata = SimpleNamespace(baseline=None, deployed=[], retail=retail, parity=parity)

    def local(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["restore_only"] is True
        return {"scope": "authored frozen restoration proof"}

    class Session:
        def client(self, name: str, **kwargs: Any) -> Any:
            assert kwargs["config"].retries["total_max_attempts"] == 1
            if name == "sts":
                return SimpleNamespace(get_caller_identity=lambda: {"Account": "453711491609"})
            if name == "cloudformation":
                return SimpleNamespace()
            pytest.fail("Unexpected SDK construction: " + name)

    def session(**kwargs: Any) -> Session:
        assert kwargs == {"profile_name": "analytics-dev", "region_name": "us-west-2"}
        return Session()

    class Controller:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            metadata.baseline = kwargs["baseline_validator"]

        def deploy(self, assembly: str, version: str, kind: str, verify: Any, **kwargs: Any) -> Any:
            assert kind == "retail" and Path(assembly) == directory
            assert version == state.review.artifact_version_id
            metadata.baseline(
                {"Parameters": [{"ParameterKey": "ArtifactVersionId", "ParameterValue": version}]},
                parity,
            )
            metadata.deployed.append(kind)
            return verify(120)

    query = {
        "api_version": "v2",
        "metric_id": "net_revenue",
        "time_range": {"api_version": "v2", "start": "2025-03-31", "end": "2025-04-01"},
        "group_by": [],
        "dimension_filters": {},
    }
    metadata.response = {
        "status": "answer",
        "answer": "Authored independent Q18 total: 110.25 USD",
        "dataset_version": "retail-v1",
        "metric_versions": {"net_revenue": "1.0.0"},
        "results": [
            {
                "api_version": "v2",
                "metric_id": "net_revenue",
                "definition_version": "1.0.0",
                "time_range": query["time_range"],
                "group_by": [],
                "unit": "currency",
                "currency": "USD",
                "rows": [{"api_version": "v2", "dimensions": {}, "value": "110.25"}],
            }
        ],
        "diagnostics": {
            "model_id": state.review.model_id,
            "configuration": {
                "model_id": state.review.model_id,
                "reference_date": "2025-04-01",
                "max_iterations": 6,
                "max_tool_calls": 16,
                "max_output_tokens": 1024,
                "max_total_tokens": 12000,
                "timeout_seconds": 90.0,
            },
            "tool_calls": [
                {
                    "tool_use_id": "authored-Q18",
                    "name": "query_metric",
                    "arguments": query,
                    "status": "success",
                }
            ],
            "athena": [
                {
                    "metric_id": "net_revenue",
                    "metric_version": "1.0.0",
                    "dataset_version": "retail-v1",
                    "state": "SUCCEEDED",
                    "scanned_bytes": 64,
                    "query_id": "authored-query",
                }
            ],
        },
    }

    def invoker(target: Any, **kwargs: Any) -> Any:
        assert target.dataset_version == "retail-v1"
        assert target.reference_date.isoformat() == "2025-04-01"
        assert target.runtime_arn == state.review.runtime_arn

        def invoke(**arguments: Any) -> RuntimeReply:
            assert json.loads(arguments["payload"]) == {
                "question": "Show net_revenue for yesterday."
            }
            parsed = AgentResponse.model_validate(metadata.response)
            return RuntimeReply(BytesIO(parsed.model_dump_json().encode()), "authored-invocation")

        return invoke

    monkeypatch.setattr(full_live, "verify_offline", local)
    monkeypatch.setattr(boto3, "Session", session)
    monkeypatch.setattr(full_live, "DeploymentController", Controller)
    monkeypatch.setattr(full_live, "create_runtime_invoker", invoker)
    monkeypatch.setattr(
        full_live, "checkpoint", lambda *args, **kwargs: {"runtime": {"agentRuntimeVersion": "15"}}
    )
    metadata.calls = full_live.operations(state.review, state.output, restore_only=True)
    return metadata


def test_restoration_provider_accepts_reviewed_parity_without_source_or_parity_files(
    workflow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = restoration_provider(workflow, monkeypatch)
    assert provider.calls["deploy"]("retail")["runtime"]["agentRuntimeVersion"] == "15"
    assert str(provider.calls["smoke"]().results[0].rows[0].value) == "110.25"
    assert provider.deployed == ["retail"]


@pytest.mark.parametrize("drift", ["extra-row", "grouping", "wrong-version", "wrong-plan"])
def test_restoration_smoke_requires_complete_q18_shape_and_plan(
    workflow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    provider = restoration_provider(workflow, monkeypatch)
    result = provider.response["results"][0]
    if drift == "extra-row":
        result["rows"].append({"api_version": "v2", "dimensions": {}, "value": "999.00"})
    elif drift == "grouping":
        result["group_by"] = ["region"]
        result["rows"][0]["dimensions"] = {"region": "North"}
    elif drift == "wrong-version":
        result["definition_version"] = "2.0.0"
        provider.response["metric_versions"]["net_revenue"] = "2.0.0"
    else:
        provider.response["diagnostics"]["tool_calls"][0]["arguments"]["group_by"] = ["region"]
    with pytest.raises(ValueError):
        provider.calls["smoke"]()


@pytest.mark.parametrize(
    "count,child,status,expected",
    [
        (18, None, 0, True),
        (18, "skipped", 0, False),
        (18, "failure", 0, False),
        (18, "error", 0, False),
        (18, "duplicate-case", 0, False),
        (17, None, 0, False),
        (0, None, 0, False),
        (18, None, 1, False),
    ],
)
def test_phase_requires_exact_count_and_no_junit_skip_failure_or_error(
    workflow: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    child: str | None,
    status: int,
    expected: bool,
) -> None:
    import xml.etree.ElementTree as ET

    workflow.output.mkdir(parents=True)
    commands: list[list[str]] = []

    class Process:
        def __init__(self, command: list[str], **kwargs: Any) -> None:
            commands.append(command)
            assert "--fail-on-skip" in command
            assert kwargs["env"]["ANALYTICS_FULL_LIVE_APPROVAL"] == workflow.review.sha256

        def wait(self, timeout: int) -> int:
            assert timeout == 1800
            report = ET.Element("testsuite")
            for index in range(count):
                name = "0" if child == "duplicate-case" and index == count - 1 else str(index)
                case = ET.SubElement(report, "testcase", name=name)
                if index == 0 and child in {"skipped", "failure", "error"}:
                    ET.SubElement(case, child)
            ET.ElementTree(report).write(workflow.output / "agent_parity/junit.xml")
            return status

    monkeypatch.setattr(subprocess, "Popen", Process)
    assert (
        full_live.run_phase("agent_parity", workflow.review, workflow.review_path, workflow.output)
        is expected
    )
    assert len(commands) == 1
    assert "agent_live" in commands[0]
