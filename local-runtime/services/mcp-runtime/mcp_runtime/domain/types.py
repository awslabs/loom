"""Shared typed payloads for mcp-runtime ports."""
from __future__ import annotations

from typing import TypedDict


class SecretRef(TypedDict, total=False):
    name: str
    backend: str
    ref: str


class HealthInfo(TypedDict, total=False):
    server_id: int
    state: str
    catalog_status: str
    restarts: int
    started_at: str | None
    last_error_code: str | None
    template_id: str
    pid: int | None
