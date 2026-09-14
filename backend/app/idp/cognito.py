"""Amazon Cognito adapter."""
from __future__ import annotations

import os
from typing import Any

from app.idp.base import BaseOidcAdapter, NormalizedIdentity, IdpConfig, ProviderCapabilities


class CognitoAdapter(BaseOidcAdapter):
    provider_type = "cognito"
    capabilities = ProviderCapabilities(
        authorization_code_pkce=True,
        refresh_token=True,
        password_grant=True,
        client_credentials=True,
        idp_initiated_logout=False,
        requires_group_mapping=False,
    )
    default_group_claim = "cognito:groups"

    def extract_identity(self, claims: dict[str, Any], config: IdpConfig) -> NormalizedIdentity:
        raw = self.raw_groups(claims, config)
        username = (
            claims.get("cognito:username")
            or claims.get("username")
            or claims.get("sub", "")
        )
        return NormalizedIdentity(
            sub=claims.get("sub", ""),
            username=username,
            groups=self.map_groups(raw, config),
            email=claims.get("email"),
            raw_claims=claims,
        )


def cognito_config_from_env() -> IdpConfig | None:
    """Build a Cognito config from environment variables, or None when unconfigured.

    This keeps the environment-driven Cognito deployment on the same code path as any
    registered provider. ``client_id`` is intentionally left empty so audience validation
    stays disabled for user tokens, matching the behaviour before the adapter refactor.
    """
    user_pool_id = os.getenv("LOOM_COGNITO_USER_POOL_ID", "").strip()
    if not user_pool_id:
        return None
    region = os.getenv("LOOM_COGNITO_REGION", os.getenv("AWS_REGION", "us-east-1"))
    issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
    return IdpConfig(
        provider_type="cognito",
        issuer_url=issuer,
        client_id="",
        name="cognito-env",
        jwks_uri=f"{issuer}/.well-known/jwks.json",
        group_claim_path="cognito:groups",
    )
