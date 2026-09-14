"""Chat completions use case (OpenAI-compatible → Cursor)."""
from __future__ import annotations

import os
from typing import Any

from cursor_adapter.application.ports import CursorAgentRunner, SessionStore
from cursor_adapter.domain.errors import AdapterError
from cursor_adapter.domain.streaming import iter_openai_chunks


def handle_chat_completions(
    body: dict[str, Any],
    headers: dict[str, str],
    *,
    sessions: SessionStore,
    runner: CursorAgentRunner,
) -> tuple[int, dict[str, Any] | list[dict[str, Any]], bool]:
    messages = body.get("messages") or []
    if not isinstance(messages, list):
        return 400, {"error": {"message": "messages must be an array", "code": "invalid_request"}}, False
    workspace = headers.get("X-Loom-Workspace") or body.get("workspace") or os.environ.get("CURSOR_WORKSPACE")
    session_id = headers.get("X-Loom-Session-Id") or body.get("session_id")
    agent_id = headers.get("X-Loom-Agent-Id") or body.get("agent_id")
    stream = bool(body.get("stream"))
    model = body.get("model") or os.environ.get("CURSOR_MODEL") or "composer-2.5"
    tools = body.get("tools") if isinstance(body.get("tools"), list) else None
    try:
        completion = runner.run_prompt(
            messages,
            workspace=workspace,
            session_id=session_id,
            agent_id=agent_id,
            sessions=sessions,
            default_workspace=os.environ.get("CURSOR_WORKSPACE"),
            api_key=os.environ.get("CURSOR_API_KEY"),
            model=os.environ.get("CURSOR_MODEL") or "composer-2.5",
            tools=tools,
        )
    except AdapterError as exc:
        return exc.status, exc.to_body(), False
    if stream:
        text = (completion.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        events = [type("E", (), {"type": "assistant", "message": type("M", (), {"content": [type("B", (), {"type": "text", "text": text})()]})()})()]
        return 200, list(iter_openai_chunks(events, model=model)), True
    return 200, completion, False
