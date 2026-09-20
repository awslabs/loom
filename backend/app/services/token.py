"""Generic OAuth2 token retrieval using client credentials grant."""

import base64
import logging
from typing import Any

from app.services.net_guard import get_trusted_oauth_hosts, is_trusted_oauth_host, safe_post
from app.services.oidc import fetch_discovery

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

    if not is_trusted_oauth_host(token_url, get_trusted_oauth_hosts()):
        raise ValueError(
            f"Refusing to send OAuth2 client credentials to untrusted token endpoint {token_url!r} "
            "(host is not a configured identity provider or authorizer)"
        )

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {credentials}",
    }
    body_params: dict[str, str] = {"grant_type": "client_credentials"}
    if scopes:
        body_params["scope"] = " ".join(scopes)

    resp = safe_post(token_url, data=body_params, headers=headers)
    resp.raise_for_status()
    return resp.json()
