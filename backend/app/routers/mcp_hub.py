"""MCP Hub BFF endpoints (ADR 0007 / 0008 / specs 016-022)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.services import mcp_hub as hub
from app.services import mcp_hub_proxy as hub_proxy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/hub", tags=["mcp-hub"])
ext_router = APIRouter(prefix="/api/ext/local-runtime", tags=["local-runtime-ext"])


class MintRequest(BaseModel):
    client_label: str | None = Field(None, max_length=64)


class IntrospectRequest(BaseModel):
    hub_session_token: str


class HubToolCallRequest(BaseModel):
    hub_session_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    server_id: int | None = None
    original_tool_name: str | None = None


class MaterializeRequest(BaseModel):
    hub_session_id: str
    mcp_client_slug: str
    client_status: str = "discovered"
    allowed_groups: list[str] = Field(default_factory=list)
    grants: list[dict[str, Any]] = Field(default_factory=list)


class ClientPatchRequest(BaseModel):
    status: str | None = None
    display_name: str | None = None
    allowed_groups: list[str] | None = None


class ClientGrantsRequest(BaseModel):
    grants: list[dict[str, Any]]


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
    """Interim union allowlist. Hub MCP path uses materialize-allowlist instead."""
    _require_service_token(authorization)
    if not x_loom_hub_session_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing_hub_session_id")
    user = hub.user_from_hub_session(db, x_loom_hub_session_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_inactive")
    payload = hub.build_allowlist(db, user)
    payload["hub_session_id"] = x_loom_hub_session_id
    return payload


@router.post("/materialize-allowlist")
def materialize_hub_allowlist(
    body: MaterializeRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _require_service_token(authorization)
    user = hub.user_from_hub_session(db, body.hub_session_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_inactive")
    return hub.materialize_from_grants(
        db,
        user,
        hub_session_id=body.hub_session_id,
        mcp_client_slug=body.mcp_client_slug,
        client_status=body.client_status,
        allowed_groups=body.allowed_groups,
        grants=body.grants,
    )


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
    result = hub.call_hub_tool(
        db,
        user,
        body.tool_name,
        body.arguments or {},
        server_id=body.server_id,
        original_tool_name=body.original_tool_name,
    )
    if result.get("denied"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result.get("error") or "denied")
    return result


@ext_router.get("/mcp-clients")
def list_mcp_clients(
    status_filter: str | None = Query(default=None, alias="status"),
    user: UserInfo = Depends(require_scopes("mcp:read")),
) -> dict:
    _ = user
    code, payload = hub_proxy.list_clients(status_filter)
    if code >= 400:
        raise HTTPException(status_code=code, detail=payload.get("error") or payload.get("detail") or "hub_error")
    return payload


@ext_router.get("/mcp-clients/{slug}")
def get_mcp_client(
    slug: str,
    user: UserInfo = Depends(require_scopes("mcp:read")),
) -> dict:
    _ = user
    code, payload = hub_proxy.get_client(slug)
    if code >= 400:
        raise HTTPException(status_code=code, detail=payload.get("error") or payload.get("detail") or "hub_error")
    return payload


@ext_router.patch("/mcp-clients/{slug}")
def patch_mcp_client(
    slug: str,
    body: ClientPatchRequest,
    user: UserInfo = Depends(require_scopes("mcp:write")),
) -> dict:
    _ = user
    code, payload = hub_proxy.patch_client(slug, body.model_dump(exclude_none=True))
    if code >= 400:
        raise HTTPException(status_code=code, detail=payload.get("error") or payload.get("detail") or "hub_error")
    return payload


@ext_router.put("/mcp-clients/{slug}/grants")
def put_mcp_client_grants(
    slug: str,
    body: ClientGrantsRequest,
    user: UserInfo = Depends(require_scopes("mcp:write")),
) -> dict:
    _ = user
    code, payload = hub_proxy.put_grants(slug, body.grants)
    if code >= 400:
        raise HTTPException(status_code=code, detail=payload.get("error") or payload.get("detail") or "hub_error")
    return payload


@ext_router.delete("/mcp-clients/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mcp_client(
    slug: str,
    user: UserInfo = Depends(require_scopes("mcp:write")),
) -> None:
    _ = user
    code, payload = hub_proxy.delete_client(slug)
    if code == 204:
        return
    raise HTTPException(status_code=code if code >= 400 else 502, detail=payload.get("error") or "hub_error")
