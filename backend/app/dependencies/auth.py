"""Authentication dependencies for FastAPI routes."""
import dataclasses
import logging
import os
from typing import Any

from fastapi import Depends, HTTPException, Request, Security, WebSocket
from fastapi.security import OAuth2AuthorizationCodeBearer, SecurityScopes

from app.services.jwt_validator import validate_cognito_token, validate_token

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


def _is_loopback_request(request: "Request | WebSocket") -> bool:
    client = request.client
    return bool(client) and client.host in _LOOPBACK_HOSTS


# Headers that only appear once a request has traversed a proxy or load
# balancer. A genuine direct-to-loopback development request carries none.
_FORWARDING_HEADERS = (
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    "forwarded",
)


def _has_forwarding_headers(request: "Request | WebSocket") -> bool:
    return any(header in request.headers for header in _FORWARDING_HEADERS)


def _bypass_allowed_for_request(request: "Request | WebSocket") -> bool:
    """Whether the local-dev bypass may even be considered for this request.

    ``request.client`` is only as trustworthy as the proxy configuration in
    front of the app, which is the weak point: uvicorn ships with
    ``proxy_headers=True``, so if ``FORWARDED_ALLOW_IPS`` is ever widened
    past loopback — a common change behind a load balancer, made to recover
    real client IPs for logging or rate limiting, and one that looks entirely
    unrelated to auth — then a remote caller can send
    ``X-Forwarded-For: 127.0.0.1`` and have ``request.client.host`` read back
    as loopback.

    Requiring that no forwarding header is present closes that off, because
    the spoof cannot work *without* the very header this rejects, while a real
    direct-to-loopback request never carries one. Note this is the second line
    of defence: ``assert_local_dev_bypass_not_deployed`` is what stops the
    process from serving at all in that configuration.
    """
    if not _bypass_auth_enabled():
        return False
    if _has_forwarding_headers(request):
        logger.error(
            "Local-dev auth bypass refused: request carries proxy forwarding headers, "
            "so its client address cannot be trusted to be loopback"
        )
        return False
    return _is_loopback_request(request)


# Variables that only exist inside a container runtime. ECS injects these into
# every task; a developer's machine has none of them.
_DEPLOYMENT_SIGNAL_VARS = (
    "ECS_CONTAINER_METADATA_URI_V4",
    "ECS_CONTAINER_METADATA_URI",
    "AWS_EXECUTION_ENV",
)

# Values of FORWARDED_ALLOW_IPS that keep uvicorn's proxy-header handling
# restricted to loopback peers, and so leave request.client trustworthy.
_SAFE_FORWARDED_ALLOW_IPS = {"", "127.0.0.1", "::1", "localhost"}


def assert_local_dev_bypass_not_deployed() -> None:
    """Refuse to serve if the local-dev auth bypass is enabled in a deployment.

    Called from the application lifespan so that this combination fails at
    startup, in front of whoever deployed it, instead of quietly serving an
    open admin panel. Misconfiguration is a config-time event, so it should be
    caught at config time rather than left to be discovered at request time.

    The exposure being guarded is narrow but plausible: the bypass requires
    neither Cognito nor an external IdP to be configured, which is exactly the
    state of a fresh deployment that intends to use an external IdP but has
    not registered it yet. Add a stale
    ``LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV`` in the task definition and a
    widened ``FORWARDED_ALLOW_IPS``, and an unauthenticated caller reaches
    every scope.
    """
    if not _bypass_auth_enabled():
        return

    reasons = []
    for var in _DEPLOYMENT_SIGNAL_VARS:
        value = os.getenv(var)
        if value:
            reasons.append(f"{var}={value!r} indicates a container runtime")

    forwarded = os.getenv("FORWARDED_ALLOW_IPS", "").strip()
    if forwarded not in _SAFE_FORWARDED_ALLOW_IPS:
        reasons.append(
            f"FORWARDED_ALLOW_IPS={forwarded!r} makes uvicorn trust proxy headers "
            "from non-loopback peers, so a spoofed X-Forwarded-For can masquerade "
            "as a loopback client"
        )

    if reasons:
        raise RuntimeError(
            f"{LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV} is enabled, but this looks like a "
            f"deployed environment ({'; '.join(reasons)}). In that combination every "
            "request would be served as super-admin with no authentication. Unset "
            f"{LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV} before deploying."
        )


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
        "session:read",
        "memory:read", "memory:write", "security:read", "security:write",
        "tagging:read", "tagging:write",
        "costs:read", "costs:write",
        "mcp:read", "mcp:write", "a2a:read", "a2a:write",
        "registry:read", "registry:write",
        "invoke", "admin:read", "admin:write",
    ],
    "g-admins-demo": [
        "catalog:read", "agent:read", "agent:write", "session:read",
        "memory:read", "memory:write",
        "security:read", "tagging:read", "costs:read", "costs:write",
        "mcp:read", "mcp:write", "a2a:read", "a2a:write",
        "registry:read", "registry:write",
        "invoke",
    ],
    "g-admins-security": [
        "security:read", "security:write", "tagging:read",
    ],
    "g-admins-memory": [
        "memory:read", "memory:write", "tagging:read",
    ],
    "g-admins-mcp": [
        "mcp:read", "mcp:write", "tagging:read",
    ],
    "g-admins-a2a": [
        "a2a:read", "a2a:write", "tagging:read",
    ],
    "g-admins-registry": [
        "mcp:read", "a2a:read", "registry:read", "registry:write", "tagging:read",
    ],

    # User groups (t-user users - can have multiple)
    # session:read is held alongside agent:read by everyone who has it today,
    # so splitting the scope is not a privilege change. The point of the split
    # is that conversation content (prompts, reasoning, responses, tool inputs)
    # is far more sensitive than "this agent exists", and now has to be granted
    # deliberately: the domain admins below (security/memory/mcp/a2a/registry)
    # hold neither, and a future read-only or audit role can be given
    # agent:read without handing over every chat transcript.
    "g-users-demo": ["agent:read", "session:read", "memory:read", "mcp:read", "invoke"],
    "g-users-test": ["agent:read", "session:read", "memory:read", "mcp:read", "invoke"],
    "g-users-strategics": ["agent:read", "session:read", "memory:read", "mcp:read", "invoke"],
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
        "session:read": "Read agent conversations (prompts, reasoning, responses)",
        "memory:read": "Read memory",
        "memory:write": "Write memory",
        "security:read": "Read security",
        "security:write": "Write security",
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
    """FastAPI dependency: validate the request's Bearer token into a UserInfo.

    Only pulls the token out of the header; everything else lives in
    authenticate_bearer_token so the WebSocket path resolves identity through
    exactly the same code.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    return authenticate_bearer_token(token, request)


def authenticate_bearer_token(token: str, connection: "Request | WebSocket") -> UserInfo:
    """Resolve a bearer token to a UserInfo, or raise HTTPException(401).

    Shared by the HTTP dependency above and the invoke WebSocket handler. It is
    deliberately one implementation: the WebSocket endpoint previously had no
    authentication at all (CWE-306), and a second copy of this logic is how
    that kind of gap survives a fix to the first copy.

    ``connection`` only needs ``.headers`` and ``.client``, for the local-dev
    bypass checks — both Request and WebSocket provide them.

    Checks for an active external IdP first, then falls back to Cognito. In
    bypass mode (no LOOM_COGNITO_USER_POOL_ID and no active IdP) returns a user
    with all scopes, but ONLY with the explicit opt-in and a loopback client;
    fails closed with 401 otherwise, since an IdP-less deployment reachable
    over the network would otherwise be an open admin panel.
    """
    user_pool_id = os.getenv("LOOM_COGNITO_USER_POOL_ID", "")
    region = os.getenv("LOOM_COGNITO_REGION", os.getenv("AWS_REGION", "us-east-1"))

    # Check for active external IdP
    active_idp = _get_active_idp_cached()

    # Bypass mode — no Cognito and no external IdP configured. Requires explicit
    # opt-in and a loopback client; otherwise fail closed with 401.
    if not user_pool_id and not active_idp:
        if _bypass_allowed_for_request(connection):
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

    # Map external groups to Loom groups. An empty or missing mapping table
    # means "nothing is authorised yet", never "trust whatever the IdP says":
    # falling back to the raw claim here handed an external token direct
    # control over Loom group names, so a caller who could stand up an IdP
    # (security:write alone) could mint a JWT claiming g-admins-super and
    # authenticate as full super-admin. _assert_group_mappings_within_caller_scopes
    # guards the mapping *table*, but an empty table bypassed it entirely by
    # never putting the group name in the table in the first place.
    #
    # _map_external_groups already resolves an empty table to no groups, so the
    # user still authenticates and simply holds no scopes — every guarded route
    # returns 403. An IdP configured without mappings is now a visible
    # misconfiguration instead of a silent grant of everything.
    group_mappings = idp.get("group_mappings", {})
    loom_groups = _map_external_groups(external_groups, group_mappings)
    if external_groups and not loom_groups:
        logger.warning(
            "External IdP %s returned groups %s, none of which are mapped to a Loom "
            "group; user has no scopes. Configure the provider's group_mappings.",
            idp.get("id"),
            external_groups,
        )

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
