"""HTTP client to Loom BFF for Hub session and tools."""
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


def _request(method: str, path: str, body: dict[str, Any] | None = None, extra_headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
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
            **(extra_headers or {}),
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


def introspect(hub_session_token: str) -> dict[str, Any]:
    status, payload = _request("POST", "/api/mcp/hub/sessions/introspect", {"hub_session_token": hub_session_token})
    if status != 200:
        return {"active": False}
    return payload


def allowlist(hub_session_id: str) -> tuple[int, dict[str, Any]]:
    return _request(
        "GET",
        "/api/mcp/hub/allowlist",
        None,
        {"X-Loom-Hub-Session-Id": hub_session_id},
    )


def tools_call(hub_session_id: str, tool_name: str, arguments: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return _request(
        "POST",
        "/api/mcp/hub/tools/call",
        {
            "hub_session_id": hub_session_id,
            "tool_name": tool_name,
            "arguments": arguments or {},
        },
    )
