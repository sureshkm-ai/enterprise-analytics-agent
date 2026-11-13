"""AWS-only accepted-runtime binding, using handwritten inputs and fake SDK boundaries."""

import hashlib
import io
import json
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.adapters import ui_accepted_runtime as adapter
from enterprise_analytics_agent.adapters.ui_release import (
    CANDIDATE_CONFIG_SHA256,
    ReleaseRecord,
)
from enterprise_analytics_agent.agent.contracts import AgentDiagnostics, AgentResponse
from enterprise_analytics_agent.ui import __main__ as cli
from enterprise_analytics_agent.ui.accepted_runtime import (
    SHARED_REVIEW_SHA256,
    AcceptedRuntimeApproval,
    AcceptedRuntimeReview,
)
from enterprise_analytics_agent.ui.models import AskRequest, UiError, UiResult
from enterprise_analytics_agent.ui.shared import (
    RUNTIME_ARN,
    SdkAttemptRecorder,
    SharedLedger,
    SharedReview,
)

NOW = datetime(2026, 11, 12, 23, 0, tzinfo=UTC)


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode()


def response(shared: SharedReview) -> AgentResponse:
    return AgentResponse(
        status="clarification",
        answer="Which supported period should I use?",
        dataset_version="retail-v1",
        diagnostics=AgentDiagnostics(
            model_id="us.amazon.nova-lite-v1:0",
            configuration=shared.agent_config.model_dump(mode="json"),
        ),
    )


def item(**changes: Any) -> AskRequest:
    return AskRequest.model_validate(
        {
            "mode": "live",
            "question": "Show net_revenue.",
            "request_id": str(uuid4()),
            **changes,
        }
    )


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fixed historic review/config, plus authored mocked archive-verification boundary."""
    shared = SharedReview.model_validate(
        {
            "campaign_id": "ui-shared-retail-v1-02",
            "expires_at": "2026-11-13T23:59:00Z",
            "source_sha256": "aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be",
            "target": {
                "runtime_arn": RUNTIME_ARN,
                "dataset_version": "retail-v1",
                "reference_date": "2025-04-01",
            },
        }
    )
    assert shared.sha256 == SHARED_REVIEW_SHA256
    shared_path = tmp_path / "evaluations/ui-shared/interactive-02.proposed.json"
    shared_path.parent.mkdir(parents=True)
    shared_bytes = encode(shared.model_dump(mode="json"))
    shared_path.write_bytes(shared_bytes)
    release = ReleaseRecord(
        kind="candidate",
        observed_at=datetime(2026, 11, 11, 21, 26, 3, tzinfo=UTC),
        runtime_arn=RUNTIME_ARN,
        runtime_version="15",
        review_sha256=shared.sha256,
        source_sha256=shared.source_sha256,
        archive_sha256=shared.archive_sha256,
        artifact_version_id=shared.artifact_version_id,
        configuration_sha256=CANDIDATE_CONFIG_SHA256,
        template_sha256=shared.runtime_template_sha256,
        dataset_version="retail-v1",
        canonical_manifest_sha256=shared.canonical_manifest_sha256,
    )
    release_path = tmp_path / "artifacts/ui-shared/interactive-02-preparation/release-record.json"
    release_path.parent.mkdir(parents=True)
    release_bytes = encode(release.model_dump(mode="json"))
    release_path.write_bytes(release_bytes)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/operator.py").write_text("# Authored operator source\n")
    guards = tmp_path / "artifacts/milestone-5"
    guards.mkdir(parents=True)
    (guards / "runtime-operator.lock").write_text("")
    (guards / "runtime-deployment.lock").write_text('{"active": false}\n')
    review = AcceptedRuntimeReview.model_validate(
        {
            "shared_review_path": shared_path.relative_to(tmp_path).as_posix(),
            "shared_review_file_sha256": sha(shared_bytes),
            "release_record_path": release_path.relative_to(tmp_path).as_posix(),
            "release_record_file_sha256": sha(release_bytes),
            "archive_path": "artifacts/milestone-5/q18-repair-v1/candidate/agent.zip",
            "archive_sha256": shared.archive_sha256,
            "archive_bytes": 100,
            "archive_source_sha256": shared.source_sha256,
            "archive_manifest_sha256": "f" * 64,
            "operator_source_sha256": adapter.operator_source_digest(tmp_path),
            "canonical_directory": "artifacts/milestone-5/canonical/retail-v1",
            "expires_at": shared.expires_at,
        }
    )
    approval = AcceptedRuntimeApproval(
        approved=True,
        scope="aws-only-existing-interactive02-questions",
        review_sha256=review.sha256,
        approved_at=NOW - timedelta(minutes=1),
        expires_at=review.expires_at,
    )
    ledger = SharedLedger(tmp_path, shared, now=lambda: NOW)
    for purpose in ("verification", "question"):

        def dispatch(recorder: SdkAttemptRecorder) -> UiResult:
            recorder.invoke_runtime(lambda: None)
            return UiResult(mode="live", response=response(shared))

        ledger.execute(item(), lambda: dispatch, purpose=purpose)
    archive_checks: list[str] = []

    def archive_proof(root: Path, review: AcceptedRuntimeReview) -> dict[str, object]:
        archive_checks.append(review.archive_sha256)
        return {"archive_source_sha256": shared.source_sha256, "archive_core_files": 25}

    monkeypatch.setattr(adapter, "verify_archive_inputs", archive_proof)
    monkeypatch.chdir(tmp_path)
    return {
        "root": tmp_path,
        "shared": shared,
        "release": release,
        "review": review,
        "approval": approval,
        "ledger": ledger,
        "archive_checks": archive_checks,
    }


def backend(prepared: dict[str, Any], **changes: Any) -> adapter.AcceptedRuntimeQuestions:
    return adapter.AcceptedRuntimeQuestions(
        prepared["root"],
        changes.get("review", prepared["review"]),
        changes.get("approval", prepared["approval"]),
        now=changes.get("now", lambda: NOW),
    )


def sdk_boundaries(
    monkeypatch: pytest.MonkeyPatch, prepared: dict[str, Any], *, fail: bool = False
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class Runtime:
        def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            events = [json.loads(line) for line in prepared["ledger"].path.read_text().splitlines()]
            assert sum(event["event"] == "reserved" for event in events) == 3
            if fail:
                raise RuntimeError("Authored one-shot SDK failure")
            return {
                "response": io.BytesIO(response(prepared["shared"]).model_dump_json().encode()),
                "statusCode": 200,
            }

    class Pool:
        def __init__(self, session: Any, path: Path) -> None:
            self.session = session

        def view(self, deadline: float, phase: str) -> "Pool":
            return self

        def record(self, record: object) -> None:
            pass

        def client(self, service: str, **kwargs: Any) -> "Pool":
            assert service == "sts"
            return self

        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": "453711491609"}

        def invocation_client(self, *, runtime_arn: str, config: Any) -> Runtime:
            assert runtime_arn == RUNTIME_ARN
            assert config.retries["total_max_attempts"] == 1
            return Runtime()

    def session(**kwargs: Any) -> object:
        assert kwargs == {"profile_name": "analytics-dev", "region_name": "us-west-2"}
        return object()

    monkeypatch.setattr(adapter, "ReadPool", Pool)
    monkeypatch.setattr(boto3, "Session", session)
    monkeypatch.setattr(adapter, "verify_release", lambda *args, **kwargs: {"observed_at": NOW})
    monkeypatch.setattr(
        adapter,
        "make_record",
        lambda *args, **kwargs: prepared["release"].model_copy(update={"observed_at": NOW}),
    )
    monkeypatch.setattr(adapter, "verify_publication", lambda *args, **kwargs: {"verified": True})
    return calls


def test_construction_status_are_offline_and_preserve_existing_two_of_twenty(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(boto3, "Session", lambda **kw: pytest.fail("No AWS in status"))
    paths = list(prepared["ledger"].directory.rglob("*"))
    before = {p: p.read_bytes() for p in paths if p.is_file()}
    current = backend(prepared)
    assert current.public_state("live")["enabled"] is True
    assert current.public_state("live")["word_streaming"] is False
    assert current.public_state("local_agent")["enabled"] is False
    assert current.ledger.summary()["used"] == 2
    assert current.ledger.summary()["regular_remaining"] == 17
    assert {p: p.read_bytes() for p in paths if p.is_file()} == before
    assert not list(prepared["root"].glob("artifacts/ui-demo/*"))


def test_one_question_only_runtime_payload_and_real_shared_receipts(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = sdk_boundaries(monkeypatch, prepared)
    current = backend(prepared)
    request = item()
    assert current.ask(request).mode == "live"
    assert len(calls) == 1
    assert json.loads(calls[0]["payload"]) == {"question": request.question}
    assert calls[0]["agentRuntimeArn"] == RUNTIME_ARN
    assert calls[0]["qualifier"] == "DEFAULT"
    assert calls[0]["runtimeSessionId"] != str(request.request_id)
    summary = current.ledger.summary()
    assert summary["used"] == 3 and summary["regular_remaining"] == 16
    sdk = summary["sdk_attempts"]
    assert isinstance(sdk, dict) and sdk["agentcore_invocations"] == 3
    assert summary["rollback_remaining"] == 1
    assert current.ask(request).mode == "live"
    assert len(calls) == 1
    restarted = backend(prepared)
    assert restarted.public_state("live")["enabled"] is True
    assert restarted.ledger.summary()["regular_remaining"] == 16


def test_sdk_failure_stays_spent_and_blocks_without_retry(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = sdk_boundaries(monkeypatch, prepared, fail=True)
    current = backend(prepared)
    with pytest.raises(RuntimeError, match="one-shot"):
        current.ask(item())
    assert len(calls) == 1
    assert current.ledger.summary()["used"] == 3
    assert current.public_state("live")["enabled"] is False
    with pytest.raises(UiError, match="allowance"):
        current.ask(item())
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["operator_source", "archive", "review", "release"])
def test_local_drift_disables_status_and_never_reaches_sdk(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    calls = sdk_boundaries(monkeypatch, prepared)
    current = backend(prepared)
    if kind == "operator_source":
        (prepared["root"] / "src/operator.py").write_text("# changed\n")
    elif kind == "archive":

        def changed(*args: Any, **kwargs: Any) -> Any:
            raise UiError("Accepted archive changed")

        monkeypatch.setattr(adapter, "verify_archive_inputs", changed)
    else:
        name = "shared_review_path" if kind == "review" else "release_record_path"
        path = prepared["root"] / getattr(prepared["review"], name)
        path.write_bytes(path.read_bytes() + b" ")
    assert current.public_state("live")["enabled"] is False
    with pytest.raises(UiError, match="preflight"):
        current.ask(item())
    assert calls == []
    assert current.ledger.summary()["used"] == 2


@pytest.mark.parametrize("kind", ["runtime_version", "configuration", "publication"])
def test_fresh_cloud_drift_fails_before_reservation(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    calls = sdk_boundaries(monkeypatch, prepared)
    current = backend(prepared)
    if kind == "publication":

        def fail(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("Authored publication drift")

        monkeypatch.setattr(adapter, "verify_publication", fail)
    else:
        changes = (
            {"runtime_version": "16"}
            if kind == "runtime_version"
            else {"configuration_sha256": "b" * 64}
        )
        monkeypatch.setattr(
            adapter, "make_record", lambda *a, **k: prepared["release"].model_copy(update=changes)
        )
    with pytest.raises(UiError, match="preflight"):
        current.ask(item())
    assert calls == [] and current.ledger.summary()["used"] == 2


def test_missing_or_wrong_approval_and_expiry_never_create_sdk(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(boto3, "Session", lambda **kw: pytest.fail("No SDK"))
    with pytest.raises(UiError, match="approval"):
        backend(prepared, approval=None)
    wrong = prepared["approval"].model_copy(update={"review_sha256": "0" * 64})
    with pytest.raises(UiError, match="approval"):
        backend(prepared, approval=wrong)
    with pytest.raises(UiError, match="expired"):
        backend(prepared, now=lambda: datetime(2026, 11, 14, tzinfo=UTC))
    assert prepared["ledger"].summary()["used"] == 2


@pytest.mark.parametrize("changes", [{"mode": "local_agent"}, {"model_key": "claude-sonnet-5-5"}])
def test_no_local_agent_or_browser_model_override(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch, changes: dict[str, object]
) -> None:
    monkeypatch.setattr(boto3, "Session", lambda **kw: pytest.fail("No SDK"))
    with pytest.raises(UiError, match="only routed AWS"):
        backend(prepared).ask(item(**changes))
    assert prepared["ledger"].summary()["used"] == 2


def test_browser_identity_and_configuration_fields_rejected() -> None:
    for name in ("tenant_id", "allowed_regions", "profile", "model_id", "runtime_arn", "history"):
        with pytest.raises(ValidationError):
            item(**{name: "untrusted"})


def test_review_cannot_change_existing_scope_or_grant_new_questions(
    prepared: dict[str, Any],
) -> None:
    for changes in (
        {"profile": "default"},
        {"runtime_version": "16"},
        {"maximum_calls": 20},
        {"evidence_mode": "skip-source-check"},
        {"shared_review_path": "other.json"},
    ):
        with pytest.raises(ValidationError):
            AcceptedRuntimeReview.model_validate({**prepared["review"].model_dump(), **changes})


def test_archive_core_inventory_is_derived_without_importing_any_code(tmp_path: Path) -> None:
    members = {
        "enterprise_analytics_agent/__init__.py": b"raise RuntimeError('never import')\n",
        "enterprise_analytics_agent/hosting/__init__.py": b"",
        "enterprise_analytics_agent/adapters/__init__.py": b"",
        "enterprise_analytics_agent/hosting/server.py": (
            b"import enterprise_analytics_agent.adapters.bedrock_agent\n"
        ),
        "enterprise_analytics_agent/adapters/bedrock_agent.py": b"import decimal\n",
        "enterprise_analytics_agent/adapters/duckdb.py": b"# independent authored fixture\n",
        "runtime_entry.py": b"# authored frozen entrypoint\n",
    }
    path = tmp_path / "authored.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    with zipfile.ZipFile(path) as archive:
        actual = adapter.archive_source_inventory(archive)
    assert actual == dict(sorted((name, sha(content)) for name, content in members.items()))


@pytest.mark.parametrize("kind", ["missing", "duplicate", "oversized"])
def test_archive_inventory_rejects_invalid_members(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        if kind == "duplicate":
            archive.writestr("same.py", "")
            with pytest.warns(UserWarning):
                archive.writestr("same.py", "")
        elif kind == "oversized":
            archive.writestr(
                "enterprise_analytics_agent/hosting/server.py", " " * (1024 * 1024 + 1)
            )
    with zipfile.ZipFile(path) as archive, pytest.raises(UiError):
        adapter.archive_source_inventory(archive)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--accepted-runtime-review", "review.json"],
        ["--accepted-runtime-review", "review.json", "--allow-live"],
        ["--accepted-runtime-approval", "approval.json", "--allow-live"],
        [
            "--accepted-runtime-review",
            "review.json",
            "--accepted-runtime-approval",
            "approval.json",
            "--allow-live",
            "--live-review",
            "legacy.json",
        ],
    ],
)
def test_cli_requires_explicit_separate_approval_and_exclusive_binding(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["analytics-ui", *arguments])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_offline_preparation_does_not_need_or_create_execution_approval(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(boto3, "Session", lambda **kw: pytest.fail("No SDK in offline preparation"))
    before = {p: p.read_bytes() for p in prepared["ledger"].directory.rglob("*") if p.is_file()}
    proof = adapter.verify_offline(prepared["root"], prepared["review"], now=lambda: NOW)
    assert proof["aws_calls"] == 0
    assert proof["budget"]["used"] == 2  # type: ignore[index]
    assert "separate approval required" in str(proof["execution_approval"])
    assert {p: p.read_bytes() for p in before} == before


def test_read_only_preflight_uses_exact_release_and_publication_without_reserving(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = sdk_boundaries(monkeypatch, prepared)
    output = prepared["root"] / "artifacts/accepted-runtime/new-preflight.json"
    proof = adapter.verify_read_only(
        prepared["root"], prepared["review"], output, read_only_aws=True
    )
    assert proof["runtime_invocations"] == 0
    assert calls == []
    assert prepared["ledger"].summary()["used"] == 2
    encoded = json.loads(output.read_bytes())
    assert encoded["checkpoint"]["observed_at"] == NOW.isoformat()
    assert encoded["publication"] == {"verified": True}
    with pytest.raises(UiError, match="new unaliased"):
        adapter.verify_read_only(prepared["root"], prepared["review"], output, read_only_aws=True)


def test_preflight_requires_explicit_read_only_gate_before_sdk(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(boto3, "Session", lambda **kw: pytest.fail("No SDK without read-only gate"))
    with pytest.raises(UiError, match="explicit read-only"):
        adapter.verify_read_only(
            prepared["root"],
            prepared["review"],
            prepared["root"] / "artifacts/not-created.json",
        )
    assert prepared["ledger"].summary()["used"] == 2


def test_cli_binds_only_aws_backend_and_startup_sends_no_question(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    review_path = prepared["root"] / "accepted-review.json"
    review_path.write_text(prepared["review"].model_dump_json())
    approval_path = prepared["root"] / "accepted-approval.json"
    approval_path.write_text(prepared["approval"].model_dump_json())
    configured: list[dict[str, Any]] = []

    class Backend:
        ledger = prepared["ledger"]

        def __init__(self, root: Path, review: object, approval: object) -> None:
            pass

    class Server:
        server_address = ("127.0.0.1", 8533)

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            pass

    def workbench(directory: Path, **kwargs: Any) -> object:
        configured.append(kwargs)
        return object()

    monkeypatch.setattr(adapter, "AcceptedRuntimeQuestions", Backend)
    monkeypatch.setattr(cli, "Workbench", workbench)
    monkeypatch.setattr(cli, "make_server", lambda *args: Server())
    monkeypatch.setattr(boto3, "Session", lambda **kw: pytest.fail("No SDK in UI launch"))
    monkeypatch.chdir(Path(cli.__file__).resolve().parents[3])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analytics-ui",
            "--allow-live",
            "--accepted-runtime-review",
            str(review_path),
            "--accepted-runtime-approval",
            str(approval_path),
            "--port",
            "8533",
        ],
    )
    assert cli.main() == 0
    assert len(configured) == 1
    assert isinstance(configured[0]["live"], Backend)
    assert configured[0]["local_agent"] is None
    assert configured[0]["model_backends"] == ()
    assert prepared["ledger"].summary()["used"] == 2


def short_binding(
    prepared: dict[str, Any],
) -> tuple[AcceptedRuntimeReview, AcceptedRuntimeApproval]:
    review = prepared["review"].model_copy(update={"expires_at": NOW + timedelta(seconds=1)})
    approval = prepared["approval"].model_copy(
        update={"review_sha256": review.sha256, "expires_at": review.expires_at}
    )
    return review, approval


def test_short_binding_expiring_during_preflight_sends_nothing_and_reserves_nothing(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = sdk_boundaries(monkeypatch, prepared)
    clock = [NOW]
    review, approval = short_binding(prepared)
    current = backend(prepared, review=review, approval=approval, now=lambda: clock[0])

    def publication(*args: Any, **kwargs: Any) -> dict[str, bool]:
        clock[0] = NOW + timedelta(seconds=2)
        return {"verified": True}

    monkeypatch.setattr(adapter, "verify_publication", publication)
    with pytest.raises(UiError, match="expired|approval|preflight") as failure:
        current.ask(item())
    assert failure.value.__cause__ is not None
    assert "expired" in str(failure.value.__cause__) or "approval" in str(failure.value.__cause__)
    assert calls == []
    assert current.ledger.summary()["used"] == 2
    assert current.ledger.summary()["sdk_attempts"] == prepared["ledger"].summary()["sdk_attempts"]


def test_short_binding_expiring_after_question_reservation_never_calls_runtime(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = sdk_boundaries(monkeypatch, prepared)
    clock = [NOW]
    review, approval = short_binding(prepared)
    current = backend(prepared, review=review, approval=approval, now=lambda: clock[0])
    append = current.ledger._append

    def expire_at_reservation(stream: Any, record: dict[str, object]) -> None:
        append(stream, record)
        if record.get("event") == "reserved":
            clock[0] = NOW + timedelta(seconds=2)

    monkeypatch.setattr(current.ledger, "_append", expire_at_reservation)
    with pytest.raises(UiError, match="expired|approval"):
        current.ask(item())
    assert calls == []
    summary = current.ledger.summary()
    assert summary["used"] == 3
    assert summary["failed"] is True
    assert summary["incomplete"] is False


def test_manual_preflight_respects_active_runtime_guard_before_sdk_creation(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        boto3, "Session", lambda **kw: pytest.fail("Guard must precede SDK creation")
    )
    guard = prepared["root"] / "artifacts/milestone-5/runtime-deployment.lock"
    guard.write_text('{"active": true}\n')
    output = prepared["root"] / "artifacts/accepted-runtime/guarded.json"
    with pytest.raises(UiError, match="unresolved|guard|active"):
        adapter.verify_read_only(prepared["root"], prepared["review"], output, read_only_aws=True)
    assert not output.exists()
    assert prepared["ledger"].summary()["used"] == 2


def test_manual_preflight_rechecks_source_after_network_reads_before_passed_output(
    prepared: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = sdk_boundaries(monkeypatch, prepared)
    output = prepared["root"] / "artifacts/accepted-runtime/source-drift.json"
    before = {p: p.read_bytes() for p in prepared["ledger"].directory.rglob("*") if p.is_file()}

    def release_read(*args: Any, **kwargs: Any) -> dict[str, datetime]:
        (prepared["root"] / "src/operator.py").write_text("# changed during preflight\n")
        return {"observed_at": NOW}

    monkeypatch.setattr(adapter, "verify_release", release_read)
    with pytest.raises(UiError, match="source changed"):
        adapter.verify_read_only(prepared["root"], prepared["review"], output, read_only_aws=True)
    assert calls == []
    assert not output.exists()
    assert {p: p.read_bytes() for p in before} == before
    assert prepared["ledger"].summary()["used"] == 2
