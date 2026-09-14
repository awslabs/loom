"""Run a Cursor Agent. Import of cursor_sdk is deferred so unit tests stay offline."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from cursor_adapter.domain.errors import AdapterError, auth_missing, invalid_workspace, run_failed, from_sdk_error
from cursor_adapter.domain.planner import (
    completion_from_planner_text,
    extract_tools_from_messages,
    planner_system_prompt,
)
from cursor_adapter.adapters.outbound.memory_sessions import SessionManager
from cursor_adapter.domain.translation import translate_messages

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
    tools: list[dict[str, Any]] | None = None,
    launch: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute one Cursor turn. ``launch`` is injected in tests.

    When ``tools`` is non-empty, runs in planner mode: Cursor must return
    OpenAI-shaped tool_calls/content JSON; Loom agent-runtime executes MCP.
    """
    key = require_api_key(api_key)
    cwd = resolve_workspace(workspace, default_workspace)
    embedded_tools, stripped_messages = extract_tools_from_messages(list(messages))
    body_tools = [t for t in (tools or []) if isinstance(t, dict)]
    planner_tools = body_tools or embedded_tools
    working_messages = list(stripped_messages)
    if planner_tools:
        working_messages = [
            {"role": "system", "content": planner_system_prompt(planner_tools)},
            *working_messages,
        ]

    translated = translate_messages(working_messages)
    logger.info(
        "cursor_request model=%s workspace=%s session=%s agent=%s turns=%s planner_tools=%s unsupported=%s",
        model, str(cwd), session_id or "-", agent_id or "-",
        translated["turn_count"], len(planner_tools), translated["unsupported_parts"],
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
            planner_mode=bool(planner_tools),
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
    logger.info(
        "cursor_result status=%s run=%s planner=%s text_len=%s preview=%s",
        status,
        run_id or "-",
        bool(planner_tools),
        len(content),
        content[:120].replace("\n", " "),
    )
    if planner_tools:
        completion = completion_from_planner_text(content, model="cursor-local")
        completion["id"] = run_id or completion["id"]
        completion["x_cursor"] = {
            "agent_id": agent_id_out,
            "run_id": run_id,
            "workspace": str(cwd),
            "unsupported_parts": translated["unsupported_parts"],
            "planner_mode": True,
            "planner_tool_count": len(planner_tools),
        }
        return completion

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
            "planner_mode": False,
        },
    }


def _launch_real(
    *,
    prompt: str,
    api_key: str,
    model: str,
    cwd: str,
    previous_agent_id: str | None,
    planner_mode: bool = False,
) -> dict[str, Any]:
    """Local runtime. Planner mode relies on the prompt contract (JSON tool_calls),
    not Cursor-owned MCP — agent-runtime executes Loom tools (ADR 0005).
    """
    from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

    # Do not pass disallowed_tools: some SDK builds return empty text when the
    # agent cannot use shell/mcp. The planner prompt already forbids those paths.
    _ = planner_mode
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
