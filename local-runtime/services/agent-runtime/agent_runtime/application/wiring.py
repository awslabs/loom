"""Composition root — default outbound adapters."""
from __future__ import annotations

from agent_runtime.adapters.outbound.litellm_http import LiteLlmGateway
from agent_runtime.adapters.outbound.mcp_http import McpHttpClient
from agent_runtime.adapters.outbound.memory_sessions import MemorySessionStore
from agent_runtime.application.ports import LlmGateway, McpToolsClient, SessionStore

_SESSIONS = MemorySessionStore()


def default_sessions() -> SessionStore:
    return _SESSIONS


def default_llm() -> LlmGateway:
    return LiteLlmGateway()


def default_mcp() -> McpToolsClient:
    return McpHttpClient()
