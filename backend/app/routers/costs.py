"""Cost dashboard endpoints for aggregated cost data."""
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.invocation import Invocation
from app.models.session import InvocationSession
from app.routers.agents import AGENTCORE_RUNTIME_PRICING
from app.models.memory import Memory
from app.services.cloudwatch import (
    get_memory_log_events,
    get_usage_log_events_by_time,
    parse_memory_log_events,
    parse_usage_events,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["costs"])

_ZERO_COSTS: dict[str, Any] = {
    "total_invocations": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_estimated_cost": 0.0,
    "total_compute_cpu_cost": 0.0,
    "total_compute_memory_cost": 0.0,
    "total_idle_cpu_cost": 0.0,
    "total_idle_memory_cost": 0.0,
    "total_stm_cost": 0.0,
    "total_ltm_cost": 0.0,
}


@router.get("/costs")
def get_cost_dashboard(
    group: str | None = Query(None, description="Filter by loom:group tag"),
    days: int = Query(30, description="Number of days to aggregate (0 = all time)"),
    user: UserInfo = Depends(require_scopes("costs:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Aggregate cost data across agents, optionally filtered by group tag."""
    # Build agent query
    agents = db.query(Agent).all()

    # Filter by group parameter (for View As) or user's groups
    # - Admins (t-admin): See ALL resources including untagged (unless group param is set for View As)
    # - Users (t-user): See only resources tagged with their groups (g-users-* → strip prefix)
    if group:
        # Explicit group filter (used by admins for View As)
        agents = [a for a in agents if a.get_tags().get("loom:group") == group]
    elif "t-admin" not in user.groups:
        # User view: filter by group tags (strip "g-users-" prefix)
        user_groups = [g for g in user.groups if g.startswith("g-users-")]
        allowed_tags = [g.replace("g-users-", "", 1) for g in user_groups]
        agents = [a for a in agents if a.get_tags().get("loom:group") in allowed_tags]
        # Use first group tag for display purposes
        group = allowed_tags[0] if allowed_tags else None

    agent_ids = [a.id for a in agents]

    if not agent_ids:
        return {"group": group, "days": days, **_ZERO_COSTS, "agents": []}

    # Build invocation query with time filter
    inv_query = db.query(Invocation).join(
        InvocationSession, Invocation.session_id == InvocationSession.session_id
    ).filter(InvocationSession.agent_id.in_(agent_ids))

    if days > 0:
        cutoff = datetime.utcnow() - timedelta(days=days)
        inv_query = inv_query.filter(Invocation.created_at >= cutoff)

    # Apply I/O wait discount at view time (DB stores raw CPU cost)
    from app.routers.settings import get_cpu_io_wait_discount
    from app.routers.invocations import compute_live_status, _backfill_idle_costs
    io_discount = get_cpu_io_wait_discount(db)
    cpu_factor = 1.0 - io_discount

    # Recompute idle costs for all sessions in scope (uses current pricing defaults)
    sessions_in_scope = db.query(InvocationSession).filter(
        InvocationSession.agent_id.in_(agent_ids)
    ).all()
    for sess in sessions_in_scope:
        live_status = compute_live_status(sess, db)
        _backfill_idle_costs(sess, live_status, db)

    # Aggregate per agent
    agent_costs: list[dict[str, Any]] = []
    totals = {k: 0 if isinstance(v, int) else 0.0 for k, v in _ZERO_COSTS.items()}

    for agent in agents:
        q = inv_query.filter(InvocationSession.agent_id == agent.id)

        inv_count = q.count()

        # Include agents even if they have zero invocations (show $0 costs)
        if inv_count == 0:
            input_sum = output_sum = 0
            est_cost = duration_ms_sum = idle_cpu = idle_mem = stm = ltm = 0.0
            rt_cpu = compute_mem = rt_mem = rt_total = mem_total = grand_total = 0.0
        else:
            input_sum = q.with_entities(func.sum(Invocation.input_tokens)).scalar() or 0
            output_sum = q.with_entities(func.sum(Invocation.output_tokens)).scalar() or 0
            est_cost = q.with_entities(func.sum(Invocation.estimated_cost)).scalar() or 0.0
            duration_ms_sum = q.with_entities(func.sum(Invocation.client_duration_ms)).scalar() or 0.0
            idle_cpu = q.with_entities(func.sum(Invocation.idle_cpu_cost)).scalar() or 0.0
            idle_mem = q.with_entities(func.sum(Invocation.idle_memory_cost)).scalar() or 0.0
            stm = q.with_entities(func.sum(Invocation.stm_cost)).scalar() or 0.0
            ltm = q.with_entities(func.sum(Invocation.ltm_cost)).scalar() or 0.0

            # Recompute CPU and memory from duration using current pricing defaults
            total_hours = duration_ms_sum / 1000 / 3600
            compute_cpu = total_hours * AGENTCORE_RUNTIME_PRICING["default_vcpu"] * AGENTCORE_RUNTIME_PRICING["cpu_per_vcpu_hour"]
            compute_mem = total_hours * AGENTCORE_RUNTIME_PRICING["default_memory_gb"] * AGENTCORE_RUNTIME_PRICING["memory_per_gb_hour"]

            # Derived totals — apply I/O wait discount to CPU; idle is memory only
            rt_cpu = compute_cpu * cpu_factor
            rt_mem = compute_mem + idle_mem
            rt_total = rt_cpu + rt_mem
            mem_total = stm + ltm
            grand_total = est_cost + rt_total + mem_total

        entry: dict[str, Any] = {
            "agent_id": agent.id,
            "agent_name": agent.name,
            "model_id": None,
            "total_invocations": inv_count,
            "total_input_tokens": input_sum,
            "total_output_tokens": output_sum,
            "total_estimated_cost": round(est_cost, 6),
            "total_compute_cpu_cost": round(rt_cpu, 6),
            "total_compute_memory_cost": round(compute_mem, 6),
            "total_idle_cpu_cost": round(idle_cpu, 6),
            "total_idle_memory_cost": round(idle_mem, 6),
            "total_stm_cost": round(stm, 6),
            "total_ltm_cost": round(ltm, 6),
            "avg_cost_per_invocation": round(grand_total / inv_count, 6) if inv_count else 0,
        }

        # Extract model_id from config entries
        config_map = {e.key: e.value for e in agent.config_entries}
        config_json_str = config_map.get("AGENT_CONFIG_JSON", "")
        if config_json_str:
            try:
                config = json.loads(config_json_str)
                entry["model_id"] = config.get("model_id")
            except (json.JSONDecodeError, TypeError):
                pass

        agent_costs.append(entry)

        totals["total_invocations"] += inv_count
        totals["total_input_tokens"] += input_sum
        totals["total_output_tokens"] += output_sum
        totals["total_estimated_cost"] += est_cost
        totals["total_compute_cpu_cost"] += rt_cpu
        totals["total_compute_memory_cost"] += compute_mem
        totals["total_idle_cpu_cost"] += idle_cpu
        totals["total_idle_memory_cost"] += idle_mem
        totals["total_stm_cost"] += stm
        totals["total_ltm_cost"] += ltm

    # Round float totals
    for k, v in totals.items():
        if isinstance(v, float):
            totals[k] = round(v, 6)

    return {
        "group": group,
        "days": days,
        **totals,
        "agents": sorted(agent_costs, key=lambda x: (
            x["total_estimated_cost"]
            + x["total_compute_cpu_cost"]
            + x["total_compute_memory_cost"] + x["total_idle_memory_cost"]
            + x["total_stm_cost"] + x["total_ltm_cost"]
        ), reverse=True),
    }


# ---------------------------------------------------------------------------
# On-demand cost actuals from USAGE_LOGS
# ---------------------------------------------------------------------------


@router.post("/costs/actuals")
def pull_cost_actuals(
    group: str | None = Query(None, description="Filter by loom:group tag"),
    days: int = Query(30, description="Number of days to query (0 = all time)"),
    user: UserInfo = Depends(require_scopes("costs:read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Pull all usage log events from CloudWatch for agents in scope.

    Queries the ``BedrockAgentCoreRuntime_UsageLogs`` stream for each
    agent runtime and returns every event with computed costs.  Filtering
    and matching to invocations is left to the caller.

    Does NOT update stored costs — this is a read-only view.
    """
    # Find agents in scope
    agents = db.query(Agent).all()

    # Filter by group parameter (for View As) or user's groups
    # - Admins (t-admin): See ALL resources including untagged (unless group param is set for View As)
    # - Users (t-user): See only resources tagged with their groups (g-users-* → strip prefix)
    if group:
        # Explicit group filter (used by admins for View As)
        agents = [a for a in agents if a.get_tags().get("loom:group") == group]
    elif "t-admin" not in user.groups:
        # User view: filter by group tags (strip "g-users-" prefix)
        user_groups = [g for g in user.groups if g.startswith("g-users-")]
        allowed_tags = [g.replace("g-users-", "", 1) for g in user_groups]
        agents = [a for a in agents if a.get_tags().get("loom:group") in allowed_tags]
        # Use first group tag for display purposes
        group = allowed_tags[0] if allowed_tags else None

    if not agents:
        return {"group": group, "days": days, "agents": [], "summary": {"total_events": 0}}

    # Determine time window
    if days > 0:
        cutoff = datetime.utcnow() - timedelta(days=days)
        start_ms = int(cutoff.timestamp() * 1000)
    else:
        start_ms = 0
    end_ms = int(datetime.utcnow().timestamp() * 1000)

    # I/O wait discount for display
    from app.routers.settings import get_cpu_io_wait_discount
    io_discount = get_cpu_io_wait_discount(db)
    cpu_factor = 1.0 - io_discount

    # Group agents by (runtime_id, region) to deduplicate queries
    runtime_to_agents: dict[tuple[str, str], list[Agent]] = {}
    for agent in agents:
        if not agent.runtime_id:
            continue
        key = (agent.runtime_id, agent.region)
        runtime_to_agents.setdefault(key, []).append(agent)

    agent_results: list[dict[str, Any]] = []
    total_events = 0

    for (runtime_id, region), agent_list in runtime_to_agents.items():
        log_group = f"/aws/vendedlogs/bedrock-agentcore/runtimes/{runtime_id}"
        logger.info("[cost_actuals] Querying %s (stream=BedrockAgentCoreRuntime_UsageLogs) start=%s end=%s",
                     log_group, start_ms, end_ms)

        try:
            raw_events = get_usage_log_events_by_time(
                runtime_id=runtime_id, region=region,
                start_time_ms=start_ms, end_time_ms=end_ms,
            )
        except Exception as e:
            logger.warning("Failed to get USAGE_LOGS for runtime %s: %s", runtime_id, e)
            continue

        logger.info("[cost_actuals] Got %d raw events for runtime %s", len(raw_events), runtime_id)
        usage_events = parse_usage_events(raw_events)
        logger.info("[cost_actuals] Parsed %d usage events for runtime %s", len(usage_events), runtime_id)
        if not usage_events:
            continue

        total_events += len(usage_events)

        # Aggregate by (agent_name, session_id) — include all events for the
        # runtime within the time window.  USAGE_LOGS session IDs may differ
        # from Loom's runtimeSessionId, so we cannot filter by tracked sessions.
        session_agg: dict[tuple[str | None, str | None], dict[str, Any]] = {}
        for ue in usage_events:
            sid = ue.get("session_id")
            key = (ue.get("agent_name"), sid)
            if key not in session_agg:
                session_agg[key] = {
                    "agent_name": ue.get("agent_name"),
                    "session_id": ue.get("session_id"),
                    "vcpu_hours": 0.0,
                    "memory_gb_hours": 0.0,
                    "event_count": 0,
                    "first_timestamp": ue.get("event_timestamp"),
                    "last_timestamp": ue.get("event_timestamp"),
                    "first_epoch": ue.get("event_timestamp_epoch"),
                    "last_epoch": ue.get("event_timestamp_epoch"),
                }
            agg = session_agg[key]
            agg["vcpu_hours"] += ue["vcpu_hours"]
            agg["memory_gb_hours"] += ue["memory_gb_hours"]
            agg["event_count"] += 1
            evt_epoch = ue.get("event_timestamp_epoch")
            if evt_epoch is not None:
                if agg["first_epoch"] is None or evt_epoch < agg["first_epoch"]:
                    agg["first_epoch"] = evt_epoch
                    agg["first_timestamp"] = ue.get("event_timestamp")
                if agg["last_epoch"] is None or evt_epoch > agg["last_epoch"]:
                    agg["last_epoch"] = evt_epoch
                    agg["last_timestamp"] = ue.get("event_timestamp")

        # Build session-level results with computed costs
        sessions_out: list[dict[str, Any]] = []
        for agg in session_agg.values():
            cpu_cost_raw = round(agg["vcpu_hours"] * AGENTCORE_RUNTIME_PRICING["cpu_per_vcpu_hour"], 6)
            mem_cost = round(agg["memory_gb_hours"] * AGENTCORE_RUNTIME_PRICING["memory_per_gb_hour"], 6)
            cpu_cost = round(cpu_cost_raw * cpu_factor, 6)
            sessions_out.append({
                "agent_name": agg["agent_name"],
                "session_id": agg["session_id"],
                "event_count": agg["event_count"],
                "first_timestamp": agg["first_timestamp"],
                "last_timestamp": agg["last_timestamp"],
                "vcpu_hours": round(agg["vcpu_hours"], 8),
                "memory_gb_hours": round(agg["memory_gb_hours"], 8),
                "cpu_cost": cpu_cost,
                "memory_cost": mem_cost,
                "total_cost": round(cpu_cost + mem_cost, 6),
            })

        # Sort by first timestamp descending
        sessions_out.sort(key=lambda s: s.get("first_timestamp") or "", reverse=True)

        # Use first agent name from DB for display
        db_agent_name = agent_list[0].name
        db_agent_id = agent_list[0].id

        agent_results.append({
            "agent_id": db_agent_id,
            "agent_name": db_agent_name,
            "runtime_id": runtime_id,
            "log_group": log_group,
            "sessions": sessions_out,
            "total_cpu_cost": round(sum(s["cpu_cost"] for s in sessions_out), 6),
            "total_memory_cost": round(sum(s["memory_cost"] for s in sessions_out), 6),
            "total_cost": round(sum(s["total_cost"] for s in sessions_out), 6),
        })

    # ------------------------------------------------------------------
    # Memory actuals from APPLICATION_LOGS per memory resource (vendedlogs)
    # ------------------------------------------------------------------
    memory_results: list[dict[str, Any]] = []

    # Find all memory resources linked to agents in scope
    from app.models.config_entry import ConfigEntry
    agent_ids_in_scope = [a.id for a in agents]
    config_entries = db.query(ConfigEntry).filter(
        ConfigEntry.agent_id.in_(agent_ids_in_scope),
        ConfigEntry.key == "AGENT_CONFIG_JSON",
    ).all()

    # Map memory_id → set of agent IDs that use it
    memory_to_agent_ids: dict[str, set[int]] = {}
    for entry in config_entries:
        try:
            cfg = json.loads(entry.value)
            for res in cfg.get("integrations", {}).get("memory", {}).get("resources", []):
                mid = res.get("memory_id")
                if mid:
                    memory_to_agent_ids.setdefault(mid, set()).add(entry.agent_id)
        except (json.JSONDecodeError, TypeError):
            pass

    # Also include all Memory records in the DB (covers imported memories), filtered by group
    all_memories = db.query(Memory).filter(Memory.memory_id.isnot(None)).all()

    # Filter memories by group parameter (for View As) or user's groups (same logic as agents)
    if group:
        # Explicit group filter (used by admins for View As)
        all_memories = [m for m in all_memories if m.get_tags().get("loom:group") == group]
    elif "t-admin" not in user.groups:
        # User view: filter by group tags (strip "g-users-" prefix)
        user_groups = [g for g in user.groups if g.startswith("g-users-")]
        allowed_tags = [g.replace("g-users-", "", 1) for g in user_groups]
        all_memories = [m for m in all_memories if m.get_tags().get("loom:group") in allowed_tags]

    for mem in all_memories:
        if mem.memory_id:
            memory_to_agent_ids.setdefault(mem.memory_id, set())

    for mid, agent_ids in memory_to_agent_ids.items():
        mem_record = db.query(Memory).filter(Memory.memory_id == mid).first()
        region = mem_record.region if mem_record else "us-east-1"
        display_name = mem_record.name if mem_record else mid

        log_group_name = f"/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/{mid}"
        logger.info("[cost_actuals] Querying memory logs: %s (no session filter — memory session IDs differ from runtime)",
                     log_group_name)

        try:
            raw = get_memory_log_events(
                memory_id=mid, region=region,
                start_time_ms=start_ms, end_time_ms=end_ms,
            )
        except Exception as e:
            logger.warning("Failed to get memory logs for %s: %s", mid, e)
            continue

        if not raw:
            continue

        parsed = parse_memory_log_events(raw)
        logger.info("[cost_actuals] Memory %s: %d matched log events, %d retrievals, %d records stored, %d extractions, %d consolidations",
                     mid, parsed["total_log_events"], parsed["retrieve_records"], parsed["records_stored"],
                     parsed["extractions"], parsed["consolidations"])

        memory_results.append({
            "memory_id": mid,
            "memory_name": display_name,
            "log_group": log_group_name,
            **parsed,
        })

    return {
        "group": group,
        "days": days,
        "io_wait_discount_percent": round(io_discount * 100),
        "agents": agent_results,
        "memory": memory_results,
        "summary": {"total_events": total_events},
    }
