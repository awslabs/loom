"""HTTP client to Loom BFF for materialize/call (service token + user claims)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def loom_base() -> str:
    return os.environ.get("LOOM_BACKEND_URL", "http://backend:8000").rstrip("/")


def service_token() -> str:
    return os.environ.get("MCP_HUB_SERVICE_TOKEN", "").strip()


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    token = service_token()
    if not token:
        return 503, {"error": "hub_service_token_unset"}
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{loom_base()}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": "upstream_error"}
        return exc.code, payload if isinstance(payload, dict) else {"detail": str(payload)}
    except Exception:
        return 502, {"detail": "loom_unreachable"}


def materialize_allowlist(
    *,
    subject: str,
    groups: list[str],
    connection_id: str,
    mcp_client_slug: str,
    client_status: str,
    grants: list[dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    return _request(
        "POST",
        "/api/mcp/hub/materialize-allowlist",
        {
            "subject": subject,
            "groups": groups,
            "connection_id": connection_id,
            "mcp_client_slug": mcp_client_slug,
            "client_status": client_status,
            "grants": grants,
        },
    )


def tools_call(
    *,
    subject: str,
    groups: list[str],
    tool_name: str,
    arguments: dict[str, Any],
    server_id: int | None = None,
    original_tool_name: str | None = None,
) -> tuple[int, dict[str, Any]]:
    body: dict[str, Any] = {
        "subject": subject,
        "groups": groups,
        "tool_name": tool_name,
        "arguments": arguments or {},
    }
    if server_id is not None:
        body["server_id"] = server_id
    if original_tool_name is not None:
        body["original_tool_name"] = original_tool_name
    return _request("POST", "/api/mcp/hub/tools/call", body)
