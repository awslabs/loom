"""User-facing MCP Hub HTTP facade (ADR 0007 / 0008 / specs 016-022)."""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp_hub import loom_client, store
from mcp_hub.access import grants_for_user
from mcp_hub.identity import parse_client_info
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
    handler.send_response(405)
    handler.send_header("Allow", allow)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _require_service(handler: BaseHTTPRequestHandler) -> bool:
    expected = loom_client.service_token()
    if not expected:
        _json(handler, 503, {"error": {"message": "hub_unavailable"}})
        return False
    if _bearer(handler) != expected:
        _json(handler, 401, {"error": {"message": "unauthorized"}})
        return False
    return True


def _read_json(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("Content-Length") or "0")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def _build_session_allowlist(token: str, hub_session_id: str, groups: list[str]) -> tuple[str, dict[str, Any], dict[str, tuple[int, str]]]:
    slug = store.session_client_slug(hub_session_id)
    if not slug:
        empty = {
            "hub_session_id": hub_session_id,
            "mcp_client_slug": None,
            "client_status": "unbound",
            "entries": [],
        }
        return "unbound", empty, {}
    client = store.get_client(slug, include_grants=True)
    if client is None:
        empty = {
            "hub_session_id": hub_session_id,
            "mcp_client_slug": slug,
            "client_status": "missing",
            "entries": [],
        }
        return slug, empty, {}
    status = str(client.get("status") or "discovered")
    if status != "enabled":
        empty = {
            "hub_session_id": hub_session_id,
            "mcp_client_slug": slug,
            "client_status": status,
            "entries": [],
        }
        return slug, empty, {}
    # Channel enabled → resolve tools for this user's IdP profile before list/call.
    profile_grants = grants_for_user(groups, list(client.get("grants") or []))
    if not profile_grants:
        empty = {
            "hub_session_id": hub_session_id,
            "mcp_client_slug": slug,
            "client_status": status,
            "entries": [],
        }
        return slug, empty, {}
    code, payload = loom_client.materialize_allowlist(
        hub_session_id=hub_session_id,
        mcp_client_slug=slug,
        client_status=status,
        allowed_groups=[],
        grants=profile_grants,
    )
    if code != 200:
        empty = {
            "hub_session_id": hub_session_id,
            "mcp_client_slug": slug,
            "client_status": status,
            "entries": [],
            "error": "materialize_failed",
        }
        return slug, empty, {}
    entries = list(payload.get("entries") or [])
    _tools, mapping = expose_tools(entries)
    return slug, payload, mapping


class HubHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
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
        if path in ("/mcp", "/"):
            _method_not_allowed(self)
            return
        if path == "/v1/clients":
            if not _require_service(self):
                return
            qs = parse_qs(parsed.query)
            status_filter = (qs.get("status") or [None])[0]
            _json(self, 200, {"clients": store.list_clients(status_filter)})
            return
        if path.startswith("/v1/clients/"):
            if not _require_service(self):
                return
            rest = path.removeprefix("/v1/clients/").strip("/")
            # /v1/clients/{slug}/profile-grants?group=…  (on-demand; empty → 200 [])
            if rest.endswith("/profile-grants") or rest.endswith("/grants"):
                slug = rest.removesuffix("/profile-grants").removesuffix("/grants").strip("/")
                if not slug or "/" in slug:
                    _json(self, 404, {"error": {"message": "not_found"}})
                    return
                qs = parse_qs(parsed.query)
                group = (qs.get("group") or [""])[0].strip()
                if not group:
                    _json(self, 400, {"error": {"message": "group_required"}})
                    return
                payload = store.get_profile_grants(slug, group)
                if payload is None:
                    # Missing client only. Empty profile grants → 200 + [].
                    _json(self, 404, {"error": {"message": "client_not_found"}})
                    return
                _json(self, 200, payload)
                return
            slug = rest
            if not slug or "/" in slug:
                _json(self, 404, {"error": {"message": "not_found"}})
                return
            row = store.get_client(slug)
            if row is None:
                _json(self, 404, {"error": {"message": "not_found"}})
                return
            _json(self, 200, row)
            return
        _json(self, 404, {"error": {"message": "not_found"}})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/mcp", "/"):
            _method_not_allowed(self)
            return
        if path.startswith("/v1/clients/"):
            if not _require_service(self):
                return
            slug = path.removeprefix("/v1/clients/").strip("/")
            if not slug or "/" in slug:
                _json(self, 404, {"error": {"message": "not_found"}})
                return
            if not store.delete_client(slug):
                _json(self, 404, {"error": {"message": "not_found"}})
                return
            self.send_response(204)
            self.end_headers()
            return
        _json(self, 404, {"error": {"message": "not_found"}})

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not path.startswith("/v1/clients/"):
            _json(self, 404, {"error": {"message": "not_found"}})
            return
        if not _require_service(self):
            return
        slug = path.removeprefix("/v1/clients/").strip("/")
        if not slug or "/" in slug:
            _json(self, 404, {"error": {"message": "not_found"}})
            return
        try:
            body = _read_json(self)
        except json.JSONDecodeError:
            _json(self, 400, {"error": {"message": "parse_error"}})
            return
        if not isinstance(body, dict):
            _json(self, 400, {"error": {"message": "invalid_request"}})
            return
        row = store.patch_client(slug, body)
        if row is None:
            _json(self, 404, {"error": {"message": "not_found"}})
            return
        _json(self, 200, row)

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not path.startswith("/v1/clients/") or not (
            path.endswith("/profile-grants") or path.endswith("/grants")
        ):
            _json(self, 404, {"error": {"message": "not_found"}})
            return
        if not _require_service(self):
            return
        mid = (
            path.removeprefix("/v1/clients/")
            .removesuffix("/profile-grants")
            .removesuffix("/grants")
            .strip("/")
        )
        if not mid or "/" in mid:
            _json(self, 404, {"error": {"message": "not_found"}})
            return
        try:
            body = _read_json(self)
        except json.JSONDecodeError:
            _json(self, 400, {"error": {"message": "parse_error"}})
            return
        grants = body.get("grants") if isinstance(body, dict) else None
        if not isinstance(grants, list):
            _json(self, 400, {"error": {"message": "grants_required"}})
            return
        group = str(body.get("group") or "").strip() if isinstance(body, dict) else ""
        if not group:
            _json(self, 400, {"error": {"message": "group_required"}})
            return
        row = store.put_profile_grants(mid, group, grants)
        if row is None:
            _json(self, 404, {"error": {"message": "client_not_found"}})
            return
        _json(self, 200, row)

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
        try:
            body = _read_json(self)
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
            info = loom_client.introspect(token)
            if not info.get("active"):
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": "unauthorized"}}
            hub_session_id = str(info["hub_session_id"])
            slug, name, version, family = parse_client_info(params if isinstance(params, dict) else {})
            row = store.upsert_from_initialize(
                hub_session_id=hub_session_id,
                slug=slug,
                declared_name=name,
                declared_version=version,
                declared_family=family,
            )
            logger.info(
                "hub_initialize session=%s slug=%s family=%s status=%s name=%s",
                hub_session_id,
                slug,
                family,
                row.get("status"),
                name[:64],
            )
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
            groups = list(info.get("groups") or [])
            _slug, allow, _mapping = _build_session_allowlist(token, str(info["hub_session_id"]), groups)
            tools, _ = expose_tools(allow.get("entries") or [])
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
        if method == "tools/call":
            info = loom_client.introspect(token)
            if not info.get("active"):
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": "unauthorized"}}
            groups = list(info.get("groups") or [])
            _slug, allow, mapping = _build_session_allowlist(token, str(info["hub_session_id"]), groups)
            name = str((params or {}).get("name") or "")
            arguments = (params or {}).get("arguments") or {}
            if name not in mapping:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32003, "message": "tool_not_allowed"}}
            server_id, original = mapping[name]
            status, result = loom_client.tools_call(
                str(info["hub_session_id"]),
                name,
                arguments if isinstance(arguments, dict) else {},
                server_id=server_id,
                original_tool_name=original,
            )
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
    try:
        os.makedirs(os.path.dirname(store.store_path()) or ".", exist_ok=True)
    except OSError:
        pass
    server = ThreadingHTTPServer((bind_host, bind_port), HubHandler)
    logger.info("mcp-hub listening on %s:%s store=%s", bind_host, bind_port, store.store_path())
    server.serve_forever()
