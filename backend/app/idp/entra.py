"""Microsoft Entra ID adapter."""
from __future__ import annotations

from app.idp.base import BaseOidcAdapter, IdpConfig, ProviderCapabilities


class EntraIdAdapter(BaseOidcAdapter):
    provider_type = "entra_id"
    capabilities = ProviderCapabilities(
        authorization_code_pkce=True,
        refresh_token=True,
        client_credentials=True,
        jwt_bearer_grant=True,
        idp_initiated_logout=True,
        requires_group_mapping=True,
    )
    default_group_claim = "roles"

    def expected_issuer(self, config: IdpConfig) -> str:
        """Azure AD v2.0 token endpoints issue access tokens carrying the v1.0 issuer."""
        issuer = config.issuer_url
        if "/v2.0" in issuer:
            tenant_id = issuer.rstrip("/").split("/")[-2]
            return f"https://sts.windows.net/{tenant_id}/"
        return issuer

    def token_exchange_params(
        self, config: IdpConfig, subject_token: str, audience: str
    ) -> dict[str, str] | None:
        return {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": subject_token,
            "requested_token_use": "on_behalf_of",
            "scope": audience,
        }
