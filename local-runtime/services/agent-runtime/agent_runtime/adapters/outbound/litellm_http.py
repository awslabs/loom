"""LiteLLM OpenAI-compatible chat completions."""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from agent_runtime.domain.contract import is_cursor_model
from agent_runtime.domain.errors import AgentRuntimeError


def litellm_base_url() -> str:
    return os.environ.get("LITELLM_BASE_URL", "http://litellm:4000").rstrip("/")


def litellm_api_key() -> str:
    return os.environ.get("LITELLM_API_KEY", os.environ.get("LITELLM_MASTER_KEY", "")).strip()


class LiteLlmGateway:
    """Outbound adapter implementing ``LlmGateway``."""

    def chat_completion(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        session_id: str,
        timeout_s: float,
    ) -> dict[str, Any]:
        key = litellm_api_key()
        if not key:
            raise AgentRuntimeError("model_auth", "LITELLM_API_KEY is not set")
        url = f"{litellm_base_url()}/v1/chat/completions"
        outbound = list(messages)
        if tools and is_cursor_model(model_id):
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
        timeout = httpx.Timeout(timeout_s, connect=10.0)
        try:
            with httpx.Client(timeout=timeout) as client:
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
