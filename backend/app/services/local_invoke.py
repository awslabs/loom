"""Local-dev invoke path: Loom backend → LiteLLM proxy (not AgentCore).

Only agents with source='local' use this. Deployed/harness/register agents
keep the existing AgentCore runtime path.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncGenerator

import httpx
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.invocation import Invocation
from app.models.session import InvocationSession
from app.services.litellm import get_litellm_proxy_config

logger = logging.getLogger(__name__)


class LocalInvokeError(Exception):
    """LiteLLM proxy is missing or rejected the completion request."""


def format_sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def is_local_agent(agent: Agent) -> bool:
    return (agent.source or "") == "local"


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
                    "Cursor adapter is not running on the host. "
                    "Leave the model as orientador-academico for the local mock, "
                    "or start the adapter in WSL on 127.0.0.1:8765 and retry."
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


async def invoke_local_agent_stream(
    agent: Agent,
    session: InvocationSession,
    invocation: Invocation,
    db: Session,
    client_invoke_time: float,
    prompt: str,
    runtime_model_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Yield the same SSE events as AgentCore invoke: session_start, chunk, session_end."""
    session_id = session.session_id
    invocation_id = invocation.invocation_id
    invocation.client_invoke_time = client_invoke_time
    invocation.status = "streaming"
    session.status = "streaming"
    db.commit()

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
