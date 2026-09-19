"""Shared fake HTTP server for CLI tests that need a stand-in backend API
or a stand-in LLM/embedding provider -- avoids depending on FastAPI or a
real network call. Not a test module itself (no ``test_`` prefix).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeApiServer:
    """A tiny threaded HTTP server whose responses are configured per
    (method, path) -- query strings are ignored when matching -- and which
    records every request it receives for assertions."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], tuple[int, dict]] = {}
        self.requests: list[dict] = []
        self.port: int | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def set_route(self, method: str, path: str, status: int, body: dict) -> None:
        self.routes[(method.upper(), path)] = (status, body)

    def start(self) -> int:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(handler_self, method: str) -> None:
                length = int(handler_self.headers.get("Content-Length", 0) or 0)
                raw_body = handler_self.rfile.read(length) if length else b""
                try:
                    parsed_body = json.loads(raw_body) if raw_body else None
                except json.JSONDecodeError:
                    parsed_body = None
                path_only = handler_self.path.split("?", 1)[0]
                server.requests.append(
                    {
                        "method": method,
                        "path": handler_self.path,
                        # lowercased: HTTP headers are case-insensitive but
                        # urllib.request.Request capitalizes what it sends
                        # (e.g. "x-org" -> "X-org"), which would otherwise
                        # make assertions here brittle to that detail.
                        "headers": {k.lower(): v for k, v in handler_self.headers.items()},
                        "body": parsed_body,
                    }
                )
                match = server.routes.get((method, path_only))
                if match is None:
                    handler_self.send_response(404)
                    handler_self.end_headers()
                    return
                status, body = match
                response = json.dumps(body).encode("utf-8")
                handler_self.send_response(status)
                handler_self.send_header("Content-Type", "application/json")
                handler_self.end_headers()
                handler_self.wfile.write(response)

            def do_GET(handler_self):
                handler_self._handle("GET")

            def do_POST(handler_self):
                handler_self._handle("POST")

            def do_PUT(handler_self):
                handler_self._handle("PUT")

            def do_DELETE(handler_self):
                handler_self._handle("DELETE")

            def log_message(handler_self, *args):
                pass  # keep test output quiet

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
