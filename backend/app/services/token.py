"""Generic OAuth2 token retrieval using client credentials grant."""

import base64
import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from app.services.oidc import fetch_discovery, OIDCDiscoveryError, require_https_url

logger = logging.getLogger(__name__)


def get_oauth2_token(
    discovery_url: str,
    client_id: str,
    client_secret: str,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Get an access token from any OIDC provider using client credentials grant.

    Args:
        discovery_url: OIDC issuer URL (used to discover token endpoint)
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret
        scopes: Optional list of scopes to request

    Returns:
        Dict with access_token, token_type, expires_in
    """
    disc = fetch_discovery(discovery_url)
    token_url = disc["token_endpoint"]

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {credentials}",
    }
    body_params: dict[str, str] = {"grant_type": "client_credentials"}
    if scopes:
        body_params["scope"] = " ".join(scopes)

    require_https_url(token_url)
    data = urllib.parse.urlencode(body_params).encode()
    req = urllib.request.Request(token_url, data=data, headers=headers, method="POST")

    with urllib.request.urlopen(req) as resp:  # nosec B310
        result = json.loads(resp.read().decode())

    return result
