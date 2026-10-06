"""Agent kill switch: Stop and Resume an agent from Loom, with an audit trail.

The mechanism lives in ``app/services/kill_switch.py``. Reading the state needs
``agent:read``; Stop and Resume need ``agent:write``. Both enforce the same
loom:group access as every other agent route (``get_agent_or_404``), and they
refuse to act when the execution role is shared with an agent the caller
cannot access, because an IAM deny on a role stops every agent using it.
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
from app.routers.utils import check_resource_group_access, get_agent_or_404
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
    acknowledge_shared_role: bool = Field(
        False, description="Confirm that the other agents on the same execution role change state too",
    )

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
    result: str  # stopped | not_running | failed | skipped
    request_id: str | None = None
    error: str | None = None


class KillSwitchEventResponse(BaseModel):
    id: int
    agent_id: int
    agent_name: str | None = None
    action: str
    reason: str
    actor: str
    role_arn: str
    policy_arn: str
    iam_change: str
    iam_request_id: str | None = None
    sessions: list[SessionStopResult] = []
    shared_with: list[int] = []
    created_at: str | None = None


class SharedAgent(BaseModel):
    id: int
    name: str | None = None
    stopped: bool


KillSwitchState = Literal[
    "running", "stopped", "stop_not_enforced", "stopped_outside_loom", "unknown", "unavailable",
]


class KillSwitchStatusResponse(BaseModel):
    configured: bool
    unavailable_reason: str | None = None
    policy_arn: str | None = None
    role_arn: str | None = None
    state: KillSwitchState
    stopped: bool
    stopped_at: str | None = None
    stopped_by: str | None = None
    stop_reason: str | None = None
    deny_attached: bool | None = None
    iam_error: str | None = None
    shared_with: list[SharedAgent] = []
    shared_outside_access: int = 0
    events: list[KillSwitchEventResponse] = []


class KillSwitchActionResponse(BaseModel):
    changed: bool
    message: str
    status: KillSwitchStatusResponse
    events: list[KillSwitchEventResponse] = []


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


def _shared_agents(db: Session, agent: Agent, role_arn: str, user: UserInfo) -> tuple[list[Agent], int]:
    """Other Loom agents on the same execution role: (those the caller may act on, count of the rest)."""
    visible: list[Agent] = []
    hidden = 0
    for other in db.query(Agent).filter(Agent.id != agent.id).all():
        if ks.execution_role_arn(other) != role_arn:
            continue
        try:
            check_resource_group_access(other, user, resource_label="agent")
        except HTTPException:
            hidden += 1
            continue
        visible.append(other)
    return visible, hidden


def _status(db: Session, agent: Agent, user: UserInfo) -> KillSwitchStatusResponse:
    record = {
        "stopped": agent.stopped_at is not None,
        "stopped_at": _iso(agent.stopped_at),
        "stopped_by": agent.stopped_by,
        "stop_reason": agent.stop_reason,
        "events": _events(db, agent.id),
    }
    role_arn = ks.execution_role_arn(agent)
    try:
        policy, role_arn, role = ks.resolve_target(agent)
    except ks.KillSwitchUnavailable as exc:
        try:
            configured_policy: str | None = ks.policy_arn()
        except ks.KillSwitchUnavailable:
            configured_policy = None
        return KillSwitchStatusResponse(
            configured=configured_policy is not None, unavailable_reason=str(exc),
            policy_arn=configured_policy, role_arn=role_arn, state="unavailable", **record,
        )

    shared, hidden = _shared_agents(db, agent, role_arn, user)
    deny_attached: bool | None
    iam_error = None
    try:
        deny_attached = ks.is_attached(role, policy)
    except (ClientError, BotoCoreError) as err:
        deny_attached, iam_error = None, _describe(err)
    return KillSwitchStatusResponse(
        configured=True, policy_arn=policy, role_arn=role_arn,
        state=ks.derive_state(agent.stopped_at is not None, deny_attached),
        deny_attached=deny_attached, iam_error=iam_error,
        shared_with=[SharedAgent(id=a.id, name=a.name, stopped=a.stopped_at is not None) for a in shared],
        shared_outside_access=hidden, **record,
    )


def _target_or_409(agent: Agent) -> tuple[str, str, str]:
    try:
        return ks.resolve_target(agent)
    except ks.KillSwitchUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _shared_or_403(db: Session, agent: Agent, role_arn: str, role: str, user: UserInfo) -> list[Agent]:
    shared, hidden = _shared_agents(db, agent, role_arn, user)
    if hidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"This agent's execution role ({role}) is also used by {hidden} agent(s) outside your "
                "group, and the kill switch acts on the whole role. Ask a super-admin to do it."
            ),
        )
    return shared


def _attached_or_502(role: str, policy: str) -> bool:
    try:
        return ks.is_attached(role, policy)
    except (ClientError, BotoCoreError) as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not read the policies attached to role {role}: {_describe(err)}",
        )


def _require_shared_ack(verb: str, role: str, shared: list[Agent], acknowledged: bool) -> None:
    if not shared or acknowledged:
        return
    names = ", ".join(a.name or str(a.id) for a in shared)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"{verb} this agent also affects {len(shared)} other agent(s) on the same execution role "
            f"({role}): {names}. Send acknowledge_shared_role=true to confirm."
        ),
    )


def _record(
    db: Session, target: Agent, action: str, reason: str, user: UserInfo, role_arn: str, policy: str,
    iam_change: str, request_id: str | None, sessions: list[dict[str, Any]], shared_ids: list[int],
    now: datetime,
) -> AgentKillSwitchEvent:
    event = AgentKillSwitchEvent(
        agent_id=target.id, agent_name=target.name, agent_arn=target.arn, action=action, reason=reason,
        actor=user.username, role_arn=role_arn, policy_arn=policy, iam_change=iam_change,
        iam_request_id=request_id, sessions=json.dumps(sessions), shared_with=json.dumps(shared_ids),
        created_at=now,
    )
    db.add(event)
    return event


def _commit_or_undo(db: Session, undo: Callable[[], Any] | None, what: str) -> None:
    """Commit the record; if that fails, undo the IAM change so Loom and the role agree."""
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Kill switch: could not record the %s", what)
        if undo is not None:
            try:
                undo()
            except Exception:
                logger.exception("Kill switch: could not undo the IAM change after a failed %s", what)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Loom could not record the {what}, so the IAM change was undone. Try again.",
        )


def _session_summary(events: list[AgentKillSwitchEvent]) -> str:
    counts = {"stopped": 0, "not_running": 0, "failed": 0, "skipped": 0}
    for event in events:
        for result in event.get_sessions():
            counts[result.get("result", "failed")] = counts.get(result.get("result", "failed"), 0) + 1
    if not any(counts.values()):
        return "No recent sessions to stop."
    parts = [f"{counts['stopped']} session(s) stopped"]
    if counts["not_running"]:
        parts.append(f"{counts['not_running']} already ended")
    if counts["failed"]:
        parts.append(f"{counts['failed']} could not be stopped (the deny still applies to them)")
    if counts["skipped"]:
        parts.append(f"{counts['skipped']} skipped (not AgentCore Runtime sessions)")
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
    """The agent's kill-switch state: Loom's record, the role's live state, and the audit trail."""
    agent = get_agent_or_404(agent_id, db, user)
    return _status(db, agent, user)


@router.post("/{agent_id}/stop", response_model=KillSwitchActionResponse)
def stop_agent(
    agent_id: int,
    request: KillSwitchRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> KillSwitchActionResponse:
    """Stop the agent: attach the deny policy to its execution role, then stop its known sessions."""
    agent = get_agent_or_404(agent_id, db, user)
    policy, role_arn, role = _target_or_409(agent)
    shared = _shared_or_403(db, agent, role_arn, role, user)
    attached = _attached_or_502(role, policy)

    if agent.stopped_at is not None and attached:
        return KillSwitchActionResponse(
            changed=False, message="The agent is already stopped; nothing changed.",
            status=_status(db, agent, user),
        )
    _require_shared_ack("Stopping", role, shared, request.acknowledge_shared_role)

    iam_change, request_id = "already_attached", None
    if not attached:
        try:
            request_id = ks.attach(role, policy)
        except (ClientError, BotoCoreError) as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AWS refused to attach the kill-switch policy to role {role}: {_describe(err)}",
            )
        iam_change = "attached"

    now = datetime.utcnow()
    affected = [agent, *shared]
    events: list[AgentKillSwitchEvent] = []
    for target in affected:
        sessions = ks.stop_sessions(target, ks.recent_sessions(db, target, now))
        target.stopped_at, target.stopped_by, target.stop_reason = now, user.username, request.reason
        events.append(_record(
            db, target, "stop", request.reason, user, role_arn, policy, iam_change, request_id,
            sessions, [a.id for a in affected if a.id != target.id], now,
        ))
    _commit_or_undo(db, (lambda: ks.detach(role, policy)) if iam_change == "attached" else None, "stop")
    logger.warning(
        "Kill switch: STOP agent=%s by=%s role=%s iam=%s request_id=%s shared=%s reason=%r",
        agent.id, user.username, role, iam_change, request_id, [a.id for a in shared], request.reason,
    )

    message = f"Stopped: role {role} now denies everything except logs, traces and metrics. "
    message += _session_summary(events)
    if shared:
        message += " Also stopped: " + ", ".join(a.name or str(a.id) for a in shared) + "."
    for event in events:
        db.refresh(event)
    return KillSwitchActionResponse(
        changed=True, message=message, status=_status(db, agent, user),
        events=[KillSwitchEventResponse(**e.to_dict()) for e in events],
    )


@router.post("/{agent_id}/resume", response_model=KillSwitchActionResponse)
def resume_agent(
    agent_id: int,
    request: KillSwitchRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> KillSwitchActionResponse:
    """Resume the agent: detach the deny policy from its execution role. Nothing is redeployed."""
    agent = get_agent_or_404(agent_id, db, user)
    policy, role_arn, role = _target_or_409(agent)
    shared = _shared_or_403(db, agent, role_arn, role, user)
    attached = _attached_or_502(role, policy)

    if agent.stopped_at is None and not attached:
        return KillSwitchActionResponse(
            changed=False, message="The agent is not stopped; nothing changed.",
            status=_status(db, agent, user),
        )
    _require_shared_ack("Resuming", role, shared, request.acknowledge_shared_role)

    iam_change, request_id = "already_detached", None
    if attached:
        try:
            detached, request_id = ks.detach(role, policy)
        except (ClientError, BotoCoreError) as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AWS refused to detach the kill-switch policy from role {role}: {_describe(err)}",
            )
        iam_change = "detached" if detached else "already_detached"

    now = datetime.utcnow()
    affected = [agent, *shared]
    events: list[AgentKillSwitchEvent] = []
    for target in affected:
        was_stopped = target.stopped_at is not None
        target.stopped_at = target.stopped_by = target.stop_reason = None
        if target is agent or was_stopped:
            events.append(_record(
                db, target, "resume", request.reason, user, role_arn, policy, iam_change, request_id,
                [], [a.id for a in affected if a.id != target.id], now,
            ))
    _commit_or_undo(db, (lambda: ks.attach(role, policy)) if iam_change == "detached" else None, "resume")
    logger.warning(
        "Kill switch: RESUME agent=%s by=%s role=%s iam=%s request_id=%s shared=%s reason=%r",
        agent.id, user.username, role, iam_change, request_id, [a.id for a in shared], request.reason,
    )

    message = f"Resumed: the kill-switch policy is no longer attached to role {role}; no redeployment needed."
    if shared:
        message += " Also resumed: " + ", ".join(a.name or str(a.id) for a in shared) + "."
    for event in events:
        db.refresh(event)
    return KillSwitchActionResponse(
        changed=True, message=message, status=_status(db, agent, user),
        events=[KillSwitchEventResponse(**e.to_dict()) for e in events],
    )
