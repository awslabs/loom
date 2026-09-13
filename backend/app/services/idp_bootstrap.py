"""Seed the active identity provider from the environment.

Without this, the first provider can only be registered through an endpoint that
itself requires an authenticated user with ``security:write`` — and the local-dev
auth bypass is restricted to loopback clients, which a containerised backend never
is. That combination makes a fresh deployment unable to bootstrap its own login.

Seeding is idempotent and never overwrites a provider a human created: rows carry
``managed_by = "bootstrap"`` so operator-created rows (``managed_by`` null) win.
"""
from __future__ import annotations

import json
import logging
import os
import time

from app.services.oidc import OIDCDiscoveryError

logger = logging.getLogger(__name__)

ENV_PREFIX = "LOOM_IDP_BOOTSTRAP_"
ENV_JSON = "LOOM_IDP_BOOTSTRAP_JSON"

MANAGED_BY = "bootstrap"

_FIELDS = (
    "name",
    "type",
    "issuer_url",
    "internal_base_url",
    "client_id",
    "client_type",
    "audience",
    "group_claim_path",
    "scopes",
)

_DISCOVERY_ATTEMPTS = 10
_DISCOVERY_BACKOFF_SECONDS = 3


def _read_env_config() -> dict[str, str] | None:
    """Read the bootstrap configuration from JSON or discrete variables."""
    raw_json = os.getenv(ENV_JSON, "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as e:
            logger.warning("%s is not valid JSON, ignoring: %s", ENV_JSON, e)
            return None
        if not isinstance(parsed, dict):
            logger.warning("%s must be a JSON object, ignoring", ENV_JSON)
            return None
        config = {k: str(v) for k, v in parsed.items() if v is not None}
    else:
        config = {}
        for field in _FIELDS:
            value = os.getenv(f"{ENV_PREFIX}{field.upper()}", "").strip()
            if value:
                config[field] = value

    if not config:
        return None

    missing = [f for f in ("name", "type", "issuer_url", "client_id") if not config.get(f)]
    if missing:
        logger.warning(
            "Identity provider bootstrap is incomplete (missing %s); skipping",
            ", ".join(f"{ENV_PREFIX}{m.upper()}" for m in missing),
        )
        return None
    return config


def _discover_with_retry(idp, name: str) -> bool:
    from app.services.idp_discovery import run_discovery

    for attempt in range(1, _DISCOVERY_ATTEMPTS + 1):
        try:
            run_discovery(idp)
            return True
        except OIDCDiscoveryError as e:
            if attempt == _DISCOVERY_ATTEMPTS:
                logger.warning(
                    "OIDC discovery for bootstrap provider %r failed after %d attempts: %s. "
                    "The provider row is saved; re-run discovery from Settings once the IdP is up.",
                    name, attempt, e,
                )
                return False
            logger.info(
                "OIDC discovery for %r not ready (attempt %d/%d): %s",
                name, attempt, _DISCOVERY_ATTEMPTS, e,
            )
            time.sleep(_DISCOVERY_BACKOFF_SECONDS)
    return False


def bootstrap_identity_provider(engine=None) -> bool:
    """Upsert and activate the provider described by the environment.

    Returns True when a provider row was created or updated. Never raises: a failed
    bootstrap must not prevent the application from starting, or the operator loses the
    UI they would use to fix the configuration.
    """
    try:
        config = _read_env_config()
        if not config:
            return False

        from sqlalchemy.orm import sessionmaker

        from app.db import SessionLocal
        from app.models.identity_provider import IdentityProvider

        session_factory = sessionmaker(bind=engine) if engine is not None else SessionLocal
        db = session_factory()
        try:
            name = config["name"]
            idp = db.query(IdentityProvider).filter(IdentityProvider.name == name).first()

            if idp and idp.managed_by != MANAGED_BY:
                logger.info(
                    "Identity provider %r exists and is operator-managed; leaving it untouched",
                    name,
                )
                return False

            created = idp is None
            if created:
                idp = IdentityProvider(name=name)

            idp.provider_type = config["type"]
            idp.issuer_url = config["issuer_url"]
            idp.internal_base_url = config.get("internal_base_url")
            idp.client_id = config["client_id"]
            idp.client_type = config.get("client_type", "public")
            idp.audience = config.get("audience")
            idp.group_claim_path = config.get("group_claim_path")
            idp.scopes = config.get("scopes")
            idp.managed_by = MANAGED_BY
            idp.status = "active"

            _discover_with_retry(idp, name)

            for other in db.query(IdentityProvider).filter(
                IdentityProvider.status == "active",
                IdentityProvider.name != name,
            ).all():
                logger.info("Deactivating provider %r in favour of bootstrap provider", other.name)
                other.status = "inactive"

            if created:
                db.add(idp)
            db.commit()

            logger.info(
                "%s bootstrap identity provider %r (type=%s, issuer=%s, internal=%s)",
                "Created" if created else "Updated",
                name, idp.provider_type, idp.issuer_url, idp.internal_base_url,
            )
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        logger.warning("Identity provider bootstrap failed: %s", e, exc_info=True)
        return False
    finally:
        try:
            from app.dependencies.auth import invalidate_idp_cache

            invalidate_idp_cache()
        except Exception:  # pragma: no cover
            pass
