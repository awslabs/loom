"""BFF client for agent-runtime local templates (ADR 0013 / Spec 026 A2)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.local_invoke import agent_runtime_base_url, agent_runtime_token

logger = logging.getLogger(__name__)


class LocalTemplateError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _headers() -> dict[str, str]:
    token = agent_runtime_token()
    if not token:
        raise LocalTemplateError("AGENT_RUNTIME_TOKEN is not configured", status_code=503)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _base() -> str:
    base = agent_runtime_base_url()
    if not base:
        raise LocalTemplateError("AGENT_RUNTIME_URL is not configured", status_code=503)
    return base


def list_local_templates() -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(f"{_base()}/v1/templates", headers=_headers())
    except httpx.HTTPError as exc:
        raise LocalTemplateError(f"agent-runtime unreachable: {exc}", status_code=503) from exc
    if resp.status_code >= 400:
        raise LocalTemplateError(
            f"agent-runtime templates HTTP {resp.status_code}",
            status_code=502,
        )
    payload = resp.json()
    rows = payload.get("templates") if isinstance(payload, dict) else None
    return list(rows) if isinstance(rows, list) else []


def materialize_local_template(
    template_id: str,
    *,
    params: dict[str, Any] | None = None,
    system_prompt_override: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"params": params or {}}
    if system_prompt_override is not None:
        body["system_prompt_override"] = system_prompt_override
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{_base()}/v1/templates/{template_id}/materialize",
                headers=_headers(),
                json=body,
            )
    except httpx.HTTPError as exc:
        raise LocalTemplateError(f"agent-runtime unreachable: {exc}", status_code=503) from exc
    if resp.status_code >= 400:
        detail = "template_error"
        try:
            err = resp.json().get("error") or {}
            detail = str(err.get("message") or detail)
        except Exception:
            pass
        raise LocalTemplateError(detail, status_code=400 if resp.status_code < 500 else 502)
    payload = resp.json()
    config = payload.get("config") if isinstance(payload, dict) else None
    if not isinstance(config, dict):
        raise LocalTemplateError("agent-runtime returned invalid materialize payload", status_code=502)
    return config
