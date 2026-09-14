"""Auth0 adapter."""
from __future__ import annotations

from app.idp.base import BaseOidcAdapter, ProviderCapabilities


class Auth0Adapter(BaseOidcAdapter):
    provider_type = "auth0"
    capabilities = ProviderCapabilities(
        authorization_code_pkce=True,
        refresh_token=True,
        client_credentials=True,
        idp_initiated_logout=True,
        requires_group_mapping=True,
    )
    default_group_claim = "groups"
