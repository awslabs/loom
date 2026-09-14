"""Outbound ports for the agent runtime."""
from __future__ import annotations

import threading
from typing import Any, Protocol

from agent_runtime.domain.types import CallerIdentity

# LiteLLM / MCP JSON-RPC wire payloads (external boundary).
JsonObject = dict[str, Any]
ChatMessage = dict[str, Any]


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
        messages: list[ChatMessage],
        tools: list[JsonObject],
        session_id: str,
        timeout_s: float,
    ) -> JsonObject: ...


class McpToolsClient(Protocol):
    def load_tools(
        self,
        mcp_servers: list[JsonObject],
        identity: CallerIdentity,
        *,
        timeout_s: float,
    ) -> tuple[list[JsonObject], dict[str, tuple[JsonObject, str]]]: ...

    def call_tool(
        self,
        server: JsonObject,
        identity: CallerIdentity,
        *,
        name: str,
        arguments: JsonObject,
        timeout_s: float,
        req_id: int = 1,
    ) -> JsonObject: ...
