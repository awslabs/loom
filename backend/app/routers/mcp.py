"""MCP server management endpoints."""
import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from sqlalchemy import or_

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.mcp import McpServer, McpTool, McpServerAccess
from app.services.mcp import test_mcp_connection as svc_test_connection
from app.services.mcp import fetch_mcp_tools as svc_fetch_tools
from app.services.mcp import invoke_mcp_tool as svc_invoke_tool
from app.services.mcp import resolve_api_key
from app.services.secrets import store_secret, delete_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/servers", tags=["mcp"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class McpServerCreateRequest(BaseModel):
    name: str = Field(..., description="Server display name")
    description: str | None = Field(None, description="Server description")
    endpoint_url: str = Field(..., description="MCP server endpoint URL")
    transport_type: str = Field(..., description="Transport type: 'sse' or 'streamable_http'")
    auth_type: str = Field(default="none", description="Auth type: 'none' or 'oauth2'")
    oauth2_well_known_url: str | None = Field(None, description="OAuth2 well-known URL")
    oauth2_client_id: str | None = Field(None, description="OAuth2 client ID")
    oauth2_client_secret: str | None = Field(None, description="OAuth2 client secret")
    oauth2_scopes: str | None = Field(None, description="OAuth2 scopes (space-separated)")
    delegation_mode: str = Field(default="m2m", description="OAuth2 delegation mode: 'm2m' or 'obo'")
    obo_grant_type: str | None = Field(None, description="OBO grant type: 'JWT_AUTHORIZATION_GRANT' (Entra ID) or 'TOKEN_EXCHANGE' (Okta)")
    oauth2_audience: str | None = Field(None, description="Token exchange audience (required for Okta custom auth servers)")
    api_key_header_name: str | None = Field(None, description="Header name for API key auth")
    api_key: str | None = Field(None, description="Admin API key (stored in Secrets Manager)")
    supports_elicitation: bool = Field(default=False, description="Whether this server supports MCP elicitation")
    runtime_endpoint_url: str | None = Field(None, description="Direct runtime URL for WebSocket elicitation (bypasses Gateway)")

    @model_validator(mode="after")
    def validate_auth_fields(self):
        if self.auth_type == "oauth2":
            if not self.oauth2_well_known_url:
                raise ValueError("oauth2_well_known_url is required when auth_type is 'oauth2'")  # nosec B105 — validation error message, not a password
            if not self.oauth2_client_id:
                raise ValueError("oauth2_client_id is required when auth_type is 'oauth2'")
        if self.auth_type == "api_key":
            if not self.api_key_header_name:
                raise ValueError("api_key_header_name is required when auth_type is 'api_key'")
        return self


class McpServerUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    endpoint_url: str | None = None
    transport_type: str | None = None
    status: str | None = None
    auth_type: str | None = None
    oauth2_well_known_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret: str | None = None
    oauth2_scopes: str | None = None
    delegation_mode: str | None = None
    obo_grant_type: str | None = None
    oauth2_audience: str | None = None
    api_key_header_name: str | None = None
    api_key: str | None = None
    supports_elicitation: bool | None = None
    runtime_endpoint_url: str | None = None


class McpServerResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    endpoint_url: str
    transport_type: str
    status: str
    auth_type: str
    oauth2_well_known_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_scopes: str | None = None
    delegation_mode: str = "m2m"
    obo_grant_type: str | None = None
    oauth2_audience: str | None = None
    has_oauth2_secret: bool = False
    api_key_header_name: str | None = None
    has_admin_api_key: bool = False
    supports_elicitation: bool = False
    runtime_endpoint_url: str | None = None
    registry_record_id: str | None = None
    registry_status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpToolResponse(BaseModel):
    id: int
    server_id: int
    tool_name: str
    description: str | None = None
    input_schema: dict | None = None
    last_refreshed_at: str | None = None


class ConnectorInfo(BaseModel):
    id: int
    name: str
    description: str | None = None
    auth_type: str
    has_user_api_key: bool = False
    supports_elicitation: bool = False


class McpAccessRuleResponse(BaseModel):
    id: int
    server_id: int
    persona_id: int
    access_level: str
    allowed_tool_names: list[str] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class McpAccessRuleInput(BaseModel):
    persona_id: int
    access_level: str
    allowed_tool_names: list[str] | None = None


class McpAccessUpdateRequest(BaseModel):
    rules: list[McpAccessRuleInput]


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


class ToolInvokeRequest(BaseModel):
    tool_name: str = Field(..., description="Name of the tool to invoke")
    arguments: dict = Field(default_factory=dict, description="Arguments to pass to the tool")


class ToolInvokeResponse(BaseModel):
    success: bool
    request: dict
    result: dict | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_server_or_404(server_id: int, db: Session) -> McpServer:
    server = db.query(McpServer).filter(McpServer.id == server_id).first()
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server with id {server_id} not found",
        )
    return server


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------
@router.post("", response_model=McpServerResponse, status_code=status.HTTP_201_CREATED)
def create_mcp_server(
    request: McpServerCreateRequest,
    user: UserInfo = Depends(require_scopes("mcp:write")),
    db: Session = Depends(get_db),
) -> McpServerResponse:
    server = McpServer(
        name=request.name,
        description=request.description,
        endpoint_url=request.endpoint_url,
        transport_type=request.transport_type,
        auth_type=request.auth_type,
        oauth2_well_known_url=request.oauth2_well_known_url,
        oauth2_client_id=request.oauth2_client_id,
        oauth2_client_secret=request.oauth2_client_secret,
        oauth2_scopes=request.oauth2_scopes,
        delegation_mode=request.delegation_mode or "m2m",
        obo_grant_type=request.obo_grant_type,
        oauth2_audience=request.oauth2_audience,
    )
    server.api_key_header_name = request.api_key_header_name
    server.supports_elicitation = "true" if request.supports_elicitation else "false"
    server.runtime_endpoint_url = request.runtime_endpoint_url
    if request.auth_type == "api_key" and request.api_key:
        region = os.getenv("AWS_REGION", "us-east-1")
        store_secret(f"loom/mcp/{request.name}/admin-api-key", request.api_key, region, description=f"Admin API key for MCP server {request.name}")
        server.has_admin_api_key = "true"
    db.add(server)
    db.commit()
    db.refresh(server)
    return McpServerResponse(**server.to_dict())


@router.get("", response_model=list[McpServerResponse])
def list_mcp_servers(
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> list[McpServerResponse]:
    query = db.query(McpServer)
    # t-user (without t-admin) can only see APPROVED or unregistered servers
    if "t-user" in user.groups and "t-admin" not in user.groups:
        query = query.filter(or_(McpServer.registry_status == "APPROVED", McpServer.registry_status.is_(None)))
    servers = query.order_by(McpServer.created_at.desc()).all()
    return [McpServerResponse(**s.to_dict()) for s in servers]


@router.get("/connectors", response_model=list[ConnectorInfo])
def list_connectors(
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> list[ConnectorInfo]:
    """List MCP servers available as connectors with per-user API key status."""
    query = db.query(McpServer)
    if "t-user" in user.groups and "t-admin" not in user.groups:
        query = query.filter(or_(McpServer.registry_status == "APPROVED", McpServer.registry_status.is_(None)))
    servers = query.order_by(McpServer.name.asc()).all()
    region = os.getenv("AWS_REGION", "us-east-1")
    from app.services.secrets import get_secret
    results: list[ConnectorInfo] = []
    for server in servers:
        has_key = False
        if server.auth_type == "api_key":
            try:
                get_secret(f"loom/mcp/{server.name}/api-key/{user.sub}", region)
                has_key = True
            except Exception:
                pass
        results.append(ConnectorInfo(
            id=server.id,
            name=server.name,
            description=server.description,
            auth_type=server.auth_type,
            has_user_api_key=has_key,
            supports_elicitation=server.supports_elicitation == "true",
        ))
    return results


@router.get("/{server_id}", response_model=McpServerResponse)
def get_mcp_server(
    server_id: int,
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> McpServerResponse:
    server = _get_server_or_404(server_id, db)
    return McpServerResponse(**server.to_dict())


@router.get("/{server_id}/export")
def export_mcp_server(
    server_id: int,
    user: UserInfo = Depends(require_scopes("admin:write")),
    db: Session = Depends(get_db),
):
    """Export full MCP server config including secrets. Super admin only."""
    server = _get_server_or_404(server_id, db)
    data: dict = {
        "name": server.name,
        "description": server.description,
        "endpoint_url": server.endpoint_url,
        "transport_type": server.transport_type,
        "auth_type": server.auth_type,
    }
    if server.auth_type == "oauth2":
        data["oauth2_well_known_url"] = server.oauth2_well_known_url
        data["oauth2_client_id"] = server.oauth2_client_id
        data["oauth2_client_secret"] = server.oauth2_client_secret or None
        data["oauth2_scopes"] = server.oauth2_scopes
        data["delegation_mode"] = server.delegation_mode
        if server.obo_grant_type:
            data["obo_grant_type"] = server.obo_grant_type
        if server.oauth2_audience:
            data["oauth2_audience"] = server.oauth2_audience
    if server.auth_type == "api_key":
        data["api_key_header_name"] = server.api_key_header_name
        data["api_key"] = resolve_api_key(server)
    if server.supports_elicitation == "true":
        data["supports_elicitation"] = True
    return data


@router.put("/{server_id}", response_model=McpServerResponse)
def update_mcp_server(
    server_id: int,
    request: McpServerUpdateRequest,
    user: UserInfo = Depends(require_scopes("mcp:write")),
    db: Session = Depends(get_db),
) -> McpServerResponse:
    server = _get_server_or_404(server_id, db)

    update_data = request.model_dump(exclude_unset=True)
    new_api_key = update_data.pop("api_key", None)
    if "supports_elicitation" in update_data:
        update_data["supports_elicitation"] = "true" if update_data["supports_elicitation"] else "false"
    for field, value in update_data.items():
        setattr(server, field, value)

    if new_api_key:
        region = os.getenv("AWS_REGION", "us-east-1")
        store_secret(f"loom/mcp/{server.name}/admin-api-key", new_api_key, region, description=f"Admin API key for MCP server {server.name}")
        server.has_admin_api_key = "true"

    server.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(server)
    return McpServerResponse(**server.to_dict())


@router.delete("/{server_id}", response_model=McpServerResponse)
def delete_mcp_server(
    server_id: int,
    user: UserInfo = Depends(require_scopes("mcp:write")),
    db: Session = Depends(get_db),
) -> McpServerResponse:
    server = _get_server_or_404(server_id, db)
    if server.registry_record_id:
        try:
            from app.services.registry import get_registry_client
            reg_client = get_registry_client()
            reg_client.delete_record(server.registry_record_id)
            logger.info("Deleted registry record %s for MCP server %s", server.registry_record_id, server.id)
        except Exception as reg_err:
            logger.warning("Failed to delete registry record for MCP server %s: %s", server.id, reg_err)
    if server.has_admin_api_key == "true":
        region = os.getenv("AWS_REGION", "us-east-1")
        delete_secret(f"loom/mcp/{server.name}/admin-api-key", region)
    result = McpServerResponse(**server.to_dict())
    db.delete(server)
    db.commit()
    return result


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------
class TestConnectionRequest(BaseModel):
    endpoint_url: str = Field(..., description="MCP server endpoint URL")
    transport_type: str = Field(default="sse", description="Transport type: 'sse' or 'streamable_http'")
    auth_type: str = Field(default="none", description="Auth type: 'none' or 'oauth2'")
    oauth2_well_known_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret: str | None = None
    oauth2_scopes: str | None = None
    delegation_mode: str | None = None
    oauth2_audience: str | None = None
    api_key_header_name: str | None = None
    api_key: str | None = None


def _extract_user_token(request: Request) -> str | None:
    """Extract the raw Bearer token from the request for OBO exchange."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


@router.post("/test-connection", response_model=TestConnectionResponse)
def test_connection_pre_create(
    request: TestConnectionRequest,
    raw_request: Request,
    user: UserInfo = Depends(require_scopes("mcp:write")),
) -> TestConnectionResponse:
    user_token = _extract_user_token(raw_request) if getattr(request, "delegation_mode", None) == "obo" else None
    result = svc_test_connection(request, api_key=request.api_key, user_token=user_token)
    return TestConnectionResponse(**result)


@router.post("/{server_id}/test-connection", response_model=TestConnectionResponse)
def test_connection(
    server_id: int,
    raw_request: Request,
    user: UserInfo = Depends(require_scopes("mcp:write")),
    db: Session = Depends(get_db),
) -> TestConnectionResponse:
    server = _get_server_or_404(server_id, db)
    api_key = resolve_api_key(server)
    user_token = _extract_user_token(raw_request) if getattr(server, "delegation_mode", "m2m") == "obo" else None
    result = svc_test_connection(server, api_key=api_key, user_token=user_token)
    return TestConnectionResponse(**result)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@router.get("/{server_id}/tools", response_model=list[McpToolResponse])
def get_mcp_tools(
    server_id: int,
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> list[McpToolResponse]:
    _get_server_or_404(server_id, db)
    tools = db.query(McpTool).filter(McpTool.server_id == server_id).all()
    return [McpToolResponse(**t.to_dict()) for t in tools]


@router.post("/{server_id}/tools/refresh", response_model=list[McpToolResponse])
def refresh_mcp_tools(
    server_id: int,
    request: Request,
    user: UserInfo = Depends(require_scopes("mcp:write")),
    db: Session = Depends(get_db),
) -> list[McpToolResponse]:
    server = _get_server_or_404(server_id, db)
    api_key = resolve_api_key(server)
    user_token = _extract_user_token(request) if getattr(server, "delegation_mode", "m2m") == "obo" else None

    fetched_tools = svc_fetch_tools(server, api_key=api_key, user_token=user_token)

    # Clear existing tools
    db.query(McpTool).filter(McpTool.server_id == server_id).delete()

    now = datetime.utcnow()
    new_tools = []
    for tool_data in fetched_tools:
        tool = McpTool(
            server_id=server_id,
            tool_name=tool_data.get("name", ""),
            description=tool_data.get("description"),
            last_refreshed_at=now,
        )
        schema = tool_data.get("input_schema")
        if schema:
            tool.set_input_schema(schema)
        db.add(tool)
        new_tools.append(tool)

    db.commit()
    for t in new_tools:
        db.refresh(t)

    if server.registry_record_id:
        try:
            from app.services.registry import get_registry_client
            reg_client = get_registry_client()
            tools_for_registry = db.query(McpTool).filter(McpTool.server_id == server_id).all()
            descriptors = reg_client.build_mcp_descriptors(server, tools_for_registry)
            reg_client.update_record(
                record_id=server.registry_record_id,
                name=server.name,
                descriptor_type="MCP",
                descriptors=descriptors,
                record_version="1.0",
                description=server.description,
            )
            logger.info("Updated registry record %s for MCP server %s", server.registry_record_id, server.id)
        except Exception as reg_err:
            logger.warning("Failed to update registry record for MCP server %s: %s", server.id, reg_err)

    return [McpToolResponse(**t.to_dict()) for t in new_tools]


@router.post("/{server_id}/tools/invoke", response_model=ToolInvokeResponse)
def invoke_mcp_tool(
    server_id: int,
    request: ToolInvokeRequest,
    user: UserInfo = Depends(require_scopes("mcp:write")),
    db: Session = Depends(get_db),
) -> ToolInvokeResponse:
    server = _get_server_or_404(server_id, db)
    api_key = resolve_api_key(server)
    result = svc_invoke_tool(server, request.tool_name, request.arguments, api_key=api_key)
    return ToolInvokeResponse(**result)


# ---------------------------------------------------------------------------
# Per-user API keys
# ---------------------------------------------------------------------------
class UserApiKeyRequest(BaseModel):
    api_key: str = Field(..., description="User's personal API key")


class UserApiKeyStatusResponse(BaseModel):
    has_user_api_key: bool


@router.put("/{server_id}/api-key", response_model=UserApiKeyStatusResponse)
def set_user_api_key(
    server_id: int,
    request: UserApiKeyRequest,
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> UserApiKeyStatusResponse:
    server = _get_server_or_404(server_id, db)
    region = os.getenv("AWS_REGION", "us-east-1")
    store_secret(
        f"loom/mcp/{server.name}/api-key/{user.sub}",
        request.api_key,
        region,
        description=f"User API key for MCP server {server.name}",
    )
    return UserApiKeyStatusResponse(has_user_api_key=True)


@router.get("/{server_id}/api-key/status", response_model=UserApiKeyStatusResponse)
def get_user_api_key_status(
    server_id: int,
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> UserApiKeyStatusResponse:
    server = _get_server_or_404(server_id, db)
    region = os.getenv("AWS_REGION", "us-east-1")
    try:
        from app.services.secrets import get_secret
        get_secret(f"loom/mcp/{server.name}/api-key/{user.sub}", region)
        return UserApiKeyStatusResponse(has_user_api_key=True)
    except Exception:
        return UserApiKeyStatusResponse(has_user_api_key=False)


@router.delete("/{server_id}/api-key", response_model=UserApiKeyStatusResponse)
def delete_user_api_key(
    server_id: int,
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> UserApiKeyStatusResponse:
    server = _get_server_or_404(server_id, db)
    region = os.getenv("AWS_REGION", "us-east-1")
    delete_secret(f"loom/mcp/{server.name}/api-key/{user.sub}", region)
    return UserApiKeyStatusResponse(has_user_api_key=False)


# ---------------------------------------------------------------------------
# Access rules
# ---------------------------------------------------------------------------
@router.get("/{server_id}/access", response_model=list[McpAccessRuleResponse])
def get_access_rules(
    server_id: int,
    user: UserInfo = Depends(require_scopes("mcp:read")),
    db: Session = Depends(get_db),
) -> list[McpAccessRuleResponse]:
    _get_server_or_404(server_id, db)
    rules = db.query(McpServerAccess).filter(McpServerAccess.server_id == server_id).all()
    return [McpAccessRuleResponse(**r.to_dict()) for r in rules]


@router.put("/{server_id}/access", response_model=list[McpAccessRuleResponse])
def update_access_rules(
    server_id: int,
    request: McpAccessUpdateRequest,
    user: UserInfo = Depends(require_scopes("mcp:write")),
    db: Session = Depends(get_db),
) -> list[McpAccessRuleResponse]:
    _get_server_or_404(server_id, db)

    # Replace all existing rules
    db.query(McpServerAccess).filter(McpServerAccess.server_id == server_id).delete()

    now = datetime.utcnow()
    new_rules = []
    for rule_input in request.rules:
        rule = McpServerAccess(
            server_id=server_id,
            persona_id=rule_input.persona_id,
            access_level=rule_input.access_level,
            created_at=now,
            updated_at=now,
        )
        if rule_input.allowed_tool_names is not None:
            rule.set_allowed_tool_names(rule_input.allowed_tool_names)
        db.add(rule)
        new_rules.append(rule)

    db.commit()
    for r in new_rules:
        db.refresh(r)

    return [McpAccessRuleResponse(**r.to_dict()) for r in new_rules]
