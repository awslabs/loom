"""Authentication dependencies for FastAPI routes."""
import dataclasses
import logging
import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import OAuth2AuthorizationCodeBearer, SecurityScopes

from app.idp import IdpConfig, cognito_config_from_env, get_adapter
from app.services.jwt_validator import validate_token

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local-dev auth bypass (fail-closed by default)
# ---------------------------------------------------------------------------
# Historically, the absence of Cognito/IdP config silently granted every
# request super-admin — including requests with no Authorization header —
# which is an open admin panel on any deployment that forgets to wire up an
# IdP. Bypass now requires an explicit opt-in and is further restricted to
# requests arriving from loopback, so it can't be reached over a network
# even if the env var is set in a deployed environment by mistake.
LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV = "LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV"
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _bypass_auth_enabled() -> bool:
    return os.getenv(LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV, "").strip().lower() in ("1", "true", "yes")


def _is_loopback_request(request: Request) -> bool:
    client = request.client
    return bool(client) and client.host in _LOOPBACK_HOSTS


# ---------------------------------------------------------------------------
# Group-to-scope mapping (must match frontend GROUP_SCOPES)
# ---------------------------------------------------------------------------
# Users belong to two dimensions:
# - Type (t-*): Defines UI view (t-admin or t-user). Type groups grant no scopes.
# - Group (g-*): Defines page visibility and resource access. Groups grant scopes.
#
# Admin users (t-admin): Must have exactly ONE g-admins-* group
# User users (t-user): Must have at least ONE g-users-* group (can have multiple)
GROUP_SCOPES: dict[str, list[str]] = {
    # Type groups (for UI routing - don't grant scopes directly)
    "t-admin": [],
    "t-user": [],

    # Admin groups (t-admin users - single group only)
    "g-admins-super": [
        "catalog:read", "catalog:write", "agent:read", "agent:write",
        "memory:read", "memory:write", "security:read", "security:write",
        "settings:read", "settings:write", "tagging:read", "tagging:write",
        "costs:read", "costs:write",
        "mcp:read", "mcp:write", "a2a:read", "a2a:write",
        "registry:read", "registry:write",
        "invoke", "admin:read", "admin:write",
    ],
    "g-admins-demo": [
        "catalog:read", "agent:read", "agent:write", "memory:read", "memory:write",
        "security:read", "settings:read", "settings:write", "tagging:read", "costs:read", "costs:write",
        "mcp:read", "mcp:write", "a2a:read", "a2a:write",
        "registry:read", "registry:write",
        "invoke",
    ],
    "g-admins-security": [
        "security:read", "security:write", "settings:read", "settings:write", "tagging:read",
    ],
    "g-admins-memory": [
        "memory:read", "memory:write", "settings:read", "settings:write", "tagging:read",
    ],
    "g-admins-mcp": [
        "mcp:read", "mcp:write", "settings:read", "settings:write", "tagging:read",
    ],
    "g-admins-a2a": [
        "a2a:read", "a2a:write", "settings:read", "settings:write", "tagging:read",
    ],
    "g-admins-registry": [
        "mcp:read", "a2a:read", "registry:read", "registry:write", "settings:read", "settings:write", "tagging:read",
    ],

    # User groups (t-user users - can have multiple)
    "g-users-demo": ["agent:read", "memory:read", "mcp:read", "invoke"],
    "g-users-test": ["agent:read", "memory:read", "mcp:read", "invoke"],
    "g-users-strategics": ["agent:read", "memory:read", "mcp:read", "invoke"],
}

ALL_SCOPES: set[str] = {s for scopes in GROUP_SCOPES.values() for s in scopes}

# ---------------------------------------------------------------------------
# OAuth2 scheme for OpenAPI docs
# ---------------------------------------------------------------------------
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="",
    tokenUrl="",
    scopes={
        "catalog:read": "Read catalog",
        "catalog:write": "Write catalog",
        "agent:read": "Read agents",
        "agent:write": "Write agents",
        "memory:read": "Read memory",
        "memory:write": "Write memory",
        "security:read": "Read security",
        "security:write": "Write security",
        "settings:read": "Read settings",
        "settings:write": "Write settings",
        "tagging:read": "View tag policies and profiles",
        "tagging:write": "Manage tag policies and profiles",
        "costs:read": "View cost data",
        "costs:write": "Manage cost settings",
        "mcp:read": "Read MCP",
        "mcp:write": "Write MCP",
        "a2a:read": "Read A2A",
        "a2a:write": "Write A2A",
        "registry:read": "View registry records",
        "registry:write": "Manage registry records",
        "admin:read": "View admin dashboard",
        "admin:write": "Manage admin settings",
        "invoke": "Invoke agents",
    },
    auto_error=False,
)

# ---------------------------------------------------------------------------
# UserInfo dataclass
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class UserInfo:
    sub: str
    username: str
    groups: list[str]
    scopes: set[str]
    idp_type: str = "cognito"

    @property
    def actor_id(self) -> str:
        """Return a provider:sub formatted actor ID safe for AWS APIs.

        AWS requires: [a-zA-Z0-9][a-zA-Z0-9-_/]*(?::[a-zA-Z0-9-_/]+)*
        Characters outside that set (e.g. '@', '.') are replaced with '_'.
        """
        import re as _re
        if not self.sub:
            return "loom-agent"
        raw = f"{self.idp_type}:{self.sub}"
        return _re.sub(r"[^a-zA-Z0-9:_/\-]", "_", raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def derive_scopes(groups: list[str]) -> set[str]:
    """Return the union of all scopes for the given groups."""
    result: set[str] = set()
    for group in groups:
        result.update(GROUP_SCOPES.get(group, []))
    return result


def _map_external_groups(external_groups: list[str], group_mappings: dict[str, list[str]]) -> list[str]:
    """Map external IdP group names to Loom internal groups using the IdP's mapping table."""
    loom_groups: list[str] = []
    for ext_group in external_groups:
        mapped = group_mappings.get(ext_group, [])
        loom_groups.extend(mapped)
    return list(dict.fromkeys(loom_groups))


def _get_active_idp():
    """Load the active IdP from the database, if any. Returns None if no active IdP."""
    try:
        from app.db import SessionLocal
        from app.models.identity_provider import IdentityProvider
        db = SessionLocal()
        try:
            idp = db.query(IdentityProvider).filter(IdentityProvider.status == "active").first()
            if idp:
                return IdpConfig.from_model(idp).to_dict()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to load active IdP: %s", e)
    return None


# Cache active IdP config for 60 seconds to avoid DB hit on every request
_idp_cache: dict[str, tuple[dict | None, float]] = {}
_IDP_CACHE_TTL = 60


def _get_active_idp_cached() -> dict | None:
    import time
    now = time.time()
    cached = _idp_cache.get("active")
    if cached and cached[1] > now:
        return cached[0]
    idp = _get_active_idp()
    _idp_cache["active"] = (idp, now + _IDP_CACHE_TTL)
    return idp


def invalidate_idp_cache() -> None:
    """Clear the cached active IdP. Call after IdP create/update/delete."""
    _idp_cache.pop("active", None)


def get_active_config() -> IdpConfig | None:
    """Return the configuration of the active provider: the registered one, else Cognito from env."""
    cached = _get_active_idp_cached()
    if cached:
        return IdpConfig.from_dict(cached)
    return cognito_config_from_env()


def _validate_with_config(token: str, config: IdpConfig) -> dict[str, Any]:
    """Validate a token against one provider configuration. Raises on failure."""
    adapter = get_adapter(config.provider_type)
    if not config.jwks_uri:
        raise ValueError(f"Provider {config.provider_type!r} has no cached jwks_uri; run discovery")
    try:
        return validate_token(
            token,
            jwks_uri=config.jwks_uri,
            issuer=adapter.expected_issuer(config),
            audience=adapter.expected_audience(config),
        )
    except Exception:
        _diagnose(token, config)
        raise


def _diagnose(token: str, config: IdpConfig) -> None:
    """Let the adapter explain a rejected token, using unverified claims."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
    except Exception:
        return
    try:
        get_adapter(config.provider_type).diagnose_validation_failure(claims, config)
    except Exception:  # pragma: no cover - diagnostics must never mask the original error
        logger.debug("Provider diagnostics failed", exc_info=True)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_user(request: Request) -> UserInfo:
    """Extract and validate the Bearer token, returning a UserInfo with derived scopes.

    Provider-neutral: the registered provider is tried first, then Cognito from the
    environment, and each one is validated and interpreted by its own adapter.
    In bypass mode (no provider configured at all) returns a user with all scopes, but
    ONLY when LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV is set AND the request arrives from
    loopback. Fails closed (401) otherwise, since an IdP-less deployment reachable over
    the network would otherwise be an open admin panel.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""

    registered = _get_active_idp_cached()
    registered_config = IdpConfig.from_dict(registered) if registered else None
    cognito_config = cognito_config_from_env()

    # Bypass mode — no provider configured at all. Requires explicit opt-in and a
    # loopback client; otherwise fail closed with 401.
    if not registered_config and not cognito_config:
        if _bypass_auth_enabled() and _is_loopback_request(request):
            logger.warning("No identity provider configured; bypassing auth for loopback request")
            return UserInfo(
                sub="local",
                username="local-dev",
                groups=["t-admin", "g-admins-super"],
                scopes=ALL_SCOPES.copy(),
                idp_type="local",
            )
        logger.error(
            "No identity provider configured and auth bypass not enabled "
            "(set %s=true for local dev); rejecting request",
            LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV,
        )
        raise HTTPException(status_code=401, detail="No identity provider configured")

    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    candidates = [c for c in (registered_config, cognito_config) if c is not None]
    last_error: Exception | None = None
    for config in candidates:
        try:
            claims = _validate_with_config(token, config)
        except Exception as e:
            last_error = e
            logger.warning(
                "Token validation failed for provider %r (issuer=%s): %s",
                config.provider_type, config.issuer_url, e,
            )
            continue
        identity = get_adapter(config.provider_type).extract_identity(claims, config)
        return UserInfo(
            sub=identity.sub,
            username=identity.username,
            groups=identity.groups,
            scopes=derive_scopes(identity.groups),
            idp_type=config.provider_type,
        )

    raise HTTPException(status_code=401, detail="Invalid or expired token") from last_error


def require_scopes(*required: str):
    """Create a dependency that checks the user has ALL required scopes.

    Uses Security() with the oauth2_scheme so that required scopes appear
    in the OpenAPI specification for each endpoint.
    """
    def checker(
        security_scopes: SecurityScopes = Security(oauth2_scheme, scopes=list(required)),
        user: UserInfo = Depends(get_current_user),
    ) -> UserInfo:
        for scope in required:
            if scope not in user.scopes:
                raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")
        return user
    return checker


# ---------------------------------------------------------------------------
# Legacy helpers (used by invocations.py for token forwarding)
# ---------------------------------------------------------------------------

def _validate_against_any_provider(token: str) -> dict[str, Any] | None:
    """Validate a token against every configured provider in priority order."""
    registered = _get_active_idp_cached()
    candidates = [c for c in (
        IdpConfig.from_dict(registered) if registered else None,
        cognito_config_from_env(),
    ) if c is not None]

    for config in candidates:
        try:
            return _validate_with_config(token, config)
        except Exception as e:
            logger.warning("Token validation failed for provider %r: %s", config.provider_type, e)
    return None


def get_current_user_token(request: Request) -> str | None:
    """Extract and validate the user's access token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]

    if not _get_active_idp_cached() and not cognito_config_from_env():
        logger.warning("No identity provider configured; skipping token validation")
        return token

    claims = _validate_against_any_provider(token)
    if claims is None:
        return None
    logger.debug("Validated user token for sub=%s", claims.get("sub"))
    return token


def get_token_claims(request: Request) -> dict[str, Any] | None:
    """Extract, validate, and decode the user's access token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    return _validate_against_any_provider(auth_header[7:])
