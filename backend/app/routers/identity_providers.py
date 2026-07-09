"""Identity Provider management endpoints."""
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes, invalidate_idp_cache
from app.models.identity_provider import IdentityProvider
from app.services.oidc import fetch_discovery, OIDCDiscoveryError
from app.services.secrets import store_secret, delete_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings/identity-providers", tags=["identity-providers"])


def _get_region() -> str:
    return os.getenv("AWS_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateIdPRequest(BaseModel):
    name: str
    provider_type: str = Field(..., description="cognito, entra_id, okta, auth0, generic_oidc")
    issuer_url: str
    client_id: str
    client_secret: str | None = None
    client_type: str = Field("public", description="'public' (PKCE only) or 'confidential' (backend proxies code exchange with secret)")
    scopes: str | None = None
    audience: str | None = None
    group_claim_path: str | None = Field(None, description="JWT claim for groups, e.g. 'groups', 'cognito:groups', 'roles'")
    group_mappings: dict[str, list[str]] | None = Field(None, description="Map external groups to Loom groups")
    status: str = "active"


class UpdateIdPRequest(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    issuer_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    client_type: str | None = None
    scopes: str | None = None
    audience: str | None = None
    group_claim_path: str | None = None
    group_mappings: dict[str, list[str]] | None = None
    status: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_discovery(idp: IdentityProvider) -> None:
    """Fetch OIDC discovery and update cached fields on the model."""
    try:
        disc = fetch_discovery(idp.issuer_url)
        idp.jwks_uri = disc["jwks_uri"]
        idp.authorization_endpoint = disc["authorization_endpoint"]
        idp.token_endpoint = disc["token_endpoint"]
        idp.discovery_scopes = json.dumps(disc.get("scopes_supported", []))
    except OIDCDiscoveryError:
        raise
    except Exception as e:
        raise OIDCDiscoveryError(f"Unexpected error during discovery: {e}") from e


def _enforce_single_active(db: Session, new_idp_id: int | None, new_status: str) -> None:
    """If setting an IdP to active, deactivate all others."""
    if new_status != "active":
        return
    query = db.query(IdentityProvider).filter(IdentityProvider.status == "active")
    if new_idp_id is not None:
        query = query.filter(IdentityProvider.id != new_idp_id)
    for other in query.all():
        other.status = "inactive"


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
def create_identity_provider(
    request: CreateIdPRequest,
    user: UserInfo = Depends(require_scopes("security:write")),
    db: Session = Depends(get_db),
) -> dict:
    existing = db.query(IdentityProvider).filter(IdentityProvider.name == request.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Identity provider with this name already exists")

    client_secret_arn = None
    if request.client_secret:
        region = _get_region()
        secret_name = f"loom/identity-providers/{request.name}/client-secret"
        try:
            client_secret_arn = store_secret(
                name=secret_name,
                secret_value=request.client_secret,
                region=region,
                description=f"Client secret for IdP '{request.name}'",
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to store client secret: {e}")

    idp = IdentityProvider(
        name=request.name,
        provider_type=request.provider_type,
        issuer_url=request.issuer_url,
        client_id=request.client_id,
        client_secret_arn=client_secret_arn,
        client_type=request.client_type,
        scopes=request.scopes,
        audience=request.audience,
        group_claim_path=request.group_claim_path,
        status=request.status,
    )
    if request.group_mappings:
        idp.set_group_mappings(request.group_mappings)

    # Run OIDC discovery to populate cached fields
    try:
        _run_discovery(idp)
    except OIDCDiscoveryError as e:
        raise HTTPException(status_code=422, detail=str(e))

    _enforce_single_active(db, None, idp.status)

    db.add(idp)
    db.commit()
    db.refresh(idp)
    invalidate_idp_cache()
    return idp.to_dict()


@router.get("")
def list_identity_providers(
    user: UserInfo = Depends(require_scopes("security:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    idps = db.query(IdentityProvider).order_by(IdentityProvider.id).all()
    return [idp.to_dict() for idp in idps]


@router.get("/{idp_id}")
def get_identity_provider(
    idp_id: int,
    user: UserInfo = Depends(require_scopes("security:read")),
    db: Session = Depends(get_db),
) -> dict:
    idp = db.query(IdentityProvider).filter(IdentityProvider.id == idp_id).first()
    if not idp:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    return idp.to_dict()


@router.put("/{idp_id}")
def update_identity_provider(
    idp_id: int,
    request: UpdateIdPRequest,
    user: UserInfo = Depends(require_scopes("security:write")),
    db: Session = Depends(get_db),
) -> dict:
    idp = db.query(IdentityProvider).filter(IdentityProvider.id == idp_id).first()
    if not idp:
        raise HTTPException(status_code=404, detail="Identity provider not found")

    rerun_discovery = False
    for field in ("name", "provider_type", "issuer_url", "client_id", "client_type", "scopes", "audience", "group_claim_path", "status"):
        value = getattr(request, field)
        if value is not None:
            if field == "issuer_url" and value != idp.issuer_url:
                rerun_discovery = True
            setattr(idp, field, value)

    if request.client_secret is not None:
        region = _get_region()
        secret_name = f"loom/identity-providers/{idp.name}/client-secret"
        try:
            client_secret_arn = store_secret(
                name=secret_name,
                secret_value=request.client_secret,
                region=region,
                description=f"Client secret for IdP '{idp.name}'",
            )
            idp.client_secret_arn = client_secret_arn
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to store client secret: {e}")

    if request.group_mappings is not None:
        idp.set_group_mappings(request.group_mappings)

    if rerun_discovery:
        try:
            _run_discovery(idp)
        except OIDCDiscoveryError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if request.status is not None:
        _enforce_single_active(db, idp.id, request.status)

    db.commit()
    db.refresh(idp)
    invalidate_idp_cache()
    return idp.to_dict()


@router.delete("/{idp_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_identity_provider(
    idp_id: int,
    user: UserInfo = Depends(require_scopes("security:write")),
    db: Session = Depends(get_db),
) -> None:
    idp = db.query(IdentityProvider).filter(IdentityProvider.id == idp_id).first()
    if not idp:
        raise HTTPException(status_code=404, detail="Identity provider not found")

    if idp.client_secret_arn:
        region = _get_region()
        delete_secret(idp.client_secret_arn, region)

    db.delete(idp)
    db.commit()
    invalidate_idp_cache()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

@router.get("/{idp_id}/discover")
def discover_identity_provider(
    idp_id: int,
    user: UserInfo = Depends(require_scopes("security:write")),
    db: Session = Depends(get_db),
) -> dict:
    """Re-fetch OIDC discovery metadata for an IdP."""
    idp = db.query(IdentityProvider).filter(IdentityProvider.id == idp_id).first()
    if not idp:
        raise HTTPException(status_code=404, detail="Identity provider not found")

    try:
        _run_discovery(idp)
    except OIDCDiscoveryError as e:
        raise HTTPException(status_code=422, detail=str(e))

    db.commit()
    db.refresh(idp)
    invalidate_idp_cache()
    return idp.to_dict()


@router.post("/test-discovery")
def test_discovery(
    body: dict,
    user: UserInfo = Depends(require_scopes("security:write")),
) -> dict:
    """Test OIDC discovery for a given issuer URL without saving anything."""
    issuer_url = body.get("issuer_url", "")
    if not issuer_url:
        raise HTTPException(status_code=400, detail="issuer_url is required")

    try:
        result = fetch_discovery(issuer_url)
        return {"status": "ok", **result}
    except OIDCDiscoveryError as e:
        return {"status": "error", "detail": str(e)}
