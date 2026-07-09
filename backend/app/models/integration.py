"""Integration ORM model for storing agent integration configurations."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class Integration(Base):
    """
    Represents an integration for an agent.

    Tracks external service integrations such as S3, DynamoDB, MCP Gateway,
    A2A, and external APIs that an agent connects to.
    """
    __tablename__ = "agent_integrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_type = Column(String, nullable=True)  # 's3', 'dynamodb', 'mcp_gateway', 'a2a', 'external_api'
    integration_config = Column(String, nullable=True)  # JSON stored as text
    credential_provider_id = Column(Integer, ForeignKey("credential_providers.id", ondelete="SET NULL"), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    # Relationships
    agent = relationship("Agent", back_populates="integrations")
    credential_provider = relationship("CredentialProvider", back_populates="integrations")

    def get_integration_config(self) -> dict:
        """Parse integration_config from JSON text."""
        if not self.integration_config:
            return {}
        try:
            return json.loads(self.integration_config)
        except json.JSONDecodeError:
            return {}

    def to_dict(self) -> dict:
        """Convert integration to dictionary for API responses."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "integration_type": self.integration_type,
            "integration_config": self.get_integration_config(),
            "credential_provider_id": self.credential_provider_id,
            "enabled": self.enabled,
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
            "updated_at": (self.updated_at.isoformat() + "Z") if self.updated_at else None,
        }
