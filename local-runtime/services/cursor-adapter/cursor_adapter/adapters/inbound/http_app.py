"""Host HTTP surface the LiteLLM CustomLLM calls."""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

from cursor_adapter.application.ports import CursorAgentRunner, SessionStore
from cursor_adapter.application.use_cases.chat import handle_chat_completions
from cursor_adapter.application.wiring import default_runner, default_sessions
from cursor_adapter.domain.errors import unavailable
from cursor_adapter.domain.streaming import format_sse

logger = logging.getLogger("cursor_adapter")


class AdapterHandler(BaseHTTPRequestHandler):
    sessions: ClassVar[SessionStore]
    runner: ClassVar[CursorAgentRunner]

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info(fmt, *args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/health", "/healthz"):
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"error": {"message": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": "not_found"}})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "invalid_json"}})
            return
        headers = {k: v for k, v in self.headers.items()}
        try:
            status, payload, streamed = handle_chat_completions(
                body,
                headers,
                sessions=self.sessions,
                runner=self.runner,
            )
        except Exception:
            logger.exception("unhandled adapter error")
            status, payload, streamed = unavailable().status, unavailable().to_body(), False
        if streamed and isinstance(payload, list):
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in payload:
                self.wfile.write(format_sse(chunk).encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            return
        assert isinstance(payload, dict)
        self._send_json(status, payload)


def bind_address() -> tuple[str, int]:
    """Loopback on the host; 0.0.0.0 inside Compose so LiteLLM can reach us."""
    host = os.environ.get("CURSOR_ADAPTER_HOST", "127.0.0.1").strip() or "127.0.0.1"
    raw_port = os.environ.get("CURSOR_ADAPTER_PORT", "8765").strip() or "8765"
    return host, int(raw_port)


def _wire_defaults() -> None:
    AdapterHandler.sessions = default_sessions()
    AdapterHandler.runner = default_runner()


_wire_defaults()


def serve(
    host: str | None = None,
    port: int | None = None,
    *,
    sessions: SessionStore | None = None,
    runner: CursorAgentRunner | None = None,
) -> None:
    AdapterHandler.sessions = sessions or default_sessions()
    AdapterHandler.runner = runner or default_runner()
    bind_host, bind_port = bind_address()
    if host is not None:
        bind_host = host
    if port is not None:
        bind_port = port
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    server = ThreadingHTTPServer((bind_host, bind_port), AdapterHandler)
    logger.info("cursor adapter listening on %s:%s", bind_host, bind_port)
    server.serve_forever()
