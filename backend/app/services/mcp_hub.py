"""MCP Hub control-plane helpers (ADR 0007, specs 016-019)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.dependencies.auth import UserInfo
from app.models.agent import Agent
from app.models.mcp import McpServer, McpServerAccess, McpTool
from app.models.mcp_hub import McpHubSession
from app.services.mcp import invoke_mcp_tool
from app.services.mcp_access import allowed_tool_names, get_access_rule
from app.services.mcp_runtime_client import ensure_stdio_ready

CONTRACT_VERSION = "2026-09-hub-1"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def hub_session_ttl_s() -> int:
    raw = int(os.getenv("MCP_HUB_SESSION_TTL_S", str(8 * 3600)))
    return max(60, min(raw, 24 * 3600))


def hub_public_url() -> str:
    return os.getenv("MCP_HUB_PUBLIC_URL", "http://127.0.0.1:8790/mcp").rstrip("/")


def hub_service_token() -> str:
    return os.environ.get("MCP_HUB_SERVICE_TOKEN", "").strip()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_session(db: Session, user: UserInfo, client_label: str | None = None) -> dict[str, Any]:
    token = "hs_" + secrets.token_urlsafe(32)
    session_id = str(uuid.uuid4())
    now = datetime.utcnow()
    expires = now + timedelta(seconds=hub_session_ttl_s())
    row = McpHubSession(
        id=session_id,
        token_hash=hash_token(token),
        subject=user.sub,
        idp_type=user.idp_type or "unknown",
        scopes_json=json.dumps(sorted(user.scopes or [])),
        groups_json=json.dumps(list(user.groups or [])),
        created_at=now,
        expires_at=expires,
        client_label=client_label,
    )
    db.add(row)
    db.commit()
    return {
        "hub_session_token": token,
        "hub_session_id": session_id,
        "mcp_hub_url": hub_public_url(),
        "expires_at": _iso_z(expires),
        "contract_version": CONTRACT_VERSION,
    }


def introspect_token(db: Session, token: str) -> dict[str, Any]:
    if not token or not token.startswith("hs_"):
        return {"active": False}
    row = db.query(McpHubSession).filter(McpHubSession.token_hash == hash_token(token)).first()
    if row is None or row.revoked_at is not None:
        return {"active": False}
    if row.expires_at <= datetime.utcnow():
        return {"active": False}
    scopes: list[str] = []
    if row.scopes_json:
        try:
            scopes = list(json.loads(row.scopes_json))
        except json.JSONDecodeError:
            scopes = []
    return {
        "active": True,
        "hub_session_id": row.id,
        "subject": row.subject,
        "idp_type": row.idp_type,
        "scopes": scopes,
        "expires_at": _iso_z(row.expires_at),
    }


def revoke_session(db: Session, session_id: str, user: UserInfo) -> bool:
    row = db.query(McpHubSession).filter(McpHubSession.id == session_id).first()
    if row is None or row.subject != user.sub:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.commit()
    return True


def get_session(db: Session, session_id: str) -> McpHubSession | None:
    return db.query(McpHubSession).filter(McpHubSession.id == session_id).first()


def user_can_invoke_agent(user: UserInfo, agent: Agent) -> bool:
    if "g-admins-super" in (user.groups or []):
        return True
    tags = agent.get_tags() if hasattr(agent, "get_tags") else {}
    agent_group = (tags or {}).get("loom:group", "") or ""
    if not agent_group:
        return True
    if "t-admin" in (user.groups or []):
        admin_groups = [g for g in user.groups if g.startswith("g-admins-")]
        allowed = [g.replace("g-admins-", "", 1) for g in admin_groups]
    else:
        user_groups = [g for g in user.groups if g.startswith("g-users-")]
        allowed = [g.replace("g-users-", "", 1) for g in user_groups]
    return agent_group in allowed


def server_slug(server: McpServer) -> str:
    raw = (server.template_id or server.name or f"server-{server.id}").lower()
    slug = _SLUG_RE.sub("-", raw).strip("-")
    return slug or f"server-{server.id}"


def build_allowlist(db: Session, user: UserInfo) -> dict[str, Any]:
    agents = db.query(Agent).all()
    invocavel = [a for a in agents if user_can_invoke_agent(user, a)]
    per_server: dict[int, set[str] | None] = {}
    for agent in invocavel:
        rules = db.query(McpServerAccess).filter(McpServerAccess.persona_id == agent.id).all()
        for rule in rules:
            names = allowed_tool_names(rule)
            if names is None:
                per_server[rule.server_id] = None
                continue
            current = per_server.get(rule.server_id, "__missing__")
            if current == "__missing__":
                per_server[rule.server_id] = set(names)
            elif current is None:
                continue
            else:
                current.update(names)

    entries: list[dict[str, Any]] = []
    for server_id, allowed in per_server.items():
        server = db.query(McpServer).filter(McpServer.id == server_id).first()
        if server is None or server.status == "inactive":
            continue
        tools_rows = db.query(McpTool).filter(McpTool.server_id == server_id).all()
        tools: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in tools_rows:
            if allowed is not None and row.tool_name not in allowed:
                continue
            seen.add(row.tool_name)
            tools.append({
                "name": row.tool_name,
                "description": row.description or "",
                "inputSchema": row.get_input_schema() or {"type": "object", "properties": {}},
            })
        if allowed is not None:
            for name in sorted(allowed):
                if name in seen:
                    continue
                tools.append({
                    "name": name,
                    "description": "",
                    "inputSchema": {"type": "object", "properties": {}},
                })
        if not tools:
            continue
        transport = "streamable_http" if server.transport_type == "stdio" else server.transport_type
        entries.append({
            "server_id": server.id,
            "server_slug": server_slug(server),
            "endpoint_url": server.endpoint_url,
            "transport": transport,
            "tools": tools,
        })

    return {
        "subject": user.sub,
        "entries": entries,
        "generated_at": _iso_z(datetime.utcnow()),
    }


def expose_tools(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, tuple[int, str]]]:
    name_owners: dict[str, list[tuple[int, str, dict[str, Any], str]]] = {}
    for entry in entries:
        sid = int(entry["server_id"])
        slug = str(entry["server_slug"])
        for tool in entry.get("tools") or []:
            original = str(tool["name"])
            name_owners.setdefault(original, []).append((sid, slug, tool, original))

    exposed: list[dict[str, Any]] = []
    mapping: dict[str, tuple[int, str]] = {}
    for _original, owners in name_owners.items():
        collide = len({sid for sid, _, _, _ in owners}) > 1
        for sid, slug, tool, orig in owners:
            exposed_name = f"{slug}__{orig}" if collide else orig
            mapping[exposed_name] = (sid, orig)
            exposed.append({
                "name": exposed_name,
                "description": tool.get("description") or "",
                "inputSchema": tool.get("inputSchema") or {"type": "object", "properties": {}},
            })
    exposed.sort(key=lambda t: t["name"])
    return exposed, mapping


def call_hub_tool(db: Session, user: UserInfo, exposed_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    allowlist = build_allowlist(db, user)
    _exposed, mapping = expose_tools(allowlist["entries"])
    if exposed_name not in mapping:
        return {"success": False, "error": "tool_not_allowed", "denied": True}
    server_id, original = mapping[exposed_name]
    server = db.query(McpServer).filter(McpServer.id == server_id).first()
    if server is None:
        return {"success": False, "error": "server_not_found", "denied": True}
    if not _subject_still_allows(db, user, server_id, original):
        return {"success": False, "error": "tool_not_allowed", "denied": True}
    if server.transport_type == "stdio":
        try:
            ensure_stdio_ready(server)
        except Exception:
            return {"success": False, "error": "stdio_not_ready", "denied": False}
    return invoke_mcp_tool(server, original, arguments or {})


def _subject_still_allows(db: Session, user: UserInfo, server_id: int, tool_name: str) -> bool:
    for agent in db.query(Agent).all():
        if not user_can_invoke_agent(user, agent):
            continue
        rule = get_access_rule(db, server_id, agent.id)
        if rule is None:
            continue
        names = allowed_tool_names(rule)
        if names is None or tool_name in names:
            return True
    return False


def user_from_hub_session(db: Session, session_id: str) -> UserInfo | None:
    row = get_session(db, session_id)
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at <= datetime.utcnow():
        return None
    scopes: set[str] = set()
    if row.scopes_json:
        try:
            scopes = set(json.loads(row.scopes_json))
        except json.JSONDecodeError:
            scopes = set()
    groups: list[str] = []
    if row.groups_json:
        try:
            groups = list(json.loads(row.groups_json))
        except json.JSONDecodeError:
            groups = []
    if not groups:
        if "admin:write" in scopes:
            groups = ["t-admin", "g-admins-super"]
        elif "invoke" in scopes:
            groups = ["t-user", "g-users-demo"]
    return UserInfo(
        sub=row.subject,
        username=row.subject,
        groups=groups,
        scopes=scopes,
        idp_type=row.idp_type,
    )


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
