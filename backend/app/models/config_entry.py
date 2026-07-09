"""ConfigEntry ORM model for storing agent configuration key-value pairs."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db import Base


class ConfigEntry(Base):
    """
    Represents a configuration entry for an agent.

    Stores key-value pairs that configure agent behavior, including
    environment variables, secrets references, and S3-sourced config.
    """
    __tablename__ = "agent_config_entries"
    __table_args__ = (
        UniqueConstraint("agent_id", "key", name="uq_config_agent_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String, nullable=False)
    value = Column(String, nullable=True)  # Plaintext for non-secrets, ARN for secrets
    is_secret = Column(Boolean, nullable=False, default=False)
    source = Column(String, nullable=True)  # 'env_var', 'secrets_manager', 's3'
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    # Relationship to agent
    agent = relationship("Agent", back_populates="config_entries")

    def to_dict(self) -> dict:
        """Convert config entry to dictionary for API responses."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "key": self.key,
            "value": self.value,
            "is_secret": self.is_secret,
            "source": self.source,
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
            "updated_at": (self.updated_at.isoformat() + "Z") if self.updated_at else None,
        }
