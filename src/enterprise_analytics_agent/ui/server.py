"""Loopback-only browser application. All AWS work is behind an explicit POST."""

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

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


class Budget(Protocol):
    def summary(self) -> dict[str, object]: ...


class LiveBackend(Protocol):
    @property
    def ledger(self) -> Budget: ...

    def ask(self, request: AskRequest) -> UiResult: ...


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
        report: Path | None = None,
    ) -> None:
        self.local = LocalQuestions(directory)
        self.live = live
        self.local_agent = local_agent
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
        return {
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
        }

    def ask(self, body: object) -> UiResult:
        request = AskRequest.model_validate(body)
        if not self.lock.acquire(blocking=False):
            raise UiError("Another question is running. Wait for its result.")
        try:
            if request.mode == "local":
                return self.local.ask(request.question)
            backend = self.local_agent if request.mode == "local_agent" else self.live
            if backend is None:
                raise UiError(
                    "Local Bedrock mode is disabled; billable-call approval is required."
                    if request.mode == "local_agent"
                    else "AWS mode is not enabled. Start with an approved UI live review."
                )
            return backend.ask(request)
        finally:
            self.lock.release()


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

        def _send(self, code: int, value: bytes, mime: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(value)))
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
            try:
                self.wfile.write(value)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, code: int, value: object) -> None:
            self._send(code, json.dumps(value).encode())

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
