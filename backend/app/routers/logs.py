"""CloudWatch log retrieval endpoints."""
import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.memory import Memory
from app.routers.agents import derive_log_group

from app.services.cloudwatch import get_log_events, get_stream_log_events, list_log_streams


router = APIRouter(prefix="/api/agents", tags=["logs"])


# Pydantic models
class LogEvent(BaseModel):
    """Model for a single CloudWatch log event."""
    timestamp_ms: int
    timestamp_iso: str
    message: str
    session_id: str | None


class LogResponse(BaseModel):
    """Response model for log retrieval."""
    log_group: str
    log_stream: str
    events: List[LogEvent]


class LogStreamInfo(BaseModel):
    """Model for a single log stream."""
    name: str
    last_event_time: int


class LogStreamsResponse(BaseModel):
    """Response model for listing log streams."""
    log_group: str
    streams: List[LogStreamInfo]


def iso_to_timestamp_ms(iso_string: str) -> int:
    """Convert ISO 8601 timestamp to Unix milliseconds."""
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _timestamp_ms_to_iso(timestamp_ms: int) -> str:
    """Convert Unix milliseconds to ISO 8601 string."""
    if not timestamp_ms:
        return ""
    dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
    return dt.isoformat()


def _extract_session_id(message: str) -> str | None:
    """Extract session ID from a CloudWatch log message if present."""
    if not message:
        return None
    if message.startswith("{"):
        try:
            log_data = json.loads(message)
            return log_data.get("sessionId")
        except json.JSONDecodeError:
            pass
    return None


def _format_events(events: list[dict]) -> list[LogEvent]:
    """Convert raw CloudWatch events to LogEvent models."""
    return [
        LogEvent(
            timestamp_ms=event.get("timestamp", 0),
            timestamp_iso=_timestamp_ms_to_iso(event.get("timestamp", 0)),
            message=event.get("message", ""),
            session_id=_extract_session_id(event.get("message", ""))
        )
        for event in events
    ]


def _resolve_agent_and_log_group(
    agent_id: int,
    qualifier: str,
    db: Session
) -> tuple[Agent, str]:
    """Look up agent, validate qualifier, and derive log group."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found"
        )

    available_qualifiers = agent.get_available_qualifiers()
    if qualifier not in available_qualifiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Qualifier '{qualifier}' not available. Available: {available_qualifiers}"
        )

    log_group = derive_log_group(agent.runtime_id, qualifier)
    return agent, log_group


@router.get("/{agent_id}/logs/streams", response_model=LogStreamsResponse)
def get_log_stream_list(
    agent_id: int,
    qualifier: str = Query(default="DEFAULT", description="Endpoint qualifier"),
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> LogStreamsResponse:
    """
    List available log streams for an agent, ordered by most recent first.

    Useful for populating a frontend dropdown to select which stream to view.
    """
    agent, log_group = _resolve_agent_and_log_group(agent_id, qualifier, db)

    try:
        streams = list_log_streams(log_group, agent.region)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list log streams: {str(e)}"
        )

    return LogStreamsResponse(
        log_group=log_group,
        streams=[LogStreamInfo(**s) for s in streams]
    )


@router.get("/{agent_id}/logs", response_model=LogResponse)
def get_agent_logs(
    agent_id: int,
    qualifier: str = Query(default="DEFAULT", description="Endpoint qualifier"),
    stream: Optional[str] = Query(default=None, description="Log stream name (defaults to latest stream)"),
    limit: int = Query(default=10000, ge=1, le=10000, description="Max number of log events"),
    start_time: Optional[str] = Query(default=None, description="Filter events after this ISO 8601 timestamp"),
    end_time: Optional[str] = Query(default=None, description="Filter events before this ISO 8601 timestamp"),
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> LogResponse:
    """
    Retrieve recent logs from CloudWatch for this agent.

    By default, returns events from the latest log stream. Use the stream
    parameter to query a specific stream (see /logs/streams for available names).
    """
    agent, log_group = _resolve_agent_and_log_group(agent_id, qualifier, db)

    # Resolve which stream to query
    stream_name = stream
    if not stream_name:
        try:
            streams = list_log_streams(log_group, agent.region)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to list log streams: {str(e)}"
            )
        if not streams:
            return LogResponse(log_group=log_group, log_stream="", events=[])
        stream_name = streams[0]["name"]

    # Convert time filters to milliseconds
    start_time_ms = iso_to_timestamp_ms(start_time) if start_time else None
    end_time_ms = iso_to_timestamp_ms(end_time) if end_time else None

    # Fetch log events from the single stream
    try:
        events = get_stream_log_events(
            log_group=log_group,
            stream_name=stream_name,
            region=agent.region,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve logs: {str(e)}"
        )

    # Enforce limit
    events = events[:limit]

    return LogResponse(
        log_group=log_group,
        log_stream=stream_name,
        events=_format_events(events)
    )


@router.get("/{agent_id}/sessions/{session_id}/logs", response_model=LogResponse)
def get_session_logs(
    agent_id: int,
    session_id: str,
    qualifier: str = Query(default="DEFAULT", description="Endpoint qualifier"),
    limit: int = Query(default=1000, ge=1, le=10000, description="Max number of log events"),
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> LogResponse:
    """
    Retrieve logs filtered to a specific session.

    Searches across all streams since the session may span multiple streams.
    """
    agent, log_group = _resolve_agent_and_log_group(agent_id, qualifier, db)

    # Fetch log events filtered by session_id (searches across streams with retry)
    try:
        events = get_log_events(
            log_group=log_group,
            session_id=session_id,
            region=agent.region,
            start_time_ms=None,
            max_retries=1,
            retry_interval=0
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve logs: {str(e)}"
        )

    logger.info(
        "[get_session_logs] session_id=%s raw_events=%d limit=%d",
        session_id, len(events), limit,
    )

    # Enforce limit
    events = events[:limit]

    return LogResponse(
        log_group=log_group,
        log_stream="(filtered by session)",
        events=_format_events(events)
    )


# --------------------------------------------------------------------------
# Vended log sources
# --------------------------------------------------------------------------

class VendedLogSource(BaseModel):
    """A vended log source available for an agent."""
    key: str
    label: str
    log_group: str
    stream: str


class VendedLogSourcesResponse(BaseModel):
    """Response model listing available vended log sources."""
    sources: List[VendedLogSource]


def _resolve_agent(agent_id: int, db: Session) -> Agent:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.get("/{agent_id}/logs/vended-sources", response_model=VendedLogSourcesResponse)
def list_vended_log_sources(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> VendedLogSourcesResponse:
    """List available vended log sources (runtime and memory) for an agent."""
    agent = _resolve_agent(agent_id, db)

    sources: list[VendedLogSource] = []

    # Runtime vended logs
    if agent.runtime_id:
        sources.append(VendedLogSource(
            key=f"vended:runtime:app:{agent.runtime_id}",
            label="Runtime — Application Logs",
            log_group=f"/aws/vendedlogs/bedrock-agentcore/runtimes/{agent.runtime_id}",
            stream="BedrockAgentCoreRuntime_ApplicationLogs",
        ))
        sources.append(VendedLogSource(
            key=f"vended:runtime:usage:{agent.runtime_id}",
            label="Runtime — Usage Logs",
            log_group=f"/aws/vendedlogs/bedrock-agentcore/runtimes/{agent.runtime_id}",
            stream="BedrockAgentCoreRuntime_UsageLogs",
        ))

    # Memory vended logs — look up memory resources linked to this agent
    from app.models.config_entry import ConfigEntry
    config_entry = db.query(ConfigEntry).filter(
        ConfigEntry.agent_id == agent_id,
        ConfigEntry.key == "AGENT_CONFIG_JSON",
    ).first()
    if config_entry:
        try:
            cfg = json.loads(config_entry.value)
            for res in cfg.get("integrations", {}).get("memory", {}).get("resources", []):
                mid = res.get("memory_id")
                if not mid:
                    continue
                mem = db.query(Memory).filter(Memory.memory_id == mid).first()
                label = f"Memory — Application Logs ({mem.name})" if mem else f"Memory — Application Logs ({mid})"
                sources.append(VendedLogSource(
                    key=f"vended:memory:{mid}",
                    label=label,
                    log_group=f"/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/{mid}",
                    stream="BedrockAgentCoreMemory_ApplicationLogs",
                ))
        except (json.JSONDecodeError, TypeError):
            pass

    return VendedLogSourcesResponse(sources=sources)


@router.get("/{agent_id}/logs/vended", response_model=LogResponse)
def get_vended_logs(
    agent_id: int,
    log_group: str = Query(..., description="Vended log group name"),
    stream: str = Query(..., description="Log stream name within the group"),
    limit: int = Query(default=10000, ge=1, le=10000),
    start_time: Optional[str] = Query(default=None),
    end_time: Optional[str] = Query(default=None),
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> LogResponse:
    """Retrieve log events from a vended log group."""
    agent = _resolve_agent(agent_id, db)

    start_time_ms = iso_to_timestamp_ms(start_time) if start_time else None
    end_time_ms = iso_to_timestamp_ms(end_time) if end_time else None

    try:
        events = get_stream_log_events(
            log_group=log_group,
            stream_name=stream,
            region=agent.region,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve vended logs: {str(e)}",
        )

    events = events[:limit]

    return LogResponse(
        log_group=log_group,
        log_stream=stream,
        events=_format_events(events),
    )
