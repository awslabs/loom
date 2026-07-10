"""AgentCore Harness API wrapper.

Provides functions to create, get, delete, and invoke harness-based managed agents
via the bedrock-agentcore-control (control plane) and bedrock-agentcore (data plane) clients.
"""

import json
import logging
from typing import Any, Generator

logger = logging.getLogger(__name__)


def _build_model_config(
    provider: str,
    model_id: str,
    max_tokens: int | None = None,
    litellm_api_key_arn: str | None = None,
    litellm_api_base: str | None = None,
) -> dict[str, Any]:
    """Build the `model` field for CreateHarness/UpdateHarness/InvokeHarness.

    Bedrock (the default) uses `bedrockModelConfig`. LiteLLM uses
    `liteLlmModelConfig` — `apiKeyArn` points at an AgentCore Identity API
    key credential provider (not Secrets Manager), and `apiBase` is the
    LiteLLM proxy's endpoint. Both are optional per the API, but Loom's
    LiteLLM provider always requires a base_url so `apiBase` is effectively
    always set for LiteLLM harness agents.
    """
    if provider == "litellm":
        cfg: dict[str, Any] = {"modelId": model_id}
        if litellm_api_key_arn:
            cfg["apiKeyArn"] = litellm_api_key_arn
        if litellm_api_base:
            cfg["apiBase"] = litellm_api_base
        if max_tokens is not None:
            cfg["maxTokens"] = max_tokens
        return {"liteLlmModelConfig": cfg}

    cfg = {"modelId": model_id}
    if max_tokens is not None:
        cfg["maxTokens"] = max_tokens
    return {"bedrockModelConfig": cfg}


def create_harness(
    name: str,
    execution_role_arn: str,
    model_id: str,
    system_prompt: str,
    tools: list[dict[str, Any]] | None = None,
    allowed_tools: list[str] | None = None,
    max_iterations: int | None = None,
    max_tokens: int | None = None,
    authorizer_config: dict[str, Any] | None = None,
    network_mode: str = "PUBLIC",
    vpc_subnet_ids: list[str] | None = None,
    vpc_security_group_ids: list[str] | None = None,
    idle_timeout: int | None = None,
    max_lifetime: int | None = None,
    tags: dict[str, str] | None = None,
    memory_arn: str | None = None,
    memory_retrieval_config: dict[str, Any] | None = None,
    region: str = "us-east-1",
    provider: str = "bedrock",
    litellm_api_key_arn: str | None = None,
    litellm_api_base: str | None = None,
) -> dict[str, Any]:
    """Create a new AgentCore Harness (managed agent loop).

    Returns the CreateHarness API response containing harnessId, harnessArn, status, etc.
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)

    params: dict[str, Any] = {
        "harnessName": name,
        "executionRoleArn": execution_role_arn,
        "model": _build_model_config(provider, model_id, max_tokens, litellm_api_key_arn, litellm_api_base),
        "systemPrompt": [{"text": system_prompt}],
    }

    if tools:
        params["tools"] = tools
    if allowed_tools:
        params["allowedTools"] = allowed_tools
    else:
        params["allowedTools"] = ["*"]

    if max_iterations is not None:
        params["maxIterations"] = max_iterations
    if authorizer_config:
        params["authorizerConfiguration"] = authorizer_config

    lifecycle_config: dict[str, int] = {}
    if idle_timeout is not None:
        lifecycle_config["idleRuntimeSessionTimeout"] = idle_timeout
    if max_lifetime is not None:
        lifecycle_config["maxLifetime"] = max_lifetime

    if lifecycle_config or network_mode != "PUBLIC":
        env_config: dict[str, Any] = {}
        if lifecycle_config:
            env_config["lifecycleConfiguration"] = lifecycle_config
        if network_mode != "PUBLIC":
            net_cfg: dict[str, Any] = {"networkMode": network_mode}
            if network_mode == "VPC" and (vpc_subnet_ids or vpc_security_group_ids):
                net_cfg["networkModeConfig"] = {
                    "subnets": vpc_subnet_ids or [],
                    "securityGroups": vpc_security_group_ids or [],
                }
            env_config["networkConfiguration"] = net_cfg
        params["environment"] = {"agentCoreRuntimeEnvironment": env_config}

    if memory_arn:
        mem_cfg: dict[str, Any] = {"arn": memory_arn}
        if memory_retrieval_config:
            mem_cfg["retrievalConfig"] = memory_retrieval_config
        params["memory"] = {"agentCoreMemoryConfiguration": mem_cfg}

    if tags:
        params["tags"] = tags

    response = client.create_harness(**params)
    result = response.get("harness", response)
    logger.info("Created harness '%s': id=%s status=%s", name, result.get("harnessId"), result.get("status"))
    return result


def get_harness(harness_id: str, region: str = "us-east-1") -> dict[str, Any]:
    """Get the current state of a harness."""
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    response = client.get_harness(harnessId=harness_id)
    return response.get("harness", response)


def update_harness(
    harness_id: str,
    execution_role_arn: str | None = None,
    model_id: str | None = None,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    allowed_tools: list[str] | None = None,
    max_iterations: int | None = None,
    max_tokens: int | None = None,
    authorizer_config: dict[str, Any] | None = None,
    network_mode: str | None = None,
    vpc_subnet_ids: list[str] | None = None,
    vpc_security_group_ids: list[str] | None = None,
    idle_timeout: int | None = None,
    max_lifetime: int | None = None,
    memory_arn: str | None = None,
    memory_retrieval_config: dict[str, Any] | None = None,
    region: str = "us-east-1",
    provider: str = "bedrock",
    litellm_api_key_arn: str | None = None,
    litellm_api_base: str | None = None,
) -> dict[str, Any]:
    """Update an existing AgentCore Harness."""
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)

    params: dict[str, Any] = {"harnessId": harness_id}

    if execution_role_arn:
        params["executionRoleArn"] = execution_role_arn
    if model_id:
        params["model"] = _build_model_config(provider, model_id, max_tokens, litellm_api_key_arn, litellm_api_base)
    if system_prompt is not None:
        params["systemPrompt"] = [{"text": system_prompt}]
    if tools is not None:
        params["tools"] = tools
    if allowed_tools:
        params["allowedTools"] = allowed_tools
    else:
        params["allowedTools"] = ["*"]
    if max_iterations is not None:
        params["maxIterations"] = max_iterations
    if authorizer_config is not None:
        params["authorizerConfiguration"] = {"optionalValue": authorizer_config}

    lifecycle_config: dict[str, int] = {}
    if idle_timeout is not None:
        lifecycle_config["idleRuntimeSessionTimeout"] = idle_timeout
    if max_lifetime is not None:
        lifecycle_config["maxLifetime"] = max_lifetime

    if lifecycle_config or (network_mode and network_mode != "PUBLIC"):
        env_config: dict[str, Any] = {}
        if lifecycle_config:
            env_config["lifecycleConfiguration"] = lifecycle_config
        if network_mode and network_mode != "PUBLIC":
            net_cfg: dict[str, Any] = {"networkMode": network_mode}
            if network_mode == "VPC" and (vpc_subnet_ids or vpc_security_group_ids):
                net_cfg["networkModeConfig"] = {
                    "subnets": vpc_subnet_ids or [],
                    "securityGroups": vpc_security_group_ids or [],
                }
            env_config["networkConfiguration"] = net_cfg
        params["environment"] = {"agentCoreRuntimeEnvironment": env_config}

    if memory_arn is not None:
        mem_cfg: dict[str, Any] = {"arn": memory_arn}
        if memory_retrieval_config:
            mem_cfg["retrievalConfig"] = memory_retrieval_config
        params["memory"] = {"optionalValue": {"agentCoreMemoryConfiguration": mem_cfg}}

    response = client.update_harness(**params)
    result = response.get("harness", response)
    logger.info("Updated harness '%s': status=%s", harness_id, result.get("status"))
    return result


def delete_harness(harness_id: str, region: str = "us-east-1") -> dict[str, Any]:
    """Delete a harness."""
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    response = client.delete_harness(harnessId=harness_id)
    logger.info("Deleted harness %s", harness_id)
    return response


def invoke_harness_stream(
    harness_arn: str,
    session_id: str,
    prompt: str,
    region: str = "us-east-1",
    model_id: str | None = None,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    allowed_tools: list[str] | None = None,
    max_iterations: int | None = None,
    timeout_seconds: int | None = None,
    max_tokens: int | None = None,
    actor_id: str | None = None,
    access_token: str | None = None,
    user_access_token: str | None = None,
    provider: str = "bedrock",
    litellm_api_key_arn: str | None = None,
    litellm_api_base: str | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Invoke a harness and yield translated SSE events.

    Translates the Converse API-style streaming response into the same event
    format used by invoke_agent (text chunks, tool_use, metadata) so the
    frontend chat UI works without modification.

    Yields dicts with keys:
        - {"type": "text", "content": str} for text deltas
        - {"type": "structured", "content": {"tool_use": {"name": str}}} for tool use
        - {"type": "metadata", "content": dict} for token usage/metrics
    """
    import boto3

    if access_token:
        from botocore import UNSIGNED
        from botocore.config import Config

        client = boto3.client(
            "bedrock-agentcore",
            region_name=region,
            config=Config(signature_version=UNSIGNED),
        )

        def _add_auth_header(request, **kwargs):
            request.headers["Authorization"] = f"Bearer {access_token}"

        client.meta.events.register("before-send.bedrock-agentcore.InvokeHarness", _add_auth_header)
    else:
        client = boto3.client("bedrock-agentcore", region_name=region)

    params: dict[str, Any] = {
        "harnessArn": harness_arn,
        "runtimeSessionId": session_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
    }

    if model_id:
        params["model"] = _build_model_config(provider, model_id, litellm_api_key_arn=litellm_api_key_arn, litellm_api_base=litellm_api_base)
    if system_prompt:
        params["systemPrompt"] = [{"text": system_prompt}]
    if tools:
        params["tools"] = tools
    if allowed_tools:
        params["allowedTools"] = allowed_tools
    if max_iterations is not None:
        params["maxIterations"] = max_iterations
    if timeout_seconds is not None:
        params["timeoutSeconds"] = timeout_seconds
    if max_tokens is not None:
        params["maxTokens"] = max_tokens
    if actor_id:
        params["actorId"] = actor_id

    if user_access_token:
        def _add_user_token_header(request, **kwargs):
            request.headers["X-Loom-User-Access-Token"] = user_access_token

        client.meta.events.register(
            "before-send.bedrock-agentcore.InvokeHarness", _add_user_token_header,
        )

    response = client.invoke_harness(**params)

    stream = response.get("stream") or response.get("body") or response.get("response")
    if stream is None:
        return

    total_input_tokens = 0
    total_output_tokens = 0
    current_tool_name: str | None = None
    current_tool_use_id: str | None = None
    current_tool_input_chunks: list[str] = []
    stop_reason: str | None = None

    for event in stream:
        logger.debug("Harness raw event: %s", event)
        if "contentBlockStart" in event:
            start = event["contentBlockStart"].get("start", {})
            tool_use = start.get("toolUse")
            if tool_use:
                current_tool_name = tool_use.get("name")
                current_tool_use_id = tool_use.get("toolUseId")
                current_tool_input_chunks = []
                logger.info("Harness tool_use start: name=%s id=%s", current_tool_name, current_tool_use_id)
                if current_tool_name:
                    yield {"type": "structured", "content": {"tool_use": {"name": current_tool_name}}}

        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            text = delta.get("text")
            if text:
                yield {"type": "text", "content": text}
            tool_use_delta = delta.get("toolUse")
            if tool_use_delta:
                input_chunk = tool_use_delta.get("input", "")
                if input_chunk:
                    current_tool_input_chunks.append(input_chunk)

        elif "contentBlockStop" in event:
            current_tool_name = None

        elif "messageStart" in event:
            pass

        elif "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason")
            logger.info("Harness messageStop: stopReason=%s current_tool=%s current_tool_use_id=%s", stop_reason, current_tool_name, current_tool_use_id)

        elif "metadata" in event:
            meta = event["metadata"]
            usage = meta.get("usage", {})
            total_input_tokens += usage.get("inputTokens", 0)
            total_output_tokens += usage.get("outputTokens", 0)

    if total_input_tokens > 0 or total_output_tokens > 0:
        yield {
            "type": "metadata",
            "content": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
            },
        }

    # When the stream stops for an inline tool_use, yield a special event
    # so the caller can handle the HITL loop (wait for user, then resume).
    if stop_reason == "tool_use" and current_tool_use_id:
        tool_input_str = "".join(current_tool_input_chunks)
        tool_input: dict[str, Any] = {}
        if tool_input_str:
            try:
                tool_input = json.loads(tool_input_str)
            except (json.JSONDecodeError, TypeError):
                pass
        yield {
            "type": "tool_use_stop",
            "content": {
                "tool_use_id": current_tool_use_id,
                "tool_name": current_tool_name,
                "tool_input": tool_input,
            },
        }


def resume_harness_stream(
    harness_arn: str,
    session_id: str,
    tool_use_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_result_content: str,
    tool_result_status: str = "success",
    region: str = "us-east-1",
    tools: list[dict[str, Any]] | None = None,
    access_token: str | None = None,
    actor_id: str | None = None,
    user_access_token: str | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Re-invoke a harness with a toolResult to resume after an inline function call.

    Sends the assistant toolUse turn followed by the user toolResult turn so the
    Converse API sees a matching pair.

    Yields the same event format as invoke_harness_stream.
    """
    import boto3

    if access_token:
        from botocore import UNSIGNED
        from botocore.config import Config

        client = boto3.client(
            "bedrock-agentcore",
            region_name=region,
            config=Config(signature_version=UNSIGNED),
        )

        def _add_auth_header(request, **kwargs):
            request.headers["Authorization"] = f"Bearer {access_token}"

        client.meta.events.register("before-send.bedrock-agentcore.InvokeHarness", _add_auth_header)
    else:
        client = boto3.client("bedrock-agentcore", region_name=region)

    params: dict[str, Any] = {
        "harnessArn": harness_arn,
        "runtimeSessionId": session_id,
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": tool_name,
                            "input": tool_input,
                        }
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"text": tool_result_content}],
                            "status": tool_result_status,
                        }
                    }
                ],
            },
        ],
    }

    if tools:
        params["tools"] = tools
    if actor_id:
        params["actorId"] = actor_id

    if user_access_token:
        def _add_user_token_header(request, **kwargs):
            request.headers["X-Loom-User-Access-Token"] = user_access_token

        client.meta.events.register(
            "before-send.bedrock-agentcore.InvokeHarness", _add_user_token_header,
        )

    response = client.invoke_harness(**params)

    stream = response.get("stream") or response.get("body") or response.get("response")
    if stream is None:
        return

    total_input_tokens = 0
    total_output_tokens = 0
    current_tool_name_r: str | None = None
    current_tool_use_id_r: str | None = None
    current_tool_input_chunks_r: list[str] = []
    stop_reason_r: str | None = None

    for event in stream:
        if "contentBlockStart" in event:
            start = event["contentBlockStart"].get("start", {})
            tool_use = start.get("toolUse")
            if tool_use:
                current_tool_name_r = tool_use.get("name")
                current_tool_use_id_r = tool_use.get("toolUseId")
                current_tool_input_chunks_r = []
                if current_tool_name_r:
                    yield {"type": "structured", "content": {"tool_use": {"name": current_tool_name_r}}}

        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            text = delta.get("text")
            if text:
                yield {"type": "text", "content": text}
            tool_use_delta = delta.get("toolUse")
            if tool_use_delta:
                input_chunk = tool_use_delta.get("input", "")
                if input_chunk:
                    current_tool_input_chunks_r.append(input_chunk)

        elif "contentBlockStop" in event:
            current_tool_name_r = None

        elif "messageStart" in event:
            pass

        elif "messageStop" in event:
            stop_reason_r = event["messageStop"].get("stopReason")

        elif "metadata" in event:
            meta = event["metadata"]
            usage = meta.get("usage", {})
            total_input_tokens += usage.get("inputTokens", 0)
            total_output_tokens += usage.get("outputTokens", 0)

    if total_input_tokens > 0 or total_output_tokens > 0:
        yield {
            "type": "metadata",
            "content": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
            },
        }

    if stop_reason_r == "tool_use" and current_tool_use_id_r:
        tool_input_str = "".join(current_tool_input_chunks_r)
        tool_input: dict[str, Any] = {}
        if tool_input_str:
            try:
                tool_input = json.loads(tool_input_str)
            except (json.JSONDecodeError, TypeError):
                pass
        yield {
            "type": "tool_use_stop",
            "content": {
                "tool_use_id": current_tool_use_id_r,
                "tool_name": current_tool_name_r,
                "tool_input": tool_input,
            },
        }
