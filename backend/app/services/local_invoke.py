"""Local-dev invoke path: Loom backend → agent-runtime (or LiteLLM fallback).

Only agents with source='local' use this. Deployed/harness/register agents
keep the existing AgentCore runtime path.

When AGENT_RUNTIME_URL is set, the backend is a BFF: it authorizes, mounts the
spec-011 payload, and proxies SSE from agent-runtime. Otherwise it keeps the
legacy in-process LiteLLM shortcut (no MCP tools).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, AsyncGenerator

import httpx
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.invocation import Invocation
from app.models.session import InvocationSession
from app.services.litellm import get_litellm_proxy_config

logger = logging.getLogger(__name__)

CONTRACT_VERSION = "2026-09-local-1"


class LocalInvokeError(Exception):
    """LiteLLM proxy / agent-runtime is missing or rejected the request."""


def format_sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def is_local_agent(agent: Agent) -> bool:
    return (agent.source or "") == "local"


def agent_runtime_base_url() -> str:
    return os.getenv("AGENT_RUNTIME_URL", "").strip().rstrip("/")


def agent_runtime_token() -> str:
    return os.getenv("AGENT_RUNTIME_TOKEN", "").strip()


def mcp_runtime_token() -> str:
    return os.getenv("MCP_RUNTIME_TOKEN", "").strip()


def _agent_config(agent: Agent) -> dict[str, Any]:
    for entry in agent.config_entries:
        if entry.key == "AGENT_CONFIG_JSON" and entry.value:
            try:
                parsed = json.loads(entry.value)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                return {}
    return {}


def resolve_local_model_id(agent: Agent, runtime_model_id: str | None) -> str:
    if runtime_model_id:
        return runtime_model_id
    config = _agent_config(agent)
    model_id = config.get("model_id")
    if isinstance(model_id, str) and model_id:
        return model_id
    allowed = agent.get_allowed_model_ids()
    if allowed:
        return allowed[0]
    raise LocalInvokeError("Local agent has no model_id configured")


def build_chat_messages(agent: Agent, prompt: str) -> list[dict[str, str]]:
    config = _agent_config(agent)
    system_prompt = config.get("system_prompt")
    messages: list[dict[str, str]] = []
    if isinstance(system_prompt, str) and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


def parse_openai_sse_line(line: str) -> str | None:
    """Extract incremental text from one OpenAI-compatible SSE line."""
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return None
    if stripped.startswith("data:"):
        stripped = stripped[5:].strip()
    if not stripped or stripped == "[DONE]":
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return extract_completion_text(payload)


def extract_completion_text(payload: dict[str, Any]) -> str | None:
    """Extract assistant text from a non-streaming OpenAI-compatible body."""
    choices = payload.get("choices") or []
    if not choices:
        return None
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content:
        return content
    delta = choices[0].get("delta") or {}
    delta_content = delta.get("content")
    if isinstance(delta_content, str) and delta_content:
        return delta_content
    text = choices[0].get("text")
    if isinstance(text, str) and text:
        return text
    return None


def enrich_mcp_servers_for_runtime(servers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Attach service bearer for mcp-runtime facades; never send user JWT."""
    token = mcp_runtime_token()
    enriched: list[dict[str, Any]] = []
    for server in servers or []:
        entry = dict(server)
        auth = dict(entry.get("auth") or {})
        url = str(entry.get("endpoint_url") or "")
        auth_type = (auth.get("type") or "").lower()
        needs_runtime_token = (
            "mcp-runtime" in url
            or auth_type in ("service_bearer", "loom")
        )
        if needs_runtime_token and token:
            entry["auth"] = {"type": "service_bearer", "token": token}
        elif auth:
            entry["auth"] = auth
        enriched.append(entry)
    return enriched


async def stream_litellm_text(
    *,
    base_url: str,
    api_key: str,
    model_id: str,
    messages: list[dict[str, str]],
    session_id: str,
) -> AsyncGenerator[str, None]:
    """Fetch a completion from LiteLLM and yield it as UI chunks.

    Always uses stream=false. This LiteLLM build turns mock_response +
    stream=true into a coroutine that its own streaming handler cannot
    iterate ('coroutine object is not an iterator').
    """
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Loom-Session-Id": session_id,
    }
    payload = {
        "model": model_id,
        "messages": messages,
        "stream": False,
    }
    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            body = response.text
            if "cursor_adapter_unavailable" in body:
                raise LocalInvokeError(
                    "Cursor adapter is not running. "
                    "Use model orientador-academico, or start the cursor-adapter service."
                )
            if "cursor_auth_missing" in body:
                raise LocalInvokeError(
                    "cursor-local needs CURSOR_API_KEY in the repo-root .env. "
                    "Copy .env.example, set the key from https://cursor.com/dashboard/integrations, "
                    "then run: docker compose up -d --force-recreate cursor-adapter. "
                    "Or switch the chat model to orientador-academico."
                )
            raise LocalInvokeError(
                f"LiteLLM returned HTTP {response.status_code}: {body[:500]}"
            )
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise LocalInvokeError(
                f"LiteLLM returned non-JSON body: {response.text[:200]}"
            ) from exc
    text = extract_completion_text(body if isinstance(body, dict) else {})
    if text:
        yield text


async def _proxy_agent_runtime_sse(
    *,
    payload: dict[str, Any],
) -> AsyncGenerator[str, None]:
    base = agent_runtime_base_url()
    token = agent_runtime_token()
    if not base:
        raise LocalInvokeError("AGENT_RUNTIME_URL is not configured")
    if not token:
        raise LocalInvokeError("AGENT_RUNTIME_TOKEN is not configured")
    url = f"{base}/v1/invoke"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    timeout = httpx.Timeout(float((payload.get("options") or {}).get("timeout_s") or 300) + 30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise LocalInvokeError(
                    f"agent-runtime HTTP {response.status_code}: {body[:500]}"
                )
            async for line in response.aiter_lines():
                # Re-emit SSE lines; blank line ends an event.
                yield line + "\n"


async def invoke_local_agent_stream(
    agent: Agent,
    session: InvocationSession,
    invocation: Invocation,
    db: Session,
    client_invoke_time: float,
    prompt: str,
    runtime_model_id: str | None = None,
    dynamic_mcp_servers: list[dict[str, Any]] | None = None,
    subject: str | None = None,
) -> AsyncGenerator[str, None]:
    """Yield SSE events: session_start, chunk, session_end (or error)."""
    session_id = session.session_id
    invocation_id = invocation.invocation_id
    invocation.client_invoke_time = client_invoke_time
    invocation.status = "streaming"
    session.status = "streaming"
    db.commit()

    # Prefer agent-runtime BFF when configured (ADR 0005).
    if agent_runtime_base_url():
        config = _agent_config(agent)
        try:
            model_id = resolve_local_model_id(agent, runtime_model_id)
            system_prompt = config.get("system_prompt")
            payload = {
                "contract_version": CONTRACT_VERSION,
                "prompt": prompt,
                "session_id": session_id,
                "invocation_id": invocation_id,
                "agent": {
                    "id": agent.id,
                    "name": agent.name,
                    "system_prompt": system_prompt if isinstance(system_prompt, str) else None,
                },
                "model_id": model_id,
                "mcp_servers": enrich_mcp_servers_for_runtime(dynamic_mcp_servers),
                "identity": {
                    "subject": subject or session.user_id or "",
                    "agent_id": str(agent.id),
                    "session_id": session_id,
                },
                "approval_policies": [],
                "options": {"timeout_s": 300, "max_tool_rounds": 20},
            }
            buffer = ""
            saw_end = False
            async for piece in _proxy_agent_runtime_sse(payload=payload):
                buffer += piece
                while "\n\n" in buffer:
                    event_block, buffer = buffer.split("\n\n", 1)
                    text = event_block + "\n\n"
                    yield text
                    if "event: session_end" in text:
                        saw_end = True
                    if "event: error" in text and "event: session_start" not in text:
                        # Keep streaming; runtime may still close.
                        pass
            if buffer.strip():
                yield buffer if buffer.endswith("\n\n") else buffer + "\n\n"

            client_done_time = time.time()
            invocation.client_done_time = client_done_time
            invocation.client_duration_ms = round((client_done_time - client_invoke_time) * 1000, 3)
            if saw_end:
                invocation.status = "complete"
                session.status = "complete"
            else:
                invocation.status = "error"
                invocation.error_message = "agent-runtime stream ended without session_end"
                session.status = "error"
            db.commit()
        except Exception as exc:
            error_detail = str(exc)
            logger.error("Local agent-runtime invoke failed for agent %s: %s", agent.id, error_detail)
            invocation.status = "error"
            invocation.error_message = error_detail
            session.status = "error"
            db.commit()
            yield format_sse_event("session_start", {
                "session_id": session_id,
                "invocation_id": invocation_id,
                "client_invoke_time": client_invoke_time,
                "user_id": session.user_id,
                "token_source": "local-agent-runtime",
                "delegation_mode": "m2m",
            })
            yield format_sse_event("error", {
                "message": f"Invocation failed: {error_detail}",
                "code": "internal",
            })
        return

    # Legacy in-process LiteLLM path (no MCP tools).
    yield format_sse_event("session_start", {
        "session_id": session_id,
        "invocation_id": invocation_id,
        "client_invoke_time": client_invoke_time,
        "user_id": session.user_id,
        "token_source": "local-litellm",
        "delegation_mode": "m2m",
    })

    proxy = get_litellm_proxy_config(db)
    if proxy is None:
        invocation.status = "error"
        invocation.error_message = "LiteLLM proxy is not configured"
        session.status = "error"
        db.commit()
        yield format_sse_event("error", {
            "message": "LiteLLM proxy is not configured. Check LOOM_LITELLM_DISCOVERY_BASE_URL.",
        })
        return

    base_url, api_key = proxy
    chunks: list[str] = []
    try:
        model_id = resolve_local_model_id(agent, runtime_model_id)
        messages = build_chat_messages(agent, prompt)
        async for text in stream_litellm_text(
            base_url=base_url,
            api_key=api_key,
            model_id=model_id,
            messages=messages,
            session_id=session_id,
        ):
            chunks.append(text)
            yield format_sse_event("chunk", {"text": text})

        if not chunks:
            raise LocalInvokeError(
                f"LiteLLM returned an empty completion for model '{model_id}'"
            )

        client_done_time = time.time()
        full_text = "".join(chunks)
        invocation.client_done_time = client_done_time
        invocation.client_duration_ms = round((client_done_time - client_invoke_time) * 1000, 3)
        invocation.output_tokens = max(1, len(full_text.split()))
        invocation.input_tokens = max(1, len(prompt.split()))
        invocation.status = "complete"
        session.status = "complete"
        db.commit()

        yield format_sse_event("session_end", {
            "session_id": session_id,
            "invocation_id": invocation_id,
            "qualifier": session.qualifier,
            "client_invoke_time": client_invoke_time,
            "client_done_time": client_done_time,
            "client_duration_ms": invocation.client_duration_ms,
            "input_tokens": invocation.input_tokens,
            "output_tokens": invocation.output_tokens,
            "estimated_cost": 0,
        })
    except Exception as exc:
        error_detail = str(exc)
        logger.error("Local LiteLLM invoke failed for agent %s: %s", agent.id, error_detail)
        invocation.status = "error"
        invocation.error_message = error_detail
        session.status = "error"
        db.commit()
        yield format_sse_event("error", {
            "message": f"Invocation failed: {error_detail}",
        })
