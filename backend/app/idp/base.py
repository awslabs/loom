"""Provider-neutral identity contracts.

This module is the anti-corruption boundary between identity providers and the
rest of Loom. Everything downstream consumes ``NormalizedIdentity`` and never
sees a provider-specific claim name, issuer quirk, or grant type.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ProviderCapabilities:
    """What a provider supports, so call sites ask questions instead of comparing strings."""

    authorization_code_pkce: bool = True
    refresh_token: bool = False
    password_grant: bool = False
    client_credentials: bool = False
    rfc8693_token_exchange: bool = False
    jwt_bearer_grant: bool = False
    idp_initiated_logout: bool = False
    requires_group_mapping: bool = False

    def to_dict(self) -> dict[str, bool]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class NormalizedIdentity:
    """The only identity shape the rest of the backend consumes."""

    sub: str
    username: str
    groups: list[str]
    email: str | None = None
    raw_claims: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class IdpConfig:
    """Provider configuration, decoupled from its storage representation."""

    provider_type: str
    issuer_url: str
    client_id: str = ""
    id: int | None = None
    name: str | None = None
    audience: str | None = None
    jwks_uri: str | None = None
    group_claim_path: str | None = None
    group_mappings: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    internal_base_url: str | None = None
    client_type: str = "public"
    scopes: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    end_session_endpoint: str | None = None
    client_secret_arn: str | None = None
    refresh_enabled: bool | None = None

    @classmethod
    def from_model(cls, idp: Any) -> IdpConfig:
        """Build from an IdentityProvider ORM instance."""
        refresh_enabled = getattr(idp, "refresh_enabled", None)
        if isinstance(refresh_enabled, str):
            refresh_enabled = refresh_enabled.strip().lower() in ("1", "true", "yes")
        return cls(
            provider_type=idp.provider_type,
            issuer_url=idp.issuer_url,
            client_id=idp.client_id or "",
            id=idp.id,
            name=idp.name,
            audience=idp.audience,
            jwks_uri=idp.jwks_uri,
            group_claim_path=idp.group_claim_path,
            group_mappings=idp.get_group_mappings(),
            internal_base_url=getattr(idp, "internal_base_url", None),
            client_type=idp.client_type or "public",
            scopes=idp.scopes,
            authorization_endpoint=idp.authorization_endpoint,
            token_endpoint=idp.token_endpoint,
            end_session_endpoint=getattr(idp, "end_session_endpoint", None),
            client_secret_arn=idp.client_secret_arn,
            refresh_enabled=refresh_enabled,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdpConfig:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@runtime_checkable
class IdpAdapter(Protocol):
    provider_type: str
    capabilities: ProviderCapabilities

    def expected_issuer(self, config: IdpConfig) -> str: ...
    def discovery_base_url(self, config: IdpConfig) -> str: ...
    def expected_audience(self, config: IdpConfig) -> str | None: ...
    def rewrite_jwks_uri(self, config: IdpConfig, jwks_uri: str) -> str: ...
    def extract_identity(self, claims: dict[str, Any], config: IdpConfig) -> NormalizedIdentity: ...
    def logout_url(self, config: IdpConfig, post_logout_redirect_uri: str) -> str | None: ...
    def token_exchange_params(
        self, config: IdpConfig, subject_token: str, audience: str
    ) -> dict[str, str] | None: ...


class BaseOidcAdapter:
    """Spec-compliant OIDC behaviour. Adapters override only what their provider changes."""

    provider_type = "generic_oidc"
    capabilities = ProviderCapabilities(refresh_token=True)
    default_group_claim = "groups"

    def expected_issuer(self, config: IdpConfig) -> str:
        return config.issuer_url

    def discovery_base_url(self, config: IdpConfig) -> str:
        return config.internal_base_url or config.issuer_url

    def expected_audience(self, config: IdpConfig) -> str | None:
        return config.audience or config.client_id or None

    def rewrite_jwks_uri(self, config: IdpConfig, jwks_uri: str) -> str:
        """Point the JWKS URL at the internal base, since only this process fetches it.

        The discovery document advertises externally reachable endpoints because the
        provider derives them from its own configured hostname. Authorization and token
        endpoints must stay external (the browser uses them); JWKS must not.
        """
        internal = config.internal_base_url
        if not internal or not jwks_uri:
            return jwks_uri
        external = config.issuer_url.rstrip("/")
        if external and jwks_uri.startswith(external):
            return internal.rstrip("/") + jwks_uri[len(external):]
        parsed_internal = urlparse(internal)
        parsed_jwks = urlparse(jwks_uri)
        return urlunparse(
            (
                parsed_internal.scheme,
                parsed_internal.netloc,
                parsed_jwks.path,
                parsed_jwks.params,
                parsed_jwks.query,
                parsed_jwks.fragment,
            )
        )

    def group_claim(self, config: IdpConfig) -> str:
        return config.group_claim_path or self.default_group_claim

    def raw_groups(self, claims: dict[str, Any], config: IdpConfig) -> list[str]:
        value = claims.get(self.group_claim(config), [])
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(v) for v in value]
        return []

    def map_groups(self, raw_groups: list[str], config: IdpConfig) -> list[str]:
        if not config.group_mappings:
            return raw_groups
        mapped: list[str] = []
        for group in raw_groups:
            mapped.extend(config.group_mappings.get(group, []))
        return list(dict.fromkeys(mapped))

    def username(self, claims: dict[str, Any]) -> str:
        return (
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("name")
            or claims.get("sub", "")
        )

    def extract_identity(self, claims: dict[str, Any], config: IdpConfig) -> NormalizedIdentity:
        raw = self.raw_groups(claims, config)
        return NormalizedIdentity(
            sub=claims.get("sub", ""),
            username=self.username(claims),
            groups=self.map_groups(raw, config),
            email=claims.get("email") or claims.get("preferred_username"),
            raw_claims=claims,
        )

    def logout_url(self, config: IdpConfig, post_logout_redirect_uri: str) -> str | None:
        if not self.capabilities.idp_initiated_logout or not config.end_session_endpoint:
            return None
        from urllib.parse import urlencode

        params = {"post_logout_redirect_uri": post_logout_redirect_uri}
        if config.client_id:
            params["client_id"] = config.client_id
        return f"{config.end_session_endpoint}?{urlencode(params)}"

    def token_exchange_params(
        self, config: IdpConfig, subject_token: str, audience: str
    ) -> dict[str, str] | None:
        if not self.capabilities.rfc8693_token_exchange:
            return None
        return {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": subject_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": audience,
        }

    def supports_refresh(self, config: IdpConfig) -> bool:
        if config.refresh_enabled is not None:
            return config.refresh_enabled
        return self.capabilities.refresh_token

    def diagnose_validation_failure(self, token_claims: dict[str, Any], config: IdpConfig) -> None:
        """Hook for adapters to log actionable diagnostics on a rejected token."""
        return None
