"""Proxy from Loom BFF to mcp-hub management API (extension store)."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def mcp_hub_base() -> str:
    return os.environ.get("MCP_HUB_INTERNAL_URL", "http://mcp-hub:8790").rstrip("/")


def service_token() -> str:
    return os.environ.get("MCP_HUB_SERVICE_TOKEN", "").strip()


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    token = service_token()
    if not token:
        return 503, {"detail": "hub_service_token_unset"}
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{mcp_hub_base()}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            if resp.status == 204 or not raw:
                return resp.status, {}
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": "hub_error"}
        err = payload.get("error")
        if isinstance(err, dict) and "message" in err:
            payload = {"error": err["message"], "detail": err["message"]}
        return exc.code, payload if isinstance(payload, dict) else {"detail": str(payload)}
    except Exception as exc:
        logger.warning("mcp-hub unreachable: %s", exc)
        return 502, {"detail": "mcp_hub_unreachable"}


def list_clients(status: str | None = None) -> tuple[int, dict[str, Any]]:
    path = "/v1/clients"
    if status:
        path = f"{path}?status={status}"
    return _request("GET", path)


def get_client(slug: str) -> tuple[int, dict[str, Any]]:
    return _request("GET", f"/v1/clients/{slug}")


def patch_client(slug: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return _request("PATCH", f"/v1/clients/{slug}", body)


def put_grants(slug: str, grants: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    return _request("PUT", f"/v1/clients/{slug}/grants", {"grants": grants})


def delete_client(slug: str) -> tuple[int, dict[str, Any]]:
    return _request("DELETE", f"/v1/clients/{slug}")
