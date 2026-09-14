"""Local agent create/list from agent-runtime templates (Spec 026 A2).

Authorized Core exception: thin BFF over agent-runtime allowlist; persists
source=local rows in the Loom agents catalog.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.config_entry import ConfigEntry
from app.routers.agents import AgentResponse, _agent_response
from app.services.local_agent_templates import (
    LocalTemplateError,
    list_local_templates,
    materialize_local_template,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["local-agents"])


class LocalAgentCreateRequest(BaseModel):
    template_id: str = Field(..., description="Allowlisted template id from agent-runtime")
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="")
    params: dict[str, Any] = Field(default_factory=dict)
    system_prompt_override: str | None = Field(
        default=None,
        description="Optional full system prompt override after materialize",
    )
    tags: dict[str, str] | None = None


class LocalAgentBehaviorRequest(BaseModel):
    system_prompt: str | None = Field(
        default=None,
        description="Replace system_prompt on a local agent",
    )
    reset_to_template: bool = Field(
        default=False,
        description="Re-materialize prompt from template_id + stored template_params",
    )


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "local-agent"
    return f"{base}-{uuid.uuid4().hex[:8]}"


@router.get("/local-templates")
def get_local_templates(
    user: UserInfo = Depends(require_scopes("agent:read")),
) -> dict[str, Any]:
    try:
        return {"templates": list_local_templates()}
    except LocalTemplateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/local", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_local_agent(
    request: LocalAgentCreateRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> AgentResponse:
    if "g-admins-demo" in user.groups and "g-admins-super" not in user.groups:
        agent_group = (request.tags or {}).get("loom:group", "")
        if agent_group and agent_group != "demo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo admins can only create agents in the 'demo' group",
            )
    if "g-users-demo" in user.groups and not request.name.startswith("demo_"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Demo users must prefix agent names with 'demo_'",
        )

    try:
        config = materialize_local_template(
            request.template_id,
            params=request.params,
            system_prompt_override=request.system_prompt_override,
        )
    except LocalTemplateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    runtime_id = _slug(request.name)
    arn = f"arn:local:loom:local:local:runtime/{runtime_id}"
    if db.query(Agent).filter(Agent.arn == arn).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ARN collision; retry")

    model_id = str(config.get("model_id") or "cursor-local")
    allowed = config.get("allowed_model_ids") or [model_id]
    if not isinstance(allowed, list) or not allowed:
        allowed = [model_id]

    tags = dict(config.get("tags") or {})
    if request.tags:
        tags.update(request.tags)
    tags.setdefault("loom:owner", user.username or user.sub or "local")

    agent = Agent(
        arn=arn,
        runtime_id=runtime_id,
        name=request.name.strip(),
        description=(request.description or "").strip() or None,
        status="READY",
        region="local",
        account_id="local",
        source="local",
        deployment_status="deployed",
        protocol="HTTP",
        network_mode="PUBLIC",
    )
    agent.set_available_qualifiers(["DEFAULT"])
    agent.set_allowed_model_ids([str(m) for m in allowed])
    agent.set_tags(tags)
    db.add(agent)
    db.flush()

    db.add(ConfigEntry(
        agent_id=agent.id,
        key="AGENT_CONFIG_JSON",
        value=json.dumps(config),
        is_secret=False,
        source="env_var",
    ))
    db.commit()
    db.refresh(agent)
    logger.info(
        "Created local agent id=%s template=%s name=%s",
        agent.id,
        request.template_id,
        agent.name,
    )
    return _agent_response(agent, db)


@router.post("/{agent_id}/local-behavior", response_model=AgentResponse)
def update_local_agent_behavior(
    agent_id: int,
    request: LocalAgentBehaviorRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> AgentResponse:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.source != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="local-behavior is only supported for source=local agents",
        )

    entry = next((e for e in agent.config_entries if e.key == "AGENT_CONFIG_JSON"), None)
    if entry is None or not entry.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing AGENT_CONFIG_JSON")

    try:
        config = json.loads(entry.value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="invalid AGENT_CONFIG_JSON") from exc

    if request.reset_to_template:
        template_id = str(config.get("template_id") or "").strip()
        if not template_id:
            raise HTTPException(status_code=400, detail="agent has no template_id to reset")
        params = config.get("template_params") if isinstance(config.get("template_params"), dict) else {}
        try:
            refreshed = materialize_local_template(template_id, params=params)
        except LocalTemplateError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        config = refreshed
    elif request.system_prompt is not None:
        config["system_prompt"] = request.system_prompt
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide system_prompt or reset_to_template=true",
        )

    entry.value = json.dumps(config)
    db.commit()
    db.refresh(agent)
    return _agent_response(agent, db)
