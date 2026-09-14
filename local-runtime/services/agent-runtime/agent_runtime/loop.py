"""Compat shim — prefer domain / application / adapters modules."""
from __future__ import annotations

from agent_runtime.adapters.outbound.memory_sessions import MemorySessionStore
from agent_runtime.application.use_cases.invoke import max_sessions, run_invoke as _run_invoke
from agent_runtime.application.wiring import default_llm, default_mcp, default_sessions
from agent_runtime.domain.contract import (
    CONTRACT_VERSION,
    SUPPORTED_CONTRACTS,
    assistant_message as _assistant_message,
    is_cursor_model as _is_cursor_model,
    sse as _sse,
    tool_name as _tool_name,
    validate_payload,
)
from agent_runtime.domain.errors import AgentRuntimeError

# Backward-compatible aliases used by tests / older imports
SESSIONS = default_sessions()


def run_invoke(payload):  # type: ignore[no-untyped-def]
    return _run_invoke(
        payload,
        sessions=default_sessions(),
        llm=default_llm(),
        mcp=default_mcp(),
    )


__all__ = [
    "AgentRuntimeError",
    "CONTRACT_VERSION",
    "MemorySessionStore",
    "SESSIONS",
    "SUPPORTED_CONTRACTS",
    "_assistant_message",
    "_is_cursor_model",
    "_sse",
    "_tool_name",
    "max_sessions",
    "run_invoke",
    "validate_payload",
]
