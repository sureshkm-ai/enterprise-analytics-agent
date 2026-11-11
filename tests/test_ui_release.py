"""Shared release records and deployment recovery use independent fake AWS evidence."""

import base64
import hashlib
import json
import shutil
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import boto3
import pytest
from pydantic import ValidationError
from test_q18_artifacts import runtime_for, templates

from enterprise_analytics_agent.adapters import ui_release
from enterprise_analytics_agent.adapters.operator_reads import ReadPool, ReadSession
from enterprise_analytics_agent.retail_evaluation.campaign import CODE_SHA256, CODE_VERSION
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.ui.models import UiError
from enterprise_analytics_agent.ui.shared import (
    CANDIDATE_SHA256,
    CANDIDATE_TEMPLATE,
    CANDIDATE_VERSION,
    RUNTIME_ARN,
    SharedReview,
)
from infrastructure.agentcore import ui_workflow

NOW = datetime.now(UTC)
SOURCE_SHA256 = "aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be"
ORIGINAL_TEMPLATE = "dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb"
type Kind = Literal["candidate", "original"]


def review() -> SharedReview:
    return SharedReview(
        campaign_id="ui-shared-test",
        expires_at=NOW + timedelta(days=1),
        target=RetailTarget(
            runtime_arn=RUNTIME_ARN,
            dataset_version="retail-v1",
            reference_date="2025-04-01",
        ),
        source_sha256=SOURCE_SHA256,
    )


def template_for(kind: Kind) -> dict[str, Any]:
    """Author the reviewed settings; do not require ignored production artifacts in CI."""
    base, _ = templates()
    settings = {
        "account": "453711491609",
        "allowed_regions": ["North", "South"],
        "database": "enterprise_analytics_dev",
        "dataset_version": "retail-v1" if kind == "candidate" else "parity-v1",
        "max_iterations": 6,
        "max_output_tokens": 1024,
        "max_payload_bytes": 16384,
        "max_tool_calls": 16,
        "max_total_tokens": 12000,
        "model_id": "us.amazon.nova-lite-v1:0",
        "principal_id": "analytics-development-runtime",
        "query_role_arn": (
            "arn:aws:iam::453711491609:role/enterprise-analytics-dev-query-executor"
        ),
        "query_timeout_seconds": 60.0,
        "reference_date": "2025-04-01" if kind == "candidate" else "2025-02-01",
        "region": "us-west-2",
        "results_bucket": "enterprise-analytics-dev-453711491609-us-west-2-results",
        "source_bucket": "enterprise-analytics-dev-453711491609-us-west-2-data",
        "table_prefix": "ea",
        "tenant_id": "retail_demo" if kind == "candidate" else "t1",
        "timeout_seconds": 90.0,
        "workgroup": "enterprise-analytics-dev",
    }
    properties = base["Resources"]["AnalyticsRuntime"]["Properties"]
    properties["EnvironmentVariables"] = {
        "ANALYTICS_RUNTIME_CONFIG": json.dumps(settings, sort_keys=True, separators=(",", ":"))
    }
    properties["AgentRuntimeArtifact"]["CodeConfiguration"]["Code"]["S3"]["Prefix"] = (
        f"releases/{CANDIDATE_SHA256 if kind == 'candidate' else CODE_SHA256}/agent.zip"
    )
    base["Parameters"]["BootstrapVersion"] = {
        "Type": "AWS::SSM::Parameter::Value<String>",
        "Default": "/cdk-bootstrap/hnb659fds/version",
    }
    return base


def checkpoint(kind: Kind = "candidate", *, version: str | None = None) -> dict[str, Any]:
    template = template_for(kind)
    artifact_version = CANDIDATE_VERSION if kind == "candidate" else CODE_VERSION
    archive_sha = CANDIDATE_SHA256 if kind == "candidate" else CODE_SHA256
    runtime, endpoint = runtime_for(template, version=artifact_version)
    runtime["agentRuntimeVersion"] = version or ("13" if kind == "candidate" else "12")
    endpoint.update(
        liveVersion=runtime["agentRuntimeVersion"],
        targetVersion=runtime["agentRuntimeVersion"],
        agentRuntimeArn=RUNTIME_ARN,
        createdAt=NOW - timedelta(days=1),
        lastUpdatedAt=NOW,
    )
    runtime.update(createdAt=NOW - timedelta(days=1), lastUpdatedAt=NOW)
    return {
        "observed_at": NOW.isoformat(),
        "scope": "retail-v1" if kind == "candidate" else "parity-v1",
        "identity": {
            "Account": "453711491609",
            "Arn": "arn:aws:sts::453711491609:assumed-role/approved-developer/session",
        },
        "runtime": runtime,
        "endpoint": endpoint,
        "policies": {
            name: json.loads(resource["Properties"]["Policy"])
            for name, resource in template["Resources"].items()
            if resource["Type"] == "AWS::BedrockAgentCore::ResourcePolicy"
        },
        "stacks": {
            "enterprise-analytics-dev-agent-runtime": "UPDATE_COMPLETE",
            "enterprise-analytics-dev-agent-foundation": "CREATE_COMPLETE",
            "enterprise-analytics-dev-data-layer": "UPDATE_COMPLETE",
        },
        "artifact_head": {
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(archive_sha)).decode(),
            "VersionId": artifact_version,
            "ContentLength": 39171778 if kind == "candidate" else 39117152,
            "LastModified": NOW - timedelta(days=1),
        },
        "template_sha256": CANDIDATE_TEMPLATE if kind == "candidate" else ORIGINAL_TEMPLATE,
        "retention_days": 7,
        "artifact_sha256": archive_sha,
        "artifact_version_id": artifact_version,
    }


@pytest.fixture(autouse=True)
def authored_template(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hash validation of the actual files is covered by offline preparation tests.
    # Record tests isolate strict validation of full read-only checkpoint responses.
    monkeypatch.setattr(ui_release, "_template", lambda kind, **kwargs: template_for(kind))


def test_candidate_record_pins_observed_version_and_preserves_sdk_timestamps() -> None:
    proof = checkpoint(version="17")
    before = deepcopy(proof)
    record = ui_release.make_record(review(), proof, now=NOW)
    assert record.runtime_version == "17"
    assert record.kind == "candidate"
    assert record.archive_sha256 == CANDIDATE_SHA256
    assert record.artifact_version_id == CANDIDATE_VERSION
    assert record.source_sha256 == SOURCE_SHA256
    assert record.review_sha256 == review().sha256
    assert record.observed_at == NOW
    assert proof == before
    round_trip = ui_release.ReleaseRecord.model_validate_json(record.model_dump_json())
    assert round_trip == record
    ui_release.validate_record(review(), round_trip)


def test_original_record_does_not_relabel_original_source_as_shared_candidate() -> None:
    record = ui_release.make_record(
        review(), checkpoint("original", version="14"), kind="original", now=NOW
    )
    assert record.runtime_version == "14"
    assert record.archive_sha256 == CODE_SHA256
    assert record.artifact_version_id == CODE_VERSION
    assert record.source_sha256 != SOURCE_SHA256
    ui_release.validate_record(review(), record, kind="original")
    with pytest.raises(ValueError):
        ui_release.validate_record(review(), record, kind="candidate")


@pytest.mark.parametrize("version", ["0", "11", "12", "13.0", "v13", "latest"])
def test_candidate_requires_actual_numeric_post_v12_runtime_version(version: str) -> None:
    with pytest.raises(ValueError):
        ui_release.make_record(review(), checkpoint(version=version), now=NOW)


@pytest.mark.parametrize(
    "field,value", [("liveVersion", "12"), ("targetVersion", "14"), ("status", "UPDATING")]
)
def test_endpoint_ready_alone_does_not_prove_the_candidate(field: str, value: str) -> None:
    proof = checkpoint()
    proof["endpoint"][field] = value
    with pytest.raises(ValueError):
        ui_release.make_record(review(), proof, now=NOW)


def test_candidate_environment_must_match_every_reviewed_setting() -> None:
    proof = checkpoint()
    settings = json.loads(proof["runtime"]["environmentVariables"]["ANALYTICS_RUNTIME_CONFIG"])
    settings["tenant_id"] = "another-tenant"
    proof["runtime"]["environmentVariables"]["ANALYTICS_RUNTIME_CONFIG"] = json.dumps(settings)
    with pytest.raises(ValueError):
        ui_release.make_record(review(), proof, now=NOW)


@pytest.mark.parametrize(
    "field",
    [
        "review_sha256",
        "source_sha256",
        "archive_sha256",
        "configuration_sha256",
        "template_sha256",
        "canonical_manifest_sha256",
    ],
)
def test_saved_record_cannot_bind_a_different_release_or_review(field: str) -> None:
    record = ui_release.make_record(review(), checkpoint(), now=NOW)
    with pytest.raises(ValueError):
        altered = ui_release.ReleaseRecord.model_validate({**record.model_dump(), field: "0" * 64})
        ui_release.validate_record(review(), altered)


@pytest.mark.parametrize(
    "when", [NOW.replace(tzinfo=None), NOW - timedelta(seconds=301), NOW + timedelta(seconds=1)]
)
def test_in_memory_checkpoint_requires_fresh_aware_nonfuture_observation(when: datetime) -> None:
    proof = checkpoint()
    proof["observed_at"] = when.isoformat()
    with pytest.raises(ValueError):
        ui_release.make_record(review(), proof, now=NOW)


def test_saved_record_is_a_pin_and_not_a_cached_live_proof() -> None:
    record = ui_release.make_record(review(), checkpoint(), now=NOW)
    # A saved record can be retained as expected pins; verify_release must obtain
    # new observations before any execution. Do not silently invent a new date.
    ui_release.validate_record(review(), record)
    assert record.observed_at == NOW


def test_naive_timestamp_or_unrecognized_record_fields_are_rejected() -> None:
    record = ui_release.make_record(review(), checkpoint(), now=NOW)
    with pytest.raises(ValidationError):
        ui_release.ReleaseRecord.model_validate(
            {**record.model_dump(), "observed_at": NOW.replace(tzinfo=None)}
        )
    with pytest.raises(ValidationError):
        ui_release.ReleaseRecord.model_validate(
            {**record.model_dump(), "authorization": "another-tenant"}
        )


@pytest.mark.parametrize(
    "damage", ["checksum", "version", "size", "policy", "account", "stack", "retention", "template"]
)
def test_full_proof_cannot_be_reduced_to_runtime_ready(damage: str) -> None:
    proof = checkpoint()
    if damage == "checksum":
        proof["artifact_head"]["ChecksumSHA256"] = base64.b64encode(b"x" * 32).decode()
    elif damage == "version":
        proof["artifact_head"]["VersionId"] = "a-different-upload"
    elif damage == "size":
        proof["artifact_head"]["ContentLength"] = 42
    elif damage == "policy":
        proof["policies"]["DefaultEndpointInboundPolicy"]["Statement"][0]["Principal"] = "*"
    elif damage == "account":
        proof["identity"]["Account"] = "000000000000"
    elif damage == "stack":
        proof["stacks"]["enterprise-analytics-dev-agent-runtime"] = "UPDATE_ROLLBACK_COMPLETE"
    elif damage == "retention":
        proof["retention_days"] = 0
    else:
        proof["template_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        ui_release.make_record(review(), proof, now=NOW)


def fresh_checkpoint(kind: Kind, version: str) -> dict[str, Any]:
    proof = checkpoint(kind, version=version)
    proof["observed_at"] = datetime.now(UTC).isoformat()
    return proof


def test_deployment_flow_verifies_original_then_leaves_reviewed_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui_workflow, "_operator_lease", lambda root: nullcontext())
    calls: list[str] = []

    def original() -> dict[str, Any]:
        calls.append("verify original")
        return fresh_checkpoint("original", "12")

    def candidate() -> dict[str, Any]:
        calls.append("deploy and fully verify candidate")
        return fresh_checkpoint("candidate", "13")

    def restore() -> dict[str, Any]:
        pytest.fail("A successful shared release must stay on the reviewed candidate")

    operations = ui_workflow.WorkflowOperations(original, candidate, restore)
    result = ui_workflow.execute_workflow(
        tmp_path, review(), tmp_path / "operation", operations=operations
    )
    assert calls == ["verify original", "deploy and fully verify candidate"]
    assert result["succeeded"] is True
    assert result["candidate_deployed"] is True
    assert result["restored"] is False


@pytest.mark.parametrize("interruption", [False, True])
def test_candidate_failure_or_interrupt_restores_original_without_overlapping_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: bool
) -> None:
    calls: list[str] = []
    active = [False]

    @contextmanager
    def lease(root: Path) -> Any:
        assert root == tmp_path
        assert not active[0]
        active[0] = True
        try:
            yield
        finally:
            active[0] = False

    monkeypatch.setattr(ui_workflow, "_operator_lease", lease)

    def original() -> dict[str, Any]:
        assert active[0]
        calls.append("verify original")
        return fresh_checkpoint("original", "12")

    def candidate() -> dict[str, Any]:
        assert active[0]
        calls.append("candidate failed and returned control")
        if interruption:
            raise KeyboardInterrupt("interrupted local process")
        raise RuntimeError("candidate reconciliation failed")

    def restore() -> dict[str, Any]:
        assert active[0]
        assert calls[-1] == "candidate failed and returned control"
        calls.append("restore and fully verify original")
        return fresh_checkpoint("original", "14")

    operations = ui_workflow.WorkflowOperations(original, candidate, restore)
    directory = tmp_path / "operation"
    if interruption:
        with pytest.raises(KeyboardInterrupt):
            ui_workflow.execute_workflow(tmp_path, review(), directory, operations=operations)
    else:
        outcome = ui_workflow.execute_workflow(tmp_path, review(), directory, operations=operations)
        assert outcome["succeeded"] is False
        assert outcome["error"]["causes"][0]["error_type"] == "RuntimeError"
    assert calls == [
        "verify original",
        "candidate failed and returned control",
        "restore and fully verify original",
    ]
    assert active == [False]
    evidence = json.loads((directory / "deployment-result.json").read_text())
    assert evidence["restored"] is True
    assert evidence["succeeded"] is False


def test_preflight_drift_stops_before_deployment_or_restoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui_workflow, "_operator_lease", lambda root: nullcontext())

    def original() -> dict[str, Any]:
        return fresh_checkpoint("original", "14")

    def forbidden() -> dict[str, Any]:
        pytest.fail("The explicitly reviewed v12 starting checkpoint has drifted")

    operations = ui_workflow.WorkflowOperations(original, forbidden, forbidden)
    outcome = ui_workflow.execute_workflow(
        tmp_path, review(), tmp_path / "operation", operations=operations
    )
    assert outcome["succeeded"] is False
    assert outcome["candidate_attempted"] is False
    assert outcome["restored"] is False
    assert outcome["error"]["causes"][0]["error_type"] == "UiError"


def test_unresolved_process_guard_blocks_both_deployment_and_restoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def refused(root: Path) -> Any:
        raise RuntimeError("unresolved owned deployment process")
        yield

    monkeypatch.setattr(ui_workflow, "_operator_lease", refused)

    def forbidden() -> dict[str, Any]:
        pytest.fail("The process guard must run before any AWS-facing operation")

    operations = ui_workflow.WorkflowOperations(forbidden, forbidden, forbidden)
    with pytest.raises(RuntimeError, match="unresolved"):
        ui_workflow.execute_workflow(
            tmp_path, review(), tmp_path / "operation", operations=operations
        )


def mock_release_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: Kind,
    parameters: list[dict[str, str]],
) -> tuple[Any, list[str]]:
    calls: list[str] = []
    binding = SimpleNamespace(version_id=CANDIDATE_VERSION, require_review=lambda reviewed: None)
    version_record = tmp_path / "artifacts/milestone-5/q18-repair-v1/candidate-version.json"
    version_record.parent.mkdir(parents=True)
    version_record.write_text("{}")
    monkeypatch.setattr(ui_release, "ROOT", tmp_path)
    monkeypatch.setattr(ui_release, "load_review", lambda: object())
    monkeypatch.setattr(
        ui_release,
        "CandidateVersionBinding",
        SimpleNamespace(model_validate_json=lambda content: binding),
    )

    def verified(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert isinstance(kwargs["session"], ReadSession)
        calls.append("strict checkpoint")
        return fresh_checkpoint(kind, "13" if kind == "candidate" else "12")

    monkeypatch.setattr(ui_release, "verify_candidate_checkpoint", verified)
    monkeypatch.setattr(ui_release, "verify_checkpoint", verified)

    class CloudFormation:
        def describe_stacks(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs == {"StackName": "enterprise-analytics-dev-agent-runtime"}
            calls.append("exact parameters")
            return {"Stacks": [{"Parameters": parameters}]}

    class Session:
        def client(self, service: str, **kwargs: Any) -> CloudFormation:
            assert service == "cloudformation"
            assert kwargs["config"].retries == {"total_max_attempts": 1}
            return CloudFormation()

    return Session(), calls


@pytest.mark.parametrize("kind", ["candidate", "original"])
def test_release_verification_obtains_new_strict_proof_through_bounded_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: Kind
) -> None:
    parameters = [
        {
            "ParameterKey": "ArtifactVersionId",
            "ParameterValue": CANDIDATE_VERSION if kind == "candidate" else CODE_VERSION,
        },
        {"ParameterKey": "BootstrapVersion", "ParameterValue": "/cdk-bootstrap/hnb659fds/version"},
    ]
    session, calls = mock_release_reads(tmp_path, monkeypatch, kind, parameters)
    first = ui_release.verify_release(review(), kind=kind, session=session)
    second = ui_release.verify_release(review(), kind=kind, session=session)
    assert first is not second
    assert calls == ["strict checkpoint", "exact parameters"] * 2
    assert first["stack_parameters"] == {
        "ArtifactVersionId": CANDIDATE_VERSION if kind == "candidate" else CODE_VERSION,
        "BootstrapVersion": "/cdk-bootstrap/hnb659fds/version",
    }


@pytest.mark.parametrize("damage", ["extra", "missing", "duplicate", "wrong-value"])
def test_exact_cloudformation_parameters_are_required_after_runtime_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    parameters = [
        {"ParameterKey": "ArtifactVersionId", "ParameterValue": CANDIDATE_VERSION},
        {"ParameterKey": "BootstrapVersion", "ParameterValue": "/cdk-bootstrap/hnb659fds/version"},
    ]
    if damage == "extra":
        parameters.append({"ParameterKey": "Unreviewed", "ParameterValue": "setting"})
    elif damage == "missing":
        parameters.pop()
    elif damage == "duplicate":
        parameters.append(dict(parameters[0]))
    else:
        parameters[1]["ParameterValue"] = "an-unreviewed-bootstrap"
    session, _ = mock_release_reads(tmp_path, monkeypatch, "candidate", parameters)
    with pytest.raises(ValueError, match="parameter"):
        ui_release.verify_release(review(), session=session)


@pytest.mark.parametrize("same_sources", [True, False])
def test_local_source_mismatch_fails_before_sdk_creation_or_canonical_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_sources: bool
) -> None:
    from infrastructure.agentcore import source_audit

    monkeypatch.setattr(
        source_audit,
        "compare_archive",
        lambda *args: {
            "same_runtime_sources": same_sources,
            "local_source_sha256": "0" * 64,
        },
    )
    monkeypatch.setattr(
        boto3,
        "Session",
        lambda **kwargs: pytest.fail("Local release verification must be entirely offline"),
    )
    with pytest.raises(ValueError, match="source"):
        ui_release.verify_local_release(tmp_path, review(), tmp_path / "canonical")


@pytest.mark.parametrize("action", ["deploy", "restore"])
def test_cli_mutation_requires_explicit_gate_before_loading_or_creating_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    monkeypatch.setattr(
        boto3,
        "Session",
        lambda **kwargs: pytest.fail("An ungated command must not create any AWS session"),
    )
    with pytest.raises(SystemExit) as caught:
        ui_workflow.main(
            [
                action,
                "--review",
                str(tmp_path / "not-loaded.json"),
                "--output",
                str(tmp_path / "not-created"),
            ]
        )
    assert caught.value.code == 2
    assert not (tmp_path / "not-created").exists()


def test_explicit_restoration_only_does_not_repeat_candidate_or_invoke_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui_workflow, "_operator_lease", lambda root: nullcontext())
    calls: list[str] = []

    def forbidden() -> dict[str, Any]:
        pytest.fail(
            "Restoration-only must not repeat candidate deployment or original-v12 preflight"
        )

    def restore() -> dict[str, Any]:
        calls.append("original fully restored")
        return fresh_checkpoint("original", "14")

    outcome = ui_workflow.execute_workflow(
        tmp_path,
        review(),
        tmp_path / "restore",
        restore_only=True,
        operations=ui_workflow.WorkflowOperations(forbidden, forbidden, restore),
    )
    assert calls == ["original fully restored"]
    assert outcome["succeeded"] is True
    assert outcome["restored"] is True
    assert outcome["shared_ui_disabled"] is True
    assert outcome["rollback_smoke_pending"] is True
    assert outcome["billable_invocations"] == 0
    assert outcome["runtime_version"] == "14"


def test_failed_restoration_retains_primary_and_restoration_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui_workflow, "_operator_lease", lambda root: nullcontext())

    def original() -> dict[str, Any]:
        return fresh_checkpoint("original", "12")

    def candidate() -> dict[str, Any]:
        raise RuntimeError("private primary transport detail")

    def restore() -> dict[str, Any]:
        raise TimeoutError("private restoration transport detail")

    directory = tmp_path / "operation"
    outcome = ui_workflow.execute_workflow(
        tmp_path,
        review(),
        directory,
        operations=ui_workflow.WorkflowOperations(original, candidate, restore),
    )
    assert outcome["succeeded"] is False
    assert outcome["restored"] is False
    assert outcome["error"]["causes"][0]["error_type"] == "RuntimeError"
    assert outcome["restoration_error"]["causes"][0]["error_type"] == "TimeoutError"
    evidence = (directory / "deployment-result.json").read_text()
    assert "private primary" not in evidence
    assert "private restoration" not in evidence


@pytest.mark.parametrize("restore_only", [True, False])
def test_expired_window_blocks_new_deployment_but_allows_original_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restore_only: bool
) -> None:
    monkeypatch.setattr(ui_workflow, "_operator_lease", lambda root: nullcontext())
    expired = review().model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    calls: list[str] = []

    def forbidden() -> dict[str, Any]:
        pytest.fail("Expiry cannot authorize a new candidate deployment")

    def restore() -> dict[str, Any]:
        calls.append("nonbillable original cleanup")
        return fresh_checkpoint("original", "14")

    operations = ui_workflow.WorkflowOperations(forbidden, forbidden, restore)
    if restore_only:
        outcome = ui_workflow.execute_workflow(
            tmp_path,
            expired,
            tmp_path / "restore",
            restore_only=True,
            operations=operations,
        )
        assert calls == ["nonbillable original cleanup"]
        assert outcome["restored"] is True
        assert outcome["billable_invocations"] == 0
    else:
        with pytest.raises(UiError, match="expired"):
            ui_workflow.execute_workflow(
                tmp_path, expired, tmp_path / "candidate", operations=operations
            )
        assert calls == []
        assert not (tmp_path / "candidate").exists()


def test_expiry_during_original_preflight_blocks_mutation_without_restoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = review()
    clock = [NOW]
    calls: list[str] = []
    monkeypatch.setattr(ui_workflow, "_operator_lease", lambda root: nullcontext())
    monkeypatch.setattr(ui_workflow, "datetime", SimpleNamespace(now=lambda timezone: clock[0]))

    def original() -> dict[str, Any]:
        calls.append("verify original")
        clock[0] = approved.expires_at
        return fresh_checkpoint("original", "12")

    def forbidden() -> dict[str, Any]:
        pytest.fail("Expiry during read-only preflight cannot authorize a deployment")

    directory = tmp_path / "operation"
    outcome = ui_workflow.execute_workflow(
        tmp_path,
        approved,
        directory,
        operations=ui_workflow.WorkflowOperations(original, forbidden, forbidden),
    )
    assert calls == ["verify original"]
    assert outcome["candidate_attempted"] is False
    assert outcome["succeeded"] is False
    assert outcome["restored"] is False
    assert outcome["error"]["causes"][0]["error_type"] == "UiError"
    assert (directory / "original-checkpoint.json").is_file()
    assert (directory / "deployment-result.json").is_file()
    assert not (directory / "release-record.json").exists()


def prepared_rollback_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    directory = tmp_path / "prepared"
    original = tmp_path / "frozen-original.template.json"
    original.write_text('{"reviewed":"original template bytes"}')
    rollback = directory / "rollback"
    rollback.mkdir(parents=True)
    (rollback / "enterprise-analytics-dev-agent-runtime.template.json").write_bytes(
        original.read_bytes()
    )
    (rollback / "manifest.json").write_text('{"reviewed":"original assembly manifest"}')
    candidate = directory / "candidate"
    candidate.mkdir()
    (candidate / "enterprise-analytics-dev-agent-runtime.template.json").write_text("candidate")
    files = {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }
    (directory / "assembly-review.json").write_text(
        json.dumps(
            {
                "review_sha256": review().sha256,
                "files": files,
                "candidate_artifact_version_id": CANDIDATE_VERSION,
                "original_artifact_version_id": CODE_VERSION,
            }
        )
    )
    monkeypatch.setattr(
        ui_workflow, "_paths", lambda kind, **kwargs: (tmp_path / "original.zip", original)
    )
    return directory, rollback


def test_original_rollback_can_use_its_pins_when_candidate_preparation_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, rollback = prepared_rollback_fixture(tmp_path, monkeypatch)
    shutil.rmtree(directory / "candidate")
    _, result = ui_workflow._prepared(tmp_path, review(), directory, restore_only=True)
    assert result == rollback


@pytest.mark.parametrize("damage", ["changed", "missing", "extra"])
def test_rollback_still_rejects_any_drift_in_original_assembly_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    directory, rollback = prepared_rollback_fixture(tmp_path, monkeypatch)
    if damage == "changed":
        (rollback / "manifest.json").write_text("unreviewed")
    elif damage == "missing":
        (rollback / "manifest.json").unlink()
    else:
        (rollback / "unreviewed.json").write_text("unreviewed")
    with pytest.raises(ValueError, match="inventory|bytes"):
        ui_workflow._prepared(tmp_path, review(), directory, restore_only=True)


def test_expiry_during_candidate_deployment_restores_original_before_release_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = review()
    clock = [NOW]
    calls: list[str] = []
    monkeypatch.setattr(ui_workflow, "_operator_lease", lambda root: nullcontext())
    monkeypatch.setattr(ui_workflow, "datetime", SimpleNamespace(now=lambda timezone: clock[0]))

    def original() -> dict[str, Any]:
        calls.append("verify original")
        return fresh_checkpoint("original", "12")

    def candidate() -> dict[str, Any]:
        calls.append("candidate completed after expiry")
        clock[0] = approved.expires_at + timedelta(seconds=1)
        return fresh_checkpoint("candidate", "13")

    def restore() -> dict[str, Any]:
        calls.append("restore original")
        return fresh_checkpoint("original", "14")

    directory = tmp_path / "operation"
    outcome = ui_workflow.execute_workflow(
        tmp_path,
        approved,
        directory,
        operations=ui_workflow.WorkflowOperations(original, candidate, restore),
    )
    assert calls == ["verify original", "candidate completed after expiry", "restore original"]
    assert outcome["candidate_attempted"] is True
    assert outcome["succeeded"] is False
    assert outcome["restored"] is True
    assert outcome["billable_invocations"] == 0
    assert not (directory / "release-record.json").exists()
    rollback = ui_release.ReleaseRecord.model_validate_json(
        (directory / "rollback-record.json").read_bytes()
    )
    assert rollback.kind == "original"
    assert rollback.runtime_version == "14"


def publication_reader(
    tmp_path: Path,
    *,
    damage: str | None = None,
) -> tuple[ReadSession, list[str]]:
    """Publish fake metadata from tracked evidence, never from ignored/cloud inputs."""
    fixtures = Path(__file__).resolve().parents[1] / "evaluations/retail-v1"
    directory = tmp_path / "evaluations/retail-v1"
    directory.mkdir(parents=True)
    for name in ("ready-manifest.json", "oracle-provenance.json"):
        (directory / name).write_bytes((fixtures / name).read_bytes())
    manifest = json.loads((directory / "ready-manifest.json").read_bytes())
    provenance = json.loads((directory / "oracle-provenance.json").read_bytes())
    objects = {
        item["key"]: item for item in [provenance["manifest"], *provenance["objects"].values()]
    }
    calls: list[str] = []

    class S3:
        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["Bucket"] == "enterprise-analytics-dev-453711491609-us-west-2-data"
            assert kwargs["ExpectedBucketOwner"] == "453711491609"
            assert "VersionId" not in kwargs, (
                "Only a latest-object read can prove unchanged publication"
            )
            expected = objects[kwargs["Key"]]
            calls.append("head")
            result = {
                "VersionId": expected["version_id"],
                "ContentLength": expected["size_bytes"],
                "ETag": expected["etag"],
                "LastModified": NOW,
            }
            if damage == "latest-version":
                result["VersionId"] = "a-new-unreviewed-object-version"
            elif damage == "head-size":
                result["ContentLength"] += 1
            elif damage == "head-etag":
                result["ETag"] = '"another-etag"'
            return result

        def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["Bucket"] == "enterprise-analytics-dev-453711491609-us-west-2-data"
            assert kwargs["ExpectedBucketOwner"] == "453711491609"
            assert kwargs["MaxKeys"] == 2
            table = kwargs["Prefix"].rstrip("/").rsplit("/", 1)[1]
            expected = provenance["objects"][table]
            assert kwargs["Prefix"] == expected["key"].rsplit("/", 1)[0] + "/"
            calls.append("list")
            item = {
                "Key": expected["key"],
                "Size": expected["size_bytes"],
                "ETag": expected["etag"],
            }
            if damage == "list-etag":
                item["ETag"] = '"another-etag"'
            contents = [item]
            if damage == "extra-object":
                contents.append({**item, "Key": kwargs["Prefix"] + "unreviewed.parquet"})
            return {"IsTruncated": damage == "truncated", "Contents": contents}

    class Glue:
        def get_table(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["CatalogId"] == "453711491609"
            assert kwargs["DatabaseName"] == "enterprise_analytics_dev"
            name = kwargs["Name"]
            prefix = "ea_c1afc276bd3a34a8_"
            assert name.startswith(prefix)
            table = name.removeprefix(prefix)
            table_manifest = manifest["tables"][table]
            calls.append("glue")
            sql_types = {"VARCHAR": "string", "INTEGER": "int", "BIGINT": "bigint", "DATE": "date"}
            descriptor: dict[str, Any] = {
                "Columns": [
                    {"Name": column["name"], "Type": sql_types[column["type"]]}
                    for column in table_manifest["columns"]
                ],
                "Location": "s3://enterprise-analytics-dev-453711491609-us-west-2-data/"
                + table_manifest["key"].rsplit("/", 1)[0]
                + "/",
                "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                "SerdeInfo": {
                    "SerializationLibrary": (
                        "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
                    )
                },
            }
            result: dict[str, Any] = {
                "Name": name,
                "TableType": "EXTERNAL_TABLE",
                "PartitionKeys": [],
                "StorageDescriptor": descriptor,
            }
            if damage == "column-name":
                descriptor["Columns"][0]["Name"] = "unreviewed_tenant"
            elif damage == "column-type":
                descriptor["Columns"][0]["Type"] = "int"
            elif damage == "location":
                descriptor["Location"] = "s3://another-bucket/mixed-snapshots/"
            elif damage == "partition":
                result["PartitionKeys"] = [{"Name": "tenant_id", "Type": "string"}]
            elif damage == "additional-locations":
                descriptor["AdditionalLocations"] = ["s3://another-bucket/mixed-snapshots/"]
            elif damage == "format":
                descriptor["InputFormat"] = "org.apache.hadoop.mapred.TextInputFormat"
            elif damage == "output-format":
                descriptor["OutputFormat"] = (
                    "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
                )
            elif damage == "serde":
                descriptor["SerdeInfo"]["SerializationLibrary"] = "another-serde"
            elif damage == "table-type":
                result["TableType"] = "VIRTUAL_VIEW"
            elif damage == "table-name":
                result["Name"] = "an_unreviewed_table"
            elif damage == "projection":
                result["Parameters"] = {"projection.enabled": "true"}
            elif damage == "location-template":
                result["Parameters"] = {
                    "storage.location.template": "s3://another/tenant=${tenant}/"
                }
            return {"Table": result}

    class Session:
        def client(self, name: str, **kwargs: Any) -> Any:
            assert kwargs["config"].retries == {"total_max_attempts": 1}
            if name == "s3":
                return S3()
            if name == "glue":
                return Glue()
            pytest.fail("Publication verification must not create query/model/runtime clients")

    reader = ReadPool(Session(), monotonic=lambda: 1.0).view(20, "publication test")
    return reader, calls


def test_publication_preflight_verifies_latest_objects_exclusive_locations_and_glue(
    tmp_path: Path,
) -> None:
    reader, calls = publication_reader(tmp_path)
    result = ui_release.verify_publication(review(), reader, root=tmp_path)
    assert result["canonical_manifest_sha256"] == review().canonical_manifest_sha256
    assert len(result["latest_heads"]) == 8
    assert len(result["source_prefixes"]) == len(result["glue_tables"]) == 7
    assert result["latest_heads"]["manifest"]["version_id"] == "cvCWKV3bv9Ub4iZOPSh79W4TnizV6FmJ"
    assert calls.count("head") == 8
    assert calls.count("list") == 7
    assert calls.count("glue") == 7
    assert len(calls) == 22


@pytest.mark.parametrize(
    "damage",
    [
        "latest-version",
        "head-size",
        "head-etag",
        "list-etag",
        "extra-object",
        "truncated",
        "column-name",
        "column-type",
        "location",
        "partition",
        "additional-locations",
        "format",
        "output-format",
        "serde",
        "table-type",
        "table-name",
        "projection",
        "location-template",
    ],
)
def test_publication_preflight_rejects_data_or_glue_drift_before_execution(
    tmp_path: Path, damage: str
) -> None:
    reader, _ = publication_reader(tmp_path, damage=damage)
    with pytest.raises(ValueError):
        ui_release.verify_publication(review(), reader, root=tmp_path)


@pytest.mark.parametrize("damage", ["latest-version", "extra-object", "column-name", "column-type"])
def test_operator_rejects_publication_drift_before_candidate_or_controller_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    reader, _ = publication_reader(tmp_path, damage=damage)
    calls: list[str] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ui_workflow, "verify_local_release", lambda *args: {})
    monkeypatch.setattr(
        ui_workflow,
        "_prepared",
        lambda *args, **kwargs: (tmp_path / "candidate", tmp_path / "rollback"),
    )

    class Sts:
        def get_caller_identity(self) -> dict[str, str]:
            calls.append("identity")
            return {"Account": "453711491609"}

    class Session:
        def client(self, name: str, **kwargs: Any) -> Sts:
            assert kwargs["config"].retries == {"total_max_attempts": 1}
            if name != "sts":
                pytest.fail("Drift must stop before candidate reads or controller AWS setup")
            return Sts()

    def selected_session(**kwargs: Any) -> Session:
        assert kwargs == {"profile_name": "analytics-dev", "region_name": "us-west-2"}
        return Session()

    def publication(approved: SharedReview, session: ReadSession, *, root: Path) -> dict[str, Any]:
        assert calls == ["identity"]
        calls.append("publication")
        return ui_release.verify_publication(approved, reader, root=root)

    monkeypatch.setattr(boto3, "Session", selected_session)
    monkeypatch.setattr(ui_workflow, "verify_publication", publication)
    monkeypatch.setattr(
        ui_workflow,
        "DeploymentController",
        lambda *args, **kwargs: pytest.fail(
            "Publication drift must precede controller construction"
        ),
    )
    monkeypatch.setattr(
        ui_workflow,
        "verify_uploaded_version",
        lambda *args, **kwargs: pytest.fail(
            "Publication drift must precede candidate verification"
        ),
    )
    with pytest.raises(ValueError):
        ui_workflow._operations(
            tmp_path,
            review(),
            tmp_path / "operation",
            tmp_path / "prepared",
            restore_only=False,
        )
    assert calls == ["identity", "publication"]
