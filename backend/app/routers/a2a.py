"""A2A agent management endpoints."""
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from sqlalchemy import or_

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.a2a import A2aAgent, A2aAgentSkill, A2aAgentAccess
from app.services.a2a import (
    _build_headers,
    _is_agentcore_url,
    fetch_agent_card,
    parse_agent_card,
    parse_skills,
    test_a2a_connection as svc_test_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/a2a/agents", tags=["a2a"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class A2aAgentCreateRequest(BaseModel):
    base_url: str = Field(..., description="Base URL of the A2A agent")
    name: str | None = Field(None, description="Display name (defaults to Agent Card name if not provided)")
    auth_type: str = Field(default="none", description="Auth type: 'none' or 'oauth2'")
    oauth2_well_known_url: str | None = Field(None, description="OAuth2 well-known URL")
    oauth2_client_id: str | None = Field(None, description="OAuth2 client ID")
    oauth2_client_secret: str | None = Field(None, description="OAuth2 client secret")
    oauth2_scopes: str | None = Field(None, description="OAuth2 scopes (space-separated)")
    delegation_mode: str = Field(default="m2m", description="OAuth2 delegation mode: 'm2m' or 'obo'")
    obo_grant_type: str | None = Field(None, description="OBO grant type: 'JWT_AUTHORIZATION_GRANT' (Entra ID) or 'TOKEN_EXCHANGE' (Okta)")

    @model_validator(mode="after")
    def validate_oauth2_fields(self):
        if self.auth_type == "oauth2":
            if not self.oauth2_well_known_url:
                raise ValueError("oauth2_well_known_url is required when auth_type is 'oauth2'")
            if not self.oauth2_client_id:
                raise ValueError("oauth2_client_id is required when auth_type is 'oauth2'")
        return self


class A2aAgentUpdateRequest(BaseModel):
    base_url: str | None = None
    name: str | None = None
    status: str | None = None
    auth_type: str | None = None
    oauth2_well_known_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret: str | None = None
    oauth2_scopes: str | None = None
    delegation_mode: str | None = None
    obo_grant_type: str | None = None


class A2aAgentResponse(BaseModel):
    id: int
    base_url: str
    name: str
    description: str  # nosec B105 — field type annotation, not a password
    agent_version: str
    documentation_url: str | None = None
    provider_organization: str | None = None
    provider_url: str | None = None
    capabilities: dict = {}
    authentication_schemes: list = []
    default_input_modes: list = []
    default_output_modes: list = []
    agent_card_raw: dict = {}
    status: str
    auth_type: str
    oauth2_well_known_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_scopes: str | None = None
    has_oauth2_secret: bool = False
    delegation_mode: str = "m2m"
    obo_grant_type: str | None = None
    agentcore_session_id: str | None = None
    registry_record_id: str | None = None
    registry_status: str | None = None
    last_fetched_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class A2aSkillResponse(BaseModel):
    id: int
    agent_id: int
    skill_id: str
    name: str
    description: str
    tags: list = []
    examples: list | None = None
    input_modes: list | None = None
    output_modes: list | None = None
    last_refreshed_at: str | None = None


class A2aAccessRuleResponse(BaseModel):
    id: int
    agent_id: int
    persona_id: int
    access_level: str
    allowed_skill_ids: list[str] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class A2aAccessRuleInput(BaseModel):
    persona_id: int
    access_level: str
    allowed_skill_ids: list[str] | None = None


class A2aAccessUpdateRequest(BaseModel):
    rules: list[A2aAccessRuleInput]


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_agent_or_404(agent_id: int, db: Session) -> A2aAgent:
    agent = db.query(A2aAgent).filter(A2aAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"A2A agent with id {agent_id} not found",
        )
    return agent


def _sync_skills(agent_id: int, card: dict, db: Session) -> list[A2aAgentSkill]:
    """Sync skills from an Agent Card into the database."""
    db.query(A2aAgentSkill).filter(A2aAgentSkill.agent_id == agent_id).delete()

    now = datetime.utcnow()
    new_skills = []
    for skill_data in parse_skills(card):
        skill = A2aAgentSkill(
            agent_id=agent_id,
            skill_id=skill_data["skill_id"],
            name=skill_data["name"],
            description=skill_data["description"],
            tags=json.dumps(skill_data.get("tags", [])),
            examples=json.dumps(skill_data["examples"]) if skill_data.get("examples") else None,
            input_modes=json.dumps(skill_data["input_modes"]) if skill_data.get("input_modes") else None,
            output_modes=json.dumps(skill_data["output_modes"]) if skill_data.get("output_modes") else None,
            last_refreshed_at=now,
        )
        db.add(skill)
        new_skills.append(skill)
    return new_skills


def _apply_card_to_agent(agent: A2aAgent, card: dict, parsed: dict, *, preserve_name: bool = False) -> None:
    """Apply parsed Agent Card data to an A2aAgent model instance."""
    if not preserve_name:
        agent.name = parsed["name"]
    agent.description = parsed["description"]
    agent.agent_version = parsed["agent_version"]
    agent.documentation_url = parsed.get("documentation_url")
    agent.provider_organization = parsed.get("provider_organization")
    agent.provider_url = parsed.get("provider_url")
    agent.capabilities = json.dumps(parsed["capabilities"])
    agent.authentication_schemes = json.dumps(parsed["authentication_schemes"])
    agent.default_input_modes = json.dumps(parsed["default_input_modes"])
    agent.default_output_modes = json.dumps(parsed["default_output_modes"])
    agent.agent_card_raw = json.dumps(card)
    agent.last_fetched_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------
@router.post("", response_model=A2aAgentResponse, status_code=status.HTTP_201_CREATED)
def create_a2a_agent(
    request: A2aAgentCreateRequest,
    user: UserInfo = Depends(require_scopes("a2a:write")),
    db: Session = Depends(get_db),
) -> A2aAgentResponse:
    # Fetch Agent Card using OAuth2 credentials from the request
    try:
        headers = _build_headers(request)
        card = fetch_agent_card(request.base_url, auth_headers=headers)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    parsed = parse_agent_card(card)

    agent = A2aAgent(
        base_url=request.base_url,
        name=request.name.strip() if request.name and request.name.strip() else parsed["name"],
        description=parsed["description"],
        agent_version=parsed["agent_version"],
        documentation_url=parsed.get("documentation_url"),
        provider_organization=parsed.get("provider_organization"),
        provider_url=parsed.get("provider_url"),
        capabilities=json.dumps(parsed["capabilities"]),
        authentication_schemes=json.dumps(parsed["authentication_schemes"]),
        default_input_modes=json.dumps(parsed["default_input_modes"]),
        default_output_modes=json.dumps(parsed["default_output_modes"]),
        agent_card_raw=json.dumps(card),
        auth_type=request.auth_type,
        oauth2_well_known_url=request.oauth2_well_known_url,
        oauth2_client_id=request.oauth2_client_id,
        oauth2_client_secret=request.oauth2_client_secret,
        oauth2_scopes=request.oauth2_scopes,
        delegation_mode=request.delegation_mode or "m2m",
        obo_grant_type=request.obo_grant_type,
        agentcore_session_id=str(uuid.uuid4()) if _is_agentcore_url(request.base_url) else None,
        last_fetched_at=datetime.utcnow(),
    )
    db.add(agent)
    db.flush()

    _sync_skills(agent.id, card, db)

    db.commit()
    db.refresh(agent)
    return A2aAgentResponse(**agent.to_dict())


@router.get("", response_model=list[A2aAgentResponse])
def list_a2a_agents(
    user: UserInfo = Depends(require_scopes("a2a:read")),
    db: Session = Depends(get_db),
) -> list[A2aAgentResponse]:
    query = db.query(A2aAgent)
    # t-user (without t-admin) can only see APPROVED or unregistered agents
    if "t-user" in user.groups and "t-admin" not in user.groups:
        query = query.filter(or_(A2aAgent.registry_status == "APPROVED", A2aAgent.registry_status.is_(None)))
    agents = query.order_by(A2aAgent.created_at.desc()).all()
    return [A2aAgentResponse(**a.to_dict()) for a in agents]


@router.get("/{agent_id}", response_model=A2aAgentResponse)
def get_a2a_agent(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("a2a:read")),
    db: Session = Depends(get_db),
) -> A2aAgentResponse:
    agent = _get_agent_or_404(agent_id, db)
    return A2aAgentResponse(**agent.to_dict())


@router.put("/{agent_id}", response_model=A2aAgentResponse)
def update_a2a_agent(
    agent_id: int,
    request: A2aAgentUpdateRequest,
    user: UserInfo = Depends(require_scopes("a2a:write")),
    db: Session = Depends(get_db),
) -> A2aAgentResponse:
    agent = _get_agent_or_404(agent_id, db)

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)

    # Assign AgentCore session ID if base_url changed to an AgentCore endpoint
    if "base_url" in update_data:
        if _is_agentcore_url(agent.base_url) and not agent.agentcore_session_id:
            agent.agentcore_session_id = str(uuid.uuid4())
        elif not _is_agentcore_url(agent.base_url):
            agent.agentcore_session_id = None

    agent.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(agent)
    return A2aAgentResponse(**agent.to_dict())


@router.delete("/{agent_id}", response_model=A2aAgentResponse)
def delete_a2a_agent(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("a2a:write")),
    db: Session = Depends(get_db),
) -> A2aAgentResponse:
    agent = _get_agent_or_404(agent_id, db)
    if agent.registry_record_id:
        try:
            from app.services.registry import get_registry_client
            reg_client = get_registry_client()
            reg_client.delete_record(agent.registry_record_id)
            logger.info("Deleted registry record %s for A2A agent %s", agent.registry_record_id, agent.id)
        except Exception as reg_err:
            logger.warning("Failed to delete registry record for A2A agent %s: %s", agent.id, reg_err)
    result = A2aAgentResponse(**agent.to_dict())
    db.delete(agent)
    db.commit()
    return result


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------
class TestConnectionRequest(BaseModel):
    base_url: str = Field(..., description="Base URL of the A2A agent")
    auth_type: str = Field(default="none", description="Auth type: 'none' or 'oauth2'")
    oauth2_well_known_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret: str | None = None
    oauth2_scopes: str | None = None


@router.post("/test-connection", response_model=TestConnectionResponse)
def test_connection_pre_create(
    request: TestConnectionRequest,
    user: UserInfo = Depends(require_scopes("a2a:write")),
) -> TestConnectionResponse:
    result = svc_test_connection(request)
    return TestConnectionResponse(**result)


@router.post("/{agent_id}/test-connection", response_model=TestConnectionResponse)
def test_connection(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("a2a:write")),
    db: Session = Depends(get_db),
) -> TestConnectionResponse:
    agent = _get_agent_or_404(agent_id, db)
    result = svc_test_connection(agent)
    return TestConnectionResponse(**result)


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------
@router.get("/{agent_id}/card", response_model=dict)
def get_agent_card(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("a2a:read")),
    db: Session = Depends(get_db),
) -> dict:
    agent = _get_agent_or_404(agent_id, db)
    raw = agent.agent_card_raw
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {}


@router.post("/{agent_id}/card/refresh", response_model=A2aAgentResponse)
def refresh_agent_card(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("a2a:write")),
    db: Session = Depends(get_db),
) -> A2aAgentResponse:
    agent = _get_agent_or_404(agent_id, db)
    headers = _build_headers(agent)

    try:
        card = fetch_agent_card(agent.base_url, auth_headers=headers)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    parsed = parse_agent_card(card)
    _apply_card_to_agent(agent, card, parsed, preserve_name=True)
    _sync_skills(agent.id, card, db)

    db.commit()
    db.refresh(agent)
    return A2aAgentResponse(**agent.to_dict())


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------
@router.get("/{agent_id}/skills", response_model=list[A2aSkillResponse])
def get_agent_skills(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("a2a:read")),
    db: Session = Depends(get_db),
) -> list[A2aSkillResponse]:
    _get_agent_or_404(agent_id, db)
    skills = db.query(A2aAgentSkill).filter(A2aAgentSkill.agent_id == agent_id).all()
    return [A2aSkillResponse(**s.to_dict()) for s in skills]


# ---------------------------------------------------------------------------
# Access rules
# ---------------------------------------------------------------------------
@router.get("/{agent_id}/access", response_model=list[A2aAccessRuleResponse])
def get_access_rules(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("a2a:read")),
    db: Session = Depends(get_db),
) -> list[A2aAccessRuleResponse]:
    _get_agent_or_404(agent_id, db)
    rules = db.query(A2aAgentAccess).filter(A2aAgentAccess.agent_id == agent_id).all()
    return [A2aAccessRuleResponse(**r.to_dict()) for r in rules]


@router.put("/{agent_id}/access", response_model=list[A2aAccessRuleResponse])
def update_access_rules(
    agent_id: int,
    request: A2aAccessUpdateRequest,
    user: UserInfo = Depends(require_scopes("a2a:write")),
    db: Session = Depends(get_db),
) -> list[A2aAccessRuleResponse]:
    _get_agent_or_404(agent_id, db)

    db.query(A2aAgentAccess).filter(A2aAgentAccess.agent_id == agent_id).delete()

    now = datetime.utcnow()
    new_rules = []
    for rule_input in request.rules:
        rule = A2aAgentAccess(
            agent_id=agent_id,
            persona_id=rule_input.persona_id,
            access_level=rule_input.access_level,
            created_at=now,
            updated_at=now,
        )
        if rule_input.allowed_skill_ids is not None:
            rule.set_allowed_skill_ids(rule_input.allowed_skill_ids)
        db.add(rule)
        new_rules.append(rule)

    db.commit()
    for r in new_rules:
        db.refresh(r)

    return [A2aAccessRuleResponse(**r.to_dict()) for r in new_rules]


@router.get("/{agent_id}/export")
def export_a2a_agent(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("admin:write")),
    db: Session = Depends(get_db),
):
    """Export full A2A agent config including secrets. Super admin only."""
    agent = _get_agent_or_404(agent_id, db)
    data: dict = {
        "base_url": agent.base_url,
        "name": agent.name,
        "auth_type": agent.auth_type,
    }
    if agent.auth_type == "oauth2":
        data["oauth2_well_known_url"] = agent.oauth2_well_known_url
        data["oauth2_client_id"] = agent.oauth2_client_id
        data["oauth2_client_secret"] = agent.oauth2_client_secret or None
        data["oauth2_scopes"] = agent.oauth2_scopes
        data["delegation_mode"] = agent.delegation_mode
    return data
