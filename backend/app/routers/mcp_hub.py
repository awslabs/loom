"""MCP Hub BFF endpoints (ADR 0007 / specs 016-019)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.services import mcp_hub as hub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/hub", tags=["mcp-hub"])


class MintRequest(BaseModel):
    client_label: str | None = Field(None, max_length=64)


class IntrospectRequest(BaseModel):
    hub_session_token: str


class HubToolCallRequest(BaseModel):
    hub_session_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


def _require_service_token(authorization: str | None) -> None:
    expected = hub.hub_service_token()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="hub_service_token_unset")
    if not authorization or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def mint_hub_session(
    body: MintRequest | None = None,
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> dict:
    label = body.client_label if body else None
    return hub.mint_session(db, user, client_label=label)


@router.post("/sessions/introspect")
def introspect_hub_session(
    body: IntrospectRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _require_service_token(authorization)
    return hub.introspect_token(db, body.hub_session_token)


@router.delete("/sessions/{hub_session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_hub_session(
    hub_session_id: str,
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> None:
    if not hub.revoke_session(db, hub_session_id, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")


@router.get("/allowlist")
def get_hub_allowlist(
    authorization: str | None = Header(default=None),
    x_loom_hub_session_id: str | None = Header(default=None, alias="X-Loom-Hub-Session-Id"),
    db: Session = Depends(get_db),
) -> dict:
    _require_service_token(authorization)
    if not x_loom_hub_session_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing_hub_session_id")
    user = hub.user_from_hub_session(db, x_loom_hub_session_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_inactive")
    payload = hub.build_allowlist(db, user)
    payload["hub_session_id"] = x_loom_hub_session_id
    return payload


@router.post("/tools/call")
def hub_tools_call(
    body: HubToolCallRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _require_service_token(authorization)
    user = hub.user_from_hub_session(db, body.hub_session_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_inactive")
    result = hub.call_hub_tool(db, user, body.tool_name, body.arguments or {})
    if result.get("denied"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result.get("error") or "denied")
    return result
