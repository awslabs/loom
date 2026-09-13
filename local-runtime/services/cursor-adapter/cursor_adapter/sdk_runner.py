"""Run a Cursor Agent. Import of cursor_sdk is deferred so unit tests stay offline."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from cursor_adapter.errors import AdapterError, auth_missing, invalid_workspace, run_failed, from_sdk_error
from cursor_adapter.sessions import SessionManager
from cursor_adapter.translation import translate_messages

logger = logging.getLogger("cursor_adapter")


def resolve_workspace(requested: str | None, default: str | None) -> Path:
    raw = (requested or default or "").strip()
    if not raw:
        raise AdapterError(400, "invalid_workspace", "invalid_workspace")
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise invalid_workspace()
    return path.resolve()


def require_api_key(explicit: str | None = None) -> str:
    key = (explicit or os.environ.get("CURSOR_API_KEY") or "").strip()
    if not key:
        raise auth_missing()
    return key


def run_prompt(
    messages: list[dict[str, Any]],
    *,
    workspace: str | None,
    session_id: str | None,
    agent_id: str | None,
    tenant: str = "local",
    sessions: SessionManager,
    default_workspace: str | None = None,
    api_key: str | None = None,
    model: str = "composer-2.5",
    launch: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute one Cursor turn. ``launch`` is injected in tests.

    Returns an OpenAI-shaped completion dict. Distinguishes startup failures
    (raised AdapterError) from a run that started and failed (502 + run_id).
    """
    key = require_api_key(api_key)
    cwd = resolve_workspace(workspace, default_workspace)
    translated = translate_messages(messages)
    logger.info(
        "cursor_request model=%s workspace=%s session=%s agent=%s turns=%s unsupported=%s",
        model, str(cwd), session_id or "-", agent_id or "-",
        translated["turn_count"], translated["unsupported_parts"],
    )

    if launch is None:
        launch = _launch_real

    session_key = None
    previous_id = None
    if session_id:
        session_key = sessions.make_key(tenant, agent_id or "-", str(cwd), session_id)
        existing = sessions.get(session_key)
        if existing is not None:
            previous_id = existing.cursor_agent_id

    try:
        result = launch(
            prompt=translated["prompt"],
            api_key=key,
            model=model,
            cwd=str(cwd),
            previous_agent_id=previous_id,
        )
    except AdapterError:
        raise
    except Exception as exc:
        raise from_sdk_error(exc) from exc

    status = result.get("status")
    agent_id_out = result.get("agent_id") or previous_id or ""
    run_id = result.get("run_id")
    if session_key and agent_id_out:
        sessions.put(session_key, agent_id_out, str(cwd))

    if status == "error":
        raise run_failed(run_id)

    content = result.get("text") or ""
    return {
        "id": run_id or "chatcmpl-cursor-local",
        "object": "chat.completion",
        "model": "cursor-local",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "x_cursor": {
            "agent_id": agent_id_out,
            "run_id": run_id,
            "workspace": str(cwd),
            "unsupported_parts": translated["unsupported_parts"],
        },
    }


def _launch_real(
    *,
    prompt: str,
    api_key: str,
    model: str,
    cwd: str,
    previous_agent_id: str | None,
) -> dict[str, Any]:
    """Local runtime, explicit cwd, explicit api_key. Bridge for async servers.

    Uses the sync one-shot API when there is no prior agent (disposes for us).
    Follow-ups resume the stored id. MCP inline is not persisted across resume.
    """
    from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

    options = AgentOptions(
        api_key=api_key,
        model=model,
        local=LocalAgentOptions(cwd=cwd),
    )
    try:
        if previous_agent_id:
            with Agent.resume(previous_agent_id, options) as agent:
                run = agent.send(prompt)
                result = run.wait()
                return {
                    "status": result.status,
                    "text": getattr(result, "result", None) or getattr(result, "text", None) or "",
                    "agent_id": getattr(agent, "agent_id", None) or previous_agent_id,
                    "run_id": getattr(result, "id", None),
                }
        result = Agent.prompt(prompt, options)
        return {
            "status": result.status,
            "text": getattr(result, "result", None) or getattr(result, "text", None) or "",
            "agent_id": getattr(result, "agent_id", None),
            "run_id": getattr(result, "id", None),
        }
    except CursorAgentError:
        raise
