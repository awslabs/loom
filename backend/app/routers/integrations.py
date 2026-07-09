"""Integration management endpoints."""
import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.integration import Integration
from app.routers.utils import get_agent_or_404
from app.services.iam import update_role_policy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["integrations"])


class IntegrationCreateRequest(BaseModel):
    """Request body for creating an integration."""
    integration_type: str = Field(..., description="Type: 's3', 'bedrock', 'lambda', 'dynamodb', 'sqs', 'sns'")
    integration_config: dict = Field(default_factory=dict, description="Integration-specific configuration")
    credential_provider_id: Optional[int] = Field(None, description="Associated credential provider ID")


class IntegrationUpdateRequest(BaseModel):
    """Request body for updating an integration."""
    integration_config: Optional[dict] = Field(None, description="Updated configuration")
    credential_provider_id: Optional[int] = Field(None, description="Updated credential provider ID")
    enabled: Optional[bool] = Field(None, description="Enable or disable the integration")


class IntegrationResponse(BaseModel):
    """Response model for integration details."""
    id: int
    agent_id: int
    integration_type: str | None
    integration_config: dict
    credential_provider_id: int | None
    enabled: bool
    created_at: str | None
    updated_at: str | None


def _sync_role_policy(agent: Agent, db: Session) -> None:
    """Update the agent's IAM role policy based on current enabled integrations."""
    if not agent.execution_role_arn:
        return

    role_name = agent.execution_role_arn.split("/")[-1]
    enabled_integrations = db.query(Integration).filter(
        Integration.agent_id == agent.id,
        Integration.enabled == True
    ).all()

    integration_dicts = [
        {
            "integration_type": i.integration_type,
            "integration_config": i.integration_config or "{}"
        }
        for i in enabled_integrations
    ]

    try:
        update_role_policy(
            role_name=role_name,
            integrations=integration_dicts,
            region=agent.region,
            account_id=agent.account_id,
            agent_name=agent.name or ""
        )
    except Exception as e:
        logger.error("Failed to update IAM role policy for agent %s: %s", agent.id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to update IAM role policy: {str(e)}"
        )


@router.post(
    "/{agent_id}/integrations",
    response_model=IntegrationResponse,
    status_code=status.HTTP_201_CREATED
)
def create_integration(
    agent_id: int,
    request: IntegrationCreateRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> IntegrationResponse:
    """Add an integration to an agent."""
    agent = get_agent_or_404(agent_id, db)

    integration = Integration(
        agent_id=agent_id,
        integration_type=request.integration_type,
        integration_config=json.dumps(request.integration_config),
        credential_provider_id=request.credential_provider_id,
        enabled=True,
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)

    _sync_role_policy(agent, db)

    return IntegrationResponse(**integration.to_dict())


@router.get("/{agent_id}/integrations", response_model=List[IntegrationResponse])
def list_integrations(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> List[IntegrationResponse]:
    """List all integrations for an agent."""
    get_agent_or_404(agent_id, db)
    integrations = db.query(Integration).filter(
        Integration.agent_id == agent_id
    ).all()
    return [IntegrationResponse(**i.to_dict()) for i in integrations]


@router.put("/{agent_id}/integrations/{integration_id}", response_model=IntegrationResponse)
def update_integration(
    agent_id: int,
    integration_id: int,
    request: IntegrationUpdateRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> IntegrationResponse:
    """Update an integration."""
    agent = get_agent_or_404(agent_id, db)
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.agent_id == agent_id
    ).first()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration with ID {integration_id} not found for agent {agent_id}"
        )

    if request.integration_config is not None:
        integration.integration_config = json.dumps(request.integration_config)
    if request.credential_provider_id is not None:
        integration.credential_provider_id = request.credential_provider_id
    if request.enabled is not None:
        integration.enabled = request.enabled

    db.commit()
    db.refresh(integration)

    _sync_role_policy(agent, db)

    return IntegrationResponse(**integration.to_dict())


@router.delete(
    "/{agent_id}/integrations/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_integration(
    agent_id: int,
    integration_id: int,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> None:
    """Delete an integration from an agent."""
    agent = get_agent_or_404(agent_id, db)
    integration = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.agent_id == agent_id
    ).first()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration with ID {integration_id} not found for agent {agent_id}"
        )

    db.delete(integration)
    db.commit()

    _sync_role_policy(agent, db)
