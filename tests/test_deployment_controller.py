"""Authored offline CDK/CloudFormation lifecycles, including the retained Q18 failure."""

import fcntl
import json
import signal
import subprocess
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from enterprise_analytics_agent.adapters.deployment_controller import (
    STACK_NAME,
    DeploymentController,
    DeploymentError,
    DeploymentLimits,
    DeploymentTimeout,
)
from enterprise_analytics_agent.retail_evaluation.deployment import TEMPLATE_NAME

T0 = datetime(2026, 11, 9, 19, 37, 23, 202000, tzinfo=UTC)
TEMPLATE: dict[str, Any] = {
    "Parameters": {
        "ArtifactVersionId": {"Type": "String"},
        "BootstrapVersion": {
            "Type": "AWS::SSM::Parameter::Value<String>",
            "Default": "/cdk-bootstrap/hnb659fds/version",
        },
    },
    "Resources": {"AnalyticsRuntime": {"Type": "AWS::BedrockAgentCore::Runtime"}},
}
PARAMETERS = [
    {"ParameterKey": "ArtifactVersionId", "ParameterValue": "candidate-version"},
    {
        "ParameterKey": "BootstrapVersion",
        "ParameterValue": "/cdk-bootstrap/hnb659fds/version",
        "ResolvedValue": "30",
    },
]


def state(*, status: str = "UPDATE_COMPLETE", old: bool = False, **changes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "StackName": STACK_NAME,
        "StackId": f"arn:aws:cloudformation:us-west-2:453711491609:stack/{STACK_NAME}/stack-id",
        "StackStatus": status,
        "LastUpdatedTime": T0 if old else T0 + timedelta(seconds=19),
        "Parameters": deepcopy(PARAMETERS),
        "template": {"Resources": {}} if old else deepcopy(TEMPLATE),
    }
    if old:
        result["Parameters"][0]["ParameterValue"] = "original-version"
    result.update(changes)
    return result


@dataclass
class Clock:
    value: float = 0

    def now(self) -> float:
        return self.value

    def sleep(self, value: float) -> None:
        assert 0 <= value <= 5
        self.value += value


@dataclass
class Process:
    clock: Clock
    pid: int = 98765
    returncode: int | None = None
    resist_term: bool = False
    resist_kill: bool = False
    events: list[tuple[str, object]] = field(default_factory=list)

    def poll(self) -> int | None:
        self.events.append(("poll", self.returncode))
        return self.returncode

    def wait(self, *, timeout: float) -> int:
        self.events.append(("wait", timeout))
        if self.returncode is None:
            self.clock.sleep(timeout)
            raise subprocess.TimeoutExpired("authored-cdk", timeout)
        return self.returncode

    def signal(self, pid: int, value: int) -> None:
        assert pid == self.pid, "never signal an unowned process"
        self.events.append(("signal", value))
        if (value == signal.SIGTERM and not self.resist_term) or (
            value == signal.SIGKILL and not self.resist_kill
        ):
            self.returncode = -value


@dataclass
class CloudFormation:
    states: list[dict[str, Any]]
    calls: int = 0
    current: dict[str, Any] = field(default_factory=dict)
    failure: Exception | None = None

    def describe_stacks(self, *, StackName: str) -> dict[str, Any]:
        assert StackName == STACK_NAME
        if self.failure:
            raise self.failure
        self.current = self.states[min(self.calls, len(self.states) - 1)]
        self.calls += 1
        return {
            "Stacks": [{key: value for key, value in self.current.items() if key != "template"}]
        }

    def get_template(self, *, StackName: str, TemplateStage: str) -> dict[str, Any]:
        assert StackName == STACK_NAME and TemplateStage == "Original"
        return {"TemplateBody": deepcopy(self.current["template"])}


@dataclass
class Harness:
    root: Path
    cfn: CloudFormation
    clock: Clock
    child: Process
    launched: list[dict[str, Any]] = field(default_factory=list)
    proofs: list[float] = field(default_factory=list)
    verification_error: BaseException | None = None

    def launch(self, command: list[str], **kwargs: Any) -> Process:
        assert kwargs["start_new_session"] is True
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert command[command.index("--profile") + 1] == "analytics-dev"
        assert command[command.index("--region") + 1] == "us-west-2"
        assert command[command.index("--parameters") + 1] == "ArtifactVersionId=candidate-version"
        kwargs["stdout"].write("authored retained stdout\n")
        kwargs["stderr"].write("deploying... [1/1]\n")
        self.launched.append(kwargs)
        return self.child

    def verify(self, deadline: float) -> dict[str, object]:
        self.proofs.append(deadline)
        if self.verification_error:
            raise self.verification_error
        # The injected real adapter callback verifies the whole reviewed checkpoint:
        # exact Runtime/DEFAULT artifact/version/config/policies/retention and S3 bytes.
        return {"strict": True, "runtime_version": "7", "endpoint_version": "7"}

    def controller(self, directory: str = "run") -> DeploymentController:
        return DeploymentController(
            self.root / directory,
            self.cfn,
            lock_path=self.root / "runtime-deployment.lock",
            limits=DeploymentLimits(
                deployment_seconds=12,
                settle_seconds=9,
                verification_seconds=6,
                cleanup_seconds=2,
                poll_seconds=3,
            ),
            process_factory=self.launch,
            signal_group=self.child.signal,
            group_exists=lambda pid: self.child.returncode is None,
            monotonic=self.clock.now,
            sleep=self.clock.sleep,
        )

    def run(self, controller: DeploymentController | None = None) -> dict[str, Any]:
        active = controller or self.controller()
        active.deploy(str(self.root / "assembly"), "candidate-version", "candidate", self.verify)
        result: dict[str, Any] = json.loads(
            (active.directory / "candidate.controller.json").read_text()
        )
        return result


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    monkeypatch.setattr(
        "boto3.Session", lambda *args, **kwargs: pytest.fail("offline lifecycle test contacted AWS")
    )
    assembly = tmp_path / "assembly"
    assembly.mkdir()
    (assembly / TEMPLATE_NAME).write_text(json.dumps(TEMPLATE))
    clock = Clock()
    return Harness(
        tmp_path, CloudFormation([state(old=True), state(), state()]), clock, Process(clock)
    )


def test_retained_q18_aws_success_with_stalled_cdk_is_verified_and_reaped(harness: Harness) -> None:
    """Original subprocess.run waited1800s and raised before strict candidate verification.

    Authored statuses/times follow the retained19:37 UPDATE_COMPLETE scenario. The
    child never exits by itself, yet complete matching AWS proof enables progress.
    """
    result = harness.run()
    assert result["accepted"] is True
    assert result["completion"] == "fresh_verified_aws_update"
    assert result["cleanup_signals"] == ["SIGTERM"]
    assert result["process_reaped"] is True
    assert len(harness.proofs) == 2, "verify before cleanup and again after it"
    assert harness.clock.value <= 12
    assert (harness.root / "run/candidate.stdout.log").read_text() == "authored retained stdout\n"
    assert (harness.root / "run/candidate.stderr.log").read_text() == "deploying... [1/1]\n"
    assert ("signal", signal.SIGTERM) in harness.child.events


def test_controller_returns_final_proof_only_after_reaping(harness: Harness) -> None:
    observations: list[dict[str, object]] = []

    def verify(deadline: float) -> dict[str, object]:
        proof: dict[str, object] = {
            "strict": True,
            "sequence": len(observations),
            "process_reaped": harness.child.returncode is not None,
        }
        observations.append(proof)
        return proof

    result = harness.controller().deploy(
        str(harness.root / "assembly"), "candidate-version", "candidate", verify
    )
    assert len(observations) == 2
    assert result is observations[-1] and result["process_reaped"] is True
    assert observations[0]["process_reaped"] is False


@pytest.mark.parametrize(
    "drift", ["template", "version", "bootstrap", "parameter_inventory", "stale"]
)
def test_ready_alone_never_accepts_incorrect_or_stale_cfn(harness: Harness, drift: str) -> None:
    actual = state()
    if drift == "template":
        actual["template"]["Resources"]["Unreviewed"] = {"Type": "AWS::S3::Bucket"}
    elif drift == "version":
        actual["Parameters"][0]["ParameterValue"] = "old-or-unreviewed-version"
    elif drift == "bootstrap":
        actual["Parameters"][1]["ParameterValue"] = "different-bootstrap-key"
    elif drift == "parameter_inventory":
        actual["Parameters"].append({"ParameterKey": "Extra", "ParameterValue": "unreviewed"})
    else:
        actual["LastUpdatedTime"] = T0
    harness.cfn.states = [state(old=True), actual]
    with pytest.raises(DeploymentTimeout):
        harness.run()
    assert not harness.proofs
    assert harness.child.returncode == -signal.SIGTERM
    assert (
        json.loads((harness.root / "run/candidate.controller.json").read_text())["accepted"]
        is False
    )


@pytest.mark.parametrize(
    "failure",
    [ValueError("wrong artifact/configuration"), ConnectionError("verification unavailable")],
)
def test_unavailable_or_wrong_runtime_verification_never_accepts(
    harness: Harness, failure: Exception
) -> None:
    harness.verification_error = failure
    with pytest.raises(DeploymentTimeout):
        harness.run()
    assert harness.proofs and harness.clock.value <= 14
    assert harness.child.returncode == -signal.SIGTERM


def test_nonzero_cdk_and_real_rollback_are_failures(harness: Harness) -> None:
    harness.child.returncode = 1
    with pytest.raises(DeploymentError, match="return code 1"):
        harness.run()
    assert not harness.proofs
    assert json.loads((harness.root / "run/candidate.controller.json").read_text())[
        "process_reaped"
    ]


@pytest.mark.parametrize(
    "status",
    ["UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED", "UPDATE_FAILED", "ROLLBACK_COMPLETE"],
)
def test_fresh_terminal_rollback_never_becomes_success(harness: Harness, status: str) -> None:
    harness.cfn.states = [state(old=True), state(status=status)]
    with pytest.raises(DeploymentError, match="failed or rolled back"):
        harness.run()
    assert not harness.proofs
    assert harness.child.returncode == -signal.SIGTERM


def test_unresolved_previous_update_blocks_restoration_overlap(harness: Harness) -> None:
    harness.cfn.states = [state(old=True), state(status="UPDATE_IN_PROGRESS")]
    controller = harness.controller()
    with pytest.raises(DeploymentTimeout):
        harness.run(controller)
    assert len(harness.launched) == 1
    second = harness.controller("restore")
    with pytest.raises(DeploymentTimeout, match="previous AWS update remains unresolved"):
        second.deploy(
            str(harness.root / "assembly"), "candidate-version", "restore", harness.verify
        )
    assert len(harness.launched) == 1, "never overlap the unresolved AWS update"


def test_unavailable_preflight_starts_no_process(harness: Harness) -> None:
    harness.cfn.failure = ConnectionError("cannot establish stable stack")
    with pytest.raises(ConnectionError):
        harness.run()
    assert not harness.launched


def test_zero_exit_is_not_proof_of_aws_success(harness: Harness) -> None:
    harness.child.returncode = 0
    harness.cfn.states = [state(old=True)]
    with pytest.raises(DeploymentTimeout):
        harness.run()
    assert not harness.proofs and harness.clock.value <= 6


def test_interruption_cleans_only_owned_child_and_preserves_logs(harness: Harness) -> None:
    harness.verification_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        harness.run()
    assert harness.child.returncode == -signal.SIGTERM
    assert (
        json.loads((harness.root / "run/candidate.controller.json").read_text())["error_type"]
        == "KeyboardInterrupt"
    )


def test_resistant_child_escalates_bounded_cleanup(harness: Harness) -> None:
    harness.child.resist_term = True
    result = harness.run()
    assert result["accepted"] is True
    assert result["cleanup_signals"] == ["SIGTERM", "SIGKILL"]
    assert harness.child.returncode == -signal.SIGKILL
    assert harness.clock.value == 2


def test_failed_child_cleanup_blocks_any_next_deployment(harness: Harness) -> None:
    harness.child.resist_term = harness.child.resist_kill = True
    controller = harness.controller()
    with pytest.raises(DeploymentError, match="cleanup failed"):
        harness.run(controller)
    assert controller.poisoned
    with pytest.raises(DeploymentError, match="cleanup failed"):
        controller.deploy(
            str(harness.root / "assembly"), "candidate-version", "restore", harness.verify
        )
    assert len(harness.launched) == 1


def test_runtime_lock_prevents_a_second_controller(harness: Harness) -> None:
    lock = harness.root / "runtime-deployment.lock"
    with lock.open("a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(DeploymentError, match="another controller"):
            harness.run()
    assert not harness.launched and harness.cfn.calls == 0


def test_verified_already_current_restore_is_an_explicit_noop(harness: Harness) -> None:
    harness.cfn.states = [state()]
    result = harness.run()
    assert result["completion"] == "already_verified_no_mutation"
    assert result["accepted"] is True
    assert len(harness.proofs) == 1 and not harness.launched


def test_incorrect_runtime_under_matching_stack_blocks_before_mutation(harness: Harness) -> None:
    harness.cfn.states = [state()]
    harness.verification_error = ValueError("wrong original artifact")
    with pytest.raises(ValueError, match="wrong original artifact"):
        harness.run()
    assert not harness.launched


def test_aws_drift_during_owned_child_cleanup_is_rejected(harness: Harness) -> None:
    harness.cfn.states = [state(old=True), state(), state(status="UPDATE_IN_PROGRESS")]
    with pytest.raises(DeploymentError, match="changed during child cleanup"):
        harness.run()
    assert len(harness.proofs) == 1 and harness.child.returncode == -signal.SIGTERM


def test_retained_log_paths_are_never_overwritten(harness: Harness) -> None:
    path = harness.root / "run/candidate.stderr.log"
    path.parent.mkdir()
    path.write_text("retained original evidence")
    with pytest.raises(DeploymentError, match="evidence already exists"):
        harness.run()
    assert path.read_text() == "retained original evidence"
    assert not harness.launched


def test_retained_unresolved_owned_process_blocks_a_new_controller(harness: Harness) -> None:
    journal = harness.root / "runtime-deployment.lock"
    journal.write_text(json.dumps({"active": True, "owner_pid": 456, "process_group": 98765}))
    with pytest.raises(DeploymentError, match="retained task-owned process"):
        harness.run()
    assert not harness.launched and harness.cfn.calls == 0
    assert json.loads(journal.read_text())["active"] is True


def test_unreaped_child_journal_is_retained_after_cleanup_failure(harness: Harness) -> None:
    harness.child.resist_term = harness.child.resist_kill = True
    with pytest.raises(DeploymentError, match="cleanup failed"):
        harness.run()
    journal = json.loads((harness.root / "runtime-deployment.lock").read_text())
    assert journal["active"] is True and journal["process_group"] == harness.child.pid
    with pytest.raises(DeploymentError, match="retained task-owned process"):
        harness.run(harness.controller("another"))
    assert len(harness.launched) == 1


def test_cleanup_includes_owned_descendants_after_parent_exits(harness: Harness) -> None:
    harness.child.returncode = 0
    alive = True
    signals: list[tuple[int, int]] = []

    def signal_descendants(pid: int, value: int) -> None:
        nonlocal alive
        assert pid == harness.child.pid
        signals.append((pid, value))
        if value == signal.SIGKILL:
            alive = False

    controller = harness.controller()
    controller.group_exists = lambda pid: alive
    controller.signal_group = signal_descendants
    result = harness.run(controller)
    assert result["accepted"] and result["process_reaped"]
    assert [value for pid, value in signals] == [signal.SIGTERM, signal.SIGKILL]
    assert harness.clock.value == 2
    assert not json.loads((harness.root / "runtime-deployment.lock").read_text())["active"]


def test_verification_overrun_never_claims_success(harness: Harness) -> None:
    def too_slow(deadline: float) -> dict[str, object]:
        harness.clock.value = deadline + 1
        return {"late": True}

    harness.verify = too_slow  # type: ignore[method-assign]
    with pytest.raises(DeploymentTimeout, match="exceeded its budget"):
        harness.run()
    assert harness.child.returncode == -signal.SIGTERM


def test_wrong_account_stack_and_invalid_poll_response_fail_closed(harness: Harness) -> None:
    harness.cfn.states = [state(StackId="arn:aws:cloudformation:us-east-1:000000000000:stack/x/y")]
    with pytest.raises(DeploymentError, match="outside the reviewed"):
        harness.run()
    assert not harness.launched


def test_original_ready_without_timestamp_cannot_be_a_continuation_proof(harness: Harness) -> None:
    harness.cfn.states = [state(old=True, LastUpdatedTime=None)]
    with pytest.raises(DeploymentError, match="timestamp"):
        harness.run()
    assert not harness.launched


def test_read_budget_caps_sdk_and_checks_every_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    from enterprise_analytics_agent.adapters.repair_operations import _BudgetedSession

    clock = Clock()
    calls: list[object] = []

    class Reads:
        def client(self, name: str, **kwargs: Any) -> Any:
            config = kwargs["config"]
            assert config.connect_timeout == 5 and config.read_timeout == 10
            assert config.retries == {"total_max_attempts": 1}
            calls.append(name)
            return self

        def describe_stacks(self, **kwargs: Any) -> object:
            calls.append(kwargs)
            return {"Stacks": []}

    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.repair_operations.time.monotonic", clock.now
    )
    session = _BudgetedSession(Reads(), deadline=5)
    client = session.client("cloudformation")
    assert client.describe_stacks(StackName=STACK_NAME) == {"Stacks": []}
    clock.value = 5
    with pytest.raises(TimeoutError, match="read budget"):
        client.describe_stacks(StackName=STACK_NAME)
    with pytest.raises(TimeoutError, match="client budget"):
        session.client("s3")
    assert len(calls) == 2, "expired budgets do not create clients or dispatch reads"


def test_real_owned_process_is_terminated_and_reaped_without_aws(harness: Harness) -> None:
    """Exercise actual Popen/process-group controls with a local sleeper, never CDK."""
    import sys

    children: list[subprocess.Popen[str]] = []

    def launch_local_sleeper(command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        assert command[0].endswith("/cdk")
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], text=True, **kwargs
        )
        children.append(child)
        return child

    controller = DeploymentController(
        harness.root / "real-run",
        harness.cfn,
        lock_path=harness.root / "real-runtime-deployment.lock",
        limits=DeploymentLimits(
            deployment_seconds=3,
            settle_seconds=3,
            verification_seconds=2,
            cleanup_seconds=0.5,
            poll_seconds=0.1,
        ),
        process_factory=launch_local_sleeper,
    )
    try:
        result = harness.run(controller)
        assert result["accepted"] and result["process_reaped"]
        assert len(children) == 1 and children[0].poll() is not None
        assert result["owned_process_group"] == children[0].pid
    finally:
        # Test failures must not leak the deliberately task-owned local sleeper.
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=1)


def test_cdk_exit_one_during_strict_checkpoint_cannot_become_success(harness: Harness) -> None:
    def exits_while_verified(deadline: float) -> dict[str, object]:
        harness.child.returncode = 1
        return {"strict": True}

    harness.verify = exits_while_verified  # type: ignore[method-assign]
    with pytest.raises(DeploymentError, match="nonzero during checkpoint"):
        harness.run()
    record = json.loads((harness.root / "run/candidate.controller.json").read_text())
    assert record["accepted"] is False and record["cdk_returncode"] == 1
    assert record["process_reaped"] and not record["cleanup_signals"]


def test_changed_reviewed_template_fails_before_any_process_or_aws_read(harness: Harness) -> None:
    controller = harness.controller()
    with pytest.raises(DeploymentError, match="reviewed SHA-256"):
        controller.deploy(
            str(harness.root / "assembly"),
            "candidate-version",
            "candidate",
            harness.verify,
            template_sha256="0" * 64,
        )
    assert not harness.launched and harness.cfn.calls == 0


def test_budgeted_read_rejects_a_final_sdk_call_that_returns_late(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from enterprise_analytics_agent.adapters.repair_operations import _BudgetedSession

    clock = Clock()
    calls: list[str] = []

    class Reads:
        def client(self, name: str, **kwargs: Any) -> Any:
            return self

        def get_caller_identity(self) -> dict[str, str]:
            calls.append("read")
            clock.value = 6
            return {"Account": "453711491609"}

    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.repair_operations.time.monotonic", clock.now
    )
    client = _BudgetedSession(Reads(), deadline=5).client("sts")
    with pytest.raises(TimeoutError, match="read exceeded"):
        client.get_caller_identity()
    assert calls == ["read"]


def test_original_proof_accepts_only_explicit_injected_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from enterprise_analytics_agent.adapters import retail_checkpoint

    selected = object()
    seen: list[object] = []

    def fake_checkpoint(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs.get("session"))
        raise ValueError("stop before any SDK work")

    monkeypatch.setattr(retail_checkpoint, "verify_checkpoint", fake_checkpoint)
    with pytest.raises(ValueError, match="before any SDK"):
        retail_checkpoint.verify_restoration(session=selected)
    assert seen == [selected]


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_deployment_deadlines_are_finite_positive_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        DeploymentLimits(deployment_seconds=value)


@pytest.mark.parametrize("drift", ["bootstrap", "extra", "missing", "duplicate"])
def test_baseline_parameter_drift_stops_before_popen(harness: Harness, drift: str) -> None:
    original = state(old=True)
    if drift == "bootstrap":
        original["Parameters"][1]["ParameterValue"] = "/unreviewed/bootstrap"
    elif drift == "extra":
        original["Parameters"].append({"ParameterKey": "Extra", "ParameterValue": "unreviewed"})
    elif drift == "missing":
        original["Parameters"].pop()
    else:
        original["Parameters"].append(deepcopy(original["Parameters"][0]))
    harness.cfn.states = [original]
    with pytest.raises(DeploymentError, match="baseline .*parameters|baseline parameter inventory"):
        harness.run()
    assert not harness.launched
    assert not harness.proofs


def test_baseline_template_validator_blocks_unreviewed_state_before_popen(harness: Harness) -> None:
    def reject(stack: dict[str, Any], body: dict[str, Any]) -> None:
        assert body == {"Resources": {}}
        raise ValueError("unreviewed baseline body/artifact pair")

    controller = harness.controller()
    controller.baseline_validator = reject
    with pytest.raises(DeploymentError, match="baseline template/artifact pair"):
        harness.run(controller)
    assert not harness.launched


def test_valid_reviewed_rollback_source_can_restore_without_overlap(harness: Harness) -> None:
    harness.cfn.states = [state(old=True, status="UPDATE_ROLLBACK_COMPLETE"), state(), state()]
    seen: list[str] = []

    def reviewed_source(stack: dict[str, Any], body: dict[str, Any]) -> None:
        assert body == {"Resources": {}}
        assert stack["Parameters"][0]["ParameterValue"] == "original-version"
        seen.append(stack["StackStatus"])

    controller = harness.controller()
    controller.baseline_validator = reviewed_source
    result = harness.run(controller)
    assert result["accepted"] is True
    assert seen == ["UPDATE_ROLLBACK_COMPLETE"]
    assert len(harness.launched) == 1


def test_production_baseline_policy_pairs_reviewed_body_and_actual_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_q18_repair_config import UploadReads, review, version

    from enterprise_analytics_agent.adapters import repair_operations
    from enterprise_analytics_agent.retail_evaluation.campaign import CODE_SHA256, CODE_VERSION

    selected = review()
    uploaded = version(selected)
    original: dict[str, Any] = {
        "Parameters": deepcopy(TEMPLATE["Parameters"]),
        "Resources": {
            "AnalyticsRuntime": {
                "Properties": {
                    "EnvironmentVariables": {
                        "ANALYTICS_RUNTIME_CONFIG": json.dumps(
                            {
                                "dataset_version": "parity-v1",
                                "tenant_id": "t1",
                                "reference_date": "2025-02-01",
                                "model_id": "unchanged-model",
                            }
                        )
                    },
                    "AgentRuntimeArtifact": {
                        "CodeConfiguration": {
                            "Code": {
                                "S3": {
                                    "Bucket": "unchanged-code-bucket",
                                    "Prefix": f"releases/{CODE_SHA256}/agent.zip",
                                    "VersionId": {"Ref": "ArtifactVersionId"},
                                }
                            }
                        }
                    },
                }
            }
        },
    }
    candidate = deepcopy(original)
    props = candidate["Resources"]["AnalyticsRuntime"]["Properties"]
    props["AgentRuntimeArtifact"]["CodeConfiguration"]["Code"]["S3"]["Prefix"] = (
        f"releases/{selected.candidate_sha256}/agent.zip"
    )
    settings = json.loads(props["EnvironmentVariables"]["ANALYTICS_RUNTIME_CONFIG"])
    settings.update(
        dataset_version="retail-v1", tenant_id="retail_demo", reference_date="2025-04-01"
    )
    props["EnvironmentVariables"]["ANALYTICS_RUNTIME_CONFIG"] = json.dumps(settings)
    base = tmp_path / "base"
    base.mkdir()
    (base / TEMPLATE_NAME).write_text(json.dumps(original))
    monkeypatch.setattr(repair_operations, "BASE_ASSEMBLY", base)
    monkeypatch.setattr(
        repair_operations, "digest", lambda path: selected.restoration_template_sha256
    )
    monkeypatch.setattr(repair_operations, "review_assemblies", lambda: {})
    captured: dict[str, Any] = {}

    def controller(directory: Path, cloudformation: Any, **kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    class ReadOnlySession(UploadReads):
        def client(self, name: str, **kwargs: Any) -> Any:
            assert name in {"sts", "cloudformation"}
            return self

    monkeypatch.setattr(repair_operations, "DeploymentController", controller)
    monkeypatch.setattr("boto3.Session", lambda **kwargs: ReadOnlySession(selected))
    # Restoration-only construction must not read a candidate ZIP, assembly or object.
    repair_operations.operations_for(selected, uploaded, tmp_path / "reports", restore_only=True)
    validate = captured["baseline_validator"]
    for body, correct in ((original, CODE_VERSION), (candidate, uploaded.version_id)):
        for status in ("UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"):
            baseline = state(status=status)
            baseline["Parameters"][0]["ParameterValue"] = correct
            validate(baseline, body)
        for incorrect in {"unreviewed-version", CODE_VERSION, uploaded.version_id} - {correct}:
            baseline = state()
            baseline["Parameters"][0]["ParameterValue"] = incorrect
            with pytest.raises(ValueError, match="unreviewed artifact version"):
                validate(baseline, body)
    drift = deepcopy(original)
    drift["Resources"]["Unexpected"] = {"Type": "AWS::S3::Bucket"}
    baseline = state()
    baseline["Parameters"][0]["ParameterValue"] = CODE_VERSION
    with pytest.raises(ValueError):
        validate(baseline, drift)
