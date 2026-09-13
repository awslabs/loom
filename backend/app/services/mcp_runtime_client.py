"""HTTP client for the compose mcp-runtime. Does not Popen children."""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)


class McpRuntimeError(RuntimeError):
    """Runtime missing, unauthorized, or child failed."""


def runtime_base_url() -> str:
    return os.getenv("MCP_RUNTIME_URL", "http://mcp-runtime:8787").rstrip("/")


def runtime_token() -> str:
    return os.getenv("MCP_RUNTIME_TOKEN", "").strip()


def facade_url(server_id: int) -> str:
    return f"{runtime_base_url()}/s/{server_id}/mcp"


def _headers(identity: dict[str, str] | None = None, allowed_tools: list[str] | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = runtime_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if identity:
        if identity.get("subject"):
            headers["X-Loom-Subject"] = identity["subject"]
        if identity.get("agent_id"):
            headers["X-Loom-Agent-Id"] = identity["agent_id"]
        if identity.get("session_id"):
            headers["X-Loom-Session-Id"] = identity["session_id"]
    if allowed_tools is None:
        headers["X-Loom-Allowed-Tools"] = "*"
    else:
        headers["X-Loom-Allowed-Tools"] = ",".join(allowed_tools)
    return headers


def _request(method: str, path: str, json_body: dict[str, Any] | None = None, identity: dict[str, str] | None = None) -> dict[str, Any]:
    url = urljoin(runtime_base_url() + "/", path.lstrip("/"))
    try:
        timeout = 180.0 if path.rstrip("/").endswith("/start") else 60.0
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, json=json_body, headers=_headers(identity))
    except httpx.HTTPError as exc:
        raise McpRuntimeError(f"mcp-runtime unreachable: {exc}") from exc
    if response.status_code == 401:
        raise McpRuntimeError("mcp-runtime rejected the service token")
    if response.status_code == 404:
        raise McpRuntimeError("mcp-runtime does not know this server")
    try:
        payload = response.json()
    except ValueError as exc:
        raise McpRuntimeError("mcp-runtime returned non-JSON") from exc
    if response.status_code >= 400:
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else response.text
        raise McpRuntimeError(str(message) or f"mcp-runtime HTTP {response.status_code}")
    return payload


def register(server_id: int, template_id: str, params: dict[str, Any], secret_refs: list[dict[str, Any]]) -> dict[str, Any]:
    return _request("POST", "/runtime/servers/register", {
        "server_id": server_id,
        "template_id": template_id,
        "params": params,
        "secret_refs": secret_refs,
    })


def start(server_id: int) -> dict[str, Any]:
    return _request("POST", f"/runtime/servers/{server_id}/start", {})


def stop(server_id: int) -> dict[str, Any]:
    return _request("POST", f"/runtime/servers/{server_id}/stop", {})


def restart(server_id: int) -> dict[str, Any]:
    return _request("POST", f"/runtime/servers/{server_id}/restart", {})


def health(server_id: int) -> dict[str, Any]:
    return _request("GET", f"/runtime/servers/{server_id}/health")


def call_mcp(
    server_id: int,
    method: str,
    params: dict[str, Any] | None = None,
    identity: dict[str, str] | None = None,
    allowed_tools: list[str] | None = None,
) -> dict[str, Any] | None:
    url = facade_url(server_id)
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, json=body, headers=_headers(identity, allowed_tools))
    except httpx.HTTPError as exc:
        logger.warning("stdio MCP call to runtime failed: %s", exc)
        return None
    if response.status_code >= 400:
        logger.warning("stdio MCP call HTTP %s: %s", response.status_code, response.text[:300])
        try:
            return response.json()
        except ValueError:
            return None
    try:
        return response.json()
    except ValueError:
        return None


def provision(server_id: int, template_id: str, params: dict[str, Any], secret_refs: list[dict[str, Any]]) -> str:
    """Register and start. Returns runtime_state (READY or FAILED)."""
    register(server_id, template_id, params, secret_refs)
    result = start(server_id)
    return str(result.get("state") or "READY")


def ensure_stdio(server: Any) -> str:
    """Re-register after a runtime recreate, then start the child."""
    template_id = getattr(server, "template_id", None)
    if not template_id:
        raise McpRuntimeError("stdio MCP is missing template_id")
    params = server.get_template_params() if hasattr(server, "get_template_params") else {}
    refs = server.get_secret_refs() if hasattr(server, "get_secret_refs") else []
    return provision(int(server.id), str(template_id), params or {}, refs or [])


def stdio_user_message(exc: Exception) -> str:
    text = str(exc)
    if "secret" in text.lower() or "secret_unresolved" in text:
        return (
            "The Azure DevOps PAT is missing in the mcp-runtime container. "
            "Set AZURE_DEVOPS_PAT in the compose .env and recreate mcp-runtime."
        )
    if "unknown_server" in text or "does not know this server" in text:
        return "The local MCP runtime was restarted. Retry Refresh Tools to start the process again."
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "The stdio MCP timed out while starting (npx may still be downloading the package). Retry in a minute."
    if "closed stdout" in text.lower() or "mcp-server-azuredevops" in text.lower():
        return (
            "The Azure DevOps MCP process exited before it answered. "
            "Retry Refresh Tools; if it fails again, check mcp-runtime logs."
        )
    if len(text) > 160 or any(token in text for token in (";", "|", "$")):
        return "The local MCP runtime failed to start the stdio process."
    return text or "The local MCP runtime failed to start the stdio process."
