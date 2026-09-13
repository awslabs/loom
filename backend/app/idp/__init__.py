"""Identity provider adapters.

Adding a provider means adding one adapter here and one descriptor in
``frontend/src/auth/providers``. No authorization logic, router, or UI component
should ever branch on a provider type.
"""
from __future__ import annotations

from app.idp.auth0 import Auth0Adapter
from app.idp.base import (
    BaseOidcAdapter,
    IdpAdapter,
    IdpConfig,
    NormalizedIdentity,
    ProviderCapabilities,
)
from app.idp.cognito import CognitoAdapter, cognito_config_from_env
from app.idp.entra import EntraIdAdapter
from app.idp.generic_oidc import GenericOidcAdapter
from app.idp.keycloak import KeycloakAdapter
from app.idp.okta import OktaAdapter

_ADAPTER_CLASSES = (
    KeycloakAdapter,
    CognitoAdapter,
    EntraIdAdapter,
    OktaAdapter,
    Auth0Adapter,
    GenericOidcAdapter,
)

ADAPTERS: dict[str, BaseOidcAdapter] = {cls.provider_type: cls() for cls in _ADAPTER_CLASSES}

#: Provider types accepted when registering an identity provider.
SUPPORTED_PROVIDER_TYPES = tuple(ADAPTERS.keys())

_DEFAULT_ADAPTER = ADAPTERS["generic_oidc"]


def get_adapter(provider_type: str | None) -> BaseOidcAdapter:
    """Return the adapter for a provider type, falling back to generic OIDC."""
    if not provider_type:
        return _DEFAULT_ADAPTER
    return ADAPTERS.get(provider_type, _DEFAULT_ADAPTER)


__all__ = [
    "ADAPTERS",
    "SUPPORTED_PROVIDER_TYPES",
    "Auth0Adapter",
    "BaseOidcAdapter",
    "CognitoAdapter",
    "EntraIdAdapter",
    "GenericOidcAdapter",
    "IdpAdapter",
    "IdpConfig",
    "KeycloakAdapter",
    "NormalizedIdentity",
    "OktaAdapter",
    "ProviderCapabilities",
    "cognito_config_from_env",
    "get_adapter",
]
