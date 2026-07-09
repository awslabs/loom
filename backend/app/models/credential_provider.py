"""CredentialProvider ORM model for storing agent credential provider metadata."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class CredentialProvider(Base):
    """
    Represents a credential provider for an agent.

    Tracks MCP servers, A2A endpoints, and API targets that require
    credential management for the agent.
    """
    __tablename__ = "credential_providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    vendor = Column(String, nullable=True)
    callback_url = Column(String, nullable=True)
    scopes = Column(String, nullable=True)  # JSON array stored as text
    provider_type = Column(String, nullable=True)  # 'mcp_server', 'a2a', 'api_target'
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    agent = relationship("Agent", back_populates="credential_providers")
    integrations = relationship("Integration", back_populates="credential_provider")

    def get_scopes(self) -> list[str]:
        """Parse scopes from JSON text."""
        if not self.scopes:
            return []
        try:
            return json.loads(self.scopes)
        except json.JSONDecodeError:
            return []

    def to_dict(self) -> dict:
        """Convert credential provider to dictionary for API responses."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "name": self.name,
            "vendor": self.vendor,
            "callback_url": self.callback_url,
            "scopes": self.get_scopes(),
            "provider_type": self.provider_type,
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
        }
