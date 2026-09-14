"""Hub agent tools — materialize, async/sync invoke, run status (ADR 0012 / spec 025)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.dependencies.auth import UserInfo
from app.models.agent import Agent
from app.models.invocation import Invocation
from app.models.session import InvocationSession
from app.services.local_invoke import invoke_local_agent_stream, is_local_agent
from app.services.mcp_hub import user_can_invoke_agent

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")

AGENT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["prompt"],
    "properties": {
        "prompt": {"type": "string"},
        "session_id": {
            "type": "string",
            "description": "Optional; continues an existing conversation",
        },
        "wait": {
            "type": "string",
            "enum": ["accepted", "complete"],
            "default": "accepted",
            "description": "accepted=async job (default); complete=wait for result with timeout",
        },
    },
}

STATUS_TOOL: dict[str, Any] = {
    "name": "agent_run_status",
    "description": "Poll status of a Loom agent run started via agent__* tools.",
    "inputSchema": {
        "type": "object",
        "required": ["session_id"],
        "properties": {"session_id": {"type": "string"}},
    },
}

RESULT_TOOL: dict[str, Any] = {
    "name": "agent_run_result",
    "description": "Fetch final text of a completed Loom agent run.",
    "inputSchema": {
        "type": "object",
        "required": ["session_id"],
        "properties": {"session_id": {"type": "string"}},
    },
}


def agent_slug(agent: Agent) -> str:
    raw = (agent.name or f"agent-{agent.id}").lower()
    slug = _SLUG_RE.sub("-", raw).strip("-")
    return slug or f"agent-{agent.id}"


def exposed_agent_name(agent: Agent, *, collision: bool) -> str:
    slug = agent_slug(agent)
    if collision:
        return f"agent__{slug}__{agent.id}"
    return f"agent__{slug}"


def _agent_invocable(agent: Agent) -> bool:
    # Hub v1 focuses on source=local; other sources listed only if RBAC ok
    # (invoke returns hub_agent_non_local_not_supported until wired).
    _ = agent
    return True


def materialize_agents(db: Session, user: UserInfo) -> dict[str, Any]:
    if "invoke" not in (user.scopes or set()):
        return {"agents": [], "monitor_tools": []}
    agents = [a for a in db.query(Agent).all() if _agent_invocable(a) and user_can_invoke_agent(user, a)]
    slug_counts: dict[str, int] = {}
    for a in agents:
        slug_counts[agent_slug(a)] = slug_counts.get(agent_slug(a), 0) + 1
    out: list[dict[str, Any]] = []
    for a in agents:
        collide = slug_counts[agent_slug(a)] > 1
        name = exposed_agent_name(a, collision=collide)
        out.append({
            "agent_id": a.id,
            "slug": agent_slug(a),
            "exposed_name": name,
            "name": a.name or name,
            "description": (a.description or a.name or name)[:500],
            "inputSchema": AGENT_INPUT_SCHEMA,
            "source": a.source,
        })
    out.sort(key=lambda x: x["exposed_name"])
    return {
        "agents": out,
        "monitor_tools": [STATUS_TOOL, RESULT_TOOL],
    }


def resolve_agent_id_from_exposed(db: Session, user: UserInfo, exposed_name: str) -> int | None:
    mat = materialize_agents(db, user)
    for row in mat["agents"]:
        if row["exposed_name"] == exposed_name:
            return int(row["agent_id"])
    return None


def _latest_invocation(db: Session, session_id: str) -> Invocation | None:
    return (
        db.query(Invocation)
        .filter(Invocation.session_id == session_id)
        .order_by(Invocation.created_at.desc())
        .first()
    )


def get_run(db: Session, user: UserInfo, session_id: str) -> dict[str, Any]:
    session = db.query(InvocationSession).filter(InvocationSession.session_id == session_id).first()
    if session is None:
        return {"error": "not_found", "denied": False}
    if "g-admins-super" not in (user.groups or []):
        if session.user_id and session.user_id != user.username and session.user_id != user.sub:
            return {"error": "forbidden", "denied": True}
    agent = db.query(Agent).filter(Agent.id == session.agent_id).first()
    if agent is None or not user_can_invoke_agent(user, agent):
        return {"error": "forbidden", "denied": True}
    inv = _latest_invocation(db, session_id)
    text = (inv.response_text if inv else None) or ""
    preview = text[:400] if text else None
    status = session.status
    if inv and inv.status == "error":
        status = "error"
    return {
        "session_id": session.session_id,
        "invocation_id": inv.invocation_id if inv else None,
        "agent_id": session.agent_id,
        "status": status,
        "preview": preview,
        "text": text if status == "complete" else None,
        "error_message": inv.error_message if inv else None,
    }


def _parse_sse_chunks(raw: str) -> tuple[str, bool, str | None]:
    """Extract concatenated chunk text from SSE; detect session_end / error."""
    texts: list[str] = []
    saw_end = False
    err: str | None = None
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            continue
        if event == "chunk":
            piece = payload.get("text") or payload.get("content") or ""
            if piece:
                texts.append(str(piece))
        elif event == "session_end":
            saw_end = True
        elif event == "error":
            err = str(payload.get("message") or "invoke_error")
    return "".join(texts), saw_end, err


async def _consume_local_stream(
    *,
    agent_id: int,
    session_id: str,
    invocation_id: str,
    prompt: str,
    subject: str,
    groups: list[str] | None = None,
    hub_server_ids: list[int] | None = None,
    hub_tool_allowlists: dict[int, list[str]] | None = None,
) -> None:
    db = SessionLocal()
    try:
        from app.dependencies.auth import UserInfo, derive_scopes
        from app.services.local_agent_mcp import resolve_dynamic_mcp_servers

        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        session = db.query(InvocationSession).filter(InvocationSession.session_id == session_id).first()
        invocation = db.query(Invocation).filter(Invocation.invocation_id == invocation_id).first()
        if not agent or not session or not invocation:
            return
        if not is_local_agent(agent):
            invocation.status = "error"
            invocation.error_message = "hub_agent_non_local_not_supported"
            session.status = "error"
            db.commit()
            return
        user = UserInfo(
            sub=subject,
            username=subject,
            groups=list(groups or []),
            scopes=derive_scopes(list(groups or [])),
            idp_type="keycloak",
        )
        hub_ids = set(hub_server_ids) if hub_server_ids is not None else None
        hub_tools: dict[int, set[str] | None] | None = None
        if hub_tool_allowlists is not None:
            hub_tools = {int(k): set(v) for k, v in hub_tool_allowlists.items()}
        dynamic_mcp = resolve_dynamic_mcp_servers(
            db,
            agent,
            user,
            hub_allowed_server_ids=hub_ids,
            hub_tool_allowlists=hub_tools,
        )
        buf: list[str] = []
        async for piece in invoke_local_agent_stream(
            agent,
            session,
            invocation,
            db,
            time.time(),
            prompt,
            subject=subject,
            dynamic_mcp_servers=dynamic_mcp,
        ):
            buf.append(piece)
        raw = "".join(buf)
        text, saw_end, err = _parse_sse_chunks(raw)
        # Re-load after stream commits
        invocation = db.query(Invocation).filter(Invocation.invocation_id == invocation_id).first()
        session = db.query(InvocationSession).filter(InvocationSession.session_id == session_id).first()
        if invocation is None or session is None:
            return
        if text and not invocation.response_text:
            invocation.response_text = text
        if err and invocation.status != "complete":
            invocation.status = "error"
            invocation.error_message = err
            session.status = "error"
        elif saw_end or invocation.status == "complete":
            invocation.status = "complete"
            session.status = "complete"
            if text:
                invocation.response_text = text
        db.commit()
    except Exception as exc:
        logger.exception("hub agent background run failed: %s", exc)
        try:
            invocation = db.query(Invocation).filter(Invocation.invocation_id == invocation_id).first()
            session = db.query(InvocationSession).filter(InvocationSession.session_id == session_id).first()
            if invocation and session:
                invocation.status = "error"
                invocation.error_message = str(exc)[:500]
                session.status = "error"
                db.commit()
        except Exception:
            logger.exception("hub agent error finalize failed")
    finally:
        db.close()


def _create_session_and_invocation(
    db: Session,
    user: UserInfo,
    agent: Agent,
    prompt: str,
    session_id: str | None,
) -> tuple[InvocationSession, Invocation]:
    qualifier = "DEFAULT"
    available = agent.get_available_qualifiers() if hasattr(agent, "get_available_qualifiers") else ["DEFAULT"]
    if available and qualifier not in available:
        qualifier = available[0]
    if session_id:
        session = db.query(InvocationSession).filter(
            InvocationSession.agent_id == agent.id,
            InvocationSession.session_id == session_id,
        ).first()
        if session is None:
            raise ValueError("session_not_found")
        if session.user_id and session.user_id not in (user.username, user.sub):
            raise PermissionError("session_forbidden")
        session.status = "pending"
    else:
        session = InvocationSession(
            agent_id=agent.id,
            session_id=str(uuid.uuid4()),
            qualifier=qualifier,
            status="pending",
            created_at=datetime.utcnow(),
            user_id=user.username or user.sub,
        )
        db.add(session)
    invocation = Invocation(
        session_id=session.session_id,
        invocation_id=str(uuid.uuid4()),
        status="pending",
        prompt_text=prompt,
        created_at=datetime.utcnow(),
    )
    db.add(invocation)
    db.commit()
    db.refresh(session)
    db.refresh(invocation)
    return session, invocation


async def start_agent_run(
    db: Session,
    user: UserInfo,
    *,
    agent_id: int,
    prompt: str,
    session_id: str | None = None,
    mode: str = "async",
    timeout_s: int = 120,
    hub_server_ids: list[int] | None = None,
    hub_tool_allowlists: dict[int, list[str]] | None = None,
) -> dict[str, Any]:
    if "invoke" not in (user.scopes or set()):
        return {"error": "invoke_scope_required", "denied": True}
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        return {"error": "agent_not_found", "denied": False}
    if not user_can_invoke_agent(user, agent):
        return {"error": "agent_forbidden", "denied": True}
    if not is_local_agent(agent):
        return {"error": "hub_agent_non_local_not_supported", "denied": False}
    try:
        session, invocation = _create_session_and_invocation(db, user, agent, prompt, session_id)
    except PermissionError:
        return {"error": "session_forbidden", "denied": True}
    except ValueError as exc:
        return {"error": str(exc), "denied": False}

    sid = session.session_id
    iid = invocation.invocation_id
    stream_kwargs = {
        "agent_id": agent.id,
        "session_id": sid,
        "invocation_id": iid,
        "prompt": prompt,
        "subject": user.sub,
        "groups": list(user.groups or []),
        "hub_server_ids": hub_server_ids,
        "hub_tool_allowlists": hub_tool_allowlists,
    }

    if mode == "sync":
        try:
            await asyncio.wait_for(
                _consume_local_stream(**stream_kwargs),
                timeout=max(5, min(timeout_s, 600)),
            )
        except asyncio.TimeoutError:
            run = get_run(db, user, sid)
            return {
                "status": "timeout",
                "session_id": sid,
                "invocation_id": iid,
                "agent_id": agent.id,
                "text": run.get("text") or run.get("preview"),
            }
        run = get_run(db, user, sid)
        return {
            "status": "ok" if run.get("status") == "complete" else (run.get("status") or "error"),
            "session_id": sid,
            "invocation_id": iid,
            "agent_id": agent.id,
            "text": run.get("text"),
            "error_message": run.get("error_message"),
        }

    asyncio.create_task(_consume_local_stream(**stream_kwargs))
    return {
        "status": "accepted",
        "session_id": sid,
        "invocation_id": iid,
        "agent_id": agent.id,
        "text": None,
    }
