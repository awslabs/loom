"""A2A (Agent-to-Agent) client vending from agent configuration.

Uses the Strands Agents SDK A2AAgent class to create callable wrappers
around remote A2A-compliant agents.  Each enabled A2A agent in the
configuration becomes a Strands ``@tool`` function that the orchestrating
agent can invoke during a conversation.
"""

import json as _json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
from a2a.client.errors import A2AClientJSONRPCError
from a2a.types import (
    AgentCard,
    JSONRPCErrorResponse,
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    SendMessageRequest,
    SendMessageResponse,
    SendStreamingMessageRequest,
    SendStreamingMessageResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from strands import tool
from strands.agent.a2a_agent import A2AAgent
from strands.multiagent.a2a._converters import convert_input_to_message

from src.config import A2AAgentConfig
from src.integrations.mcp_client import _OAuth2Auth

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 300


class _AuthenticatedA2AAgent(A2AAgent):
    """A2AAgent subclass that injects OAuth2 auth into agent card fetches.

    The base ``A2AAgent.get_agent_card()`` creates a bare
    ``httpx.AsyncClient`` with no authentication, which fails with 401
    for endpoints that require OAuth2 (e.g. AgentCore Runtime).  This
    subclass overrides ``get_agent_card()`` to use an authenticated
    httpx client so that the card fetch carries a valid Bearer token.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        name: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        http_auth: httpx.Auth | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            endpoint,
            name=name,
            timeout=timeout,
        )
        self._http_auth = http_auth
        self._http_client = http_client

    async def get_agent_card(self):
        """Fetch the agent card using an authenticated httpx client.

        After fetching, overrides the card's ``url`` with the configured
        endpoint.  AgentCore-hosted agents report an internal URL
        (e.g. ``http://localhost:8081``) in their card which is not
        reachable from external callers.  The registered endpoint URL
        (the AgentCore Runtime invocation URL) is the correct target.

        A trailing slash is appended if absent so that the A2A JSON-RPC
        POST targets the proxied root path (``/``) of the A2A server
        rather than the BedrockAgentCoreApp ``/invocations`` handler.
        """
        if self._agent_card is not None:
            return self._agent_card

        # Fetch the raw card JSON and apply defaults for fields that older
        # A2A agents may omit but the current SDK requires, then validate.
        base_url = self.endpoint.rstrip("/")
        if "salesforce.com/einstein/ai-agent" in base_url:
            card_url = f"{base_url}/v1/card"
        else:
            card_url = f"{base_url}/{AGENT_CARD_WELL_KNOWN_PATH.lstrip('/')}"

        async with httpx.AsyncClient(timeout=self.timeout, auth=self._http_auth) as client:
            response = await client.get(card_url)
            response.raise_for_status()
            card_data: dict = response.json()

        logger.info("Fetched agent card JSON from %s: %s", card_url, _json.dumps(card_data, indent=2, default=str))

        # Backfill required fields that older agent cards may omit
        card_data.setdefault("defaultInputModes", ["application/json"])
        card_data.setdefault("defaultOutputModes", ["application/json"])
        for skill in card_data.get("skills", []):
            skill.setdefault("tags", [])

        self._agent_card = AgentCard.model_validate(card_data)

        # AgentCore-hosted agents report an internal URL (e.g.
        # http://localhost:8081) that is not reachable externally.
        # Override with the configured endpoint for those agents.
        # For non-AgentCore agents (e.g. Salesforce), trust the card's URL
        # since the RPC endpoint may differ from the base URL.
        if "salesforce.com/einstein/ai-agent" not in self.endpoint:
            external_url = self.endpoint.rstrip("/") + "/"
            logger.info(
                "Overriding agent card url '%s' → '%s' (endpoint='%s')",
                self._agent_card.url,
                external_url,
                self.endpoint,
            )
            self._agent_card.url = external_url
        else:
            logger.info(
                "Using agent card url '%s' as-is (endpoint='%s')",
                self._agent_card.url,
                self.endpoint,
            )

        if self.name is None and self._agent_card.name:
            self.name = self._agent_card.name
        if self.description is None and self._agent_card.description:
            self.description = self._agent_card.description

        logger.info(
            "agent=<%s>, endpoint=<%s> | agent card ready, message url='%s'",
            self.name, self.endpoint, self._agent_card.url,
        )
        return self._agent_card

    async def _send_message(self, prompt) -> AsyncIterator[Any]:
        """Send message to remote A2A agent.

        Checks ``agent_card.capabilities.streaming`` to decide whether
        to use ``message/stream`` or ``message/send``.  The response
        may arrive as either:
        - **SSE** (``text/event-stream``) — streaming format where
          each SSE event carries a JSON-RPC response.
        - **Plain JSON** (``application/json``) — when the proxy
          collapses the stream or the agent only supports send.

        Yields the same event shapes as the SDK's ``BaseClient.send_message``:
        - ``Message`` for direct message responses
        - ``(Task, None)`` for initial task objects
        - ``(Task, TaskStatusUpdateEvent)`` for status updates
        - ``(Task, TaskArtifactUpdateEvent)`` for artifact updates
        """
        agent_card = await self.get_agent_card()
        message = convert_input_to_message(prompt)

        params = MessageSendParams(
            message=message,
            configuration=MessageSendConfiguration(blocking=True),
        )

        # Use message/stream only if the agent advertises streaming support;
        # otherwise go directly to message/send.
        supports_streaming = getattr(
            getattr(agent_card, "capabilities", None), "streaming", False,
        )
        if supports_streaming:
            methods = [
                (SendStreamingMessageRequest, "message/stream"),
                (SendMessageRequest, "message/send"),
            ]
        else:
            methods = [
                (SendMessageRequest, "message/send"),
            ]
        logger.info(
            "Agent '%s' streaming=%s, methods=%s",
            self.name, supports_streaming, [m for _, m in methods],
        )

        for rpc_request_cls, method_label in methods:
            rpc_request = rpc_request_cls(params=params, id=str(uuid4()))
            payload = rpc_request.model_dump(mode="json", exclude_none=True)

            logger.info(
                "Sending %s to '%s' (url=%s)",
                method_label, self.name, agent_card.url,
            )

            # Use streaming request so we can inspect Content-Type before
            # deciding how to consume the body (SSE vs plain JSON).
            async with self._http_client.stream(
                "POST", agent_card.url, json=payload, timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                logger.info(
                    "A2A response from '%s' (%s): status=%d content_type='%s'",
                    self.name, method_label, response.status_code, content_type,
                )

                if "text/event-stream" in content_type:
                    # SSE streaming response — parse events and track task
                    # state so we yield the same (Task, UpdateEvent) tuples
                    # the SDK's BaseClient does.
                    #
                    # We track the current Task manually rather than using
                    # ClientTaskManager because the manager raises on
                    # duplicate Task events, which some A2A servers emit
                    # (e.g. initial Task followed by Task with final status).
                    #
                    # Message events are buffered and yielded LAST because
                    # stream_async picks the last "complete" event for text
                    # extraction.  Both Message and (Task, None) count as
                    # complete, so if (Task, None) comes after Message the
                    # actual content (in Message.parts) is lost.
                    current_task: Task | None = None
                    buffered_messages: list[Message] = []
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        raw = line[len("data:"):].strip()
                        if not raw:
                            continue

                        data = _json.loads(raw)
                        logger.debug(
                            "SSE event from '%s': %s",
                            self.name, _json.dumps(data, default=str)[:500],
                        )

                        result = self._extract_rpc_result(data)
                        if result is None:
                            continue

                        if isinstance(result, Message):
                            buffered_messages.append(result)
                        elif isinstance(result, Task):
                            current_task = result
                            yield (current_task, None)
                        elif isinstance(result, (TaskStatusUpdateEvent, TaskArtifactUpdateEvent)):
                            if current_task is None:
                                current_task = Task(
                                    id=result.task_id,
                                    context_id=result.context_id,
                                    status=result.status if isinstance(result, TaskStatusUpdateEvent) else TaskStatus(state=TaskState.unknown),
                                )
                            if isinstance(result, TaskStatusUpdateEvent):
                                current_task.status = result.status
                            yield (current_task, result)
                        else:
                            logger.debug("Skipping unknown result type: %s", type(result).__name__)

                    # Yield buffered Messages last so they become the
                    # last_complete_event in stream_async.
                    for msg in buffered_messages:
                        yield msg
                    return
                else:
                    # Plain JSON response (proxy-collapsed or non-streaming)
                    body = await response.aread()
                    body_text = body.decode()
                    if not body_text.strip():
                        logger.error(
                            "Empty response body from '%s' (%s)",
                            self.name, method_label,
                        )
                        raise RuntimeError(
                            f"A2A agent '{self.name}' returned empty response"
                        )

                    data = _json.loads(body_text)
                    logger.info(
                        "A2A JSON response from '%s' (%s): %s",
                        self.name, method_label,
                        _json.dumps(data, indent=2, default=str)[:2000],
                    )

                    # Check for Method not found — fall back to next method
                    result = self._extract_rpc_result(data)
                    if result is None:
                        # Parsed as error — check if we should fall back
                        continue

                    if isinstance(result, Message):
                        yield result
                    elif isinstance(result, Task):
                        yield (result, None)
                    else:
                        # TaskStatusUpdateEvent / TaskArtifactUpdateEvent
                        # without a preceding Task — shouldn't happen for
                        # non-streaming, but handle gracefully
                        yield result
                    return

        raise RuntimeError(f"A2A agent '{self.name}' rejected both message/stream and message/send")

    def _extract_rpc_result(self, data: dict) -> Any | None:
        """Parse a JSON-RPC response and return the result object.

        Returns the typed result (``Message``, ``Task``,
        ``TaskStatusUpdateEvent``, or ``TaskArtifactUpdateEvent``)
        or ``None`` if the event cannot be parsed.

        Raises ``A2AClientJSONRPCError`` on JSON-RPC error responses,
        **except** for *Method not found* errors which return ``None``
        to allow the caller to fall back to an alternative method.
        """
        try:
            parsed = SendStreamingMessageResponse.model_validate(data)
        except Exception:
            try:
                parsed = SendMessageResponse.model_validate(data)
            except Exception:
                logger.debug("Skipping unparseable event: %s", str(data)[:200])
                return None

        if isinstance(parsed.root, JSONRPCErrorResponse):
            error_msg = getattr(parsed.root.error, "message", "")
            if "Method not found" in error_msg:
                logger.warning("Server returned: %s", error_msg)
                return None
            raise A2AClientJSONRPCError(parsed.root)

        return parsed.root.result


def _build_a2a_tool(config: A2AAgentConfig) -> Any:
    """Build a Strands tool function that delegates to a remote A2A agent.

    For OAuth2-authenticated agents, creates an ``_AuthenticatedA2AAgent``
    that injects Bearer tokens via the AgentCore Identity service into
    both the agent card fetch and message sending requests.

    Args:
        config: A2A agent configuration with endpoint and optional auth.

    Returns:
        A ``@tool``-decorated callable suitable for passing to a Strands Agent.
    """
    if config.auth and config.auth.type == "oauth2" and config.auth.credential_provider_name:
        scope_list = config.auth.scopes.split() if config.auth.scopes else []
        delegation_mode = (config.auth.delegation_mode or "m2m").lower()
        user_access_token = os.environ.get("USER_ACCESS_TOKEN") or None
        auth = _OAuth2Auth(
            credential_provider_name=config.auth.credential_provider_name,
            scopes=scope_list,
            delegation_mode=delegation_mode,
            user_access_token=user_access_token if delegation_mode == "obo" else None,
        )
        logger.info(
            "A2A agent '%s' configured with OAuth2 auth (credential_provider=%s, scopes=%s, delegation_mode=%s)",
            config.name,
            config.auth.credential_provider_name,
            scope_list,
            delegation_mode,
        )

        # Long-lived authenticated httpx client used for both agent card
        # fetch and message sending (bypasses the SDK's SSE transport
        # which is incompatible with AgentCore's JSON proxy).
        authenticated_client = httpx.AsyncClient(auth=auth, timeout=_DEFAULT_TIMEOUT)

        a2a_agent = _AuthenticatedA2AAgent(
            endpoint=config.endpoint_url,
            name=config.name,
            http_auth=auth,
            http_client=authenticated_client,
        )
    else:
        a2a_agent = A2AAgent(
            endpoint=config.endpoint_url,
            name=config.name,
        )

    agent_name = config.name
    agent_endpoint = config.endpoint_url
    agent_description = f"Send a message to the '{agent_name}' A2A agent."

    @tool(name=f"a2a_{agent_name}", description=agent_description)
    def a2a_tool(message: str) -> str:
        """Forward a message to the remote A2A agent and return its response."""
        logger.info(
            "Invoking A2A agent '%s' at endpoint '%s' with message length=%d",
            agent_name, agent_endpoint, len(message),
        )
        try:
            result = a2a_agent(message)
            logger.info("A2A agent '%s' returned successfully", agent_name)
            return str(result.message)
        except Exception as e:
            logger.error(
                "A2A agent '%s' invocation failed: %s: %s",
                agent_name, type(e).__name__, e,
                exc_info=True,
            )
            raise

    logger.info("Created A2A tool for agent '%s' at %s", config.name, config.endpoint_url)
    return a2a_tool


def create_a2a_clients(agents: list[A2AAgentConfig]) -> list[Any]:
    """Create A2A tool wrappers for all enabled agent configurations.

    Each enabled A2A agent is wrapped in a Strands ``@tool`` function using
    ``A2AAgent`` from the Strands SDK.  The returned tools can be passed
    directly to a Strands ``Agent`` constructor.

    Args:
        agents: List of A2A agent configurations.

    Returns:
        List of ``@tool``-decorated callables, one per enabled agent.
    """
    tools: list[Any] = []

    for agent_cfg in agents:
        if not agent_cfg.enabled:
            logger.debug("Skipping disabled A2A agent '%s'", agent_cfg.name)
            continue

        a2a_tool = _build_a2a_tool(agent_cfg)
        tools.append(a2a_tool)

    logger.info("Initialised %d A2A tool(s)", len(tools))
    return tools
