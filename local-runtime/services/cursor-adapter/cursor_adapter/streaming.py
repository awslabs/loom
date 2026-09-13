"""Turn Cursor-like SDK messages into OpenAI chat.completion.chunk payloads."""
from __future__ import annotations

from typing import Any, Iterable, Iterator
import json
import time
import uuid


def _assistant_text(message: Any) -> str:
    payload = getattr(message, "message", None) or message
    content = getattr(payload, "content", None)
    if content is None and isinstance(payload, dict):
        content = payload.get("content")
    if isinstance(content, str):
        return content
    texts: list[str] = []
    if isinstance(content, list):
        for block in content:
            kind = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
            if kind == "text":
                texts.append(getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else "") or "")
    return "".join(texts)


def iter_openai_chunks(events: Iterable[Any], *, model: str = "cursor-local") -> Iterator[dict[str, Any]]:
    completion_id = f"chatcmpl-cursor-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    for event in events:
        kind = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
        if kind == "assistant":
            text = _assistant_text(event)
            if not text:
                continue
            yield {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
            }
            continue
        if kind in {"tool", "status", "system"}:
            yield {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                "x_cursor_event": {"type": kind},
            }
    yield {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }


def format_sse(chunk: dict[str, Any]) -> str:
    return f"data: {json.dumps(chunk)}\n\n"
