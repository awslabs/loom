"""Outbound ports for the agent runtime."""
from __future__ import annotations

import threading
from typing import Any, Protocol


class SessionStore(Protocol):
    def begin(self, session_id: str) -> threading.Event: ...

    def cancel(self, session_id: str) -> bool: ...

    def end(self, session_id: str) -> None: ...

    def active_count(self) -> int: ...


class LlmGateway(Protocol):
    def chat_completion(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        session_id: str,
        timeout_s: float,
    ) -> dict[str, Any]: ...


class McpToolsClient(Protocol):
    def load_tools(
        self,
        mcp_servers: list[dict[str, Any]],
        identity: dict[str, str],
        *,
        timeout_s: float,
    ) -> tuple[list[dict[str, Any]], dict[str, tuple[dict[str, Any], str]]]: ...

    def call_tool(
        self,
        server: dict[str, Any],
        identity: dict[str, str],
        *,
        name: str,
        arguments: dict[str, Any],
        timeout_s: float,
        req_id: int = 1,
    ) -> dict[str, Any]: ...
