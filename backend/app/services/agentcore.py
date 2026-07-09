"""
Bedrock AgentCore Runtime API wrapper.

This module provides functions to interact with AWS Bedrock AgentCore Runtime API
for describing runtimes, listing endpoints, and invoking agents with streaming responses.
Supports both HTTP streaming (for hook-based HITL) and WebSocket (for MCP elicitation).
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Generator

logger = logging.getLogger(__name__)


def describe_runtime(arn: str, region: str) -> dict[str, Any]:
    """
    Describe an AgentCore Runtime by ARN.

    Uses the bedrock-agentcore-control client (control plane).
    See: https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/get_agent_runtime.html

    Args:
        arn: AgentCore Runtime ARN (e.g., 'arn:aws:bedrock-agentcore:us-east-1:...:runtime/...')
        region: AWS region name

    Returns:
        Dictionary containing runtime metadata from the AgentCore API response

    Raises:
        Exception: If the runtime does not exist or API call fails
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)

    # Extract runtime ID from ARN
    # ARN format: arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{runtime_id}
    runtime_id = arn.split('/')[-1]

    response = client.get_agent_runtime(agentRuntimeId=runtime_id)
    return response


def list_runtime_endpoints(runtime_id: str, region: str) -> list[str]:
    """
    List available endpoint qualifiers for an AgentCore Runtime.

    Uses the bedrock-agentcore-control client (control plane).
    See: https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore-control/client/list_agent_runtime_endpoints.html

    Args:
        runtime_id: AgentCore Runtime ID (extracted from ARN)
        region: AWS region name

    Returns:
        List of endpoint qualifier names (e.g., ['DEFAULT'])
        Falls back to ['DEFAULT'] if the API call fails or returns no endpoints
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)

    try:
        response = client.list_agent_runtime_endpoints(agentRuntimeId=runtime_id)
        endpoints = response.get('runtimeEndpoints', [])

        # Extract qualifier names from endpoint objects
        qualifiers = [ep.get('name', 'DEFAULT') for ep in endpoints if 'name' in ep]

        return qualifiers if qualifiers else ['DEFAULT']

    except Exception:
        # Fallback to DEFAULT if API call fails
        return ['DEFAULT']


def invoke_agent(
    arn: str,
    qualifier: str,
    session_id: str,
    prompt: str,
    region: str,
    access_token: str | None = None,
    actor_id: str | None = None,
    dynamic_mcp_servers: list[dict[str, Any]] | None = None,
    runtime_model_id: str | None = None,
    interrupt_response: list[dict[str, Any]] | None = None,
    approval_policies: list[dict[str, Any]] | None = None,
    supports_elicitation: bool = False,
    elicitation_response: dict[str, Any] | None = None,
    user_access_token: str | None = None,
) -> Generator[dict[str, Any], None, None]:
    """
    Invoke an AgentCore Runtime agent and stream the response.

    Calls the AgentCore invoke_agent_runtime API and yields structured chunks
    as they arrive from the streaming response.

    The boto3 API returns a 'response' field containing a StreamingBody.
    See: https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore/client/invoke_agent_runtime.html

    Args:
        arn: AgentCore Runtime ARN
        qualifier: Endpoint qualifier (e.g., 'DEFAULT')
        session_id: Unique session ID (typically a UUID) for this invocation
        prompt: Input prompt text to send to the agent
        region: AWS region name

    Yields:
        Structured dicts: {"type": "text", "content": str} for text payloads,
        {"type": "structured", "content": dict} for dict payloads (e.g. thinking data)

    Raises:
        Exception: If the agent invocation fails
    """
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    payload: dict[str, Any] = {"prompt": prompt, "session_id": session_id, "actor_id": actor_id or "loom-agent"}
    if interrupt_response:
        payload["interruptResponse"] = interrupt_response
    if dynamic_mcp_servers:
        payload["dynamic_mcp_servers"] = dynamic_mcp_servers
    if runtime_model_id:
        payload["model_id"] = runtime_model_id
    if approval_policies:
        payload["approval_policies"] = approval_policies
    if supports_elicitation:
        payload["supports_elicitation"] = True
    if elicitation_response:
        payload["elicitationResponse"] = elicitation_response
    if user_access_token:
        payload["user_access_token"] = user_access_token
    payload_bytes = json.dumps(payload).encode('utf-8')

    params: dict[str, Any] = {
        "agentRuntimeArn": arn,
        "qualifier": qualifier,
        "runtimeSessionId": session_id,
        "payload": payload_bytes,
        "contentType": "application/json",
        "accept": "application/json",
    }

    if access_token:
        # OAuth-authorized agents: skip SigV4, use Bearer token only
        client = boto3.client(
            'bedrock-agentcore',
            region_name=region,
            config=Config(signature_version=UNSIGNED),
        )

        def _add_auth_header(request, **kwargs):
            request.headers["Authorization"] = f"Bearer {access_token}"

        client.meta.events.register("before-send.bedrock-agentcore.InvokeAgentRuntime", _add_auth_header)
    else:
        client = boto3.client('bedrock-agentcore', region_name=region)

    response = client.invoke_agent_runtime(**params)

    # The API returns 'response' as a StreamingBody.
    # The agent's response is SSE-formatted: each token arrives as a
    # "data: <json-string>\n\n" line within the stream.  We parse these
    # inner SSE events and yield individual text tokens so the caller
    # can forward them one-by-one.
    streaming_body = response.get('response')
    if streaming_body is None:
        return

    line_count = 0
    for line in streaming_body.iter_lines():
        decoded = line.decode('utf-8').strip()
        if not decoded:
            continue
        line_count += 1
        if line_count <= 10 or "elicitation" in decoded.lower() or "interrupt" in decoded.lower():
            if "token_info" in decoded:
                logger.info("Stream line %d: [token_info event redacted]", line_count)
            else:
                logger.info("Stream line %d: %s", line_count, decoded[:500])
        if not decoded.startswith('data:'):
            logger.info("Non-data stream line: %s", decoded[:500])
            continue
        payload = decoded[5:].strip()  # strip "data:" prefix
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                yield {"type": "structured", "content": parsed}
            elif isinstance(parsed, str) and parsed:
                yield {"type": "text", "content": parsed}
        except json.JSONDecodeError:
            if payload:
                yield {"type": "text", "content": payload}
    logger.info("Stream completed: %d total lines received", line_count)


async def invoke_agent_ws(
    arn: str,
    qualifier: str,
    session_id: str,
    prompt: str,
    region: str,
    access_token: str | None = None,
    actor_id: str | None = None,
    dynamic_mcp_servers: list[dict[str, Any]] | None = None,
    runtime_model_id: str | None = None,
) -> AsyncGenerator[dict[str, Any], str | None]:
    """Invoke an AgentCore Runtime agent via WebSocket for MCP elicitation support.

    Uses a bidirectional WebSocket connection so elicitation requests from the
    agent can be relayed to the caller and responses sent back inline.

    This is an async generator that yields events. The caller can send
    elicitation responses back via generator.asend(response_json).

    Args:
        arn: AgentCore Runtime ARN
        qualifier: Endpoint qualifier
        session_id: Session ID for this invocation
        prompt: Input prompt
        region: AWS region
        access_token: Optional OAuth Bearer token
        actor_id: Actor identity
        dynamic_mcp_servers: MCP servers to attach with elicitation support
        runtime_model_id: Optional model override

    Yields:
        Structured dicts with "type" field:
        - {"type": "text", "content": str}
        - {"type": "elicitation", "id": str, "message": str}
        - {"type": "result", "content": str}
        - {"type": "error", "content": str}

    Send:
        JSON string with elicitation response to resume tool execution
    """
    import websockets
    from botocore.auth import SigV4Auth
    from botocore.credentials import Credentials
    import boto3

    runtime_id = arn.split('/')[-1]
    encoded_arn = arn.replace(":", "%3A").replace("/", "%2F")
    ws_url = f"wss://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/ws?qualifier={qualifier}"

    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        async with websockets.connect(ws_url, additional_headers=headers) as ws:
            payload: dict[str, Any] = {
                "type": "prompt",
                "prompt": prompt,
                "session_id": session_id,
                "actor_id": actor_id or "loom-agent",
            }
            if dynamic_mcp_servers:
                payload["dynamic_mcp_servers_elicit"] = dynamic_mcp_servers
            if runtime_model_id:
                payload["model_id"] = runtime_model_id

            await ws.send(json.dumps(payload))
            logger.info("WebSocket prompt sent session_id=%s", session_id)

            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                msg_type = data.get("type", "")

                if msg_type == "elicitation":
                    response = yield data
                    if response:
                        await ws.send(response)
                elif msg_type == "result":
                    yield data
                    return
                elif msg_type == "error":
                    yield data
                    return
                elif msg_type == "text":
                    yield data
                else:
                    yield {"type": "structured", "content": data}

    except Exception as e:
        logger.error("WebSocket invocation failed: %s", e)
        yield {"type": "error", "content": str(e)}
