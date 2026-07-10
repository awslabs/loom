"""AgentCore Runtime entry point for the Strands agent.

This module uses ``BedrockAgentCoreApp`` from the ``bedrock-agentcore``
SDK to expose the agent via the ``/invocations`` and ``/ping`` endpoints
required by AgentCore Runtime (port 8080, linux/arm64 container).

The ``@app.entrypoint`` decorator registers the handler so the SDK
manages the HTTP plumbing, health-check, and invocation lifecycle.

The handler is async and yields streaming events via
``agent.stream_async()`` so partial text chunks are emitted as they are
generated (R5).

Two invocation paths are supported:
- HTTP streaming (``@app.entrypoint``): Uses Strands interrupt mechanism
  for HITL approval (Methods 1 & 2). Also supports MCP elicitation
  (Method 3) via a two-invocation pattern: the first invocation blocks
  the tool and ends the stream with an elicitation event; the second
  invocation provides the user's response and resumes the agent task.
- WebSocket (``@app.websocket``): Supports full MCP elicitation (Method 4)
  via bidirectional messaging. The elicitation callback relays requests to
  the WebSocket client and awaits the response inline.
"""

import asyncio
import dataclasses
import json
import logging
import os
import sys
import threading
from typing import Any, AsyncGenerator

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands.types.exceptions import MaxTokensReachedException, ToolProviderException

from strands.models import Model
from strands.models.bedrock import BedrockModel

from mcp.types import ElicitResult

from src.config import AgentConfig, MCPServerConfig, AuthConfig, load_config
from src.agent import _build_model, attach_mcp_tools, build_agent
from src.integrations.approval import ApprovalHook
from src.integrations.mcp_client import has_deferred_auth_servers, _build_transport_callable, drain_token_info_events, reset_token_info_state, set_user_access_token
from src.telemetry import trace_invocation

# Configure the root Python logger so all modules (agent, mcp_client, etc.)
# emit to stdout where AgentCore Runtime captures them for CloudWatch.
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
    force=True,
)

app = BedrockAgentCoreApp()
logger = app.logger

# Module-level state, initialized once at cold start
_agent = None
_config: AgentConfig | None = None
_mcp_attached = False
_dynamic_mcp_clients: dict[str, Any] = {}  # keyed by (server_name, actor_id)
_default_model: Model | None = None
_model_cache: dict[tuple[str, str, str], Model] = {}  # keyed by (provider, model_id, base_url)
_approval_hook: ApprovalHook | None = None
_code_interpreter = None  # AgentCoreCodeInterpreter instance for pre-warm

# Elicitation bridge state (persists across HTTP invocations on same container)
# When a tool calls ctx.elicit(), the agent task blocks. The HTTP response ends
# with an elicitation event. The next invocation provides the response and
# resumes reading from the same running agent task.
_elicit_events: dict[str, threading.Event] = {}  # session_id -> Event to unblock callback
_elicit_responses: dict[str, dict[str, Any]] = {}  # session_id -> response from user
_elicit_queues: dict[str, asyncio.Queue] = {}  # session_id -> event queue from agent task
_agent_tasks: dict[str, asyncio.Task] = {}  # session_id -> background agent task


def _prewarm_code_interpreter(ci) -> None:
    """Pre-warm the code interpreter session in a background thread.

    Session creation takes 30-60s. Calling _ensure_session here at container
    startup means the session is READY before the first tool invocation arrives,
    avoiding the AgentCore Runtime HTTP streaming timeout.
    """
    try:
        logger.info("Pre-warming code interpreter session in background thread")
        ci._ensure_session(None)
        logger.info("Code interpreter session pre-warm complete")
    except Exception as e:
        logger.warning("Code interpreter pre-warm failed: %s. Session will be created on first use.", e)


def _get_agent():
    """Get or initialize the singleton agent instance.

    If the configuration includes OAuth2-authenticated MCP servers,
    MCP client initialization is deferred until the first invocation
    when the workload access token is available in the request context.
    """
    global _agent, _config, _default_model, _approval_hook, _code_interpreter
    if _agent is None:
        _config = load_config()
        defer_mcp = has_deferred_auth_servers(_config.integrations.mcp_servers)
        if defer_mcp:
            logger.info("Deferring MCP client init — authenticated servers require invocation context")
        _agent, _approval_hook, _code_interpreter = build_agent(_config, defer_mcp=defer_mcp)
        _default_model = _agent.model
        if _code_interpreter is not None:
            t = threading.Thread(target=_prewarm_code_interpreter, args=(_code_interpreter,), daemon=True)
            t.start()
        logger.info("Agent initialized successfully")
    return _agent


def _ensure_mcp_tools(actor_id: str = ""):
    """Attach MCP tools on the first invocation when context is available."""
    global _mcp_attached
    if _mcp_attached or _config is None:
        return

    static_servers = [s for s in _config.integrations.mcp_servers if s.enabled and not s.dynamic_only]
    if not static_servers:
        _mcp_attached = True
        return

    if actor_id:
        for server in static_servers:
            if server.auth and server.auth.type == "api_key" and "{actor_id}" in server.auth.credentials_secret_arn:
                server.auth.credentials_secret_arn = server.auth.credentials_secret_arn.replace("{actor_id}", actor_id)

    logger.info("Attaching MCP tools (first invocation with context)")
    try:
        attach_mcp_tools(_agent, static_servers)
        _mcp_attached = True
    except Exception as e:
        logger.warning("Failed to attach MCP tools: %s. Will retry on next invocation.", e)


def _attach_dynamic_mcp_servers(agent_instance, dynamic_servers: list[dict[str, Any]], actor_id: str, elicitation_callback=None) -> None:
    """Attach dynamically-requested MCP servers for this invocation.

    Maintains a pool keyed by (server_name, actor_id). New servers are
    started and registered; previously-connected servers are reused.
    Skips servers whose tools are already registered (e.g. from static config).
    """
    from strands.tools.mcp import MCPClient

    for server_data in dynamic_servers:
        name = server_data.get("name", "")
        suffix = ":elicit" if elicitation_callback else ""
        pool_key = f"{name}:{actor_id}{suffix}"

        if pool_key in _dynamic_mcp_clients:
            logger.debug("Reusing cached dynamic MCP client for '%s'", name)
            continue

        auth_data = server_data.get("auth")
        auth_config = None
        if auth_data:
            auth_config = AuthConfig(
                type=auth_data.get("type", ""),
                credentials_secret_arn=auth_data.get("credentials_secret_arn", ""),
                api_key_header_name=auth_data.get("api_key_header_name", "x-api-key"),
                well_known_endpoint=auth_data.get("well_known_endpoint", ""),
                credential_provider_name=auth_data.get("credential_provider_name", ""),
                scopes=auth_data.get("scopes", ""),
                delegation_mode=(auth_data.get("delegation_mode") or "m2m").lower(),
                obo_grant_type=auth_data.get("obo_grant_type", ""),
            )

        # Skip OAuth2 servers with no usable credentials — they would connect
        # unauthenticated and fail.
        if auth_config and auth_config.type == "oauth2" and not auth_config.credential_provider_name and not auth_config.credentials_secret_arn:
            logger.info("Skipping dynamic MCP server '%s' — OAuth2 without credentials", name)
            continue

        config = MCPServerConfig(
            name=name,
            enabled=True,
            transport=server_data.get("transport", "streamable_http"),
            endpoint_url=server_data.get("endpoint_url", ""),
            auth=auth_config,
        )

        # When attaching with elicitation, remove conflicting static tools first
        if elicitation_callback:
            from strands.tools.mcp.mcp_agent_tool import MCPAgentTool
            to_remove = [
                tname for tname, tool in agent_instance.tool_registry.registry.items()
                if isinstance(tool, MCPAgentTool)
            ]
            for tname in to_remove:
                del agent_instance.tool_registry.registry[tname]
            if to_remove:
                logger.info("Cleared %d static MCP tool(s) for elicitation re-attach: %s", len(to_remove), to_remove)

        transport_callable = _build_transport_callable(config)
        client = MCPClient(transport_callable, elicitation_callback=elicitation_callback)

        strands_mcp_logger = logging.getLogger("strands.tools.mcp.mcp_client")
        strands_registry_logger = logging.getLogger("strands.tools.registry")
        prev_mcp_level = strands_mcp_logger.level
        prev_registry_level = strands_registry_logger.level
        strands_mcp_logger.setLevel(logging.CRITICAL)
        strands_registry_logger.setLevel(logging.CRITICAL)
        try:
            agent_instance.tool_registry.process_tools([client])
            _dynamic_mcp_clients[pool_key] = client
            logger.info("Attached dynamic MCP server '%s' for actor '%s' (elicit=%s)", name, actor_id, bool(elicitation_callback))
        except BaseException as e:
            logger.warning("Failed to attach dynamic MCP server '%s' for actor '%s': %s", name, actor_id, e)
            try:
                client.stop()
            except BaseException:
                pass
        finally:
            strands_mcp_logger.setLevel(prev_mcp_level)
            strands_registry_logger.setLevel(prev_registry_level)


@app.entrypoint
async def invoke(payload: dict[str, Any]) -> AsyncGenerator[Any, None]:
    """Handle an AgentCore Runtime invocation with streaming response.

    Supports three invocation modes:
    1. Normal prompt → stream text back
    2. interruptResponse → resume from ApprovalHook interrupt
    3. elicitationResponse → resume a blocked elicitation callback

    When ``supports_elicitation`` is true in the payload, dynamic MCP servers
    are attached with an elicitation callback. If the tool calls ctx.elicit(),
    the agent task blocks while the HTTP response yields the elicitation event
    and ends. The next invocation with ``elicitationResponse`` unblocks it.
    """
    agent = _get_agent()

    session_id = payload.get("session_id", "")
    actor_id = payload.get("actor_id") or "loom-agent"

    # Make user access token available for OBO token exchange flows
    set_user_access_token(payload.get("user_access_token"))

    reset_token_info_state()
    _ensure_mcp_tools(actor_id)

    # --- Handle elicitation response (resume a blocked tool) ---
    elicitation_response = payload.get("elicitationResponse")
    if elicitation_response and session_id in _elicit_events:
        logger.info("Resuming elicitation for session_id=%s action=%s", session_id, elicitation_response.get("action"))
        _elicit_responses[session_id] = elicitation_response
        _elicit_events[session_id].set()

        queue = _elicit_queues.get(session_id)
        if queue:
            async for event in _drain_queue(queue):
                yield event
        _cleanup_elicit_state(session_id)
        return

    # --- Determine if elicitation is enabled for this invocation ---
    supports_elicitation = payload.get("supports_elicitation", False)

    elicitation_callback = None
    if supports_elicitation:
        # Capture the main event loop so the callback (which runs in the
        # MCPClient's background thread) can schedule work on it.
        _main_loop = asyncio.get_event_loop()

        async def elicitation_callback(context, params):
            """Block until the next invocation provides the user's response.

            This callback runs in the MCPClient's background thread event loop.
            The asyncio.Queue and Event live on the main loop, so we use
            run_coroutine_threadsafe + wrap_future to bridge the gap.
            """
            elicit_id = f"elicit-{session_id}-{id(params)}"
            logger.info("Elicitation requested: id=%s message=%s", elicit_id, params.message[:100])

            schema = None
            if hasattr(params, "requestedSchema") and params.requestedSchema:
                schema = params.requestedSchema

            # Create the threading.Event BEFORE putting the elicitation on the
            # queue, so the main loop sees it in _elicit_events when _drain_queue
            # returns (avoids race where cleanup fires before event is stored).
            t_event = threading.Event()
            _elicit_events[session_id] = t_event

            queue = _elicit_queues.get(session_id)
            if queue:
                fut = asyncio.run_coroutine_threadsafe(
                    queue.put({"_elicitation": {"id": elicit_id, "message": params.message, "schema": schema}}),
                    _main_loop,
                )
                await asyncio.wrap_future(fut)

            # Block the background thread until the resume sets the event
            await asyncio.get_event_loop().run_in_executor(None, t_event.wait, 600)

            response_data = _elicit_responses.pop(session_id, {})
            _elicit_events.pop(session_id, None)
            action = response_data.get("action", "decline")
            content = response_data.get("content")
            logger.info("Elicitation response: action=%s", action)
            return ElicitResult(action=action, content=content)

    dynamic_servers = payload.get("dynamic_mcp_servers")
    if dynamic_servers:
        _attach_dynamic_mcp_servers(agent, dynamic_servers, actor_id, elicitation_callback=elicitation_callback)

    # Re-attach static MCP servers with elicitation callback if needed
    if supports_elicitation and elicitation_callback and _config and _mcp_attached:
        elicit_servers = [s for s in _config.integrations.mcp_servers if s.enabled and not s.dynamic_only]
        if elicit_servers:
            static_as_dynamic = [
                {"name": s.name, "transport": s.transport, "endpoint_url": s.endpoint_url,
                 "auth": {"type": s.auth.type, "credentials_secret_arn": s.auth.credentials_secret_arn,
                          "api_key_header_name": s.auth.api_key_header_name,
                          "well_known_endpoint": s.auth.well_known_endpoint,
                          "credential_provider_name": s.auth.credential_provider_name,
                          "scopes": s.auth.scopes,
                          "delegation_mode": s.auth.delegation_mode,
                          "obo_grant_type": s.auth.obo_grant_type,
                          "audience": s.auth.audience} if s.auth else None}
                for s in elicit_servers
            ]
            _attach_dynamic_mcp_servers(agent, static_as_dynamic, actor_id, elicitation_callback=elicitation_callback)
            logger.info("Re-attached %d static MCP server(s) with elicitation callback", len(elicit_servers))

    # Inject approval policies from the invocation payload (sent by Loom)
    invocation_policies = payload.get("approval_policies")
    if invocation_policies and isinstance(invocation_policies, list) and _approval_hook:
        _approval_hook.policies = invocation_policies
        logger.info("Injected %d approval policy(ies) from payload", len(invocation_policies))

    # Runtime model override
    runtime_model_id = payload.get("model_id")
    if runtime_model_id and _config:
        cache_key = (_config.provider, runtime_model_id, _config.base_url)
        if cache_key not in _model_cache:
            _model_cache[cache_key] = _build_model(dataclasses.replace(_config, model_id=runtime_model_id))
            logger.info("Created cached model for runtime override: provider=%s model_id=%s", _config.provider, runtime_model_id)
        agent.model = _model_cache[cache_key]
    elif _default_model:
        agent.model = _default_model

    # Determine if this is a new prompt or an interrupt resume
    interrupt_responses = payload.get("interruptResponse")
    if interrupt_responses and isinstance(interrupt_responses, list):
        agent_input = interrupt_responses
        logger.info("Resuming from interrupt session_id=%s with %d response(s)", session_id, len(interrupt_responses))
    else:
        agent_input = payload.get("prompt", "")
        logger.info("Processing invocation session_id=%s actor_id=%s model=%s", session_id, actor_id, runtime_model_id or _config.model_id if _config else "unknown")

    # Set user_role in agent state for Method 2 tool-context approval
    user_role = payload.get("user_role")
    if user_role:
        agent.state.set("user_role", user_role)

    if supports_elicitation:
        # Run agent in background task so elicitation can block without stopping the stream
        queue: asyncio.Queue = asyncio.Queue()
        _elicit_queues[session_id] = queue

        async def _run_agent_task():
            try:
                with trace_invocation(invocation_id=session_id) as span:
                    span.set_attribute("agent.session_id", session_id)
                    result = None
                    stream = agent.stream_async(agent_input, invocation_state={"session_id": session_id, "actor_id": actor_id})
                    async for event in stream:
                        if isinstance(event, dict):
                            if "result" in event:
                                result = event["result"]
                                continue
                            text = None
                            data = event.get("data")
                            if isinstance(data, str):
                                text = data
                            elif isinstance(event.get("delta"), dict):
                                text = event["delta"].get("text")
                            if text:
                                await queue.put(text)
                                continue
                            chunk = event.get("event")
                            if isinstance(chunk, dict):
                                if "contentBlockStart" in chunk:
                                    start = chunk["contentBlockStart"].get("start", {})
                                    tool_use = start.get("toolUse")
                                    if isinstance(tool_use, dict) and tool_use.get("name"):
                                        logger.info("Tool call detected: %s", tool_use["name"])
                                        await queue.put({"tool_use": {"name": tool_use["name"], "id": tool_use.get("toolUseId", "")}})

                        # Drain any OBO token info events acquired during tool execution
                        for ti in drain_token_info_events():
                            await queue.put({"token_info": ti})

                    if result and getattr(result, "stop_reason", None) == "interrupt":
                        interrupts = getattr(result, "interrupts", [])
                        logger.info("Agent interrupted with %d pending approval(s)", len(interrupts))
                        await queue.put({"interrupt": {"stopReason": "interrupt", "interrupts": [{"id": i.id, "name": i.name, "reason": i.reason} for i in interrupts]}})
            except MaxTokensReachedException:
                await queue.put("\n\n[Response truncated: the model reached its maximum output token limit.]")
            except ToolProviderException as e:
                logger.warning("Tool provider error session_id=%s: %s", session_id, e)
                await queue.put({"_error": f"A tool provider encountered an error: {e}"})
            except Exception as e:
                logger.exception("Agent task error session_id=%s (%s): %s", session_id, type(e).__name__, e)
                await queue.put({"_error": f"{type(e).__name__}: {e}" if str(e) else type(e).__name__})
            finally:
                await queue.put(None)

        _agent_tasks[session_id] = asyncio.create_task(_run_agent_task())
        async for event in _drain_queue(queue):
            yield event
        if session_id not in _elicit_events:
            _cleanup_elicit_state(session_id)
    else:
        # Simple path: no elicitation, stream directly
        with trace_invocation(invocation_id=session_id) as span:
            span.set_attribute("agent.session_id", session_id)
            try:
                result = None
                stream = agent.stream_async(agent_input, invocation_state={"session_id": session_id, "actor_id": actor_id})
                async for event in stream:
                    if isinstance(event, dict):
                        if "result" in event:
                            result = event["result"]
                            continue
                        text = None
                        data = event.get("data")
                        if isinstance(data, str):
                            text = data
                        elif isinstance(event.get("delta"), dict):
                            text = event["delta"].get("text")
                        if text:
                            yield text
                            continue
                        event_keys = list(event.keys())
                        logger.debug("Stream event keys: %s", event_keys)
                        chunk = event.get("event")
                        if isinstance(chunk, dict):
                            if "contentBlockStart" in chunk:
                                start = chunk["contentBlockStart"].get("start", {})
                                tool_use = start.get("toolUse")
                                if isinstance(tool_use, dict) and tool_use.get("name"):
                                    logger.info("Tool call detected: %s", tool_use["name"])
                                    yield {"tool_use": {"name": tool_use["name"], "id": tool_use.get("toolUseId", "")}}

                    # Drain any OBO token info events acquired during tool execution
                    for ti in drain_token_info_events():
                        yield {"token_info": ti}

                if result and getattr(result, "stop_reason", None) == "interrupt":
                    interrupts = getattr(result, "interrupts", [])
                    logger.info("Agent interrupted with %d pending approval(s)", len(interrupts))
                    yield {"interrupt": {"stopReason": "interrupt", "interrupts": [{"id": i.id, "name": i.name, "reason": i.reason} for i in interrupts]}}
            except MaxTokensReachedException:
                logger.warning("Max tokens reached for session_id=%s", session_id)
                yield "\n\n[Response truncated: the model reached its maximum output token limit. Try a shorter prompt or a model with a higher token limit.]"
            except ToolProviderException as e:
                logger.warning("Tool provider error session_id=%s: %s", session_id, e)
                yield f"\n\nA tool provider encountered an error: {e}"
            except Exception as e:
                logger.exception("Agent stream error session_id=%s (%s): %s", session_id, type(e).__name__, e)
                detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                yield f"\n\nError: {detail}"


async def _drain_queue(queue: asyncio.Queue) -> AsyncGenerator[Any, None]:
    """Yield events from the agent task queue until sentinel or elicitation."""
    while True:
        event = await queue.get()
        if event is None:
            break
        if isinstance(event, dict):
            if "_elicitation" in event:
                yield {"elicitation": event["_elicitation"]}
                return
            if "_error" in event:
                yield f"\n\nError: {event['_error']}"
                break
        yield event


def _cleanup_elicit_state(session_id: str) -> None:
    """Remove elicitation bridge state for a session."""
    _elicit_events.pop(session_id, None)
    _elicit_responses.pop(session_id, None)
    _elicit_queues.pop(session_id, None)
    _agent_tasks.pop(session_id, None)


@app.websocket
async def ws_invoke(websocket, context) -> None:
    """WebSocket handler for MCP elicitation support (Method 4).

    Bidirectional WebSocket enables the elicitation callback to send
    requests to the client and await responses inline during tool execution.

    Protocol:
    - Client sends: {"type": "prompt", "prompt": "...", ...}
    - Server sends: {"type": "text", "content": "..."}  (streaming tokens)
    - Server sends: {"type": "tool_use", "name": "..."}  (tool call notification)
    - Server sends: {"type": "elicitation", "message": "...", "id": "..."}
    - Client sends: {"type": "elicitation_response", "id": "...", "action": "accept|decline"}
    - Server sends: {"type": "result", "content": "..."}  (final result)
    - Server sends: {"type": "error", "content": "..."}  (on failure)
    """
    await websocket.accept()

    agent = _get_agent()
    elicit_event = asyncio.Event()
    elicit_response: dict[str, Any] = {}

    async def elicitation_callback(ctx, params):
        elicit_id = f"elicit-{id(params)}"
        await websocket.send_json({
            "type": "elicitation",
            "id": elicit_id,
            "message": params.message,
        })
        elicit_event.clear()
        await elicit_event.wait()
        action = elicit_response.pop("action", "decline")
        content = elicit_response.pop("content", {})
        return ElicitResult(action=action, content=content)

    try:
        pending_recv = None
        while True:
            if pending_recv is None:
                pending_recv = asyncio.ensure_future(websocket.receive_json())

            data = await pending_recv
            pending_recv = None
            msg_type = data.get("type", "prompt")

            if msg_type == "elicitation_response":
                elicit_response["action"] = data.get("action", "decline")
                elicit_response["content"] = data.get("content", {})
                elicit_event.set()
                continue

            if msg_type != "prompt":
                continue

            prompt = data.get("prompt", "")
            session_id = data.get("session_id", "")
            actor_id = data.get("actor_id") or "loom-agent"

            set_user_access_token(data.get("user_access_token"))
            _ensure_mcp_tools(actor_id)

            dynamic_servers = data.get("dynamic_mcp_servers")
            if dynamic_servers:
                _attach_dynamic_mcp_servers(agent, dynamic_servers, actor_id)

            # Attach dynamic MCP servers with elicitation support
            dynamic_mcp_elicit = data.get("dynamic_mcp_servers_elicit")
            if dynamic_mcp_elicit:
                _attach_dynamic_mcp_servers_ws(agent, dynamic_mcp_elicit, actor_id, elicitation_callback)

            # Runtime model override
            runtime_model_id = data.get("model_id")
            if runtime_model_id and _config:
                cache_key = (_config.provider, runtime_model_id, _config.base_url)
                if cache_key not in _model_cache:
                    _model_cache[cache_key] = _build_model(dataclasses.replace(_config, model_id=runtime_model_id))
                agent.model = _model_cache[cache_key]
            elif _default_model:
                agent.model = _default_model

            # Run agent in executor so we can receive messages concurrently
            loop = asyncio.get_event_loop()

            def _run_agent(p=prompt):
                result = agent(p)
                return str(result)

            agent_task = asyncio.ensure_future(
                loop.run_in_executor(None, _run_agent)
            )

            while not agent_task.done():
                if pending_recv is None:
                    pending_recv = asyncio.ensure_future(websocket.receive_json())
                done, _ = await asyncio.wait(
                    {agent_task, pending_recv}, return_when=asyncio.FIRST_COMPLETED,
                )
                if pending_recv in done:
                    msg = pending_recv.result()
                    pending_recv = None
                    if msg.get("type") == "elicitation_response":
                        elicit_response["action"] = msg.get("action", "decline")
                        elicit_response["content"] = msg.get("content", {})
                        elicit_event.set()

            result_text = agent_task.result()
            await websocket.send_json({"type": "result", "content": result_text})

    except Exception as e:
        logger.exception("WebSocket handler error: %s", e)
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


def _attach_dynamic_mcp_servers_ws(
    agent_instance, dynamic_servers: list[dict[str, Any]], actor_id: str, elicitation_callback
) -> None:
    """Attach dynamic MCP servers with elicitation callback for WebSocket path."""
    from strands.tools.mcp import MCPClient
    from functools import partial
    from datetime import timedelta

    for server_data in dynamic_servers:
        name = server_data.get("name", "")
        pool_key = f"{name}:{actor_id}:ws"

        if pool_key in _dynamic_mcp_clients:
            logger.debug("Reusing cached dynamic MCP client (ws) for '%s'", name)
            continue

        auth_data = server_data.get("auth")
        auth_config = None
        if auth_data:
            auth_config = AuthConfig(
                type=auth_data.get("type", ""),
                credentials_secret_arn=auth_data.get("credentials_secret_arn", ""),
                api_key_header_name=auth_data.get("api_key_header_name", "x-api-key"),
                well_known_endpoint=auth_data.get("well_known_endpoint", ""),
                credential_provider_name=auth_data.get("credential_provider_name", ""),
                scopes=auth_data.get("scopes", ""),
                delegation_mode=(auth_data.get("delegation_mode") or "m2m").lower(),
                obo_grant_type=auth_data.get("obo_grant_type", ""),
            )

        config = MCPServerConfig(
            name=name,
            enabled=True,
            transport=server_data.get("transport", "streamable_http"),
            endpoint_url=server_data.get("endpoint_url", ""),
            auth=auth_config,
        )

        transport_callable = _build_transport_callable(config)
        client = MCPClient(transport_callable, elicitation_callback=elicitation_callback)

        strands_mcp_logger = logging.getLogger("strands.tools.mcp.mcp_client")
        strands_registry_logger = logging.getLogger("strands.tools.registry")
        prev_mcp_level = strands_mcp_logger.level
        prev_registry_level = strands_registry_logger.level
        strands_mcp_logger.setLevel(logging.CRITICAL)
        strands_registry_logger.setLevel(logging.CRITICAL)
        try:
            agent_instance.tool_registry.process_tools([client])
            _dynamic_mcp_clients[pool_key] = client
            logger.info("Attached dynamic MCP server (ws+elicit) '%s' for actor '%s'", name, actor_id)
        except BaseException as e:
            logger.warning("Failed to attach dynamic MCP server (ws) '%s': %s", name, e)
            try:
                client.stop()
            except BaseException:
                pass
        finally:
            strands_mcp_logger.setLevel(prev_mcp_level)
            strands_registry_logger.setLevel(prev_registry_level)


def main() -> None:
    """Local development entry point for running the agent interactively."""
    agent = _get_agent()
    print("Agent ready. Type your prompt (Ctrl+C to exit):")

    while True:
        try:
            prompt = input("\n> ")
            if not prompt.strip():
                continue
            result = agent(prompt)
            for chunk in result:
                if hasattr(chunk, "text") and chunk.text:
                    print(chunk.text, end="", flush=True)
                elif isinstance(chunk, str):
                    print(chunk, end="", flush=True)
            print()
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    app.run()
