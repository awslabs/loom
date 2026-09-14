"""Contract validation and pure helpers (no I/O)."""
from __future__ import annotations

import json
import uuid
from typing import Any

from agent_runtime.domain.errors import AgentRuntimeError

CONTRACT_VERSION = "2026-09-local-1"
SUPPORTED_CONTRACTS = frozenset({CONTRACT_VERSION})


def validate_payload(body: dict[str, Any]) -> dict[str, Any]:
    version = body.get("contract_version")
    if version not in SUPPORTED_CONTRACTS:
        raise AgentRuntimeError("unsupported_contract", f"unsupported contract_version {version!r}")
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise AgentRuntimeError("invalid_payload", "prompt is required")
    session_id = body.get("session_id") or str(uuid.uuid4())
    invocation_id = body.get("invocation_id") or str(uuid.uuid4())
    model_id = body.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        raise AgentRuntimeError("invalid_payload", "model_id is required")
    agent = body.get("agent") if isinstance(body.get("agent"), dict) else {}
    options = body.get("options") if isinstance(body.get("options"), dict) else {}
    identity = body.get("identity") if isinstance(body.get("identity"), dict) else {}
    mcp_servers = body.get("mcp_servers") if isinstance(body.get("mcp_servers"), list) else []
    return {
        "contract_version": version,
        "prompt": prompt.strip(),
        "session_id": str(session_id),
        "invocation_id": str(invocation_id),
        "model_id": model_id.strip(),
        "agent": agent,
        "options": {
            "timeout_s": float(options.get("timeout_s") or 300),
            "max_tool_rounds": int(options.get("max_tool_rounds") or 20),
        },
        "identity": {
            "subject": str(identity.get("subject") or ""),
            "agent_id": str(identity.get("agent_id") or agent.get("id") or ""),
            "session_id": str(identity.get("session_id") or session_id),
        },
        "mcp_servers": mcp_servers,
        "approval_policies": body.get("approval_policies") or [],
    }


def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


def tool_name(server_name: str, tool_name_raw: str) -> str:
    safe_server = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in server_name)[:40]
    safe_tool = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in tool_name_raw)[:60]
    return f"{safe_server}__{safe_tool}"


def is_cursor_model(model_id: str) -> bool:
    lowered = model_id.strip().lower()
    return lowered == "cursor-local" or lowered.startswith("cursor_agent/") or lowered.startswith("cursor-")


def assistant_message(completion: dict[str, Any]) -> dict[str, Any]:
    choices = completion.get("choices") or []
    if not choices:
        return {"role": "assistant", "content": ""}
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return {"role": "assistant", "content": ""}
    out = dict(message)
    tool_calls = out.get("tool_calls") or []
    content = out.get("content")
    if not tool_calls and isinstance(content, str) and "tool_calls" in content:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("tool_calls"), list):
            out["tool_calls"] = parsed["tool_calls"]
            out["content"] = parsed.get("content") if isinstance(parsed.get("content"), str) else None
    return out
