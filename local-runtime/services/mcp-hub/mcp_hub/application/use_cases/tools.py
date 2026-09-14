"""tools/list and tools/call use cases (MCP + agent__*)."""
from __future__ import annotations

import logging
from typing import Any

from mcp_hub.application.ports import HubStore, LoomGateway
from mcp_hub.application.use_cases.session_allowlist import build_session_allowlist
from mcp_hub.domain.naming import expose_tools

logger = logging.getLogger("mcp_hub")


def mcp_tool_result(text: str, structured: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }
    if is_error:
        out["isError"] = True
    return out


def list_agent_tools(
    identity: dict[str, Any],
    client: dict[str, Any],
    *,
    loom: LoomGateway,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return MCP tool defs + map exposed_name → agent_id when agents_enabled."""
    if not bool(client.get("agents_enabled")):
        return [], {}
    code, payload = loom.materialize_agents(
        subject=str(identity["sub"]),
        groups=list(identity.get("groups") or []),
    )
    if code != 200:
        logger.warning("materialize-agents failed status=%s", code)
        return [], {}
    tools: list[dict[str, Any]] = []
    agent_map: dict[str, int] = {}
    for row in payload.get("agents") or []:
        name = str(row.get("exposed_name") or "")
        if not name:
            continue
        tools.append({
            "name": name,
            "description": row.get("description") or row.get("name") or name,
            "inputSchema": row.get("inputSchema") or {"type": "object", "properties": {}},
        })
        try:
            agent_map[name] = int(row["agent_id"])
        except (KeyError, TypeError, ValueError):
            continue
    for mon in payload.get("monitor_tools") or []:
        if isinstance(mon, dict) and mon.get("name"):
            tools.append(mon)
    return tools, agent_map


def handle_agent_tool_call(
    identity: dict[str, Any],
    name: str,
    arguments: dict[str, Any],
    agent_map: dict[str, int],
    *,
    loom: LoomGateway,
) -> dict[str, Any]:
    subject = str(identity["sub"])
    groups = list(identity.get("groups") or [])
    if name == "agent_run_status":
        sid = str(arguments.get("session_id") or "")
        if not sid:
            return {"jsonrpc": "2.0", "error": {"code": -32602, "message": "session_id_required"}}
        status, result = loom.agents_run(subject=subject, groups=groups, session_id=sid)
        if status == 403:
            return {"error": {"code": -32003, "message": "forbidden"}}
        if status != 200:
            return {"error": {"code": -32004, "message": "run_status_failed"}}
        text = f"status={result.get('status')} session_id={sid}"
        return {"result": mcp_tool_result(text, result)}
    if name == "agent_run_result":
        sid = str(arguments.get("session_id") or "")
        if not sid:
            return {"error": {"code": -32602, "message": "session_id_required"}}
        status, result = loom.agents_run(subject=subject, groups=groups, session_id=sid)
        if status == 403:
            return {"error": {"code": -32003, "message": "forbidden"}}
        if status != 200:
            return {"error": {"code": -32004, "message": "run_result_failed"}}
        if result.get("status") != "complete":
            return {
                "result": mcp_tool_result(
                    f"Run not complete yet (status={result.get('status')})",
                    result,
                    is_error=True,
                )
            }
        return {"result": mcp_tool_result(str(result.get("text") or ""), result)}
    if name.startswith("agent__"):
        agent_id = agent_map.get(name)
        if agent_id is None:
            code, payload = loom.materialize_agents(subject=subject, groups=groups)
            if code == 200:
                for row in payload.get("agents") or []:
                    if row.get("exposed_name") == name:
                        try:
                            agent_id = int(row["agent_id"])
                        except (TypeError, ValueError):
                            agent_id = None
                        break
        if agent_id is None:
            return {"error": {"code": -32003, "message": "tool_not_allowed"}}
        prompt = str(arguments.get("prompt") or "")
        if not prompt:
            return {"error": {"code": -32602, "message": "prompt_required"}}
        wait = str(arguments.get("wait") or "accepted")
        mode = "sync" if wait == "complete" else "async"
        sid = arguments.get("session_id")
        status, result = loom.agents_invoke(
            subject=subject,
            groups=groups,
            agent_id=agent_id,
            prompt=prompt,
            session_id=str(sid) if sid else None,
            mode=mode,
        )
        if status == 403:
            return {"error": {"code": -32003, "message": "agent_forbidden"}}
        if status >= 400:
            detail = result.get("detail") or result.get("error") or "invoke_failed"
            return {"error": {"code": -32004, "message": str(detail)}}
        st = str(result.get("status") or "")
        text = (
            f"Run accepted. session_id={result.get('session_id')}"
            if st == "accepted"
            else (result.get("text") or f"status={st} session_id={result.get('session_id')}")
        )
        return {"result": mcp_tool_result(str(text), result, is_error=st in ("error",))}
    return {"error": {"code": -32003, "message": "tool_not_allowed"}}


def list_tools(
    identity: dict[str, Any],
    *,
    store: HubStore,
    loom: LoomGateway,
) -> list[dict[str, Any]]:
    _slug, allow, _mapping, client = build_session_allowlist(identity, store=store, loom=loom)
    tools, _ = expose_tools(allow.get("entries") or [])
    if client and str(client.get("status") or "") == "enabled":
        agent_tools, _amap = list_agent_tools(identity, client, loom=loom)
        tools = list(tools) + list(agent_tools)
        tools.sort(key=lambda t: t.get("name") or "")
    return tools


def call_tool(
    identity: dict[str, Any],
    *,
    name: str,
    arguments: dict[str, Any],
    store: HubStore,
    loom: LoomGateway,
) -> dict[str, Any]:
    """Return JSON-RPC ``result`` or ``error`` object (without jsonrpc/id wrapper)."""
    groups = list(identity.get("groups") or [])
    _slug, _allow, mapping, client = build_session_allowlist(identity, store=store, loom=loom)
    if not isinstance(arguments, dict):
        arguments = {}
    agents_on = bool(client and client.get("agents_enabled") and client.get("status") == "enabled")
    if name.startswith("agent__") or name in ("agent_run_status", "agent_run_result"):
        if not agents_on:
            return {"error": {"code": -32003, "message": "agents_disabled"}}
        _agent_tools, agent_map = list_agent_tools(identity, client or {}, loom=loom)
        handled = handle_agent_tool_call(identity, name, arguments, agent_map, loom=loom)
        if "error" in handled and "result" not in handled:
            return {"error": handled["error"]}
        return {"result": handled.get("result") or {}}
    if name not in mapping:
        return {"error": {"code": -32003, "message": "tool_not_allowed"}}
    server_id, original = mapping[name]
    status, result = loom.tools_call(
        subject=str(identity["sub"]),
        groups=groups,
        tool_name=name,
        arguments=arguments,
        server_id=server_id,
        original_tool_name=original,
    )
    if status == 403:
        return {"error": {"code": -32003, "message": "tool_not_allowed"}}
    if status != 200 or not result.get("success"):
        return {"error": {"code": -32004, "message": "tool_call_failed"}}
    return {"result": result.get("result") or {}}
