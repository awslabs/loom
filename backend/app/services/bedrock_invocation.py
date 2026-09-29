"""Resolve and perform serverless inference against Bedrock models on
either the `bedrock-runtime` or `bedrock-mantle` endpoint (#64, R1).

Bedrock exposes two endpoints for model inference:
  - `bedrock-runtime`: the traditional endpoint, reached via the standard
    boto3 "bedrock-runtime" service client. Supports Converse, Invoke, and
    (for Anthropic models) the native Messages API.
  - `bedrock-mantle`: a newer endpoint some model families require for some
    or all of their APIs (e.g. the OpenAI-compatible Responses API, and
    several OSS models that are `bedrock-mantle`-only, like Gemma 4). It
    isn't a registered boto3 service model, so this module builds and
    SigV4-signs the HTTPS request directly.

Each catalog entry (`etc/models.json` / `etc/bedrock_model_catalog.json`)
declares which endpoint(s) and API(s) its `model_id` supports via the
`endpoints`/`apis` fields (see `scripts/refresh_models_json.py`).
`resolve_model_target` reads that metadata to pick the client/API/model-ID
to use; `invoke_model` performs the call.
"""
import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

BEDROCK_RUNTIME = "bedrock-runtime"
BEDROCK_MANTLE = "bedrock-mantle"

# Preference order when a model supports several APIs on the same endpoint —
# favor the most structured/normalizable shape first.
_API_PREFERENCE = ("converse", "messages", "chat_completions", "responses", "invoke")


class UnsupportedModelEndpointError(ValueError):
    """Raised when a model_id has no catalog entry, or doesn't support the
    requested (or any) endpoint/API."""


@dataclass
class ModelInvocationTarget:
    """The resolved endpoint/API/model-ID to invoke a catalog entry with."""
    catalog_model_id: str  # the model_id as stored in the catalog (unique key)
    invoke_model_id: str   # the model_id to actually send to Bedrock (may differ per endpoint)
    endpoint: str           # "bedrock-runtime" | "bedrock-mantle"
    api: str                 # "converse" | "invoke" | "messages" | "chat_completions" | "responses"
    region: str


def find_catalog_entry(model_id: str, catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in catalog:
        if entry.get("model_id") == model_id:
            return entry
    return None


def resolve_model_target(
    model_id: str,
    catalog: list[dict[str, Any]],
    region: str,
    preferred_endpoint: str | None = None,
    preferred_api: str | None = None,
) -> ModelInvocationTarget:
    """Pick the endpoint + API (+ per-endpoint model ID) to invoke `model_id` with.

    Catalog entries created before the `endpoints`/`apis` metadata existed
    fall back to `bedrock-runtime` + `converse` so older data keeps working
    without a migration.
    """
    entry = find_catalog_entry(model_id, catalog)
    if entry is None:
        raise UnsupportedModelEndpointError(f"Unknown model_id: {model_id!r}")

    endpoints: list[str] = entry.get("endpoints") or [BEDROCK_RUNTIME]
    apis_by_endpoint: dict[str, list[str]] = entry.get("apis") or {BEDROCK_RUNTIME: ["converse"]}

    endpoint = preferred_endpoint or endpoints[0]
    if endpoint not in endpoints:
        raise UnsupportedModelEndpointError(
            f"Model {model_id!r} does not support endpoint {endpoint!r} "
            f"(supported: {endpoints})"
        )

    apis = apis_by_endpoint.get(endpoint) or []
    if not apis:
        raise UnsupportedModelEndpointError(f"No known API for {model_id!r} on {endpoint!r}")

    if preferred_api:
        if preferred_api not in apis:
            raise UnsupportedModelEndpointError(
                f"Model {model_id!r} does not support API {preferred_api!r} on "
                f"{endpoint!r} (supported: {apis})"
            )
        api = preferred_api
    else:
        api = next((a for a in _API_PREFERENCE if a in apis), apis[0])

    invoke_model_id = (entry.get("endpoint_model_ids") or {}).get(endpoint, model_id)

    return ModelInvocationTarget(
        catalog_model_id=model_id,
        invoke_model_id=invoke_model_id,
        endpoint=endpoint,
        api=api,
        region=region,
    )


def assert_model_supports_endpoint(
    model_id: str,
    catalog: list[dict[str, Any]],
    endpoint: str = BEDROCK_RUNTIME,
) -> None:
    """Raise `UnsupportedModelEndpointError` unless `model_id` supports
    `endpoint`. Used to validate harness/agent model selection up front —
    AgentCore Harness only reaches models via `bedrock-runtime`, so a
    `bedrock-mantle`-only model (e.g. Gemma 4) can't back a harness agent."""
    entry = find_catalog_entry(model_id, catalog)
    if entry is None:
        # Unknown to the curated catalog (e.g. a dynamically-discovered
        # LiteLLM/live-Bedrock model) — nothing to validate against.
        return
    endpoints = entry.get("endpoints") or [BEDROCK_RUNTIME]
    if endpoint not in endpoints:
        raise UnsupportedModelEndpointError(
            f"Model {model_id!r} is only available via {endpoints}, not {endpoint!r}"
        )


def _mantle_base_url(region: str) -> str:
    return f"https://bedrock-mantle.{region}.api.aws"


def _sign_mantle_request(method: str, url: str, region: str, body: bytes) -> dict[str, str]:
    """SigV4-sign a request to bedrock-mantle. It isn't a registered boto3
    service model, so botocore's signer is driven directly rather than via
    a generated client."""
    import botocore.auth
    import botocore.awsrequest
    import botocore.session

    session = botocore.session.get_session()
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials available to sign the bedrock-mantle request")

    request = botocore.awsrequest.AWSRequest(
        method=method,
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    botocore.auth.SigV4Auth(credentials, "bedrock", region).add_auth(request)
    return dict(request.headers)


def invoke_model(
    model_id: str,
    catalog: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    region: str,
    max_tokens: int | None = None,
    system_prompt: str | None = None,
    preferred_endpoint: str | None = None,
    preferred_api: str | None = None,
) -> dict[str, Any]:
    """Run a single-turn serverless inference call against `model_id`, on
    whichever endpoint (bedrock-runtime or bedrock-mantle) it supports.

    `messages` is `[{"role": "user"|"assistant", "content": "..."}]`.
    Returns `{"content": str, "endpoint": str, "api": str, "model_id": str, "raw": <provider response>}`.
    """
    target = resolve_model_target(model_id, catalog, region, preferred_endpoint, preferred_api)

    if target.endpoint == BEDROCK_RUNTIME:
        result = _invoke_bedrock_runtime(target, messages, max_tokens, system_prompt)
    else:
        result = _invoke_bedrock_mantle(target, messages, max_tokens, system_prompt)

    result["model_id"] = model_id
    return result


def _invoke_bedrock_runtime(
    target: ModelInvocationTarget,
    messages: list[dict[str, Any]],
    max_tokens: int | None,
    system_prompt: str | None,
) -> dict[str, Any]:
    import boto3

    client = boto3.client("bedrock-runtime", region_name=target.region)

    if target.api == "converse":
        kwargs: dict[str, Any] = {
            "modelId": target.invoke_model_id,
            "messages": [{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages],
        }
        if max_tokens is not None:
            kwargs["inferenceConfig"] = {"maxTokens": max_tokens}
        if system_prompt:
            kwargs["system"] = [{"text": system_prompt}]
        response = client.converse(**kwargs)
        content = response["output"]["message"]["content"][0].get("text", "")
        return {"content": content, "endpoint": target.endpoint, "api": target.api, "raw": response}

    if target.api == "messages":
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": messages,
            "max_tokens": max_tokens or 1024,
        }
        if system_prompt:
            body["system"] = system_prompt
        response = client.invoke_model(modelId=target.invoke_model_id, body=json.dumps(body))
        payload = json.loads(response["body"].read())
        content = "".join(block.get("text", "") for block in payload.get("content", []))
        return {"content": content, "endpoint": target.endpoint, "api": target.api, "raw": payload}

    # "invoke" fallback and any other InvokeModel-shaped API not covered
    # above — every current catalog entry that reaches this branch is an
    # Anthropic model, so the Anthropic Messages request body is correct.
    body = {"anthropic_version": "bedrock-2023-05-31", "messages": messages}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if system_prompt:
        body["system"] = system_prompt
    response = client.invoke_model(modelId=target.invoke_model_id, body=json.dumps(body))
    payload = json.loads(response["body"].read())
    content = "".join(block.get("text", "") for block in payload.get("content", []))
    return {"content": content, "endpoint": target.endpoint, "api": target.api, "raw": payload}


def _invoke_bedrock_mantle(
    target: ModelInvocationTarget,
    messages: list[dict[str, Any]],
    max_tokens: int | None,
    system_prompt: str | None,
) -> dict[str, Any]:
    base_url = _mantle_base_url(target.region)

    if target.api == "messages":
        path = "/anthropic/v1/messages"
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "model": target.invoke_model_id,
            "messages": messages,
            "max_tokens": max_tokens or 1024,
        }
        if system_prompt:
            body["system"] = system_prompt
    else:
        # chat_completions / responses are OpenAI-compatible on bedrock-mantle.
        path = "/openai/v1/chat/completions" if target.api == "chat_completions" else "/openai/v1/responses"
        chat_messages = list(messages)
        if system_prompt:
            chat_messages = [{"role": "system", "content": system_prompt}] + chat_messages
        body = {"model": target.invoke_model_id, "messages": chat_messages}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

    url = f"{base_url}{path}"
    payload_bytes = json.dumps(body).encode("utf-8")
    headers = _sign_mantle_request("POST", url, target.region, payload_bytes)

    request = urllib.request.Request(url, data=payload_bytes, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as resp:  # noqa: S310 - internal AWS endpoint, SigV4-signed
        data = json.loads(resp.read())

    if target.api == "messages":
        content = "".join(block.get("text", "") for block in data.get("content", []))
    else:
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"content": content, "endpoint": target.endpoint, "api": target.api, "raw": data}
