"""Post-upload binding and campaign gates remain offline and refuse guessed versions."""

import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from enterprise_analytics_agent.adapters.repair_operations import verify_uploaded_version
from enterprise_analytics_agent.retail_evaluation.campaign import CODE_VERSION
from enterprise_analytics_agent.retail_evaluation.repair_cli import main
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    RepairReview,
    select_repair,
)


def review() -> RepairReview:
    return RepairReview(
        candidate_artifact_path="artifacts/milestone-5/q18-repair-v1/candidate/agent.zip",
        candidate_assembly_path="artifacts/milestone-5/q18-repair-v1/cdk.candidate.out",
        candidate_sha256="a" * 64,
        candidate_template_sha256="b" * 64,
        questions_sha256="c" * 64,
        expected_results_sha256="d" * 64,
        source_patch_sha256="e" * 64,
    )


def version(selected: RepairReview) -> CandidateVersionBinding:
    return CandidateVersionBinding(
        review_sha256=selected.review_sha256,
        candidate_sha256=selected.candidate_sha256,
        candidate_template_sha256=selected.candidate_template_sha256,
        bucket="enterprise-analytics-dev-453711491609-us-west-2-agent-code",
        key=f"releases/{selected.candidate_sha256}/agent.zip",
        version_id="mock-upload-version",
        checksum_sha256=selected.candidate_sha256,
        size_bytes=3,
        verified_at=datetime.now(UTC),
    )


def test_explicit_selection_needs_uploaded_version_before_any_sdk(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown"):
        select_repair("unreviewed-campaign", None, repository_root=tmp_path)
    with pytest.raises(ValueError, match="post-upload"):
        select_repair("q18-repair-v1", None, repository_root=tmp_path)
    selected = review()
    path = tmp_path / "evaluations/retail-v1/q18-repair-review.json"
    path.parent.mkdir(parents=True)
    path.write_text(selected.model_dump_json())
    uploaded = tmp_path / "uploaded.json"
    uploaded.write_text(version(selected).model_dump_json())
    actual, bound, ledger = select_repair("q18-repair-v1", uploaded, repository_root=tmp_path)
    assert actual == selected and bound.version_id == "mock-upload-version"
    assert ledger.review_sha256 == selected.review_sha256
    assert not (tmp_path / selected.ledger_path).exists()
    uploaded.write_text(
        version(selected).model_copy(update={"review_sha256": "f" * 64}).model_dump_json()
    )
    with pytest.raises(ValueError, match="reviewed campaign"):
        select_repair("q18-repair-v1", uploaded, repository_root=tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version_id", "pending"),
        ("version_id", "null"),
        ("checksum_sha256", "f" * 64),
        ("key", "releases/old/agent.zip"),
        ("size_bytes", True),
        ("verified_at", "2025-01-01T00:00:00"),
    ],
)
def test_version_binding_rejects_unpinned_fields(field: str, value: object) -> None:
    raw = version(review()).model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValueError):
        CandidateVersionBinding.model_validate(raw)


class UploadReads:
    def __init__(self, selected: RepairReview) -> None:
        self.selected = selected
        self.calls: list[dict[str, object]] = []
        self.head: dict[str, object] = {
            "VersionId": "actual-mock-upload",
            "ContentLength": 3,
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(selected.candidate_sha256)).decode(),
        }

    def client(self, name: str, **kwargs: Any) -> Any:
        assert name in {"sts", "s3"}
        return self

    def get_caller_identity(self) -> dict[str, str]:
        return {"Account": "453711491609"}

    def head_object(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.head


def test_bind_only_upload_returned_version_after_exact_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = review()
    monkeypatch.chdir(tmp_path)
    artifact = Path(selected.candidate_artifact_path)
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"zip")
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.repair_operations.review_candidate_assemblies",
        lambda reviewed: {},
    )
    session = UploadReads(selected)
    bound = verify_uploaded_version(selected, {"VersionId": "actual-mock-upload"}, session=session)
    bound.require_review(selected)
    assert bound.version_id == "actual-mock-upload" and bound.version_id != CODE_VERSION
    assert session.calls[0]["VersionId"] == bound.version_id
    assert session.calls[0]["ExpectedBucketOwner"] == "453711491609"
    assert session.calls[0]["Key"] == f"releases/{selected.candidate_sha256}/agent.zip"
    for field, bad in (("VersionId", "other"), ("ContentLength", 4), ("ChecksumSHA256", "bad")):
        old = session.head[field]
        session.head[field] = bad
        with pytest.raises(ValueError, match="differs"):
            verify_uploaded_version(selected, {"VersionId": "actual-mock-upload"}, session=session)
        session.head[field] = old


def test_cli_unknown_or_unversioned_execution_never_builds_aws_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> Any:
        pytest.fail("AWS session constructed before pinned campaign selection")

    monkeypatch.setattr("boto3.Session", forbidden)
    assert main(["--campaign", "unknown", "verify-offline"]) == 1
    # The parser rejects a missing post-upload record before importing operations_for.
    with pytest.raises(SystemExit):
        main(["--campaign", "q18-repair-v1", "run", "--invoke-live", "--report-dir", "unused"])


def test_edited_uploaded_version_fails_before_deployment_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from enterprise_analytics_agent.adapters.repair_operations import operations_for

    selected = review()
    monkeypatch.chdir(tmp_path)
    artifact = Path(selected.candidate_artifact_path)
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"zip")
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.repair_operations.review_candidate_assemblies",
        lambda reviewed: {},
    )
    session = UploadReads(selected)
    # The version record is structurally valid and binds the review, but this
    # service response identifies another immutable object version.
    monkeypatch.setattr("boto3.Session", lambda **kwargs: session)
    with pytest.raises(ValueError, match="differs"):
        operations_for(selected, version(selected), tmp_path / "reports")
    assert len(session.calls) == 1
    assert session.calls[0]["VersionId"] == "mock-upload-version"
    assert not (tmp_path / "reports").exists()


def test_restore_only_does_not_read_a_missing_candidate_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from enterprise_analytics_agent.adapters.repair_operations import operations_for

    selected = review()

    class OriginalOnly:
        def client(self, name: str, **kwargs: Any) -> Any:
            assert name in {"sts", "bedrock-agentcore-control", "cloudformation"}
            return self

        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": "453711491609"}

    monkeypatch.setattr("boto3.Session", lambda **kwargs: OriginalOnly())
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.repair_operations.review_assemblies", lambda: {}
    )
    # Neither new ZIP nor uploaded object is required to reconstruct original-only recovery.
    assert callable(
        operations_for(
            selected, version(selected), tmp_path / "logs", restore_only=True
        ).restore_original
    )
