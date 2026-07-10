"""Agent invocation endpoints with SSE streaming support."""
import asyncio
import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any, List, AsyncGenerator, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

import threading

from app.db import get_db, SessionLocal
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.session import InvocationSession
from app.models.invocation import Invocation
from app.models.authorizer_config import AuthorizerConfig
from app.models.authorizer_credential import AuthorizerCredential
from app.models.mcp import McpServer
from app.models.approval_policy import ApprovalPolicy

from app.services.agentcore import invoke_agent, invoke_agent_ws
from app.services.harness import invoke_harness_stream
from app.services.cloudwatch import (
    get_log_events, get_usage_log_events,
    parse_agent_start_time, parse_agentcore_request_id,
    parse_memory_telemetry, parse_usage_telemetry,
)
from app.services.cognito import get_cognito_token
from app.services.latency import compute_client_duration, compute_cold_start
from app.services.secrets import get_secret
from app.services.tokens import count_input_tokens, count_output_tokens
from app.routers.agents import derive_log_group


router = APIRouter(prefix="/api/agents", tags=["invocations"])


def _decode_jwt_claims(token: str) -> dict[str, Any] | None:
    """Decode JWT payload without verification (for admin inspection)."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None


def _extract_token_summary(token: str, token_type: str = "user", source: str | None = None) -> dict[str, Any] | None:  # nosec B107 — "user" is a token-type label, not a password
    """Extract key claims from a JWT for admin display."""
    claims = _decode_jwt_claims(token)
    if not claims:
        return None
    summary: dict[str, Any] = {"token_type": token_type}
    if source:
        summary["source"] = source
    summary["claims"] = {
        "iss": claims.get("iss"),
        "sub": claims.get("sub"),
        "aud": claims.get("aud"),
        "cid": claims.get("cid") or claims.get("client_id"),
        "scp": claims.get("scp"),
        "roles": claims.get("roles"),
        "act": claims.get("act"),
        "exp": claims.get("exp"),
        "iat": claims.get("iat"),
    }
    return summary


# Pydantic models
class InvokeRequest(BaseModel):
    """Request body for agent invocation."""
    prompt: str = Field(..., description="Prompt to send to the agent")
    qualifier: str = Field(default="DEFAULT", description="Endpoint qualifier to use")
    session_id: str | None = Field(default=None, description="Existing session ID to reuse (runtimeSessionId)")
    credential_id: int | None = Field(default=None, description="Authorizer credential ID for token generation")
    bearer_token: str | None = Field(default=None, description="Manual bearer token for agent invocation")
    use_linked_token: bool = Field(default=False, description="Use linked user token for cross-IdP auth")
    model_id: str | None = Field(default=None, description="Runtime model override (must be in agent's allowed_model_ids)")
    connector_ids: list[int] | None = Field(default=None, description="User-enabled MCP connector IDs for runtime tool access")


class InvocationResponse(BaseModel):
    """Response model for invocation details."""
    id: int
    session_id: str
    invocation_id: str
    request_id: str | None = None
    client_invoke_time: float | None
    client_done_time: float | None
    agent_start_time: float | None
    cold_start_latency_ms: float | None
    client_duration_ms: float | None
    status: str
    error_message: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    compute_cost: float | None = None
    compute_cpu_cost: float | None = None
    compute_memory_cost: float | None = None
    idle_timeout_cost: float | None = None
    idle_cpu_cost: float | None = None
    idle_memory_cost: float | None = None
    memory_retrievals: int | None = None
    memory_events_sent: int | None = None
    memory_estimated_cost: float | None = None
    stm_cost: float | None = None
    ltm_cost: float | None = None
    cost_source: str | None = None
    prompt_text: str | None = None
    thinking_text: str | None = None
    response_text: str | None = None
    created_at: str | None


class SessionResponse(BaseModel):
    """Response model for session details."""
    agent_id: int
    session_id: str
    qualifier: str
    status: str
    live_status: str
    created_at: str | None
    user_id: str | None = None
    hidden_at: str | None = None
    invocations: List[InvocationResponse]


def compute_live_status(session: InvocationSession, db: Session) -> str:
    """
    Compute the live status of a session based on its status and timing data.

    Returns "pending", "streaming", "active", or "expired".

    Sessions stuck in ``pending`` or ``streaming`` longer than the idle
    timeout are automatically transitioned to ``error`` so they do not
    remain in a stale state indefinitely.
    """
    timeout_seconds = int(os.getenv("LOOM_SESSION_IDLE_TIMEOUT_SECONDS", "300"))

    if session.status in ("pending", "streaming"):
        # If the session has been pending/streaming longer than the idle
        # timeout, it is stuck — transition to error.
        if session.created_at:
            age = (datetime.utcnow() - session.created_at).total_seconds()
            if age > timeout_seconds:
                logger.warning(
                    "Session %s stuck in '%s' for %.0fs; marking as error",
                    session.session_id, session.status, age,
                )
                session.status = "error"
                # Also mark any pending/streaming invocations as error
                stuck_invocations = db.query(Invocation).filter(
                    Invocation.session_id == session.session_id,
                    Invocation.status.in_(("pending", "streaming")),
                ).all()
                for inv in stuck_invocations:
                    inv.status = "error"
                    inv.error_message = "Session timed out in pending/streaming state"
                db.commit()
                return "expired"
        return session.status

    max_done_time = db.query(func.max(Invocation.client_done_time)).filter(
        Invocation.session_id == session.session_id
    ).scalar()

    if max_done_time is not None:
        if (time.time() - max_done_time) < timeout_seconds:
            return "active"
        return "expired"

    # No client_done_time — fall back to created_at
    if session.created_at:
        if (datetime.utcnow() - session.created_at).total_seconds() < timeout_seconds:
            return "active"
    return "expired"


def _get_io_discount(db: Session) -> float:
    """Get the configured CPU I/O wait discount."""
    from app.routers.settings import get_cpu_io_wait_discount
    return get_cpu_io_wait_discount(db)


def _apply_view_time_costs(inv_dict: dict, io_discount: float) -> dict:
    """Recompute runtime costs at view time using current pricing defaults.

    When client_duration_ms is available, CPU and memory costs are recomputed
    from duration so that pricing constant changes affect all historical data.
    Falls back to applying only the I/O wait discount on stored CPU cost.
    """
    from app.routers.agents import AGENTCORE_RUNTIME_PRICING
    duration_ms = inv_dict.get("client_duration_ms")
    if duration_ms is not None and duration_ms > 0:
        hours = duration_ms / 1000 / 3600
        raw_cpu = hours * AGENTCORE_RUNTIME_PRICING["default_vcpu"] * AGENTCORE_RUNTIME_PRICING["cpu_per_vcpu_hour"]
        inv_dict["compute_cpu_cost"] = round(raw_cpu * (1.0 - io_discount), 6)
        inv_dict["compute_memory_cost"] = round(hours * AGENTCORE_RUNTIME_PRICING["default_memory_gb"] * AGENTCORE_RUNTIME_PRICING["memory_per_gb_hour"], 6)
    else:
        raw = inv_dict.get("compute_cpu_cost")
        if raw is not None:
            inv_dict["compute_cpu_cost"] = round(raw * (1.0 - io_discount), 6)
    return inv_dict


def _backfill_idle_costs(session: InvocationSession, live_status: str, db: Session) -> None:
    """Backfill idle memory cost on invocations. Idle cost is memory-only.

    Two scenarios:
      1. Between invocations: a completed invoke is followed by another invoke
         before the session times out. Idle duration = next.client_invoke_time
         minus current.client_done_time, capped at idle_timeout_seconds.
      2. Last invocation + session expired: the session has fully idled out.
         Idle duration = idle_timeout_seconds.
    """
    invocations = db.query(Invocation).filter(
        Invocation.session_id == session.session_id,
        Invocation.status.in_(("complete", "streaming", "pending")),
    ).order_by(Invocation.client_done_time.asc().nullslast()).all()

    completed = [inv for inv in invocations if inv.status == "complete" and inv.client_done_time]
    if not completed:
        return

    from app.routers.agents import AGENTCORE_RUNTIME_PRICING
    idle_timeout_seconds = int(os.getenv(
        "LOOM_SESSION_IDLE_TIMEOUT_SECONDS",
        str(AGENTCORE_RUNTIME_PRICING["default_idle_timeout_seconds"]),
    ))
    mem_rate = (
        AGENTCORE_RUNTIME_PRICING["default_memory_gb"]
        * AGENTCORE_RUNTIME_PRICING["memory_per_gb_hour"]
        / 3600
    )

    changed = False

    # Scenario 2: gap between consecutive completed invocations
    for i in range(len(completed) - 1):
        current = completed[i]
        next_inv = completed[i + 1]
        if next_inv.client_invoke_time:
            gap_seconds = next_inv.client_invoke_time - current.client_done_time
            if gap_seconds > 0:
                idle_seconds = min(gap_seconds, idle_timeout_seconds)
                new_cost = round(idle_seconds * mem_rate, 6)
                if current.idle_memory_cost != new_cost:
                    current.idle_cpu_cost = 0.0
                    current.idle_memory_cost = new_cost
                    current.idle_timeout_cost = new_cost
                    changed = True

    # Scenario 1: last completed invocation and session has expired
    last = completed[-1]
    if live_status == "expired":
        new_cost = round(idle_timeout_seconds * mem_rate, 6)
        if last.idle_memory_cost != new_cost:
            last.idle_cpu_cost = 0.0
            last.idle_memory_cost = new_cost
            last.idle_timeout_cost = new_cost
            changed = True

    if changed:
        db.commit()
        logger.info("Recomputed idle memory costs for session %s", session.session_id)


def _estimate_compute_costs(
    duration_seconds: float,
) -> tuple[float, float, float]:
    """Estimate raw CPU and memory costs from measured invocation duration.

    Uses the default resource allocation from AGENTCORE_RUNTIME_PRICING.
    CPU cost is stored at full rate (no I/O wait discount).  The configurable
    discount is applied at view time so changing the setting retroactively
    affects all historical data.

    Returns (cpu_cost, memory_cost, total_cost) all rounded to 6 decimals.
    """
    from app.routers.agents import AGENTCORE_RUNTIME_PRICING

    hours = duration_seconds / 3600
    cpu_cost = round(
        hours * AGENTCORE_RUNTIME_PRICING["default_vcpu"]
        * AGENTCORE_RUNTIME_PRICING["cpu_per_vcpu_hour"], 6,
    )
    memory_cost = round(
        hours * AGENTCORE_RUNTIME_PRICING["default_memory_gb"]
        * AGENTCORE_RUNTIME_PRICING["memory_per_gb_hour"], 6,
    )
    return cpu_cost, memory_cost, round(cpu_cost + memory_cost, 6)


def format_sse_event(event: str, data: dict) -> str:
    """
    Format a Server-Sent Event message.

    Format:
        event: {event_name}
        data: {json_data}

        (blank line)
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _finalize_invocation(
    invocation_id: str,
    session_id: str,
    runtime_id: str,
    qualifier: str,
    region: str,
    agent_model_id: str | None,
    prompt: str,
    response_chunks: list[str],
    thinking_chunks: list[str],
    client_invoke_time: float,
    chunk_generator: Any | None = None,
) -> None:
    """Finalize an invocation: drain remaining chunks, compute metrics, update DB.

    Designed to run in a background thread so that metrics are captured even
    when the client disconnects mid-stream.
    """
    # Drain any remaining chunks from the agent stream
    if chunk_generator is not None:
        try:
            for chunk in chunk_generator:
                if chunk.get("type") == "text":
                    response_chunks.append(chunk["content"])
                elif chunk.get("type") == "structured":
                    structured = chunk["content"]
                    if isinstance(structured, dict):
                        data = structured.get("data")
                        if isinstance(data, str) and data:
                            response_chunks.append(data)
                        thinking = structured.get("thinking") or structured.get("reasoning")
                        if thinking:
                            thinking_chunks.append(str(thinking))
        except Exception as e:
            logger.warning("Error draining agent stream for invocation %s: %s", invocation_id, e)

    client_done_time = time.time()

    # CloudWatch log retrieval
    agent_start_time_val = None
    memory_retrievals = None
    memory_events_sent = None
    memory_estimated_cost = None
    try:
        log_group = derive_log_group(runtime_id, qualifier)
        start_time_ms = int(client_invoke_time * 1000)
        logger.info("[finalize] Fetching CloudWatch logs: log_group=%s session_id=%s", log_group, session_id)

        events = get_log_events(
            log_group=log_group,
            session_id=session_id,
            region=region,
            start_time_ms=start_time_ms,
            limit=100,
            max_retries=6,
            retry_interval=5.0,
            required_marker="LOOM_MEMORY_TELEMETRY",
        )

        if events:
            logger.info("[finalize] Found %d CloudWatch log events for session %s", len(events), session_id)

            # Extract AgentCore request ID
            agentcore_req_id = parse_agentcore_request_id(events)

            agent_start_time_val = parse_agent_start_time(events)

            mem_telemetry = parse_memory_telemetry(events)
            if mem_telemetry["retrievals"] > 0 or mem_telemetry["events_sent"] > 0:
                memory_retrievals = mem_telemetry["retrievals"]
                memory_events_sent = mem_telemetry["events_sent"]
                stm_cost = mem_telemetry["events_sent"] / 1000 * 0.25
                ltm_retrieval_cost = mem_telemetry["retrievals"] / 1000 * 0.50
                memory_estimated_cost = round(stm_cost + ltm_retrieval_cost, 6)
        else:
            agentcore_req_id = None
            logger.warning("[finalize] No CloudWatch log events found for session %s", session_id)
    except Exception as cw_err:
        logger.exception("[finalize] CloudWatch retrieval failed for session %s: %s", session_id, cw_err)

    # Token counting
    output_text = "".join(response_chunks) if response_chunks else ""
    if agent_model_id:
        input_tokens = count_input_tokens(agent_model_id, prompt, region)
        output_tokens = count_output_tokens(agent_model_id, output_text, region)
    else:
        input_tokens = max(1, len(prompt) // 4)
        output_tokens = max(1, len(output_text) // 4)
        logger.info("[finalize] Token count via heuristic (no model_id): input=%d output=%d", input_tokens, output_tokens)

    # Cost calculation
    estimated_cost = None
    if agent_model_id:
        from app.routers.agents import DEFAULT_REGION
        from app.services.model_catalog import get_merged_models
        models = get_merged_models(DEFAULT_REGION)
        model_pricing = next((m for m in models if m["model_id"] == agent_model_id), None)
        if model_pricing:
            input_price = model_pricing.get("input_price_per_1k_tokens", 0)
            output_price = model_pricing.get("output_price_per_1k_tokens", 0)
            estimated_cost = round(
                (input_tokens / 1000 * input_price) + (output_tokens / 1000 * output_price),
                6,
            )

    # Compute cost: estimate from measured duration using default resource allocation.
    duration_seconds = client_done_time - client_invoke_time
    compute_cpu_cost, compute_memory_cost, compute_cost = _estimate_compute_costs(duration_seconds)
    cost_source = "estimated"
    logger.info("[finalize] Estimated compute cost from %.1fs duration: cpu=$%s mem=$%s total=$%s",
                duration_seconds, compute_cpu_cost, compute_memory_cost, compute_cost)

    # Memory cost breakdown (STM create events + LTM retrieve records)
    stm_cost = None
    ltm_cost = None
    if memory_events_sent is not None and memory_events_sent > 0:
        stm_cost = round(memory_events_sent / 1000 * 0.25, 6)
    if memory_retrievals is not None and memory_retrievals > 0:
        ltm_cost = round(memory_retrievals / 1000 * 0.50, 6)

    # Persist to DB using a fresh session
    # Note: idle costs are NOT set here — they are backfilled when the session
    # enters idle state (see _backfill_idle_costs).
    db = SessionLocal()
    try:
        inv = db.query(Invocation).filter(Invocation.invocation_id == invocation_id).first()
        sess = db.query(InvocationSession).filter(InvocationSession.session_id == session_id).first()
        if inv:
            inv.client_done_time = client_done_time
            inv.client_duration_ms = compute_client_duration(client_invoke_time, client_done_time)
            if agent_start_time_val is not None:
                inv.agent_start_time = agent_start_time_val
                inv.cold_start_latency_ms = compute_cold_start(client_invoke_time, agent_start_time_val)
            inv.response_text = "".join(response_chunks) if response_chunks else None
            inv.thinking_text = "\n".join(thinking_chunks) if thinking_chunks else None
            inv.input_tokens = input_tokens
            inv.output_tokens = output_tokens
            inv.estimated_cost = estimated_cost
            inv.compute_cost = compute_cost
            inv.compute_cpu_cost = compute_cpu_cost
            inv.compute_memory_cost = compute_memory_cost
            inv.cost_source = cost_source
            inv.memory_retrievals = memory_retrievals
            inv.memory_events_sent = memory_events_sent
            inv.memory_estimated_cost = memory_estimated_cost
            inv.stm_cost = stm_cost
            inv.ltm_cost = ltm_cost
            if agentcore_req_id:
                inv.request_id = agentcore_req_id
            inv.status = "complete"
        if sess:
            sess.status = "complete"
        db.commit()
        logger.info("[finalize] Completed finalization for invocation %s (cost_source=%s input=%d output=%d cost=%s)",
                     invocation_id, cost_source, input_tokens, output_tokens, estimated_cost)
    except Exception as e:
        db.rollback()
        logger.exception("[finalize] DB update failed for invocation %s: %s", invocation_id, e)
    finally:
        db.close()


async def invoke_agent_stream(
    agent: Agent,
    session: InvocationSession,
    invocation: Invocation,
    db: Session,
    client_invoke_time: float,
    prompt: str,
    access_token: str | None = None,
    token_source: str | None = None,
    actor_id: str | None = None,
    runtime_model_id: str | None = None,
    dynamic_mcp_servers: list[dict[str, Any]] | None = None,
    approval_policies: list[dict[str, Any]] | None = None,
    supports_elicitation: bool = False,
    user_access_token: str | None = None,
    delegation_mode: str = "m2m",
) -> AsyncGenerator[str, None]:
    """
    Invoke the agent and yield SSE events as the response streams.

    If the client disconnects mid-stream, a background thread drains the
    remaining agent response and completes metrics computation so that
    token counts and costs are always captured.

    Yields:
        SSE formatted events: session_start, chunk, session_end, error
    """
    session_id = session.session_id
    invocation_id = invocation.invocation_id

    # Extract model_id and runtime context for finalization
    config_map = {e.key: e.value for e in agent.config_entries}
    import json as _json
    agent_model_id = None
    config_json_str = config_map.get("AGENT_CONFIG_JSON", "")
    if config_json_str:
        try:
            agent_model_id = _json.loads(config_json_str).get("model_id")
        except (json.JSONDecodeError, TypeError):
            pass

    # Override with runtime model selection (already validated by caller)
    if runtime_model_id:
        logger.info("Runtime model override: %s (default: %s)", runtime_model_id, agent_model_id)
        agent_model_id = runtime_model_id

    runtime_id = agent.runtime_id
    qualifier = session.qualifier
    region = agent.region

    # Update invocation with invoke time
    invocation.client_invoke_time = client_invoke_time
    invocation.status = "streaming"
    session.status = "streaming"
    finalized = False
    db.commit()

    # Yield session_start event
    session_start_data: dict[str, Any] = {
        "session_id": session_id,
        "invocation_id": invocation_id,
        "client_invoke_time": client_invoke_time,
        "user_id": session.user_id,
    }
    if token_source:
        session_start_data["token_source"] = token_source
    if access_token:
        session_start_data["has_token"] = True
        token_summary = _extract_token_summary(access_token, "user", token_source)
        if token_summary:
            session_start_data["user_token"] = token_summary
    session_start_data["delegation_mode"] = delegation_mode
    if delegation_mode == "obo":
        session_start_data["has_user_access_token"] = bool(user_access_token)
    yield format_sse_event("session_start", session_start_data)

    # Validate OBO precondition: user access token must be present
    if delegation_mode == "obo" and not user_access_token:
        error_msg = (
            "OBO delegation is configured for this agent but no user access token "
            "is available. Sign in via the same identity provider as the agent "
            "authorizer, or select a credential that forwards the user token."
        )
        logger.error(
            "OBO precondition failed for agent %s session %s: missing user_access_token",
            agent.id, session_id,
        )
        invocation.status = "error"
        invocation.error_message = error_msg
        session.status = "error"
        db.commit()
        yield format_sse_event("error", {"message": error_msg, "code": "obo_missing_user_token"})
        return

    # Shared state between streaming and finalization
    response_chunks: list[str] = []
    thinking_chunks: list[str] = []
    chunk_generator = None
    stream_drained = False
    aws_request_id: str | None = None

    try:
        # Call invoke_agent service (returns a synchronous generator)
        chunk_generator = invoke_agent(
            arn=agent.arn,
            qualifier=qualifier,
            session_id=session_id,
            prompt=prompt,
            region=region,
            access_token=access_token,
            actor_id=actor_id,
            dynamic_mcp_servers=dynamic_mcp_servers,
            runtime_model_id=runtime_model_id,
            approval_policies=approval_policies,
            supports_elicitation=supports_elicitation,
            user_access_token=user_access_token,
        )

        # Stream chunks to frontend. Each next() call on the synchronous
        # generator blocks while waiting for boto3's StreamingBody. Running
        # it in a thread via asyncio.to_thread keeps the event loop free so
        # uvicorn can flush each SSE event to the client in real-time.
        _sentinel = object()

        def _next_chunk():
            return next(chunk_generator, _sentinel)

        while True:
            chunk = await asyncio.to_thread(_next_chunk)
            if chunk is _sentinel:
                break

            if chunk.get("type") == "text":
                text_content = chunk["content"]
                response_chunks.append(text_content)
                yield format_sse_event("chunk", {"text": text_content})
            elif chunk.get("type") == "structured":
                structured = chunk["content"]
                if isinstance(structured, dict):
                    logger.info("Structured event keys: %s", list(structured.keys()))
                    # Tool use event forwarded from the agent handler
                    tool_use = structured.get("tool_use")
                    if isinstance(tool_use, dict) and tool_use.get("name"):
                        logger.info("Tool use event: %s", tool_use["name"])
                        yield format_sse_event("tool_use", {"name": tool_use["name"]})
                        continue
                    # OBO token info event from agent
                    token_info = structured.get("token_info")
                    if isinstance(token_info, dict):
                        logger.info("Token info event: type=%s provider=%s", token_info.get("token_type"), token_info.get("credential_provider"))
                        yield format_sse_event("token_info", token_info)
                        continue
                    # MCP elicitation: tool paused waiting for user input
                    elicitation_data = structured.get("elicitation")
                    if isinstance(elicitation_data, dict):
                        elicit_id = elicitation_data.get("id", "")
                        logger.info("MCP elicitation request: id=%s", elicit_id)

                        from app.routers.approvals import create_approval_request, wait_for_approval
                        request_id = create_approval_request()

                        yield format_sse_event("elicitation_request", {
                            "elicitation_id": elicit_id,
                            "request_id": request_id,
                            "message": elicitation_data.get("message", ""),
                            "schema": elicitation_data.get("schema"),
                        })

                        decision = await wait_for_approval(request_id, timeout=300.0)
                        decision_str = decision.get("decision", "timeout")

                        if decision_str == "approved":
                            elicit_action = "accept"
                            elicit_content = decision.get("content", {})
                        else:
                            elicit_action = "decline"
                            elicit_content = None

                        # Re-invoke agent to unblock the elicitation callback
                        resume_generator = invoke_agent(
                            arn=agent.arn,
                            qualifier=qualifier,
                            session_id=session_id,
                            prompt="",
                            region=region,
                            access_token=access_token,
                            actor_id=actor_id,
                            dynamic_mcp_servers=None,
                            runtime_model_id=runtime_model_id,
                            supports_elicitation=True,
                            elicitation_response={"action": elicit_action, "content": elicit_content},
                            user_access_token=user_access_token,
                        )

                        def _next_elicit_resume():
                            return next(resume_generator, _sentinel)

                        while True:
                            rchunk = await asyncio.to_thread(_next_elicit_resume)
                            if rchunk is _sentinel:
                                break
                            if rchunk.get("type") == "text":
                                text_c = rchunk["content"]
                                response_chunks.append(text_c)
                                yield format_sse_event("chunk", {"text": text_c})
                            elif rchunk.get("type") == "structured":
                                rs = rchunk["content"]
                                if isinstance(rs, dict):
                                    rtool = rs.get("tool_use")
                                    if isinstance(rtool, dict) and rtool.get("name"):
                                        yield format_sse_event("tool_use", {"name": rtool["name"]})
                                    rdata = rs.get("data")
                                    if isinstance(rdata, str) and rdata:
                                        response_chunks.append(rdata)
                                        yield format_sse_event("chunk", {"text": rdata})
                        continue
                    # Strands interrupt: agent paused waiting for approval
                    interrupt_data = structured.get("interrupt")
                    if isinstance(interrupt_data, dict):
                        interrupts = interrupt_data.get("interrupts", [])
                        logger.info("Agent interrupted with %d pending approval(s)", len(interrupts))
                        for intr in interrupts:
                            from app.routers.approvals import create_approval_request, wait_for_approval
                            request_id = create_approval_request()
                            approval_event = {
                                "request_id": request_id,
                                "interrupt_id": intr.get("id", ""),
                                "interrupt_name": intr.get("name", ""),
                                "tool_name": intr.get("reason", {}).get("tool_name", intr.get("name", "")),
                                "tool_input_summary": intr.get("reason", {}).get("tool_input_summary", ""),
                                "policy_name": intr.get("reason", {}).get("policy_name", ""),
                                "policy_type": intr.get("reason", {}).get("policy_type", "loop_hook"),
                                "approval_mode": intr.get("reason", {}).get("approval_mode", "require_approval"),
                                "timeout_seconds": intr.get("reason", {}).get("timeout_seconds", 300),
                                "session_id": session_id,
                            }
                            yield format_sse_event("approval_request", approval_event)

                            timeout = intr.get("reason", {}).get("timeout_seconds", 300)
                            decision = await wait_for_approval(request_id, timeout=float(timeout))
                            decision_str = decision.get("decision", "timeout")
                            yield format_sse_event("approval_resolved", {
                                "request_id": request_id,
                                "status": decision_str,
                                "decided_by": decision.get("decided_by"),
                                "reason": decision.get("reason"),
                            })

                            # Map decision to interrupt response value
                            if decision_str == "approved":
                                response_value = "y"
                            elif decision_str == "trusted":
                                response_value = "t"
                            else:
                                response_value = "n"

                            # Re-invoke agent with interruptResponse to resume
                            interrupt_response_payload = [
                                {"interruptResponse": {"interruptId": intr["id"], "name": intr["name"], "response": response_value}}
                            ]
                            resume_generator = invoke_agent(
                                arn=agent.arn,
                                qualifier=qualifier,
                                session_id=session_id,
                                prompt="",
                                region=region,
                                access_token=access_token,
                                actor_id=actor_id,
                                dynamic_mcp_servers=None,
                                runtime_model_id=runtime_model_id,
                                interrupt_response=interrupt_response_payload,
                                user_access_token=user_access_token,
                            )

                            def _next_resume():
                                return next(resume_generator, _sentinel)

                            while True:
                                rchunk = await asyncio.to_thread(_next_resume)
                                if rchunk is _sentinel:
                                    break
                                if rchunk.get("type") == "text":
                                    text_c = rchunk["content"]
                                    response_chunks.append(text_c)
                                    yield format_sse_event("chunk", {"text": text_c})
                                elif rchunk.get("type") == "structured":
                                    rs = rchunk["content"]
                                    if isinstance(rs, dict):
                                        rtool = rs.get("tool_use")
                                        if isinstance(rtool, dict) and rtool.get("name"):
                                            yield format_sse_event("tool_use", {"name": rtool["name"]})
                                        rdata = rs.get("data")
                                        if isinstance(rdata, str) and rdata:
                                            response_chunks.append(rdata)
                                            yield format_sse_event("chunk", {"text": rdata})
                        continue
                    # Legacy: direct approval_request events (harness mode)
                    approval_req = structured.get("approval_request")
                    if isinstance(approval_req, dict):
                        logger.info("Approval request: %s", approval_req.get("request_id"))
                        yield format_sse_event("approval_request", approval_req)
                        continue
                    approval_res = structured.get("approval_resolved")
                    if isinstance(approval_res, dict):
                        yield format_sse_event("approval_resolved", approval_res)
                        continue
                    # Strands SDK text delta: {"data": "token"}
                    data = structured.get("data")
                    if isinstance(data, str) and data:
                        response_chunks.append(data)
                        yield format_sse_event("chunk", {"text": data})
                    # Extract thinking/reasoning data
                    thinking = structured.get("thinking") or structured.get("reasoning")
                    if thinking:
                        thinking_chunks.append(str(thinking))

        stream_drained = True

        # Client is still connected — run finalization inline using the
        # request DB session (avoids cross-session issues with SQLite).
        client_done_time = time.time()
        invocation.client_done_time = client_done_time
        invocation.client_duration_ms = compute_client_duration(client_invoke_time, client_done_time)

        # Retrieve CloudWatch logs for cold start latency and memory telemetry
        try:
            log_group = derive_log_group(runtime_id, qualifier)
            start_time_ms = int(client_invoke_time * 1000)
            logger.info("Fetching CloudWatch logs: log_group=%s session_id=%s start_time_ms=%d",
                        log_group, session_id, start_time_ms)

            events = await asyncio.to_thread(
                lambda: get_log_events(
                    log_group=log_group,
                    session_id=session_id,
                    region=region,
                    start_time_ms=start_time_ms,
                    limit=100,
                    max_retries=6,
                    retry_interval=5.0,
                    required_marker="LOOM_MEMORY_TELEMETRY",
                )
            )

            if events:
                logger.info("Found %d CloudWatch log events for session %s", len(events), session_id)

                # Extract AgentCore request ID for correlation
                agentcore_req_id = parse_agentcore_request_id(events)
                if agentcore_req_id:
                    aws_request_id = agentcore_req_id
                    invocation.request_id = agentcore_req_id
                    logger.info("Parsed AgentCore request_id=%s for invocation %s", agentcore_req_id, invocation_id)

                agent_start_time = parse_agent_start_time(events)
                if agent_start_time is not None:
                    invocation.agent_start_time = agent_start_time
                    invocation.cold_start_latency_ms = compute_cold_start(client_invoke_time, agent_start_time)
                    logger.info("Computed cold_start_latency_ms=%.1f agent_start_time=%.3f",
                                invocation.cold_start_latency_ms, agent_start_time)

                mem_telemetry = parse_memory_telemetry(events)
                if mem_telemetry["retrievals"] > 0 or mem_telemetry["events_sent"] > 0:
                    invocation.memory_retrievals = mem_telemetry["retrievals"]
                    invocation.memory_events_sent = mem_telemetry["events_sent"]
                    stm_cost = mem_telemetry["events_sent"] / 1000 * 0.25
                    ltm_retrieval_cost = mem_telemetry["retrievals"] / 1000 * 0.50
                    invocation.memory_estimated_cost = round(stm_cost + ltm_retrieval_cost, 6)
            else:
                logger.warning("No CloudWatch log events found for session %s after retries", session_id)
        except Exception as cw_err:
            logger.exception("CloudWatch retrieval failed for session %s: %s", session_id, cw_err)

        # Persist accumulated content
        invocation.response_text = "".join(response_chunks) if response_chunks else None
        invocation.thinking_text = "\n".join(thinking_chunks) if thinking_chunks else None

        # Token counting via Bedrock CountTokens API (falls back to heuristic)
        output_text = "".join(response_chunks) if response_chunks else ""
        if agent_model_id:
            input_tokens = await asyncio.to_thread(count_input_tokens, agent_model_id, prompt, region)
            output_tokens = await asyncio.to_thread(count_output_tokens, agent_model_id, output_text, region)
        else:
            input_tokens = max(1, len(prompt) // 4)
            output_tokens = max(1, len(output_text) // 4)
            logger.info("Token count via heuristic (no model_id): input=%d output=%d", input_tokens, output_tokens)

        # Cost calculation
        estimated_cost = None
        if agent_model_id:
            from app.routers.agents import DEFAULT_REGION
            from app.services.model_catalog import get_merged_models
            models = await asyncio.to_thread(get_merged_models, DEFAULT_REGION)
            model_pricing = next((m for m in models if m["model_id"] == agent_model_id), None)
            if model_pricing:
                input_price = model_pricing.get("input_price_per_1k_tokens", 0)
                output_price = model_pricing.get("output_price_per_1k_tokens", 0)
                estimated_cost = round(
                    (input_tokens / 1000 * input_price) + (output_tokens / 1000 * output_price), 6,
                )

        # Compute cost: estimate from measured duration using default resource allocation.
        duration_seconds = client_done_time - client_invoke_time
        compute_cpu_cost, compute_memory_cost, compute_cost = _estimate_compute_costs(duration_seconds)
        cost_source = "estimated"
        logger.info("Estimated compute cost from %.1fs duration: cpu=$%s mem=$%s total=$%s",
                     duration_seconds, compute_cpu_cost, compute_memory_cost, compute_cost)

        # Memory cost breakdown (STM create events + LTM retrieve records)
        stm_cost = invocation.stm_cost
        ltm_cost = invocation.ltm_cost
        if invocation.memory_events_sent and invocation.memory_events_sent > 0:
            stm_cost = round(invocation.memory_events_sent / 1000 * 0.25, 6)
        if invocation.memory_retrievals and invocation.memory_retrievals > 0:
            ltm_cost = round(invocation.memory_retrievals / 1000 * 0.50, 6)

        # Note: idle costs are NOT set here — they are backfilled when the
        # session enters idle state (see _backfill_idle_costs).
        invocation.input_tokens = input_tokens
        invocation.output_tokens = output_tokens
        invocation.estimated_cost = estimated_cost
        invocation.compute_cost = compute_cost
        invocation.compute_cpu_cost = compute_cpu_cost
        invocation.compute_memory_cost = compute_memory_cost
        invocation.cost_source = cost_source
        invocation.stm_cost = stm_cost
        invocation.ltm_cost = ltm_cost
        invocation.status = "complete"
        session.status = "complete"
        finalized = True
        db.commit()

        yield format_sse_event("session_end", {
            "session_id": session_id,
            "invocation_id": invocation_id,
            "request_id": aws_request_id,
            "qualifier": qualifier,
            "client_invoke_time": client_invoke_time,
            "client_done_time": client_done_time,
            "client_duration_ms": invocation.client_duration_ms,
            "cold_start_latency_ms": invocation.cold_start_latency_ms,
            "agent_start_time": invocation.agent_start_time,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": estimated_cost,
            "compute_cost": compute_cost,
            "compute_cpu_cost": round(compute_cpu_cost * (1.0 - _get_io_discount(db)), 6),
            "compute_memory_cost": compute_memory_cost,
            "memory_retrievals": invocation.memory_retrievals,
            "memory_events_sent": invocation.memory_events_sent,
            "memory_estimated_cost": invocation.memory_estimated_cost,
            "stm_cost": stm_cost,
            "ltm_cost": ltm_cost,
        })

    except Exception as e:
        # Handle errors — include full exception details for debugging
        error_detail = str(e)
        if hasattr(e, "response"):
            try:
                error_detail = f"{error_detail} | Response: {e.response}"
            except Exception:
                pass
        logger.error("Invocation failed for agent %s session %s (token_source=%s): %s",
                      agent.id, session_id, token_source, error_detail)
        client_done_time = time.time()
        invocation.client_done_time = client_done_time
        invocation.client_duration_ms = compute_client_duration(client_invoke_time, client_done_time)
        invocation.status = "error"
        invocation.error_message = error_detail
        session.status = "error"
        finalized = True
        db.commit()

        yield format_sse_event("error", {
            "message": f"Invocation failed: {error_detail}"
        })

    finally:
        # If finalization hasn't run (client disconnected mid-stream or
        # during post-processing), spawn a background thread to drain
        # remaining chunks and compute metrics.
        if not finalized:
            remaining_gen = chunk_generator if not stream_drained else None
            logger.info("Client disconnected for invocation %s; spawning background finalization", invocation_id)
            thread = threading.Thread(
                target=_finalize_invocation,
                args=(
                    invocation_id, session_id, runtime_id, qualifier, region,
                    agent_model_id, prompt, response_chunks, thinking_chunks,
                    client_invoke_time, remaining_gen,
                ),
                daemon=True,
            )
            thread.start()


async def invoke_harness_agent_stream(
    agent: Agent,
    session: InvocationSession,
    invocation: Invocation,
    db: Session,
    client_invoke_time: float,
    prompt: str,
    actor_id: str | None = None,
    runtime_model_id: str | None = None,
    access_token: str | None = None,
    token_source: str | None = None,
    dynamic_tools: list[dict[str, Any]] | None = None,
    user_access_token: str | None = None,
    delegation_mode: str = "m2m",
) -> AsyncGenerator[str, None]:
    """Invoke a harness-deployed agent and yield SSE events.

    Translates the harness streaming response to the same SSE format as
    invoke_agent_stream so the frontend works without modification.
    """
    session_id = session.session_id
    invocation_id = invocation.invocation_id

    config_map = {e.key: e.value for e in agent.config_entries}
    import json as _json
    agent_model_id = None
    agent_provider = "bedrock"
    agent_litellm_api_key_arn = None
    agent_litellm_api_base = None
    config_json_str = config_map.get("AGENT_CONFIG_JSON", "")
    if config_json_str:
        try:
            _harness_cfg = _json.loads(config_json_str)
            agent_model_id = _harness_cfg.get("model_id")
            agent_provider = _harness_cfg.get("provider") or "bedrock"
            agent_litellm_api_key_arn = _harness_cfg.get("litellm_api_key_credential_provider_arn") or None
            agent_litellm_api_base = _harness_cfg.get("base_url") or None
        except (json.JSONDecodeError, TypeError):
            pass

    if runtime_model_id:
        agent_model_id = runtime_model_id

    # Build tools with OAuth2 M2M tokens injected for this invocation.
    # Each MCP server has its own OAuth2 credentials — resolve a
    # client_credentials token per server and inject as a Bearer header.
    invoke_tools: list[dict[str, Any]] | None = None
    if config_json_str:
        try:
            parsed_config = _json.loads(config_json_str)
            harness_config = parsed_config.get("harness_config", {})
            configured_tools = harness_config.get("tools", [])
            mcp_servers_config = parsed_config.get("integrations", {}).get("mcp_servers", [])

            # Build name → auth_type lookup from stored config
            mcp_auth_map: dict[str, str] = {}
            for mcp_cfg in mcp_servers_config:
                mcp_auth_map[mcp_cfg["name"]] = mcp_cfg.get("auth_type", "none")

            # Pre-fetch OAuth2 tokens for MCP servers that need them
            mcp_tokens: dict[str, str] = {}
            if any(v == "oauth2" for v in mcp_auth_map.values()):
                from app.services.mcp import _get_oauth2_token
                oauth2_names = [n for n, t in mcp_auth_map.items() if t == "oauth2"]
                oauth2_servers = db.query(McpServer).filter(McpServer.name.in_(oauth2_names)).all()
                for server in oauth2_servers:
                    token = _get_oauth2_token(server)
                    if token:
                        mcp_tokens[server.name] = token
                    else:
                        logger.warning("Failed to get OAuth2 token for MCP server '%s'", server.name)

            if configured_tools:
                invoke_tools = []
                for tool in configured_tools:
                    tool_copy = _json.loads(_json.dumps(tool))
                    tool_name = tool_copy.get("name", "")
                    remote_mcp = (tool_copy.get("config") or {}).get("remoteMcp")
                    if remote_mcp and tool_name in mcp_tokens:
                        headers = remote_mcp.get("headers") or {}
                        headers["Authorization"] = f"Bearer {mcp_tokens[tool_name]}"
                        remote_mcp["headers"] = headers
                    invoke_tools.append(tool_copy)
        except (ValueError, TypeError):
            pass

    if dynamic_tools:
        if invoke_tools is None:
            invoke_tools = []
        existing_names = {t.get("name") for t in invoke_tools}
        for tool in dynamic_tools:
            if tool.get("name") not in existing_names:
                invoke_tools.append(_json.loads(_json.dumps(tool)))

    invocation.client_invoke_time = client_invoke_time
    invocation.status = "streaming"
    session.status = "streaming"
    db.commit()

    harness_start_data: dict[str, Any] = {
        "session_id": session_id,
        "invocation_id": invocation_id,
        "client_invoke_time": client_invoke_time,
        "user_id": session.user_id,
        "has_token": bool(access_token),
        "token_source": token_source,
        "delegation_mode": delegation_mode,
        "has_user_access_token": bool(user_access_token) if delegation_mode == "obo" else None,
    }
    if access_token:
        harness_token_summary = _extract_token_summary(access_token, "user", token_source)
        if harness_token_summary:
            harness_start_data["user_token"] = harness_token_summary
    yield format_sse_event("session_start", harness_start_data)

    if delegation_mode == "obo" and not user_access_token:
        error_msg = (
            "OBO delegation is configured for this harness agent but no user "
            "access token is available. Sign in via the agent's identity provider."
        )
        logger.error(
            "OBO precondition failed for harness agent %s session %s: missing user_access_token",
            agent.id, session_id,
        )
        invocation.status = "error"
        invocation.error_message = error_msg
        session.status = "error"
        db.commit()
        yield format_sse_event("error", {"message": error_msg, "code": "obo_missing_user_token"})
        return

    response_chunks: list[str] = []
    harness_input_tokens = 0
    harness_output_tokens = 0

    try:
        chunk_generator = invoke_harness_stream(
            harness_arn=agent.arn,
            session_id=session_id,
            prompt=prompt,
            region=agent.region,
            model_id=runtime_model_id,
            actor_id=actor_id,
            access_token=access_token,
            tools=invoke_tools,
            user_access_token=user_access_token,
            provider=agent_provider,
            litellm_api_key_arn=agent_litellm_api_key_arn,
            litellm_api_base=agent_litellm_api_base,
        )

        _sentinel = object()

        def _next_chunk():
            return next(chunk_generator, _sentinel)

        while True:
            chunk = await asyncio.to_thread(_next_chunk)
            if chunk is _sentinel:
                break

            if chunk.get("type") == "text":
                text_content = chunk["content"]
                response_chunks.append(text_content)
                yield format_sse_event("chunk", {"text": text_content})
            elif chunk.get("type") == "tool_use_stop":
                # Inline function HITL: the harness paused waiting for a tool result.
                # Loop to handle multiple consecutive HITL rounds.
                from app.routers.approvals import create_approval_request, wait_for_approval
                from app.services.harness import resume_harness_stream

                pending_tool_stop = chunk["content"]
                logger.info("HITL tool_use_stop event: %s", json.dumps(pending_tool_stop))

                while pending_tool_stop is not None:
                    tool_use_id = pending_tool_stop["tool_use_id"]
                    tool_name = pending_tool_stop.get("tool_name") or "user_confirmation"
                    tool_input = pending_tool_stop.get("tool_input", {})
                    pending_tool_stop = None

                    logger.info(
                        "HITL inline function called: tool=%s id=%s input=%s",
                        tool_name, tool_use_id, json.dumps(tool_input),
                    )

                    request_id = create_approval_request()
                    approval_event = {
                        "request_id": request_id,
                        "tool_name": tool_name,
                        "tool_input_summary": tool_input.get("action_summary") or tool_input.get("message") or json.dumps(tool_input)[:200],
                        "policy_name": tool_input.get("risk_level", ""),
                        "policy_type": "inline_function",
                        "approval_mode": "require_approval",
                        "timeout_seconds": 300,
                        "session_id": session_id,
                    }
                    logger.info("HITL approval_request: %s", json.dumps(approval_event))
                    yield format_sse_event("approval_request", approval_event)

                    decision = await wait_for_approval(request_id, timeout=300.0)
                    decision_str = decision.get("decision", "timeout")
                    logger.info(
                        "HITL approval decision: request_id=%s decision=%s decided_by=%s reason=%s",
                        request_id, decision_str, decision.get("decided_by"), decision.get("reason"),
                    )
                    yield format_sse_event("approval_resolved", {
                        "request_id": request_id,
                        "status": decision_str,
                        "decided_by": decision.get("decided_by"),
                        "reason": decision.get("reason"),
                    })

                    if decision_str == "approved":
                        tool_result_content = json.dumps({"approved": True, "message": "User approved the action."})
                        tool_result_status = "success"
                    else:
                        reason = decision.get("reason", "User denied the action.")
                        tool_result_content = json.dumps({"approved": False, "message": reason})
                        tool_result_status = "error"

                    logger.info(
                        "HITL resuming harness: tool=%s status=%s content=%s",
                        tool_name, tool_result_status, tool_result_content,
                    )
                    resume_generator = resume_harness_stream(
                        harness_arn=agent.arn,
                        session_id=session_id,
                        tool_use_id=tool_use_id,
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_result_content=tool_result_content,
                        tool_result_status=tool_result_status,
                        region=agent.region,
                        tools=invoke_tools,
                        access_token=access_token,
                        actor_id=actor_id,
                        user_access_token=user_access_token,
                    )

                    def _next_resume():
                        return next(resume_generator, _sentinel)

                    while True:
                        rchunk = await asyncio.to_thread(_next_resume)
                        if rchunk is _sentinel:
                            break
                        if rchunk.get("type") == "text":
                            text_c = rchunk["content"]
                            response_chunks.append(text_c)
                            yield format_sse_event("chunk", {"text": text_c})
                        elif rchunk.get("type") == "structured":
                            rs = rchunk["content"]
                            if isinstance(rs, dict):
                                rtool = rs.get("tool_use")
                                if isinstance(rtool, dict) and rtool.get("name"):
                                    yield format_sse_event("tool_use", {"name": rtool["name"]})
                        elif rchunk.get("type") == "metadata":
                            rmeta = rchunk.get("content", {})
                            harness_input_tokens += rmeta.get("input_tokens", 0)
                            harness_output_tokens += rmeta.get("output_tokens", 0)
                        elif rchunk.get("type") == "tool_use_stop":
                            pending_tool_stop = rchunk["content"]
                            break

            elif chunk.get("type") == "structured":
                structured = chunk["content"]
                if isinstance(structured, dict):
                    tool_use = structured.get("tool_use")
                    if isinstance(tool_use, dict) and tool_use.get("name"):
                        yield format_sse_event("tool_use", {"name": tool_use["name"]})
                    approval_req = structured.get("approval_request")
                    if isinstance(approval_req, dict):
                        yield format_sse_event("approval_request", approval_req)
                    approval_res = structured.get("approval_resolved")
                    if isinstance(approval_res, dict):
                        yield format_sse_event("approval_resolved", approval_res)
                    elicitation_req = structured.get("elicitation_request")
                    if isinstance(elicitation_req, dict):
                        yield format_sse_event("elicitation_request", elicitation_req)
            elif chunk.get("type") == "metadata":
                meta = chunk.get("content", {})
                harness_input_tokens = meta.get("input_tokens", 0)
                harness_output_tokens = meta.get("output_tokens", 0)

        client_done_time = time.time()
        invocation.client_done_time = client_done_time
        invocation.client_duration_ms = compute_client_duration(client_invoke_time, client_done_time)
        invocation.response_text = "".join(response_chunks) if response_chunks else None

        # Use token counts from harness metadata (no heuristic needed)
        input_tokens = harness_input_tokens
        output_tokens = harness_output_tokens
        if input_tokens == 0 and output_tokens == 0:
            output_text = "".join(response_chunks) if response_chunks else ""
            if agent_model_id:
                input_tokens = await asyncio.to_thread(count_input_tokens, agent_model_id, prompt, agent.region)
                output_tokens = await asyncio.to_thread(count_output_tokens, agent_model_id, output_text, agent.region)
            else:
                input_tokens = max(1, len(prompt) // 4)
                output_tokens = max(1, len(output_text) // 4)

        estimated_cost = None
        if agent_model_id:
            from app.routers.agents import DEFAULT_REGION
            from app.services.model_catalog import get_merged_models
            models = await asyncio.to_thread(get_merged_models, DEFAULT_REGION)
            model_pricing = next((m for m in models if m["model_id"] == agent_model_id), None)
            if model_pricing:
                input_price = model_pricing.get("input_price_per_1k_tokens", 0)
                output_price = model_pricing.get("output_price_per_1k_tokens", 0)
                estimated_cost = round(
                    (input_tokens / 1000 * input_price) + (output_tokens / 1000 * output_price), 6,
                )

        duration_seconds = client_done_time - client_invoke_time
        compute_cpu_cost, compute_memory_cost, compute_cost = _estimate_compute_costs(duration_seconds)

        invocation.input_tokens = input_tokens
        invocation.output_tokens = output_tokens
        invocation.estimated_cost = estimated_cost
        invocation.compute_cost = compute_cost
        invocation.compute_cpu_cost = compute_cpu_cost
        invocation.compute_memory_cost = compute_memory_cost
        invocation.cost_source = "harness"
        invocation.status = "complete"
        session.status = "complete"
        db.commit()

        yield format_sse_event("session_end", {
            "session_id": session_id,
            "invocation_id": invocation_id,
            "request_id": None,
            "qualifier": session.qualifier,
            "client_invoke_time": client_invoke_time,
            "client_done_time": client_done_time,
            "client_duration_ms": invocation.client_duration_ms,
            "cold_start_latency_ms": None,
            "agent_start_time": None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": estimated_cost,
            "compute_cost": compute_cost,
            "compute_cpu_cost": compute_cpu_cost,
            "compute_memory_cost": compute_memory_cost,
            "memory_retrievals": None,
            "memory_events_sent": None,
            "memory_estimated_cost": None,
            "stm_cost": None,
            "ltm_cost": None,
        })

    except Exception as e:
        error_detail = str(e)
        logger.error("Harness invocation failed for agent %s session %s: %s", agent.id, session_id, error_detail)
        client_done_time = time.time()
        invocation.client_done_time = client_done_time
        invocation.client_duration_ms = compute_client_duration(client_invoke_time, client_done_time)
        invocation.status = "error"
        invocation.error_message = error_detail
        session.status = "error"
        db.commit()
        yield format_sse_event("error", {"message": f"Invocation failed: {error_detail}"})


@router.post("/{agent_id}/invoke")
async def invoke_agent_endpoint(
    agent_id: int,
    request_body: InvokeRequest,
    request: Request,
    user: UserInfo = Depends(require_scopes("invoke")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Invoke an agent and stream the response via Server-Sent Events.

    Returns a text/event-stream with events: session_start, chunk, session_end, error
    """
    # Look up agent
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found"
        )

    # Validate qualifier
    available_qualifiers = agent.get_available_qualifiers()
    if request_body.qualifier not in available_qualifiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Qualifier '{request_body.qualifier}' not available. Available: {available_qualifiers}"
        )

    # ---- Group-based invoke restriction ----
    # Super-admins (g-admins-super) can invoke any agent.
    # Agents with no loom:group tag are accessible to any authenticated user with invoke scope.
    # Other admins (g-admins-demo, etc.) can only invoke agents in their specific group.
    # Users (t-user) can only invoke agents tagged with their groups (g-users-* → strip prefix).
    # Check this BEFORE creating any session/invocation records.
    if "g-admins-super" not in user.groups:
        agent_group = agent.get_tags().get("loom:group", "")

        if agent_group:
            if "t-admin" in user.groups:
                admin_groups = [g for g in user.groups if g.startswith("g-admins-")]
                allowed_tags = [g.replace("g-admins-", "", 1) for g in admin_groups]
            else:
                user_groups = [g for g in user.groups if g.startswith("g-users-")]
                allowed_tags = [g.replace("g-users-", "", 1) for g in user_groups]

            if agent_group not in allowed_tags:
                logger.warning(
                    "Group-based 403 for user=%s groups=%s agent_id=%s agent_group=%s allowed_tags=%s",
                    user.username, user.groups, agent_id, agent_group, allowed_tags,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"You can only invoke agents within your group (agent group: {agent_group})",
                )

    # Validate runtime model_id if provided
    runtime_model_id: str | None = None
    if request_body.model_id:
        allowed = agent.get_allowed_model_ids()
        if allowed and request_body.model_id not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{request_body.model_id}' is not in this agent's allowed models: {allowed}",
            )
        runtime_model_id = request_body.model_id

    # Record client invoke time before session creation
    client_invoke_time = time.time()

    # Reuse existing session or create a new one
    if request_body.session_id:
        session = db.query(InvocationSession).filter(
            InvocationSession.agent_id == agent.id,
            InvocationSession.session_id == request_body.session_id,
        ).first()
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {request_body.session_id} not found for agent {agent_id}"
            )
        if session.qualifier != request_body.qualifier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Qualifier mismatch: session uses '{session.qualifier}', request uses '{request_body.qualifier}'"
            )
        # Enforce session ownership: only the original invoker may reuse a session
        if session.user_id and session.user_id != user.username:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot invoke in a session created by another user",
            )
        session.status = "pending"
        db.commit()
    else:
        session = InvocationSession(
            agent_id=agent.id,
            session_id=str(uuid.uuid4()),
            qualifier=request_body.qualifier,
            status="pending",
            created_at=datetime.utcnow(),
            user_id=user.username,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    # Create invocation record within the session
    invocation = Invocation(
        session_id=session.session_id,
        invocation_id=str(uuid.uuid4()),
        status="pending",
        prompt_text=request_body.prompt,
        created_at=datetime.utcnow(),
    )
    db.add(invocation)
    db.commit()
    db.refresh(invocation)

    # ---- Resolve access token ----
    # Priority: manual token > credential_id (M2M) > user login token > agent config M2M
    # The frontend and agent share the same authorization server, so the user's
    # login token is the primary path. M2M credentials are for future integrations
    # (MCP, A2A) that need service-to-service tokens.
    access_token = None
    token_source = None

    # Priority 0: Use manually provided bearer token
    if request_body.bearer_token:
        access_token = request_body.bearer_token
        token_source = "manual"  # nosec B105 — log label, not a password
        logger.info("Using manually provided bearer token for agent invocation")

    # Priority 1: Use credential_id if provided (M2M for integrations)
    if not access_token and request_body.credential_id:
        cred = db.query(AuthorizerCredential).filter(AuthorizerCredential.id == request_body.credential_id).first()
        if cred and cred.client_secret_arn:
            auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == cred.authorizer_config_id).first()
            if auth and auth.pool_id:
                try:
                    import json as _json
                    region = os.getenv("AWS_REGION", "us-east-1")
                    client_secret = get_secret(cred.client_secret_arn, region)
                    allowed_scopes = _json.loads(auth.allowed_scopes) if auth.allowed_scopes else None
                    token_response = get_cognito_token(
                        pool_id=auth.pool_id,
                        client_id=cred.client_id,
                        client_secret=client_secret,
                        scopes=allowed_scopes or None,
                    )
                    access_token = token_response.get("access_token")
                    token_source = cred.label
                except Exception as e:
                    logger.warning("Failed to get token via credential %s: %s", request_body.credential_id, e)

    # Priority 1.5: Linked user token (cross-IdP authorizer linking)
    logger.info("Token resolution state: access_token=%s, use_linked_token=%s, user.sub=%s",
                bool(access_token), request_body.use_linked_token, user.sub)
    if not access_token:
        agent_auth_config_15 = agent.get_authorizer_config()
        logger.info("Priority 1.5: agent_auth_config=%s", agent_auth_config_15)
        if agent_auth_config_15 and agent_auth_config_15.get("type"):
            # Find the matching AuthorizerConfig by name, pool_id, or discovery_url
            linked_auth = None
            auth_name = agent_auth_config_15.get("name")
            if auth_name:
                linked_auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.name == auth_name).first()
            if not linked_auth and agent_auth_config_15.get("pool_id"):
                linked_auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.pool_id == agent_auth_config_15["pool_id"]).first()
            if not linked_auth and agent_auth_config_15.get("discovery_url"):
                linked_auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.discovery_url == agent_auth_config_15["discovery_url"]).first()
            if linked_auth and linked_auth.user_client_id and linked_auth.discovery_url:
                try:
                    from app.services.authorizer_linking import resolve_access_token as resolve_linked_token
                    region = os.getenv("AWS_REGION", "us-east-1")
                    user_client_secret = get_secret(linked_auth.user_client_secret_arn, region) if linked_auth.user_client_secret_arn else None
                    logger.info("Attempting linked-user token resolution: auth_id=%s, user_sub=%s, authorizer=%s", linked_auth.id, user.sub, linked_auth.name)
                    linked_token = resolve_linked_token(
                        linked_auth.id, user.sub, region,
                        linked_auth.discovery_url, linked_auth.user_client_id, user_client_secret,
                    )
                    if linked_token:
                        access_token = linked_token
                        token_source = "linked-user"  # nosec B105 — log label, not a password
                        logger.info("Using linked-user token for agent invocation (authorizer=%s)", linked_auth.name)
                    else:
                        logger.warning("Linked-user token resolution returned None for authorizer=%s user=%s", linked_auth.name, user.sub)
                except Exception as e:
                    logger.warning("Failed to resolve linked-user token: %s", e)
            else:
                logger.info("No linkable authorizer found for agent config: name=%s, pool_id=%s",
                            auth_name, agent_auth_config_15.get("pool_id"))

    # Priority 2: Forward user's login token (same auth server as agent)
    # Only applies when the agent has an authorizer; non-OAuth agents use SigV4.
    # Skip if user explicitly requested linked token — don't mask linking failures.
    if not access_token and not request_body.use_linked_token:
        agent_auth_config = agent.get_authorizer_config()
        if agent_auth_config and agent_auth_config.get("type"):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                access_token = auth_header[7:]
                token_source = "user"  # nosec B105 — log label, not a password
                logger.info("Using user login token for agent invocation")

    # Priority 3: Fall back to agent config M2M flow
    if not access_token:
        auth_config = agent.get_authorizer_config()
        if auth_config and auth_config.get("type") == "cognito" and auth_config.get("pool_id"):
            config_map = {e.key: e.value for e in agent.config_entries}
            client_id = config_map.get("COGNITO_CLIENT_ID", "")
            secret_arn = config_map.get("COGNITO_CLIENT_SECRET_ARN", "")
            if client_id and secret_arn:
                try:
                    client_secret = get_secret(secret_arn, agent.region)
                    token_response = get_cognito_token(
                        pool_id=auth_config["pool_id"],
                        client_id=client_id,
                        client_secret=client_secret,
                        scopes=auth_config.get("allowed_scopes") or None,
                    )
                    access_token = token_response.get("access_token")
                    token_source = "agent-config"  # nosec B105 — log label, not a password
                except Exception as e:
                    logger.warning("Failed to get Cognito token for agent %s: %s", agent_id, e)

    logger.info("Invoking agent %s with token_source=%s, has_token=%s",
                agent_id, token_source, bool(access_token))

    # Resolve dynamic MCP connector configs for user-enabled connectors
    dynamic_mcp_servers: list[dict[str, Any]] | None = None
    has_elicitation_connector = False
    if request_body.connector_ids:
        actor_id = user.actor_id
        mcp_records = db.query(McpServer).filter(McpServer.id.in_(request_body.connector_ids)).all()
        dynamic_mcp_servers = []

        for server in mcp_records:
            entry: dict[str, Any] = {
                "name": server.name,
                "enabled": True,
                "transport": server.transport_type,
                "endpoint_url": server.endpoint_url,
            }
            if server.auth_type == "api_key":
                secret_name = f"loom/mcp/{server.name}/api-key/{actor_id}"
                entry["auth"] = {
                    "type": "api_key",
                    "credentials_secret_arn": secret_name,
                    "api_key_header_name": server.api_key_header_name or "x-api-key",
                }
            elif server.auth_type == "oauth2":
                cred_provider = getattr(server, "credential_provider_name", None) or f"loom-{agent.name}-mcp-{server.name}"
                auth_entry: dict[str, str] = {
                    "type": "oauth2",
                    "well_known_endpoint": server.oauth2_well_known_url or "",
                    "credential_provider_name": cred_provider,
                }
                if server.oauth2_scopes:
                    auth_entry["scopes"] = server.oauth2_scopes
                if getattr(server, "delegation_mode", None):
                    auth_entry["delegation_mode"] = server.delegation_mode
                if getattr(server, "obo_grant_type", None):
                    auth_entry["obo_grant_type"] = server.obo_grant_type
                if getattr(server, "oauth2_audience", None):
                    auth_entry["audience"] = server.oauth2_audience
                entry["auth"] = auth_entry
            dynamic_mcp_servers.append(entry)
            if server.supports_elicitation == "true":
                has_elicitation_connector = True
        logger.info("Resolved %d dynamic MCP connectors for invocation (elicitation=%s)", len(dynamic_mcp_servers), has_elicitation_connector)

    # ---- Detect OBO delegation mode and static elicitation from AGENT_CONFIG_JSON ----
    # If any integration has delegation_mode="obo", we must forward the user's
    # access token so the runtime can perform RFC 8693 token exchange.
    delegation_mode = "m2m"
    try:
        config_map_agent = {e.key: e.value for e in agent.config_entries}
        raw_cfg = config_map_agent.get("AGENT_CONFIG_JSON", "")
        if raw_cfg:
            cfg = json.loads(raw_cfg)
            integrations = cfg.get("integrations", {}) or {}
            mcp_list = integrations.get("mcp_servers", []) or []
            a2a_list = integrations.get("a2a_agents", []) or []
            if any((i.get("delegation_mode") or "m2m") == "obo" for i in (mcp_list + a2a_list)):
                delegation_mode = "obo"
            # Check if any static MCP server supports elicitation
            if not has_elicitation_connector:
                for mcp_cfg in mcp_list:
                    if mcp_cfg.get("supports_elicitation") == "true" or mcp_cfg.get("supports_elicitation") is True:
                        has_elicitation_connector = True
                        break
    except (ValueError, TypeError) as e:
        logger.warning("Failed to parse AGENT_CONFIG_JSON for delegation_mode detection: %s", e)

    # Resolve user access token for OBO: prefer Authorization header from the
    # incoming request (the frontend user's login token). This is the
    # subject_token for RFC 8693 exchange.
    user_access_token: str | None = None
    if delegation_mode == "obo":
        incoming_auth = request.headers.get("Authorization", "")
        if incoming_auth.startswith("Bearer "):
            user_access_token = incoming_auth[7:]
        # If the resolved agent bearer came from the user's login token, reuse it.
        elif token_source == "user" and access_token:  # nosec B105 — "user" is a token-source label, not a password
            user_access_token = access_token
        logger.info(
            "OBO delegation active for agent %s: user_access_token_present=%s",
            agent_id, bool(user_access_token),
        )

    logger.info("Elicitation support resolved: has_elicitation_connector=%s", has_elicitation_connector)

    # Resolve active approval policies for the agent
    approval_policies_payload: list[dict[str, Any]] | None = None
    active_policies = db.query(ApprovalPolicy).filter(ApprovalPolicy.enabled == True).all()  # noqa: E712
    if active_policies:
        approval_policies_payload = [p.to_dict() for p in active_policies]

    # Dispatch to harness or standard invoke path
    if agent.source == "harness" and agent.harness_id:
        # Convert dynamic MCP connectors to harness tool format
        dynamic_harness_tools: list[dict[str, Any]] | None = None
        if dynamic_mcp_servers:
            dynamic_harness_tools = []
            for mcp in dynamic_mcp_servers:
                tool_entry: dict[str, Any] = {
                    "type": "remote_mcp",
                    "name": mcp["name"],
                    "config": {"remoteMcp": {"url": mcp["endpoint_url"]}},
                }
                dynamic_harness_tools.append(tool_entry)

        stream_gen = invoke_harness_agent_stream(
            agent, session, invocation, db, client_invoke_time,
            request_body.prompt, user.actor_id,
            runtime_model_id, access_token, token_source,
            dynamic_harness_tools,
            user_access_token=user_access_token,
            delegation_mode=delegation_mode,
        )
    else:
        stream_gen = invoke_agent_stream(
            agent, session, invocation, db, client_invoke_time,
            request_body.prompt, access_token, token_source,
            user.actor_id,
            runtime_model_id, dynamic_mcp_servers,
            approval_policies=approval_policies_payload,
            supports_elicitation=has_elicitation_connector,
            user_access_token=user_access_token,
            delegation_mode=delegation_mode,
        )

    return StreamingResponse(
        stream_gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.websocket("/{agent_id}/ws")
async def invoke_agent_websocket(
    websocket: WebSocket,
    agent_id: int,
):
    """WebSocket endpoint for agent invocation with MCP elicitation support.

    Enables bidirectional communication so MCP elicitation requests from the
    agent can be relayed to the frontend and responses sent back inline.

    Protocol:
    - Client sends: {"type": "prompt", "prompt": "...", "session_id": "...", ...}
    - Server sends: {"type": "text", "content": "..."}
    - Server sends: {"type": "elicitation", "id": "...", "message": "..."}
    - Client sends: {"type": "elicitation_response", "id": "...", "action": "accept|decline", "content": {...}}
    - Server sends: {"type": "result", "content": "..."}
    - Server sends: {"type": "error", "content": "..."}
    """
    await websocket.accept()

    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            await websocket.send_json({"type": "error", "content": f"Agent {agent_id} not found"})
            await websocket.close()
            return

        region = agent.region or os.environ.get("AWS_REGION", "us-east-1")

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "prompt")

            if msg_type != "prompt":
                continue

            prompt = data.get("prompt", "")
            qualifier = data.get("qualifier", "DEFAULT")
            session_id = data.get("session_id") or str(uuid.uuid4())
            actor_id = data.get("actor_id", "loom-agent")

            # Resolve dynamic MCP servers for elicitation
            connector_ids = data.get("connector_ids")
            dynamic_mcp_servers = None
            if connector_ids:
                mcp_servers = db.query(McpServer).filter(McpServer.id.in_(connector_ids)).all()
                dynamic_mcp_servers = []
                for s in mcp_servers:
                    server_data: dict[str, Any] = {
                        "name": s.name,
                        "transport": s.transport_type,
                        "endpoint_url": s.endpoint_url,
                    }
                    dynamic_mcp_servers.append(server_data)

            # Resolve access token (simplified — reuses same logic as HTTP path)
            access_token = data.get("bearer_token")

            await websocket.send_json({"type": "session_start", "session_id": session_id})

            gen = invoke_agent_ws(
                arn=agent.arn,
                qualifier=qualifier,
                session_id=session_id,
                prompt=prompt,
                region=region,
                access_token=access_token,
                actor_id=actor_id,
                dynamic_mcp_servers=dynamic_mcp_servers,
                runtime_model_id=data.get("model_id"),
            )

            try:
                event = await gen.__anext__()
                while True:
                    await websocket.send_json(event)

                    if event.get("type") == "elicitation":
                        # Wait for client to send elicitation response
                        response_data = await websocket.receive_json()
                        response_json = json.dumps(response_data)
                        event = await gen.asend(response_json)
                    elif event.get("type") in ("result", "error"):
                        break
                    else:
                        event = await gen.__anext__()
            except StopAsyncIteration:
                pass
            except Exception as e:
                logger.error("WebSocket invocation error: %s", e)
                await websocket.send_json({"type": "error", "content": str(e)})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for agent %d", agent_id)
    except Exception as e:
        logger.error("WebSocket handler error: %s", e)
    finally:
        db.close()


@router.post("/{agent_id}/token")
def get_agent_token(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("invoke")),
    db: Session = Depends(get_db),
) -> dict:
    """Get an access token for an agent with a Cognito authorizer.

    Reads COGNITO_CLIENT_ID and COGNITO_CLIENT_SECRET from the agent's
    config entries and exchanges them for a token via the client credentials grant.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    auth_config = agent.get_authorizer_config()
    if not auth_config or auth_config.get("type") != "cognito" or not auth_config.get("pool_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent does not have a Cognito authorizer configured",
        )

    config_map = {e.key: e.value for e in agent.config_entries}
    client_id = config_map.get("COGNITO_CLIENT_ID", "")
    secret_arn = config_map.get("COGNITO_CLIENT_SECRET_ARN", "")
    if not client_id or not secret_arn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="COGNITO_CLIENT_ID and COGNITO_CLIENT_SECRET_ARN must be set in agent configuration",
        )

    try:
        client_secret = get_secret(secret_arn, agent.region)
        token_response = get_cognito_token(
            pool_id=auth_config["pool_id"],
            client_id=client_id,
            client_secret=client_secret,
            scopes=auth_config.get("allowed_scopes") or None,
        )
        return {
            "access_token": token_response["access_token"],
            "token_type": token_response.get("token_type", "Bearer"),
            "expires_in": token_response.get("expires_in"),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to get token from Cognito: {str(e)}",
        )


@router.get("/{agent_id}/sessions", response_model=List[SessionResponse])
def list_sessions(
    agent_id: int,
    user_id: Optional[str] = Query(None, description="Filter sessions by user_id"),
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> List[SessionResponse]:
    """List all invocation sessions for an agent with their invocations."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found"
        )

    filters = [
        InvocationSession.agent_id == agent_id,
        InvocationSession.hidden_at.is_(None),
    ]
    # Non-admin users always see only their own sessions (server-side enforcement)
    if "t-admin" not in user.groups:
        filters.append(InvocationSession.user_id == user.username)
    elif user_id:
        filters.append(InvocationSession.user_id == user_id)

    sessions = db.query(InvocationSession).filter(
        *filters,
    ).order_by(InvocationSession.created_at.desc()).all()

    from app.routers.settings import get_cpu_io_wait_discount
    io_discount = get_cpu_io_wait_discount(db)

    result = []
    for session in sessions:
        live_status = compute_live_status(session, db)
        _backfill_idle_costs(session, live_status, db)
        sdict = session.to_dict()
        sdict["invocations"] = [_apply_view_time_costs(inv, io_discount) for inv in sdict.get("invocations", [])]
        result.append(SessionResponse(**sdict, live_status=live_status))
    return result


@router.get("/{agent_id}/sessions/{session_id}", response_model=SessionResponse)
def get_session(
    agent_id: int,
    session_id: str,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Get a specific session with all its invocations."""
    session = db.query(InvocationSession).filter(
        InvocationSession.agent_id == agent_id,
        InvocationSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found for agent {agent_id}"
        )

    live_status = compute_live_status(session, db)
    _backfill_idle_costs(session, live_status, db)
    from app.routers.settings import get_cpu_io_wait_discount
    io_discount = get_cpu_io_wait_discount(db)
    sdict = session.to_dict()
    sdict["invocations"] = [_apply_view_time_costs(inv, io_discount) for inv in sdict.get("invocations", [])]
    return SessionResponse(**sdict, live_status=live_status)


@router.delete("/{agent_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def hide_session(
    agent_id: int,
    session_id: str,
    user: UserInfo = Depends(require_scopes("invoke")),
    db: Session = Depends(get_db),
) -> None:
    """Hide a session from the user's conversation history (soft delete).

    Sets hidden_at on the session record — no data is removed. The session
    remains visible to admins and continues to contribute to cost reporting.
    Only the session owner may hide their own sessions.
    """
    session = db.query(InvocationSession).filter(
        InvocationSession.agent_id == agent_id,
        InvocationSession.session_id == session_id,
    ).first()

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Ownership check — users may only hide their own sessions
    if session.user_id != (user.username or user.sub):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only remove your own conversations")

    # Only allow hiding completed sessions
    if session.status in ("pending", "streaming"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot remove an active session")

    session.hidden_at = datetime.utcnow()
    db.commit()


@router.get("/{agent_id}/sessions/{session_id}/invocations/{invocation_id}", response_model=InvocationResponse)
def get_invocation(
    agent_id: int,
    session_id: str,
    invocation_id: str,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> InvocationResponse:
    """Get a specific invocation within a session."""
    # Look up session first to validate agent_id
    session = db.query(InvocationSession).filter(
        InvocationSession.agent_id == agent_id,
        InvocationSession.session_id == session_id
    ).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found for agent {agent_id}"
        )

    # Look up invocation
    invocation = db.query(Invocation).filter(
        Invocation.session_id == session.session_id,
        Invocation.invocation_id == invocation_id
    ).first()

    if not invocation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invocation {invocation_id} not found in session {session_id}"
        )

    from app.routers.settings import get_cpu_io_wait_discount
    io_discount = get_cpu_io_wait_discount(db)
    return InvocationResponse(**_apply_view_time_costs(invocation.to_dict(), io_discount))
