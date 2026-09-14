"""Session identity value object (domain)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionRecord:
    key: str
    cursor_agent_id: str
    workspace: str
    created_at: float
    last_used_at: float
