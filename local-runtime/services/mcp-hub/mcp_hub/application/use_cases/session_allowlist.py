"""Build the MCP allowlist for the current Hub session."""
from __future__ import annotations

from typing import Any

from mcp_hub.application.ports import HubStore, LoomGateway
from mcp_hub.domain.access import grants_for_user
from mcp_hub.domain.naming import expose_tools


def build_session_allowlist(
    identity: dict[str, Any],
    *,
    store: HubStore,
    loom: LoomGateway,
) -> tuple[str, dict[str, Any], dict[str, tuple[int, str]], dict[str, Any] | None]:
    """Return slug, allowlist payload, MCP tool mapping, and full client row (or None)."""
    connection_id = str(identity["connection_id"])
    groups = list(identity.get("groups") or [])
    slug = store.session_client_slug(connection_id)
    if not slug:
        empty = {
            "connection_id": connection_id,
            "mcp_client_slug": None,
            "client_status": "unbound",
            "entries": [],
        }
        return "unbound", empty, {}, None
    client = store.get_client(slug, include_grants=True)
    if client is None:
        empty = {
            "connection_id": connection_id,
            "mcp_client_slug": slug,
            "client_status": "missing",
            "entries": [],
        }
        return slug, empty, {}, None
    status = str(client.get("status") or "discovered")
    if status != "enabled":
        empty = {
            "connection_id": connection_id,
            "mcp_client_slug": slug,
            "client_status": status,
            "entries": [],
        }
        return slug, empty, {}, client
    profile_grants = grants_for_user(groups, list(client.get("grants") or []))
    if not profile_grants:
        empty = {
            "connection_id": connection_id,
            "mcp_client_slug": slug,
            "client_status": status,
            "entries": [],
        }
        return slug, empty, {}, client
    code, payload = loom.materialize_allowlist(
        subject=str(identity["sub"]),
        groups=groups,
        connection_id=connection_id,
        mcp_client_slug=slug,
        client_status=status,
        grants=profile_grants,
    )
    if code != 200:
        empty = {
            "connection_id": connection_id,
            "mcp_client_slug": slug,
            "client_status": status,
            "entries": [],
            "error": "materialize_failed",
        }
        return slug, empty, {}, client
    entries = list(payload.get("entries") or [])
    _tools, mapping = expose_tools(entries)
    return slug, payload, mapping, client
