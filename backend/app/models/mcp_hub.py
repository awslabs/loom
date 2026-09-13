"""Hub session persistence for the MCP Hub (ADR 0007 / spec 017)."""
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.db import Base


class McpHubSession(Base):
    __tablename__ = "mcp_hub_sessions"

    id = Column(String, primary_key=True)  # uuid
    token_hash = Column(String, nullable=False, unique=True, index=True)
    subject = Column(String, nullable=False, index=True)
    idp_type = Column(String, nullable=False, default="keycloak")
    scopes_json = Column(Text, nullable=True)  # JSON list
    groups_json = Column(Text, nullable=True)  # JSON list of IdP groups at mint
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    client_label = Column(String, nullable=True)
