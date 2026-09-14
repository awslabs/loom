"""Shared typed payloads for agent-runtime ports."""
from __future__ import annotations

from typing import TypedDict


class CallerIdentity(TypedDict, total=False):
    """Propagated user claims for MCP outbound calls."""

    subject: str
    agent_id: str
    session_id: str
