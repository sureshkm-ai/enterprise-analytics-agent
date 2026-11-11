"""A new operator campaign must not reuse historical retail accounting or skip checks."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import boto3
import pytest
from test_retail_live import test_approved_retail_campaign as run_retail_pytest_item
from test_retail_reporting import EVIDENCE, authored_response

from enterprise_analytics_agent.retail_evaluation import runner
from enterprise_analytics_agent.retail_evaluation.cases import load_goldens, load_suite
from enterprise_analytics_agent.retail_evaluation.client import InvocationResult
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.retail_evaluation.runner import LiveRunDependencies


@dataclass
class InjectedRun:
    dependencies: LiveRunDependencies
    target: RetailTarget
    arguments: list[str]
    directory: Path
    calls: list[tuple[str, str | None]]
    events: list[str]
    proof: dict[str, object]


@pytest.fixture
def injected_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> InjectedRun:
    """Real frozen requests/judge/report flow with only trusted external bindings replaced."""
    target = RetailTarget.model_validate_json((EVIDENCE / "target.json").read_bytes())
    suite = load_suite(EVIDENCE / "questions.json")
    goldens = load_goldens(EVIDENCE / "expected-results.json", suite)
    remaining = iter(zip(suite.cases, goldens.cases, strict=True))
    directory = tmp_path / "new-campaign"
    config = tmp_path / "target.json"
    config.write_text(target.model_dump_json())
    arguments = [
        "--questions",
        str(EVIDENCE / "questions.json"),
        "--expected",
        str(EVIDENCE / "expected-results.json"),
        "--provenance",
        str(EVIDENCE / "oracle-provenance.json"),
        "--target-config",
        str(config),
        "--invoke-live",
        "--report-dir",
        str(directory),
    ]
    calls: list[tuple[str, str | None]] = []
    events: list[str] = []
    proof: dict[str, object] = {
        "runtime": {"agentRuntimeArn": target.runtime_arn},
        "observed_at": datetime(2026, 11, 11, 17, 0, tzinfo=UTC),
    }

    def checkpoint(selected: RetailTarget) -> dict[str, object]:
        assert selected == target
        events.append("checkpoint")
        return proof

    def invoke(question: str, *, session_id: str | None = None) -> InvocationResult:
        # Durable, serializable run context must precede any billable dispatch.
        context = json.loads((directory / "run-context.json").read_bytes())
        assert context["mode"] == "live"
        case, golden = next(remaining)
        assert case.question == question
        calls.append((question, session_id))
        events.append("invoke")
        observed = authored_response(case, golden)
        return InvocationResult(observed, 25, case.id, observed.model_dump(mode="json"))

    def summary() -> dict[str, object]:
        events.append("summary")
        return {"campaign_id": "new-reviewed-full-suite", "used": len(calls), "maximum": 56}

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("injected execution must not construct AWS or the historical campaign")

    monkeypatch.setattr(boto3, "Session", forbidden)
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.agentcore_invocation.create_runtime_invoker",
        forbidden,
    )
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.retail_checkpoint.verify_checkpoint", forbidden
    )
    monkeypatch.setattr(
        "enterprise_analytics_agent.retail_evaluation.campaign.CampaignLedger", forbidden
    )
    return InjectedRun(
        LiveRunDependencies(checkpoint, invoke, summary),
        target,
        arguments,
        directory,
        calls,
        events,
        proof,
    )


def test_injected_complete_command_preserves_all_36_cases_and_the_session_pair(
    injected_run: InjectedRun,
) -> None:
    run = injected_run
    assert runner.main(run.arguments, live_dependencies=run.dependencies) == 0
    assert len(run.calls) == 36
    assert len({session for _, session in run.calls[:-2]}) == 34
    assert run.calls[-2][1] == run.calls[-1][1]
    assert run.calls[-2][1] not in {session for _, session in run.calls[:-2]}
    assert run.events == ["checkpoint", "summary", *("invoke" for _ in range(36)), "summary"]
    report = json.loads((run.directory / "report.json").read_bytes())
    context = json.loads((run.directory / "run-context.json").read_bytes())
    assert report["summary"]["passed"] == 36
    assert report["summary"]["failed"] == report["summary"]["unrun"] == 0
    assert report["summary"]["live_gates_passed"] is True
    assert context["evidence"]["campaign_before"]["used"] == 0
    assert report["campaign"]["used"] == 36
    assert len((run.directory / "attempts.jsonl").read_text().splitlines()) == 36


@pytest.mark.parametrize("bad", [{}, {"agentRuntimeArn": "wrong"}, None])
def test_wrong_checkpoint_cannot_invoke_or_read_new_campaign_budget(
    injected_run: InjectedRun, bad: object
) -> None:
    run = injected_run
    run.proof["runtime"] = bad
    assert runner.main(run.arguments, live_dependencies=run.dependencies) == 1
    assert run.calls == [] and run.events == ["checkpoint"]
    assert not (run.directory / "run-context.json").exists()


def test_checkpoint_failure_retains_no_incomplete_context_or_invocation(
    injected_run: InjectedRun, capsys: pytest.CaptureFixture[str]
) -> None:
    run = injected_run

    def failed(target: RetailTarget) -> dict[str, object]:
        raise TimeoutError("private preflight details")

    dependencies = LiveRunDependencies(failed, run.dependencies.invoke, run.dependencies.summary)
    assert runner.main(run.arguments, live_dependencies=dependencies) == 1
    assert run.calls == [] and run.events == []
    assert not (run.directory / "run-context.json").exists()
    assert "TimeoutError" in capsys.readouterr().err


def test_frozen_input_failure_precedes_operator_checkpoint_or_dispatch(
    injected_run: InjectedRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = injected_run

    def unfrozen(*args: Any) -> dict[str, object]:
        raise ValueError("authored frozen input mismatch")

    monkeypatch.setattr(runner, "verify_frozen_inputs", unfrozen)
    assert runner.main(run.arguments, live_dependencies=run.dependencies) == 1
    assert run.calls == [] and run.events == []


def test_checkpoint_serialization_failure_happens_before_invocation(
    injected_run: InjectedRun,
) -> None:
    run = injected_run
    run.proof["unsupported"] = object()
    assert runner.main(run.arguments, live_dependencies=run.dependencies) == 1
    assert run.calls == [] and run.events == ["checkpoint", "summary"]
    assert not (run.directory / "run-context.json").exists()


def test_summary_failure_precedes_context_and_dispatch(injected_run: InjectedRun) -> None:
    run = injected_run

    def failed_summary() -> dict[str, object]:
        raise ValueError("new campaign receipt mismatch")

    dependencies = LiveRunDependencies(
        run.dependencies.checkpoint, run.dependencies.invoke, failed_summary
    )
    assert runner.main(run.arguments, live_dependencies=dependencies) == 1
    assert run.calls == [] and run.events == ["checkpoint"]
    assert not (run.directory / "run-context.json").exists()


def test_replay_rejects_live_bindings_before_loading_or_creating_output(
    injected_run: InjectedRun,
) -> None:
    run = injected_run
    args = [arg for arg in run.arguments if arg != "--invoke-live"]
    args.extend(["--response-dir", "unused"])
    assert runner.main(args, live_dependencies=run.dependencies) == 1
    assert run.calls == [] and run.events == []
    assert not run.directory.exists()


def test_existing_output_does_not_verify_or_dispatch(injected_run: InjectedRun) -> None:
    run = injected_run
    run.directory.mkdir()
    assert runner.main(run.arguments, live_dependencies=run.dependencies) == 1
    assert run.calls == [] and run.events == []


def test_transport_failure_stops_new_dispatch_and_keeps_final_count(
    injected_run: InjectedRun,
) -> None:
    run = injected_run

    def failed(question: str, *, session_id: str | None = None) -> InvocationResult:
        run.calls.append((question, session_id))
        raise TimeoutError("authored transport failure")

    dependencies = LiveRunDependencies(
        run.dependencies.checkpoint, failed, run.dependencies.summary
    )
    assert runner.main(run.arguments, live_dependencies=dependencies) == 1
    report = json.loads((run.directory / "report.json").read_bytes())
    assert len(run.calls) == report["campaign"]["used"] == 1
    assert report["summary"]["failed"] == 1 and report["summary"]["unrun"] == 35
    assert report["cases"][0]["error_type"] == "TimeoutError"


def test_interruption_preserves_completed_attempt_and_context(
    injected_run: InjectedRun,
) -> None:
    run = injected_run

    def interrupted(question: str, *, session_id: str | None = None) -> InvocationResult:
        if run.calls:
            raise KeyboardInterrupt()
        return run.dependencies.invoke(question, session_id=session_id)

    dependencies = LiveRunDependencies(
        run.dependencies.checkpoint, interrupted, run.dependencies.summary
    )
    with pytest.raises(KeyboardInterrupt):
        runner.main(run.arguments, live_dependencies=dependencies)
    rows = (run.directory / "attempts.jsonl").read_text().splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["case_id"] == "Q01"
    assert (run.directory / "run-context.json").is_file()
    assert not (run.directory / "report.json").exists()


def test_pytest_entry_uses_reviewed_dependencies_and_separate_output(
    injected_run: InjectedRun,
) -> None:
    run = injected_run
    request = cast(
        pytest.FixtureRequest,
        SimpleNamespace(
            config=SimpleNamespace(
                _reviewed_retail_report_dir=run.directory,
                getoption=lambda name: run.arguments[run.arguments.index("--target-config") + 1],
            )
        ),
    )
    run_retail_pytest_item(request, run.dependencies)
    assert len(run.calls) == 36 and (run.directory / "report.json").is_file()


@pytest.mark.parametrize("path", ["not-a-Path", 1, False])
def test_pytest_entry_rejects_untyped_report_output_before_invocation(
    injected_run: InjectedRun, path: object
) -> None:
    run = injected_run
    request = cast(
        pytest.FixtureRequest,
        SimpleNamespace(config=SimpleNamespace(_reviewed_retail_report_dir=path)),
    )
    with pytest.raises(pytest.UsageError, match="trusted live dependencies"):
        run_retail_pytest_item(request, run.dependencies)
    assert run.calls == [] and run.events == []


def test_pytest_entry_cannot_redirect_original_campaign_report(
    injected_run: InjectedRun,
) -> None:
    run = injected_run
    request = cast(
        pytest.FixtureRequest,
        SimpleNamespace(config=SimpleNamespace(_reviewed_retail_report_dir=run.directory)),
    )
    with pytest.raises(pytest.UsageError, match="trusted live dependencies"):
        run_retail_pytest_item(request, None)
    assert run.calls == [] and run.events == []


def test_default_command_still_uses_original_checkpoint_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "target.json"
    config.write_bytes((EVIDENCE / "target.json").read_bytes())
    observed: list[str] = []

    def historical(*, scope: str) -> dict[str, object]:
        observed.append(scope)
        raise RuntimeError("original checkpoint rejects the candidate")

    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.retail_checkpoint.verify_checkpoint", historical
    )
    assert (
        runner.main(
            [
                "--invoke-live",
                "--target-config",
                str(config),
                "--report-dir",
                str(tmp_path / "default"),
            ]
        )
        == 1
    )
    assert observed == ["retail-v1"]
