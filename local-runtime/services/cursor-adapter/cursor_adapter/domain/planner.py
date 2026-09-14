"""OpenAI-compatible planner mode for cursor-local.

Architecture (ADR 0005): Cursor is only the *model*. agent-runtime owns the
tool loop and calls mcp-runtime. This module turns Cursor free-text into
OpenAI chat.completion shapes (content / tool_calls).
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
TOOLS_START = "<<<loom_openai_tools>>>"
TOOLS_END = "<<<end_loom_openai_tools>>>"
_TOOLS_RE = re.compile(
    re.escape(TOOLS_START) + r"(.*?)" + re.escape(TOOLS_END),
    re.DOTALL,
)


def extract_tools_from_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pull tool schemas embedded by agent-runtime; strip markers from messages."""
    tools: list[dict[str, Any]] = []
    cleaned: list[dict[str, Any]] = []
    for message in messages:
        role = (message.get("role") or "").lower()
        content = message.get("content")
        if role != "system" or not isinstance(content, str) or TOOLS_START not in content:
            cleaned.append(message)
            continue
        for match in _TOOLS_RE.finditer(content):
            raw = match.group(1).strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                tools.extend(item for item in parsed if isinstance(item, dict))
        remainder = _TOOLS_RE.sub("", content).strip()
        if remainder:
            cleaned.append({**message, "content": remainder})
    return tools, cleaned


def _slim_tools_for_prompt(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep names/descriptions; trim huge JSON schemas so the planner stays reliable."""
    slim: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = function.get("name") or tool.get("name")
        if not name:
            continue
        parameters = function.get("parameters") or {"type": "object", "properties": {}}
        # Cap nested schema size
        params_raw = json.dumps(parameters, ensure_ascii=False)
        if len(params_raw) > 800:
            parameters = {"type": "object", "properties": {}, "description": "see Loom catalog; pass a JSON object"}
        slim.append({
            "type": "function",
            "function": {
                "name": str(name),
                "description": str(function.get("description") or name)[:240],
                "parameters": parameters,
            },
        })
    return slim


def planner_system_prompt(tools: list[dict[str, Any]]) -> str:
    catalog = json.dumps(_slim_tools_for_prompt(tools), ensure_ascii=False)
    return (
        "You are an OpenAI-compatible chat model for Loom (planner only).\n"
        "Loom's agent-runtime WILL execute any tool_calls you emit against the "
        "real MCP catalog. Do not use shell, Azure CLI, or claim tools are missing.\n\n"
        f"Tools:\n{catalog}\n\n"
        "Reply with ONLY one JSON object (no markdown, no prose outside JSON):\n"
        '{"tool_calls":[{"id":"call_1","type":"function","function":'
        '{"name":"<exact_name>","arguments":"{}"}}]}\n'
        "or\n"
        '{"content":"<final user-facing answer>"}\n'
    )


def extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    fence = _FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def normalize_tool_calls(raw_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_calls, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, call in enumerate(raw_calls):
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = function.get("name") or call.get("name")
        if not name:
            continue
        arguments = function.get("arguments", call.get("arguments", "{}"))
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)
        elif not isinstance(arguments, str):
            arguments = str(arguments)
        call_id = call.get("id") or f"call_{uuid.uuid4().hex[:8]}_{index}"
        normalized.append({
            "id": str(call_id),
            "type": "function",
            "function": {"name": str(name), "arguments": arguments},
        })
    return normalized


def completion_from_planner_text(text: str, *, model: str = "cursor-local") -> dict[str, Any]:
    """Turn Cursor free-text into an OpenAI chat.completion (content and/or tool_calls)."""
    stripped = (text or "").strip()
    parsed = extract_json_object(stripped)
    message: dict[str, Any] = {"role": "assistant", "content": None}
    finish = "stop"

    if parsed is not None:
        tool_calls = normalize_tool_calls(parsed.get("tool_calls"))
        content = parsed.get("content")
        if tool_calls:
            message["tool_calls"] = tool_calls
            # Content fallback: LiteLLM CustomLLM often drops structured tool_calls.
            message["content"] = json.dumps({"tool_calls": tool_calls}, ensure_ascii=False)
            finish = "tool_calls"
        elif isinstance(content, str) and content.strip():
            message["content"] = content
        elif isinstance(parsed.get("message"), str) and parsed["message"].strip():
            message["content"] = parsed["message"]
        else:
            message["content"] = stripped or None
    elif stripped:
        # Prose fallback (model ignored JSON contract) — still user-visible.
        message["content"] = stripped
    else:
        message["content"] = (
            "Planner returned an empty response. Retry the prompt, or switch to a "
            "non-cursor LiteLLM model for MCP tool use."
        )

    if message.get("content") == "":
        message["content"] = None

    return {
        "id": f"chatcmpl-cursor-planner-{uuid.uuid4().hex[:10]}",
        "object": "chat.completion",
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish,
        }],
    }
