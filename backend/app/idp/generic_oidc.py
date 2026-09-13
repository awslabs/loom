"""Generic, spec-compliant OIDC adapter. Used as the default for unknown provider types."""
from __future__ import annotations

from app.idp.base import BaseOidcAdapter, ProviderCapabilities


class GenericOidcAdapter(BaseOidcAdapter):
    provider_type = "generic_oidc"
    capabilities = ProviderCapabilities(
        authorization_code_pkce=True,
        refresh_token=True,
        idp_initiated_logout=True,
        requires_group_mapping=False,
    )
    default_group_claim = "groups"
