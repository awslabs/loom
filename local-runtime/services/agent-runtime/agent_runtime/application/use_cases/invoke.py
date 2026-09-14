"""Invoke use case — SSE agent loop over LLM + MCP tools."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Iterator

from agent_runtime.application.ports import LlmGateway, McpToolsClient, SessionStore
from agent_runtime.domain.contract import assistant_message, sse
from agent_runtime.domain.errors import AgentRuntimeError

logger = logging.getLogger("agent_runtime")


def max_sessions() -> int:
    return int(os.environ.get("AGENT_RUNTIME_MAX_SESSIONS", "4"))


def run_invoke(
    payload: dict[str, Any],
    *,
    sessions: SessionStore,
    llm: LlmGateway,
    mcp: McpToolsClient,
) -> Iterator[bytes]:
    """Yield SSE bytes for one local invoke."""
    started = time.time()
    session_id = payload["session_id"]
    invocation_id = payload["invocation_id"]
    timeout_s = float(payload["options"]["timeout_s"])
    cancel = sessions.begin(session_id)
    try:
        if sessions.active_count() > max_sessions():
            yield sse("error", {"message": "too many active sessions", "code": "internal"})
            return

        yield sse("session_start", {
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

        tools, mapping = mcp.load_tools(
            payload["mcp_servers"],
            payload["identity"],
            timeout_s=timeout_s,
        )
        text_parts: list[str] = []
        for _round in range(payload["options"]["max_tool_rounds"] + 1):
            if cancel.is_set():
                yield sse("error", {"message": "cancelled", "code": "cancelled"})
                return
            if time.time() - started > timeout_s:
                yield sse("error", {"message": "invoke timed out", "code": "timeout"})
                return

            completion = llm.chat_completion(
                model_id=payload["model_id"],
                messages=messages,
                tools=tools,
                session_id=session_id,
                timeout_s=timeout_s,
            )
            message = assistant_message(completion)
            tool_calls = message.get("tool_calls") or []
            content = message.get("content")
            if isinstance(content, str) and content:
                if not (tool_calls and content.lstrip().startswith("{") and "tool_calls" in content):
                    text_parts.append(content)
                    yield sse("chunk", {"text": content})

            if not tool_calls:
                if tools and not text_parts and not (isinstance(content, str) and content.strip()):
                    yield sse("error", {
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
                    yield sse("error", {"message": "cancelled", "code": "cancelled"})
                    return
                fn = call.get("function") or {}
                keyed = str(fn.get("name") or "")
                call_id = str(call.get("id") or keyed)
                if keyed not in mapping:
                    yield sse("error", {
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
                    yield sse("error", {
                        "message": f"tool denied: {original}",
                        "code": "mcp_denied",
                    })
                    return
                yield sse("chunk", {"text": f"\n[tool:{original}]\n"})
                result = mcp.call_tool(
                    server,
                    payload["identity"],
                    name=original,
                    arguments=arguments,
                    timeout_s=timeout_s,
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
            yield sse("error", {
                "message": "max tool rounds exceeded",
                "code": "internal",
            })
            return

        full = "".join(text_parts)
        done = time.time()
        yield sse("session_end", {
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
        yield sse("error", {"message": exc.message, "code": exc.code})
    except Exception:
        logger.exception("invoke internal error")
        yield sse("error", {"message": "internal error", "code": "internal"})
    finally:
        sessions.end(session_id)
