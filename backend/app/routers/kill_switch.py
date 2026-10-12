"""Agent kill switch: Stop and Resume an agent from Loom, with an audit trail.

The mechanism lives in ``app/services/kill_switch.py``: Stop adds a deny
statement to the AgentCore Runtime's resource policy and ends its known
sessions; Resume removes the statement. Loom never writes IAM. Reading the
state needs ``agent:read``; Stop and Resume need ``agent:write``. Both enforce
the same loom:group access as every other agent route (``get_agent_or_404``).
The deny applies to one runtime only, so stopping an agent never stops another.
"""
import json
import logging
from datetime import datetime
from typing import Any, Callable, Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.kill_switch import AgentKillSwitchEvent
from app.routers.utils import get_agent_or_404
from app.services import kill_switch as ks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["kill-switch"])

EVENTS_SHOWN = 20


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class KillSwitchRequest(BaseModel):
    """Body of a Stop or Resume: the reason is mandatory and kept in the audit trail."""
    reason: str = Field(..., max_length=500, description="Why the agent is stopped or resumed")

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A reason is required")
        return value


class SessionStopResult(BaseModel):
    session_id: str
    qualifier: str | None = None
    result: str  # stopped | not_running | failed
    request_id: str | None = None
    error: str | None = None


class KillSwitchEventResponse(BaseModel):
    id: int
    agent_id: int
    agent_name: str | None = None
    runtime_arn: str
    action: str
    reason: str
    actor: str
    policy_change: str
    request_id: str | None = None
    sessions: list[SessionStopResult] = []
    created_at: str | None = None


KillSwitchState = Literal[
    "running", "stopped", "stop_not_enforced", "stopped_outside_loom", "unknown", "unavailable",
]


class KillSwitchStatusResponse(BaseModel):
    unavailable_reason: str | None = None
    runtime_arn: str | None = None
    state: KillSwitchState
    stopped: bool
    stopped_at: str | None = None
    stopped_by: str | None = None
    stop_reason: str | None = None
    deny_present: bool | None = None
    policy_error: str | None = None
    denied_actions: list[str] = []
    events: list[KillSwitchEventResponse] = []


class KillSwitchActionResponse(BaseModel):
    changed: bool
    message: str
    status: KillSwitchStatusResponse
    event: KillSwitchEventResponse | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(value: datetime | None) -> str | None:
    return (value.isoformat() + "Z") if value else None


def _describe(err: Exception) -> str:
    if isinstance(err, ClientError):
        return ks.describe_client_error(err)
    return f"{type(err).__name__}: {err}"


def _events(db: Session, agent_id: int) -> list[KillSwitchEventResponse]:
    rows = (
        db.query(AgentKillSwitchEvent)
        .filter(AgentKillSwitchEvent.agent_id == agent_id)
        .order_by(AgentKillSwitchEvent.created_at.desc(), AgentKillSwitchEvent.id.desc())
        .limit(EVENTS_SHOWN)
        .all()
    )
    return [KillSwitchEventResponse(**row.to_dict()) for row in rows]


def _status(db: Session, agent: Agent) -> KillSwitchStatusResponse:
    record = {
        "stopped": agent.stopped_at is not None,
        "stopped_at": _iso(agent.stopped_at),
        "stopped_by": agent.stopped_by,
        "stop_reason": agent.stop_reason,
        "events": _events(db, agent.id),
    }
    try:
        runtime_arn, region = ks.resolve_target(agent)
    except ks.KillSwitchUnavailable as exc:
        return KillSwitchStatusResponse(
            unavailable_reason=str(exc), runtime_arn=agent.arn, state="unavailable", **record,
        )

    deny_present: bool | None
    policy_error = None
    try:
        policy, _ = ks.get_policy(runtime_arn, region)
        deny_present = ks.has_deny(policy, runtime_arn)
    except ks.ForeignPolicyStatement as exc:
        deny_present, policy_error = None, str(exc)
    except (ClientError, BotoCoreError, ValueError) as err:
        deny_present, policy_error = None, _describe(err)
    return KillSwitchStatusResponse(
        runtime_arn=runtime_arn,
        state=ks.derive_state(agent.stopped_at is not None, deny_present),
        deny_present=deny_present, policy_error=policy_error,
        denied_actions=list(ks.DENIED_ACTIONS), **record,
    )


def _target_or_409(agent: Agent) -> tuple[str, str]:
    try:
        return ks.resolve_target(agent)
    except ks.KillSwitchUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _deny_present_or_error(runtime_arn: str, region: str) -> bool:
    try:
        policy, _ = ks.get_policy(runtime_arn, region)
        return ks.has_deny(policy, runtime_arn)
    except ks.ForeignPolicyStatement as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (ClientError, BotoCoreError, ValueError) as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not read the runtime's resource policy: {_describe(err)}",
        )


def _write_or_502(action: Callable[[], tuple[bool, str | None]], what: str) -> tuple[bool, str | None]:
    try:
        return action()
    except ks.ForeignPolicyStatement as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (ClientError, BotoCoreError, ValueError) as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AWS refused to {what} the runtime's resource policy: {_describe(err)}",
        )


def _record(
    db: Session, agent: Agent, action: str, reason: str, user: UserInfo, runtime_arn: str,
    policy_change: str, request_id: str | None, sessions: list[dict[str, Any]], now: datetime,
) -> AgentKillSwitchEvent:
    event = AgentKillSwitchEvent(
        agent_id=agent.id, agent_name=agent.name, runtime_arn=runtime_arn, action=action,
        reason=reason, actor=user.username, policy_change=policy_change, request_id=request_id,
        sessions=json.dumps(sessions), created_at=now,
    )
    db.add(event)
    return event


def _commit_or_undo(db: Session, undo: Callable[[], Any] | None, what: str) -> None:
    """Commit the record; if that fails, undo the policy change so Loom and the runtime agree."""
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Kill switch: could not record the %s", what)
        if undo is not None:
            try:
                undo()
            except Exception:
                logger.exception("Kill switch: could not undo the policy change after a failed %s", what)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Loom could not record the {what}, so the policy change was undone. Try again.",
        )


def _session_summary(sessions: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {"stopped": 0, "not_running": 0, "failed": 0}
    for result in sessions:
        key = result.get("result", "failed")
        counts[key] = counts.get(key, 0) + 1
    if not any(counts.values()):
        return "No recent sessions to stop."
    parts = [f"{counts['stopped']} session(s) stopped"]
    if counts["not_running"]:
        parts.append(f"{counts['not_running']} already ended")
    if counts["failed"]:
        parts.append(f"{counts['failed']} could not be stopped (new calls to them are still denied)")
    return ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/kill-switch", response_model=KillSwitchStatusResponse)
def get_kill_switch(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> KillSwitchStatusResponse:
    """The agent's kill-switch state: Loom's record, the runtime policy's live state, and the audit trail."""
    agent = get_agent_or_404(agent_id, db, user)
    return _status(db, agent)


@router.post("/{agent_id}/stop", response_model=KillSwitchActionResponse)
def stop_agent(
    agent_id: int,
    request: KillSwitchRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> KillSwitchActionResponse:
    """Stop the agent: deny every invocation in its runtime's resource policy, then end its known sessions."""
    agent = get_agent_or_404(agent_id, db, user)
    runtime_arn, region = _target_or_409(agent)
    present = _deny_present_or_error(runtime_arn, region)

    if agent.stopped_at is not None and present:
        return KillSwitchActionResponse(
            changed=False, message="The agent is already stopped; nothing changed.",
            status=_status(db, agent),
        )

    # Deny first, then end the sessions, so nothing can start a new call in between.
    policy_change, request_id = "already_denied", None
    if not present:
        added, request_id = _write_or_502(lambda: ks.add_deny(runtime_arn, region), "update")
        policy_change = "deny_added" if added else "already_denied"

    now = datetime.utcnow()
    sessions = ks.stop_sessions(runtime_arn, region, ks.recent_sessions(db, agent, now))
    agent.stopped_at, agent.stopped_by, agent.stop_reason = now, user.username, request.reason
    event = _record(db, agent, "stop", request.reason, user, runtime_arn, policy_change,
                    request_id, sessions, now)
    _commit_or_undo(
        db, (lambda: ks.remove_deny(runtime_arn, region)) if policy_change == "deny_added" else None,
        "stop",
    )
    logger.warning(
        "Kill switch: STOP agent=%s by=%s runtime=%s policy=%s request_id=%s reason=%r",
        agent.id, user.username, runtime_arn, policy_change, request_id, request.reason,
    )
    db.refresh(event)
    return KillSwitchActionResponse(
        changed=True,
        message="Stopped: the runtime's resource policy now denies every invocation. "
                + _session_summary(sessions),
        status=_status(db, agent), event=KillSwitchEventResponse(**event.to_dict()),
    )


@router.post("/{agent_id}/resume", response_model=KillSwitchActionResponse)
def resume_agent(
    agent_id: int,
    request: KillSwitchRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> KillSwitchActionResponse:
    """Resume the agent: remove Loom's deny statement from its runtime's resource policy. Nothing is redeployed."""
    agent = get_agent_or_404(agent_id, db, user)
    runtime_arn, region = _target_or_409(agent)
    present = _deny_present_or_error(runtime_arn, region)

    if agent.stopped_at is None and not present:
        return KillSwitchActionResponse(
            changed=False, message="The agent is not stopped; nothing changed.",
            status=_status(db, agent),
        )

    policy_change, request_id = "already_removed", None
    if present:
        removed, request_id = _write_or_502(lambda: ks.remove_deny(runtime_arn, region), "update")
        policy_change = "deny_removed" if removed else "already_removed"

    now = datetime.utcnow()
    agent.stopped_at = agent.stopped_by = agent.stop_reason = None
    event = _record(db, agent, "resume", request.reason, user, runtime_arn, policy_change,
                    request_id, [], now)
    _commit_or_undo(
        db, (lambda: ks.add_deny(runtime_arn, region)) if policy_change == "deny_removed" else None,
        "resume",
    )
    logger.warning(
        "Kill switch: RESUME agent=%s by=%s runtime=%s policy=%s request_id=%s reason=%r",
        agent.id, user.username, runtime_arn, policy_change, request_id, request.reason,
    )
    db.refresh(event)
    return KillSwitchActionResponse(
        changed=True,
        message="Resumed: Loom's deny statement is removed from the runtime's resource policy; "
                "no redeployment needed.",
        status=_status(db, agent), event=KillSwitchEventResponse(**event.to_dict()),
    )
