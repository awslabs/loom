"""Admin dashboard endpoints for audit logging and usage analytics."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, get_current_user, require_scopes
from app.models.audit import AuditLogin, AuditAction, AuditPageView

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Pydantic request/response schemas
# ---------------------------------------------------------------------------
class AuditLoginRequest(BaseModel):
    user_id: str
    browser_session_id: str
    logged_in_at: Optional[str] = None


class AuditLoginResponse(BaseModel):
    id: int
    user_id: str
    browser_session_id: str
    logged_in_at: str


class AuditActionRequest(BaseModel):
    user_id: str
    browser_session_id: str
    action_category: str
    action_type: str
    resource_name: Optional[str] = None
    performed_at: Optional[str] = None


class AuditActionResponse(BaseModel):
    id: int
    user_id: str
    browser_session_id: str
    action_category: str
    action_type: str
    resource_name: Optional[str]
    performed_at: str


class AuditPageViewRequest(BaseModel):
    user_id: str
    browser_session_id: str
    page_name: str
    entered_at: str
    duration_seconds: Optional[int] = None


class AuditPageViewResponse(BaseModel):
    id: int
    user_id: str
    browser_session_id: str
    page_name: str
    entered_at: str
    duration_seconds: Optional[int]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dt_to_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.isoformat() + "Z" if not dt.isoformat().endswith("Z") else dt.isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Audit Login endpoints
# ---------------------------------------------------------------------------
@router.post("/audit/login", status_code=201)
def create_audit_login(
    request: AuditLoginRequest,
    user: UserInfo = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Record a user login event."""
    login = AuditLogin(
        user_id=request.user_id,
        browser_session_id=request.browser_session_id,
    )
    if request.logged_in_at:
        login.logged_in_at = _parse_dt(request.logged_in_at)
    db.add(login)
    db.commit()
    db.refresh(login)
    return {
        "id": login.id,
        "user_id": login.user_id,
        "browser_session_id": login.browser_session_id,
        "logged_in_at": _dt_to_iso(login.logged_in_at),
    }


@router.get("/audit/logins")
def list_audit_logins(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    user: UserInfo = Depends(require_scopes("admin:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List audit login records with optional date filtering."""
    query = db.query(AuditLogin)
    if start:
        query = query.filter(AuditLogin.logged_in_at >= _parse_dt(start))
    if end:
        query = query.filter(AuditLogin.logged_in_at <= _parse_dt(end))
    logins = query.order_by(AuditLogin.id.desc()).all()
    return [
        {
            "id": l.id,
            "user_id": l.user_id,
            "browser_session_id": l.browser_session_id,
            "logged_in_at": _dt_to_iso(l.logged_in_at),
        }
        for l in logins
    ]


# ---------------------------------------------------------------------------
# Audit Action endpoints
# ---------------------------------------------------------------------------
@router.post("/audit/action", status_code=201)
def create_audit_action(
    request: AuditActionRequest,
    user: UserInfo = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Record a user action event."""
    action = AuditAction(
        user_id=request.user_id,
        browser_session_id=request.browser_session_id,
        action_category=request.action_category,
        action_type=request.action_type,
        resource_name=request.resource_name,
    )
    if request.performed_at:
        action.performed_at = _parse_dt(request.performed_at)
    db.add(action)
    db.commit()
    db.refresh(action)
    return {
        "id": action.id,
        "user_id": action.user_id,
        "browser_session_id": action.browser_session_id,
        "action_category": action.action_category,
        "action_type": action.action_type,
        "resource_name": action.resource_name,
        "performed_at": _dt_to_iso(action.performed_at),
    }


@router.get("/audit/actions")
def list_audit_actions(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    user: UserInfo = Depends(require_scopes("admin:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List audit action records with optional date filtering."""
    query = db.query(AuditAction)
    if start:
        query = query.filter(AuditAction.performed_at >= _parse_dt(start))
    if end:
        query = query.filter(AuditAction.performed_at <= _parse_dt(end))
    actions = query.order_by(AuditAction.id.desc()).all()
    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "browser_session_id": a.browser_session_id,
            "action_category": a.action_category,
            "action_type": a.action_type,
            "resource_name": a.resource_name,
            "performed_at": _dt_to_iso(a.performed_at),
        }
        for a in actions
    ]


# ---------------------------------------------------------------------------
# Audit Page View endpoints
# ---------------------------------------------------------------------------
@router.post("/audit/pageview", status_code=201)
def create_audit_pageview(
    request: AuditPageViewRequest,
    user: UserInfo = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Record a page view event."""
    pv = AuditPageView(
        user_id=request.user_id,
        browser_session_id=request.browser_session_id,
        page_name=request.page_name,
        entered_at=_parse_dt(request.entered_at),
        duration_seconds=request.duration_seconds,
    )
    db.add(pv)
    db.commit()
    db.refresh(pv)
    return {
        "id": pv.id,
        "user_id": pv.user_id,
        "browser_session_id": pv.browser_session_id,
        "page_name": pv.page_name,
        "entered_at": _dt_to_iso(pv.entered_at),
        "duration_seconds": pv.duration_seconds,
    }


@router.get("/audit/pageviews")
def list_audit_pageviews(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    user: UserInfo = Depends(require_scopes("admin:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List audit page view records with optional date filtering."""
    query = db.query(AuditPageView)
    if start:
        query = query.filter(AuditPageView.entered_at >= _parse_dt(start))
    if end:
        query = query.filter(AuditPageView.entered_at <= _parse_dt(end))
    views = query.order_by(AuditPageView.id.desc()).all()
    return [
        {
            "id": v.id,
            "user_id": v.user_id,
            "browser_session_id": v.browser_session_id,
            "page_name": v.page_name,
            "entered_at": _dt_to_iso(v.entered_at),
            "duration_seconds": v.duration_seconds,
        }
        for v in views
    ]


# ---------------------------------------------------------------------------
# Sessions endpoint
# ---------------------------------------------------------------------------
@router.get("/audit/sessions")
def list_audit_sessions(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    user: UserInfo = Depends(require_scopes("admin:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List browser sessions with aggregated activity counts."""
    # Base login query
    login_q = db.query(
        AuditLogin.browser_session_id,
        AuditLogin.user_id,
        func.min(AuditLogin.logged_in_at).label("first_login"),
    )
    if start:
        login_q = login_q.filter(AuditLogin.logged_in_at >= _parse_dt(start))
    if end:
        login_q = login_q.filter(AuditLogin.logged_in_at <= _parse_dt(end))
    login_q = login_q.group_by(AuditLogin.browser_session_id, AuditLogin.user_id)
    sessions = login_q.all()

    results = []
    for session_row in sessions:
        bsid = session_row.browser_session_id
        uid = session_row.user_id

        action_count = db.query(func.count(AuditAction.id)).filter(
            AuditAction.browser_session_id == bsid
        ).scalar() or 0

        pv_count = db.query(func.count(AuditPageView.id)).filter(
            AuditPageView.browser_session_id == bsid
        ).scalar() or 0

        # Compute last activity
        last_action = db.query(func.max(AuditAction.performed_at)).filter(
            AuditAction.browser_session_id == bsid
        ).scalar()
        last_pv = db.query(func.max(AuditPageView.entered_at)).filter(
            AuditPageView.browser_session_id == bsid
        ).scalar()

        last_activity = session_row.first_login
        if last_action and (last_activity is None or last_action > last_activity):
            last_activity = last_action
        if last_pv and (last_activity is None or last_pv > last_activity):
            last_activity = last_pv

        results.append({
            "browser_session_id": bsid,
            "user_id": uid,
            "logged_in_at": _dt_to_iso(session_row.first_login),
            "last_activity_at": _dt_to_iso(last_activity),
            "action_count": action_count,
            "page_view_count": pv_count,
        })

    return results


# ---------------------------------------------------------------------------
# Session timeline endpoint
# ---------------------------------------------------------------------------
@router.get("/audit/sessions/{browser_session_id}/timeline")
def get_session_timeline(
    browser_session_id: str,
    user: UserInfo = Depends(require_scopes("admin:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Get a chronological timeline of events for a browser session."""
    timeline: list[dict] = []

    logins = db.query(AuditLogin).filter(
        AuditLogin.browser_session_id == browser_session_id
    ).all()
    for l in logins:
        timeline.append({
            "type": "login",
            "timestamp": _dt_to_iso(l.logged_in_at),
            "user_id": l.user_id,
            "detail": {},
        })

    actions = db.query(AuditAction).filter(
        AuditAction.browser_session_id == browser_session_id
    ).all()
    for a in actions:
        timeline.append({
            "type": "action",
            "timestamp": _dt_to_iso(a.performed_at),
            "user_id": a.user_id,
            "detail": {
                "action_category": a.action_category,
                "action_type": a.action_type,
                "resource_name": a.resource_name,
            },
        })

    page_views = db.query(AuditPageView).filter(
        AuditPageView.browser_session_id == browser_session_id
    ).all()
    for v in page_views:
        timeline.append({
            "type": "page_view",
            "timestamp": _dt_to_iso(v.entered_at),
            "user_id": v.user_id,
            "detail": {
                "page_name": v.page_name,
                "duration_seconds": v.duration_seconds,
            },
        })

    timeline.sort(key=lambda e: e["timestamp"])
    return timeline


# ---------------------------------------------------------------------------
# Summary endpoint
# ---------------------------------------------------------------------------
@router.get("/audit/summary")
def get_audit_summary(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    user: UserInfo = Depends(require_scopes("admin:read")),
    db: Session = Depends(get_db),
) -> dict:
    """Get aggregated audit summary statistics."""
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)

    # Total logins
    login_q = db.query(AuditLogin)
    if start_dt:
        login_q = login_q.filter(AuditLogin.logged_in_at >= start_dt)
    if end_dt:
        login_q = login_q.filter(AuditLogin.logged_in_at <= end_dt)
    total_logins = login_q.count()

    # Active users (distinct user_ids across logins)
    active_users = db.query(func.count(func.distinct(AuditLogin.user_id)))
    if start_dt:
        active_users = active_users.filter(AuditLogin.logged_in_at >= start_dt)
    if end_dt:
        active_users = active_users.filter(AuditLogin.logged_in_at <= end_dt)
    active_users = active_users.scalar() or 0

    # Total actions
    action_q = db.query(AuditAction)
    if start_dt:
        action_q = action_q.filter(AuditAction.performed_at >= start_dt)
    if end_dt:
        action_q = action_q.filter(AuditAction.performed_at <= end_dt)
    total_actions = action_q.count()

    # Actions by category
    cat_q = db.query(
        AuditAction.action_category,
        func.count(AuditAction.id).label("count"),
    )
    if start_dt:
        cat_q = cat_q.filter(AuditAction.performed_at >= start_dt)
    if end_dt:
        cat_q = cat_q.filter(AuditAction.performed_at <= end_dt)
    cat_q = cat_q.group_by(AuditAction.action_category)
    actions_by_category = {row.action_category: row.count for row in cat_q.all()}

    # Page views by page
    pv_q = db.query(
        AuditPageView.page_name,
        func.count(AuditPageView.id).label("count"),
        func.coalesce(func.sum(AuditPageView.duration_seconds), 0).label("total_duration"),
    )
    if start_dt:
        pv_q = pv_q.filter(AuditPageView.entered_at >= start_dt)
    if end_dt:
        pv_q = pv_q.filter(AuditPageView.entered_at <= end_dt)
    pv_q = pv_q.group_by(AuditPageView.page_name)
    pv_rows = pv_q.all()
    page_views_by_page = {
        row.page_name: {"count": row.count, "total_duration_seconds": row.total_duration}
        for row in pv_rows
    }

    # Total page views and total duration
    total_pv_q = db.query(
        func.count(AuditPageView.id).label("total_page_views"),
        func.coalesce(func.sum(AuditPageView.duration_seconds), 0).label("total_duration"),
    )
    if start_dt:
        total_pv_q = total_pv_q.filter(AuditPageView.entered_at >= start_dt)
    if end_dt:
        total_pv_q = total_pv_q.filter(AuditPageView.entered_at <= end_dt)
    total_pv_row = total_pv_q.one()
    total_page_views = total_pv_row.total_page_views or 0
    total_duration = int(total_pv_row.total_duration or 0)

    # Logins by day
    logins_by_day_q = db.query(
        func.date(AuditLogin.logged_in_at).label("day"),
        func.count(AuditLogin.id).label("count"),
    )
    if start_dt:
        logins_by_day_q = logins_by_day_q.filter(AuditLogin.logged_in_at >= start_dt)
    if end_dt:
        logins_by_day_q = logins_by_day_q.filter(AuditLogin.logged_in_at <= end_dt)
    logins_by_day_q = logins_by_day_q.group_by(func.date(AuditLogin.logged_in_at)).order_by("day")
    logins_by_day = [{"date": str(row.day), "count": row.count} for row in logins_by_day_q.all()]

    # Actions by day
    actions_by_day_q = db.query(
        func.date(AuditAction.performed_at).label("day"),
        func.count(AuditAction.id).label("count"),
    )
    if start_dt:
        actions_by_day_q = actions_by_day_q.filter(AuditAction.performed_at >= start_dt)
    if end_dt:
        actions_by_day_q = actions_by_day_q.filter(AuditAction.performed_at <= end_dt)
    actions_by_day_q = actions_by_day_q.group_by(func.date(AuditAction.performed_at)).order_by("day")
    actions_by_day = [{"date": str(row.day), "count": row.count} for row in actions_by_day_q.all()]

    return {
        "total_logins": total_logins,
        "active_users": active_users,
        "total_duration": total_duration,
        "total_actions": total_actions,
        "total_page_views": total_page_views,
        "actions_by_category": actions_by_category,
        "page_views_by_page": page_views_by_page,
        "logins_by_day": logins_by_day,
        "actions_by_day": actions_by_day,
    }
