"""Authentication dependencies for FastAPI routes."""
import dataclasses
import logging
import os
from typing import Any

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import OAuth2AuthorizationCodeBearer, SecurityScopes

from app.services.jwt_validator import validate_cognito_token, validate_token

logger = logging.getLogger(__name__)

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
    """Load the active external IdP from the database, if any. Returns None if no active IdP."""
    try:
        from app.db import SessionLocal
        from app.models.identity_provider import IdentityProvider
        db = SessionLocal()
        try:
            idp = db.query(IdentityProvider).filter(IdentityProvider.status == "active").first()
            if idp:
                return {
                    "id": idp.id,
                    "provider_type": idp.provider_type,
                    "issuer_url": idp.issuer_url,
                    "client_id": idp.client_id,
                    "audience": idp.audience,
                    "jwks_uri": idp.jwks_uri,
                    "group_claim_path": idp.group_claim_path,
                    "group_mappings": idp.get_group_mappings(),
                }
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


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_user(request: Request) -> UserInfo:
    """Extract and validate the Bearer token, returning a UserInfo with derived scopes.

    Checks for an active external IdP first. Falls back to Cognito.
    In bypass mode (LOOM_COGNITO_USER_POOL_ID not set and no active IdP) returns a user with all scopes.
    """
    user_pool_id = os.getenv("LOOM_COGNITO_USER_POOL_ID", "")
    region = os.getenv("LOOM_COGNITO_REGION", os.getenv("AWS_REGION", "us-east-1"))

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""

    # Check for active external IdP
    active_idp = _get_active_idp_cached()

    # Bypass mode — no Cognito and no external IdP configured
    if not user_pool_id and not active_idp:
        logger.warning("No identity provider configured; bypassing auth")
        return UserInfo(
            sub="local",
            username="local-dev",
            groups=["t-admin", "g-admins-super"],
            scopes=ALL_SCOPES.copy(),
            idp_type="local",
        )

    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    # Try external IdP first if active
    if active_idp and active_idp.get("jwks_uri"):
        try:
            issuer = active_idp["issuer_url"]
            # Azure AD v2.0 token endpoint issues access tokens with v1.0 issuer
            if active_idp.get("provider_type") == "entra_id" and "/v2.0" in issuer:
                tid = issuer.split("/")[-2]
                issuer = f"https://sts.windows.net/{tid}/"
            claims = validate_token(
                token,
                jwks_uri=active_idp["jwks_uri"],
                issuer=issuer,
                audience=active_idp.get("audience") or active_idp.get("client_id"),
            )
            return _build_user_from_external_claims(claims, active_idp)
        except Exception as e:
            logger.warning("External IdP validation failed (jwks_uri=%s, issuer=%s, audience=%s): %s",
                           active_idp["jwks_uri"], issuer,
                           active_idp.get("audience") or active_idp.get("client_id"), e)
            # Fall through to Cognito if external validation fails
            if not user_pool_id:
                raise HTTPException(status_code=401, detail="Invalid or expired token") from e

    # Cognito validation
    try:
        claims = validate_cognito_token(token, user_pool_id, region)
    except Exception as e:
        logger.warning("Invalid token: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from e

    groups: list[str] = claims.get("cognito:groups", [])
    username: str = claims.get("cognito:username", claims.get("username", claims.get("sub", "")))

    return UserInfo(
        sub=claims.get("sub", ""),
        username=username,
        groups=groups,
        scopes=derive_scopes(groups),
    )


def _build_user_from_external_claims(claims: dict[str, Any], idp: dict) -> UserInfo:
    """Build a UserInfo from external IdP JWT claims using the IdP's group mapping."""
    sub = claims.get("sub", "")
    username = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("name")
        or sub
    )

    # Extract groups using the configured claim path
    group_claim = idp.get("group_claim_path", "groups")
    external_groups = claims.get(group_claim, [])
    if isinstance(external_groups, str):
        external_groups = [external_groups]

    # Map external groups to Loom groups
    group_mappings = idp.get("group_mappings", {})
    if group_mappings:
        loom_groups = _map_external_groups(external_groups, group_mappings)
    else:
        loom_groups = external_groups

    return UserInfo(
        sub=sub,
        username=username,
        groups=loom_groups,
        scopes=derive_scopes(loom_groups),
        idp_type=idp.get("provider_type", "external"),
    )


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

def get_current_user_token(request: Request) -> str | None:
    """Extract and validate the user's access token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]

    user_pool_id = os.getenv("LOOM_COGNITO_USER_POOL_ID", "")
    region = os.getenv("LOOM_COGNITO_REGION", os.getenv("AWS_REGION", "us-east-1"))

    # Check for active external IdP
    active_idp = _get_active_idp_cached()

    if not user_pool_id and not active_idp:
        logger.warning("No identity provider configured; skipping token validation")
        return token

    # Try external IdP first
    if active_idp and active_idp.get("jwks_uri"):
        try:
            validate_token(
                token,
                jwks_uri=active_idp["jwks_uri"],
                issuer=active_idp["issuer_url"],
                audience=active_idp.get("audience") or active_idp.get("client_id"),
            )
            return token
        except Exception:
            if not user_pool_id:
                return None

    # Cognito validation
    if user_pool_id:
        try:
            claims = validate_cognito_token(token, user_pool_id, region)
            logger.debug("Validated user token for sub=%s", claims.get("sub"))
            return token
        except Exception as e:
            logger.warning("Invalid user token: %s", e)
            return None

    return None


def get_token_claims(request: Request) -> dict[str, Any] | None:
    """Extract, validate, and decode the user's access token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]

    user_pool_id = os.getenv("LOOM_COGNITO_USER_POOL_ID", "")
    region = os.getenv("LOOM_COGNITO_REGION", os.getenv("AWS_REGION", "us-east-1"))

    # Try external IdP first
    active_idp = _get_active_idp_cached()
    if active_idp and active_idp.get("jwks_uri"):
        try:
            return validate_token(
                token,
                jwks_uri=active_idp["jwks_uri"],
                issuer=active_idp["issuer_url"],
                audience=active_idp.get("audience") or active_idp.get("client_id"),
            )
        except Exception:
            if not user_pool_id:
                return None

    if not user_pool_id:
        return None

    try:
        return validate_cognito_token(token, user_pool_id, region)
    except Exception as e:
        logger.warning("Invalid user token: %s", e)
        return None
