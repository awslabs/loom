"""User-facing MCP Hub HTTP facade (ADR 0007 / spec 016)."""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from mcp_hub import loom_client
from mcp_hub.naming import expose_tools

logger = logging.getLogger("mcp_hub")


def _json(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _bearer(handler: BaseHTTPRequestHandler) -> str:
    header = handler.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return ""


def _is_hub_session(token: str) -> bool:
    return bool(token) and token.startswith("hs_") and token.count(".") < 2


def _method_not_allowed(handler: BaseHTTPRequestHandler, allow: str = "POST") -> None:
    """Streamable HTTP: no standalone SSE — clients (Cursor) treat 405 as OK, 404 as fatal."""
    handler.send_response(405)
    handler.send_header("Allow", allow)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


class HubHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            _json(self, 200, {"status": "ok"})
            return
        if path == "/v1/health":
            if not loom_client.service_token():
                _json(self, 503, {"status": "fail_closed"})
                return
            token = _bearer(self)
            if not _is_hub_session(token) and token != loom_client.service_token():
                _json(self, 401, {"error": {"message": "unauthorized"}})
                return
            _json(self, 200, {"status": "ok", "contract_version": "2026-09-hub-1"})
            return
        # Cursor opens GET /mcp as SSE listen; we are POST/JSON-only (MCP 2025-03-26).
        if path in ("/mcp", "/"):
            _method_not_allowed(self)
            return
        _json(self, 404, {"error": {"message": "not_found"}})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/mcp", "/"):
            _method_not_allowed(self)
            return
        _json(self, 404, {"error": {"message": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in ("/mcp", "/"):
            _json(self, 404, {"error": {"message": "not_found"}})
            return
        if not loom_client.service_token():
            _json(self, 503, {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "hub_unavailable"}})
            return
        token = _bearer(self)
        if not _is_hub_session(token):
            _json(self, 401, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "unauthorized"}})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            _json(self, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse_error"}})
            return
        if isinstance(body, list):
            responses = [self._handle_one(token, item) for item in body if isinstance(item, dict)]
            _json(self, 200, responses)
            return
        if not isinstance(body, dict):
            _json(self, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid_request"}})
            return
        # notifications have no id / no response body required; still ack 202-ish as empty 200
        if "id" not in body and body.get("method", "").startswith("notifications/"):
            self.send_response(202)
            self.end_headers()
            return
        _json(self, 200, self._handle_one(token, body))

    def _handle_one(self, token: str, body: dict[str, Any]) -> dict[str, Any]:
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "loom-mcp-hub", "version": "2026-09-hub-1"},
                },
            }
        if method == "notifications/initialized":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            info = loom_client.introspect(token)
            if not info.get("active"):
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": "unauthorized"}}
            status, allow = loom_client.allowlist(str(info["hub_session_id"]))
            if status != 200:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32002, "message": "allowlist_unavailable"}}
            tools, _mapping = expose_tools(allow.get("entries") or [])
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
        if method == "tools/call":
            info = loom_client.introspect(token)
            if not info.get("active"):
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": "unauthorized"}}
            name = str((params or {}).get("name") or "")
            arguments = (params or {}).get("arguments") or {}
            status, result = loom_client.tools_call(str(info["hub_session_id"]), name, arguments if isinstance(arguments, dict) else {})
            if status == 403:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32003, "message": "tool_not_allowed"}}
            if status != 200 or not result.get("success"):
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32004, "message": "tool_call_failed"}}
            return {"jsonrpc": "2.0", "id": req_id, "result": result.get("result") or {}}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method_not_found:{method}"}}


def serve(host: str | None = None, port: int | None = None) -> None:
    bind_host = host or os.environ.get("MCP_HUB_HOST", "0.0.0.0")
    bind_port = port or int(os.environ.get("MCP_HUB_PORT", "8790"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if not loom_client.service_token():
        logger.error("MCP_HUB_SERVICE_TOKEN unset — fail-closed")
    server = ThreadingHTTPServer((bind_host, bind_port), HubHandler)
    logger.info("mcp-hub listening on %s:%s", bind_host, bind_port)
    server.serve_forever()
