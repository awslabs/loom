"""Memory ORM model for storing AgentCore Memory resource metadata."""
import json
from datetime import datetime
from typing import Any
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.db import Base
from app.models.agent import DateTimeEncoder


class Memory(Base):
    """
    Represents an AgentCore Memory resource.

    ARN format: arn:aws:bedrock-agentcore:{region}:{account_id}:memory/{memory_id}
    """
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    arn = Column(String, nullable=True)
    memory_id = Column(String, nullable=True)
    region = Column(String, nullable=False)
    account_id = Column(String, nullable=False)
    status = Column(String, nullable=False)  # CREATING, ACTIVE, FAILED, DELETING
    event_expiry_duration = Column(Integer, nullable=False)
    memory_execution_role_arn = Column(String, nullable=True)
    encryption_key_arn = Column(String, nullable=True)
    strategies_config = Column(Text, nullable=True)  # JSON stored as text
    strategies_response = Column(Text, nullable=True)  # JSON stored as text
    tags = Column(Text, nullable=True)  # JSON dict of resolved tags
    failure_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_strategies_config(self) -> list | None:
        """Parse strategies_config from JSON text."""
        if not self.strategies_config:
            return None
        try:
            return json.loads(self.strategies_config)
        except json.JSONDecodeError:
            return None

    def set_strategies_config(self, config: list | dict | None) -> None:
        """Serialize strategies_config to JSON text."""
        self.strategies_config = json.dumps(config, cls=DateTimeEncoder) if config is not None else None

    def get_strategies_response(self) -> list | None:
        """Parse strategies_response from JSON text."""
        if not self.strategies_response:
            return None
        try:
            return json.loads(self.strategies_response)
        except json.JSONDecodeError:
            return None

    def set_strategies_response(self, response: list | dict | None) -> None:
        """Serialize strategies_response to JSON text."""
        self.strategies_response = json.dumps(response, cls=DateTimeEncoder) if response is not None else None

    def get_tags(self) -> dict[str, str]:
        """Parse tags from JSON text."""
        if not self.tags:
            return {}
        try:
            return json.loads(self.tags)
        except json.JSONDecodeError:
            return {}

    def set_tags(self, tags: dict[str, str]) -> None:
        """Serialize tags to JSON text."""
        self.tags = json.dumps(tags)

    def to_dict(self) -> dict[str, Any]:
        """Convert memory to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "arn": self.arn,
            "memory_id": self.memory_id,
            "region": self.region,
            "account_id": self.account_id,
            "status": self.status,
            "event_expiry_duration": self.event_expiry_duration,
            "memory_execution_role_arn": self.memory_execution_role_arn,
            "encryption_key_arn": self.encryption_key_arn,
            "strategies_config": self.get_strategies_config(),
            "strategies_response": self.get_strategies_response(),
            "tags": self.get_tags(),
            "failure_reason": self.failure_reason,
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
            "updated_at": (self.updated_at.isoformat() + "Z") if self.updated_at else None,
        }
