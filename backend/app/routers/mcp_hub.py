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
from app.services import mcp_hub_agents as hub_agents
from app.services import mcp_hub_proxy as hub_proxy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/hub", tags=["mcp-hub"])
ext_router = APIRouter(prefix="/api/ext/local-runtime", tags=["local-runtime-ext"])


class HubToolCallRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    groups: list[str] = Field(default_factory=list)
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    server_id: int | None = None
    original_tool_name: str | None = None


class MaterializeRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    groups: list[str] = Field(default_factory=list)
    connection_id: str | None = None
    mcp_client_slug: str
    client_status: str = "discovered"
    grants: list[dict[str, Any]] = Field(default_factory=list)


class ClientPatchRequest(BaseModel):
    status: str | None = None
    display_name: str | None = None
    allowed_groups: list[str] | None = None
    agents_enabled: bool | None = None


class MaterializeAgentsRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    groups: list[str] = Field(default_factory=list)
    contract_version: str | None = None


class HubAgentInvokeRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    groups: list[str] = Field(default_factory=list)
    agent_id: int
    prompt: str = Field(..., min_length=1)
    session_id: str | None = None
    mode: str = Field(default="async")
    timeout_s: int = Field(default=120, ge=5, le=600)
    # Hub profile allowlist ∩ agent MCP links (optional; omit = all linked MCPs)
    hub_server_ids: list[int] | None = None
    hub_tool_allowlists: dict[str, list[str]] | None = None


class HubAgentRunQuery(BaseModel):
    subject: str = Field(..., min_length=1)
    groups: list[str] = Field(default_factory=list)


class ClientGrantsRequest(BaseModel):
    group: str = Field(..., min_length=1, max_length=128)
    grants: list[dict[str, Any]] = Field(default_factory=list)


def _require_service_token(authorization: str | None) -> None:
    expected = hub.hub_service_token()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="hub_service_token_unset")
    if not authorization or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def _user_from_hub_claims(subject: str, groups: list[str]) -> UserInfo:
    from app.dependencies.auth import derive_scopes

    return UserInfo(
        sub=subject,
        username=subject,
        groups=list(groups or []),
        scopes=derive_scopes(list(groups or [])),
        idp_type="keycloak",
    )


@router.get("/info")
def hub_public_info() -> dict:
    """Public Hub resource URL for IDE OAuth (no mint)."""
    return {
        "mcp_hub_url": hub.hub_public_url(),
        "resource": hub.hub_public_url(),
        "auth": "oauth",
        "contract_version": hub.CONTRACT_VERSION,
    }


@router.post("/sessions", status_code=status.HTTP_410_GONE)
def mint_hub_session_removed() -> dict:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="hub_mint_removed_use_oauth",
    )


@router.post("/sessions/introspect", status_code=status.HTTP_410_GONE)
def introspect_hub_session_removed() -> dict:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="hub_mint_removed_use_oauth",
    )


@router.delete("/sessions/{hub_session_id}", status_code=status.HTTP_410_GONE)
def revoke_hub_session_removed(hub_session_id: str) -> None:
    _ = hub_session_id
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="hub_mint_removed_use_oauth",
    )


@router.post("/materialize-allowlist")
def materialize_hub_allowlist(
    body: MaterializeRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _require_service_token(authorization)
    user = _user_from_hub_claims(body.subject, body.groups)
    return hub.materialize_from_grants(
        db,
        user,
        hub_session_id=body.connection_id or f"oauth:{body.subject}",
        mcp_client_slug=body.mcp_client_slug,
        client_status=body.client_status,
        allowed_groups=[],
        grants=body.grants,
    )


@router.post("/tools/call")
def hub_tools_call(
    body: HubToolCallRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _require_service_token(authorization)
    user = _user_from_hub_claims(body.subject, body.groups)
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


@router.post("/materialize-agents")
def materialize_hub_agents(
    body: MaterializeAgentsRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _require_service_token(authorization)
    user = _user_from_hub_claims(body.subject, body.groups)
    return hub_agents.materialize_agents(db, user)


@router.post("/agents/invoke")
async def hub_agents_invoke(
    body: HubAgentInvokeRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _require_service_token(authorization)
    user = _user_from_hub_claims(body.subject, body.groups)
    mode = body.mode if body.mode in ("async", "sync") else "async"
    result = await hub_agents.start_agent_run(
        db,
        user,
        agent_id=body.agent_id,
        prompt=body.prompt,
        session_id=body.session_id,
        mode=mode,
        timeout_s=body.timeout_s,
        hub_server_ids=body.hub_server_ids,
        hub_tool_allowlists=(
            {int(k): list(v) for k, v in body.hub_tool_allowlists.items()}
            if body.hub_tool_allowlists
            else None
        ),
    )
    if result.get("denied"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result.get("error") or "denied")
    if result.get("error") == "agent_not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent_not_found")
    if result.get("error"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error"))
    return result


@router.post("/agents/runs/{session_id}")
def hub_agents_run_status(
    session_id: str,
    body: HubAgentRunQuery,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """POST with claims (Hub cannot easily put subject on GET via urllib helpers)."""
    _require_service_token(authorization)
    user = _user_from_hub_claims(body.subject, body.groups)
    result = hub_agents.get_run(db, user, session_id)
    if result.get("denied"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result.get("error") or "denied")
    if result.get("error") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
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


@ext_router.get("/mcp-clients/{slug}/profile-grants")
def get_mcp_client_profile_grants(
    slug: str,
    group: str = Query(..., min_length=1, max_length=128),
    user: UserInfo = Depends(require_scopes("mcp:read")),
) -> dict:
    """On-demand grants for one IdP profile. Empty profile → 200 + grants=[]."""
    _ = user
    code, payload = hub_proxy.get_profile_grants(slug, group)
    if code >= 400:
        raise HTTPException(status_code=code, detail=payload.get("error") or payload.get("detail") or "hub_error")
    return payload


@ext_router.put("/mcp-clients/{slug}/profile-grants")
def put_mcp_client_grants(
    slug: str,
    body: ClientGrantsRequest,
    user: UserInfo = Depends(require_scopes("mcp:write")),
) -> dict:
    _ = user
    code, payload = hub_proxy.put_grants(slug, body.grants, group=body.group)
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
