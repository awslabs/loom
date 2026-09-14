"""Outbound ports for cursor-adapter."""
from __future__ import annotations

import threading
from typing import Any, Protocol

from cursor_adapter.domain.sessions import SessionRecord

# OpenAI-compatible wire JSON (external boundary — dict[str, Any] is intentional).
JsonObject = dict[str, Any]
ChatMessage = dict[str, Any]


class SessionStore(Protocol):
    def make_key(self, tenant: str, agent_id: str, workspace: str, session_id: str) -> str: ...

    def get(self, key: str) -> SessionRecord | None: ...

    def put(self, key: str, cursor_agent_id: str, workspace: str) -> SessionRecord: ...

    def lock_for(self, key: str) -> threading.Lock: ...


class CursorAgentRunner(Protocol):
    def run_prompt(
        self,
        messages: list[ChatMessage],
        *,
        workspace: str | None,
        session_id: str | None,
        agent_id: str | None,
        tenant: str = "local",
        sessions: SessionStore,
        default_workspace: str | None = None,
        api_key: str | None = None,
        model: str = "composer-2.5",
        tools: list[JsonObject] | None = None,
    ) -> JsonObject: ...
