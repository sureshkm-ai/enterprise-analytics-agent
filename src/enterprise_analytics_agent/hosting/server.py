"""AgentCore HTTP protocol: GET /ping and POST /invocations on port 8080."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from enterprise_analytics_agent.hosting.application import RuntimeApplication
from enterprise_analytics_agent.hosting.config import load_settings


def handler_for(application: RuntimeApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format: str, *args: Any) -> None:
            # BaseHTTPRequestHandler includes paths/headers in access logs. Record
            # only sanitized operational evidence in RuntimeApplication instead.
            return

        def respond(self, status: int, payload: object) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def do_GET(self) -> None:
            if self.path == "/ping":
                self.respond(200, {"status": "Healthy"})
            else:
                self.respond(404, {"error": "Unknown endpoint"})

        def do_POST(self) -> None:
            if self.path != "/invocations":
                self.respond(404, {"error": "Unknown endpoint"})
                return
            if self.headers.get("Content-Type", "").partition(";")[0].lower() != "application/json":
                self.respond(415, {"error": "Content-Type must be application/json"})
                return
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
                self.respond(400, {"error": "One Content-Length header is required"})
                return
            try:
                size = int(lengths[0])
            except ValueError:
                self.respond(400, {"error": "Invalid Content-Length"})
                return
            if not 0 < size <= application.settings.max_payload_bytes:
                self.respond(413, {"error": "Request body is outside the allowed size"})
                return
            try:
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ValueError("Incomplete request body")
                payload = json.loads(body)
                result = application.invoke(payload)
            except (TimeoutError, ValueError):
                self.respond(400, {"error": "Invalid request; expected a JSON question only"})
                return
            self.respond(200, result.model_dump(mode="json"))

    return Handler


def main() -> None:
    application = RuntimeApplication(load_settings())
    with ThreadingHTTPServer(("0.0.0.0", 8080), handler_for(application)) as server:
        server.daemon_threads = True
        server.serve_forever()


if __name__ == "__main__":
    main()
