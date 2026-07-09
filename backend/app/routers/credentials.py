"""Credential provider management endpoints."""
import json
import logging
import os
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.credential_provider import CredentialProvider
from app.routers.utils import get_agent_or_404
from app.services.credential import create_oauth2_credential_provider, delete_credential_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["credentials"])


class CredentialProviderCreateRequest(BaseModel):
    """Request body for creating a credential provider."""
    name: str = Field(..., description="Name for the credential provider")
    vendor: str = Field(..., description="Vendor name (e.g., 'CustomOAuth2')")
    client_id: str = Field(..., description="OAuth2 client ID")
    client_secret: str = Field(..., description="OAuth2 client secret")
    auth_server_url: str = Field(..., description="OAuth2 authorization server URL")
    scopes: list[str] = Field(default_factory=list, description="OAuth2 scopes")
    provider_type: Optional[str] = Field(None, description="Provider type: 'mcp_server', 'a2a', 'api_target'")


class CredentialProviderResponse(BaseModel):
    """Response model for credential provider details."""
    id: int
    agent_id: int
    name: str
    vendor: str | None
    callback_url: str | None
    scopes: list[str]
    provider_type: str | None
    created_at: str | None


@router.post(
    "/{agent_id}/credential-providers",
    response_model=CredentialProviderResponse,
    status_code=status.HTTP_201_CREATED
)
def create_credential_provider(
    agent_id: int,
    request: CredentialProviderCreateRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> CredentialProviderResponse:
    """Create a credential provider for an agent."""
    agent = get_agent_or_404(agent_id, db)

    # Call AgentCore API to create the OAuth2 credential provider
    callback_url = None
    try:
        response = create_oauth2_credential_provider(
            name=request.name,
            client_id=request.client_id,
            client_secret=request.client_secret,
            auth_server_url=request.auth_server_url,
            scopes=request.scopes,
            region=agent.region
        )
        callback_url = response.get("callbackUrl")
    except Exception as e:
        logger.error("Failed to create credential provider via AgentCore: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create credential provider: {str(e)}"
        )

    # Store in local DB
    provider = CredentialProvider(
        agent_id=agent_id,
        name=request.name,
        vendor=request.vendor,
        callback_url=callback_url,
        scopes=json.dumps(request.scopes),
        provider_type=request.provider_type,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)

    return CredentialProviderResponse(**provider.to_dict())


@router.get("/{agent_id}/credential-providers", response_model=List[CredentialProviderResponse])
def list_credential_providers(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> List[CredentialProviderResponse]:
    """List all credential providers for an agent."""
    get_agent_or_404(agent_id, db)
    providers = db.query(CredentialProvider).filter(
        CredentialProvider.agent_id == agent_id
    ).all()
    return [CredentialProviderResponse(**p.to_dict()) for p in providers]


@router.delete(
    "/{agent_id}/credential-providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_credential_provider_endpoint(
    agent_id: int,
    provider_id: int,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> None:
    """Delete a credential provider."""
    agent = get_agent_or_404(agent_id, db)
    provider = db.query(CredentialProvider).filter(
        CredentialProvider.id == provider_id,
        CredentialProvider.agent_id == agent_id
    ).first()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential provider with ID {provider_id} not found for agent {agent_id}"
        )

    # Delete from AgentCore
    try:
        delete_credential_provider(provider.name, agent.region)
    except Exception as e:
        logger.warning("Failed to delete credential provider from AgentCore: %s", e)

    db.delete(provider)
    db.commit()
