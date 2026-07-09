"""Authentication configuration endpoints."""
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.auth import UserInfo, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
def get_auth_config() -> dict:
    """Return authentication configuration for the frontend.

    Returns the active IdP configuration if one exists, otherwise falls back to Cognito.
    """
    region = os.getenv("LOOM_COGNITO_REGION", os.getenv("AWS_REGION", "us-east-1"))
    user_pool_id = os.getenv("LOOM_COGNITO_USER_POOL_ID", "")

    # Check for an active external IdP
    try:
        from app.db import SessionLocal
        from app.models.identity_provider import IdentityProvider
        db = SessionLocal()
        try:
            idp = db.query(IdentityProvider).filter(IdentityProvider.status == "active").first()
            if idp:
                return {
                    "provider_type": idp.provider_type,
                    "authorization_endpoint": idp.authorization_endpoint,
                    "token_endpoint": idp.token_endpoint,
                    "client_id": idp.client_id,
                    "scopes": idp.scopes or "",
                    "issuer_url": idp.issuer_url,
                    "redirect_uri": os.getenv("LOOM_OIDC_REDIRECT_URI", ""),
                    "group_claim_path": idp.group_claim_path or "groups",
                    "group_mappings": idp.get_group_mappings(),
                    "has_client_secret": bool(idp.client_secret_arn),
                    "client_type": idp.client_type or ("confidential" if idp.client_secret_arn else "public"),
                    # Backward compat
                    "user_pool_id": user_pool_id,
                    "region": region,
                }
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to check for active IdP: %s", e)

    # Default: Cognito
    return {
        "provider_type": "cognito",
        "user_pool_id": user_pool_id,
        "region": region,
    }


@router.get("/me")
def get_current_user_info(user: UserInfo = Depends(get_current_user)) -> dict:
    """Return the backend-resolved identity for the current token."""
    return {
        "username": user.username,
        "sub": user.sub,
        "groups": user.groups,
    }


class TokenExchangeRequest(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str


@router.post("/token")
def exchange_token(request: TokenExchangeRequest) -> dict:
    """Proxy the authorization code exchange to the IdP's token endpoint.

    This allows the backend to include the client_secret (which should not
    be exposed to the browser) when exchanging the authorization code.
    """
    from app.db import SessionLocal
    from app.models.identity_provider import IdentityProvider

    db = SessionLocal()
    try:
        idp = db.query(IdentityProvider).filter(IdentityProvider.status == "active").first()
        if not idp or not idp.token_endpoint:
            raise HTTPException(status_code=400, detail="No active IdP with token endpoint configured")

        params = {
            "grant_type": "authorization_code",
            "client_id": idp.client_id,
            "code": request.code,
            "redirect_uri": request.redirect_uri,
            "code_verifier": request.code_verifier,
        }

        if idp.client_secret_arn:
            from app.services.secrets import get_secret
            region = os.getenv("AWS_REGION", "us-east-1")
            client_secret = get_secret(idp.client_secret_arn, region)
            if client_secret:
                params["client_secret"] = client_secret

        resp = httpx.post(
            idp.token_endpoint,
            data=params,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("Token exchange failed (HTTP %d): %s", resp.status_code, resp.text)
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        return resp.json()
    finally:
        db.close()
