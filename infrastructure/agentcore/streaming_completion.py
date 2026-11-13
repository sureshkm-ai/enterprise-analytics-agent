"""Guarded operator for the separately reviewed streaming completion candidate.

Importing and offline verification create no SDK clients, claims or counters.
S3 conditional upload: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html
Failure evidence: https://docs.aws.amazon.com/boto3/latest/reference/services/cloudtrail/client/lookup_events.html
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field

from enterprise_analytics_agent.adapters.deployment_controller import (
    DeploymentController,
    DeploymentError,
    DeploymentLimits,
)
from enterprise_analytics_agent.adapters.model_stream_ui import (
    CODE_BUCKET,
    _resolve,
    verify_developer_identity,
    verify_local_inputs,
    verify_target,
)
from enterprise_analytics_agent.adapters.operator_reads import READ_CONFIG, ReadPool
from enterprise_analytics_agent.adapters.ui_live import runtime_lease
from enterprise_analytics_agent.adapters.ui_release import verify_publication, verify_release
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record
from enterprise_analytics_agent.retail_evaluation.reporting import _redact
from enterprise_analytics_agent.ui.model_streams import (
    StreamingLedger,
    StreamingReleases,
    StreamingReview,
    StreamRelease,
    StreamTarget,
    verify_approval,
)
from enterprise_analytics_agent.ui.shared import SharedReview

ROOT = Path(__file__).resolve().parents[2]
EXECUTION_ROLE = "arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2"
OLD_VERSION = "GSY36sTbDpCNZGogULTe3cBL__bujiQK"
STABLE = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}
SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class CompletionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[
        "bedrock-streaming-completion-preparation-v1", "bedrock-workbench-preparation-v1"
    ]
    review_path: str
    review_sha256: SHA
    baseline_review_path: str
    baseline_releases_path: str
    baseline_releases_sha256: SHA
    baseline_assembly_directory: str
    candidate_assembly_directory: str
    canonical_directory: str
    process_guard_path: str
    process_guard_sha256: SHA
    baseline_stack_ids: dict[str, str]
    pinned_files: dict[str, SHA]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("Operator paths must be unaliased repository-relative paths")
    result = root / path
    if result.resolve() != result or not result.resolve().is_relative_to(root):
        raise ValueError("Operator paths must remain inside the original checkout")
    return result


def write_new(path: Path, value: object) -> None:
    content = json.dumps(_redact(value), indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextmanager
def one_sdk_attempt() -> Iterator[None]:
    previous = os.environ.get("AWS_MAX_ATTEMPTS")
    os.environ["AWS_MAX_ATTEMPTS"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AWS_MAX_ATTEMPTS", None)
        else:
            os.environ["AWS_MAX_ATTEMPTS"] = previous


@dataclass(frozen=True)
class Prepared:
    root: Path
    plan: CompletionPlan
    plan_sha256: str
    review: StreamingReview
    baseline_review: StreamingReview
    baseline_releases: StreamingReleases


def load_prepared(root: Path, path: Path, *, restoration: bool = False) -> Prepared:
    root = root.resolve()
    if path.resolve() != path or not path.is_relative_to(root):
        raise ValueError("Preparation metadata must be in the original checkout")
    plan = CompletionPlan.model_validate_json(path.read_bytes())
    review_file = local_path(root, plan.review_path)
    review = StreamingReview.model_validate_json(review_file.read_bytes())
    baseline_file = local_path(root, plan.baseline_review_path)
    baseline = StreamingReview.model_validate_json(baseline_file.read_bytes())
    release_file = local_path(root, plan.baseline_releases_path)
    releases = StreamingReleases.model_validate_json(release_file.read_bytes())
    releases.validate_review(baseline)
    workbench = plan.schema_version == "bedrock-workbench-preparation-v1"
    if workbench:
        valid_scope = (
            review.schema_version == "bedrock-model-workbench-v1" and review.parent is None
        )
    else:
        valid_scope = (
            review.parent is not None
            and review.parent.review_path == plan.baseline_review_path
            and review.parent.review_sha256 == baseline.sha256
            and all(item.runtime_version == "1" for item in releases.models)
        )
    if (
        review.sha256 != plan.review_sha256
        or not valid_scope
        or digest(release_file) != plan.baseline_releases_sha256
        or releases.artifact_version_id != OLD_VERSION
        or len(review.targets) != 10
    ):
        raise ValueError("The continuation/baseline deployment pins differ")
    keys = {target.model_key for target in review.targets}
    if keys != set(plan.baseline_stack_ids):
        raise ValueError("The exact ten baseline stack identities are required")
    for key, stack_id in plan.baseline_stack_ids.items():
        prefix = (
            "arn:aws:cloudformation:us-west-2:453711491609:stack/"
            f"enterprise-analytics-stream-{key}/"
        )
        if not stack_id.startswith(prefix) or not stack_id.removeprefix(prefix):
            raise ValueError("A baseline stack identity differs from its reviewed target")
    required = {
        plan.review_path,
        plan.baseline_review_path,
        plan.baseline_releases_path,
        "infrastructure/agentcore/streaming_completion.py",
        "src/enterprise_analytics_agent/adapters/deployment_controller.py",
    }
    if not restoration:
        required.add(review.artifact_path)
    for directory, selected in (
        (plan.candidate_assembly_directory, review),
        (plan.baseline_assembly_directory, baseline),
    ):
        if restoration and directory == plan.candidate_assembly_directory:
            continue
        folder = local_path(root, directory)
        required.update(str(item.relative_to(root)) for item in folder.rglob("*") if item.is_file())
        templates = list(folder.glob("*.template.json"))
        if len(templates) != 10:
            raise ValueError("The reviewed assembly must contain exactly ten templates")
        for target in selected.targets:
            body = json.loads(
                (
                    folder / f"enterprise-analytics-stream-{target.model_key}.template.json"
                ).read_bytes()
            )
            if (
                hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
                != target.template_sha256
            ):
                raise ValueError("A reviewed template differs from its semantic checksum")
    if not required.issubset(plan.pinned_files):
        raise ValueError("Preparation does not pin every required operator/package/assembly file")
    selected_pins = required if restoration else plan.pinned_files.keys()
    for name in selected_pins:
        if digest(local_path(root, name)) != plan.pinned_files[name]:
            raise ValueError(f"Pinned preparation input differs: {name}")
    guard = local_path(root, plan.process_guard_path)
    if digest(guard) != plan.process_guard_sha256:
        raise ValueError("The preserved process checkpoint differs")
    state = json.loads(guard.read_bytes())
    if (
        state.get("active") is not False
        or state.get("requires_inspection") is not False
        or state.get("process_reaped") is not True
        or state.get("strict_checkpoint_verified") is not True
    ):
        raise ValueError("The previous deployment process requires inspection")
    if not restoration:
        verify_local_inputs(root, review, local_path(root, plan.canonical_directory))
    budget = StreamingLedger(root, review).summary()
    if not restoration and (
        budget["used"] != 0
        or budget.get("blocked")
        or (not workbench and budget["aggregate_used"] != 3)
    ):
        raise ValueError("The deployment allowance is not an untouched, open reviewed checkpoint")
    return Prepared(root, plan, digest(path), review, baseline, releases)


class Boundaries(Protocol):
    def lease(self) -> AbstractContextManager[None]: ...
    def preflight(self) -> dict[str, Any]: ...
    def upload(self) -> str: ...
    def update(self, target: StreamTarget, version: str, *, restoring: bool) -> StreamRelease: ...
    def safe_to_restore(self, attempted: list[StreamTarget]) -> bool: ...
    def evaluate(self, releases: StreamingReleases) -> None: ...
    def cleanup(self) -> None: ...
    def collect_failure(self, attempted: list[StreamTarget]) -> None: ...
    def resume(self, operation: Path) -> None: ...


class CompletionWorkflow:
    """The same ordered controller is used by live execution and offline fakes."""

    def __init__(
        self,
        prepared: Prepared,
        output: Path,
        approval: object,
        boundaries: Boundaries,
        *,
        ledger: Any = None,
    ) -> None:
        self.prepared, self.output, self.approval = prepared, output, approval
        self.boundaries = boundaries
        self.ledger = ledger or StreamingLedger(prepared.root, prepared.review)

    def failure_evidence(self, name: str, value: object) -> None:
        # Evidence I/O failure must never prevent mandatory restoration or replace
        # the original execution error. Dispatch intents still fail closed.
        try:
            write_new(self.output / name, value)
        except Exception:
            pass

    @property
    def restoration_record(self) -> Path:
        return (
            self.prepared.root
            / "artifacts/bedrock-streaming/completion-restorations"
            / f"{self.prepared.review.campaign_id}.json"
        )

    def restore(self, operation: Path) -> None:
        """Restore only a retained approved operation; never upload/evaluate/reclaim."""
        prepared = self.prepared
        verify_approval(prepared.review, self.approval, now=datetime.now(UTC))
        if (
            not isinstance(self.approval, dict)
            or self.approval.get("preparation_sha256") != prepared.plan_sha256
        ):
            raise ValueError("Restoration approval must bind the exact preparation")
        if self.restoration_record.exists():
            raise ValueError("Restoration already completed; no smoke or deployment was repeated")
        state = self.ledger.summary()
        workbench = prepared.plan.schema_version == "bedrock-workbench-preparation-v1"
        if (not workbench and state.get("continuation_claimed") is not True) or state.get(
            "protected_cleanup"
        ) != 1:
            raise ValueError(
                "A matching continuation claim and unused protected smoke are required"
            )
        claim = json.loads(
            (
                prepared.root
                / "artifacts/bedrock-streaming/completion-claims"
                / f"{prepared.review.campaign_id}.json"
            ).read_bytes()
        )
        if (
            claim.get("review_sha256") != prepared.review.sha256
            or claim.get("preparation_sha256") != prepared.plan_sha256
            or claim.get("output") != str(operation)
        ):
            raise ValueError("The retained operation claim differs; do not create another attempt")
        attempted = []
        for target in prepared.review.targets:
            path = operation / f"update-{target.model_key}.intent.json"
            if path.exists():
                item = json.loads(path.read_bytes())
                if item.get("model_key") != target.model_key:
                    raise ValueError("A retained update intent differs")
                attempted.append(target)
        if not attempted:
            raise ValueError("No reviewed candidate update was attempted")
        self.output.mkdir(parents=True, exist_ok=False)
        restored = []
        try:
            self.boundaries.resume(operation)
            with self.boundaries.lease():
                if not self.boundaries.safe_to_restore(attempted):
                    raise DeploymentError(
                        "Restoration remains unresolved; no overlapping deployment"
                    )
                for target in reversed(attempted):
                    release = self.boundaries.update(target, OLD_VERSION, restoring=True)
                    restored.append(release.model_dump(mode="json"))
            self.boundaries.cleanup()
            write_new(
                self.restoration_record,
                {
                    "review_sha256": prepared.review.sha256,
                    "operation": str(operation),
                    "restoration_output": str(self.output),
                    "verified_restorations": restored,
                    "protected_cleanup_passed": True,
                },
            )
            write_new(
                self.output / "outcome.json",
                {
                    "status": "restored",
                    "verified_restorations": restored,
                    "budget": self.ledger.summary(),
                },
            )
        except BaseException as exc:
            self.failure_evidence("restoration-error.json", error_record(exc, "restoration-only"))
            self.failure_evidence(
                "restoration-required.json",
                {
                    "attempted": [item.model_key for item in attempted],
                    "verified_restorations": restored,
                    "preserve_claims": True,
                },
            )
            raise

    def run(self) -> None:
        prepared = self.prepared
        verify_approval(prepared.review, self.approval, now=datetime.now(UTC))
        if (
            not isinstance(self.approval, dict)
            or self.approval.get("preparation_sha256") != prepared.plan_sha256
        ):
            raise ValueError("Execution approval must bind the exact preparation metadata")
        # Ten candidate updates, ten possible restorations, evaluation and cleanup
        # must all fit before the unchanged expiry, using the controller maxima.
        if datetime.now(UTC) + timedelta(hours=10) >= prepared.review.expires_at:
            raise ValueError("Insufficient reviewed time for bounded execution and restoration")
        self.output.mkdir(parents=True, exist_ok=False)
        attempted: list[StreamTarget] = []
        restoration: list[dict[str, Any]] = []
        try:
            with self.boundaries.lease():
                write_new(self.output / "preflight.json", self.boundaries.preflight())
                claim = (
                    prepared.root
                    / "artifacts/bedrock-streaming/completion-claims"
                    / f"{prepared.review.campaign_id}.json"
                )
                write_new(
                    claim,
                    {
                        "at": datetime.now(UTC),
                        "review_sha256": prepared.review.sha256,
                        "preparation_sha256": prepared.plan_sha256,
                        "output": str(self.output),
                    },
                )
                if prepared.plan.schema_version != "bedrock-workbench-preparation-v1":
                    self.ledger.claim_continuation(self.approval)
                version = self.boundaries.upload()
                observed = []
                for target in prepared.review.targets:
                    write_new(
                        self.output / f"update-{target.model_key}.intent.json",
                        {
                            "model_key": target.model_key,
                            "artifact_version_id": version,
                            "at": datetime.now(UTC),
                        },
                    )
                    attempted.append(target)
                    observed.append(self.boundaries.update(target, version, restoring=False))
                releases = StreamingReleases(
                    review_sha256=prepared.review.sha256,
                    artifact_version_id=version,
                    models=tuple(observed),
                )
                releases.validate_review(prepared.review)
                write_new(self.output / "releases.actual.json", releases.model_dump(mode="json"))
            self.boundaries.evaluate(releases)
            status = "accepted"
            if prepared.plan.schema_version == "bedrock-workbench-preparation-v1":
                summary = json.loads((self.output / "acceptance/summary.json").read_bytes())
                if summary.get("passed") is not True:
                    status = "partially_accepted"
            write_new(
                self.output / "outcome.json",
                {
                    "status": status,
                    "budget": self.ledger.summary(),
                    "releases": releases.model_dump(mode="json"),
                },
            )
        except BaseException as primary:
            self.failure_evidence(
                "primary-error.json", error_record(primary, "streaming-completion")
            )
            restored = not attempted
            if attempted:
                try:
                    with self.boundaries.lease():
                        if not self.boundaries.safe_to_restore(attempted):
                            raise DeploymentError(
                                "Restoration requires stable CloudFormation "
                                "and a resolved owned process"
                            )
                        for target in reversed(attempted):
                            release = self.boundaries.update(target, OLD_VERSION, restoring=True)
                            restoration.append(release.model_dump(mode="json"))
                    self.boundaries.cleanup()
                    write_new(
                        self.restoration_record,
                        {
                            "review_sha256": prepared.review.sha256,
                            "operation": str(self.output),
                            "verified_restorations": restoration,
                            "protected_cleanup_passed": True,
                        },
                    )
                    restored = True
                except BaseException as secondary:
                    self.failure_evidence(
                        "restoration-error.json",
                        error_record(secondary, "streaming-completion-restoration"),
                    )
                    self.failure_evidence(
                        "restoration-required.json",
                        {
                            "attempted": [target.model_key for target in attempted],
                            "verified_restorations": restoration,
                            "preserve_claims": True,
                        },
                    )
            try:
                self.boundaries.collect_failure(attempted)
            except BaseException as diagnostic:
                self.failure_evidence(
                    "diagnostic-error.json",
                    error_record(diagnostic, "streaming-completion-diagnostics"),
                )
            try:
                budget = self.ledger.summary()
            except Exception as budget_error:
                budget = {"unavailable": error_record(budget_error, "failure-budget")}
            self.failure_evidence(
                "outcome.json",
                {
                    "status": "failed-restored" if restored else "failed-restoration-required",
                    "verified_restorations": restoration,
                    "budget": budget,
                },
            )
            raise


class LiveBoundaries:
    """Only this explicitly constructed layer can create the selected AWS session."""

    def __init__(self, prepared: Prepared, output: Path, approval_path: Path | None) -> None:
        self.prepared, self.output, self.approval_path = prepared, output, approval_path
        self.session: Any = None
        self.pool: ReadPool | None = None
        self.uploaded_version: str | None = None
        self.started_at = datetime.now(UTC)
        self.controller_lock = (
            prepared.root / "artifacts/bedrock-streaming/completion-deployment.lock"
        )
        self.restoration_only = False

    def lease(self) -> AbstractContextManager[None]:
        return runtime_lease(self.prepared.root)

    def reads(self, phase: str, seconds: float = 120) -> Any:
        assert self.pool is not None
        return self.pool.view(time.monotonic() + seconds, phase)

    def assembly(self, directory: str) -> Path:
        folder = local_path(self.prepared.root, directory)
        expected = {
            name: checksum
            for name, checksum in self.prepared.plan.pinned_files.items()
            if name.startswith(directory + "/")
        }
        actual = {
            str(item.relative_to(self.prepared.root))
            for item in folder.rglob("*")
            if item.is_file()
        }
        if not expected or actual != set(expected):
            raise ValueError("The approved assembly file inventory changed")
        for name, checksum in expected.items():
            if digest(local_path(self.prepared.root, name)) != checksum:
                raise ValueError("An approved assembly file changed before dispatch")
        return folder

    def resume(self, operation: Path) -> None:
        import boto3

        self.restoration_only = True
        version = json.loads((operation / "candidate-version.json").read_bytes())
        upload = json.loads((operation / "upload-response.json").read_bytes())
        intent = json.loads((operation / "upload-intent.json").read_bytes())
        actual_version = version.get("version_id")
        if (
            version.get("artifact_sha256") != self.prepared.review.artifact_sha256
            or version.get("key") != self.prepared.review.artifact_key
            or intent.get("key") != self.prepared.review.artifact_key
            or intent.get("sha256") != self.prepared.review.artifact_sha256
            or not isinstance(actual_version, str)
            or actual_version.lower() in {"", "null", "unknown", "pending"}
            or upload.get("VersionId") != actual_version
        ):
            raise ValueError("The retained actual upload/version record differs")
        for path in operation.glob("update-*.intent.json"):
            if json.loads(path.read_bytes()).get("artifact_version_id") != actual_version:
                raise ValueError("A retained update intent differs from the actual upload version")
        self.uploaded_version = actual_version
        self.session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
        self.pool = ReadPool(self.session, self.output / "restoration-reads.jsonl")
        reads = self.reads("completion-restoration-identity")
        verify_developer_identity(reads.client("sts").get_caller_identity())
        old = SharedReview.model_validate_json(
            (self.prepared.root / "evaluations/ui-shared/interactive-02.proposed.json").read_bytes()
        )
        legacy = verify_release(old, session=reads, kind="candidate")
        if legacy["runtime"]["agentRuntimeVersion"] != "15":
            raise ValueError("The retained legacy Runtime is no longer the reviewed v15")
        write_new(self.output / "restoration-identity.json", {"legacy": legacy})

    def preflight(self) -> dict[str, Any]:
        import boto3

        self.session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
        self.pool = ReadPool(self.session, self.output / "operator-reads.jsonl")
        reads = self.reads("completion-preflight", 600)
        identity = reads.client("sts").get_caller_identity()
        verify_developer_identity(identity)
        if self.controller_lock.exists() and json.loads(self.controller_lock.read_bytes()).get(
            "active"
        ):
            raise ValueError("A completion deployment process remains unresolved")
        old = SharedReview.model_validate_json(
            (self.prepared.root / "evaluations/ui-shared/interactive-02.proposed.json").read_bytes()
        )
        legacy = verify_release(old, session=reads, kind="candidate")
        if legacy["runtime"]["agentRuntimeVersion"] != "15":
            raise ValueError("The retained legacy Runtime is no longer the reviewed v15")
        publication = verify_publication(old, reads, root=self.prepared.root)
        try:
            reads.client("s3").head_object(
                Bucket=CODE_BUCKET,
                Key=self.prepared.review.artifact_key,
                ExpectedBucketOwner=self.prepared.review.account,
            )
        except Exception as exc:
            cause: BaseException | None = exc
            for _ in range(8):
                if (
                    isinstance(cause, ClientError)
                    and cause.response.get("Error", {}).get("Code")
                    in {"404", "NoSuchKey", "NotFound"}
                    and cause.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404
                ):
                    break
                cause = cause.__cause__ if cause is not None else None
            else:
                raise
        else:
            raise ValueError(
                "The new candidate key already exists; inspect instead of uploading again"
            )
        targets = []
        for target in self.prepared.baseline_review.targets:
            release = next(
                item
                for item in self.prepared.baseline_releases.models
                if item.model_key == target.model_key
            )
            stack = reads.client("cloudformation").describe_stacks(
                StackName="enterprise-analytics-stream-" + target.model_key
            )["Stacks"][0]
            if (
                stack.get("StackId") != self.prepared.plan.baseline_stack_ids[target.model_key]
                or stack.get("RoleARN") != EXECUTION_ROLE
            ):
                raise ValueError("A streaming baseline stack identity/execution role changed")
            targets.append(
                verify_target(
                    reads,
                    self.prepared.baseline_review,
                    self.prepared.baseline_releases,
                    target,
                    release,
                )
            )
        return {
            "identity": identity,
            "legacy": legacy,
            "publication": publication,
            "targets": targets,
            "candidate_key_absent": True,
            "at": datetime.now(UTC),
        }

    def upload(self) -> str:
        review = self.prepared.review
        path = local_path(self.prepared.root, review.artifact_path)
        if path.stat().st_size != review.artifact_bytes or digest(path) != review.artifact_sha256:
            raise ValueError("The reviewed candidate ZIP changed before conditional upload")
        write_new(
            self.output / "upload-intent.json",
            {
                "bucket": CODE_BUCKET,
                "key": review.artifact_key,
                "sha256": review.artifact_sha256,
                "bytes": review.artifact_bytes,
                "sdk_total_max_attempts": 1,
                "if_none_match": "*",
                "at": datetime.now(UTC),
            },
        )
        with path.open("rb") as stream:
            result = self.session.client("s3", config=READ_CONFIG).put_object(
                Bucket=CODE_BUCKET,
                Key=review.artifact_key,
                Body=stream,
                ContentLength=review.artifact_bytes,
                ChecksumSHA256=base64.b64encode(bytes.fromhex(review.artifact_sha256)).decode(),
                IfNoneMatch="*",
                ExpectedBucketOwner=review.account,
            )
        write_new(self.output / "upload-response.json", result)
        version = result.get("VersionId")
        if (
            not isinstance(version, str)
            or not version.strip()
            or version.lower() in {"null", "pending", "unknown"}
        ):
            raise ValueError("Conditional upload did not return a real S3 VersionId; do not retry")
        self.uploaded_version = version
        write_new(
            self.output / "candidate-version.json",
            {
                "artifact_sha256": review.artifact_sha256,
                "key": review.artifact_key,
                "version_id": version,
            },
        )
        reader = self.reads("completion-upload-verification").client("s3")
        heads = [
            reader.head_object(
                Bucket=CODE_BUCKET,
                Key=review.artifact_key,
                VersionId=version,
                ChecksumMode="ENABLED",
                ExpectedBucketOwner=review.account,
            ),
            reader.head_object(
                Bucket=CODE_BUCKET,
                Key=review.artifact_key,
                ChecksumMode="ENABLED",
                ExpectedBucketOwner=review.account,
            ),
        ]
        if any(
            head.get("VersionId") != version
            or head.get("ContentLength") != review.artifact_bytes
            or head.get("ChecksumSHA256")
            != base64.b64encode(bytes.fromhex(review.artifact_sha256)).decode()
            for head in heads
        ):
            raise ValueError("The uploaded/latest S3 object does not match the exact candidate")
        write_new(self.output / "upload-verification.json", {"heads": heads, "passed": True})
        return version

    def _proof(
        self,
        target: StreamTarget,
        version: str,
        restoring: bool,
        deadline: float,
        *,
        candidate_bytes_required: bool = True,
    ) -> dict[str, Any]:
        assert self.pool is not None
        prepared = self.prepared
        review = prepared.baseline_review if restoring else prepared.review
        selected = next(item for item in review.targets if item.model_key == target.model_key)
        assembly = (
            prepared.plan.baseline_assembly_directory
            if restoring
            else prepared.plan.candidate_assembly_directory
        )
        template = None
        if restoring or (not self.restoration_only and candidate_bytes_required):
            template = json.loads(
                (
                    self.assembly(assembly)
                    / f"enterprise-analytics-stream-{target.model_key}.template.json"
                ).read_bytes()
            )
        reader = self.pool.view(deadline, "completion-exact-" + target.model_key)
        cfn = reader.client("cloudformation")
        stack = cfn.describe_stacks(StackName="enterprise-analytics-stream-" + target.model_key)[
            "Stacks"
        ][0]
        actual = cfn.get_template(StackName=stack["StackId"], TemplateStage="Original")[
            "TemplateBody"
        ]
        actual = json.loads(actual) if isinstance(actual, str) else actual
        if template is None:
            template = actual
        if (
            hashlib.sha256(json.dumps(template, sort_keys=True).encode()).hexdigest()
            != selected.template_sha256
        ):
            raise ValueError("The exact reviewed template checksum differs")
        expected_parameters = {
            name: str(value["Default"])
            for name, value in template.get("Parameters", {}).items()
            if "Default" in value
        }
        expected_parameters["ArtifactVersionId"] = version
        if (
            stack.get("StackId") != prepared.plan.baseline_stack_ids[target.model_key]
            or stack.get("RoleARN") != EXECUTION_ROLE
            or stack.get("StackStatus")
            not in (
                STABLE
                if restoring or self.restoration_only
                else {"CREATE_COMPLETE", "UPDATE_COMPLETE"}
            )
            or actual != template
            or {item["ParameterKey"]: item["ParameterValue"] for item in stack["Parameters"]}
            != expected_parameters
        ):
            raise ValueError("Exact streaming template/parameters/stack identity differ")
        baseline = next(
            item for item in prepared.baseline_releases.models if item.model_key == target.model_key
        )
        arn = baseline.runtime_arn
        control = reader.client("bedrock-agentcore-control")
        runtime = control.get_agent_runtime(agentRuntimeId=arn.rsplit("/", 1)[1])
        endpoint = control.get_agent_runtime_endpoint(
            agentRuntimeId=arn.rsplit("/", 1)[1], endpointName="DEFAULT"
        )
        current_version = runtime.get("agentRuntimeVersion")
        if (
            runtime.get("agentRuntimeArn") != arn
            or runtime.get("agentRuntimeName") != selected.runtime_name
            or runtime.get("status") != "READY"
            or endpoint.get("status") != "READY"
            or endpoint.get("liveVersion") != current_version
            or endpoint.get("targetVersion", current_version) != current_version
            or endpoint.get("agentRuntimeEndpointArn") != arn + "/runtime-endpoint/DEFAULT"
        ):
            raise ValueError("Exact Runtime/DEFAULT readiness, identity or version differ")
        resources = template["Resources"]
        properties = next(
            item["Properties"]
            for item in resources.values()
            if item["Type"] == "AWS::BedrockAgentCore::Runtime"
        )
        wanted = _resolve(properties, resources, arn, version)
        expected_artifact = {
            "codeConfiguration": {
                "runtime": "PYTHON_3_12",
                "entryPoint": ["runtime_entry.py"],
                "code": {
                    "s3": {
                        "bucket": CODE_BUCKET,
                        "prefix": review.artifact_key,
                        "versionId": version,
                    }
                },
            }
        }
        if (
            runtime.get("agentRuntimeArtifact") != expected_artifact
            or runtime.get("environmentVariables")
            != {"ANALYTICS_RUNTIME_CONFIG": selected.settings.model_dump_json()}
            or runtime.get("roleArn") != wanted["RoleArn"]
            or runtime.get("platformVersion") != wanted["PlatformVersion"]
            or runtime.get("networkConfiguration")
            != {"networkMode": wanted["NetworkConfiguration"]["NetworkMode"]}
            or runtime.get("protocolConfiguration")
            != {"serverProtocol": wanted["ProtocolConfiguration"]}
            or runtime.get("lifecycleConfiguration")
            != {
                "idleRuntimeSessionTimeout": wanted["LifecycleConfiguration"][
                    "IdleRuntimeSessionTimeout"
                ],
                "maxLifetime": wanted["LifecycleConfiguration"]["MaxLifetime"],
            }
        ):
            raise ValueError("Exact Runtime code/trusted configuration/hosting properties differ")
        policies = [
            item
            for item in resources.values()
            if item["Type"] == "AWS::BedrockAgentCore::ResourcePolicy"
        ]
        policy_arns = set()
        for item in policies:
            expected = _resolve(item["Properties"], resources, arn, version)
            observed = control.get_resource_policy(resourceArn=expected["ResourceArn"])["policy"]
            observed = json.loads(observed) if isinstance(observed, str) else observed
            expected_policy = expected["Policy"]
            expected_policy = (
                json.loads(expected_policy) if isinstance(expected_policy, str) else expected_policy
            )
            if observed != expected_policy:
                raise ValueError("Exact Runtime/DEFAULT resource policy differs")
            policy_arns.add(expected["ResourceArn"])
        if len(policies) != 2 or policy_arns != {arn, arn + "/runtime-endpoint/DEFAULT"}:
            raise ValueError("Both exact inbound policies are required")
        if restoring or candidate_bytes_required:
            head = reader.client("s3").head_object(
                Bucket=CODE_BUCKET,
                Key=review.artifact_key,
                VersionId=version,
                ChecksumMode="ENABLED",
                ExpectedBucketOwner=review.account,
            )
            if (
                head.get("VersionId") != version
                or head.get("ContentLength") != review.artifact_bytes
                or head.get("ChecksumSHA256")
                != base64.b64encode(bytes.fromhex(review.artifact_sha256)).decode()
            ):
                raise ValueError("Exact deployed S3 version, checksum or size differs")
        else:
            head = {
                "candidate_bytes_verified": False,
                "reason": (
                    "original-restoration; exact candidate pointer/template/configuration verified"
                ),
            }
        group = "/aws/bedrock-agentcore/runtimes/" + arn.rsplit("/", 1)[1] + "-DEFAULT"
        groups = reader.client("logs").describe_log_groups(logGroupNamePrefix=group)["logGroups"]
        if not any(
            item["logGroupName"] == group and item.get("retentionInDays") == 7 for item in groups
        ):
            raise ValueError("Seven-day streaming log retention differs")
        release = StreamRelease(
            model_key=selected.model_key,
            runtime_arn=arn,
            runtime_version=current_version,
            template_sha256=selected.template_sha256,
            configuration_sha256=hashlib.sha256(
                json.dumps(selected.settings.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest(),
        )
        return {
            "release": release.model_dump(mode="json"),
            "stack": stack,
            "runtime": runtime,
            "endpoint": endpoint,
            "head": head,
            "observed_at": datetime.now(UTC),
        }

    def update(self, target: StreamTarget, version: str, *, restoring: bool) -> StreamRelease:
        assert self.pool is not None
        pool = self.pool
        prepared = self.prepared
        name = "restore-" if restoring else "update-"
        name += target.model_key
        assembly = (
            prepared.plan.baseline_assembly_directory
            if restoring
            else prepared.plan.candidate_assembly_directory
        )
        template_path = (
            self.assembly(assembly)
            / f"enterprise-analytics-stream-{target.model_key}.template.json"
        )

        def baseline(stack: dict[str, Any], body: dict[str, Any]) -> None:
            if stack.get("StackId") != prepared.plan.baseline_stack_ids[target.model_key]:
                raise ValueError("The existing stack was replaced")
            parameters = {
                item["ParameterKey"]: item["ParameterValue"] for item in stack["Parameters"]
            }
            old_target = next(
                item
                for item in prepared.baseline_review.targets
                if item.model_key == target.model_key
            )
            candidate_target = next(
                item for item in prepared.review.targets if item.model_key == target.model_key
            )
            body_sha = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            original = (
                body_sha == old_target.template_sha256
                and parameters.get("ArtifactVersionId") == OLD_VERSION
            )
            candidate = (
                body_sha == candidate_target.template_sha256
                and parameters.get("ArtifactVersionId") == self.uploaded_version
            )
            if not original and not candidate:
                raise ValueError("The stack baseline is outside the exact original/candidate pair")
            if restoring and not original:
                proof = self._proof(
                    target,
                    str(self.uploaded_version),
                    False,
                    time.monotonic() + 120,
                    candidate_bytes_required=False,
                )
            else:
                proof = self._proof(
                    target,
                    OLD_VERSION if original else str(self.uploaded_version),
                    original,
                    time.monotonic() + 120,
                )
            if proof["stack"].get("LastUpdatedTime") != stack.get("LastUpdatedTime"):
                raise ValueError("The baseline changed during full pre-mutation verification")

        if restoring:
            write_new(self.output / f"{name}.original-code.json", self.original_code())
            reader = self.reads(name + "-already-original")
            stack = reader.client("cloudformation").describe_stacks(
                StackName="enterprise-analytics-stream-" + target.model_key
            )["Stacks"][0]
            body = reader.client("cloudformation").get_template(
                StackName=stack["StackId"], TemplateStage="Original"
            )["TemplateBody"]
            body = json.loads(body) if isinstance(body, str) else body
            old_body = json.loads(template_path.read_bytes())
            parameters = {
                item["ParameterKey"]: item["ParameterValue"] for item in stack["Parameters"]
            }
            if (
                stack.get("StackStatus") in STABLE
                and body == old_body
                and parameters.get("ArtifactVersionId") == OLD_VERSION
            ):
                proof = self._proof(target, OLD_VERSION, True, time.monotonic() + 120)
                after = reader.client("cloudformation").describe_stacks(StackName=stack["StackId"])[
                    "Stacks"
                ][0]
                if (
                    after.get("StackId") != stack.get("StackId")
                    or after.get("LastUpdatedTime") != stack.get("LastUpdatedTime")
                    or after.get("StackStatus") != stack.get("StackStatus")
                ):
                    raise ValueError("Original checkpoint changed during no-mutation verification")
                write_new(
                    self.output / f"{name}.verified.json",
                    {**proof, "already_original_no_mutation": True},
                )
                return StreamRelease.model_validate(proof["release"])

        controller = DeploymentController(
            self.output / "deployments",
            None,
            lock_path=self.controller_lock,
            stack_name="enterprise-analytics-stream-" + target.model_key,
            template_name=template_path.name,
            expected_execution_role=EXECUTION_ROLE,
            baseline_validator=baseline,
            read_client=lambda deadline: pool.view(deadline, name).client("cloudformation"),
            limits=DeploymentLimits(
                deployment_seconds=900,
                settle_seconds=120,
                verification_seconds=120,
                cleanup_seconds=5,
            ),
        )
        with one_sdk_attempt():
            proof = controller.deploy(
                str(local_path(prepared.root, assembly)),
                version,
                name,
                lambda deadline: self._proof(target, version, restoring, deadline),
                template_sha256=prepared.plan.pinned_files[
                    str(template_path.relative_to(prepared.root))
                ],
            )
        write_new(self.output / f"{name}.verified.json", proof)
        return StreamRelease.model_validate(proof["release"])

    def safe_to_restore(self, attempted: list[StreamTarget]) -> bool:
        if self.controller_lock.exists() and json.loads(self.controller_lock.read_bytes()).get(
            "active"
        ):
            return False
        self.original_code()
        reader = self.reads("completion-restore-stability")
        for target in attempted:
            stack = reader.client("cloudformation").describe_stacks(
                StackName="enterprise-analytics-stream-" + target.model_key
            )["Stacks"][0]
            if (
                stack.get("StackId") != self.prepared.plan.baseline_stack_ids[target.model_key]
                or stack.get("StackStatus") not in STABLE
                or stack.get("RoleARN") != EXECUTION_ROLE
            ):
                return False
            body = reader.client("cloudformation").get_template(
                StackName=stack["StackId"], TemplateStage="Original"
            )["TemplateBody"]
            body = json.loads(body) if isinstance(body, str) else body
            digest_value = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            old_target = next(
                item
                for item in self.prepared.baseline_review.targets
                if item.model_key == target.model_key
            )
            current_target = next(
                item for item in self.prepared.review.targets if item.model_key == target.model_key
            )
            params = {item["ParameterKey"]: item["ParameterValue"] for item in stack["Parameters"]}
            original = (
                digest_value == old_target.template_sha256
                and params.get("ArtifactVersionId") == OLD_VERSION
            )
            candidate = (
                digest_value == current_target.template_sha256
                and params.get("ArtifactVersionId") == self.uploaded_version
            )
            if not original and not candidate:
                return False
            self._proof(
                target,
                OLD_VERSION if original else str(self.uploaded_version),
                original,
                time.monotonic() + 120,
                candidate_bytes_required=original,
            )
        return True

    def original_code(self) -> dict[str, Any]:
        review = self.prepared.baseline_review
        head: dict[str, Any] = (
            self.reads("original-code-before-restoration")
            .client("s3")
            .head_object(
                Bucket=CODE_BUCKET,
                Key=review.artifact_key,
                VersionId=OLD_VERSION,
                ChecksumMode="ENABLED",
                ExpectedBucketOwner=review.account,
            )
        )
        if (
            head.get("VersionId") != OLD_VERSION
            or head.get("ContentLength") != review.artifact_bytes
            or head.get("ChecksumSHA256")
            != base64.b64encode(bytes.fromhex(review.artifact_sha256)).decode()
        ):
            raise ValueError(
                "The exact original code object is unavailable; no restoration mutation"
            )
        return head

    def _cli(self, action: str, extra: list[str], *, allow_partial: bool = False) -> None:
        from enterprise_analytics_agent.adapters.model_stream_cli import main as operator

        assert self.approval_path is not None
        args = [
            "--review",
            str(local_path(self.prepared.root, self.prepared.plan.review_path)),
            "--approval",
            str(self.approval_path),
            *extra,
        ]
        with (
            (self.output / f"{action}.stdout.log").open("x") as out,
            (self.output / f"{action}.stderr.log").open("x") as err,
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            result = operator(args)
        if result != 0 and not (allow_partial and result == 1):
            raise RuntimeError(
                f"Reviewed {action} stopped with exit code {result}; preserve its diagnostics"
            )

    def evaluate(self, releases: StreamingReleases) -> None:
        workbench = self.prepared.plan.schema_version == "bedrock-workbench-preparation-v1"
        self._cli(
            "evaluation",
            [
                "--releases",
                str(self.output / "releases.actual.json"),
                "evaluate",
                "--invoke-live",
                "--output",
                str(self.output / "acceptance"),
            ],
            allow_partial=workbench,
        )
        if workbench:
            summary = json.loads((self.output / "acceptance/summary.json").read_bytes())
            ledger = StreamingLedger(self.prepared.root, self.prepared.review)
            accepted_models = []
            for target in self.prepared.review.targets:
                record = json.loads(
                    (ledger.directory / "acceptance" / f"{target.model_key}.json").read_bytes()
                )
                if (
                    record.get("review_sha256") != self.prepared.review.sha256
                    or record.get("model_key") != target.model_key
                ):
                    raise ValueError("Per-model acceptance proof has a different binding")
                if record.get("passed") is True:
                    if record.get("cases") != ["Q18", "all-five-regionals"]:
                        raise ValueError("Per-model acceptance proof is incomplete")
                    accepted_models.append(target.model_key)
            if (
                not accepted_models
                or summary.get("models") != accepted_models
                or summary.get("review_sha256") != self.prepared.review.sha256
                or ledger.summary()["blocked"]
            ):
                raise ValueError("No independently accepted, usable workbench models remain")
            return
        accepted_path = (
            StreamingLedger(self.prepared.root, self.prepared.review).directory / "accepted.json"
        )
        accepted = json.loads(accepted_path.read_bytes())
        if (
            accepted.get("passed") is not True
            or accepted.get("questions") != 20
            or accepted.get("review_sha256") != self.prepared.review.sha256
            or set(accepted.get("models", [])) != {item.model_key for item in releases.models}
        ):
            raise ValueError("Complete twenty-question acceptance proof is missing")

    def cleanup(self) -> None:
        self._cli(
            "cleanup", ["cleanup", "--invoke-live", "--output", str(self.output / "cleanup.json")]
        )

    def collect_failure(self, attempted: list[StreamTarget]) -> None:
        if self.session is None:
            return
        deadline = time.monotonic() + 120
        evidence: dict[str, Any] = {
            "at": datetime.now(UTC),
            "lookup_is_bounded_not_exhaustive": True,
            "stacks": {},
            "cloudtrail": [],
        }
        cfn = self.session.client("cloudformation", config=READ_CONFIG)
        for target in attempted:
            if time.monotonic() >= deadline:
                break
            name = "enterprise-analytics-stream-" + target.model_key
            try:
                evidence["stacks"][name] = cfn.describe_stack_events(
                    StackName=self.prepared.plan.baseline_stack_ids[target.model_key]
                )
            except Exception as exc:
                evidence["stacks"][name] = error_record(exc, "failure-stack-events")
        trail = self.session.client("cloudtrail", config=READ_CONFIG)
        end_time = datetime.now(UTC)
        for source in (
            "bedrock-agentcore.amazonaws.com",
            "bedrock.amazonaws.com",
            "iam.amazonaws.com",
            "logs.amazonaws.com",
            "sts.amazonaws.com",
        ):
            token = None
            for _ in range(5):
                if time.monotonic() >= deadline:
                    break
                arguments: dict[str, Any] = {
                    "LookupAttributes": [{"AttributeKey": "EventSource", "AttributeValue": source}],
                    "StartTime": self.started_at,
                    "EndTime": end_time,
                    "MaxResults": 50,
                }
                if token:
                    arguments["NextToken"] = token
                try:
                    # LookupEvents is limited to two requests per second. This
                    # remains read-only, finite and independent of SDK retries.
                    time.sleep(min(0.6, max(0, deadline - time.monotonic())))
                    if time.monotonic() >= deadline:
                        break
                    response = trail.lookup_events(**arguments)
                    for item in response.get("Events", []):
                        event = json.loads(item["CloudTrailEvent"])
                        if "enterprise-analytics-stream" in json.dumps(
                            event
                        ) or "enterprise_analytics_stream" in json.dumps(event):
                            evidence["cloudtrail"].append(event)
                    token = response.get("NextToken")
                    if not token:
                        break
                except Exception as exc:
                    evidence["cloudtrail"].append(error_record(exc, "failure-cloudtrail"))
                    break
        write_new(self.output / "aws-failure-evidence.json", evidence)


def main(
    argv: list[str] | None = None,
    *,
    root: Path = ROOT,
    boundary_factory: Callable[[Prepared, Path, Path | None], Boundaries] = LiveBoundaries,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("verify-offline")
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--read-only-aws", action="store_true")
    preflight.add_argument("--output", type=Path, required=True)
    execute = commands.add_parser("execute")
    execute.add_argument("--approval", type=Path, required=True)
    execute.add_argument("--execute-approved", action="store_true")
    execute.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--approval", type=Path, required=True)
    restore.add_argument("--execute-approved", action="store_true")
    restore.add_argument("--operation", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = root.resolve()
        if Path.cwd().resolve() != root:
            raise ValueError("Run the completion operator from its original checkout root")
        prepared = load_prepared(root, args.plan.absolute(), restoration=args.command == "restore")
        if args.command == "verify-offline":
            print(
                json.dumps(
                    {
                        "passed": True,
                        "review_sha256": prepared.review.sha256,
                        "budget": StreamingLedger(root, prepared.review).summary(),
                        "aws_calls": 0,
                    }
                )
            )
            return 0
        if (args.command == "preflight" and not args.read_only_aws) or (
            args.command in {"execute", "restore"} and not args.execute_approved
        ):
            raise ValueError("The explicit read-only or approved-execution gate is required")
        output = args.output.absolute()
        if output.resolve() != output or not output.is_relative_to(root) or output.exists():
            raise ValueError("Use a new report directory inside the original checkout")
        approval_path = args.approval.absolute() if args.command in {"execute", "restore"} else None
        if approval_path is not None and (
            approval_path.resolve() != approval_path or not approval_path.is_relative_to(root)
        ):
            raise ValueError("Use an unaliased approval file inside the checkout")
        boundaries = boundary_factory(prepared, output, approval_path)
        if args.command == "preflight":
            output.mkdir(parents=True, exist_ok=False)
            try:
                with boundaries.lease():
                    write_new(output / "preflight.json", boundaries.preflight())
            except BaseException as exc:
                try:
                    write_new(
                        output / "preflight-error.json", error_record(exc, "completion-preflight")
                    )
                except Exception:
                    pass
                raise
        else:
            assert approval_path is not None
            workflow = CompletionWorkflow(
                prepared, output, json.loads(approval_path.read_bytes()), boundaries
            )
            if args.command == "restore":
                operation = args.operation.absolute()
                if (
                    operation.resolve() != operation
                    or not operation.is_relative_to(root)
                    or not operation.is_dir()
                ):
                    raise ValueError("Use the retained unaliased original operation directory")
                workflow.restore(operation)
            else:
                workflow.run()
        print(json.dumps({"passed": True, "operation": args.command, "output": str(output)}))
        return 0
    except KeyboardInterrupt:
        print(
            json.dumps(
                {"passed": False, "error_type": "KeyboardInterrupt", "preserve_claims": True}
            )
        )
        return 130
    except Exception as exc:
        print(json.dumps({"passed": False, "error": error_record(exc, "streaming-completion-cli")}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
