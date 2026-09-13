"""Translate OpenAI-compatible messages into a Cursor Agent prompt."""
from __future__ import annotations

from typing import Any


def _text_from_content(content: Any, unsupported: list[str]) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind in (None, "text") and item.get("text"):
                parts.append(str(item["text"]))
            elif kind == "image_url":
                unsupported.append("image_url")
            else:
                unsupported.append(str(kind or "unknown_part"))
        return "\n".join(parts)
    return str(content)


def _tool_calls_block(message: dict[str, Any]) -> str:
    calls = message.get("tool_calls") or []
    if not calls:
        function_call = message.get("function_call")
        if isinstance(function_call, dict):
            calls = [{"function": function_call}]
    lines: list[str] = []
    for call in calls:
        function = (call or {}).get("function") or {}
        name = function.get("name") or "unknown"
        arguments = function.get("arguments") or ""
        call_id = (call or {}).get("id") or ""
        prefix = f"id={call_id} " if call_id else ""
        lines.append(f"[tool_call {prefix}name={name}] {arguments}".rstrip())
    return "\n".join(lines)


def translate_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a Cursor prompt plus metadata. Never concatenates blindly.

    system parts become a preamble. user/assistant turns keep role labels.
    tool calls and tool results are kept as explicit blocks so the Cursor
    Agent sees that work already happened (it will not re-run Loom tools).
    """
    unsupported: list[str] = []
    system_parts: list[str] = []
    turns: list[str] = []
    last_user = ""

    for message in messages:
        role = (message.get("role") or "user").lower()
        text = _text_from_content(message.get("content"), unsupported)
        if role == "system":
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            tool_id = message.get("tool_call_id") or ""
            label = f"id={tool_id} " if tool_id else ""
            turns.append(f"[tool_result {label}]{text}")
            continue
        if role == "assistant":
            block = _tool_calls_block(message)
            body = "\n".join(p for p in (text, block) if p)
            turns.append(f"Assistant: {body}" if body else "Assistant:")
            continue
        last_user = text
        turns.append(f"User: {text}")

    preamble = "\n\n".join(system_parts)
    history = "\n\n".join(turns)
    prompt_parts = [p for p in (preamble, history) if p]
    return {
        "prompt": "\n\n".join(prompt_parts).strip(),
        "preamble": preamble,
        "last_user": last_user,
        "unsupported_parts": list(dict.fromkeys(unsupported)),
        "turn_count": len(turns),
    }
