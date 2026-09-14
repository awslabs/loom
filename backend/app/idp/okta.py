"""Okta adapter."""
from __future__ import annotations

from app.idp.base import BaseOidcAdapter, ProviderCapabilities


class OktaAdapter(BaseOidcAdapter):
    provider_type = "okta"
    capabilities = ProviderCapabilities(
        authorization_code_pkce=True,
        refresh_token=True,
        client_credentials=True,
        rfc8693_token_exchange=True,
        idp_initiated_logout=True,
        requires_group_mapping=False,
    )
    default_group_claim = "groups"
