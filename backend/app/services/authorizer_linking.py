"""Per-user authorizer linking: store, resolve, and manage user tokens in Secrets Manager."""

import base64
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

from app.services.secrets import store_secret, get_secret, delete_secret
from app.services.oidc import fetch_discovery, require_https_url

logger = logging.getLogger(__name__)

# In-memory cache for resolved access tokens: (auth_id, user_sub) -> (token, expiry)
_token_cache: dict[tuple[int, str], tuple[str, float]] = {}


def _secret_name(auth_id: int, user_sub: str) -> str:
    return f"loom/authorizers/{auth_id}/user-tokens/{user_sub}"


def check_link_status(auth_id: int, user_sub: str, region: str) -> bool:
    try:
        get_secret(_secret_name(auth_id, user_sub), region)
        return True
    except Exception:
        return False


def store_user_tokens(auth_id: int, user_sub: str, refresh_token: str, region: str) -> str:
    payload = json.dumps({
        "refresh_token": refresh_token,
        "linked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return store_secret(
        name=_secret_name(auth_id, user_sub),
        secret_value=payload,
        region=region,
        description=f"User tokens for authorizer {auth_id}, user {user_sub}",
    )


def delete_user_tokens(auth_id: int, user_sub: str, region: str) -> None:
    delete_secret(_secret_name(auth_id, user_sub), region)
    _token_cache.pop((auth_id, user_sub), None)


def resolve_access_token(
    auth_id: int,
    user_sub: str,
    region: str,
    discovery_url: str,
    user_client_id: str,
    user_client_secret: str | None = None,
) -> str | None:
    now = time.time()
    cached = _token_cache.get((auth_id, user_sub))
    if cached and cached[1] > now:
        return cached[0]

    try:
        secret_name = _secret_name(auth_id, user_sub)
        logger.info("Looking up linked token at %s", secret_name)
        raw = get_secret(secret_name, region)
        payload = json.loads(raw)
        refresh_token = payload["refresh_token"]
    except Exception as e:
        logger.warning("No linked token found for auth=%s user=%s: %s", auth_id, user_sub, e)
        return None

    try:
        disc = fetch_discovery(discovery_url)
        token_url = disc["token_endpoint"]

        body_params = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": user_client_id,
        }
        require_https_url(token_url)
        data = urllib.parse.urlencode(body_params).encode()
        headers: dict[str, str] = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if user_client_secret:
            credentials = base64.b64encode(
                f"{user_client_id}:{user_client_secret}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {credentials}"
        req = urllib.request.Request(
            token_url,
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            result: dict[str, Any] = json.loads(resp.read().decode())

        access_token = result["access_token"]
        expires_in = int(result.get("expires_in", 3600))
        _token_cache[(auth_id, user_sub)] = (access_token, now + expires_in - 60)

        if "refresh_token" in result and result["refresh_token"] != refresh_token:
            store_user_tokens(auth_id, user_sub, result["refresh_token"], region)

        return access_token
    except Exception as e:
        logger.warning("Failed to resolve access token for auth=%s user=%s: %s", auth_id, user_sub, e)
        return None


def exchange_code_for_tokens(
    discovery_url: str,
    user_client_id: str,
    user_client_secret: str | None,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    disc = fetch_discovery(discovery_url)
    token_url = disc["token_endpoint"]

    body_params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "client_id": user_client_id,
    }
    require_https_url(token_url)
    data = urllib.parse.urlencode(body_params).encode()
    headers: dict[str, str] = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if user_client_secret:
        credentials = base64.b64encode(
            f"{user_client_id}:{user_client_secret}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {credentials}"
    req = urllib.request.Request(
        token_url,
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
        return json.loads(resp.read().decode())
