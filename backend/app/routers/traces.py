"""Trace retrieval endpoints using OTEL log events from CloudWatch."""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.routers.agents import derive_log_group
from app.services.otel import (
    fetch_otel_events,
    parse_otel_traces,
    parse_otel_trace_detail,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["traces"])


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class TraceEvent(BaseModel):
    """A single OTEL log event within a span."""
    observed_time_iso: str
    severity_number: int
    scope: str
    body: Any


class TraceSpan(BaseModel):
    """A span containing ordered OTEL events."""
    span_id: str
    scope: str
    start_time_iso: str
    end_time_iso: str
    duration_ms: float
    event_count: int
    events: List[TraceEvent]


class TraceSummary(BaseModel):
    """Summary of a single trace."""
    trace_id: str
    session_id: Optional[str]
    start_time_iso: str
    end_time_iso: str
    duration_ms: float
    span_count: int
    event_count: int


class TraceListResponse(BaseModel):
    """Response containing a list of trace summaries."""
    traces: List[TraceSummary]


class TraceDetailResponse(BaseModel):
    """Full trace detail with spans and events."""
    trace_id: str
    session_id: Optional[str]
    start_time_iso: str
    end_time_iso: str
    duration_ms: float
    span_count: int
    event_count: int
    spans: List[TraceSpan]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/{agent_id}/sessions/{session_id}/traces",
    response_model=TraceListResponse,
)
def get_session_traces(
    agent_id: int,
    session_id: str,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> TraceListResponse:
    """List traces for a session from OTEL runtime logs.

    Fetches all events from the otel-rt-logs stream (single API call)
    and builds summaries from the complete dataset so counts are accurate.
    Filters to traces that belong to the given session_id.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )

    if not agent.runtime_id:
        return TraceListResponse(traces=[])

    log_group = derive_log_group(agent.runtime_id, "DEFAULT")

    # Fetch all events from otel-rt-logs (no filter) for accurate counts
    raw_events = fetch_otel_events(
        log_group=log_group,
        region=agent.region,
    )

    if not raw_events:
        return TraceListResponse(traces=[])

    all_traces = parse_otel_traces(raw_events)
    # Filter to traces belonging to this session
    traces = [t for t in all_traces if t["session_id"] == session_id]
    return TraceListResponse(traces=[TraceSummary(**t) for t in traces])


@router.get(
    "/{agent_id}/traces/{trace_id}",
    response_model=TraceDetailResponse,
)
def get_trace_detail(
    agent_id: int,
    trace_id: str,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> TraceDetailResponse:
    """Get full trace detail with spans and events."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )

    if not agent.runtime_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found"
        )

    log_group = derive_log_group(agent.runtime_id, "DEFAULT")

    raw_events = fetch_otel_events(
        log_group=log_group,
        region=agent.region,
        filter_pattern=f'"{trace_id}"',
    )

    detail = parse_otel_trace_detail(raw_events, trace_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found"
        )

    return TraceDetailResponse(**detail)
