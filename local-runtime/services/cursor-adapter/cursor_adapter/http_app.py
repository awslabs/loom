"""Compat shim — prefer ``adapters.inbound.http_app``."""
from __future__ import annotations

from typing import Any

from cursor_adapter.adapters.inbound.http_app import *  # noqa: F403
from cursor_adapter.adapters.inbound.http_app import AdapterHandler, bind_address, serve  # noqa: F401
from cursor_adapter.application.use_cases.chat import handle_chat_completions as _handle
from cursor_adapter.application.wiring import default_runner, default_sessions

SESSIONS = default_sessions()


def handle_chat_completions(
    body: dict[str, Any],
    headers: dict[str, str],
) -> tuple[int, dict[str, Any] | list[dict[str, Any]], bool]:
    return _handle(body, headers, sessions=default_sessions(), runner=default_runner())
