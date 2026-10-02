"""Usage limit CRUD for controlling per-user/group token and cost limits."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import get_current_user, require_scopes
from app.models.usage_limit import UsageLimit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["usage-limits"])

VALID_MEASURES = ("tokens", "budget")
VALID_WINDOWS = ("daily", "weekly", "monthly", "rolling")
VALID_ENFORCEMENTS = ("warn", "throttle", "block")
VALID_SCOPE_TYPES = ("user", "group")
VALID_TARGET_TYPES = ("all", "model", "family")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class UsageLimitCreateRequest(BaseModel):
    name: str
    scope: dict = Field(..., description='{"type": "user", "username": ...} or {"type": "group", "group": ...}')
    target: dict = Field(default_factory=lambda: {"type": "all"})
    measure: str = Field(..., description="tokens or budget")
    threshold: float
    window: str = Field(default="daily", description="daily, weekly, monthly, or rolling")
    enforcement: str = Field(default="warn", description="warn, throttle, or block")
    enabled: bool = Field(default=True)


class UsageLimitUpdateRequest(BaseModel):
    name: str | None = None
    scope: dict | None = None
    target: dict | None = None
    measure: str | None = None
    threshold: float | None = None
    window: str | None = None
    enforcement: str | None = None
    enabled: bool | None = None


# A malformed scope/target is worse here than in approval_policy's agent_scope:
# there it just means "matches nothing", here it risks a limit silently
# applying to everyone (or no one) depending on how enforcement reads a missing
# key. So unlike approvals.py, we actually validate what's inside the JSON blob,
# not just that it's valid JSON.
def _validate_scope(scope: dict) -> None:
    scope_type = scope.get("type")
    if scope_type not in VALID_SCOPE_TYPES:
        raise HTTPException(400, f"scope.type must be one of {VALID_SCOPE_TYPES}")
    if scope_type == "user" and not scope.get("username"):
        raise HTTPException(400, "scope.username is required when scope.type is 'user'")
    if scope_type == "group" and not scope.get("group"):
        raise HTTPException(400, "scope.group is required when scope.type is 'group'")


def _validate_target(target: dict) -> None:
    target_type = target.get("type")
    if target_type not in VALID_TARGET_TYPES:
        raise HTTPException(400, f"target.type must be one of {VALID_TARGET_TYPES}")
    if target_type == "model" and not target.get("model_id"):
        raise HTTPException(400, "target.model_id is required when target.type is 'model'")
    if target_type == "family" and not target.get("family"):
        raise HTTPException(400, "target.family is required when target.type is 'family'")


# ---------------------------------------------------------------------------
# Usage Limit CRUD
# ---------------------------------------------------------------------------
@router.post(
    "/usage-limits",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scopes("security:write"))],
)
def create_usage_limit(
    request: UsageLimitCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # Field-level validation first (cheap, no DB hit), then the name-uniqueness
    # check, which does need a query.
    if request.measure not in VALID_MEASURES:
        raise HTTPException(400, f"measure must be one of {VALID_MEASURES}")
    if request.window not in VALID_WINDOWS:
        raise HTTPException(400, f"window must be one of {VALID_WINDOWS}")
    if request.enforcement not in VALID_ENFORCEMENTS:
        raise HTTPException(400, f"enforcement must be one of {VALID_ENFORCEMENTS}")
    _validate_scope(request.scope)
    _validate_target(request.target)

    existing = db.query(UsageLimit).filter(UsageLimit.name == request.name).first()
    if existing:
        raise HTTPException(409, f"Usage limit '{request.name}' already exists")

    # dicts get serialized to JSON text here; get_scope()/get_target() on the
    # model undo this on the way back out.
    limit = UsageLimit(
        name=request.name,
        scope=json.dumps(request.scope),
        target=json.dumps(request.target),
        measure=request.measure,
        threshold=request.threshold,
        window=request.window,
        enforcement=request.enforcement,
        enabled=request.enabled,
    )
    db.add(limit)
    db.commit()
    db.refresh(limit)
    return limit.to_dict()


@router.get(
    "/usage-limits",
    dependencies=[Depends(require_scopes("security:read"))],
)
def list_usage_limits(db: Session = Depends(get_db)):
    limits = db.query(UsageLimit).order_by(UsageLimit.name).all()
    return [l.to_dict() for l in limits]


@router.get(
    "/usage-limits/{limit_id}",
    dependencies=[Depends(require_scopes("security:read"))],
)
def get_usage_limit(limit_id: int, db: Session = Depends(get_db)):
    limit = db.query(UsageLimit).filter(UsageLimit.id == limit_id).first()
    if not limit:
        raise HTTPException(404, "Usage limit not found")
    return limit.to_dict()


@router.put(
    "/usage-limits/{limit_id}",
    dependencies=[Depends(require_scopes("security:write"))],
)
def update_usage_limit(
    limit_id: int,
    request: UsageLimitUpdateRequest,
    db: Session = Depends(get_db),
):
    limit = db.query(UsageLimit).filter(UsageLimit.id == limit_id).first()
    if not limit:
        raise HTTPException(404, "Usage limit not found")

    # PATCH-style partial update — only touch a field if the caller actually
    # sent one. None means "leave this alone", not "clear it".
    if request.name is not None:
        limit.name = request.name
    if request.scope is not None:
        _validate_scope(request.scope)
        limit.scope = json.dumps(request.scope)
    if request.target is not None:
        _validate_target(request.target)
        limit.target = json.dumps(request.target)
    if request.measure is not None:
        if request.measure not in VALID_MEASURES:
            raise HTTPException(400, f"measure must be one of {VALID_MEASURES}")
        limit.measure = request.measure
    if request.threshold is not None:
        limit.threshold = request.threshold
    if request.window is not None:
        if request.window not in VALID_WINDOWS:
            raise HTTPException(400, f"window must be one of {VALID_WINDOWS}")
        limit.window = request.window
    if request.enforcement is not None:
        if request.enforcement not in VALID_ENFORCEMENTS:
            raise HTTPException(400, f"enforcement must be one of {VALID_ENFORCEMENTS}")
        limit.enforcement = request.enforcement
    if request.enabled is not None:
        limit.enabled = request.enabled

    db.commit()
    db.refresh(limit)
    return limit.to_dict()


@router.delete(
    "/usage-limits/{limit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_scopes("security:write"))],
)
def delete_usage_limit(limit_id: int, db: Session = Depends(get_db)):
    limit = db.query(UsageLimit).filter(UsageLimit.id == limit_id).first()
    if not limit:
        raise HTTPException(404, "Usage limit not found")
    db.delete(limit)
    db.commit()
