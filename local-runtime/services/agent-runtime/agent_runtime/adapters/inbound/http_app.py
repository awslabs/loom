"""HTTP facade for the local agent runtime (ADR 0005 / spec 011)."""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import urlparse

from agent_runtime.application.ports import LlmGateway, McpToolsClient, SessionStore
from agent_runtime.application.use_cases.invoke import run_invoke
from agent_runtime.application.wiring import default_llm, default_mcp, default_sessions
from agent_runtime.domain.contract import CONTRACT_VERSION, SUPPORTED_CONTRACTS, validate_payload
from agent_runtime.domain.errors import AgentRuntimeError

logger = logging.getLogger("agent_runtime")


def runtime_token() -> str:
    return os.environ.get("AGENT_RUNTIME_TOKEN", "").strip()


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    expected = runtime_token()
    if not expected:
        return False
    header = handler.headers.get("Authorization", "")
    return header == f"Bearer {expected}"


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


class RuntimeHandler(BaseHTTPRequestHandler):
    sessions: ClassVar[SessionStore]
    llm: ClassVar[LlmGateway]
    mcp: ClassVar[McpToolsClient]

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            _json(self, 200, {"status": "ok"})
            return
        if path == "/v1/health":
            if not _authorized(self):
                _json(self, 401, {"error": {"message": "unauthorized", "code": "runtime_auth"}})
                return
            _json(self, 200, {
                "status": "ok",
                "active_sessions": self.sessions.active_count(),
                "contract_versions": sorted(SUPPORTED_CONTRACTS),
            })
            return
        _json(self, 404, {"error": {"message": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not _authorized(self):
            _json(self, 401, {"error": {"message": "unauthorized", "code": "runtime_auth"}})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            _json(self, 400, {"error": {"message": "invalid_json", "code": "invalid_payload"}})
            return

        if path.startswith("/v1/sessions/") and path.endswith("/cancel"):
            session_id = path.split("/")[3]
            cancelled = self.sessions.cancel(session_id)
            _json(self, 200, {"cancelled": cancelled, "session_id": session_id})
            return

        if path != "/v1/invoke":
            _json(self, 404, {"error": {"message": "not_found"}})
            return

        try:
            payload = validate_payload(body if isinstance(body, dict) else {})
        except AgentRuntimeError as exc:
            status = 400 if exc.code in {"unsupported_contract", "invalid_payload"} else 500
            _json(self, status, {"error": {"message": exc.message, "code": exc.code}})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for chunk in run_invoke(
                payload,
                sessions=self.sessions,
                llm=self.llm,
                mcp=self.mcp,
            ):
                self.wfile.write(chunk)
                self.wfile.flush()
        except BrokenPipeError:
            logger.info("client disconnected session=%s", payload.get("session_id"))
        except Exception:
            logger.exception("invoke stream failed")
            try:
                self.wfile.write(
                    f"event: error\ndata: {json.dumps({'message': 'internal error', 'code': 'internal'})}\n\n".encode("utf-8")
                )
            except Exception:
                pass


def _wire_defaults() -> None:
    RuntimeHandler.sessions = default_sessions()
    RuntimeHandler.llm = default_llm()
    RuntimeHandler.mcp = default_mcp()


_wire_defaults()


def serve(
    host: str | None = None,
    port: int | None = None,
    *,
    sessions: SessionStore | None = None,
    llm: LlmGateway | None = None,
    mcp: McpToolsClient | None = None,
) -> None:
    RuntimeHandler.sessions = sessions or default_sessions()
    RuntimeHandler.llm = llm or default_llm()
    RuntimeHandler.mcp = mcp or default_mcp()

    bind_host = host or os.environ.get("AGENT_RUNTIME_HOST", "127.0.0.1")
    bind_port = port or int(os.environ.get("AGENT_RUNTIME_PORT", "8766"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not runtime_token():
        logger.error("AGENT_RUNTIME_TOKEN is empty — fail-closed (all /v1/* will 401)")
    server = ThreadingHTTPServer((bind_host, bind_port), RuntimeHandler)
    logger.info("agent-runtime listening on %s:%s contract=%s", bind_host, bind_port, CONTRACT_VERSION)
    try:
        server.serve_forever()
    finally:
        server.server_close()
