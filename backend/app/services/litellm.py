"""LiteLLM proxy master-key resolution and per-agent virtual key vending.

The LiteLLM master key is the one credential Loom holds for a deployed
LiteLLM proxy. It is never handed to an individual agent — instead, each
LiteLLM-provider agent gets a scoped *virtual key* minted via the proxy's
key-management API (`/key/generate`), and that virtual key is what actually
gets stored as the agent's `api_key_secret_arn`.

Two distinct base URLs are tracked, since the machine calling the proxy
differs:
  - agent_base_url: what deployed agents/harnesses use at runtime to reach
    the proxy directly (must be reachable from wherever the agent runs,
    e.g. an internal ALB). This replaces the old per-agent `base_url` field
    that used to be typed into every agent's registration form.
  - discovery_base_url: what the Loom *backend itself* uses for calls it
    makes directly to the proxy (`/model/info` discovery, `/key/generate`,
    `/key/delete`). Falls back to agent_base_url when not separately set —
    they're identical in a deployed environment, but during local dev the
    backend typically reaches the proxy through an SSM tunnel
    (e.g. http://localhost:4000) while agents reach it through the real ALB.

Master key / base URL resolution order — env vars seed the *defaults* at
startup; a Settings-page save always wins after that:
  1. Site-settings override (Secrets Manager + SiteSetting rows), set via
     Settings -> Models -> LiteLLM. Wins once an agent_base_url has been
     saved there, gated by the `litellm_enabled` toggle.
  2. Fall back to the CFN-seeded env vars so a fresh deploy works without a
     Settings-page visit, and so the Settings page has something sensible
     to show/edit the first time an admin opens it:
       - LOOM_LITELLM_PROXY_BASE_URL: agent_base_url default (e.g. the
         internal ALB — P_LITELLM_ENDPOINT in environment.sh).
       - LOOM_LITELLM_DISCOVERY_BASE_URL: discovery_base_url default (e.g.
         a local SSM tunnel — P_LITELLM_ENDPOINT_LOCAL in environment.sh).
         Falls back to LOOM_LITELLM_PROXY_BASE_URL when unset.
       - LOOM_LITELLM_PROXY_API_KEY: master key default.
     Used only when no agent_base_url has ever been saved via Settings;
     considered "enabled" automatically once LOOM_LITELLM_PROXY_BASE_URL is
     set, since there's no separate toggle for the env-var tier.
"""

import logging
import os
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MASTER_KEY_SECRET_NAME = "loom/settings/litellm-master-key"
ENABLED_SETTING_KEY = "litellm_enabled"
AGENT_BASE_URL_SETTING_KEY = "litellm_proxy_base_url"
DISCOVERY_BASE_URL_SETTING_KEY = "litellm_discovery_base_url"

_DEFAULT_REGION = os.getenv("AWS_REGION", "us-east-1")


def _setting(db: Session, key: str) -> str:
    from app.models.site_setting import SiteSetting

    row = db.query(SiteSetting).filter(SiteSetting.key == key).first()
    return row.value if row else ""


def _env_agent_base_url() -> str:
    return os.getenv("LOOM_LITELLM_PROXY_BASE_URL", "")


def _env_discovery_base_url() -> str:
    return os.getenv("LOOM_LITELLM_DISCOVERY_BASE_URL", "") or _env_agent_base_url()


def is_enabled(db: Session) -> bool:
    """Whether the LiteLLM connection is active — the Settings-page toggle
    once an agent_base_url has been saved there, else implicitly true when
    only the env-var fallback provides a base URL."""
    if _setting(db, AGENT_BASE_URL_SETTING_KEY):
        return _setting(db, ENABLED_SETTING_KEY) == "true"
    return bool(_env_agent_base_url())


def get_agent_base_url(db: Session) -> str:
    """The base URL deployed agents/harnesses use at runtime — Settings
    override wins, falling back to the env-seeded default."""
    return _setting(db, AGENT_BASE_URL_SETTING_KEY) or _env_agent_base_url()


def get_effective_config(db: Session) -> dict[str, Any]:
    """Full effective config for display purposes (the Settings page GET)
    — reflects whichever source (Settings override or env-var fallback) is
    currently in effect, so the page shows real values to edit rather than
    blanks when only the env-seeded defaults are active.

    {"enabled": bool, "agent_base_url": str, "discovery_base_url": str}
    """
    agent_base_url = _setting(db, AGENT_BASE_URL_SETTING_KEY)
    if agent_base_url:
        return {
            "enabled": is_enabled(db),
            "agent_base_url": agent_base_url,
            "discovery_base_url": _setting(db, DISCOVERY_BASE_URL_SETTING_KEY),
        }
    return {
        "enabled": bool(_env_agent_base_url()),
        "agent_base_url": _env_agent_base_url(),
        "discovery_base_url": _env_discovery_base_url(),
    }


def get_litellm_proxy_config(db: Session) -> tuple[str, str] | None:
    """Resolve the (base_url, master_key) the Loom *backend* uses to call
    the proxy directly — model discovery, /key/generate, /key/delete.

    Uses discovery_base_url when set, else agent_base_url. Returns None if
    no proxy is configured, or if a Settings-page agent_base_url is set but
    `litellm_enabled` is off, or the master key can't be read.
    """
    from app.services.secrets import get_secret

    agent_base_url = _setting(db, AGENT_BASE_URL_SETTING_KEY)

    if agent_base_url:
        if not is_enabled(db):
            return None
        discovery_base_url = _setting(db, DISCOVERY_BASE_URL_SETTING_KEY) or agent_base_url
        try:
            master_key = get_secret(MASTER_KEY_SECRET_NAME, _DEFAULT_REGION)
            return (discovery_base_url, master_key)
        except Exception:
            logger.warning(
                "litellm agent_base_url is set but %s could not be read from Secrets Manager",
                MASTER_KEY_SECRET_NAME,
                exc_info=True,
            )
            return None

    env_base_url = _env_agent_base_url()
    if env_base_url:
        env_discovery_base_url = _env_discovery_base_url()
        env_api_key = os.getenv("LOOM_LITELLM_PROXY_API_KEY", "")
        return (env_discovery_base_url, env_api_key)

    return None


def has_master_key(db: Session) -> bool:
    """Return True if a master key is resolvable (settings override or env fallback)."""
    return get_litellm_proxy_config(db) is not None


def vend_virtual_key(
    agent_id: int,
    agent_name: str,
    allowed_model_ids: list[str],
    db: Session,
    timeout: float = 10.0,
) -> str | None:
    """Mint a LiteLLM virtual key scoped to allowed_model_ids for this agent.

    Returns the virtual key string on success, or None if the proxy isn't
    configured or the request fails — deploy should degrade gracefully
    rather than hard-fail when the LiteLLM proxy integration is optional.
    """
    config = get_litellm_proxy_config(db)
    if config is None:
        logger.warning("Cannot vend LiteLLM virtual key for agent %s: no proxy configured", agent_id)
        return None
    base_url, master_key = config

    key_alias = f"loom-agent-{agent_id}"
    # key_alias is deterministic per agent, so a retried/redeployed harness
    # collides with the key left over from a prior attempt (LiteLLM rejects
    # duplicate aliases with a 400) — clear it first so vending is idempotent.
    revoke_virtual_key(key_alias, db, timeout=timeout)
    try:
        import httpx

        response = httpx.post(
            f"{base_url.rstrip('/')}/key/generate",
            headers={"Authorization": f"Bearer {master_key}"},
            json={
                "models": allowed_model_ids,
                "key_alias": key_alias,
                "metadata": {"loom_agent_id": agent_id, "loom_agent_name": agent_name},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    except Exception:
        logger.warning("Failed to vend LiteLLM virtual key for agent %s", agent_id, exc_info=True)
        return None

    key = data.get("key")
    if not key:
        logger.warning("LiteLLM /key/generate response for agent %s had no 'key' field", agent_id)
        return None

    logger.info("Vended LiteLLM virtual key (alias=%s) for agent %s", key_alias, agent_id)
    return key


def revoke_virtual_key(key_alias: str, db: Session, timeout: float = 10.0) -> None:
    """Revoke a previously-vended virtual key by its alias.

    Best-effort — logs and returns on any failure rather than raising, so a
    proxy that's unreachable at delete time never blocks agent deletion.
    """
    config = get_litellm_proxy_config(db)
    if config is None:
        logger.warning("Cannot revoke LiteLLM virtual key '%s': no proxy configured", key_alias)
        return
    base_url, master_key = config

    try:
        import httpx

        response = httpx.post(
            f"{base_url.rstrip('/')}/key/delete",
            headers={"Authorization": f"Bearer {master_key}"},
            json={"key_aliases": [key_alias]},
            timeout=timeout,
        )
        if response.status_code == 404:
            # Expected on a first deploy — there's no prior key under this
            # alias to revoke yet.
            logger.debug("No existing LiteLLM virtual key to revoke (alias=%s)", key_alias)
            return
        response.raise_for_status()
        logger.info("Revoked LiteLLM virtual key (alias=%s)", key_alias)
    except Exception:
        logger.warning("Failed to revoke LiteLLM virtual key '%s'", key_alias, exc_info=True)
