"""OIDC discovery document fetcher."""

import json
import urllib.parse
import logging
from typing import Any

from app.services.net_guard import safe_get

logger = logging.getLogger(__name__)


class OIDCDiscoveryError(Exception):
    """Raised when OIDC discovery fails."""


def require_https_endpoint(field: str, value: str) -> str:
    """Reject a discovery endpoint that is not an absolute https:// URL.

    The discovery document is attacker-influenced: registering an authorizer
    or identity provider takes `security:write`, and the document itself is
    served by whatever host that URL points at. Three of its fields are used
    as URLs afterwards, and `authorization_endpoint` is the dangerous one —
    it is concatenated into `authorize_url` and handed to the SPA, which
    assigns it to `window.location.href`. A `javascript:` URL there executes
    in Loom's own origin, where the session tokens live in sessionStorage.

    Scheme-checked here at persist time *and* again before the SPA navigates,
    because rows written before this check existed are still in the database.
    """
    parsed = urllib.parse.urlparse(value or "")
    if parsed.scheme != "https" or not parsed.netloc:
        raise OIDCDiscoveryError(
            f"Discovery document field {field!r} must be an absolute https:// URL, got "
            f"{(parsed.scheme or 'no scheme')!r}"
        )
    return value


def fetch_discovery(issuer_url: str) -> dict[str, Any]:
    """Fetch and parse the OIDC discovery document from an issuer.

    Args:
        issuer_url: The OIDC issuer base URL (e.g. https://login.microsoftonline.com/{tenant}/v2.0)

    Returns:
        Dict with keys: jwks_uri, authorization_endpoint, token_endpoint, scopes_supported

    Raises:
        OIDCDiscoveryError: If the document is unreachable or missing required fields
    """
    stripped = issuer_url.rstrip("/")
    url = stripped if "/.well-known/openid-configuration" in stripped else stripped + "/.well-known/openid-configuration"
    logger.info("Fetching OIDC discovery from %s", url)

    try:
        resp = safe_get(url, headers={"Accept": "application/json"}, timeout=10)
        resp.raise_for_status()
        doc = json.loads(resp.content.decode())
    except Exception as e:
        raise OIDCDiscoveryError(f"Failed to fetch discovery document from {url}: {e}") from e

    required_fields = ["jwks_uri", "authorization_endpoint", "token_endpoint"]
    missing = [f for f in required_fields if not doc.get(f)]
    if missing:
        raise OIDCDiscoveryError(f"Discovery document missing required fields: {', '.join(missing)}")

    for field in required_fields:
        require_https_endpoint(field, doc[field])

    return {
        "jwks_uri": doc["jwks_uri"],
        "authorization_endpoint": doc["authorization_endpoint"],
        "token_endpoint": doc["token_endpoint"],
        "scopes_supported": doc.get("scopes_supported", []),
        "issuer": doc.get("issuer", issuer_url),
    }
