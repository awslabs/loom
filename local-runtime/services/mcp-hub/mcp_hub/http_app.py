"""User-facing MCP Hub HTTP facade (ADR 0007 / 0008 / 0011 / specs 016-024)."""
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
from mcp_hub import oauth

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


def _method_not_allowed(handler: BaseHTTPRequestHandler, allow: str = "POST") -> None:
    handler.send_response(405)
    handler.send_header("Allow", allow)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _unauthorized_mcp(handler: BaseHTTPRequestHandler, *, jsonrpc: bool = False) -> None:
    handler.send_response(401)
    handler.send_header("WWW-Authenticate", oauth.www_authenticate_value())
    if jsonrpc:
        raw = json.dumps({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32001, "message": "unauthorized"},
        }).encode("utf-8")
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)
    else:
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


def _require_user(handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
    token = _bearer(handler)
    if not token:
        _unauthorized_mcp(handler, jsonrpc=False)
        return None
    identity = oauth.validate_access_token(token)
    if identity is None:
        _unauthorized_mcp(handler, jsonrpc=False)
        return None
    return identity


def _build_session_allowlist(
    identity: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, tuple[int, str]]]:
    connection_id = str(identity["connection_id"])
    groups = list(identity.get("groups") or [])
    slug = store.session_client_slug(connection_id)
    if not slug:
        empty = {
            "connection_id": connection_id,
            "mcp_client_slug": None,
            "client_status": "unbound",
            "entries": [],
        }
        return "unbound", empty, {}
    client = store.get_client(slug, include_grants=True)
    if client is None:
        empty = {
            "connection_id": connection_id,
            "mcp_client_slug": slug,
            "client_status": "missing",
            "entries": [],
        }
        return slug, empty, {}
    status = str(client.get("status") or "discovered")
    if status != "enabled":
        empty = {
            "connection_id": connection_id,
            "mcp_client_slug": slug,
            "client_status": status,
            "entries": [],
        }
        return slug, empty, {}
    profile_grants = grants_for_user(groups, list(client.get("grants") or []))
    if not profile_grants:
        empty = {
            "connection_id": connection_id,
            "mcp_client_slug": slug,
            "client_status": status,
            "entries": [],
        }
        return slug, empty, {}
    code, payload = loom_client.materialize_allowlist(
        subject=str(identity["sub"]),
        groups=groups,
        connection_id=connection_id,
        mcp_client_slug=slug,
        client_status=status,
        grants=profile_grants,
    )
    if code != 200:
        empty = {
            "connection_id": connection_id,
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
        if path == "/.well-known/oauth-protected-resource":
            _json(self, 200, oauth.prm_document())
            return
        if path == "/v1/health":
            if not loom_client.service_token():
                _json(self, 503, {"status": "fail_closed"})
                return
            token = _bearer(self)
            if token == loom_client.service_token():
                _json(self, 200, {"status": "ok", "contract_version": "2026-09-hub-1", "auth": "oauth"})
                return
            identity = oauth.validate_access_token(token) if token else None
            if identity is None:
                _unauthorized_mcp(self)
                return
            _json(self, 200, {"status": "ok", "contract_version": "2026-09-hub-1", "auth": "oauth"})
            return
        if path in ("/mcp", "/"):
            # Optional auth probe: unauthenticated → 401 challenge (MCP OAuth).
            if not _bearer(self):
                _unauthorized_mcp(self)
                return
            if oauth.validate_access_token(_bearer(self)) is None:
                _unauthorized_mcp(self)
                return
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
        if not token:
            _unauthorized_mcp(self, jsonrpc=True)
            return
        identity = oauth.validate_access_token(token)
        if identity is None:
            _unauthorized_mcp(self, jsonrpc=True)
            return
        try:
            body = _read_json(self)
        except json.JSONDecodeError:
            _json(self, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse_error"}})
            return
        if isinstance(body, list):
            responses = [self._handle_one(identity, item) for item in body if isinstance(item, dict)]
            _json(self, 200, responses)
            return
        if not isinstance(body, dict):
            _json(self, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid_request"}})
            return
        if "id" not in body and body.get("method", "").startswith("notifications/"):
            self.send_response(202)
            self.end_headers()
            return
        _json(self, 200, self._handle_one(identity, body))

    def _handle_one(self, identity: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}
        connection_id = str(identity["connection_id"])
        groups = list(identity.get("groups") or [])
        if method == "initialize":
            slug, name, version, family = parse_client_info(params if isinstance(params, dict) else {})
            row = store.upsert_from_initialize(
                hub_session_id=connection_id,
                slug=slug,
                declared_name=name,
                declared_version=version,
                declared_family=family,
            )
            logger.info(
                "hub_initialize connection=%s slug=%s family=%s status=%s name=%s",
                connection_id,
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
            _slug, allow, _mapping = _build_session_allowlist(identity)
            tools, _ = expose_tools(allow.get("entries") or [])
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
        if method == "tools/call":
            _slug, allow, mapping = _build_session_allowlist(identity)
            name = str((params or {}).get("name") or "")
            arguments = (params or {}).get("arguments") or {}
            if name not in mapping:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32003, "message": "tool_not_allowed"}}
            server_id, original = mapping[name]
            status, result = loom_client.tools_call(
                subject=str(identity["sub"]),
                groups=groups,
                tool_name=name,
                arguments=arguments if isinstance(arguments, dict) else {},
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
    if not oauth.oidc_issuer():
        logger.error("MCP_HUB_OIDC_ISSUER unset — IDE OAuth will fail-closed")
    elif oauth.warm_jwks():
        logger.info("jwks warm ok issuer=%s", oauth.oidc_issuer())
    else:
        logger.warning("jwks warm failed — will retry on first request")
    try:
        os.makedirs(os.path.dirname(store.store_path()) or ".", exist_ok=True)
    except OSError:
        pass
    server = ThreadingHTTPServer((bind_host, bind_port), HubHandler)
    logger.info(
        "mcp-hub listening on %s:%s store=%s resource=%s auth=oauth",
        bind_host,
        bind_port,
        store.store_path(),
        oauth.resource_url(),
    )
    server.serve_forever()
