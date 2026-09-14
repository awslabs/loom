"""Internal HTTP facade. Requires MCP_RUNTIME_TOKEN. Loopback/compose only."""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from mcp_runtime.secrets import SecretError
from mcp_runtime.supervisor import SUPERVISOR
from mcp_runtime.templates import TemplateError, public_templates

logger = logging.getLogger("mcp_runtime")


def runtime_token() -> str:
    return os.environ.get("MCP_RUNTIME_TOKEN", "").strip()


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    expected = runtime_token()
    if not expected:
        return False
    header = handler.headers.get("Authorization", "")
    return header == f"Bearer {expected}"


def _allowed_tools(handler: BaseHTTPRequestHandler) -> set[str] | None:
    raw = handler.headers.get("X-Loom-Allowed-Tools", "").strip()
    if not raw or raw == "*":
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


class RuntimeHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            _json(self, 200, {"status": "ok"})
            return
        if not _authorized(self):
            _json(self, 401, {"error": {"message": "unauthorized", "code": "runtime_auth"}})
            return
        if parsed.path == "/runtime/templates":
            _json(self, 200, {"templates": public_templates()})
            return
        if parsed.path.startswith("/runtime/servers/") and parsed.path.endswith("/health"):
            try:
                server_id = int(parsed.path.split("/")[3])
                _json(self, 200, SUPERVISOR.health(server_id))
            except KeyError:
                _json(self, 404, {"error": {"message": "unknown_server"}})
            except ValueError:
                _json(self, 404, {"error": {"message": "unknown_server"}})
            return
        _json(self, 404, {"error": {"message": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        if not _authorized(self):
            _json(self, 401, {"error": {"message": "unauthorized", "code": "runtime_auth"}})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            _json(self, 400, {"error": {"message": "invalid_json"}})
            return
        path = urlparse(self.path).path
        try:
            self._dispatch_post(path, body)
        except TemplateError as exc:
            _json(self, 400, {"error": {"message": str(exc), "code": "template_error"}})
        except SecretError as exc:
            _json(self, 400, {"error": {"message": str(exc), "code": "secret_unresolved"}})
        except KeyError:
            _json(self, 404, {"error": {"message": "unknown_server"}})
        except Exception as exc:
            logger.exception("runtime error")
            message = str(exc)
            if "environment variable" in message or len(message) > 80:
                message = "runtime_error"
            _json(self, 500, {"error": {"message": message, "code": "runtime_error"}})

    def _dispatch_post(self, path: str, body: dict[str, Any]) -> None:
        if path == "/runtime/servers/register":
            handle = SUPERVISOR.register(
                int(body["server_id"]),
                str(body["template_id"]),
                body.get("params") or {},
                body.get("secret_refs") or [],
            )
            _json(self, 200, {"server_id": handle.server_id, "state": handle.state})
            return
        if path.startswith("/runtime/servers/") and path.endswith("/start"):
            handle = SUPERVISOR.start(int(path.split("/")[3]))
            _json(self, 200, {"server_id": handle.server_id, "state": handle.state})
            return
        if path.startswith("/runtime/servers/") and path.endswith("/stop"):
            handle = SUPERVISOR.stop(int(path.split("/")[3]))
            _json(self, 200, {"server_id": handle.server_id, "state": handle.state})
            return
        if path.startswith("/runtime/servers/") and path.endswith("/restart"):
            handle = SUPERVISOR.restart(int(path.split("/")[3]))
            _json(self, 200, {"server_id": handle.server_id, "state": handle.state})
            return
        if path.startswith("/s/") and path.endswith("/mcp"):
            server_id = int(path.split("/")[2])
            self._mcp(server_id, body)
            return
        _json(self, 404, {"error": {"message": "not_found"}})

    def _mcp(self, server_id: int, body: dict[str, Any]) -> None:
        method = body.get("method")
        params = body.get("params")
        allowed = _allowed_tools(self)
        if method == "tools/list" and allowed is not None:
            result = SUPERVISOR.call(server_id, "tools/list", params)
            tools = (result.get("result") or {}).get("tools") or []
            filtered = [tool for tool in tools if tool.get("name") in allowed]
            result = {**result, "result": {**(result.get("result") or {}), "tools": filtered}}
            _json(self, 200, result)
            return
        if method == "tools/call" and allowed is not None:
            name = (params or {}).get("name")
            if name not in allowed:
                _json(self, 403, {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {"code": 403, "message": "tool_denied"},
                })
                return
        result = SUPERVISOR.call(server_id, str(method), params)
        _json(self, 200, result)


def serve(host: str | None = None, port: int | None = None) -> None:
    bind_host = host or os.environ.get("MCP_RUNTIME_HOST", "127.0.0.1")
    bind_port = port or int(os.environ.get("MCP_RUNTIME_PORT", "8787"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    server = ThreadingHTTPServer((bind_host, bind_port), RuntimeHandler)
    logger.info("mcp-runtime listening on %s:%s", bind_host, bind_port)
    try:
        server.serve_forever()
    finally:
        SUPERVISOR.stop_all()
        server.server_close()
