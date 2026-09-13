"""LiteLLM CustomLLM that forwards to the host Cursor adapter.

This module is imported *inside* the LiteLLM process. It must not import
``cursor_sdk`` — the adapter on the host owns the SDK and the Bridge.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, AsyncIterator, Iterator

logger = logging.getLogger("cursor_handler")

DEFAULT_ADAPTER_URL = "http://host.docker.internal:8765"


def adapter_url() -> str:
    return os.environ.get("CURSOR_ADAPTER_URL", DEFAULT_ADAPTER_URL).rstrip("/")


def _optional_headers(optional_params: dict[str, Any] | None) -> dict[str, str]:
    params = optional_params or {}
    headers: dict[str, str] = {}
    mapping = {
        "loom_session_id": "X-Loom-Session-Id",
        "loom_agent_id": "X-Loom-Agent-Id",
        "loom_workspace": "X-Loom-Workspace",
        "session_id": "X-Loom-Session-Id",
        "agent_id": "X-Loom-Agent-Id",
        "workspace": "X-Loom-Workspace",
    }
    for key, header in mapping.items():
        value = params.get(key)
        if value:
            headers[header] = str(value)
    return headers


def _extract_tools(optional_params: dict[str, Any] | None, kwargs: dict[str, Any]) -> list[dict[str, Any]] | None:
    for source in (kwargs, optional_params or {}):
        tools = source.get("tools")
        if isinstance(tools, list) and tools:
            return [t for t in tools if isinstance(t, dict)]
    return None


def forward_to_adapter(
    messages: list[dict[str, Any]],
    model: str,
    stream: bool = False,
    optional_params: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    timeout: float = 120.0,
) -> tuple[int, dict[str, Any] | str]:
    """POST /v1/chat/completions on the host adapter.

    Returns ``(status_code, body)``. Body is a dict for JSON and a str for
    raw error text. Never logs secrets.
    """
    url = f"{adapter_url()}/v1/chat/completions"
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
        **_optional_headers(optional_params),
    }
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            if stream:
                return response.status, raw
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, {"error": {"message": "adapter_invalid_json"}}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": {"message": raw or f"adapter_http_{exc.code}"}}
    except urllib.error.URLError as exc:
        logger.warning("Cursor adapter unreachable at %s: %s", url, exc.reason)
        return 503, {"error": {"message": "cursor_adapter_unavailable", "code": "cursor_adapter_unavailable"}}


def _fill_model_response(model_response: Any, body: dict[str, Any], model: str) -> Any:
    choices = body.get("choices") or []
    if choices:
        message = (choices[0] or {}).get("message") or {}
        target = model_response.choices[0].message
        content = message.get("content")
        tool_calls = message.get("tool_calls")
        # Prefer structured tool_calls; keep JSON content fallback for proxies.
        if tool_calls and not content:
            content = json.dumps({"tool_calls": tool_calls}, ensure_ascii=False)
        target.content = content
        if tool_calls:
            try:
                target.tool_calls = tool_calls
            except Exception:
                setattr(target, "tool_calls", tool_calls)
            model_response.choices[0].finish_reason = (choices[0] or {}).get("finish_reason") or "tool_calls"
        else:
            model_response.choices[0].finish_reason = (choices[0] or {}).get("finish_reason") or "stop"
    else:
        error = (body.get("error") or {}).get("message") or "cursor_adapter_error"
        model_response.choices[0].message.content = ""
        model_response.choices[0].finish_reason = "stop"
        raise RuntimeError(error)
    if hasattr(model_response, "model"):
        model_response.model = body.get("model") or model
    return model_response


class CursorCustomLLM:
    """Duck-typed CustomLLM: LiteLLM binds this instance via custom_provider_map.

    Methods match ``litellm.CustomLLM`` so we can unit-test forwarding without
    importing LiteLLM in the adapter test suite.
    """

    def completion(self, *args: Any, **kwargs: Any) -> Any:
        messages: list[dict[str, Any]] = kwargs.get("messages") or []
        model: str = kwargs.get("model") or "cursor-default"
        optional_params: dict[str, Any] = kwargs.get("optional_params") or {}
        model_response = kwargs.get("model_response")
        tools = _extract_tools(optional_params, kwargs)
        status, body = forward_to_adapter(
            messages,
            model,
            stream=False,
            optional_params=optional_params,
            tools=tools,
        )
        if status >= 400 or not isinstance(body, dict):
            message = body.get("error", {}).get("message") if isinstance(body, dict) else str(body)
            raise RuntimeError(message or f"adapter_http_{status}")
        if model_response is None:
            return body
        return _fill_model_response(model_response, body, model)

    async def acompletion(self, *args: Any, **kwargs: Any) -> Any:
        return self.completion(*args, **kwargs)

    def streaming(self, *args: Any, **kwargs: Any) -> Iterator[str]:
        messages: list[dict[str, Any]] = kwargs.get("messages") or []
        model: str = kwargs.get("model") or "cursor-default"
        optional_params: dict[str, Any] = kwargs.get("optional_params") or {}
        tools = _extract_tools(optional_params, kwargs)
        status, body = forward_to_adapter(
            messages,
            model,
            stream=True,
            optional_params=optional_params,
            tools=tools,
        )
        if status >= 400:
            raise RuntimeError(
                body.get("error", {}).get("message") if isinstance(body, dict) else str(body)
            )
        text = body if isinstance(body, str) else json.dumps(body)
        for line in text.splitlines():
            if line:
                yield line

    async def astreaming(self, *args: Any, **kwargs: Any) -> AsyncIterator[str]:
        # LiteLLM's async path calls this; CustomLLM.astreaming is a stub.
        for line in self.streaming(*args, **kwargs):
            yield line


try:
    from litellm import CustomLLM  # type: ignore

    # CursorCustomLLM must come first. CustomLLM's stubs raise
    # "Not implemented yet!" and would win if listed first in the MRO.
    class CursorLiteLLM(CursorCustomLLM, CustomLLM):
        pass

    cursor_llm = CursorLiteLLM()
except Exception:  # LiteLLM is only present inside the proxy container
    cursor_llm = CursorCustomLLM()
