"""Periodic job that refreshes UsageLimit.cached_usage, so the invoke
endpoint's pre-flight check (see app/services/usage_limits.py) can read a
cheap cached value instead of recomputing a full window sum on every
single request. Follows the same asyncio-loop shape as usage_poller.py.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models.usage_limit import UsageLimit
from app.services.usage_limits import _current_usage, _window_start

logger = logging.getLogger(__name__)

# Deliberately much shorter than usage_poller.py's 10-minute interval —
# that job reconciles historical cost data where staleness is harmless;
# this one backs live enforcement decisions, so the cache needs to be
# fresh enough that a block-tier limit doesn't let much slip through
# between refreshes.
POLL_INTERVAL_SECONDS = 60


def _refresh_once() -> int:
    """Recompute cached_usage for every enabled limit. Returns the count refreshed."""
    db = SessionLocal()
    refreshed = 0
    try:
        limits = db.query(UsageLimit).filter(UsageLimit.enabled == True).all()  # noqa: E712
        now = datetime.now(timezone.utc)
        for limit in limits:
            window_start = _window_start(limit.window, now)
            limit.cached_usage = _current_usage(db, limit, window_start)
            limit.cached_usage_updated_at = now
            refreshed += 1
        if refreshed:
            db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("[usage_limit_aggregator] Refresh cycle failed: %s", e)
    finally:
        db.close()
    return refreshed


async def start_usage_limit_aggregator() -> None:
    """Run the usage-limit cache refresher as a background asyncio task."""
    logger.info("[usage_limit_aggregator] Starting background aggregator (interval=%ds)", POLL_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            count = await asyncio.to_thread(_refresh_once)
            if count:
                logger.info("[usage_limit_aggregator] Refreshed %d usage limits", count)
        except Exception as e:
            logger.exception("[usage_limit_aggregator] Unhandled error in refresh cycle: %s", e)
