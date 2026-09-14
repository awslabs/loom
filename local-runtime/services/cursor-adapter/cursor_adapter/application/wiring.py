"""Composition root."""
from __future__ import annotations

from cursor_adapter.adapters.outbound.memory_sessions import SessionManager
from cursor_adapter.adapters.outbound.sdk_runner import run_prompt as sdk_run_prompt
from cursor_adapter.application.ports import CursorAgentRunner, SessionStore

_SESSIONS = SessionManager()


class SdkCursorAgentRunner:
    """Outbound adapter implementing ``CursorAgentRunner``."""

    def run_prompt(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        return sdk_run_prompt(messages, **kwargs)


def default_sessions() -> SessionStore:
    return _SESSIONS


def default_runner() -> CursorAgentRunner:
    return SdkCursorAgentRunner()
