"""Authentication configuration endpoints."""
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.auth import UserInfo, get_current_user
from app.idp import IdpConfig, get_adapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _load_active_idp():
    """Return the active IdentityProvider row, or None. Never raises."""
    try:
        from app.db import SessionLocal
        from app.models.identity_provider import IdentityProvider
        db = SessionLocal()
        try:
            return db.query(IdentityProvider).filter(IdentityProvider.status == "active").first()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to check for active IdP: %s", e)
        return None


def _client_secret(idp) -> str | None:
    if not idp.client_secret_arn:
        return None
    from app.services.secrets import get_secret
    region = os.getenv("AWS_REGION", "us-east-1")
    return get_secret(idp.client_secret_arn, region)


@router.get("/config")
def get_auth_config() -> dict:
    """Return authentication configuration for the frontend.

    Returns the active IdP configuration if one exists, otherwise falls back to Cognito.
    Provider capabilities are included so the frontend can decide what to render and
    whether to refresh, instead of comparing the provider type to string literals.
    """
    region = os.getenv("LOOM_COGNITO_REGION", os.getenv("AWS_REGION", "us-east-1"))
    user_pool_id = os.getenv("LOOM_COGNITO_USER_POOL_ID", "")

    idp = _load_active_idp()
    if idp:
        config = IdpConfig.from_model(idp)
        adapter = get_adapter(config.provider_type)
        return {
            "provider_type": config.provider_type,
            "authorization_endpoint": config.authorization_endpoint,
            "token_endpoint": config.token_endpoint,
            "end_session_endpoint": config.end_session_endpoint,
            "client_id": config.client_id,
            "scopes": config.scopes or "",
            "issuer_url": config.issuer_url,
            "redirect_uri": os.getenv("LOOM_OIDC_REDIRECT_URI", ""),
            "group_claim_path": adapter.group_claim(config),
            "group_mappings": config.group_mappings,
            "has_client_secret": bool(config.client_secret_arn),
            "client_type": config.client_type or ("confidential" if config.client_secret_arn else "public"),
            "capabilities": adapter.capabilities.to_dict(),
            "supports_refresh": adapter.supports_refresh(config),
            # Backward compat
            "user_pool_id": user_pool_id,
            "region": region,
        }

    # Default: Cognito
    cognito_adapter = get_adapter("cognito")
    return {
        "provider_type": "cognito",
        "user_pool_id": user_pool_id,
        "region": region,
        "capabilities": cognito_adapter.capabilities.to_dict(),
        "supports_refresh": cognito_adapter.capabilities.refresh_token,
    }


@router.get("/me")
def get_current_user_info(user: UserInfo = Depends(get_current_user)) -> dict:
    """Return the backend-resolved identity for the current token."""
    return {
        "username": user.username,
        "sub": user.sub,
        "groups": user.groups,
        "scopes": sorted(user.scopes),
        "idp_type": user.idp_type,
    }


class TokenExchangeRequest(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


def _post_to_token_endpoint(idp, params: dict[str, str]) -> dict:
    """POST form-encoded params to the provider's token endpoint and return the JSON body."""
    resp = httpx.post(
        idp.token_endpoint,
        data=params,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=10,
    )
    if resp.status_code != 200:
        logger.warning("Token endpoint call failed (HTTP %d): %s", resp.status_code, resp.text)
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@router.post("/token")
def exchange_token(request: TokenExchangeRequest) -> dict:
    """Proxy the authorization code exchange to the IdP's token endpoint.

    This allows the backend to include the client_secret (which should not
    be exposed to the browser) when exchanging the authorization code.
    """
    idp = _load_active_idp()
    if not idp or not idp.token_endpoint:
        raise HTTPException(status_code=400, detail="No active IdP with token endpoint configured")

    params = {
        "grant_type": "authorization_code",
        "client_id": idp.client_id,
        "code": request.code,
        "redirect_uri": request.redirect_uri,
        "code_verifier": request.code_verifier,
    }
    secret = _client_secret(idp)
    if secret:
        params["client_secret"] = secret

    return _post_to_token_endpoint(idp, params)


@router.post("/refresh")
def refresh_token(request: RefreshTokenRequest) -> dict:
    """Exchange a refresh token for a new access token at the active provider.

    Providers that rotate refresh tokens return a new one in the response; callers must
    replace the token they stored.
    """
    idp = _load_active_idp()
    if not idp or not idp.token_endpoint:
        raise HTTPException(status_code=400, detail="No active IdP with token endpoint configured")

    config = IdpConfig.from_model(idp)
    adapter = get_adapter(config.provider_type)
    if not adapter.supports_refresh(config):
        raise HTTPException(
            status_code=400,
            detail=f"Provider {config.provider_type!r} does not support refresh tokens",
        )

    params = {
        "grant_type": "refresh_token",
        "client_id": idp.client_id,
        "refresh_token": request.refresh_token,
    }
    secret = _client_secret(idp)
    if secret:
        params["client_secret"] = secret

    return _post_to_token_endpoint(idp, params)
