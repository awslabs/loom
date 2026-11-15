"""AgentCore Runtime entry point for the ADK agent.

Uses ``BedrockAgentCoreApp`` from the ``bedrock-agentcore`` SDK exactly like
``agents/strands_agent/src/handler.py`` — the SDK's entrypoint/websocket
decorators are framework-agnostic (any callable), so the outer HTTP/WS
plumbing is identical. What differs is the streaming/pause-resume mechanics
underneath, since ADK's ``Runner``/session model and HITL primitive are
structurally different from Strands' ``stream_async``/interrupt mechanism.

Wire-contract parity with Strands (this is the part that matters — Loom's
``backend/app/routers/invocations.py`` consumes these event shapes and must
not need any changes):

- Plain ``str`` — a streamed text token.
- ``{"tool_use": {"name": str, "id": str}}`` — a tool call started.
- ``{"interrupt": {"stopReason": "interrupt", "interrupts": [{"id","name","reason"}]}}``
  — the agent paused waiting for approval. Translates ADK's
  ``adk_request_confirmation`` function-call pause into this shape; the
  emitted ``interrupt.id`` is ADK's own generated function-call id, so the
  resume path (``interruptResponse``) can look the pending call back up
  directly instead of needing a separate id-mapping table.
- Plain string error text — same ``"\\n\\nError: ..."`` formatting Strands uses.
- ``{"guardrail": {...}}`` — a Bedrock Guardrails intervention (enforce) or
  detection (monitor), see ``integrations/guardrails.py``.

Known parity gap: MCP elicitation (Strands' ``ctx.elicit()``/``{"elicitation": ...}``
event, Method 3/4 in the HITL reference implementations) and the
``{"token_info": ...}`` OBO-token-metadata event have no ADK equivalent wired
here — ADK's MCP tool layer has no elicitation callback hook analogous to
Strands' ``MCPClient(elicitation_callback=...)``. ADK agents built by this
package support tool-call approval (via ``adk_request_confirmation``, see
``integrations/approval.py``) but not the separate MCP elicitation pattern.

Session/state model: a module-level ``InMemorySessionService`` plus a
singleton ``Runner`` persist across invocations within the same
long-running container (mirroring Strands' module-level ``_agent``
singleton). Resuming a paused ``adk_request_confirmation`` call requires
looking up its function-call id from that same session's event history — a
fresh session per invocation would have no pending call to resolve against.
"""

import dataclasses
import logging
import os
import sys
import threading
from typing import Any, AsyncGenerator, Optional

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.agent import build_agent, build_model
from src.config import AgentConfig, GuardrailConfig, load_config
from src.integrations.code_interpreter import AgentCoreCodeInterpreterTools
from src.integrations.guardrails import (
    GUARDRAIL_NOT_ALLOWED_MESSAGE,
    GUARDRAIL_NOT_ALLOWED_TEXT,
    GuardrailSession,
    drain_trace_records,
    guardrail_cache_key,
    resolve_invocation_guardrail,
    start_trace_capture,
    stop_trace_capture,
)

# Configure the root Python logger so all modules emit to stdout where
# AgentCore Runtime captures them for CloudWatch — same as Strands' handler.
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
    force=True,
)

app = BedrockAgentCoreApp()
logger = app.logger

_APP_NAME = "loom_adk_agent"
_REQUEST_CONFIRMATION_FUNCTION_CALL_NAME = "adk_request_confirmation"

# Module-level state, initialized once at cold start
_config: Optional[AgentConfig] = None
_agent: Optional[LlmAgent] = None
_plugins: list[BasePlugin] = []
_code_interpreter: Optional[AgentCoreCodeInterpreterTools] = None
_session_service = InMemorySessionService()
_runner: Optional[Runner] = None
_default_model: Optional[Any] = None
# keyed by (provider, model_id, base_url, inline-guardrail key) so a
# per-invocation guardrail override gets its own model and runtime model
# overrides keep the guardrail.
_model_cache: dict[tuple[Any, ...], Any] = {}
_approval_matcher: Optional[Any] = None


def _prewarm_code_interpreter(ci: AgentCoreCodeInterpreterTools) -> None:
    """Pre-warm the code interpreter session in a background thread.

    Session creation takes 30-60s. Calling this at container startup means
    the session is READY before the first tool invocation, avoiding the
    AgentCore Runtime HTTP streaming timeout — same rationale as Strands'
    handler.
    """
    try:
        logger.info("Pre-warming code interpreter session")
        ci.prewarm()
        logger.info("Code interpreter session pre-warm complete")
    except Exception as e:
        logger.warning("Code interpreter pre-warm failed: %s. Session will be created on first use.", e)


async def _get_runner() -> Runner:
    """Get or initialize the singleton agent/Runner instance."""
    global _agent, _config, _plugins, _code_interpreter, _runner, _approval_matcher, _default_model
    if _runner is None:
        _config = load_config()
        _agent, _plugins, _code_interpreter, _approval_matcher = await build_agent(_config)
        _default_model = _agent.model
        if _code_interpreter is not None:
            t = threading.Thread(target=_prewarm_code_interpreter, args=(_code_interpreter,), daemon=True)
            t.start()
        _runner = Runner(
            app_name=_APP_NAME,
            agent=_agent,
            session_service=_session_service,
            plugins=_plugins,
        )
        logger.info("Agent initialized successfully")
    return _runner


async def _get_or_create_session(session_id: str, actor_id: str):
    """Get the existing session for this session_id, or create one."""
    session = await _session_service.get_session(app_name=_APP_NAME, user_id=actor_id, session_id=session_id)
    if session is None:
        session = await _session_service.create_session(
            app_name=_APP_NAME, user_id=actor_id, session_id=session_id
        )
    return session


def _extract_text(content: Optional[types.Content]) -> Optional[str]:
    if content is None or not content.parts:
        return None
    for part in content.parts:
        if part.text:
            return part.text
    return None


def _extract_tool_use(content: Optional[types.Content]) -> Optional[dict[str, str]]:
    if content is None or not content.parts:
        return None
    for part in content.parts:
        fc = part.function_call
        if fc and fc.name and fc.name != _REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
            return {"name": fc.name, "id": fc.id or ""}
    return None


def _extract_confirmation_request(content: Optional[types.Content]) -> Optional[dict[str, Any]]:
    """Return {"id", "name", "reason"} for a pending adk_request_confirmation
    call in this event's content, translating it into Strands' interrupt shape.
    """
    if content is None or not content.parts:
        return None
    for part in content.parts:
        fc = part.function_call
        if fc and fc.name == _REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
            original = (fc.args or {}).get("originalFunctionCall") or {}
            tool_confirmation = (fc.args or {}).get("toolConfirmation") or {}
            tool_name = original.get("name", "")
            return {
                "id": fc.id or "",
                "name": tool_name,
                "reason": {
                    "reason": f"Authorize {tool_name}",
                    "tool_name": tool_name,
                    "tool_input_summary": str(original.get("args", {}))[:500],
                    "hint": tool_confirmation.get("hint", ""),
                },
            }
    return None


def _find_pending_confirmation_call(session, interrupt_id: str):
    """Find the pending adk_request_confirmation FunctionCall by id in the
    session's event history, so a resume can be validated/targeted correctly.
    """
    for event in reversed(session.events):
        for fc in event.get_function_calls():
            if fc.name == _REQUEST_CONFIRMATION_FUNCTION_CALL_NAME and fc.id == interrupt_id:
                return fc
    return None


def _resolve_model_for_invocation(
    runtime_model_id: Optional[str], guardrail: Optional[GuardrailConfig] = None
):
    """Return a cached model instance for a runtime model-id and/or guardrail
    override, or None to use the agent's default model — mirrors Strands'
    per-invocation model-override caching. The cached model is built with
    the effective guardrail, so model overrides keep the guardrail.
    """
    if _config is None:
        return None
    if not runtime_model_id and guardrail == _config.guardrail:
        return None
    model_id = runtime_model_id or _config.model_id
    cache_key = (_config.provider, model_id, _config.base_url, guardrail_cache_key(guardrail, _config.provider))
    if cache_key not in _model_cache:
        _model_cache[cache_key] = build_model(dataclasses.replace(_config, model_id=model_id, guardrail=guardrail))
        logger.info(
            "Created cached model for runtime override: provider=%s model_id=%s guardrail=%s",
            _config.provider, model_id, guardrail.guardrail_id if guardrail else None,
        )
    return _model_cache[cache_key]


def _is_safety_stop(event: Any) -> bool:
    """True when an ADK event reports a SAFETY finish (LiteLLM ``content_filter``)."""
    safety = types.FinishReason.SAFETY
    return getattr(event, "error_code", None) == safety or getattr(event, "finish_reason", None) == safety


async def _run_turn(
    session_id: str,
    actor_id: str,
    content: Optional[types.Content],
    runtime_model_id: Optional[str] = None,
    guardrail_request: Any = None,
) -> AsyncGenerator[Any, None]:
    """Run one turn of the agent against the given session, yielding events
    in the same shapes Strands' handler yields (text tokens, tool_use dicts,
    interrupt dicts, guardrail dicts, or an error string).

    ``guardrail_request`` is the payload's optional ``guardrail`` override
    (Contract 2). It is validated here, after the config is loaded, and a
    rejected request yields the error text without calling the model.
    """
    runner = await _get_runner()

    configured_guardrail = _config.guardrail if _config is not None else None
    guardrail, guardrail_ok = resolve_invocation_guardrail(configured_guardrail, guardrail_request)
    if not guardrail_ok:
        logger.warning("Rejected payload guardrail override (not the primary or an allowed guardrail)")
        yield GUARDRAIL_NOT_ALLOWED_MESSAGE
        return

    session = await _get_or_create_session(session_id, actor_id)

    override_model = _resolve_model_for_invocation(runtime_model_id, guardrail)
    if _agent is not None:
        if override_model is not None:
            _agent.model = override_model
        elif _default_model is not None:
            # Restore the default so a previous invocation's override doesn't stick.
            _agent.model = _default_model

    provider = _config.provider if _config is not None else "bedrock"
    guardrail_session = GuardrailSession.create(guardrail, provider, session_id)
    capture_token = None
    safety_stop = False
    if guardrail_session:
        guardrail_session.start_input(_extract_text(content))
        if guardrail_session.is_enforce:
            capture_token = start_trace_capture()

    run_config = RunConfig(streaming_mode=StreamingMode.SSE)
    saw_any_partial = False

    try:
        async for event in runner.run_async(
            user_id=actor_id,
            session_id=session.id,
            new_message=content,
            run_config=run_config,
        ):
            if guardrail_session:
                for g_event in guardrail_session.poll() + guardrail_session.observe_model_calls(drain_trace_records()):
                    yield g_event

            if event.error_message:
                if guardrail_session and guardrail_session.is_enforce and _is_safety_stop(event):
                    # Guardrail intervention (LiteLLM maps guardrail_intervened
                    # to content_filter -> SAFETY): reported as a guardrail
                    # event, and the guardrail's blocked message is surfaced
                    # as text below instead of an error.
                    safety_stop = True
                else:
                    logger.warning("Agent event error session_id=%s: %s", session_id, event.error_message)
                    yield f"\n\nError: {event.error_message}"
                    continue

            confirmation = _extract_confirmation_request(event.content)
            if confirmation:
                logger.info("Agent paused for confirmation: id=%s tool=%s", confirmation["id"], confirmation["name"])
                yield {"interrupt": {"stopReason": "interrupt", "interrupts": [confirmation]}}
                continue

            tool_use = _extract_tool_use(event.content)
            if tool_use:
                logger.info("Tool call detected: %s", tool_use["name"])
                yield {"tool_use": tool_use}
                continue

            text = _extract_text(event.content)
            if text and (event.partial or not saw_any_partial):
                # Non-partial text is only yielded when no partial deltas
                # were seen: some model backends (e.g. non-streaming
                # providers routed through LiteLlm) never emit partial=True
                # deltas at all — only a single complete event. Yield it in
                # that case so text isn't silently dropped; once any partial
                # delta has been seen this turn, the final aggregated event
                # is assumed to duplicate that text and is not re-yielded.
                if guardrail_session:
                    guardrail_session.record_output(text)
                yield text
            if event.partial:
                saw_any_partial = True

        if guardrail_session:
            remaining = guardrail_session.observe_model_calls(drain_trace_records())
            remaining += await guardrail_session.finish(safety_stop)
            for g_event in remaining:
                yield g_event
    except Exception as e:
        logger.exception("Agent stream error session_id=%s (%s): %s", session_id, type(e).__name__, e)
        detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        yield f"\n\nError: {detail}"
    finally:
        if capture_token is not None:
            try:
                stop_trace_capture(capture_token)
            except ValueError:
                # Generator finalised from a different context; nothing to reset.
                pass


def _build_confirmation_response_content(interrupt_id: str, response_value: str) -> Optional[types.Content]:
    """Build the FunctionResponse content that resumes a paused tool call.

    ``response_value`` follows Strands' string convention forwarded by
    ``backend/app/routers/invocations.py`` ("y"/"yes"/"t"/"approved" = confirm,
    anything else = deny); "t" additionally sets the confirmation payload's
    ``trust`` flag so ``approval.py``'s trust-cache logic (see
    ``build_confirmation_predicate``) skips confirmation for this tool for
    the rest of the session.
    """
    confirmed = response_value.lower() in ("y", "yes", "t", "approved")
    payload = {"trust": True} if response_value.lower() == "t" else None
    function_response = types.FunctionResponse(
        id=interrupt_id,
        name=_REQUEST_CONFIRMATION_FUNCTION_CALL_NAME,
        response={"confirmed": confirmed, "payload": payload},
    )
    return types.Content(role="user", parts=[types.Part(function_response=function_response)])


@app.entrypoint
async def invoke(payload: dict[str, Any]) -> AsyncGenerator[Any, None]:
    """Handle an AgentCore Runtime invocation with streaming response.

    Supports two invocation modes, matching Strands' handler's payload shape:
    1. Normal prompt → stream text back
    2. ``interruptResponse`` → resume a paused ``adk_request_confirmation`` call
    """
    session_id = payload.get("session_id", "")
    actor_id = payload.get("actor_id") or "loom-agent"
    runtime_model_id = payload.get("model_id")
    # Per-invocation guardrail override (Contract 2), validated in _run_turn.
    guardrail_kwargs = _guardrail_kwargs(payload)

    interrupt_responses = payload.get("interruptResponse")
    if interrupt_responses and isinstance(interrupt_responses, list):
        # Strands sends a list (multiple pending interrupts can resume in one
        # call); ADK's confirmation model resolves one paused call per
        # FunctionResponse. Loom's own invocations.py resumes interrupts one
        # at a time (see the per-interrupt loop in routers/invocations.py),
        # so in practice this list always has exactly one entry — but handle
        # more defensively by resuming the first and logging if there's more
        # than one, rather than silently dropping any.
        if len(interrupt_responses) > 1:
            logger.warning(
                "Received %d interruptResponse entries; ADK resumes one confirmation per "
                "invocation, only the first will be applied",
                len(interrupt_responses),
            )
        resume = interrupt_responses[0].get("interruptResponse", interrupt_responses[0])
        interrupt_id = resume.get("interruptId", "")
        response_value = resume.get("response", "n")
        logger.info("Resuming from interrupt session_id=%s id=%s response=%s", session_id, interrupt_id, response_value)

        content = _build_confirmation_response_content(interrupt_id, response_value)
        async for event in _run_turn(session_id, actor_id, content, runtime_model_id, **guardrail_kwargs):
            yield event
        return

    # Inject approval policies from the invocation payload (sent by Loom),
    # mirroring strands_agent/src/handler.py. Without this the matcher only
    # ever held what LOOM_APPROVAL_POLICIES carried at cold start — nothing,
    # since deploy does not set it — so operator-configured HITL gates did not
    # apply to ADK agents at all.
    invocation_policies = payload.get("approval_policies")
    if invocation_policies and isinstance(invocation_policies, list) and _approval_matcher is not None:
        _approval_matcher.policies = invocation_policies
        logger.info("Injected %d approval policy(ies) from payload", len(invocation_policies))
    elif _approval_matcher is not None:
        # An invocation with no policies must not inherit the previous one's:
        # the runtime is a warm singleton shared across callers.
        _approval_matcher.policies = []

    prompt = payload.get("prompt", "")
    logger.info("Processing invocation session_id=%s actor_id=%s model=%s", session_id, actor_id, runtime_model_id or "default")
    content = types.Content(role="user", parts=[types.Part(text=prompt)]) if prompt else None
    async for event in _run_turn(session_id, actor_id, content, runtime_model_id, **guardrail_kwargs):
        yield event


def _guardrail_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """``_run_turn`` kwargs for a payload ``guardrail`` override, if one was sent."""
    if payload.get("guardrail") is None:
        return {}
    return {"guardrail_request": payload["guardrail"]}


@app.websocket
async def ws_invoke(websocket, context) -> None:
    """WebSocket handler.

    Strands' WebSocket path exists specifically for full MCP elicitation
    support (Method 4), which has no ADK equivalent here (see module
    docstring). This handler still supports the same basic prompt/result/error
    message protocol as Strands' ``ws_invoke`` for streaming-agnostic
    request/response use, but never emits an ``elicitation`` message.
    """
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type", "prompt") != "prompt":
                continue

            prompt = data.get("prompt", "")
            session_id = data.get("session_id", "")
            actor_id = data.get("actor_id") or "loom-agent"
            runtime_model_id = data.get("model_id")

            content = types.Content(role="user", parts=[types.Part(text=prompt)]) if prompt else None

            result_chunks: list[str] = []
            rejected = False
            async for event in _run_turn(session_id, actor_id, content, runtime_model_id, **_guardrail_kwargs(data)):
                if event == GUARDRAIL_NOT_ALLOWED_MESSAGE:
                    rejected = True
                    await websocket.send_json({"type": "error", "content": GUARDRAIL_NOT_ALLOWED_TEXT})
                elif isinstance(event, str):
                    result_chunks.append(event)
                elif isinstance(event, dict) and "guardrail" in event:
                    await websocket.send_json({"type": "guardrail", "content": event["guardrail"]})
                elif isinstance(event, dict) and "tool_use" in event:
                    await websocket.send_json({"type": "tool_use", "name": event["tool_use"]["name"]})
                elif isinstance(event, dict) and "interrupt" in event:
                    # No inline WS approval flow for ADK; surface as an error
                    # so the client can fall back to the HTTP interruptResponse path.
                    await websocket.send_json({
                        "type": "error",
                        "content": "This agent requires approval for a tool call; use the HTTP invoke endpoint to resume with interruptResponse.",
                    })

            if not rejected:
                await websocket.send_json({"type": "result", "content": "".join(result_chunks)})

    except Exception as e:
        logger.exception("WebSocket handler error: %s", e)
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


def main() -> None:
    """Local development entry point for running the agent interactively."""
    import asyncio

    async def _main() -> None:
        await _get_runner()
        print("Agent ready. Type your prompt (Ctrl+C to exit):")
        session_id = "local-dev-session"
        while True:
            try:
                prompt = input("\n> ")
                if not prompt.strip():
                    continue
                content = types.Content(role="user", parts=[types.Part(text=prompt)])
                async for event in _run_turn(session_id, "local-dev", content):
                    if isinstance(event, str):
                        print(event, end="", flush=True)
                print()
            except KeyboardInterrupt:
                print("\nExiting.")
                break
            except Exception as e:
                print(f"Error: {e}")

    asyncio.run(_main())


if __name__ == "__main__":
    app.run()
