"""Persist/resolve MCP + A2A linked to source=local agents (Hub + Chat)."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import UserInfo
from app.models.a2a import A2aAgent, A2aAgentAccess
from app.models.agent import Agent
from app.models.config_entry import ConfigEntry
from app.models.mcp import McpServer, McpServerAccess
from app.services.mcp_access import McpAccessDenied, allowed_tool_names, require_access

logger = logging.getLogger(__name__)


def _agent_config_entry(agent: Agent) -> ConfigEntry | None:
    return next((e for e in agent.config_entries if e.key == "AGENT_CONFIG_JSON"), None)


def _load_config(agent: Agent) -> dict[str, Any]:
    entry = _agent_config_entry(agent)
    if entry is None or not entry.value:
        return {}
    try:
        data = json.loads(entry.value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def linked_mcp_server_ids(agent: Agent, db: Session) -> list[int]:
    """Prefer McpServerAccess rows; fall back to AGENT_CONFIG_JSON snapshots."""
    rules = (
        db.query(McpServerAccess)
        .filter(McpServerAccess.persona_id == agent.id)
        .all()
    )
    if rules:
        return sorted({int(r.server_id) for r in rules})
    config = _load_config(agent)
    integrations = config.get("integrations") if isinstance(config.get("integrations"), dict) else {}
    rows = integrations.get("mcp_servers") if isinstance(integrations, dict) else []
    ids: list[int] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        sid = row.get("server_id")
        if sid is not None:
            try:
                ids.append(int(sid))
                continue
            except (TypeError, ValueError):
                pass
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        server = db.query(McpServer).filter(McpServer.name == name).first()
        if server:
            ids.append(int(server.id))
    return sorted(set(ids))


def _snapshot_server(server: McpServer) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "server_id": server.id,
        "name": server.name,
        "enabled": True,
        "transport": server.transport_type,
        "endpoint_url": server.endpoint_url,
        "auth_type": server.auth_type,
    }
    if server.transport_type == "stdio" or server.auth_type in ("loom", "none", ""):
        entry["auth"] = {"type": "service_bearer"}
    elif server.auth_type == "api_key":
        entry["auth"] = {
            "type": "api_key",
            "credentials_secret_arn": f"loom/mcp/{server.name}/api-key/{{actor_id}}",
            "api_key_header_name": server.api_key_header_name or "x-api-key",
        }
    if getattr(server, "supports_elicitation", None) == "true":
        entry["supports_elicitation"] = "true"
    entry["delegation_mode"] = getattr(server, "delegation_mode", None) or "m2m"
    return entry


def linked_a2a_agent_ids(agent: Agent, db: Session) -> list[int]:
    rules = (
        db.query(A2aAgentAccess)
        .filter(A2aAgentAccess.persona_id == agent.id)
        .all()
    )
    if rules:
        return sorted({int(r.agent_id) for r in rules})
    config = _load_config(agent)
    integrations = config.get("integrations") if isinstance(config.get("integrations"), dict) else {}
    rows = integrations.get("a2a_agents") if isinstance(integrations, dict) else []
    ids: list[int] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        aid = row.get("a2a_agent_id") or row.get("id")
        if aid is not None:
            try:
                ids.append(int(aid))
                continue
            except (TypeError, ValueError):
                pass
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        a2a = db.query(A2aAgent).filter(A2aAgent.name == name).first()
        if a2a:
            ids.append(int(a2a.id))
    return sorted(set(ids))


def _snapshot_a2a(a2a: A2aAgent) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "a2a_agent_id": a2a.id,
        "name": a2a.name,
        "enabled": True,
        "endpoint_url": a2a.base_url,
        "auth_type": a2a.auth_type,
        "delegation_mode": a2a.delegation_mode or "m2m",
    }
    if a2a.auth_type == "oauth2":
        entry["auth"] = {
            "type": "oauth2",
            "well_known_endpoint": a2a.oauth2_well_known_url or "",
            "scopes": a2a.oauth2_scopes or "",
            "delegation_mode": a2a.delegation_mode or "m2m",
        }
        if a2a.obo_grant_type:
            entry["auth"]["obo_grant_type"] = a2a.obo_grant_type
    return entry


def set_local_agent_integrations(
    db: Session,
    agent: Agent,
    *,
    mcp_server_ids: list[int] | None = None,
    a2a_agent_ids: list[int] | None = None,
) -> dict[str, list[int]]:
    """Replace MCP and/or A2A links on a local agent (config + access rules)."""
    if agent.source != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="local integrations are only supported for source=local agents",
        )
    entry = _agent_config_entry(agent)
    if entry is None:
        raise HTTPException(status_code=400, detail="missing AGENT_CONFIG_JSON")
    config = _load_config(agent)
    integrations = config.get("integrations") if isinstance(config.get("integrations"), dict) else {}
    integrations = dict(integrations or {})

    mcp_result = linked_mcp_server_ids(agent, db)
    if mcp_server_ids is not None:
        wanted = sorted({int(i) for i in mcp_server_ids})
        servers = db.query(McpServer).filter(McpServer.id.in_(wanted)).all() if wanted else []
        found = {int(s.id) for s in servers}
        missing = [i for i in wanted if i not in found]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MCP server(s) not found: {missing}",
            )
        inactive = [s.name for s in servers if s.status == "inactive"]
        if inactive:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MCP server(s) inactive: {', '.join(inactive)}",
            )
        integrations["mcp_servers"] = [_snapshot_server(s) for s in servers]
        db.query(McpServerAccess).filter(McpServerAccess.persona_id == agent.id).delete(
            synchronize_session=False
        )
        for sid in wanted:
            db.add(
                McpServerAccess(
                    server_id=sid,
                    persona_id=agent.id,
                    access_level="all_tools",
                    allowed_tool_names=None,
                )
            )
        mcp_result = wanted

    a2a_result = linked_a2a_agent_ids(agent, db)
    if a2a_agent_ids is not None:
        wanted_a2a = sorted({int(i) for i in a2a_agent_ids})
        a2as = db.query(A2aAgent).filter(A2aAgent.id.in_(wanted_a2a)).all() if wanted_a2a else []
        found_a2a = {int(a.id) for a in a2as}
        missing_a2a = [i for i in wanted_a2a if i not in found_a2a]
        if missing_a2a:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"A2A agent(s) not found: {missing_a2a}",
            )
        inactive_a2a = [a.name for a in a2as if a.status == "inactive"]
        if inactive_a2a:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A2A agent(s) inactive: {', '.join(inactive_a2a)}",
            )
        integrations["a2a_agents"] = [_snapshot_a2a(a) for a in a2as]
        db.query(A2aAgentAccess).filter(A2aAgentAccess.persona_id == agent.id).delete(
            synchronize_session=False
        )
        for aid in wanted_a2a:
            db.add(
                A2aAgentAccess(
                    agent_id=aid,
                    persona_id=agent.id,
                    access_level="all_skills",
                    allowed_skill_ids=None,
                )
            )
        a2a_result = wanted_a2a

    config["integrations"] = integrations
    entry.value = json.dumps(config)
    db.flush()
    return {"mcp_server_ids": mcp_result, "a2a_agent_ids": a2a_result}


def set_local_agent_mcp_servers(
    db: Session,
    agent: Agent,
    server_ids: list[int],
) -> list[int]:
    return set_local_agent_integrations(db, agent, mcp_server_ids=server_ids)["mcp_server_ids"]


def resolve_dynamic_mcp_servers(
    db: Session,
    agent: Agent,
    user: UserInfo,
    *,
    hub_allowed_server_ids: set[int] | None = None,
    hub_tool_allowlists: dict[int, set[str] | None] | None = None,
) -> list[dict[str, Any]]:
    """Build agent-runtime mcp_servers from linked MCPs ∩ optional Hub grants."""
    linked = linked_mcp_server_ids(agent, db)
    if hub_allowed_server_ids is not None:
        linked = [sid for sid in linked if sid in hub_allowed_server_ids]
    if not linked:
        return []

    out: list[dict[str, Any]] = []
    for sid in linked:
        server = db.query(McpServer).filter(McpServer.id == sid).first()
        if server is None or server.status == "inactive":
            continue
        try:
            rule = require_access(db, server.id, agent.id)
        except McpAccessDenied:
            logger.info(
                "Skipping MCP %s for agent %s: no access rule",
                server.id,
                agent.id,
            )
            continue

        endpoint_url = server.endpoint_url
        if server.transport_type == "stdio":
            from app.services.mcp_runtime_client import (
                McpRuntimeError,
                ensure_stdio_ready,
                facade_url,
            )
            try:
                ensure_stdio_ready(server)
            except McpRuntimeError as exc:
                logger.warning("stdio MCP %s not ready for hub/local invoke: %s", server.id, exc)
                continue
            endpoint_url = facade_url(int(server.id))
            if server.endpoint_url != endpoint_url:
                server.endpoint_url = endpoint_url

        entry: dict[str, Any] = {
            "name": server.name,
            "enabled": True,
            "transport": "streamable_http" if server.transport_type == "stdio" else server.transport_type,
            "endpoint_url": endpoint_url,
        }
        selected = allowed_tool_names(rule)
        hub_tools = None
        if hub_tool_allowlists is not None and sid in hub_tool_allowlists:
            hub_tools = hub_tool_allowlists[sid]
        if selected is not None and hub_tools is not None:
            entry["allowed_tools"] = sorted(set(selected) & hub_tools)
        elif selected is not None:
            entry["allowed_tools"] = list(selected)
        elif hub_tools is not None:
            entry["allowed_tools"] = sorted(hub_tools)

        if server.transport_type == "stdio" or server.auth_type in ("loom", "none", "", None):
            entry["auth"] = {"type": "service_bearer"}
        elif server.auth_type == "api_key":
            entry["auth"] = {
                "type": "api_key",
                "credentials_secret_arn": f"loom/mcp/{server.name}/api-key/{user.sub}",
                "api_key_header_name": server.api_key_header_name or "x-api-key",
            }
        elif server.auth_type == "oauth2":
            # Local/Hub path: prefer service bearer via loom gateway when possible;
            # keep oauth2 metadata for runtimes that support it.
            entry["auth"] = {
                "type": "oauth2",
                "well_known_endpoint": server.oauth2_well_known_url or "",
                "credential_provider_name": getattr(server, "credential_provider_name", None)
                or f"loom-{agent.name}-mcp-{server.name}",
            }
        out.append(entry)
    return out


def get_runtime_options(agent: Agent) -> dict[str, float | int]:
    """Timeout / max tool rounds from AGENT_CONFIG_JSON.options (with defaults)."""
    config = _load_config(agent)
    raw = config.get("options") if isinstance(config.get("options"), dict) else {}
    try:
        timeout_s = float(raw.get("timeout_s") or 300)
    except (TypeError, ValueError):
        timeout_s = 300.0
    try:
        max_rounds = int(raw.get("max_tool_rounds") or 20)
    except (TypeError, ValueError):
        max_rounds = 20
    timeout_s = max(5.0, min(timeout_s, 3600.0))
    max_rounds = max(1, min(max_rounds, 100))
    return {"timeout_s": timeout_s, "max_tool_rounds": max_rounds}


def set_runtime_options(
    db: Session,
    agent: Agent,
    *,
    timeout_s: float | None = None,
    max_tool_rounds: int | None = None,
) -> dict[str, float | int]:
    if agent.source != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="runtime options are only supported for source=local agents",
        )
    entry = _agent_config_entry(agent)
    if entry is None:
        raise HTTPException(status_code=400, detail="missing AGENT_CONFIG_JSON")
    config = _load_config(agent)
    current = get_runtime_options(agent)
    if timeout_s is not None:
        current["timeout_s"] = max(5.0, min(float(timeout_s), 3600.0))
    if max_tool_rounds is not None:
        current["max_tool_rounds"] = max(1, min(int(max_tool_rounds), 100))
    config["options"] = current
    entry.value = json.dumps(config)
    db.flush()
    return current
