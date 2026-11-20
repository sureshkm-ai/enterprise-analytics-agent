"""Reviewed streaming updates reuse the legacy bounded deployment controller offline."""

import hashlib
import json
import signal
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from test_deployment_controller import TEMPLATE, Clock, CloudFormation, Harness, Process, state

from enterprise_analytics_agent.adapters.deployment_controller import (
    DeploymentController,
    DeploymentError,
    DeploymentLimits,
    DeploymentTimeout,
)

STACK = "enterprise-analytics-stream-nova-lite"
TEMPLATE_FILE = f"{STACK}.template.json"
ROLE = "arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2"
EXPECTED_RUNTIME: dict[str, Any] = {
    "runtime_status": "READY",
    "endpoint_status": "READY",
    "runtime_version": "2",
    "endpoint_version": "2",
    "artifact_version": "candidate-version",
    "configuration": {"model_id": "us.amazon.nova-lite-v1:0", "dataset_version": "retail-v1"},
    "runtime_policy": {"approved_caller": "preserved", "deny_unapproved": True},
    "endpoint_policy": {"approved_caller": "preserved", "deny_unapproved": True},
    "retention_days": 7,
    "artifact_sha256": "a" * 64,
}


def streaming_state(
    *, status: str = "UPDATE_COMPLETE", old: bool = False, **changes: Any
) -> dict[str, Any]:
    result = state(status=status, old=old)
    result.update(
        StackName=STACK,
        StackId=f"arn:aws:cloudformation:us-west-2:453711491609:stack/{STACK}/stack-id",
        RoleARN=ROLE,
    )
    result.update(changes)
    return result


@dataclass
class StreamingCloudFormation(CloudFormation):
    requested_stacks: list[str] = field(default_factory=list)

    def describe_stacks(self, *, StackName: str) -> dict[str, Any]:
        assert StackName == STACK
        self.requested_stacks.append(StackName)
        if self.failure:
            raise self.failure
        self.current = self.states[min(self.calls, len(self.states) - 1)]
        self.calls += 1
        return {
            "Stacks": [{key: value for key, value in self.current.items() if key != "template"}]
        }

    def get_template(self, *, StackName: str, TemplateStage: str) -> dict[str, Any]:
        assert StackName == STACK and TemplateStage == "Original"
        self.requested_stacks.append(StackName)
        return {"TemplateBody": deepcopy(self.current["template"])}


@dataclass
class StreamingHarness(Harness):
    actual_runtime: dict[str, Any] = field(default_factory=lambda: deepcopy(EXPECTED_RUNTIME))
    baseline_proofs: list[str] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)

    def launch(self, command: list[str], **kwargs: Any) -> Process:
        assert command[4] == STACK
        assert "--role-arn" not in command
        self.commands.append(command)
        return super().launch(command, **kwargs)

    def verify(self, deadline: float) -> dict[str, object]:
        self.proofs.append(deadline)
        if self.verification_error:
            raise self.verification_error
        # Author the complete callback proof independently of CFN READY/status.
        # Production callback additionally performs the real bounded SDK reads.
        if self.actual_runtime != EXPECTED_RUNTIME:
            raise ValueError("Runtime/DEFAULT artifact/configuration/policies differ")
        return deepcopy(self.actual_runtime)

    def baseline(self, stack: dict[str, Any], body: dict[str, Any]) -> None:
        artifact = stack["Parameters"][0]["ParameterValue"]
        if (body, artifact) not in (
            ({"Resources": {}}, "original-version"),
            (TEMPLATE, "candidate-version"),
        ):
            raise ValueError("unreviewed baseline template/artifact pair")
        self.baseline_proofs.append(artifact)

    def controller(self, directory: str = "run") -> DeploymentController:
        return DeploymentController(
            self.root / directory,
            self.cfn,
            lock_path=self.root / "runtime-deployment.lock",
            stack_name=STACK,
            template_name=TEMPLATE_FILE,
            expected_execution_role=ROLE,
            baseline_validator=self.baseline,
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


@pytest.fixture
def streaming_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StreamingHarness:
    monkeypatch.setattr(
        "boto3.Session", lambda *args, **kwargs: pytest.fail("streaming update test contacted AWS")
    )
    assembly = tmp_path / "assembly"
    assembly.mkdir()
    (assembly / TEMPLATE_FILE).write_text(json.dumps(TEMPLATE))
    clock = Clock()
    return StreamingHarness(
        tmp_path,
        StreamingCloudFormation([streaming_state(old=True), streaming_state(), streaming_state()]),
        clock,
        Process(clock),
    )


def test_stalled_streaming_cdk_requires_exact_cfn_and_two_runtime_proofs(
    streaming_harness: StreamingHarness,
) -> None:
    record = streaming_harness.run()
    assert record["accepted"] is True
    assert record["completion"] == "fresh_verified_aws_update"
    assert record["stack_name"] == STACK and record["template_name"] == TEMPLATE_FILE
    assert record["expected_execution_role"] == ROLE
    assert record["process_reaped"] and record["cleanup_signals"] == ["SIGTERM"]
    assert len(streaming_harness.proofs) == 2
    assert streaming_harness.baseline_proofs == ["original-version"]
    assert len(streaming_harness.commands) == 1
    assert streaming_harness.clock.value <= 12
    assert (streaming_harness.root / "run/candidate.stdout.log").read_text() == (
        "authored retained stdout\n"
    )
    assert not json.loads((streaming_harness.root / "runtime-deployment.lock").read_text())[
        "active"
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"stack_name": "enterprise-analytics-dev-data-layer"},
        {"stack_name": "enterprise-analytics-stream-../foreign"},
        {"stack_name": "enterprise-analytics-stream-Nova"},
        {"stack_name": "enterprise-analytics-stream-nova-lite --all"},
        {"stack_name": "enterprise-analytics-stream-"},
        {"template_name": "../outside.template.json"},
        {"template_name": "/tmp/outside.template.json"},
        {"template_name": "nested/matching.template.json"},
        {"template_name": r"nested\matching.template.json"},
        {"template_name": "enterprise-analytics-stream-deepseek-v3-2.template.json"},
        {"template_name": ""},
        {"template_name": "."},
        {"template_name": ".."},
        {"expected_execution_role": None},
        {"expected_execution_role": "arn:aws:iam::453711491609:role/administrator"},
        {"expected_execution_role": ROLE.replace("453711491609", "000000000000")},
        {"expected_execution_role": ROLE.replace("us-west-2", "us-east-1")},
    ],
)
def test_invalid_streaming_controller_bindings_fail_before_reads_or_processes(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    selected: dict[str, Any] = {
        "stack_name": STACK,
        "template_name": TEMPLATE_FILE,
        "expected_execution_role": ROLE,
    }
    selected.update(changes)
    with pytest.raises(ValueError):
        DeploymentController(tmp_path, None, lock_path=tmp_path / "lock", **selected)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("stage", ["before", "during", "already_current_final"])
def test_exact_cloudformation_role_is_required_at_every_stack_read(
    streaming_harness: StreamingHarness, stage: str
) -> None:
    changed = streaming_state(RoleARN=ROLE.replace("cfn-exec-role", "wrong-role"))
    if stage == "before":
        streaming_harness.cfn.states = [streaming_state(old=True, RoleARN=None)]
    elif stage == "during":
        streaming_harness.cfn.states = [streaming_state(old=True), changed]
    else:
        streaming_harness.cfn.states = [streaming_state(), changed]
    with pytest.raises(DeploymentError, match="execution role differs"):
        streaming_harness.run()
    assert (
        not streaming_harness.launched
        if stage != "during"
        else len(streaming_harness.launched) == 1
    )
    if stage == "during":
        assert streaming_harness.child.returncode == -signal.SIGTERM
    assert not json.loads((streaming_harness.root / "run/candidate.controller.json").read_text())[
        "accepted"
    ]


@pytest.mark.parametrize("drift", ["template", "artifact", "bootstrap", "extra_parameter", "stale"])
def test_ready_does_not_replace_exact_fresh_streaming_cloudformation_proof(
    streaming_harness: StreamingHarness, drift: str
) -> None:
    candidate = streaming_state()
    if drift == "template":
        candidate["template"]["Resources"]["Unreviewed"] = {"Type": "AWS::S3::Bucket"}
    elif drift == "artifact":
        candidate["Parameters"][0]["ParameterValue"] = "wrong-version"
    elif drift == "bootstrap":
        candidate["Parameters"][1]["ParameterValue"] = "/unreviewed/bootstrap"
    elif drift == "extra_parameter":
        candidate["Parameters"].append({"ParameterKey": "Extra", "ParameterValue": "unreviewed"})
    else:
        candidate["LastUpdatedTime"] = streaming_state(old=True)["LastUpdatedTime"]
    streaming_harness.cfn.states = [streaming_state(old=True), candidate]
    with pytest.raises(DeploymentTimeout):
        streaming_harness.run()
    assert not streaming_harness.proofs
    assert streaming_harness.child.returncode == -signal.SIGTERM


@pytest.mark.parametrize(
    "drift",
    [
        "runtime_version",
        "endpoint_version",
        "artifact_version",
        "configuration",
        "runtime_policy",
        "endpoint_policy",
        "retention_days",
        "artifact_sha256",
    ],
)
def test_matching_cfn_and_ready_runtime_still_require_full_checkpoint(
    streaming_harness: StreamingHarness, drift: str
) -> None:
    streaming_harness.actual_runtime[drift] = "unreviewed"
    with pytest.raises(DeploymentTimeout):
        streaming_harness.run()
    assert streaming_harness.proofs
    assert streaming_harness.child.returncode == -signal.SIGTERM
    evidence = json.loads((streaming_harness.root / "run/candidate.controller.json").read_text())
    assert evidence["accepted"] is False
    assert evidence["last_verification_error_type"] == "ValueError"


def test_unavailable_runtime_verification_preserves_operation_diagnostics(
    streaming_harness: StreamingHarness,
) -> None:
    diagnostic = {
        "service": "bedrock-agentcore-control",
        "operation": "GetAgentRuntime",
        "attempts": 3,
    }

    class UnavailableRead(ConnectionError):
        def __init__(self) -> None:
            super().__init__("authored temporary read outage")
            self.diagnostic = diagnostic

    failure = UnavailableRead()
    streaming_harness.verification_error = failure
    with pytest.raises(DeploymentTimeout):
        streaming_harness.run()
    evidence = json.loads((streaming_harness.root / "run/candidate.controller.json").read_text())
    assert evidence["accepted"] is False
    assert evidence["last_verification_error_type"] == "UnavailableRead"
    assert evidence["last_verification_error"]["phase"] == "candidate"
    assert evidence["last_verification_error"]["causes"][0]["operation"] == diagnostic
    assert evidence["process_reaped"]


@pytest.mark.parametrize(
    "status",
    ["UPDATE_FAILED", "UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED", "ROLLBACK_COMPLETE"],
)
def test_fresh_streaming_failure_and_rollback_stop_without_acceptance(
    streaming_harness: StreamingHarness, status: str
) -> None:
    streaming_harness.cfn.states = [streaming_state(old=True), streaming_state(status=status)]
    with pytest.raises(DeploymentError, match="failed or rolled back"):
        streaming_harness.run()
    assert not streaming_harness.proofs
    assert streaming_harness.child.returncode == -signal.SIGTERM


@pytest.mark.parametrize("stage", ["before", "during"])
def test_wrong_or_replaced_streaming_stack_id_is_rejected(
    streaming_harness: StreamingHarness, stage: str
) -> None:
    if stage == "before":
        streaming_harness.cfn.states = [
            streaming_state(
                old=True, StackId="arn:aws:cloudformation:us-east-1:000000000000:stack/foreign/id"
            )
        ]
    else:
        candidate = streaming_state()
        candidate["StackId"] += "-replaced"
        streaming_harness.cfn.states = [streaming_state(old=True), candidate]
    with pytest.raises(DeploymentError, match="outside the reviewed|identity changed"):
        streaming_harness.run()
    assert not streaming_harness.proofs
    if stage == "before":
        assert not streaming_harness.launched
    else:
        assert streaming_harness.child.returncode == -signal.SIGTERM


def test_interrupted_streaming_verification_reaps_only_owned_child_and_keeps_guard(
    streaming_harness: StreamingHarness,
) -> None:
    streaming_harness.verification_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        streaming_harness.run()
    record = json.loads((streaming_harness.root / "run/candidate.controller.json").read_text())
    journal = json.loads((streaming_harness.root / "runtime-deployment.lock").read_text())
    assert record["error_type"] == "KeyboardInterrupt" and record["accepted"] is False
    assert record["process_reaped"] and record["owned_process_group"] == streaming_harness.child.pid
    assert journal["active"] is False
    assert streaming_harness.child.returncode == -signal.SIGTERM
    assert (streaming_harness.root / "run/candidate.stderr.log").exists()


def test_unresolved_streaming_update_prevents_overlapping_next_attempt(
    streaming_harness: StreamingHarness,
) -> None:
    streaming_harness.cfn.states = [
        streaming_state(old=True),
        streaming_state(status="UPDATE_IN_PROGRESS"),
    ]
    with pytest.raises(DeploymentTimeout):
        streaming_harness.run()
    with pytest.raises(DeploymentTimeout, match="previous AWS update remains unresolved"):
        streaming_harness.run(streaming_harness.controller("restore"))
    assert len(streaming_harness.launched) == 1


def test_unreaped_streaming_child_retains_active_guard_and_blocks_replay(
    streaming_harness: StreamingHarness,
) -> None:
    streaming_harness.child.resist_term = streaming_harness.child.resist_kill = True
    with pytest.raises(DeploymentError, match="cleanup failed"):
        streaming_harness.run()
    journal = json.loads((streaming_harness.root / "runtime-deployment.lock").read_text())
    assert journal["active"] and journal["process_group"] == streaming_harness.child.pid
    with pytest.raises(DeploymentError, match="retained task-owned process"):
        streaming_harness.run(streaming_harness.controller("another"))
    assert len(streaming_harness.launched) == 1


def test_streaming_template_hash_pin_precedes_any_cfn_read_or_process(
    streaming_harness: StreamingHarness,
) -> None:
    controller = streaming_harness.controller()
    with pytest.raises(DeploymentError, match="reviewed SHA-256"):
        controller.deploy(
            str(streaming_harness.root / "assembly"),
            "candidate-version",
            "candidate",
            streaming_harness.verify,
            template_sha256="0" * 64,
        )
    assert streaming_harness.cfn.calls == 0 and not streaming_harness.launched


def test_exact_already_current_streaming_deployment_is_a_verified_noop(
    streaming_harness: StreamingHarness,
) -> None:
    streaming_harness.cfn.states = [streaming_state()]
    record = streaming_harness.run()
    assert record["completion"] == "already_verified_no_mutation" and record["accepted"]
    assert not streaming_harness.launched and len(streaming_harness.proofs) == 1
    assert (
        record["template_sha256"]
        == hashlib.sha256(
            (streaming_harness.root / "assembly" / TEMPLATE_FILE).read_bytes()
        ).hexdigest()
    )


def test_unknown_streaming_baseline_template_stops_before_cdk(
    streaming_harness: StreamingHarness,
) -> None:
    candidate = streaming_state(old=True)
    candidate["template"]["Resources"]["Unreviewed"] = {"Type": "AWS::S3::Bucket"}
    streaming_harness.cfn.states = [candidate]
    with pytest.raises(DeploymentError, match="baseline template/artifact pair"):
        streaming_harness.run()
    assert not streaming_harness.launched and not streaming_harness.proofs
