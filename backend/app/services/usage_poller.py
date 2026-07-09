"""Background poller that updates estimated compute costs with actual USAGE_LOGS data.

Runs every 10 minutes and:
1. Finds invocations with cost_source="estimated" and status="complete".
2. Groups them by agent runtime_id.
3. Polls the USAGE_LOGS for each runtime.
4. Matches usage log events to invocations by event_timestamp within 5 seconds.
5. Updates matched invocations with actual costs and sets cost_source="usage_logs".
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.invocation import Invocation
from app.models.session import InvocationSession
from app.models.agent import Agent
from app.routers.agents import AGENTCORE_RUNTIME_PRICING
from app.services.cloudwatch import (
    get_usage_log_events_by_time,
    parse_usage_events,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 600  # 10 minutes
TIMESTAMP_TOLERANCE_SECONDS = 5.0


def _poll_once() -> int:
    """Run a single poll cycle. Returns the number of invocations updated."""
    db: Session = SessionLocal()
    updated_count = 0

    try:
        # Find invocations with estimated costs that are complete
        pending = (
            db.query(Invocation)
            .filter(
                Invocation.cost_source == "estimated",
                Invocation.status == "complete",
                Invocation.client_invoke_time.isnot(None),
                Invocation.client_done_time.isnot(None),
            )
            .all()
        )

        if not pending:
            return 0

        logger.info("[usage_poller] Found %d invocations with estimated costs", len(pending))

        # Group by session → agent to get runtime_id and region
        session_ids = list({inv.session_id for inv in pending})
        sessions = (
            db.query(InvocationSession)
            .filter(InvocationSession.session_id.in_(session_ids))
            .all()
        )
        session_to_agent: dict[str, int] = {s.session_id: s.agent_id for s in sessions}

        agent_ids = list(set(session_to_agent.values()))
        agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
        agent_map = {a.id: a for a in agents}

        # Group invocations by (runtime_id, region)
        runtime_groups: dict[tuple[str, str], list[Invocation]] = {}
        for inv in pending:
            agent_id = session_to_agent.get(inv.session_id)
            if not agent_id:
                continue
            agent = agent_map.get(agent_id)
            if not agent or not agent.runtime_id:
                continue
            key = (agent.runtime_id, agent.region)
            runtime_groups.setdefault(key, []).append(inv)

        # Poll USAGE_LOGS for each runtime
        for (runtime_id, region), invocations in runtime_groups.items():
            # Determine time window: earliest invoke - 60s to latest done + 600s
            earliest = min(inv.client_invoke_time for inv in invocations)
            latest = max(inv.client_done_time for inv in invocations)
            start_ms = int((earliest - 60) * 1000)
            end_ms = int((latest + 600) * 1000)

            try:
                raw_events = get_usage_log_events_by_time(
                    runtime_id=runtime_id,
                    region=region,
                    start_time_ms=start_ms,
                    end_time_ms=end_ms,
                )
            except Exception as e:
                logger.warning("[usage_poller] Failed to get USAGE_LOGS for runtime %s: %s", runtime_id, e)
                continue

            if not raw_events:
                continue

            usage_events = parse_usage_events(raw_events)
            if not usage_events:
                continue

            logger.info("[usage_poller] Got %d usage events for runtime %s", len(usage_events), runtime_id)

            # Match usage events to invocations by timestamp
            for inv in invocations:
                # Find usage event whose event_timestamp is within 5s of invoke time
                matched = None
                for ue in usage_events:
                    if abs(ue["event_timestamp_epoch"] - inv.client_invoke_time) <= TIMESTAMP_TOLERANCE_SECONDS:
                        matched = ue
                        break

                if not matched:
                    continue

                # Compute actual costs from usage data
                new_cpu_cost = round(
                    matched["vcpu_hours"] * AGENTCORE_RUNTIME_PRICING["cpu_per_vcpu_hour"], 6,
                )
                new_memory_cost = round(
                    matched["memory_gb_hours"] * AGENTCORE_RUNTIME_PRICING["memory_per_gb_hour"], 6,
                )
                new_compute_cost = round(new_cpu_cost + new_memory_cost, 6)

                # Log before/after
                logger.info(
                    "[usage_poller] Updating invocation %s: "
                    "cpu_cost $%s→$%s, memory_cost $%s→$%s, compute_cost $%s→$%s "
                    "(estimated→usage_logs)",
                    inv.invocation_id,
                    inv.compute_cpu_cost, new_cpu_cost,
                    inv.compute_memory_cost, new_memory_cost,
                    inv.compute_cost, new_compute_cost,
                )

                inv.compute_cpu_cost = new_cpu_cost
                inv.compute_memory_cost = new_memory_cost
                inv.compute_cost = new_compute_cost
                inv.cost_source = "usage_logs"
                updated_count += 1

        if updated_count > 0:
            db.commit()
            logger.info("[usage_poller] Updated %d invocations from estimated to usage_logs", updated_count)

    except Exception as e:
        db.rollback()
        logger.exception("[usage_poller] Poll cycle failed: %s", e)
    finally:
        db.close()

    return updated_count


async def start_usage_poller() -> None:
    """Run the usage log poller as a background asyncio task."""
    logger.info("[usage_poller] Starting background poller (interval=%ds)", POLL_INTERVAL_SECONDS)

    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            count = await asyncio.to_thread(_poll_once)
            if count > 0:
                logger.info("[usage_poller] Poll cycle complete: %d invocations updated", count)
        except Exception as e:
            logger.exception("[usage_poller] Unhandled error in poll cycle: %s", e)
