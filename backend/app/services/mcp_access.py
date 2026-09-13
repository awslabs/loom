"""User → Agent → MCP → Tool authorization. Deny when no McpServerAccess rule exists."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.mcp import McpServer, McpServerAccess


class McpAccessDenied(Exception):
    """Agent has no rule, or the tool is outside selected_tools."""


def get_access_rule(db: Session, server_id: int, agent_id: int) -> McpServerAccess | None:
    return (
        db.query(McpServerAccess)
        .filter(
            McpServerAccess.server_id == server_id,
            McpServerAccess.persona_id == agent_id,
        )
        .first()
    )


def require_access(db: Session, server_id: int, agent_id: int) -> McpServerAccess:
    rule = get_access_rule(db, server_id, agent_id)
    if rule is None:
        raise McpAccessDenied(f"no access rule for agent {agent_id} on MCP server {server_id}")
    return rule


def allowed_tool_names(rule: McpServerAccess) -> list[str] | None:
    """None means all tools. A list is an allowlist."""
    if rule.access_level == "all_tools":
        return None
    return rule.get_allowed_tool_names() or []


def assert_tool_allowed(rule: McpServerAccess, tool_name: str) -> None:
    names = allowed_tool_names(rule)
    if names is not None and tool_name not in names:
        raise McpAccessDenied(f"tool {tool_name!r} is not allowed")


def require_access_or_403(db: Session, server_id: int, agent_id: int) -> McpServerAccess:
    try:
        return require_access(db, server_id, agent_id)
    except McpAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


def reject_stdio_for_agentcore(servers: list[McpServer]) -> None:
    names = [server.name for server in servers if server.transport_type == "stdio"]
    if names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stdio MCP cannot be deployed to AgentCore: {', '.join(names)}",
        )
