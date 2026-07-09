"""Agent ORM model for storing registered AgentCore Runtime metadata."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects from AWS API responses."""
    def default(self, o: object) -> str:
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


class Agent(Base):
    """
    Represents a registered AgentCore Runtime agent.

    ARN format: arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{runtime_id}
    """
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    arn = Column(String, unique=True, nullable=False, index=True)
    runtime_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    status = Column(String, nullable=True)
    region = Column(String, nullable=False)
    account_id = Column(String, nullable=False)
    log_group = Column(String, nullable=True)
    available_qualifiers = Column(Text, nullable=True)  # JSON array as text
    raw_metadata = Column(Text, nullable=True)  # Full JSON from AgentCore API
    source = Column(String, nullable=True)  # 'register' or 'deploy'
    deployment_status = Column(String, nullable=True)  # 'deploying', 'deployed', 'failed', 'removing'
    execution_role_arn = Column(String, nullable=True)
    config_hash = Column(String, nullable=True)
    endpoint_name = Column(String, nullable=True)
    endpoint_arn = Column(String, nullable=True)
    endpoint_status = Column(String, nullable=True)
    protocol = Column(String, nullable=True)  # HTTP, MCP, A2A
    network_mode = Column(String, nullable=True)  # PUBLIC or VPC
    authorizer_config = Column(Text, nullable=True)  # JSON: {type, pool_id, discovery_url, client_id, client_secret}
    description = Column(Text, nullable=True)  # Human-readable description of the agent
    tags = Column(Text, nullable=True)  # JSON dict of resolved tags
    deployed_at = Column(DateTime, nullable=True)
    registered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_refreshed_at = Column(DateTime, nullable=True)
    registry_record_id = Column(String, nullable=True)
    registry_status = Column(String, nullable=True)
    allowed_model_ids = Column(Text, nullable=True)  # JSON array of allowed model IDs
    harness_id = Column(String, nullable=True)  # Harness ID for managed agent deployments
    code_interpreter_id = Column(String, nullable=True)
    vpc_subnet_ids = Column(Text, nullable=True)      # kept for migration; resolved via vpc_config_id at deploy time
    vpc_security_group_ids = Column(Text, nullable=True)  # kept for migration; resolved via vpc_config_id at deploy time
    vpc_config_id = Column(Integer, ForeignKey("vpc_configs.id"), nullable=True)
    status_reason = Column(String, nullable=True)  # failureReason from AgentCore API on CREATE_FAILED/UPDATE_FAILED

    # Relationships
    sessions = relationship("InvocationSession", back_populates="agent", cascade="all, delete-orphan")
    config_entries = relationship("ConfigEntry", back_populates="agent", cascade="all, delete-orphan")
    credential_providers = relationship("CredentialProvider", back_populates="agent", cascade="all, delete-orphan")
    integrations = relationship("Integration", back_populates="agent", cascade="all, delete-orphan")

    def get_available_qualifiers(self) -> list[str]:
        """Parse available_qualifiers from JSON text."""
        if not self.available_qualifiers:
            return ["DEFAULT"]
        try:
            return json.loads(self.available_qualifiers)
        except json.JSONDecodeError:
            return ["DEFAULT"]

    def set_available_qualifiers(self, qualifiers: list[str]) -> None:
        """Serialize available_qualifiers to JSON text."""
        self.available_qualifiers = json.dumps(qualifiers)

    def get_raw_metadata(self) -> dict:
        """Parse raw_metadata from JSON text."""
        if not self.raw_metadata:
            return {}
        try:
            return json.loads(self.raw_metadata)
        except json.JSONDecodeError:
            return {}

    def set_raw_metadata(self, metadata: dict) -> None:
        """Serialize raw_metadata to JSON text."""
        self.raw_metadata = json.dumps(metadata, cls=DateTimeEncoder)

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

    def get_allowed_model_ids(self) -> list[str]:
        """Parse allowed_model_ids from JSON text."""
        if not self.allowed_model_ids:
            return []
        try:
            return json.loads(self.allowed_model_ids)
        except json.JSONDecodeError:
            return []

    def set_allowed_model_ids(self, model_ids: list[str]) -> None:
        """Serialize allowed_model_ids to JSON text."""
        self.allowed_model_ids = json.dumps(model_ids) if model_ids else None

    def get_authorizer_config(self) -> dict | None:
        """Parse authorizer_config from JSON text."""
        if not self.authorizer_config:
            return None
        try:
            return json.loads(self.authorizer_config)
        except json.JSONDecodeError:
            return None

    def set_authorizer_config(self, config: dict | None) -> None:
        """Serialize authorizer_config to JSON text."""
        self.authorizer_config = json.dumps(config) if config else None

    def get_vpc_subnet_ids(self) -> list[str]:
        """Parse vpc_subnet_ids from JSON text."""
        if not self.vpc_subnet_ids:
            return []
        try:
            return json.loads(self.vpc_subnet_ids)
        except json.JSONDecodeError:
            return []

    def set_vpc_subnet_ids(self, subnet_ids: list[str] | None) -> None:
        """Serialize vpc_subnet_ids to JSON text."""
        self.vpc_subnet_ids = json.dumps(subnet_ids) if subnet_ids else None

    def get_vpc_security_group_ids(self) -> list[str]:
        """Parse vpc_security_group_ids from JSON text."""
        if not self.vpc_security_group_ids:
            return []
        try:
            return json.loads(self.vpc_security_group_ids)
        except json.JSONDecodeError:
            return []

    def set_vpc_security_group_ids(self, sg_ids: list[str] | None) -> None:
        """Serialize vpc_security_group_ids to JSON text."""
        self.vpc_security_group_ids = json.dumps(sg_ids) if sg_ids else None

    def to_dict(self) -> dict:
        """Convert agent to dictionary for API responses."""
        return {
            "id": self.id,
            "arn": self.arn,
            "runtime_id": self.runtime_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "region": self.region,
            "account_id": self.account_id,
            "log_group": self.log_group,
            "available_qualifiers": self.get_available_qualifiers(),
            "source": self.source,
            "deployment_status": self.deployment_status,
            "execution_role_arn": self.execution_role_arn,
            "config_hash": self.config_hash,
            "endpoint_name": self.endpoint_name,
            "endpoint_arn": self.endpoint_arn,
            "endpoint_status": self.endpoint_status,
            "protocol": self.protocol,
            "network_mode": self.network_mode,
            "tags": self.get_tags(),
            "authorizer_config": self.get_authorizer_config(),
            "deployed_at": (self.deployed_at.isoformat() + "Z") if self.deployed_at else None,
            "registered_at": (self.registered_at.isoformat() + "Z") if self.registered_at else None,
            "last_refreshed_at": (self.last_refreshed_at.isoformat() + "Z") if self.last_refreshed_at else None,
            "registry_record_id": self.registry_record_id,
            "registry_status": self.registry_status,
            "allowed_model_ids": self.get_allowed_model_ids(),
            "harness_id": self.harness_id,
            "code_interpreter_id": self.code_interpreter_id,
            "vpc_config_id": self.vpc_config_id,
            "status_reason": self.status_reason,
        }
