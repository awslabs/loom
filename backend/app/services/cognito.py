"""Cognito token retrieval for authenticated agent invocations."""

import base64
import logging
import urllib.parse
import urllib.request
import json
from typing import Any

from app.services.oidc import require_https_url

logger = logging.getLogger(__name__)


def get_cognito_token(
    pool_id: str,
    client_id: str,
    client_secret: str,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """
    Get an access token from Cognito using the client credentials grant.

    Args:
        pool_id: Cognito User Pool ID (e.g., us-east-1_abc123)
        client_id: App client ID
        client_secret: App client secret
        scopes: Optional list of OAuth scopes to request

    Returns:
        Dict with access_token, token_type, expires_in
    """
    region = pool_id.split("_")[0]
    domain = _get_pool_domain(pool_id, region)
    token_url = f"https://{domain}/oauth2/token"

    # Build request
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


def _get_pool_domain(pool_id: str, region: str) -> str:
    """Get the Cognito domain for a user pool."""
    import boto3

    client = boto3.client("cognito-idp", region_name=region)
    response = client.describe_user_pool(UserPoolId=pool_id)
    domain = response["UserPool"].get("Domain", "")
    if not domain:
        raise ValueError(f"No domain configured for Cognito pool {pool_id}")

    # If it's a custom domain, return as-is; otherwise construct the full domain
    custom_domain = response["UserPool"].get("CustomDomain")
    if custom_domain:
        return custom_domain
    return f"{domain}.auth.{region}.amazoncognito.com"
