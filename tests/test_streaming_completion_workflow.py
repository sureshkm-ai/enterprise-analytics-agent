"""Offline operator lifecycles; real command parsing/evidence with injected AWS edges."""

import base64
import hashlib
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NoReturn

import boto3
import pytest
from botocore.exceptions import ClientError

from enterprise_analytics_agent.adapters.operator_reads import ReadPool
from enterprise_analytics_agent.ui.model_streams import (
    StreamingReleases,
    StreamingReview,
    StreamRelease,
    StreamTarget,
)
from infrastructure.agentcore import streaming_completion as module

REPO = Path(__file__).resolve().parents[1]
STAMP = datetime(2026, 11, 12, 12, 34, tzinfo=timezone(timedelta(hours=5, minutes=30)))


@pytest.fixture(autouse=True)
def no_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("The completion workflow tests must never create AWS clients")

    monkeypatch.setattr(boto3, "Session", forbidden)
    monkeypatch.setattr(boto3, "client", forbidden)


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepared(root: Path) -> module.Prepared:
    old = StreamingReview.model_validate_json(
        (REPO / "evaluations/bedrock-streaming/review.recovery.proposed.json").read_bytes()
    )
    old_targets: list[StreamTarget] = []
    targets: list[StreamTarget] = []
    for target in old.targets:
        for directory, selected in (("baseline", old_targets), ("candidate", targets)):
            body = {
                "Parameters": {"ArtifactVersionId": {"Type": "String"}},
                "Resources": {},
                "Outputs": {"Model": {"Value": target.model_key + directory}},
            }
            path = (
                root / directory / f"enterprise-analytics-stream-{target.model_key}.template.json"
            )
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(body))
            selected.append(target.model_copy(update={"template_sha256": sha(body)}))
    old = old.model_copy(update={"targets": tuple(old_targets)})
    raw = old.model_dump(mode="json")
    raw.update(
        schema_version="bedrock-model-stream-continuation-v1",
        campaign_id="bedrock-stream-authored-completion",
        maximum_attempts=37,
        ordinary_limit=35,
        expires_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
        targets=[item.model_dump(mode="json") for item in targets],
        artifact_path="candidate.zip",
        parent={
            "campaign_id": old.campaign_id,
            "review_path": "baseline-review.json",
            "review_sha256": old.sha256,
            "journal_sha256": "a" * 64,
            "acceptance_claim_sha256": "b" * 64,
            "inventory_sha256": "c" * 64,
        },
    )
    review = StreamingReview.model_validate(raw)
    releases = StreamingReleases(
        review_sha256=old.sha256,
        artifact_version_id=module.OLD_VERSION,
        models=tuple(release(item, "1") for item in old.targets),
    )
    plan = module.CompletionPlan(
        schema_version="bedrock-streaming-completion-preparation-v1",
        review_path="review.json",
        review_sha256=review.sha256,
        baseline_review_path="baseline-review.json",
        baseline_releases_path="baseline-releases.json",
        baseline_releases_sha256="a" * 64,
        baseline_assembly_directory="baseline",
        candidate_assembly_directory="candidate",
        canonical_directory="canonical",
        process_guard_path="old-guard.json",
        process_guard_sha256="b" * 64,
        baseline_stack_ids={
            item.model_key: (
                "arn:aws:cloudformation:us-west-2:453711491609:stack/"
                f"enterprise-analytics-stream-{item.model_key}/authored-stack-id"
            )
            for item in old.targets
        },
        pinned_files={
            str(path.relative_to(root)): module.digest(path)
            for directory in (root / "baseline", root / "candidate")
            for path in directory.glob("*.json")
        },
    )
    return module.Prepared(root, plan, "d" * 64, review, old, releases)


def release(target: StreamTarget, version: str) -> StreamRelease:
    return StreamRelease(
        model_key=target.model_key,
        runtime_arn=(
            "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
            + target.runtime_name
            + "-AuthoredFixture"
        ),
        runtime_version=version,
        template_sha256=target.template_sha256,
        configuration_sha256=sha(target.settings.model_dump(mode="json")),
    )


def approval(item: module.Prepared) -> dict[str, object]:
    return {
        "approved": True,
        "review_sha256": item.review.sha256,
        "preparation_sha256": item.plan_sha256,
        "maximum_attempts": item.review.maximum_attempts,
        "expires_at": item.review.expires_at.isoformat(),
    }


@dataclass
class Ledger:
    calls: list[str] = field(default_factory=list)
    used: int = 0
    cleanup_used: bool = False
    claimed: bool = False

    def claim_continuation(self, approved: object) -> None:
        self.calls.append("claim")
        self.claimed = True

    def summary(self) -> dict[str, Any]:
        return {
            "used": self.used,
            "maximum": 37,
            "prior_used": 3,
            "aggregate_used": self.used + 3,
            "aggregate_maximum": 40,
            "continuation_claimed": self.claimed,
            "protected_cleanup": 0 if self.cleanup_used else 1,
        }


@dataclass
class Edges:
    item: module.Prepared
    ledger: Ledger
    failure: str | None = None
    active: bool = False
    updates: list[str] = field(default_factory=list)
    restorations: list[str] = field(default_factory=list)
    upload_calls: int = 0
    evaluation_calls: int = 0
    cleanup_calls: int = 0
    diagnostic_calls: int = 0

    @contextmanager
    def lease(self) -> Iterator[None]:
        assert not self.active, "Never overlap or nest deployment leases"
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def preflight(self) -> dict[str, Any]:
        assert self.active
        if self.failure == "preflight":
            raise ValueError("authored checkpoint drift")
        return {
            "runtime": {"createdAt": STAMP, "lastUpdatedAt": STAMP},
            "endpoint": {"createdAt": STAMP, "lastUpdatedAt": STAMP},
            "s3": {"LastModified": STAMP},
            "ResponseMetadata": {"secret": "hidden"},
        }

    def upload(self) -> str:
        assert self.active and self.ledger.claimed
        self.upload_calls += 1
        if self.failure == "upload":
            raise ValueError("authored upload denial")
        return "ACTUAL-NEW-S3-VERSION"

    def update(self, target: StreamTarget, version: str, *, restoring: bool) -> StreamRelease:
        assert self.active
        if restoring:
            assert version == module.OLD_VERSION
            self.restorations.append(target.model_key)
            if self.failure == "restoration":
                raise RuntimeError("authored restoration failure")
            old = next(
                item
                for item in self.item.baseline_review.targets
                if item.model_key == target.model_key
            )
            return release(old, "7")
        assert version == "ACTUAL-NEW-S3-VERSION"
        self.updates.append(target.model_key)
        if self.failure == "update" and len(self.updates) == 2:
            raise ValueError("authored update failure")
        if self.failure == "interrupt" and len(self.updates) == 2:
            raise KeyboardInterrupt
        return release(target, "2")

    def safe_to_restore(self, attempted: list[StreamTarget]) -> bool:
        assert self.active and attempted
        return self.failure != "unresolved"

    def evaluate(self, releases: StreamingReleases) -> None:
        assert not self.active
        releases.validate_review(self.item.review)
        self.evaluation_calls += 1
        if self.failure in {"evaluation", "restoration", "unresolved", "cleanup"}:
            self.ledger.used += 1
            raise ValueError("authored acceptance failure")
        self.ledger.used += 20

    def cleanup(self) -> None:
        assert not self.active and not self.ledger.cleanup_used
        self.cleanup_calls += 1
        self.ledger.cleanup_used = True
        self.ledger.used += 1
        if self.failure == "cleanup":
            raise RuntimeError("authored smoke failure")

    def collect_failure(self, attempted: list[StreamTarget]) -> None:
        assert not self.active
        self.diagnostic_calls += 1

    def resume(self, operation: Path) -> None:
        assert operation.is_dir()
        if self.failure == "resume":
            raise ValueError("authored restoration identity failure")


def test_complete_cli_success_keeps_exact_versions_and_redacts_datetime_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = prepared(tmp_path)
    ledger, output = Ledger(), tmp_path / "execution"
    edges = Edges(item, ledger)
    approved = tmp_path / "approval.json"
    approved.write_text(json.dumps(approval(item)))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "load_prepared", lambda *args, **kwargs: item)
    monkeypatch.setattr(module, "StreamingLedger", lambda *args: ledger)
    assert (
        module.main(
            [
                "--plan",
                "plan.json",
                "execute",
                "--execute-approved",
                "--approval",
                "approval.json",
                "--output",
                "execution",
            ],
            root=tmp_path,
            boundary_factory=lambda *args: edges,
        )
        == 0
    )
    context = json.loads((output / "preflight.json").read_bytes())
    assert context["runtime"]["createdAt"] == STAMP.isoformat()
    assert context["endpoint"]["lastUpdatedAt"] == STAMP.isoformat()
    assert context["s3"]["LastModified"] == STAMP.isoformat()
    assert context["ResponseMetadata"] == "[redacted]"
    result = json.loads((output / "outcome.json").read_bytes())
    assert result["status"] == "accepted" and result["budget"]["aggregate_used"] == 23
    assert {row["runtime_version"] for row in result["releases"]["models"]} == {"2"}
    assert len(edges.updates) == 10 and edges.upload_calls == edges.evaluation_calls == 1
    assert not edges.restorations and not edges.cleanup_calls


@pytest.mark.parametrize(
    "failure", ["update", "evaluation", "interrupt", "restoration", "unresolved", "cleanup"]
)
def test_failure_and_interruption_restore_all_attempted_targets_without_retries(
    tmp_path: Path, failure: str
) -> None:
    item, ledger = prepared(tmp_path), Ledger()
    edges = Edges(item, ledger, failure=failure)
    output = tmp_path / "execution"
    with pytest.raises(KeyboardInterrupt if failure == "interrupt" else ValueError):
        module.CompletionWorkflow(item, output, approval(item), edges, ledger=ledger).run()
    assert edges.upload_calls == 1
    assert edges.diagnostic_calls == 1
    assert (
        json.loads((output / "primary-error.json").read_bytes())["phase"] == "streaming-completion"
    )
    result = json.loads((output / "outcome.json").read_bytes())
    if failure in {"restoration", "unresolved", "cleanup"}:
        assert result["status"] == "failed-restoration-required"
        assert (output / "restoration-required.json").exists()
    else:
        assert result["status"] == "failed-restored"
        assert edges.restorations == list(reversed(edges.updates))
        assert {entry["runtime_version"] for entry in result["verified_restorations"]} == {"7"}
    assert edges.cleanup_calls == (0 if failure in {"restoration", "unresolved"} else 1)
    assert edges.evaluation_calls == (0 if failure in {"update", "interrupt"} else 1)


@pytest.mark.parametrize("failure", ["preflight", "upload"])
def test_failure_before_candidate_update_spends_no_question_or_cleanup(
    tmp_path: Path, failure: str
) -> None:
    item, ledger = prepared(tmp_path), Ledger()
    edges = Edges(item, ledger, failure=failure)
    with pytest.raises(ValueError):
        module.CompletionWorkflow(
            item, tmp_path / "execution", approval(item), edges, ledger=ledger
        ).run()
    assert not edges.updates and not edges.restorations
    assert not edges.evaluation_calls and not edges.cleanup_calls and ledger.used == 0


def test_wrong_preparation_approval_fails_before_any_boundary_or_claim(tmp_path: Path) -> None:
    item, ledger = prepared(tmp_path), Ledger()
    edges = Edges(item, ledger)
    approved = {**approval(item), "preparation_sha256": "f" * 64}
    with pytest.raises(ValueError, match="exact preparation"):
        module.CompletionWorkflow(
            item, tmp_path / "execution", approved, edges, ledger=ledger
        ).run()
    assert not ledger.claimed and not edges.upload_calls and not (tmp_path / "execution").exists()


@pytest.mark.parametrize("resume_failure", [False, True])
def test_restore_only_cli_reuses_claim_without_upload_evaluation_or_extra_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume_failure: bool
) -> None:
    item, ledger = prepared(tmp_path), Ledger(claimed=True, used=1)
    edges = Edges(item, ledger, failure="resume" if resume_failure else None)
    operation = tmp_path / "interrupted"
    operation.mkdir()
    for target in item.review.targets[:2]:
        (operation / f"update-{target.model_key}.intent.json").write_text(
            json.dumps({"model_key": target.model_key})
        )
    module.write_new(
        tmp_path
        / "artifacts/bedrock-streaming/completion-claims"
        / f"{item.review.campaign_id}.json",
        {
            "review_sha256": item.review.sha256,
            "preparation_sha256": item.plan_sha256,
            "output": str(operation),
        },
    )
    (tmp_path / "approval.json").write_text(json.dumps(approval(item)))
    modes = []

    def load(*args: object, restoration: bool = False) -> module.Prepared:
        modes.append(restoration)
        return item

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "load_prepared", load)
    monkeypatch.setattr(module, "StreamingLedger", lambda *args: ledger)
    args = [
        "--plan",
        "plan.json",
        "restore",
        "--execute-approved",
        "--approval",
        "approval.json",
        "--operation",
        "interrupted",
        "--output",
        "restoration",
    ]
    assert module.main(args, root=tmp_path, boundary_factory=lambda *args: edges) == (
        1 if resume_failure else 0
    )
    if resume_failure:
        assert (tmp_path / "restoration/restoration-error.json").exists()
        assert (tmp_path / "restoration/restoration-required.json").exists()
        assert not edges.cleanup_calls and not edges.restorations
        return
    assert modes == [True] and edges.cleanup_calls == 1
    assert not edges.upload_calls and not edges.evaluation_calls and ledger.calls == []
    assert (
        module.main(
            [*args[:-1], "second-restoration"], root=tmp_path, boundary_factory=lambda *args: edges
        )
        == 1
    )
    assert edges.cleanup_calls == 1 and len(edges.restorations) == 2


@pytest.mark.parametrize("failure", [None, "upload", "head"])
def test_upload_is_conditional_single_attempt_and_verified_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    item = prepared(tmp_path)
    data = b"authored-zip"
    (tmp_path / item.review.artifact_path).write_bytes(data)
    review = item.review.model_copy(
        update={"artifact_sha256": hashlib.sha256(data).hexdigest(), "artifact_bytes": len(data)}
    )
    item = module.Prepared(
        item.root, item.plan, item.plan_sha256, review, item.baseline_review, item.baseline_releases
    )

    class S3:
        def __init__(self) -> None:
            self.puts: list[dict[str, Any]] = []
            self.heads: list[dict[str, Any]] = []

        def put_object(self, **kwargs: Any) -> dict[str, Any]:
            self.puts.append(kwargs)
            assert kwargs["Body"].read() == b"authored-zip"
            if failure == "upload":
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")
            return {
                "VersionId": "ACTUAL-UPLOAD-VERSION",
                "ResponseMetadata": {"RequestId": "hidden"},
            }

        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            self.heads.append(kwargs)
            return {
                "VersionId": "ACTUAL-UPLOAD-VERSION",
                "ContentLength": 0 if failure == "head" else item.review.artifact_bytes,
                "ChecksumSHA256": base64.b64encode(
                    bytes.fromhex(item.review.artifact_sha256)
                ).decode(),
                "LastModified": STAMP,
            }

    s3 = S3()

    class Session:
        def client(self, name: str, **kwargs: Any) -> S3:
            assert name == "s3"
            if "config" in kwargs:
                assert kwargs["config"].retries == {"total_max_attempts": 1}
            return s3

    live = module.LiveBoundaries(item, tmp_path / "upload", None)
    live.session = Session()
    monkeypatch.setattr(live, "reads", lambda *args: Session())
    if failure:
        with pytest.raises(ClientError if failure == "upload" else ValueError):
            live.upload()
        assert len(s3.puts) == 1 and len(s3.heads) == (0 if failure == "upload" else 2)
        assert (live.output / "upload-intent.json").exists()
        return
    assert live.upload() == "ACTUAL-UPLOAD-VERSION"
    assert len(s3.puts) == 1 and len(s3.heads) == 2
    assert s3.puts[0]["IfNoneMatch"] == "*"
    assert (
        s3.puts[0]["ChecksumSHA256"]
        == base64.b64encode(bytes.fromhex(item.review.artifact_sha256)).decode()
    )
    assert "VersionId" in s3.heads[0] and "VersionId" not in s3.heads[1]
    assert (
        json.loads((live.output / "upload-response.json").read_bytes())["ResponseMetadata"]
        == "[redacted]"
    )


def test_mutation_retry_environment_is_enforced_and_restored_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "9")
    with pytest.raises(RuntimeError), module.one_sdk_attempt():
        assert os.environ["AWS_MAX_ATTEMPTS"] == "1"
        raise RuntimeError("authored CDK failure")
    assert os.environ["AWS_MAX_ATTEMPTS"] == "9"


def test_evidence_serialization_failure_leaves_no_empty_file(tmp_path: Path) -> None:
    destination = tmp_path / "context.json"
    with pytest.raises(TypeError):
        module.write_new(destination, {"unsupported": object()})
    assert not destination.exists()


def test_edited_assembly_is_rejected_before_controller_or_sdk_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = prepared(tmp_path)
    live = module.LiveBoundaries(item, tmp_path / "execution", None)
    live.pool = ReadPool(None)
    target = item.review.targets[0]
    path = tmp_path / "candidate" / f"enterprise-analytics-stream-{target.model_key}.template.json"
    path.write_text(path.read_text() + "\n")

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("Edited metadata must not construct a deployment controller")

    monkeypatch.setattr(module, "DeploymentController", forbidden)
    with pytest.raises(ValueError, match="assembly file changed"):
        live.update(target, "ACTUAL-NEW-S3-VERSION", restoring=False)


def test_pre_mutation_full_proof_and_retry_environment_reach_owned_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = prepared(tmp_path)
    target = item.review.targets[0]
    live = module.LiveBoundaries(item, tmp_path / "execution", None)
    live.pool = ReadPool(None)
    live.uploaded_version = "ACTUAL-NEW-S3-VERSION"
    observed = []
    stack = {
        "StackId": item.plan.baseline_stack_ids[target.model_key],
        "Parameters": [{"ParameterKey": "ArtifactVersionId", "ParameterValue": module.OLD_VERSION}],
        "LastUpdatedTime": STAMP,
    }

    def proof(
        selected: StreamTarget, version: str, restoring: bool, deadline: float
    ) -> dict[str, Any]:
        observed.append((version, restoring))
        chosen = next(
            t
            for t in (item.baseline_review.targets if restoring else item.review.targets)
            if t.model_key == selected.model_key
        )
        return {
            "release": release(chosen, "1" if restoring else "2").model_dump(mode="json"),
            "stack": stack,
        }

    monkeypatch.setattr(live, "_proof", proof)

    class Controller:
        def __init__(self, *args: object, **kwargs: Any) -> None:
            self.validate = kwargs["baseline_validator"]

        def deploy(
            self, assembly: str, version: str, name: str, verify: Any, **kwargs: Any
        ) -> dict[str, Any]:
            assert os.environ["AWS_MAX_ATTEMPTS"] == "1"
            path = (
                tmp_path
                / "baseline"
                / f"enterprise-analytics-stream-{target.model_key}.template.json"
            )
            self.validate(stack, json.loads(path.read_bytes()))
            assert observed == [(module.OLD_VERSION, True)]
            assert kwargs["template_sha256"] == item.plan.pinned_files[f"candidate/{path.name}"]
            return dict(verify(1000000))

    monkeypatch.setattr(module, "DeploymentController", Controller)
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "9")
    assert live.update(target, "ACTUAL-NEW-S3-VERSION", restoring=False).runtime_version == "2"
    assert observed == [(module.OLD_VERSION, True), ("ACTUAL-NEW-S3-VERSION", False)]
    assert os.environ["AWS_MAX_ATTEMPTS"] == "9"


def test_exact_original_rollback_complete_does_not_launch_noop_cdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = prepared(tmp_path)
    target = item.review.targets[0]
    live = module.LiveBoundaries(item, tmp_path / "execution", None)
    live.pool = ReadPool(None)
    stack = {
        "StackId": item.plan.baseline_stack_ids[target.model_key],
        "StackStatus": "UPDATE_ROLLBACK_COMPLETE",
        "LastUpdatedTime": STAMP,
        "Parameters": [{"ParameterKey": "ArtifactVersionId", "ParameterValue": module.OLD_VERSION}],
    }
    body = json.loads(
        (
            tmp_path / "baseline" / f"enterprise-analytics-stream-{target.model_key}.template.json"
        ).read_bytes()
    )

    class Cfn:
        def client(self, *args: object) -> "Cfn":
            return self

        def describe_stacks(self, **kwargs: Any) -> dict[str, Any]:
            return {"Stacks": [stack]}

        def get_template(self, **kwargs: Any) -> dict[str, Any]:
            return {"TemplateBody": body}

    monkeypatch.setattr(live, "reads", lambda *args: Cfn())
    monkeypatch.setattr(live, "original_code", lambda: {"verified_original": True})
    chosen = next(t for t in item.baseline_review.targets if t.model_key == target.model_key)
    monkeypatch.setattr(
        live,
        "_proof",
        lambda *args: {"release": release(chosen, "7").model_dump(mode="json"), "stack": stack},
    )

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("An exactly verified original rollback must not launch CDK")

    monkeypatch.setattr(module, "DeploymentController", forbidden)
    assert live.update(target, module.OLD_VERSION, restoring=True).runtime_version == "7"
    evidence = json.loads((live.output / f"restore-{target.model_key}.verified.json").read_bytes())
    assert evidence["already_original_no_mutation"] is True


def test_restore_metadata_survives_missing_candidate_source_and_canonical_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = prepared(tmp_path)
    files = {
        "review.json": item.review.model_dump_json(),
        "baseline-review.json": item.baseline_review.model_dump_json(),
        "baseline-releases.json": item.baseline_releases.model_dump_json(),
        "infrastructure/agentcore/streaming_completion.py": "# authored pinned operator\n",
        "src/enterprise_analytics_agent/adapters/deployment_controller.py": (
            "# authored pinned controller\n"
        ),
        "old-guard.json": json.dumps(
            {
                "active": False,
                "requires_inspection": False,
                "process_reaped": True,
                "strict_checkpoint_verified": True,
            }
        ),
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    pins = {
        **item.plan.pinned_files,
        **{name: module.digest(tmp_path / name) for name in files},
        "candidate.zip": "f" * 64,
    }
    plan = item.plan.model_copy(
        update={
            "baseline_releases_sha256": module.digest(tmp_path / "baseline-releases.json"),
            "process_guard_sha256": module.digest(tmp_path / "old-guard.json"),
            "pinned_files": pins,
        }
    )
    (tmp_path / "plan.json").write_text(plan.model_dump_json())
    shutil.rmtree(tmp_path / "candidate")

    def forbidden(*args: object) -> NoReturn:
        pytest.fail("Restoration must not inspect current source/ZIP/canonical downloads")

    monkeypatch.setattr(module, "verify_local_inputs", forbidden)
    monkeypatch.setattr(module, "StreamingLedger", lambda *args: Ledger(claimed=True, used=1))
    restored = module.load_prepared(tmp_path, tmp_path / "plan.json", restoration=True)
    assert restored.review.sha256 == item.review.sha256
    assert not (tmp_path / "candidate.zip").exists() and not (tmp_path / "canonical").exists()


def test_failed_diagnostic_write_does_not_prevent_restoration_or_replace_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item, ledger = prepared(tmp_path), Ledger()
    edges = Edges(item, ledger, failure="evaluation")
    original = module.write_new

    def write(path: Path, value: object) -> None:
        if path.name in {"primary-error.json", "outcome.json"}:
            raise OSError("authored diagnostics I/O failure")
        original(path, value)

    monkeypatch.setattr(module, "write_new", write)
    with pytest.raises(ValueError, match="authored acceptance failure"):
        module.CompletionWorkflow(
            item, tmp_path / "execution", approval(item), edges, ledger=ledger
        ).run()
    assert len(edges.restorations) == 10 and edges.cleanup_calls == 1


def test_admission_reserves_ten_hours_for_deployment_and_failure_restoration(
    tmp_path: Path,
) -> None:
    item, ledger = prepared(tmp_path), Ledger()
    review = item.review.model_copy(update={"expires_at": datetime.now(UTC) + timedelta(hours=9)})
    item = module.Prepared(
        item.root, item.plan, item.plan_sha256, review, item.baseline_review, item.baseline_releases
    )
    edges = Edges(item, ledger)
    with pytest.raises(ValueError, match="Insufficient reviewed time"):
        module.CompletionWorkflow(
            item, tmp_path / "execution", approval(item), edges, ledger=ledger
        ).run()
    assert not edges.upload_calls and not ledger.claimed


def test_original_object_failure_stops_restoration_before_any_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = prepared(tmp_path)
    live = module.LiveBoundaries(item, tmp_path / "restoration", None)

    class S3:
        def client(self, service: str) -> "S3":
            assert service == "s3"
            return self

        def head_object(self, **kwargs: Any) -> NoReturn:
            assert kwargs["VersionId"] == module.OLD_VERSION
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")

    monkeypatch.setattr(live, "reads", lambda *args: S3())
    with pytest.raises(ClientError):
        live.safe_to_restore([item.review.targets[0]])
    assert not live.controller_lock.exists()


@pytest.mark.parametrize("restoration_only", [False, True], ids=("automatic", "resume"))
def test_restoration_candidate_proof_ignores_unavailable_candidate_object_but_keeps_original_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restoration_only: bool
) -> None:
    item = prepared(tmp_path)
    target = item.review.targets[0]
    arn = item.baseline_releases.models[0].runtime_arn
    runtime_id = arn.rsplit("/", 1)[1]
    policies = {
        arn: {"Version": "2012-10-17", "Statement": []},
        arn + "/runtime-endpoint/DEFAULT": {"Version": "2012-10-17", "Statement": []},
    }
    body: dict[str, Any] = {
        "Parameters": {"ArtifactVersionId": {"Type": "String"}},
        "Resources": {
            "Runtime": {
                "Type": "AWS::BedrockAgentCore::Runtime",
                "Properties": {
                    "RoleArn": "arn:aws:iam::453711491609:role/enterprise-analytics-stream-"
                    + target.model_key,
                    "PlatformVersion": "V1",
                    "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
                    "ProtocolConfiguration": "HTTP",
                    "LifecycleConfiguration": {
                        "IdleRuntimeSessionTimeout": 300,
                        "MaxLifetime": 900,
                    },
                },
            },
            "RuntimePolicy": {
                "Type": "AWS::BedrockAgentCore::ResourcePolicy",
                "Properties": {"ResourceArn": arn, "Policy": policies[arn]},
            },
            "EndpointPolicy": {
                "Type": "AWS::BedrockAgentCore::ResourcePolicy",
                "Properties": {
                    "ResourceArn": arn + "/runtime-endpoint/DEFAULT",
                    "Policy": policies[arn + "/runtime-endpoint/DEFAULT"],
                },
            },
        },
    }
    candidate_target = target.model_copy(update={"template_sha256": sha(body)})
    review = item.review.model_copy(
        update={
            "targets": (candidate_target, *item.review.targets[1:]),
            "artifact_key": "releases/" + "f" * 64 + "/agent.zip",
            "artifact_sha256": "f" * 64,
        }
    )
    item = module.Prepared(
        item.root, item.plan, item.plan_sha256, review, item.baseline_review, item.baseline_releases
    )
    live = module.LiveBoundaries(item, tmp_path / "restoration", None)
    live.restoration_only = restoration_only
    shutil.rmtree(tmp_path / "candidate")
    state = {
        "StackId": item.plan.baseline_stack_ids[target.model_key],
        "RoleARN": module.EXECUTION_ROLE,
        "StackStatus": "UPDATE_COMPLETE",
        "Parameters": [
            {"ParameterKey": "ArtifactVersionId", "ParameterValue": "ACTUAL-CANDIDATE-VERSION"}
        ],
    }
    heads = []

    class Services:
        def client(self, name: str, **kwargs: Any) -> "Services":
            return self

        def describe_stacks(self, **kwargs: Any) -> dict[str, Any]:
            return {"Stacks": [state]}

        def get_template(self, **kwargs: Any) -> dict[str, Any]:
            return {"TemplateBody": body}

        def get_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "agentRuntimeArn": arn,
                "agentRuntimeName": target.runtime_name,
                "agentRuntimeVersion": "2",
                "status": "READY",
                "agentRuntimeArtifact": {
                    "codeConfiguration": {
                        "runtime": "PYTHON_3_12",
                        "entryPoint": ["runtime_entry.py"],
                        "code": {
                            "s3": {
                                "bucket": (
                                    "enterprise-analytics-dev-453711491609-us-west-2-agent-code"
                                ),
                                "prefix": review.artifact_key,
                                "versionId": "ACTUAL-CANDIDATE-VERSION",
                            }
                        },
                    }
                },
                "environmentVariables": {
                    "ANALYTICS_RUNTIME_CONFIG": target.settings.model_dump_json()
                },
                "roleArn": body["Resources"]["Runtime"]["Properties"]["RoleArn"],
                "platformVersion": "V1",
                "networkConfiguration": {"networkMode": "PUBLIC"},
                "protocolConfiguration": {"serverProtocol": "HTTP"},
                "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 300, "maxLifetime": 900},
            }

        def get_agent_runtime_endpoint(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "READY",
                "liveVersion": "2",
                "agentRuntimeEndpointArn": arn + "/runtime-endpoint/DEFAULT",
            }

        def get_resource_policy(self, *, resourceArn: str) -> dict[str, Any]:
            return {"policy": policies[resourceArn]}

        def describe_log_groups(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "logGroups": [
                    {
                        "logGroupName": "/aws/bedrock-agentcore/runtimes/"
                        + runtime_id
                        + "-DEFAULT",
                        "retentionInDays": 7,
                    }
                ]
            }

        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            heads.append(kwargs)
            if kwargs["Key"] == review.artifact_key:
                raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")
            return {
                "VersionId": module.OLD_VERSION,
                "ContentLength": item.baseline_review.artifact_bytes,
                "ChecksumSHA256": base64.b64encode(
                    bytes.fromhex(item.baseline_review.artifact_sha256)
                ).decode(),
            }

    services = Services()
    live.pool = ReadPool(None)
    monkeypatch.setattr(live.pool, "view", lambda *args: services)
    proof = live._proof(
        candidate_target,
        "ACTUAL-CANDIDATE-VERSION",
        False,
        99999999,
        candidate_bytes_required=False,
    )
    assert proof["head"]["candidate_bytes_verified"] is False and not heads
    with pytest.raises(ClientError if restoration_only else ValueError):
        live._proof(candidate_target, "ACTUAL-CANDIDATE-VERSION", False, 99999999)
    monkeypatch.setattr(live, "reads", lambda *args: services)
    assert live.original_code()["VersionId"] == module.OLD_VERSION
    assert heads[-1]["Key"] == item.baseline_review.artifact_key
