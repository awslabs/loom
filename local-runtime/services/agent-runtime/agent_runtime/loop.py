"""OpenAI-compatible chat + MCP HTTP tool loop."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Iterator

import httpx

logger = logging.getLogger("agent_runtime")

CONTRACT_VERSION = "2026-09-local-1"
SUPPORTED_CONTRACTS = frozenset({CONTRACT_VERSION})


class AgentRuntimeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SessionRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel: dict[str, threading.Event] = {}

    def begin(self, session_id: str) -> threading.Event:
        with self._lock:
            event = threading.Event()
            self._cancel[session_id] = event
            return event

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            event = self._cancel.get(session_id)
            if event is None:
                return False
            event.set()
            return True

    def end(self, session_id: str) -> None:
        with self._lock:
            self._cancel.pop(session_id, None)

    def active_count(self) -> int:
        with self._lock:
            return len(self._cancel)


SESSIONS = SessionRegistry()


def litellm_base_url() -> str:
    return os.environ.get("LITELLM_BASE_URL", "http://litellm:4000").rstrip("/")


def litellm_api_key() -> str:
    return os.environ.get("LITELLM_API_KEY", os.environ.get("LITELLM_MASTER_KEY", "")).strip()


def mcp_runtime_token() -> str:
    return os.environ.get("MCP_RUNTIME_TOKEN", "").strip()


def max_sessions() -> int:
    return int(os.environ.get("AGENT_RUNTIME_MAX_SESSIONS", "4"))


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


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


def _mcp_headers(server: dict[str, Any], identity: dict[str, str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    auth = server.get("auth") if isinstance(server.get("auth"), dict) else {}
    auth_type = (auth.get("type") or "none").lower()
    if auth_type == "service_bearer":
        token = auth.get("token") or mcp_runtime_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        header_name = auth.get("api_key_header_name") or "x-api-key"
        value = auth.get("api_key") or ""
        if value:
            headers[header_name] = value
    elif auth_type in ("loom", "none") and mcp_runtime_token():
        # Stdio facade on mcp-runtime always expects the service token.
        headers["Authorization"] = f"Bearer {mcp_runtime_token()}"
    if identity.get("subject"):
        headers["X-Loom-Subject"] = identity["subject"]
    if identity.get("agent_id"):
        headers["X-Loom-Agent-Id"] = identity["agent_id"]
    if identity.get("session_id"):
        headers["X-Loom-Session-Id"] = identity["session_id"]
    allowed = server.get("allowed_tools")
    if allowed is None:
        headers["X-Loom-Allowed-Tools"] = "*"
    elif isinstance(allowed, list):
        headers["X-Loom-Allowed-Tools"] = ",".join(str(item) for item in allowed)
    return headers


def _mcp_jsonrpc(
    client: httpx.Client,
    server: dict[str, Any],
    identity: dict[str, str],
    method: str,
    params: dict[str, Any] | None = None,
    req_id: int = 1,
) -> dict[str, Any]:
    url = server.get("endpoint_url")
    if not isinstance(url, str) or not url.strip():
        raise AgentRuntimeError("invalid_payload", f"mcp server {server.get('name')!r} missing endpoint_url")
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    try:
        response = client.post(url, json=body, headers=_mcp_headers(server, identity))
    except httpx.HTTPError as exc:
        raise AgentRuntimeError("mcp_unreachable", f"mcp unreachable: {exc}") from exc
    if response.status_code >= 400:
        detail = ""
        try:
            err_body = response.json()
            if isinstance(err_body, dict):
                err = err_body.get("error")
                if isinstance(err, dict) and err.get("message"):
                    detail = f": {err.get('message')}"
                elif err_body.get("message"):
                    detail = f": {err_body.get('message')}"
        except ValueError:
            detail = ""
        if response.status_code == 404:
            raise AgentRuntimeError(
                "mcp_unreachable",
                f"mcp HTTP 404{detail} (stdio child not registered — Refresh Tools or retry invoke)",
            )
        raise AgentRuntimeError("mcp_unreachable", f"mcp HTTP {response.status_code}{detail}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AgentRuntimeError("mcp_unreachable", "mcp returned non-JSON") from exc
    if not isinstance(payload, dict):
        raise AgentRuntimeError("mcp_unreachable", "mcp returned invalid envelope")
    return payload


def _tool_name(server_name: str, tool_name: str) -> str:
    safe_server = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in server_name)[:40]
    safe_tool = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in tool_name)[:60]
    return f"{safe_server}__{safe_tool}"


def _load_tools(
    client: httpx.Client,
    mcp_servers: list[dict[str, Any]],
    identity: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, tuple[dict[str, Any], str]]]:
    """Return OpenAI tool defs and map openai_name → (server, original_tool_name)."""
    openai_tools: list[dict[str, Any]] = []
    mapping: dict[str, tuple[dict[str, Any], str]] = {}
    for server in mcp_servers:
        name = str(server.get("name") or "mcp")
        listed = _mcp_jsonrpc(client, server, identity, "tools/list")
        if "error" in listed:
            message = (listed.get("error") or {}).get("message") if isinstance(listed.get("error"), dict) else listed.get("error")
            raise AgentRuntimeError("mcp_unreachable", f"tools/list failed for {name}: {message}")
        tools = ((listed.get("result") or {}).get("tools")) or []
        allow = server.get("allowed_tools")
        allow_set = {str(item) for item in allow} if isinstance(allow, list) else None
        for tool in tools:
            tool_name = str(tool.get("name") or "")
            if not tool_name:
                continue
            if allow_set is not None and tool_name not in allow_set:
                continue
            keyed = _tool_name(name, tool_name)
            mapping[keyed] = (server, tool_name)
            schema = tool.get("inputSchema") or tool.get("input_schema") or {"type": "object", "properties": {}}
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": keyed,
                    "description": (tool.get("description") or f"{name}: {tool_name}")[:500],
                    "parameters": schema,
                },
            })
    return openai_tools, mapping


def _chat_completion(
    client: httpx.Client,
    model_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    session_id: str,
) -> dict[str, Any]:
    key = litellm_api_key()
    if not key:
        raise AgentRuntimeError("model_auth", "LITELLM_API_KEY is not set")
    url = f"{litellm_base_url()}/v1/chat/completions"
    outbound = list(messages)
    # LiteLLM CustomLLM often drops `tools` before cursor_handler. Embed a
    # marker the cursor-adapter strips so planner mode still sees schemas.
    if tools and _is_cursor_model(model_id):
        outbound = [
            {
                "role": "system",
                "content": (
                    "<<<loom_openai_tools>>>\n"
                    f"{json.dumps(tools)}\n"
                    "<<<end_loom_openai_tools>>>"
                ),
            },
            *outbound,
        ]
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": outbound,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Loom-Session-Id": session_id,
    }
    try:
        response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise AgentRuntimeError("model_unreachable", f"LiteLLM unreachable: {exc}") from exc
    if response.status_code in (401, 403):
        raise AgentRuntimeError("model_auth", f"LiteLLM auth failed HTTP {response.status_code}")
    if response.status_code >= 400:
        raise AgentRuntimeError(
            "model_unreachable",
            f"LiteLLM HTTP {response.status_code}: {response.text[:300]}",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise AgentRuntimeError("model_unreachable", "LiteLLM returned non-JSON") from exc
    if not isinstance(body, dict):
        raise AgentRuntimeError("model_unreachable", "LiteLLM returned invalid body")
    return body


def _is_cursor_model(model_id: str) -> bool:
    lowered = model_id.strip().lower()
    return lowered == "cursor-local" or lowered.startswith("cursor_agent/") or lowered.startswith("cursor-")


def _assistant_message(completion: dict[str, Any]) -> dict[str, Any]:
    choices = completion.get("choices") or []
    if not choices:
        return {"role": "assistant", "content": ""}
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return {"role": "assistant", "content": ""}
    out = dict(message)
    tool_calls = out.get("tool_calls") or []
    content = out.get("content")
    # Recover tool_calls if a proxy dropped the structured field but left JSON in content.
    if not tool_calls and isinstance(content, str) and "tool_calls" in content:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("tool_calls"), list):
            out["tool_calls"] = parsed["tool_calls"]
            out["content"] = parsed.get("content") if isinstance(parsed.get("content"), str) else None
    return out


def run_invoke(payload: dict[str, Any]) -> Iterator[bytes]:
    """Yield SSE bytes for one local invoke."""
    started = time.time()
    session_id = payload["session_id"]
    invocation_id = payload["invocation_id"]
    cancel = SESSIONS.begin(session_id)
    try:
        if SESSIONS.active_count() > max_sessions():
            yield _sse("error", {"message": "too many active sessions", "code": "internal"})
            return

        yield _sse("session_start", {
            "session_id": session_id,
            "invocation_id": invocation_id,
            "client_invoke_time": started,
            "token_source": "local-agent-runtime",
            "delegation_mode": "m2m",
        })

        system_prompt = payload["agent"].get("system_prompt")
        messages: list[dict[str, Any]] = []
        if isinstance(system_prompt, str) and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": payload["prompt"]})

        timeout = httpx.Timeout(payload["options"]["timeout_s"], connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            tools, mapping = _load_tools(client, payload["mcp_servers"], payload["identity"])
            text_parts: list[str] = []
            for _round in range(payload["options"]["max_tool_rounds"] + 1):
                if cancel.is_set():
                    yield _sse("error", {"message": "cancelled", "code": "cancelled"})
                    return
                if time.time() - started > payload["options"]["timeout_s"]:
                    yield _sse("error", {"message": "invoke timed out", "code": "timeout"})
                    return

                completion = _chat_completion(
                    client,
                    payload["model_id"],
                    messages,
                    tools,
                    session_id,
                )
                message = _assistant_message(completion)
                tool_calls = message.get("tool_calls") or []
                content = message.get("content")
                if isinstance(content, str) and content:
                    # Skip JSON tool_calls fallback so the UI does not show raw protocol.
                    if not (tool_calls and content.lstrip().startswith("{") and "tool_calls" in content):
                        text_parts.append(content)
                        yield _sse("chunk", {"text": content})

                if not tool_calls:
                    if tools and not text_parts and not (isinstance(content, str) and content.strip()):
                        yield _sse("error", {
                            "message": (
                                "Model returned no text and no tool_calls while MCP tools "
                                "were available. Retry or use a non-cursor LiteLLM model."
                            ),
                            "code": "internal",
                        })
                        return
                    break

                messages.append({
                    "role": "assistant",
                    "content": content if isinstance(content, str) else None,
                    "tool_calls": tool_calls,
                })
                for call in tool_calls:
                    if cancel.is_set():
                        yield _sse("error", {"message": "cancelled", "code": "cancelled"})
                        return
                    fn = call.get("function") or {}
                    keyed = str(fn.get("name") or "")
                    call_id = str(call.get("id") or keyed)
                    if keyed not in mapping:
                        yield _sse("error", {
                            "message": f"tool denied or unknown: {keyed}",
                            "code": "mcp_denied",
                        })
                        return
                    server, original = mapping[keyed]
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except json.JSONDecodeError:
                        arguments = {}
                    if not isinstance(arguments, dict):
                        arguments = {}
                    allow = server.get("allowed_tools")
                    if isinstance(allow, list) and original not in allow:
                        yield _sse("error", {
                            "message": f"tool denied: {original}",
                            "code": "mcp_denied",
                        })
                        return
                    yield _sse("chunk", {"text": f"\n[tool:{original}]\n"})
                    result = _mcp_jsonrpc(
                        client,
                        server,
                        payload["identity"],
                        "tools/call",
                        {"name": original, "arguments": arguments},
                        req_id=abs(hash(call_id)) % 10_000_000 or 1,
                    )
                    if "error" in result:
                        err = result.get("error")
                        err_text = json.dumps(err)[:800]
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": err_text,
                        })
                        continue
                    tool_result = result.get("result") or {}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(tool_result)[:8000],
                    })
            else:
                yield _sse("error", {
                    "message": "max tool rounds exceeded",
                    "code": "internal",
                })
                return

        full = "".join(text_parts)
        done = time.time()
        yield _sse("session_end", {
            "session_id": session_id,
            "invocation_id": invocation_id,
            "client_invoke_time": started,
            "client_done_time": done,
            "client_duration_ms": round((done - started) * 1000, 3),
            "input_tokens": max(1, len(payload["prompt"].split())),
            "output_tokens": max(1, len(full.split()) if full else 1),
            "estimated_cost": 0,
        })
    except AgentRuntimeError as exc:
        logger.warning("invoke failed code=%s: %s", exc.code, exc.message)
        yield _sse("error", {"message": exc.message, "code": exc.code})
    except Exception:
        logger.exception("invoke internal error")
        yield _sse("error", {"message": "internal error", "code": "internal"})
    finally:
        SESSIONS.end(session_id)
