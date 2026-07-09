"""JWT token validation — supports Cognito and generic OIDC issuers."""
import json
import logging
import time
import urllib.request
from typing import Any

import jwt
from jwt import algorithms as jwt_algorithms

from app.services.oidc import require_https_url

logger = logging.getLogger(__name__)

# Cache for JWKS keys: {jwks_url: (keys, fetch_time)}
_jwks_cache: dict[str, tuple[dict[str, Any], float]] = {}
JWKS_CACHE_TTL = 3600  # 1 hour


def _get_jwks(jwks_url: str) -> dict[str, Any]:
    """Fetch and cache JWKS keys from any JWKS endpoint."""
    now = time.time()
    if jwks_url in _jwks_cache:
        keys, fetch_time = _jwks_cache[jwks_url]
        if now - fetch_time < JWKS_CACHE_TTL:
            return keys

    require_https_url(jwks_url)
    logger.info("Fetching JWKS from %s", jwks_url)
    req = urllib.request.Request(jwks_url)
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
        jwks = json.loads(resp.read().decode())

    _jwks_cache[jwks_url] = (jwks, now)
    return jwks


def _get_signing_key(jwks: dict[str, Any], kid: str) -> jwt_algorithms.RSAAlgorithm:
    """Find the signing key matching the given kid."""
    available_kids = [k.get("kid") for k in jwks.get("keys", [])]
    for key_data in jwks.get("keys", []):
        if key_data.get("kid") == kid:
            return jwt_algorithms.RSAAlgorithm.from_jwk(key_data)
    raise ValueError(f"Key with kid={kid} not found in JWKS (available: {available_kids})")


def validate_token(
    token: str,
    jwks_uri: str,
    issuer: str,
    audience: str | None = None,
) -> dict[str, Any]:
    """Validate a JWT token against any OIDC-compliant JWKS endpoint.

    Args:
        token: The JWT token string
        jwks_uri: URL to the JWKS endpoint
        issuer: Expected issuer claim
        audience: Expected audience. If None, audience is not validated.

    Returns:
        Decoded token claims
    """
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if not kid:
        raise jwt.InvalidTokenError("Token header missing 'kid'")

    jwks = _get_jwks(jwks_uri)
    public_key = _get_signing_key(jwks, kid)

    options = {}
    if audience is None:
        options["verify_aud"] = False

    claims = jwt.decode(
        token,
        key=public_key,
        algorithms=["RS256"],
        issuer=issuer,
        audience=audience,
        options=options,
    )

    return claims


def validate_cognito_token(
    token: str,
    user_pool_id: str,
    region: str,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Validate a Cognito JWT token (backward-compatible wrapper)."""
    issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
    jwks_uri = f"{issuer}/.well-known/jwks.json"
    return validate_token(token, jwks_uri, issuer, audience=client_id)
