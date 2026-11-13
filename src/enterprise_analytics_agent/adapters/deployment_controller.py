"""Bounded CDK supervision reconciled with exact, freshly verified AWS state.

The controller owns only the process group it starts. A local CLI exit code or
Runtime READY is never sufficient evidence that the reviewed deployment completed.
All AWS-capable dependencies are injected, so importing this module is offline.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from enterprise_analytics_agent.retail_evaluation.deployment import TEMPLATE_NAME, canonical_hash
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record

STACK_NAME = "enterprise-analytics-dev-agent-runtime"
_STREAMING_STACK = re.compile(r"enterprise-analytics-stream-[a-z][a-z0-9-]{0,63}")
_EXECUTION_ROLE = (
    "arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2"
)
_SUCCESS = {"CREATE_COMPLETE", "UPDATE_COMPLETE"}
_UPDATABLE = _SUCCESS | {"UPDATE_ROLLBACK_COMPLETE"}


class DeploymentError(RuntimeError):
    """Deployment is failed, unsafe, unresolved or cannot be verified."""


class ProcessCleanupError(DeploymentError):
    """A task-owned process group could not be proven stopped within its budget."""


class DeploymentTimeout(DeploymentError):
    """The deployment deadline expired without a complete matching checkpoint."""


@dataclass(frozen=True)
class DeploymentLimits:
    deployment_seconds: float = 900
    settle_seconds: float = 900
    verification_seconds: float = 120
    cleanup_seconds: float = 5
    poll_seconds: float = 3

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) or value <= 0 for value in vars(self).values()):
            raise ValueError("deployment limits must be finite and positive")


def _group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    return True


class DeploymentController:
    """Serialize deployments, bound a CLI child and reconcile independent state.

    Read callbacks must impose finite SDK timeouts and honor the supplied monotonic
    verification deadline. The live adapter does this for every SDK read. Polling
    may exceed a deadline only by a single already-started bounded read.
    """

    def __init__(
        self,
        directory: Path,
        cloudformation: Any,
        *,
        lock_path: Path,
        stack_name: str = STACK_NAME,
        template_name: str = TEMPLATE_NAME,
        expected_execution_role: str | None = None,
        limits: DeploymentLimits | None = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        signal_group: Callable[[int, int], None] = os.killpg,
        group_exists: Callable[[int], bool] = _group_exists,
        baseline_validator: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
        read_client: Callable[[float], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        streaming = _STREAMING_STACK.fullmatch(stack_name) is not None
        if stack_name != STACK_NAME and not streaming:
            raise ValueError("deployment stack is outside the reviewed Runtime scope")
        if (
            not template_name
            or template_name in {".", ".."}
            or Path(template_name).name != template_name
            or "\\" in template_name
        ):
            raise ValueError("deployment template must be a basename")
        if streaming and template_name != f"{stack_name}.template.json":
            raise ValueError("streaming template must match the reviewed stack name")
        if streaming and expected_execution_role != _EXECUTION_ROLE:
            raise ValueError("streaming updates require the reviewed CloudFormation execution role")
        self.stack_name = stack_name
        self.template_name = template_name
        self.expected_execution_role = expected_execution_role
        self.directory = directory
        self.cloudformation = cloudformation
        self.read_client = read_client
        self.lock_path = lock_path
        self.limits = limits or DeploymentLimits()
        self.process_factory = process_factory
        self.signal_group = signal_group
        self.group_exists = group_exists
        self.baseline_validator = baseline_validator
        self.lock_stream: TextIO | None = None
        self.monotonic = monotonic
        self.sleep = sleep
        self.poisoned = False

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DeploymentError("another controller owns the Runtime deployment") from exc
            try:
                stream.seek(0)
                retained = stream.read()
                if retained and json.loads(retained).get("active"):
                    raise DeploymentError(
                        "retained task-owned process is unresolved; inspect before recovery"
                    )
                self.lock_stream = stream
                yield
            finally:
                self.lock_stream = None
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _journal(self, *, active: bool, process_group: int | None = None) -> None:
        assert self.lock_stream is not None
        stream = self.lock_stream
        stream.seek(0)
        stream.truncate()
        stream.write(
            json.dumps({"active": active, "owner_pid": os.getpid(), "process_group": process_group})
        )
        stream.flush()
        os.fsync(stream.fileno())

    def _check_deadline(self, deadline: float | None) -> None:
        if deadline is not None and self.monotonic() >= deadline:
            raise DeploymentTimeout("deployment read deadline exhausted")

    def _reader(self, deadline: float | None) -> Any:
        if self.read_client is not None:
            bound = (
                deadline
                if deadline is not None
                else (self.monotonic() + self.limits.verification_seconds)
            )
            return self.read_client(bound)
        return self.cloudformation

    def _stack(self, deadline: float | None = None) -> dict[str, Any]:
        self._check_deadline(deadline)
        stacks = self._reader(deadline).describe_stacks(StackName=self.stack_name)["Stacks"]
        if len(stacks) != 1 or stacks[0].get("StackName") != self.stack_name:
            raise DeploymentError("unexpected CloudFormation stack identity")
        stack = dict(stacks[0])
        prefix = f"arn:aws:cloudformation:us-west-2:453711491609:stack/{self.stack_name}/"
        if not str(stack.get("StackId", "")).startswith(prefix):
            raise DeploymentError("CloudFormation stack is outside the reviewed account/region")
        if (
            self.expected_execution_role is not None
            and stack.get("RoleARN") != self.expected_execution_role
        ):
            raise DeploymentError("CloudFormation execution role differs from the reviewed role")
        return stack

    def _stable(self) -> dict[str, Any]:
        deadline = self.monotonic() + self.limits.settle_seconds
        while True:
            if self.monotonic() >= deadline:
                raise DeploymentTimeout("previous AWS update remains unresolved; no new deployment")
            stack = self._stack(deadline)
            status = stack["StackStatus"]
            if not status.endswith("_IN_PROGRESS"):
                if status not in _UPDATABLE:
                    raise DeploymentError(f"Runtime stack is not safely updatable: {status}")
                return stack
            if self.monotonic() >= deadline:
                raise DeploymentTimeout("previous AWS update remains unresolved; no new deployment")
            self.sleep(max(0, min(self.limits.poll_seconds, deadline - self.monotonic())))

    def _template(self, deadline: float | None) -> dict[str, Any]:
        self._check_deadline(deadline)
        response = self._reader(deadline).get_template(
            StackName=self.stack_name, TemplateStage="Original"
        )
        body = response["TemplateBody"]
        result: dict[str, Any] = json.loads(body) if isinstance(body, str) else dict(body)
        return result

    def _baseline(self, stack: dict[str, Any], parameters: dict[str, str], deadline: float) -> None:
        records = stack.get("Parameters", [])
        actual = {item["ParameterKey"]: item["ParameterValue"] for item in records}
        if len(records) != len(actual) or set(actual) != set(parameters):
            raise DeploymentError("baseline parameter inventory differs from the reviewed template")
        if any(
            actual[key] != expected
            for key, expected in parameters.items()
            if key != "ArtifactVersionId"
        ):
            raise DeploymentError("baseline non-artifact parameters differ from the review")
        body = self._template(deadline)
        if self.baseline_validator is not None:
            try:
                self.baseline_validator(stack, body)
            except Exception as exc:
                raise DeploymentError(
                    "baseline template/artifact pair is outside the review"
                ) from exc

    def _matches(
        self,
        stack: dict[str, Any],
        template: dict[str, Any],
        parameters: dict[str, str],
        deadline: float | None = None,
    ) -> bool:
        if stack["StackStatus"] not in _SUCCESS:
            return False
        records = stack.get("Parameters", [])
        actual = {item["ParameterKey"]: item["ParameterValue"] for item in records}
        if len(records) != len(actual) or actual != parameters:
            return False
        return self._template(deadline) == template

    @staticmethod
    def _updated(stack: dict[str, Any]) -> datetime:
        value = stack.get("LastUpdatedTime", stack.get("CreationTime"))
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise DeploymentError("CloudFormation update timestamp is unavailable")
        return value

    def _cleanup(self, process: Any, evidence: dict[str, Any]) -> None:
        """Terminate/reap only this Popen child's newly created process group."""
        try:
            if process.poll() is None or self.group_exists(process.pid):
                for value, label in ((signal.SIGTERM, "SIGTERM"), (signal.SIGKILL, "SIGKILL")):
                    deadline = self.monotonic() + self.limits.cleanup_seconds
                    evidence["cleanup_signals"].append(label)
                    try:
                        self.signal_group(process.pid, value)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=self.limits.cleanup_seconds)
                    except subprocess.TimeoutExpired:
                        pass
                    while self.group_exists(process.pid) and self.monotonic() < deadline:
                        self.sleep(max(0, min(0.1, deadline - self.monotonic())))
                    if process.poll() is not None and not self.group_exists(process.pid):
                        break
                else:
                    raise ProcessCleanupError("owned CDK process cleanup remains unresolved")
            else:
                process.wait(timeout=self.limits.cleanup_seconds)
            evidence["process_reaped"] = True
            evidence["cdk_returncode"] = process.returncode
            self._journal(active=False)
        except Exception as exc:
            self.poisoned = True
            evidence["cleanup_error_type"] = type(exc).__name__
            raise ProcessCleanupError("owned CDK process cleanup failed") from exc

    def _verify[T](
        self, verify: Callable[[float], T], deadline: float, evidence: dict[str, Any]
    ) -> T:
        if self.monotonic() >= deadline:
            raise DeploymentTimeout("strict checkpoint verification budget exhausted")
        checkpoint = verify(deadline)
        if self.monotonic() > deadline:
            raise DeploymentTimeout("strict checkpoint verification exceeded its budget")
        evidence["strict_checkpoint_verified"] = True
        return checkpoint

    def deploy[T](
        self,
        assembly: str,
        artifact_version: str,
        name: str,
        verify: Callable[[float], T],
        *,
        template_sha256: str | None = None,
    ) -> T:
        if self.poisoned:
            raise DeploymentError("owned process cleanup failed; stop before another deployment")
        raw = (Path(assembly) / self.template_name).read_bytes()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if template_sha256 is not None and actual_sha256 != template_sha256:
            raise DeploymentError("deployment template differs from its reviewed SHA-256")
        template = json.loads(raw)
        parameters = {
            key: str(value["Default"])
            for key, value in template["Parameters"].items()
            if "Default" in value
        }
        parameters["ArtifactVersionId"] = artifact_version
        if set(parameters) != set(template["Parameters"]):
            raise DeploymentError("reviewed template has an unbound parameter")
        with self._locked():
            return self._deploy_locked(
                assembly, artifact_version, name, template, actual_sha256, parameters, verify
            )

    def _deploy_locked[T](
        self,
        assembly: str,
        artifact_version: str,
        name: str,
        template: dict[str, Any],
        template_sha256: str,
        parameters: dict[str, str],
        verify: Callable[[float], T],
    ) -> T:
        self.directory.mkdir(parents=True, exist_ok=True)
        started = self.monotonic()
        evidence: dict[str, Any] = {
            "schema_version": "runtime-deployment-controller-v1",
            "started_at": datetime.now(UTC).isoformat(),
            "name": name,
            "stack_name": self.stack_name,
            "template_name": self.template_name,
            "expected_execution_role": self.expected_execution_role,
            "template_sha256": template_sha256,
            "template_canonical_sha256": canonical_hash(template),
            "parameters": parameters,
            "limits": vars(self.limits),
            "accepted": False,
            "strict_checkpoint_verified": False,
            "process_started": False,
            "process_reaped": False,
            "cleanup_signals": [],
            "observations": [],
        }
        process = None
        evidence_path = self.directory / f"{name}.controller.json"
        # Fail before mutation if evidence/log paths would overwrite an older attempt.
        if any(
            (self.directory / f"{name}.{suffix}").exists()
            for suffix in ("controller.json", "stdout.log", "stderr.log", "outputs.json")
        ):
            raise DeploymentError(
                "deployment evidence already exists; preserve the earlier attempt"
            )
        try:
            baseline = self._stable()
            baseline_time = self._updated(baseline)
            baseline_id = baseline["StackId"]
            evidence["baseline_stack_id"] = baseline_id
            evidence["baseline_updated_at"] = baseline_time.isoformat()
            deadline = self.monotonic() + self.limits.verification_seconds
            self._baseline(baseline, parameters, deadline)
            if self._matches(baseline, template, parameters, deadline):
                checkpoint = self._verify(verify, deadline, evidence)
                # Recheck CFN after full verification to catch concurrent updates.
                final = self._stack(deadline)
                if (
                    final["StackId"] != baseline_id
                    or self._updated(final) != baseline_time
                    or not self._matches(final, template, parameters, deadline)
                ):
                    raise DeploymentError("AWS state changed during already-current verification")
                evidence.update(accepted=True, completion="already_verified_no_mutation")
                return checkpoint
            with (
                (self.directory / f"{name}.stdout.log").open("x") as out,
                (self.directory / f"{name}.stderr.log").open("x") as err,
            ):
                # Durable intent blocks another controller after abrupt parent/host loss.
                self._journal(active=True)
                process = self.process_factory(
                    [
                        "infrastructure/cdk/tooling/node_modules/.bin/cdk",
                        "deploy",
                        "--app",
                        assembly,
                        self.stack_name,
                        "--parameters",
                        "ArtifactVersionId=" + artifact_version,
                        "--profile",
                        "analytics-dev",
                        "--region",
                        "us-west-2",
                        "--require-approval",
                        "never",
                        "--no-telemetry",
                        "--no-notices",
                        "--outputs-file",
                        str(self.directory / f"{name}.outputs.json"),
                    ],
                    stdout=out,
                    stderr=err,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
                self._journal(active=True, process_group=process.pid)
                evidence["process_started"] = True
                evidence["owned_process_group"] = process.pid
                deadline = self.monotonic() + self.limits.deployment_seconds
                exit_deadline = deadline
                while self.monotonic() < min(deadline, exit_deadline):
                    if process is None:
                        raise DeploymentError("owned deployment process is unavailable")
                    returncode = process.poll()
                    if returncode is not None and returncode != 0:
                        raise DeploymentError(f"CDK failed with return code {returncode}")
                    if returncode == 0:
                        exit_deadline = min(
                            exit_deadline, self.monotonic() + self.limits.verification_seconds
                        )
                    try:
                        stack = self._stack(min(deadline, exit_deadline))
                        evidence["observations"].append(
                            {
                                "status": stack["StackStatus"],
                                "updated_at": self._updated(stack).isoformat(),
                            }
                        )
                        if stack["StackId"] != baseline_id:
                            raise DeploymentError(
                                "Runtime stack identity changed during deployment"
                            )
                        status = stack["StackStatus"]
                        if (
                            not status.endswith("_IN_PROGRESS")
                            and status not in _SUCCESS
                            and self._updated(stack) > baseline_time
                        ):
                            raise DeploymentError(f"AWS deployment failed or rolled back: {status}")
                        if self._updated(stack) > baseline_time and self._matches(
                            stack, template, parameters, min(deadline, exit_deadline)
                        ):
                            verification_deadline = min(
                                deadline, self.monotonic() + self.limits.verification_seconds
                            )
                            self._verify(verify, verification_deadline, evidence)
                            # Stop a stalled local CLI only after independently proving success.
                            self._cleanup(process, evidence)
                            process = None
                            returncode = evidence["cdk_returncode"]
                            expected_signal_exit = (
                                returncode == -signal.SIGTERM
                                and "SIGTERM" in evidence["cleanup_signals"]
                            ) or (
                                returncode == -signal.SIGKILL
                                and "SIGKILL" in evidence["cleanup_signals"]
                            )
                            if returncode != 0 and not expected_signal_exit:
                                raise DeploymentError(
                                    "CDK exited nonzero during checkpoint verification"
                                )
                            final = self._stack(verification_deadline)
                            if (
                                final["StackId"] != baseline_id
                                or self._updated(final) < self._updated(stack)
                                or not self._matches(
                                    final, template, parameters, verification_deadline
                                )
                            ):
                                raise DeploymentError("AWS deployment changed during child cleanup")
                            checkpoint = self._verify(verify, verification_deadline, evidence)
                            evidence.update(accepted=True, completion="fresh_verified_aws_update")
                            return checkpoint
                    except DeploymentError:
                        raise
                    except Exception as exc:
                        evidence["last_verification_error_type"] = type(exc).__name__
                        evidence["last_verification_error"] = error_record(exc, name)
                        if process is None:
                            raise DeploymentError(
                                "post-cleanup verification is unavailable"
                            ) from exc
                        # Unavailable reads never establish success; poll only within budget.
                        code = getattr(exc, "diagnostic", {}).get("aws_error_code") or (
                            getattr(exc, "response", {}).get("Error", {}).get("Code")
                        )
                        if code:
                            evidence["last_aws_error_code"] = code
                        if code and ("AccessDenied" in code or "Unauthorized" in code):
                            raise DeploymentError(
                                "AWS verification denied; inspect complete denial"
                            ) from exc
                    remaining = min(deadline, exit_deadline) - self.monotonic()
                    if remaining > 0:
                        self.sleep(min(self.limits.poll_seconds, remaining))
                raise DeploymentTimeout(
                    "CDK/AWS completion is unresolved within the deployment budget"
                )
        except BaseException as exc:
            evidence["error_type"] = type(exc).__name__
            evidence["error"] = error_record(exc, name)
            raise
        finally:
            if process is not None and not self.poisoned:
                try:
                    self._cleanup(process, evidence)
                except BaseException as exc:
                    self.poisoned = True
                    evidence["cleanup_error_type"] = type(exc).__name__
                    # No future deployment through this controller can overlap an un-reaped child.
                    if evidence["accepted"]:
                        evidence["accepted"] = False
                        raise
            evidence["finished_at"] = datetime.now(UTC).isoformat()
            evidence["elapsed_seconds"] = round(self.monotonic() - started, 6)
            encoded = json.dumps(evidence, indent=2) + "\n"
            with evidence_path.open("x") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
