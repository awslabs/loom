"""OIDC discovery for a registered identity provider.

Shared by the provider CRUD router and the environment bootstrap so both cache the
same fields, including the internal JWKS rewrite that keeps validation working when
the browser and the backend reach the provider at different URLs.
"""
from __future__ import annotations

import json
import logging

from app.idp import IdpConfig, get_adapter
from app.services.oidc import OIDCDiscoveryError, fetch_discovery

logger = logging.getLogger(__name__)


def run_discovery(idp) -> None:
    """Fetch OIDC discovery and update the cached fields on an IdentityProvider instance."""
    config = IdpConfig.from_model(idp)
    adapter = get_adapter(idp.provider_type)
    base_url = adapter.discovery_base_url(config)

    try:
        disc = fetch_discovery(base_url)
    except OIDCDiscoveryError:
        raise
    except Exception as e:
        raise OIDCDiscoveryError(f"Unexpected error during discovery: {e}") from e

    jwks_uri = adapter.rewrite_jwks_uri(config, disc["jwks_uri"])
    if jwks_uri != disc["jwks_uri"]:
        logger.info(
            "Rewrote advertised JWKS URI %s to internal %s for provider %r",
            disc["jwks_uri"], jwks_uri, idp.name,
        )

    idp.jwks_uri = jwks_uri
    idp.authorization_endpoint = disc["authorization_endpoint"]
    idp.token_endpoint = disc["token_endpoint"]
    idp.end_session_endpoint = disc.get("end_session_endpoint")
    idp.discovery_scopes = json.dumps(disc.get("scopes_supported", []))
