"""Loopback-only browser application. All AWS work is behind an explicit POST."""

import json
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import ValidationError

from enterprise_analytics_agent.agent.contracts import AgentResponse
from enterprise_analytics_agent.catalog import METRICS
from enterprise_analytics_agent.retail_evaluation.reporting import EvaluationReport
from enterprise_analytics_agent.ui.local import (
    LOCAL_DATASET,
    REFERENCE_DATE,
    SAMPLES,
    LocalQuestions,
)
from enterprise_analytics_agent.ui.models import (
    AskRequest,
    UiError,
    UiResult,
    unreported_diagnostics,
)

MAX_BODY = 16 * 1024 * 1024


class _EventStream(Iterator[dict[str, object]]):
    def __init__(self, events: Iterator[dict[str, object]], closed: threading.Event) -> None:
        self.events, self.closed = events, closed

    def __iter__(self) -> "_EventStream":
        return self

    def __next__(self) -> dict[str, object]:
        return next(self.events)

    def close(self) -> None:
        # Also works before the generator's first next(), when its finally block
        # has not started. Never leave a producer blocked behind a dead browser.
        self.closed.set()
        close = getattr(self.events, "close", None)
        if callable(close):
            close()


class Budget(Protocol):
    def summary(self) -> dict[str, object]: ...


class LiveBackend(Protocol):
    @property
    def ledger(self) -> Budget: ...

    def ask(self, request: AskRequest) -> UiResult: ...


@dataclass(frozen=True)
class AgentModel:
    """Trusted application routing, never an arbitrary browser model/config override."""

    key: str
    label: str
    model_id: str
    local_agent: LiveBackend | None = None
    live: LiveBackend | None = None

    def __post_init__(self) -> None:
        # Reuse the same opaque-key constraint as browser selection.
        AskRequest(question="model configuration", request_id=UUID(int=0), model_key=self.key)
        if not self.label.strip() or not self.model_id.strip():
            raise ValueError("A configured model needs a label and model identifier.")
        if self.local_agent is None and self.live is None:
            raise ValueError("A configured model needs at least one approved backend.")


def _validated_result(value: object) -> UiResult:
    # Pydantic trusts existing instances by default, including nested values
    # introduced through model_copy/model_construct. Publish only a deep recheck.
    if isinstance(value, UiResult):
        value = value.model_dump(mode="python", warnings=False)
    return UiResult.model_validate(value)


def read_replay(value: object) -> dict[str, object]:
    """Validate saved responses as data; never execute instructions from a report."""
    if not isinstance(value, dict):
        raise UiError("Choose a saved AgentResponse or a suite report.json file.")
    if value.get("api_version") == "agent-v1":
        response = AgentResponse.model_validate(value)
        return {
            "label": "Saved response",
            "cases": [
                {
                    "case_id": "saved",
                    "question": "Saved answer",
                    "status": "saved",
                    "reasons": [],
                    "result": UiResult(
                        mode="replay",
                        response=response,
                        unreported_diagnostics=unreported_diagnostics(response),
                    ).model_dump(mode="json"),
                }
            ],
        }
    report = EvaluationReport.model_validate(value)
    if len(report.cases) > 200:
        raise UiError("A saved report can contain at most 200 cases.")
    return {
        "label": f"{report.run_id} · {report.created_at}",
        "original_mode": report.mode,
        "cases": [
            {
                "case_id": case.case_id,
                "question": case.question,
                "status": case.status,
                "reasons": list(case.reasons),
                "result": UiResult(
                    mode="replay",
                    response=case.response,
                    elapsed_ms=case.client_latency_ms,
                    unreported_diagnostics=unreported_diagnostics(case.response),
                ).model_dump(mode="json")
                if case.response is not None
                else None,
            }
            for case in report.cases
        ],
    }


class Workbench:
    def __init__(
        self,
        directory: Path,
        *,
        live: LiveBackend | None = None,
        local_agent: LiveBackend | None = None,
        model_backends: tuple[AgentModel, ...] = (),
        proposed_models: tuple[dict[str, object], ...] = (),
        report: Path | None = None,
    ) -> None:
        self.local = LocalQuestions(directory)
        self.live = live
        self.local_agent = local_agent
        self.proposed_models = proposed_models
        if model_backends and (live is not None or local_agent is not None):
            raise ValueError("Configure either explicit model backends or the legacy defaults.")
        if len({model.key for model in model_backends}) != len(model_backends):
            raise ValueError("Configured model keys must be unique.")
        self.model_backends = model_backends
        if not model_backends and (live is not None or local_agent is not None):
            # Existing shared/legacy reviews both pin this exact profile. New model
            # choices require trusted, separately reviewed backend configuration.
            self.model_backends = (
                AgentModel(
                    "nova-lite",
                    "Amazon Nova Lite",
                    "us.amazon.nova-lite-v1:0",
                    local_agent=local_agent,
                    live=live,
                ),
            )
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.replay = None
        if report is not None:
            if report.stat().st_size > MAX_BODY:
                raise UiError("Saved report exceeds 16 MiB.")
            self.replay = read_replay(json.loads(report.read_text()))

    def _backend_state(
        self, backend: LiveBackend | None, mode: str, defaults: dict[str, object]
    ) -> dict[str, object]:
        value = {**defaults, "enabled": backend is not None, "billable": True}
        if backend is not None:
            try:
                public_state = getattr(backend, "public_state", None)
                if callable(public_state):
                    value.update(public_state(mode))
                value["budget"] = backend.ledger.summary()
            except (UiError, OSError):
                value.update(enabled=False, error="The shared/live ledger needs inspection.")
        return value

    def state(self) -> dict[str, object]:
        state: dict[str, object] = {
            "token": self.token,
            "samples": SAMPLES,
            "local": {
                "enabled": True,
                "billable": False,
                "dataset": LOCAL_DATASET,
                "reference_date": REFERENCE_DATE.isoformat(),
                "tenant": "retail_demo",
                "regions": ["North", "South"],
                "description": "Offline playground · deterministic planner with generated samples",
                "cost_notice": "No model or AWS calls. This is not Bedrock agent execution.",
            },
            "local_agent": self._backend_state(
                self.local_agent,
                "local_agent",
                {
                    "dataset": "retail-v1",
                    "reference_date": "2025-04-01",
                    "tenant": "retail_demo",
                    "regions": ["North", "South"],
                    "description": "Local agent · canonical DuckDB data + Amazon Bedrock",
                    "cost_notice": "Billable Bedrock: up to 6 calls/question. Approval required.",
                },
            ),
            "live": self._backend_state(
                self.live,
                "live",
                {
                    "dataset": "parity-v1",
                    "reference_date": "2025-02-01",
                    "tenant": "t1",
                    "regions": ["North", "South"],
                    "runtime_version": "12",
                    "description": "AWS AgentCore · original parity deployment · reviewed v12",
                    "cost_notice": "Billable AWS agent. One Runtime call; no retries.",
                },
            ),
            "metrics": [
                metric.public_description_v2().model_dump(mode="json") for metric in METRICS
            ],
            "replay": self.replay,
            "proposed_models": list(self.proposed_models),
        }
        options = []
        for model in self.model_backends:
            modes = {}
            for mode in ("local_agent", "live"):
                backend = getattr(model, mode)
                if backend is not None:
                    defaults = cast(dict[str, object], state[mode])
                    modes[mode] = self._backend_state(backend, mode, defaults)
            options.append(
                {"key": model.key, "label": model.label, "model_id": model.model_id, "modes": modes}
            )
        state["model_options"] = options
        return state

    def _request(self, body: object) -> tuple[AskRequest, AgentModel | None]:
        request = AskRequest.model_validate(body)
        if request.mode == "local":
            if request.model_key is not None:
                raise UiError("The offline playground does not use a Bedrock model.")
            return request, None
        choices = [model for model in self.model_backends if getattr(model, request.mode)]
        selected = next(
            (model for model in choices if model.key == request.model_key),
            choices[0] if request.model_key is None and choices else None,
        )
        if selected is None:
            raise UiError("The selected model is not configured for this execution mode.")
        # Routing is UI-only. Authorization and model configuration stay owned by
        # the selected backend; its SDK payload still contains only the question.
        return request.model_copy(update={"model_key": None}), selected

    def _execute(
        self,
        request: AskRequest,
        backend: AgentModel | None,
        emit: Callable[[dict[str, object]], None] | None = None,
    ) -> UiResult:
        if request.mode == "local":
            return _validated_result(self.local.ask(request.question))
        assert backend is not None
        runner = cast(LiveBackend, getattr(backend, request.mode))
        streaming = getattr(runner, "ask_with_events", None)
        result = _validated_result(
            streaming(request, emit)
            if emit is not None and callable(streaming)
            else runner.ask(request)
        )
        if result.mode != request.mode or result.response.diagnostics.model_id != backend.model_id:
            raise UiError("The response differs from the configured execution mode or model.")
        return result

    def ask(self, body: object) -> UiResult:
        request, backend = self._request(body)
        if not self.lock.acquire(blocking=False):
            raise UiError("Another question is running. Wait for its result.")
        try:
            return self._execute(request, backend)
        finally:
            self.lock.release()

    def ask_stream(self, body: object) -> Iterator[dict[str, object]]:
        """Stream truthful progress, then validated output, with one backend dispatch.

        A disconnected browser must not cancel bookkeeping or release the question
        lock while the backend is still running. No SDK behavior/retry is changed.
        """
        request, backend = self._request(body)
        if not self.lock.acquire(blocking=False):
            raise UiError("Another question is running. Wait for its result.")
        completed: Queue[dict[str, object]] = Queue(maxsize=32)
        disconnected = threading.Event()
        started = time.monotonic()

        def publish(event: dict[str, object]) -> None:
            if (
                event.get("type") != "answer_delta"
                or event.get("validated") is not True
                or event.get("source") != "bedrock"
                or not isinstance(event.get("text"), str)
                or len(cast(str, event["text"])) > 262144
            ):
                raise UiError("Invalid validated answer stream event.")
            deliver(event)

        def deliver(event: dict[str, object]) -> None:
            while not disconnected.is_set():
                try:
                    completed.put(event, timeout=0.25)
                    return
                except Full:
                    continue

        def run() -> None:
            try:
                result = self._execute(request, backend, publish)
                outcome: dict[str, object] = {
                    "type": "result",
                    "result": result.model_dump(mode="json"),
                }
            except UiError as exc:
                outcome = {"type": "error", "error": str(exc)}
            except BaseException:
                outcome = {
                    "type": "error",
                    "error": (
                        "The question failed. Inspect retained diagnostics before another attempt."
                    ),
                }
            finally:
                self.lock.release()
            deliver(outcome)

        worker = threading.Thread(target=run, daemon=False, name="analytics-question")
        try:
            worker.start()
        except BaseException:
            self.lock.release()
            raise

        def events() -> Iterator[dict[str, object]]:
            try:
                yield {
                    "type": "status",
                    "message": "Question accepted. Waiting for validated output.",
                    "elapsed_ms": 0,
                }
                while True:
                    try:
                        outcome = completed.get(timeout=0.25)
                    except Empty:
                        yield {
                            "type": "status",
                            "message": "Execution is still running. Waiting for validated output.",
                            "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
                        }
                    else:
                        yield outcome
                        if outcome["type"] in {"result", "error"}:
                            return
            finally:
                disconnected.set()

        return _EventStream(events(), disconnected)


def make_server(app: Workbench, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "AnalyticsWorkbench"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format: str, *args: Any) -> None:
            # Do not write submitted questions, tokens or AWS exceptions to access logs.
            pass

        def _host_allowed(self) -> bool:
            actual_port = cast(ThreadingHTTPServer, self.server).server_port
            return self.headers.get("Host") in {
                f"127.0.0.1:{actual_port}",
                f"localhost:{actual_port}",
            }

        def _headers(self, code: int, mime: str, length: int | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", mime)
            if length is not None:
                self.send_header("Content-Length", str(length))
            else:
                self.send_header("Connection", "close")
                self.send_header("X-Accel-Buffering", "no")
                self.close_connection = True
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; img-src 'self' data:; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()

        def _send(self, code: int, value: bytes, mime: str = "application/json") -> None:
            self._headers(code, mime, len(value))
            try:
                self.wfile.write(value)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, code: int, value: object) -> None:
            self._send(code, json.dumps(value).encode())

        def _stream(self, body: object) -> None:
            events = app.ask_stream(body)  # Validate and reject overlap before headers.
            try:
                self._headers(200, "application/x-ndjson; charset=utf-8")
                for event in events:
                    self.wfile.write((json.dumps(event) + "\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                # The one worker retains its lock and finishes durable accounting.
                # A disconnected browser never queues a retry or another dispatch.
                pass
            finally:
                close = getattr(events, "close", None)
                if callable(close):
                    close()

        def do_GET(self) -> None:
            if not self._host_allowed():
                self._json(403, {"error": "Use the printed localhost URL."})
                return
            path = urlsplit(self.path).path
            if path == "/api/state":
                self._json(200, app.state())
                return
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if path not in assets:
                self._json(404, {"error": "Not found."})
                return
            name, mime = assets[path]
            self._send(
                200,
                files("enterprise_analytics_agent.ui").joinpath("assets", name).read_bytes(),
                mime,
            )

        def do_POST(self) -> None:
            host = self.headers.get("Host", "")
            if (
                not self._host_allowed()
                or self.headers.get("Origin") not in {None, f"http://{host}"}
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
                or not secrets.compare_digest(self.headers.get("X-UI-Token", ""), app.token)
            ):
                self._json(403, {"error": "Reload this local application before submitting."})
                return
            if (
                self.headers.get_content_type() != "application/json"
                or "Transfer-Encoding" in self.headers
            ):
                self._json(415, {"error": "A JSON request with Content-Length is required."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    self._json(413, {"error": "Request must be between 1 byte and 16 MiB."})
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("incomplete request")
                body = json.loads(raw)
                if self.path == "/api/ask":
                    result = app.ask(body)
                    self._json(200, {"result": result.model_dump(mode="json")})
                elif self.path == "/api/ask/stream":
                    self._stream(body)
                elif self.path == "/api/replay":
                    self._json(200, read_replay(body))
                else:
                    self._json(404, {"error": "Not found."})
            except UiError as exc:
                self._json(409, {"error": str(exc)})
            except (ValueError, ValidationError):
                self._json(
                    400,
                    {"error": "Invalid question or report. Check its format and required fields."},
                )
            except Exception:
                self._json(
                    500,
                    {
                        "error": "The operation failed. Inspect local diagnostics "
                        "before retrying AWS."
                    },
                )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
