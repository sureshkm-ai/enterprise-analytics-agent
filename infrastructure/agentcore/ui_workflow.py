"""Prepare and supervise the reviewed shared UI release; never invoke a model.

All deployment actions require a separate execution approval and explicit CLI gate.
Success deliberately leaves the shared candidate deployed. A failed candidate attempt
restores the separately pinned original whenever controller/process guards permit it.
"""

import argparse
import fcntl
import json
import os
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3

from enterprise_analytics_agent.adapters.deployment_controller import DeploymentController
from enterprise_analytics_agent.adapters.operator_reads import ReadPool
from enterprise_analytics_agent.adapters.repair_operations import verify_uploaded_version
from enterprise_analytics_agent.adapters.ui_release import (
    ROOT,
    ReleaseKind,
    _paths,
    _template,
    make_record,
    verify_local_release,
    verify_publication,
    verify_release,
)
from enterprise_analytics_agent.retail_evaluation.campaign import CODE_SHA256, CODE_VERSION
from enterprise_analytics_agent.retail_evaluation.deployment import (
    TEMPLATE_NAME,
    candidate_review_templates,
    digest,
)
from enterprise_analytics_agent.retail_evaluation.operator_errors import error_record
from enterprise_analytics_agent.retail_evaluation.repair_cli import interruption_guard
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    load_review,
)
from enterprise_analytics_agent.retail_evaluation.reporting import _redact
from enterprise_analytics_agent.ui.models import UiError
from enterprise_analytics_agent.ui.shared import SharedReview


def _write(path: Path, value: object) -> None:
    encoded = json.dumps(_redact(value), indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _operator_lease(root: Path) -> Iterator[None]:
    """Own only the global operator lease; the controller owns deployment locking."""
    root = root.resolve()
    path = root / "artifacts/milestone-5/runtime-operator.lock"
    journal = root / "artifacts/milestone-5/runtime-deployment.lock"
    if path.resolve() != path or not path.is_file() or journal.resolve() != journal:
        raise UiError("Retained Runtime process guards are missing or aliased.")
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UiError(
                "Another UI/operator owns the Runtime; no deployment may overlap."
            ) from exc
        value = json.loads(journal.read_bytes())
        if value.get("active") is not False or value.get("process_group") is not None:
            raise UiError("A retained deployment process is unresolved; inspect its evidence.")
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def prepare_deployment(root: Path, review: SharedReview, output: Path) -> dict[str, Any]:
    """Copy existing reviewed assemblies to a new directory; never rebuild/upload code."""
    root = root.resolve()
    local = verify_local_release(root, review, root / "artifacts/milestone-5/canonical/retail-v1")
    if output.exists():
        raise ValueError("UI preparation directory already exists; preserve the previous assembly")
    output.mkdir(parents=True)
    for kind, destination in (("candidate", "candidate"), ("original", "rollback")):
        _, template = _paths(kind, root=root)  # type: ignore[arg-type]
        _template(kind, root=root)  # type: ignore[arg-type]
        source = template.parent
        if any(path.is_symlink() for path in source.rglob("*")):
            raise ValueError("Reviewed assembly contains an aliased path")
        shutil.copytree(source, output / destination)
    files = {
        str(path.relative_to(output)): digest(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    result: dict[str, Any] = {
        "schema_version": "ui-shared-assemblies-v1",
        "review_sha256": review.sha256,
        "candidate_template_sha256": review.runtime_template_sha256,
        "original_template_sha256": digest(_paths("original", root=root)[1]),
        "candidate_artifact_version_id": review.artifact_version_id,
        "original_artifact_version_id": CODE_VERSION,
        "files": files,
        "local": local,
        "limitations": "Offline copy only: no deployment, upload, IAM change or live acceptance.",
    }
    _write(output / "assembly-review.json", result)
    return result


def _prepared(
    root: Path, review: SharedReview, directory: Path, *, restore_only: bool = False
) -> tuple[Path, Path]:
    record = json.loads((directory / "assembly-review.json").read_bytes())
    if record.get("review_sha256") != review.sha256:
        raise ValueError("Prepared assemblies are bound to another review")
    expected = {
        name: checksum
        for name, checksum in record["files"].items()
        if not restore_only or name.startswith("rollback/")
    }
    actual = {
        str(path.relative_to(directory)): digest(path)
        for path in directory.rglob("*")
        if path.is_file()
        and path != directory / "assembly-review.json"
        and (not restore_only or path.is_relative_to(directory / "rollback"))
    }
    checked = directory / "rollback" if restore_only else directory
    if not expected or actual != expected or any(path.is_symlink() for path in checked.rglob("*")):
        raise ValueError("Prepared assembly inventory or bytes changed")
    candidate, original = directory / "candidate", directory / "rollback"
    if (
        not restore_only and digest(candidate / TEMPLATE_NAME) != review.runtime_template_sha256
    ) or digest(original / TEMPLATE_NAME) != digest(_paths("original", root=root)[1]):
        raise ValueError("Prepared deployment/restoration template differs from its frozen pin")
    if (
        not restore_only
        and record.get("candidate_artifact_version_id") != review.artifact_version_id
    ) or record.get("original_artifact_version_id") != CODE_VERSION:
        raise ValueError("Prepared artifact version differs from the frozen version")
    return candidate, original


@dataclass(frozen=True)
class WorkflowOperations:
    verify_original: Callable[[], dict[str, Any]]
    deploy_candidate: Callable[[], dict[str, Any]]
    restore_original: Callable[[], dict[str, Any]]


def _operations(
    root: Path,
    review: SharedReview,
    directory: Path,
    prepared: Path,
    *,
    restore_only: bool,
) -> WorkflowOperations:
    if Path.cwd().resolve() != root.resolve():
        raise UiError("Run the deployment operator from the original repository root")
    if restore_only:
        original_archive, _ = _paths("original", root=root)
        if digest(original_archive) != CODE_SHA256:
            raise ValueError("Frozen original rollback ZIP changed")
        _template("original", root=root)
    else:
        verify_local_release(root, review, root / "artifacts/milestone-5/canonical/retail-v1")
    candidate, original = _prepared(root, review, prepared, restore_only=restore_only)
    session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
    reads = ReadPool(session, directory / "operator-reads.jsonl")
    identity = (
        reads.view(time.monotonic() + 120, "ui-operator-identity")
        .client("sts")
        .get_caller_identity()
    )
    if identity.get("Account") != review.target.account:
        raise ValueError("Operator account differs from the reviewed account")
    if not restore_only:
        publication = verify_publication(
            review, reads.view(time.monotonic() + 180, "ui-publication-preflight"), root=root
        )
        _write(directory / "publication-preflight.json", publication)
        repair = load_review(repository_root=root)
        version = CandidateVersionBinding.model_validate_json(
            (root / "artifacts/milestone-5/q18-repair-v1/candidate-version.json").read_bytes()
        )
        version.require_review(repair)
        if version.version_id != review.artifact_version_id:
            raise ValueError("Candidate VersionId differs from the reviewed shared release")
        verify_uploaded_version(
            repair,
            {"VersionId": version.version_id},
            session=reads.view(time.monotonic() + 180, "ui-candidate-upload-preflight"),
        )

    def verify(kind: ReleaseKind, deadline: float | None = None) -> dict[str, Any]:
        return verify_release(
            review,
            kind=kind,
            session=reads.view(
                deadline if deadline is not None else time.monotonic() + 180,
                "ui-" + kind + "-checkpoint",
            ),
        )

    original_template = _template("original")

    def baseline(stack: dict[str, Any], template: dict[str, Any]) -> None:
        version_id = {
            item["ParameterKey"]: item["ParameterValue"] for item in stack.get("Parameters", [])
        }.get("ArtifactVersionId")
        if template == original_template:
            if version_id != CODE_VERSION:
                raise ValueError("Current original artifact version differs from review")
        else:
            candidate_review_templates(
                original_template, template, candidate_sha256=review.archive_sha256
            )
            if version_id != review.artifact_version_id:
                raise ValueError("Current candidate artifact version differs from review")

    controller = DeploymentController(
        directory,
        reads.view(time.monotonic() + 180, "ui-deployment-preflight").client("cloudformation"),
        lock_path=root / "artifacts/milestone-5/runtime-deployment.lock",
        baseline_validator=baseline,
        read_client=lambda deadline: reads.view(deadline, "ui-deployment-reconciliation").client(
            "cloudformation"
        ),
    )
    return WorkflowOperations(
        verify_original=lambda: verify("original"),
        deploy_candidate=lambda: controller.deploy(
            str(candidate),
            review.artifact_version_id,
            "candidate",
            lambda deadline: verify("candidate", deadline),
            template_sha256=review.runtime_template_sha256,
        ),
        restore_original=lambda: controller.deploy(
            str(original),
            CODE_VERSION,
            "rollback",
            lambda deadline: verify("original", deadline),
            template_sha256=digest(_paths("original", root=root)[1]),
        ),
    )


def execute_workflow(
    root: Path,
    review: SharedReview,
    directory: Path,
    *,
    restore_only: bool = False,
    operations: WorkflowOperations | None = None,
    prepared: Path | None = None,
) -> dict[str, Any]:
    """A single supervised deployment; no question, smoke or model API is called."""
    if not restore_only and datetime.now(UTC) >= review.expires_at:
        raise UiError("The approved UI window expired; no mutation was attempted")
    directory.mkdir(parents=True, exist_ok=False)
    state: dict[str, Any] = {
        "schema_version": "ui-shared-deployment-outcome-v1",
        "review_sha256": review.sha256,
        "candidate_attempted": False,
        "candidate_deployed": False,
        "restored": False,
        "succeeded": False,
        "billable_invocations": 0,
        "live_acceptance_pending": True,
    }
    interrupted: BaseException | None = None
    with _operator_lease(root):
        try:
            ops = operations or _operations(
                root,
                review,
                directory,
                prepared or root / "artifacts/ui-shared/deployment",
                restore_only=restore_only,
            )
            if restore_only:
                checkpoint = ops.restore_original()
                record = make_record(review, checkpoint, kind="original")
                _write(directory / "rollback-record.json", record.model_dump(mode="json"))
                state.update(
                    restored=True,
                    succeeded=True,
                    steady_state="original-parity",
                    shared_ui_disabled=True,
                    rollback_smoke_pending=True,
                    runtime_version=record.runtime_version,
                )
            else:
                original = ops.verify_original()
                record = make_record(review, original, kind="original")
                if record.runtime_version != "12":
                    raise UiError("Original preflight must match the reviewed READY v12 checkpoint")
                _write(directory / "original-checkpoint.json", original)
                _write(directory / "original-record.json", record.model_dump(mode="json"))
                if datetime.now(UTC) >= review.expires_at:
                    raise UiError(
                        "The approved UI window expired during preflight; no mutation was attempted"
                    )
                state["candidate_attempted"] = True
                checkpoint = ops.deploy_candidate()
                record = make_record(review, checkpoint)
                if datetime.now(UTC) >= review.expires_at:
                    raise UiError(
                        "The approved UI window expired during deployment; restoring original"
                    )
                _write(directory / "candidate-checkpoint.json", checkpoint)
                _write(directory / "release-record.json", record.model_dump(mode="json"))
                state.update(
                    candidate_deployed=True,
                    succeeded=True,
                    steady_state="candidate-retail",
                    runtime_version=record.runtime_version,
                )
        except BaseException as exc:
            state["error"] = error_record(exc, "shared-ui-deployment")
            if not isinstance(exc, Exception):
                interrupted = exc
            if state["candidate_attempted"]:
                try:
                    checkpoint = ops.restore_original()
                    record = make_record(review, checkpoint, kind="original")
                    _write(directory / "rollback-checkpoint.json", checkpoint)
                    _write(directory / "rollback-record.json", record.model_dump(mode="json"))
                    state.update(
                        restored=True,
                        steady_state="original-parity",
                        shared_ui_disabled=True,
                        rollback_smoke_pending=True,
                        runtime_version=record.runtime_version,
                    )
                except BaseException as restoration_error:
                    state["restoration_error"] = error_record(
                        restoration_error, "shared-ui-original-restoration"
                    )
                    if interrupted is None and not isinstance(restoration_error, Exception):
                        interrupted = restoration_error
        finally:
            _write(directory / "deployment-result.json", state)
    if interrupted is not None:
        raise interrupted
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_subparsers(dest="action", required=True)
    for name in ("prepare", "preflight", "bind", "deploy", "restore"):
        command = action.add_parser(name)
        command.add_argument("--review", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name in {"preflight", "bind"}:
            command.add_argument(
                "--kind",
                choices=("candidate", "original"),
                default="candidate" if name == "bind" else "original",
            )
        if name in {"deploy", "restore"}:
            command.add_argument("--execute-approved", required=True, action="store_true")
            command.add_argument(
                "--prepared-dir", type=Path, default=ROOT / "artifacts/ui-shared/deployment"
            )
    args = parser.parse_args(argv)
    try:
        review = SharedReview.model_validate_json(args.review.read_bytes())
        if args.action == "prepare":
            result = prepare_deployment(ROOT, review, args.output)
        elif args.action in {"preflight", "bind"}:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            journal = args.output.with_name(args.output.name + ".reads.jsonl")
            if args.output.exists() or journal.exists():
                raise ValueError("Output/read evidence already exists; preserve the previous run")
            with _operator_lease(ROOT):
                local = verify_local_release(
                    ROOT, review, ROOT / "artifacts/milestone-5/canonical/retail-v1"
                )
                session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
                reads = ReadPool(session, journal)
                identity = (
                    reads.view(time.monotonic() + 120, "ui-operator-identity")
                    .client("sts")
                    .get_caller_identity()
                )
                if identity.get("Account") != review.target.account:
                    raise ValueError("Operator account differs from the reviewed account")
                publication = verify_publication(
                    review,
                    reads.view(time.monotonic() + 180, "ui-publication-preflight"),
                    root=ROOT,
                )
                checkpoint = verify_release(
                    review,
                    kind=args.kind,
                    session=reads.view(time.monotonic() + 180, "ui-read-only-preflight"),
                )
                record = make_record(review, checkpoint, kind=args.kind)
                result = (
                    record.model_dump(mode="json")
                    if args.action == "bind"
                    else {
                        "record": record.model_dump(mode="json"),
                        "checkpoint": checkpoint,
                        "local": local,
                        "publication": publication,
                    }
                )
                _write(args.output, result)
        else:
            with interruption_guard():
                result = execute_workflow(
                    ROOT,
                    review,
                    args.output,
                    restore_only=args.action == "restore",
                    prepared=args.prepared_dir,
                )
        print(json.dumps(_redact(result), indent=2))
        return 0 if args.action not in {"deploy", "restore"} or result["succeeded"] else 1
    except Exception as exc:
        print(json.dumps(error_record(exc, "ui-workflow-command"), indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
