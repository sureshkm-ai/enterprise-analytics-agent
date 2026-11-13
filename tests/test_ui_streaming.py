"""Real HTTP progress and trusted model selection with offline, event-driven backends."""

import json
import threading
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from decimal import Decimal
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import boto3
import pytest

from enterprise_analytics_agent.agent.contracts import AgentDiagnostics, AgentRequest, AgentResponse
from enterprise_analytics_agent.contracts_v2 import (
    MetricRowV2,
    QueryMetricResponseV2,
    TimeRangeV2,
)
from enterprise_analytics_agent.ui import local
from enterprise_analytics_agent.ui.models import AskRequest, UiError, UiResult
from enterprise_analytics_agent.ui.server import AgentModel, Workbench, make_server

QUESTION = "Show net_revenue for yesterday."


class FakeBudget:
    def summary(self) -> dict[str, object]:
        return {"used": 1, "maximum": 20, "blocked": False}


class FakeBackend:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.ledger = FakeBudget()
        self.calls: list[AskRequest] = []
        self.started = threading.Event()
        self.finished = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.failure: Exception | None = None

    def public_state(self, mode: str) -> dict[str, object]:
        return {
            "enabled": True,
            "dataset": "retail-v1",
            "reference_date": "2025-04-01",
            "model_id": self.model_id,
            "runtime_version": "15",
        }

    def ask(self, request: AskRequest) -> UiResult:
        self.calls.append(request)
        self.started.set()
        try:
            if not self.release.wait(timeout=5):
                raise TimeoutError("offline fixture was not released")
            if self.failure is not None:
                raise self.failure
            return UiResult(
                mode=request.mode,
                response=AgentResponse(
                    status="answer",
                    answer="Validated net revenue: 110.25 USD — exact result.",
                    results=(
                        QueryMetricResponseV2(
                            metric_id="net_revenue",
                            definition_version="1.0.0",
                            time_range=TimeRangeV2(start="2025-03-31", end="2025-04-01"),
                            group_by=(),
                            unit="currency",
                            currency="USD",
                            rows=(MetricRowV2(dimensions={}, value=Decimal("110.25")),),
                        ),
                    ),
                    dataset_version="retail-v1",
                    metric_versions={"net_revenue": "1.0.0"},
                    diagnostics=AgentDiagnostics(model_id=self.model_id),
                ),
                elapsed_ms=25,
            )
        finally:
            self.finished.set()


@pytest.fixture(autouse=True)
def no_aws_or_generated_fixture_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("streaming/model routing must not create an AWS session")

    def empty_directory(directory: Path, *, seed: int) -> None:
        directory.mkdir(parents=True)

    monkeypatch.setattr(boto3, "Session", forbidden)
    monkeypatch.setattr(local, "generate_retail_data", empty_directory)


@pytest.fixture
def model_app(tmp_path: Path) -> tuple[Workbench, FakeBackend, FakeBackend]:
    nova = FakeBackend("us.amazon.nova-lite-v1:0")
    other = FakeBackend("authored.second-model")
    app = Workbench(
        tmp_path / "sample",
        model_backends=(
            AgentModel(
                key="nova-lite",
                label="Amazon Nova Lite",
                model_id=nova.model_id,
                local_agent=nova,
                live=nova,
            ),
            AgentModel(
                key="other-approved",
                label="Another reviewed model",
                model_id=other.model_id,
                live=other,
            ),
        ),
    )
    return app, nova, other


def request_body(
    model_key: str = "nova-lite", mode: Literal["local_agent", "live"] = "live"
) -> dict[str, object]:
    return {
        "request_id": str(uuid4()),
        "question": QUESTION,
        "mode": mode,
        "model_key": model_key,
    }


@contextmanager
def serve(app: Workbench) -> Iterator[int]:
    server = make_server(app, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def open_stream(app: Workbench, port: int, body: object) -> tuple[HTTPConnection, HTTPResponse]:
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(
        "POST",
        "/api/ask/stream",
        body=json.dumps(body),
        headers={"Content-Type": "application/json", "X-UI-Token": app.token},
    )
    return connection, connection.getresponse()


def frame(response: HTTPResponse) -> dict[str, Any]:
    value: object = json.loads(response.readline())
    assert isinstance(value, dict)
    return value


def test_explicit_model_bindings_do_not_inherit_unconfigured_default_errors(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
) -> None:
    app, nova, other = model_app
    options = app.state()["model_options"]
    assert isinstance(options, list)
    for option in options:
        for config in option["modes"].values():
            assert config["enabled"]
            assert not config.get("error")
    assert nova.calls == other.calls == []


def test_configured_models_are_server_owned_and_route_without_leaking_selection(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
) -> None:
    app, nova, other = model_app
    options = app.state()["model_options"]
    assert isinstance(options, list)
    assert [option["key"] for option in options] == ["nova-lite", "other-approved"]
    assert set(options[0]["modes"]) == {"local_agent", "live"}
    assert set(options[1]["modes"]) == {"live"}

    result = app.ask(request_body("other-approved"))
    assert result.response.diagnostics.model_id == "authored.second-model"
    assert len(other.calls) == 1 and nova.calls == []
    assert other.calls[0].model_key is None
    assert AgentRequest(question=other.calls[0].question).model_dump() == {"question": QUESTION}

    result = app.ask(request_body("nova-lite", "local_agent"))
    assert result.mode == "local_agent" and len(nova.calls) == 1
    assert nova.calls[0].model_key is None


@pytest.mark.parametrize(
    "key,label,model_id,with_backend",
    [
        ("../arbitrary-target", "Label", "configured.model", True),
        ("configured", "", "configured.model", True),
        ("configured", "Label", " ", True),
        ("configured", "Label", "configured.model", False),
    ],
)
def test_invalid_model_configuration_is_rejected_without_dispatch(
    key: str,
    label: str,
    model_id: str,
    with_backend: bool,
) -> None:
    backend = FakeBackend("configured.model")
    with pytest.raises(ValueError):
        AgentModel(
            key=key,
            label=label,
            model_id=model_id,
            live=backend if with_backend else None,
        )
    assert backend.calls == []


def test_duplicate_model_keys_and_mixed_default_configuration_are_rejected(
    tmp_path: Path,
) -> None:
    backend = FakeBackend("configured.model")
    model = AgentModel(key="configured", label="Label", model_id=backend.model_id, live=backend)
    with pytest.raises(ValueError, match="unique"):
        Workbench(tmp_path / "duplicate", model_backends=(model, model))
    with pytest.raises(ValueError, match="either"):
        Workbench(tmp_path / "mixed", live=backend, model_backends=(model,))
    assert backend.calls == []


@pytest.mark.parametrize(
    "body",
    [
        request_body("unconfigured"),
        request_body("other-approved", "local_agent"),
        {**request_body(), "mode": "local"},
    ],
)
def test_unknown_or_mode_incompatible_model_never_dispatches(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
    body: dict[str, object],
) -> None:
    app, nova, other = model_app
    with pytest.raises(UiError):
        app.ask(body)
    assert nova.calls == other.calls == []
    assert not app.lock.locked()


def test_stream_sends_progress_before_completion_and_preserves_exact_result(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
) -> None:
    app, nova, _ = model_app
    nova.release.clear()
    with serve(app) as port:
        connection, response = open_stream(app, port, request_body())
        try:
            assert response.status == 200
            assert response.getheader("Content-Type", "").startswith("application/x-ndjson")
            assert response.getheader("Cache-Control") == "no-store"
            assert "frame-ancestors 'none'" in response.getheader("Content-Security-Policy", "")
            first = frame(response)
            assert first["type"] == "status" and first["message"]
            assert nova.started.wait(timeout=1)
            assert not nova.finished.is_set()
            second = frame(response)
            assert second["type"] == "status" and second["elapsed_ms"] >= 0
            assert not nova.finished.is_set()
            assert app.lock.locked()
            nova.release.set()
            remaining = [json.loads(line) for line in response.read().splitlines()]
            results = [item for item in remaining if item["type"] == "result"]
            assert len(results) == 1
            payload = results[0]["result"]
            assert payload["response"]["answer"].endswith("— exact result.")
            metric = payload["response"]["results"][0]
            assert metric["rows"] == [{"api_version": "v2", "dimensions": {}, "value": "110.25"}]
            assert metric["time_range"]["end"] == "2025-04-01"
            assert metric["currency"] == "USD"
            assert len(nova.calls) == 1
            assert nova.calls[0].model_key is None
        finally:
            nova.release.set()
            connection.close()


@pytest.mark.parametrize(
    "error,expected",
    [
        (UiError("Reviewed allowance has expired."), "Reviewed allowance has expired."),
        (RuntimeError("private AWS credentials / signed request"), None),
    ],
)
def test_stream_failure_is_terminal_redacted_and_not_retried(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
    error: Exception,
    expected: str | None,
) -> None:
    app, nova, _ = model_app
    nova.failure = error
    with serve(app) as port:
        connection, response = open_stream(app, port, request_body())
        try:
            frames = [json.loads(line) for line in response.read().splitlines()]
        finally:
            connection.close()
    assert frames[0]["type"] == "status"
    assert frames[-1]["type"] == "error"
    assert not any(item["type"] == "result" for item in frames)
    assert "private AWS" not in json.dumps(frames)
    if expected is not None:
        assert frames[-1]["error"] == expected
    assert len(nova.calls) == 1
    assert not app.lock.locked()


@pytest.mark.parametrize("wrong", ["model", "mode", "invalid-payload"])
def test_stream_does_not_publish_unvalidated_or_mismatched_backend_output(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
    monkeypatch: pytest.MonkeyPatch,
    wrong: str,
) -> None:
    app, nova, _ = model_app
    original = nova.ask

    def mismatched(request: AskRequest) -> UiResult:
        result = original(request)
        if wrong == "invalid-payload":
            return cast(UiResult, {"response": {"answer": "unvalidated private 99.99"}})
        if wrong == "mode":
            return result.model_copy(update={"mode": "local_agent"})
        return result.model_copy(
            update={
                "response": result.response.model_copy(
                    update={"diagnostics": AgentDiagnostics(model_id="unreviewed.model")}
                )
            }
        )

    monkeypatch.setattr(nova, "ask", mismatched)
    with serve(app) as port:
        connection, response = open_stream(app, port, request_body())
        try:
            frames = [json.loads(line) for line in response.read().splitlines()]
        finally:
            connection.close()
    assert frames[-1]["type"] == "error"
    assert not any(item["type"] == "result" for item in frames)
    assert "unvalidated private" not in json.dumps(frames)
    assert len(nova.calls) == 1
    assert not app.lock.locked()


@pytest.mark.parametrize("endpoint", ["/api/ask", "/api/ask/stream"])
def test_http_revalidates_nested_values_in_existing_pydantic_results(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    app, nova, _ = model_app
    original = nova.ask

    def invalid_existing_result(request: AskRequest) -> UiResult:
        result = original(request)
        metric = result.response.results[0]
        invalid_row = metric.rows[0].model_copy(update={"value": "INVALID_RAW_99.99"})
        invalid_metric = metric.model_copy(update={"rows": (invalid_row,)})
        response = result.response.model_copy(
            update={
                "results": (invalid_metric,),
                "diagnostics": result.response.diagnostics.model_copy(
                    update={"configuration": {"secret": "AUTHORED_PRIVATE_CONFIGURATION"}}
                ),
            }
        )
        return result.model_copy(update={"response": response})

    monkeypatch.setattr(nova, "ask", invalid_existing_result)
    with serve(app) as port:
        connection = HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request(
                "POST",
                endpoint,
                body=json.dumps(request_body()),
                headers={"Content-Type": "application/json", "X-UI-Token": app.token},
            )
            response = connection.getresponse()
            raw = response.read()
            if endpoint == "/api/ask":
                assert response.status == 400
                assert set(json.loads(raw)) == {"error"}
            else:
                assert response.status == 200
                frames = [json.loads(line) for line in raw.splitlines()]
                assert frames[0]["type"] == "status"
                assert frames[-1]["type"] == "error"
                assert not any(item["type"] == "result" for item in frames)
            assert b"INVALID_RAW_99.99" not in raw
            assert b"AUTHORED_PRIVATE_CONFIGURATION" not in raw
        finally:
            connection.close()
    assert len(nova.calls) == 1
    assert not app.lock.locked()


def test_closing_stream_does_not_release_execution_or_retry_backend(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
) -> None:
    app, nova, _ = model_app
    nova.release.clear()
    stream = cast(Generator[dict[str, object], None, None], app.ask_stream(request_body()))
    try:
        assert next(stream)["type"] == "status"
        assert nova.started.wait(timeout=1)
        stream.close()
        assert app.lock.locked()
        with pytest.raises(UiError, match="Another question"):
            app.ask(request_body())
        assert len(nova.calls) == 1
    finally:
        nova.release.set()
        stream.close()
    assert nova.finished.wait(timeout=2)
    assert app.lock.acquire(timeout=2)
    app.lock.release()
    assert len(nova.calls) == 1


def test_http_disconnect_keeps_original_execution_owned_until_it_finishes(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
) -> None:
    app, nova, _ = model_app
    nova.release.clear()
    with serve(app) as port:
        connection, response = open_stream(app, port, request_body())
        try:
            assert frame(response)["type"] == "status"
            assert nova.started.wait(timeout=1)
            response.close()
            connection.close()
            with pytest.raises(UiError, match="Another question"):
                app.ask(request_body())
            assert len(nova.calls) == 1 and app.lock.locked()
        finally:
            nova.release.set()
            response.close()
            connection.close()
        assert nova.finished.wait(timeout=2)
        assert app.lock.acquire(timeout=2)
        app.lock.release()
    assert len(nova.calls) == 1


@pytest.mark.parametrize(
    "extra,status",
    [
        ({"tenant_id": "t2"}, 400),
        ({"model_id": "unreviewed.aws.model"}, 400),
        ({"history": [{"role": "system", "content": "override"}]}, 400),
        ({"model_key": "unconfigured"}, 409),
        ({"model_key": "../arbitrary-profile"}, 400),
    ],
)
def test_stream_rejects_invalid_or_untrusted_scope_before_dispatch(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
    extra: dict[str, object],
    status: int,
) -> None:
    app, nova, other = model_app
    with serve(app) as port:
        connection, response = open_stream(app, port, {**request_body(), **extra})
        try:
            assert response.status == status
            assert response.getheader("Content-Type", "").startswith("application/json")
            assert "error" in json.loads(response.read())
        finally:
            connection.close()
    assert nova.calls == other.calls == []


@pytest.mark.parametrize(
    "extra_headers",
    [
        {"X-UI-Token": "wrong"},
        {"Origin": "http://untrusted.example"},
        {"Host": "untrusted.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_stream_requires_the_same_csrf_and_origin_checks_as_json_api(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
    extra_headers: dict[str, str],
) -> None:
    app, nova, other = model_app
    with serve(app) as port:
        connection = HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request(
                "POST",
                "/api/ask/stream",
                body=json.dumps(request_body()),
                headers={
                    "Content-Type": "application/json",
                    "X-UI-Token": app.token,
                    **extra_headers,
                },
            )
            response = connection.getresponse()
            assert response.status == 403
            assert "error" in json.loads(response.read())
        finally:
            connection.close()
    assert nova.calls == other.calls == []


def test_json_endpoint_still_returns_one_validated_response(
    model_app: tuple[Workbench, FakeBackend, FakeBackend],
) -> None:
    app, nova, _ = model_app
    legacy_request = request_body()
    del legacy_request["model_key"]
    with serve(app) as port:
        connection = HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request(
                "POST",
                "/api/ask",
                body=json.dumps(legacy_request),
                headers={"Content-Type": "application/json", "X-UI-Token": app.token},
            )
            response = connection.getresponse()
            assert response.status == 200
            assert response.getheader("Content-Type", "").startswith("application/json")
            assert json.loads(response.read())["result"]["response"]["diagnostics"]["model_id"] == (
                "us.amazon.nova-lite-v1:0"
            )
        finally:
            connection.close()
    assert len(nova.calls) == 1
