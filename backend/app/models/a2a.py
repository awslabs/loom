"""A2A agent ORM models for managing Agent-to-Agent protocol integrations."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class A2aAgent(Base):
    __tablename__ = "a2a_agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    base_url = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    agent_version = Column(String, nullable=False)
    documentation_url = Column(String, nullable=True)
    provider_organization = Column(String, nullable=True)
    provider_url = Column(String, nullable=True)
    capabilities = Column(Text, nullable=False, default="{}")  # JSON
    authentication_schemes = Column(Text, nullable=False, default="[]")  # JSON
    default_input_modes = Column(Text, nullable=False, default="[]")  # JSON
    default_output_modes = Column(Text, nullable=False, default="[]")  # JSON
    agent_card_raw = Column(Text, nullable=False, default="{}")  # JSON
    status = Column(String, nullable=False, default="active")  # active, inactive, error
    auth_type = Column(String, nullable=False, default="none")  # none, oauth2
    oauth2_well_known_url = Column(String, nullable=True)
    oauth2_client_id = Column(String, nullable=True)
    oauth2_client_secret = Column(String, nullable=True)
    oauth2_scopes = Column(String, nullable=True)  # space-separated
    delegation_mode = Column(String, nullable=False, default="m2m")  # 'm2m' or 'obo'
    obo_grant_type = Column(String, nullable=True)  # 'JWT_AUTHORIZATION_GRANT' or 'TOKEN_EXCHANGE'
    agentcore_session_id = Column(String, nullable=True)  # persisted AgentCore Runtime session ID
    registry_record_id = Column(String, nullable=True)
    registry_status = Column(String, nullable=True)  # DRAFT, PENDING_APPROVAL, APPROVED, REJECTED, DEPRECATED
    last_fetched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    skills = relationship("A2aAgentSkill", back_populates="agent", cascade="all, delete-orphan")
    access_rules = relationship("A2aAgentAccess", back_populates="agent", cascade="all, delete-orphan")

    def _parse_json(self, field: str) -> dict | list | None:
        val = getattr(self, field)
        if not val:
            return None
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "base_url": self.base_url,
            "name": self.name,
            "description": self.description,
            "agent_version": self.agent_version,
            "documentation_url": self.documentation_url,
            "provider_organization": self.provider_organization,
            "provider_url": self.provider_url,
            "capabilities": self._parse_json("capabilities") or {},
            "authentication_schemes": self._parse_json("authentication_schemes") or [],
            "default_input_modes": self._parse_json("default_input_modes") or [],
            "default_output_modes": self._parse_json("default_output_modes") or [],
            "agent_card_raw": self._parse_json("agent_card_raw") or {},
            "status": self.status,
            "auth_type": self.auth_type,
            "oauth2_well_known_url": self.oauth2_well_known_url,
            "oauth2_client_id": self.oauth2_client_id,
            "oauth2_scopes": self.oauth2_scopes,
            "has_oauth2_secret": bool(self.oauth2_client_secret),
            "delegation_mode": self.delegation_mode or "m2m",
            "obo_grant_type": self.obo_grant_type,
            "agentcore_session_id": self.agentcore_session_id,
            "registry_record_id": self.registry_record_id,
            "registry_status": self.registry_status,
            "last_fetched_at": (self.last_fetched_at.isoformat() + "Z") if self.last_fetched_at else None,
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
            "updated_at": (self.updated_at.isoformat() + "Z") if self.updated_at else None,
        }


class A2aAgentSkill(Base):
    __tablename__ = "a2a_agent_skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("a2a_agents.id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    tags = Column(Text, nullable=False, default="[]")  # JSON
    examples = Column(Text, nullable=True)  # JSON
    input_modes = Column(Text, nullable=True)  # JSON
    output_modes = Column(Text, nullable=True)  # JSON
    last_refreshed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    agent = relationship("A2aAgent", back_populates="skills")

    def _parse_json(self, field: str) -> list | None:
        val = getattr(self, field)
        if not val:
            return None
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "tags": self._parse_json("tags") or [],
            "examples": self._parse_json("examples"),
            "input_modes": self._parse_json("input_modes"),
            "output_modes": self._parse_json("output_modes"),
            "last_refreshed_at": (self.last_refreshed_at.isoformat() + "Z") if self.last_refreshed_at else None,
        }


class A2aAgentAccess(Base):
    __tablename__ = "a2a_agent_access"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("a2a_agents.id", ondelete="CASCADE"), nullable=False)
    persona_id = Column(Integer, nullable=False)
    access_level = Column(String, nullable=False)  # 'all_skills' or 'selected_skills'
    allowed_skill_ids = Column(Text, nullable=True)  # JSON list
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent = relationship("A2aAgent", back_populates="access_rules")

    def get_allowed_skill_ids(self) -> list[str] | None:
        if not self.allowed_skill_ids:
            return None
        try:
            return json.loads(self.allowed_skill_ids)
        except json.JSONDecodeError:
            return None

    def set_allowed_skill_ids(self, ids: list[str] | None) -> None:
        self.allowed_skill_ids = json.dumps(ids) if ids else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "persona_id": self.persona_id,
            "access_level": self.access_level,
            "allowed_skill_ids": self.get_allowed_skill_ids(),
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
            "updated_at": (self.updated_at.isoformat() + "Z") if self.updated_at else None,
        }
