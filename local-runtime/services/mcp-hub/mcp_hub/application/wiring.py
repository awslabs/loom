"""Composition root helpers — default outbound adapters for the Hub."""
from __future__ import annotations

import logging
import os

from mcp_hub.adapters.outbound.file_store import FileHubStore, load_snapshot, store_path
from mcp_hub.adapters.outbound.loom_http import LoomHttpGateway
from mcp_hub.adapters.outbound.oauth_jwks import OAuthJwksValidator
from mcp_hub.adapters.outbound.pg_store import PostgresHubStore, database_url
from mcp_hub.application.ports import HubStore, LoomGateway, TokenValidator

logger = logging.getLogger("mcp_hub")


def _maybe_migrate_json(pg: PostgresHubStore) -> None:
    """Import from JSON when Postgres is empty (or MCP_HUB_MIGRATE_JSON=force)."""
    mode = os.environ.get("MCP_HUB_MIGRATE_JSON", "").strip().lower()
    force = mode in ("force", "overwrite")
    if pg.client_count() > 0 and not force:
        return
    path = store_path()
    if not os.path.isfile(path):
        return
    try:
        snap = load_snapshot()
    except OSError as exc:
        logger.warning("json migrate skipped: cannot read %s (%s)", path, exc)
        return
    clients = snap.get("clients") or {}
    if not clients and not force:
        return
    n = pg.import_snapshot(snap)
    logger.info("migrated hub store json→postgres clients=%s path=%s force=%s", n, path, force)


def default_store() -> HubStore:
    dsn = database_url()
    if dsn:
        pg = PostgresHubStore(dsn)
        _maybe_migrate_json(pg)
        return pg
    logger.warning("MCP_HUB_DATABASE_URL unset — using JSON file store at %s", store_path())
    return FileHubStore()


def default_loom() -> LoomGateway:
    return LoomHttpGateway()


def default_tokens() -> TokenValidator:
    return OAuthJwksValidator()
