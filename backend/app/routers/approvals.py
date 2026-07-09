"""Approval policy CRUD and human-in-the-loop approval coordination."""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, get_current_user, require_scopes
from app.models.approval_policy import ApprovalPolicy
from app.models.approval_log import ApprovalLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["approvals"])


# ---------------------------------------------------------------------------
# In-memory approval coordination store
# ---------------------------------------------------------------------------
# Maps request_id -> {event: asyncio.Event, decision: str | None, reason: str | None, decided_by: str | None}
_pending_approvals: dict[str, dict[str, Any]] = {}


def create_approval_request(request_id: str | None = None) -> str:
    """Register a pending approval and return its request_id."""
    rid = request_id or str(uuid.uuid4())
    _pending_approvals[rid] = {
        "event": asyncio.Event(),
        "decision": None,
        "reason": None,
        "decided_by": None,
    }
    return rid


def resolve_approval(request_id: str, decision: str, decided_by: str | None = None, reason: str | None = None, content: dict | None = None) -> bool:
    """Resolve a pending approval. Returns True if the request was found."""
    entry = _pending_approvals.get(request_id)
    if not entry:
        return False
    entry["decision"] = decision
    entry["decided_by"] = decided_by
    entry["reason"] = reason
    if content is not None:
        entry["content"] = content
    entry["event"].set()
    return True


async def wait_for_approval(request_id: str, timeout: float = 300.0) -> dict[str, Any]:
    """Wait for an approval decision. Returns the decision dict or timeout."""
    entry = _pending_approvals.get(request_id)
    if not entry:
        return {"decision": "timeout", "reason": "Request not found"}
    try:
        await asyncio.wait_for(entry["event"].wait(), timeout=timeout)
    except asyncio.TimeoutError:
        entry["decision"] = "timeout"
        entry["reason"] = "Approval timed out"
    finally:
        result = {
            "decision": entry.get("decision", "timeout"),
            "reason": entry.get("reason"),
            "decided_by": entry.get("decided_by"),
            "content": entry.get("content"),
        }
        _pending_approvals.pop(request_id, None)
    return result


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ApprovalPolicyCreateRequest(BaseModel):
    name: str
    policy_type: str = Field(..., description="loop_hook, tool_context, or mcp_elicitation")
    tool_match_rules: list[str] = Field(default_factory=list, description="Tool name patterns (glob)")
    approval_mode: str = Field(default="require_approval", description="require_approval or notify_only")
    timeout_seconds: int = Field(default=300)
    agent_scope: dict = Field(default_factory=lambda: {"type": "all"})
    approval_cache_ttl: int = Field(default=0)
    enabled: bool = Field(default=True)


class ApprovalPolicyUpdateRequest(BaseModel):
    name: str | None = None
    policy_type: str | None = None
    tool_match_rules: list[str] | None = None
    approval_mode: str | None = None
    timeout_seconds: int | None = None
    agent_scope: dict | None = None
    approval_cache_ttl: int | None = None
    enabled: bool | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., description="approved or rejected")
    reason: str | None = None
    content: dict | None = Field(default=None, description="Structured content for elicitation responses")


# ---------------------------------------------------------------------------
# Approval Policy CRUD
# ---------------------------------------------------------------------------
@router.post(
    "/approval-policies",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scopes("security:write"))],
)
def create_approval_policy(
    request: ApprovalPolicyCreateRequest,
    db: Session = Depends(get_db),
    user: UserInfo = Depends(get_current_user),
):
    valid_types = ("loop_hook", "tool_context", "mcp_elicitation")
    if request.policy_type not in valid_types:
        raise HTTPException(400, f"policy_type must be one of {valid_types}")
    valid_modes = ("require_approval", "notify_only")
    if request.approval_mode not in valid_modes:
        raise HTTPException(400, f"approval_mode must be one of {valid_modes}")

    existing = db.query(ApprovalPolicy).filter(ApprovalPolicy.name == request.name).first()
    if existing:
        raise HTTPException(409, f"Approval policy '{request.name}' already exists")

    policy = ApprovalPolicy(
        name=request.name,
        policy_type=request.policy_type,
        tool_match_rules=json.dumps(request.tool_match_rules),
        approval_mode=request.approval_mode,
        timeout_seconds=request.timeout_seconds,
        agent_scope=json.dumps(request.agent_scope),
        approval_cache_ttl=request.approval_cache_ttl,
        enabled=request.enabled,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy.to_dict()


@router.get(
    "/approval-policies",
    dependencies=[Depends(require_scopes("security:read"))],
)
def list_approval_policies(db: Session = Depends(get_db)):
    policies = db.query(ApprovalPolicy).order_by(ApprovalPolicy.name).all()
    return [p.to_dict() for p in policies]


@router.get(
    "/approval-policies/{policy_id}",
    dependencies=[Depends(require_scopes("security:read"))],
)
def get_approval_policy(policy_id: int, db: Session = Depends(get_db)):
    policy = db.query(ApprovalPolicy).filter(ApprovalPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(404, "Approval policy not found")
    return policy.to_dict()


@router.put(
    "/approval-policies/{policy_id}",
    dependencies=[Depends(require_scopes("security:write"))],
)
def update_approval_policy(
    policy_id: int,
    request: ApprovalPolicyUpdateRequest,
    db: Session = Depends(get_db),
):
    policy = db.query(ApprovalPolicy).filter(ApprovalPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(404, "Approval policy not found")

    if request.name is not None:
        policy.name = request.name
    if request.policy_type is not None:
        valid_types = ("loop_hook", "tool_context", "mcp_elicitation")
        if request.policy_type not in valid_types:
            raise HTTPException(400, f"policy_type must be one of {valid_types}")
        policy.policy_type = request.policy_type
    if request.tool_match_rules is not None:
        policy.tool_match_rules = json.dumps(request.tool_match_rules)
    if request.approval_mode is not None:
        policy.approval_mode = request.approval_mode
    if request.timeout_seconds is not None:
        policy.timeout_seconds = request.timeout_seconds
    if request.agent_scope is not None:
        policy.agent_scope = json.dumps(request.agent_scope)
    if request.approval_cache_ttl is not None:
        policy.approval_cache_ttl = request.approval_cache_ttl
    if request.enabled is not None:
        policy.enabled = request.enabled

    db.commit()
    db.refresh(policy)
    return policy.to_dict()


@router.delete(
    "/approval-policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_scopes("security:write"))],
)
def delete_approval_policy(policy_id: int, db: Session = Depends(get_db)):
    policy = db.query(ApprovalPolicy).filter(ApprovalPolicy.id == policy_id).first()
    if not policy:
        raise HTTPException(404, "Approval policy not found")
    db.delete(policy)
    db.commit()


# ---------------------------------------------------------------------------
# Approval Decision Endpoint (used by frontend during streaming)
# ---------------------------------------------------------------------------
@router.post(
    "/approvals/{request_id}/decide",
    dependencies=[Depends(require_scopes("invoke"))],
)
async def decide_approval(
    request_id: str,
    body: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    user: UserInfo = Depends(get_current_user),
):
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be 'approved' or 'rejected'")

    # Retry briefly if the approval request hasn't been registered yet (race condition)
    found = resolve_approval(
        request_id,
        decision=body.decision,
        decided_by=user.sub,
        reason=body.reason,
        content=body.content,
    )
    if not found:
        for _ in range(10):
            await asyncio.sleep(0.5)
            found = resolve_approval(
                request_id,
                decision=body.decision,
                decided_by=user.sub,
                reason=body.reason,
                content=body.content,
            )
            if found:
                break
    if not found:
        raise HTTPException(404, "Approval request not found or already resolved")

    log_entry = db.query(ApprovalLog).filter(ApprovalLog.request_id == request_id).first()
    if log_entry:
        log_entry.status = body.decision
        log_entry.decided_at = datetime.now(timezone.utc)
        log_entry.decided_by = user.sub
        log_entry.reason = body.reason
        db.commit()

    return {"request_id": request_id, "status": body.decision}


# ---------------------------------------------------------------------------
# Approval Log Query
# ---------------------------------------------------------------------------
@router.get(
    "/approvals/logs",
    dependencies=[Depends(require_scopes("agent:read"))],
)
def list_approval_logs(
    agent_id: int | None = Query(None),
    session_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    query = db.query(ApprovalLog).order_by(ApprovalLog.requested_at.desc())
    if agent_id is not None:
        query = query.filter(ApprovalLog.agent_id == agent_id)
    if session_id is not None:
        query = query.filter(ApprovalLog.session_id == session_id)
    if status_filter is not None:
        query = query.filter(ApprovalLog.status == status_filter)
    logs = query.limit(500).all()
    return [log.to_dict() for log in logs]
