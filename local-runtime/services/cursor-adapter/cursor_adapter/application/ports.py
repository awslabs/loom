"""Outbound ports for cursor-adapter."""
from __future__ import annotations

from typing import Any, Protocol


class SessionStore(Protocol):
    def make_key(self, tenant: str, agent_id: str, workspace: str, session_id: str) -> str: ...

    def get(self, key: str) -> Any: ...

    def put(self, key: str, cursor_agent_id: str, workspace: str) -> Any: ...

    def lock_for(self, key: str) -> Any: ...


class CursorAgentRunner(Protocol):
    def run_prompt(
        self,
        messages: list[dict[str, Any]],
        *,
        workspace: str | None,
        session_id: str | None,
        agent_id: str | None,
        tenant: str = "local",
        sessions: Any,
        default_workspace: str | None = None,
        api_key: str | None = None,
        model: str = "composer-2.5",
        tools: list[dict[str, Any]] | None = None,
        launch: Any | None = None,
    ) -> dict[str, Any]: ...
