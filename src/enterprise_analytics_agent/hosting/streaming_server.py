"""Opt-in fixed-model AgentCore SSE entry point; legacy hosting is unchanged."""

import json
import threading
import time
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Full, Queue
from typing import Any, cast

from enterprise_analytics_agent.adapters.bedrock_agent import BedrockAnalyticsAgent
from enterprise_analytics_agent.adapters.bedrock_mantle import BedrockMantleClient
from enterprise_analytics_agent.adapters.bedrock_model_catalog import ModelSpec, model_catalog
from enterprise_analytics_agent.adapters.bedrock_word_stream import ConverseStreamClient
from enterprise_analytics_agent.adapters.streaming_agent import StreamingAnalyticsAgent
from enterprise_analytics_agent.adapters.streaming_diagnostics import report_aws_failure
from enterprise_analytics_agent.agent.contracts import AgentDiagnostics, AgentRequest, AgentResponse
from enterprise_analytics_agent.hosting.application import build_agent
from enterprise_analytics_agent.hosting.config import RuntimeSettings, load_settings
from enterprise_analytics_agent.hosting.workload import workload_session


def build_streaming_agent(settings: RuntimeSettings) -> StreamingAnalyticsAgent:
    model = next((m for m in _catalog() if m.model_id == settings.model_id), None)
    if model is None:
        raise ValueError("The fixed deployment model is outside the reviewed Bedrock catalog.")
    agent = build_agent(settings)
    if not isinstance(agent, BedrockAnalyticsAgent):
        raise TypeError("The streaming release requires the shared semantic agent implementation.")
    if model.transport == "mantle_chat":
        client = BedrockMantleClient(session=workload_session(settings))
        agent.client = client
    return StreamingAnalyticsAgent(
        agent,
        presentation_client=cast(ConverseStreamClient, agent.client),
        allow_temperature=model.temperature_supported,
        planner_operation="ChatCompletions" if model.transport == "mantle_chat" else "Converse",
        presentation_operation=(
            "ChatCompletionsStream" if model.transport == "mantle_chat" else "ConverseStream"
        ),
        readable=True,
    )


def _catalog() -> tuple[ModelSpec, ...]:
    # Kept in the adapter layer; importing/health checks create no SDK client.
    return model_catalog()


class StreamingApplication:
    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        factory: Callable[[RuntimeSettings], StreamingAnalyticsAgent] = build_streaming_agent,
        log: Callable[[str], None] = print,
    ) -> None:
        self.settings, self.factory, self.log = settings, factory, log

    def execute(self, payload: object, emit: Callable[[dict[str, object]], None]) -> None:
        request = AgentRequest.model_validate(payload)
        identifier = str(uuid.uuid4())  # Diagnostic correlation only, never identity.
        call_events: list[dict[str, object]] = []

        def record(event: dict[str, object]) -> None:
            call_events.append(dict(event))
            self.log(
                json.dumps(
                    {
                        "event": "streaming_model_call",
                        "request_id": identifier,
                        "model_id": self.settings.model_id,
                        "call": event,
                    }
                )
            )

        def diagnostic(event: dict[str, object]) -> None:
            # This sink is separate from call_events and every public SSE/response
            # field. The adapter supplies only allowlisted, redacted AWS fields.
            self.log(
                json.dumps(
                    {
                        "event": "streaming_aws_error",
                        "request_id": identifier,
                        "model_id": self.settings.model_id,
                        **event,
                    }
                )
            )

        try:
            try:
                runner = self.factory(self.settings)
            except BaseException as exc:
                # Setup reads/credential assumption are not model attempts. Keep
                # their AWS failure private without fabricating call reservations.
                report_aws_failure(exc, operation=None, number=0, diagnostic=diagnostic)
                raise
            outcome = runner.run(
                request,
                context=self.settings.authorization_context(),
                on_verified=lambda value: emit(
                    {
                        "type": "verified",
                        "response": value.model_dump(mode="json"),
                        **(
                            {"display_answer": runner.presentation_text(value)}
                            if isinstance(runner, StreamingAnalyticsAgent) and runner.readable
                            else {}
                        ),
                    }
                ),
                on_word=lambda text: emit(
                    {
                        "type": "answer_delta",
                        "text": text,
                        "source": "bedrock",
                        "validated": True,
                    }
                ),
                record=record,
                diagnostic=diagnostic,
            )
            result: dict[str, object] = {
                "type": "result",
                "response": outcome.response.model_dump(mode="json"),
                "presentation_status": outcome.presentation,
                "presentation_reason": outcome.reason,
                "model_calls": list(outcome.calls),
                **(
                    {"display_answer": outcome.display_answer}
                    if outcome.display_answer is not None
                    else {}
                ),
            }
        except BaseException as exc:
            try:
                self.log(
                    json.dumps(
                        {
                            "event": "streaming_runtime_error",
                            "request_id": identifier,
                            "error_type": type(exc).__name__,
                        }
                    )
                )
            except Exception:
                pass
            response = AgentResponse(
                status="error",
                answer="The analytics streaming runtime is unavailable.",
                dataset_version=self.settings.dataset_version,
                error_code="streaming_runtime_unavailable",
                diagnostics=AgentDiagnostics(
                    model_id=self.settings.model_id,
                    model_calls=sum(event.get("event") == "reserved" for event in call_events),
                ),
            )
            result = {
                "type": "result",
                "response": response.model_dump(mode="json"),
                "presentation_status": "not_needed",
                "model_calls": call_events,
            }
        emit(result)


def handler_for(application: StreamingApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def respond(self, status: int, value: object) -> None:
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass

        def do_GET(self) -> None:
            self.respond(
                200 if self.path == "/ping" else 404,
                {"status": "Healthy"} if self.path == "/ping" else {"error": "Not found"},
            )

        def do_POST(self) -> None:
            if self.path != "/invocations":
                self.respond(404, {"error": "Not found"})
                return
            lengths = self.headers.get_all("Content-Length", [])
            if (
                self.headers.get_content_type() != "application/json"
                or self.headers.get("Transfer-Encoding")
                or len(lengths) != 1
            ):
                self.respond(400, {"error": "One JSON question with Content-Length is required"})
                return
            try:
                length = int(lengths[0])
                if not 0 < length <= application.settings.max_payload_bytes:
                    raise ValueError("payload length")
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError("incomplete payload")
                request = AgentRequest.model_validate(json.loads(data))
            except (ValueError, TimeoutError):
                self.respond(400, {"error": "Expected a JSON question only"})
                return
            if self.headers.get("Accept", "").split(";", 1)[0] != "text/event-stream":
                results: list[dict[str, object]] = []
                application.execute(request.model_dump(), results.append)
                self.respond(200, results[-1]["response"])
                return
            events: Queue[dict[str, object]] = Queue(maxsize=32)
            closed = threading.Event()

            def emit(event: dict[str, object]) -> None:
                while not closed.is_set():
                    try:
                        events.put(event, timeout=0.25)
                        return
                    except Full:
                        continue

            worker = threading.Thread(
                target=application.execute,
                args=(request.model_dump(), emit),
                daemon=False,
                name="governed-streaming-runtime",
            )
            worker.start()
            deadline = time.monotonic() + application.settings.timeout_seconds + 180
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                while True:
                    try:
                        event = events.get(timeout=0.25)
                    except Empty:
                        if not worker.is_alive() or time.monotonic() >= deadline:
                            self.wfile.write(
                                b'data: {"type":"error","error":'
                                b'"The runtime stream did not complete within its budget."}\n\n'
                            )
                            self.wfile.flush()
                            break
                        self.wfile.write(b": running\n\n")
                    else:
                        self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                        if event["type"] == "result":
                            self.wfile.flush()
                            break
                    self.wfile.flush()
            except OSError:
                pass
            finally:
                closed.set()
                self.close_connection = True

    return Handler


def main() -> None:
    settings = load_settings()
    # Catalog membership is checked without resolving credentials on startup.
    if not any(model.model_id == settings.model_id for model in _catalog()):
        raise ValueError("Unsupported fixed streaming model")
    app = StreamingApplication(settings)
    with ThreadingHTTPServer(("0.0.0.0", 8080), handler_for(app)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
