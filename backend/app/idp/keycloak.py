"""Keycloak adapter."""
from __future__ import annotations

import logging
from typing import Any

from app.idp.base import BaseOidcAdapter, NormalizedIdentity, IdpConfig, ProviderCapabilities

logger = logging.getLogger(__name__)


class KeycloakAdapter(BaseOidcAdapter):
    provider_type = "keycloak"
    capabilities = ProviderCapabilities(
        authorization_code_pkce=True,
        refresh_token=True,
        client_credentials=True,
        rfc8693_token_exchange=True,
        idp_initiated_logout=True,
        requires_group_mapping=False,
    )
    default_group_claim = "groups"

    def extract_identity(self, claims: dict[str, Any], config: IdpConfig) -> NormalizedIdentity:
        raw = self.raw_groups(claims, config)
        if any(group.startswith("/") for group in raw):
            logger.warning(
                "Keycloak groups arrived as full paths (%s). Loom group names carry no leading "
                "slash, so these resolve to no scopes. Set 'full.path' to false on the group "
                "membership mapper of client %r.",
                raw,
                config.client_id,
            )
        return super().extract_identity(claims, config)

    def diagnose_validation_failure(self, token_claims: dict[str, Any], config: IdpConfig) -> None:
        expected = self.expected_audience(config)
        audience = token_claims.get("aud")
        if expected and audience is not None:
            audiences = [audience] if isinstance(audience, str) else list(audience)
            if expected not in audiences:
                logger.error(
                    "Keycloak token audience %s does not contain %r. Add an 'audience' protocol "
                    "mapper to client %r with access.token.claim enabled, or set the IdP's "
                    "audience field to match. Keycloak does not put the client ID in 'aud' by "
                    "default (it uses 'azp': %r).",
                    audiences,
                    expected,
                    config.client_id,
                    token_claims.get("azp"),
                )
        if self.group_claim(config) not in token_claims:
            logger.error(
                "Keycloak token has no %r claim. Add a group membership mapper to client %r with "
                "both access.token.claim and id.token.claim enabled.",
                self.group_claim(config),
                config.client_id,
            )
