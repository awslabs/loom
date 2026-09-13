"""MCP server ORM models for managing Model Context Protocol server connections."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    endpoint_url = Column(String, nullable=False)
    transport_type = Column(String, nullable=False)  # 'sse', 'streamable_http', or 'stdio'
    status = Column(String, nullable=False, default="active")  # active, inactive, error
    auth_type = Column(String, nullable=False, default="none")  # none, oauth2, api_key, loom
    template_id = Column(String, nullable=True)
    template_params = Column(Text, nullable=True)  # JSON
    secret_refs = Column(Text, nullable=True)  # JSON list of SecretReference
    runtime_state = Column(String, nullable=True)
    oauth2_well_known_url = Column(String, nullable=True)
    oauth2_client_id = Column(String, nullable=True)
    oauth2_client_secret = Column(String, nullable=True)
    oauth2_scopes = Column(String, nullable=True)  # space-separated
    delegation_mode = Column(String, nullable=False, default="m2m")  # 'm2m' or 'obo'
    obo_grant_type = Column(String, nullable=True)  # 'JWT_AUTHORIZATION_GRANT' or 'TOKEN_EXCHANGE'
    oauth2_audience = Column(String, nullable=True)  # Token exchange audience (required for Okta custom auth servers)
    api_key_header_name = Column(String, nullable=True)  # e.g. 'x-api-key', 'Authorization'
    has_admin_api_key = Column(String, nullable=True)  # 'true' or 'false'
    supports_elicitation = Column(String, nullable=True, default="false")  # 'true' or 'false'
    runtime_endpoint_url = Column(String, nullable=True)  # direct runtime URL for WebSocket (bypasses Gateway)
    registry_record_id = Column(String, nullable=True)
    registry_status = Column(String, nullable=True)  # DRAFT, PENDING_APPROVAL, APPROVED, REJECTED, DEPRECATED
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tools = relationship("McpTool", back_populates="server", cascade="all, delete-orphan")
    access_rules = relationship("McpServerAccess", back_populates="server", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "endpoint_url": self.endpoint_url,
            "transport_type": self.transport_type,
            "status": self.status,
            "auth_type": self.auth_type,
            "oauth2_well_known_url": self.oauth2_well_known_url,
            "oauth2_client_id": self.oauth2_client_id,
            "oauth2_scopes": self.oauth2_scopes,
            "delegation_mode": self.delegation_mode or "m2m",
            "obo_grant_type": self.obo_grant_type,
            "oauth2_audience": self.oauth2_audience,
            "has_oauth2_secret": bool(self.oauth2_client_secret),
            "api_key_header_name": self.api_key_header_name,
            "has_admin_api_key": self.has_admin_api_key == "true",
            "supports_elicitation": self.supports_elicitation == "true",
            "runtime_endpoint_url": self.runtime_endpoint_url,
            "template_id": self.template_id,
            "template_params": self.get_template_params(),
            "secret_refs": self.get_secret_refs(),
            "runtime_state": self.runtime_state,
            "registry_record_id": self.registry_record_id,
            "registry_status": self.registry_status,
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
            "updated_at": (self.updated_at.isoformat() + "Z") if self.updated_at else None,
        }

    def get_template_params(self) -> dict | None:
        if not self.template_params:
            return None
        try:
            return json.loads(self.template_params)
        except json.JSONDecodeError:
            return None

    def set_template_params(self, params: dict | None) -> None:
        self.template_params = json.dumps(params) if params else None

    def get_secret_refs(self) -> list | None:
        if not self.secret_refs:
            return None
        try:
            return json.loads(self.secret_refs)
        except json.JSONDecodeError:
            return None

    def set_secret_refs(self, refs: list | None) -> None:
        self.secret_refs = json.dumps(refs) if refs else None


class McpTool(Base):
    __tablename__ = "mcp_tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(Integer, ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    input_schema = Column(Text, nullable=True)  # JSON
    last_refreshed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    server = relationship("McpServer", back_populates="tools")

    def get_input_schema(self) -> dict | None:
        if not self.input_schema:
            return None
        try:
            return json.loads(self.input_schema)
        except json.JSONDecodeError:
            return None

    def set_input_schema(self, schema: dict | None) -> None:
        self.input_schema = json.dumps(schema) if schema else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "tool_name": self.tool_name,
            "description": self.description,
            "input_schema": self.get_input_schema(),
            "last_refreshed_at": (self.last_refreshed_at.isoformat() + "Z") if self.last_refreshed_at else None,
        }


class McpServerAccess(Base):
    __tablename__ = "mcp_server_access"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(Integer, ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False)
    persona_id = Column(Integer, nullable=False)
    access_level = Column(String, nullable=False)  # 'all_tools' or 'selected_tools'
    allowed_tool_names = Column(Text, nullable=True)  # JSON list
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    server = relationship("McpServer", back_populates="access_rules")

    def get_allowed_tool_names(self) -> list[str] | None:
        if not self.allowed_tool_names:
            return None
        try:
            return json.loads(self.allowed_tool_names)
        except json.JSONDecodeError:
            return None

    def set_allowed_tool_names(self, names: list[str] | None) -> None:
        self.allowed_tool_names = json.dumps(names) if names else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "persona_id": self.persona_id,
            "access_level": self.access_level,
            "allowed_tool_names": self.get_allowed_tool_names(),
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
            "updated_at": (self.updated_at.isoformat() + "Z") if self.updated_at else None,
        }
