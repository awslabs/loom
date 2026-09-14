"""User-facing MCP Hub HTTP facade (ADR 0007 / 0008 / 0011 / specs 016-024)."""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

from mcp_hub.application.ports import HubStore, LoomGateway, TokenValidator
from mcp_hub.application.use_cases.tools import call_tool, list_tools
from mcp_hub.application.wiring import default_loom, default_store, default_tokens
from mcp_hub.domain.identity import parse_client_info

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


def _read_json(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("Content-Length") or "0")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


class HubHandler(BaseHTTPRequestHandler):
    """Inbound adapter — HTTP only; ports injected on the class before serve()."""

    store: ClassVar[HubStore]
    loom: ClassVar[LoomGateway]
    tokens: ClassVar[TokenValidator]

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info(fmt, *args)

    def _unauthorized_mcp(self, *, jsonrpc: bool = False) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", self.tokens.www_authenticate_value())
        if jsonrpc:
            raw = json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32001, "message": "unauthorized"},
            }).encode("utf-8")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        else:
            self.send_header("Content-Length", "0")
            self.end_headers()

    def _require_service(self) -> bool:
        expected = self.loom.service_token()
        if not expected:
            _json(self, 503, {"error": {"message": "hub_unavailable"}})
            return False
        if _bearer(self) != expected:
            _json(self, 401, {"error": {"message": "unauthorized"}})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            _json(self, 200, {"status": "ok"})
            return
        if path == "/.well-known/oauth-protected-resource":
            _json(self, 200, self.tokens.prm_document())
            return
        if path == "/v1/health":
            if not self.loom.service_token():
                _json(self, 503, {"status": "fail_closed"})
                return
            token = _bearer(self)
            if token == self.loom.service_token():
                _json(self, 200, {"status": "ok", "contract_version": "2026-09-hub-1", "auth": "oauth"})
                return
            identity = self.tokens.validate_access_token(token) if token else None
            if identity is None:
                self._unauthorized_mcp()
                return
            _json(self, 200, {"status": "ok", "contract_version": "2026-09-hub-1", "auth": "oauth"})
            return
        if path in ("/mcp", "/"):
            if not _bearer(self):
                self._unauthorized_mcp()
                return
            if self.tokens.validate_access_token(_bearer(self)) is None:
                self._unauthorized_mcp()
                return
            _method_not_allowed(self)
            return
        if path == "/v1/clients":
            if not self._require_service():
                return
            qs = parse_qs(parsed.query)
            status_filter = (qs.get("status") or [None])[0]
            _json(self, 200, {"clients": self.store.list_clients(status_filter)})
            return
        if path.startswith("/v1/clients/"):
            if not self._require_service():
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
                payload = self.store.get_profile_grants(slug, group)
                if payload is None:
                    _json(self, 404, {"error": {"message": "client_not_found"}})
                    return
                _json(self, 200, payload)
                return
            slug = rest
            if not slug or "/" in slug:
                _json(self, 404, {"error": {"message": "not_found"}})
                return
            row = self.store.get_client(slug)
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
            if not self._require_service():
                return
            slug = path.removeprefix("/v1/clients/").strip("/")
            if not slug or "/" in slug:
                _json(self, 404, {"error": {"message": "not_found"}})
                return
            if not self.store.delete_client(slug):
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
        if not self._require_service():
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
        row = self.store.patch_client(slug, body)
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
        if not self._require_service():
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
        row = self.store.put_profile_grants(mid, group, grants)
        if row is None:
            _json(self, 404, {"error": {"message": "client_not_found"}})
            return
        _json(self, 200, row)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in ("/mcp", "/"):
            _json(self, 404, {"error": {"message": "not_found"}})
            return
        if not self.loom.service_token():
            _json(self, 503, {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "hub_unavailable"}})
            return
        token = _bearer(self)
        if not token:
            self._unauthorized_mcp(jsonrpc=True)
            return
        identity = self.tokens.validate_access_token(token)
        if identity is None:
            self._unauthorized_mcp(jsonrpc=True)
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
        if method == "initialize":
            slug, name, version, family = parse_client_info(params if isinstance(params, dict) else {})
            row = self.store.upsert_from_initialize(
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
            tools = list_tools(identity, store=self.store, loom=self.loom)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
        if method == "tools/call":
            name = str((params or {}).get("name") or "")
            arguments = (params or {}).get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            outcome = call_tool(
                identity,
                name=name,
                arguments=arguments,
                store=self.store,
                loom=self.loom,
            )
            if "error" in outcome:
                return {"jsonrpc": "2.0", "id": req_id, "error": outcome["error"]}
            return {"jsonrpc": "2.0", "id": req_id, "result": outcome.get("result") or {}}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method_not_found:{method}"}}


def serve(
    host: str | None = None,
    port: int | None = None,
    *,
    store: HubStore | None = None,
    loom: LoomGateway | None = None,
    tokens: TokenValidator | None = None,
) -> None:
    HubHandler.store = store or default_store()
    HubHandler.loom = loom or default_loom()
    HubHandler.tokens = tokens or default_tokens()

    bind_host = host or os.environ.get("MCP_HUB_HOST", "0.0.0.0")
    bind_port = port or int(os.environ.get("MCP_HUB_PORT", "8790"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if not HubHandler.loom.service_token():
        logger.error("MCP_HUB_SERVICE_TOKEN unset — fail-closed")
    if not HubHandler.tokens.oidc_issuer():
        logger.error("MCP_HUB_OIDC_ISSUER unset — IDE OAuth will fail-closed")
    elif HubHandler.tokens.warm_jwks():
        logger.info("jwks warm ok issuer=%s", HubHandler.tokens.oidc_issuer())
    else:
        logger.warning("jwks warm failed — will retry on first request")
    try:
        os.makedirs(os.path.dirname(HubHandler.store.store_path()) or ".", exist_ok=True)
    except OSError:
        pass
    server = ThreadingHTTPServer((bind_host, bind_port), HubHandler)
    logger.info(
        "mcp-hub listening on %s:%s store=%s resource=%s auth=oauth",
        bind_host,
        bind_port,
        HubHandler.store.store_path(),
        HubHandler.tokens.resource_url(),
    )
    server.serve_forever()
