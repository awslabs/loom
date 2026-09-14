"""MCP HTTP JSON-RPC client (tools/list + tools/call)."""
from __future__ import annotations

import os
from typing import Any

import httpx

from agent_runtime.domain.contract import tool_name
from agent_runtime.domain.errors import AgentRuntimeError


def mcp_runtime_token() -> str:
    return os.environ.get("MCP_RUNTIME_TOKEN", "").strip()


def _mcp_headers(server: dict[str, Any], identity: dict[str, str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    auth = server.get("auth") if isinstance(server.get("auth"), dict) else {}
    auth_type = (auth.get("type") or "none").lower()
    if auth_type == "service_bearer":
        token = auth.get("token") or mcp_runtime_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        header_name = auth.get("api_key_header_name") or "x-api-key"
        value = auth.get("api_key") or ""
        if value:
            headers[header_name] = value
    elif auth_type in ("loom", "none") and mcp_runtime_token():
        headers["Authorization"] = f"Bearer {mcp_runtime_token()}"
    if identity.get("subject"):
        headers["X-Loom-Subject"] = identity["subject"]
    if identity.get("agent_id"):
        headers["X-Loom-Agent-Id"] = identity["agent_id"]
    if identity.get("session_id"):
        headers["X-Loom-Session-Id"] = identity["session_id"]
    allowed = server.get("allowed_tools")
    if allowed is None:
        headers["X-Loom-Allowed-Tools"] = "*"
    elif isinstance(allowed, list):
        headers["X-Loom-Allowed-Tools"] = ",".join(str(item) for item in allowed)
    return headers


class McpHttpClient:
    """Outbound adapter implementing ``McpToolsClient``."""

    def _jsonrpc(
        self,
        client: httpx.Client,
        server: dict[str, Any],
        identity: dict[str, str],
        method: str,
        params: dict[str, Any] | None = None,
        req_id: int = 1,
    ) -> dict[str, Any]:
        url = server.get("endpoint_url")
        if not isinstance(url, str) or not url.strip():
            raise AgentRuntimeError(
                "invalid_payload",
                f"mcp server {server.get('name')!r} missing endpoint_url",
            )
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            body["params"] = params
        try:
            response = client.post(url, json=body, headers=_mcp_headers(server, identity))
        except httpx.HTTPError as exc:
            raise AgentRuntimeError("mcp_unreachable", f"mcp unreachable: {exc}") from exc
        if response.status_code >= 400:
            detail = ""
            try:
                err_body = response.json()
                if isinstance(err_body, dict):
                    err = err_body.get("error")
                    if isinstance(err, dict) and err.get("message"):
                        detail = f": {err.get('message')}"
                    elif err_body.get("message"):
                        detail = f": {err_body.get('message')}"
            except ValueError:
                detail = ""
            if response.status_code == 404:
                raise AgentRuntimeError(
                    "mcp_unreachable",
                    f"mcp HTTP 404{detail} (stdio child not registered — Refresh Tools or retry invoke)",
                )
            raise AgentRuntimeError("mcp_unreachable", f"mcp HTTP {response.status_code}{detail}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AgentRuntimeError("mcp_unreachable", "mcp returned non-JSON") from exc
        if not isinstance(payload, dict):
            raise AgentRuntimeError("mcp_unreachable", "mcp returned invalid envelope")
        return payload

    def load_tools(
        self,
        mcp_servers: list[dict[str, Any]],
        identity: dict[str, str],
        *,
        timeout_s: float,
    ) -> tuple[list[dict[str, Any]], dict[str, tuple[dict[str, Any], str]]]:
        openai_tools: list[dict[str, Any]] = []
        mapping: dict[str, tuple[dict[str, Any], str]] = {}
        timeout = httpx.Timeout(timeout_s, connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            for server in mcp_servers:
                name = str(server.get("name") or "mcp")
                listed = self._jsonrpc(client, server, identity, "tools/list")
                if "error" in listed:
                    message = (
                        (listed.get("error") or {}).get("message")
                        if isinstance(listed.get("error"), dict)
                        else listed.get("error")
                    )
                    raise AgentRuntimeError(
                        "mcp_unreachable",
                        f"tools/list failed for {name}: {message}",
                    )
                tools = ((listed.get("result") or {}).get("tools")) or []
                allow = server.get("allowed_tools")
                allow_set = {str(item) for item in allow} if isinstance(allow, list) else None
                for tool in tools:
                    tname = str(tool.get("name") or "")
                    if not tname:
                        continue
                    if allow_set is not None and tname not in allow_set:
                        continue
                    keyed = tool_name(name, tname)
                    mapping[keyed] = (server, tname)
                    schema = tool.get("inputSchema") or tool.get("input_schema") or {
                        "type": "object",
                        "properties": {},
                    }
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": keyed,
                            "description": (tool.get("description") or f"{name}: {tname}")[:500],
                            "parameters": schema,
                        },
                    })
        return openai_tools, mapping

    def call_tool(
        self,
        server: dict[str, Any],
        identity: dict[str, str],
        *,
        name: str,
        arguments: dict[str, Any],
        timeout_s: float,
        req_id: int = 1,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(timeout_s, connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            return self._jsonrpc(
                client,
                server,
                identity,
                "tools/call",
                {"name": name, "arguments": arguments},
                req_id=req_id,
            )
