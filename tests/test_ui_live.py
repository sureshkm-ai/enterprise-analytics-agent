"""Exercise the entire optional live boundary with fake AWS transports only."""

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from botocore.session import get_session
from botocore.validate import validate_parameters
from pydantic import ValidationError

from enterprise_analytics_agent.adapters import ui_live
from enterprise_analytics_agent.agent.contracts import AgentDiagnostics, AgentResponse
from enterprise_analytics_agent.retail_evaluation.client import RuntimeReply
from enterprise_analytics_agent.retail_evaluation.models import RetailTarget
from enterprise_analytics_agent.ui.live import LiveReview, UiLedger
from enterprise_analytics_agent.ui.models import AskRequest, UiError, UiResult

NOW = datetime(2026, 11, 10, tzinfo=UTC)
RUNTIME = (
    "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
    "enterprise_analytics_dev_agent-HlWywlG60h"
)


def endpoint_response(version: str = "12") -> dict[str, object]:
    """Validate the authored fixture against the installed SDK's real response shape."""
    value: dict[str, object] = {
        "agentRuntimeEndpointArn": RUNTIME + "/runtime-endpoint/DEFAULT",
        "agentRuntimeArn": RUNTIME,
        "status": "READY",
        "createdAt": NOW,
        "lastUpdatedAt": NOW,
        "name": "DEFAULT",
        "id": "DEFAULT",
        "liveVersion": version,
        "targetVersion": version,
    }
    shape = (
        get_session()
        .get_service_model("bedrock-agentcore-control")
        .operation_model("GetAgentRuntimeEndpoint")
        .output_shape
    )
    assert shape is not None
    validate_parameters(value, shape)
    return value


def review(maximum: int = 2) -> LiveReview:
    return LiveReview(
        campaign_id="ui-demo-test",
        maximum_calls=maximum,
        expires_at=NOW + timedelta(hours=1),
        target=RetailTarget(
            runtime_arn=RUNTIME, dataset_version="parity-v1", reference_date="2025-02-01"
        ),
    )


def request(question: str = "List metrics.") -> AskRequest:
    return AskRequest(mode="live", question=question, request_id=uuid4())


def result() -> UiResult:
    return UiResult(
        mode="live",
        response=AgentResponse(
            status="clarification",
            answer="Please specify a supported metric and period.",
            dataset_version="parity-v1",
            diagnostics=AgentDiagnostics(
                model_id="us.amazon.nova-lite-v1:0",
                configuration={"reference_date": "2025-02-01"},
            ),
        ),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"maximum_calls": 0},
        {"maximum_calls": 21},
        {"maximum_calls": True},
        {"campaign_id": "q18-recovery-v1"},
        {"campaign_id": "ui-demo-../other"},
        {"runtime_version": "11"},
        {"expires_at": "2026-11-11T00:00:00"},
    ],
)
def test_review_rejects_unbounded_or_historical_scope(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LiveReview.model_validate({**review().model_dump(mode="json"), **change})


@pytest.mark.parametrize(
    "key,value",
    [
        ("profile", "administrator"),
        ("account", "999999999999"),
        ("region", "us-east-1"),
        ("dataset_version", "retail-v1"),
        ("reference_date", "2025-04-01"),
        ("qualifier", "OTHER"),
        ("model_id", "other"),
    ],
)
def test_review_pins_existing_profile_and_original_target(key: str, value: str) -> None:
    data = review().model_dump(mode="json")
    data["target"][key] = value
    with pytest.raises(ValidationError):
        LiveReview.model_validate(data)


def test_ledger_reserves_once_before_dispatch_and_survives_restart(tmp_path: Path) -> None:
    ledger = UiLedger(tmp_path, review(), now=lambda: NOW)
    assert ledger.summary()["used"] == 0
    assert not ledger.path.exists()
    observed = []
    ask = request()

    def dispatch() -> UiResult:
        rows = [json.loads(line) for line in ledger.path.read_text().splitlines()]
        assert rows[-1]["event"] == "reserved"
        claim = ledger.claims / f"{rows[-1]['number']}.json"
        assert json.loads(claim.read_text()) == rows[-1]
        observed.append(1)
        return result()

    returned = ledger.execute(ask, lambda: dispatch)
    restarted = UiLedger(tmp_path, review(), now=lambda: NOW)
    assert restarted.summary()["used"] == 1
    assert restarted.execute(ask, lambda: pytest.fail("duplicate dispatch")) == returned
    assert observed == [1]
    with pytest.raises(UiError, match="different question"):
        restarted.execute(ask.model_copy(update={"question": "other"}), lambda: dispatch)
    restarted.execute(request(), lambda: dispatch)
    assert restarted.summary()["blocked"] is True
    with pytest.raises(UiError, match="exhausted"):
        restarted.execute(request(), lambda: dispatch)
    assert len(observed) == 2


def test_preflight_failure_does_not_spend_invocation_allowance(tmp_path: Path) -> None:
    ledger = UiLedger(tmp_path, review(), now=lambda: NOW)

    def prepare() -> Any:
        raise UiError("read failed")

    with pytest.raises(UiError, match="read failed"):
        ledger.execute(request(), prepare)
    assert ledger.summary()["used"] == 0
    assert not ledger.claims.exists()


def test_expiry_during_preflight_prevents_dispatch(tmp_path: Path) -> None:
    clock = [NOW]
    ledger = UiLedger(tmp_path, review(), now=lambda: clock[0])

    def prepare() -> Any:
        clock[0] += timedelta(hours=2)
        return lambda: pytest.fail("expired dispatch")

    with pytest.raises(UiError, match="expired during"):
        ledger.execute(request(), prepare)
    assert ledger.summary()["used"] == 0


@pytest.mark.parametrize("failure", ["exception", "error-response", "incomplete"])
def test_failed_or_uncertain_dispatch_blocks_further_calls(tmp_path: Path, failure: str) -> None:
    ledger = UiLedger(tmp_path, review(), now=lambda: NOW)

    def dispatch() -> UiResult:
        if failure == "exception":
            raise TimeoutError("private transport detail")
        if failure == "error-response":
            return result().model_copy(
                update={"response": result().response.model_copy(update={"status": "error"})}
            )
        raise KeyboardInterrupt()

    try:
        ledger.execute(request(), lambda: dispatch)
    except (TimeoutError, KeyboardInterrupt):
        pass
    if failure == "incomplete":
        # An outcome write may be lost after dispatch, but its reservation remains spent.
        ledger.path.write_text(ledger.path.read_text().splitlines(keepends=True)[0])
    assert ledger.summary()["used"] == 1
    assert ledger.summary()["blocked"] is True
    assert "private transport detail" not in ledger.path.read_text()
    with pytest.raises(UiError):
        ledger.execute(request(), lambda: pytest.fail("must not retry"))


@pytest.mark.parametrize("damage", ["delete", "truncate", "claim", "review", "partial-row"])
def test_damaged_ledger_cannot_reset_usage(tmp_path: Path, damage: str) -> None:
    ledger = UiLedger(tmp_path, review(), now=lambda: NOW)
    ledger.execute(request(), lambda: result)
    if damage == "delete":
        ledger.path.unlink()
    elif damage == "truncate":
        ledger.path.write_text("")
    elif damage == "claim":
        (ledger.claims / "1.json").write_text("{}")
    elif damage == "review":
        ledger = UiLedger(tmp_path, review(maximum=3), now=lambda: NOW)
    else:
        with ledger.path.open("a") as file:
            file.write('{"event":')
    with pytest.raises(UiError):
        ledger.summary()
    with pytest.raises(UiError):
        ledger.execute(request(), lambda: pytest.fail("invalid allowance"))


def test_failed_reservation_write_never_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = UiLedger(tmp_path, review(), now=lambda: NOW)

    def failure(fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("enterprise_analytics_agent.ui.live.os.fsync", failure)
    with pytest.raises(OSError):
        ledger.execute(request(), lambda: lambda: pytest.fail("not durably reserved"))
    with pytest.raises(UiError):
        ledger.summary()


def test_ledger_and_runtime_lease_refuse_overlap_and_aliases(tmp_path: Path) -> None:
    ledger = UiLedger(tmp_path, review(), now=lambda: NOW)
    with ledger._open(create=True), pytest.raises(UiError, match="Another request"):
        ledger.execute(request(), lambda: result)
    other = tmp_path / "other"
    other.mkdir()
    (tmp_path / "aliased").symlink_to(other, target_is_directory=True)
    alias_root = tmp_path / "alias-root"
    (alias_root / "artifacts").mkdir(parents=True)
    (alias_root / "artifacts/ui-demo").symlink_to(other, target_is_directory=True)
    with pytest.raises(UiError, match="aliased"):
        UiLedger(alias_root, review())
    with pytest.raises(UiError, match="missing"):
        with ui_live.runtime_lease(tmp_path):
            pytest.fail("missing guard")


def guards(root: Path) -> dict[Path, bytes]:
    directory = root / "artifacts/milestone-5"
    directory.mkdir(parents=True)
    operator = directory / "runtime-operator.lock"
    deployment = directory / "runtime-deployment.lock"
    operator.write_text("retained operator file")
    deployment.write_text('{"active": false}')
    return {path: path.read_bytes() for path in (operator, deployment)}


@pytest.mark.parametrize("active", ["true", "null", '"false"'])
def test_runtime_guard_requires_explicit_inactive_state(tmp_path: Path, active: str) -> None:
    guards(tmp_path)
    (tmp_path / "artifacts/milestone-5/runtime-deployment.lock").write_text(
        '{"active": ' + active + "}"
    )
    with pytest.raises(UiError, match="unresolved"):
        with ui_live.runtime_lease(tmp_path):
            pytest.fail("unresolved deployment")


def test_runtime_lease_does_not_modify_existing_evidence(tmp_path: Path) -> None:
    retained = guards(tmp_path)
    with ui_live.runtime_lease(tmp_path):
        with pytest.raises(UiError, match="active"):
            with ui_live.runtime_lease(tmp_path):
                pytest.fail("overlapping owner")
    assert {path: path.read_bytes() for path in retained} == retained


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "session",
        "checkpoint",
        "version",
        "setup",
        "invoke",
        "body",
        "malformed",
        "wrong-target",
    ],
)
def test_live_adapter_full_path_uses_only_question_and_counts_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    retained = guards(tmp_path)
    monkeypatch.chdir(tmp_path)
    backend = ui_live.LiveQuestions(tmp_path, review())
    backend.ledger.now = lambda: NOW
    observations: list[str] = []

    def session(**kwargs: Any) -> object:
        assert kwargs == {"profile_name": "analytics-dev", "region_name": "us-west-2"}
        observations.append("session")
        if failure == "session":
            raise RuntimeError("private session details")
        return object()

    def checkpoint(**kwargs: Any) -> dict[str, object]:
        assert kwargs["scope"] == "parity-v1"
        observations.append("checkpoint")
        if failure == "checkpoint":
            raise TimeoutError("private endpoint")
        return {
            "runtime": {"agentRuntimeArn": RUNTIME, "agentRuntimeVersion": "12"},
            "endpoint": endpoint_response("11" if failure == "version" else "12"),
        }

    class Body(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            if failure == "body":
                raise TimeoutError("private body detail")
            return super().read(size)

    response = result().response
    if failure == "wrong-target":
        response = response.model_copy(update={"dataset_version": "retail-v1"})
    body = Body(b"invalid" if failure == "malformed" else response.model_dump_json().encode())

    def factory(target: RetailTarget, **kwargs: Any) -> Any:
        observations.append("setup")
        assert target == review().target
        assert callable(kwargs["client_factory"])
        if failure == "setup":
            raise RuntimeError("private setup detail")

        def invoke(*, payload: bytes, session_id: str) -> RuntimeReply:
            observations.append("invoke")
            assert json.loads(payload) == {"question": "List metrics."}
            assert len(session_id) == 36
            assert (
                json.loads(backend.ledger.path.read_text().splitlines()[-1])["event"] == "reserved"
            )
            if failure == "invoke":
                raise TimeoutError("private invocation detail")
            return RuntimeReply(body)

        return invoke

    monkeypatch.setattr("enterprise_analytics_agent.adapters.ui_live.boto3.Session", session)
    monkeypatch.setattr(ui_live, "verify_checkpoint", checkpoint)
    monkeypatch.setattr(ui_live, "create_runtime_invoker", factory)
    assert observations == []
    if failure is None:
        assert backend.ask(request()).response == response
    else:
        with pytest.raises(UiError) as error:
            backend.ask(request())
        assert "private" not in str(error.value)
    dispatched = failure not in {"session", "checkpoint", "version", "setup"}
    assert observations.count("invoke") == int(dispatched)
    assert backend.ledger.summary()["used"] == int(dispatched)
    if dispatched and failure != "invoke":
        assert body.closed
    if failure:
        journal = (backend.ledger.directory / "operator-reads.jsonl").read_text()
        assert "ui-failed" in journal
        assert "private" not in journal
    assert {path: path.read_bytes() for path in retained} == retained
