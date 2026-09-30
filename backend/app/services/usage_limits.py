"""Usage-limit evaluation: matching, aggregation, and precedence decisions.

Called from the invoke endpoint as a pre-flight check, before a new
Invocation row is created. Enforcement is necessarily based on *already
completed* usage in the current window, since a request's own token/cost
usage isn't known until after it finishes — there's no way to meter or
cut off a request mid-stream.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.invocation import Invocation
from app.models.session import InvocationSession
from app.models.usage_limit import UsageLimit
from app.services.model_catalog import get_model_family, _normalize_model_id

logger = logging.getLogger(__name__)

_ENFORCEMENT_RANK = {"warn": 0, "throttle": 1, "block": 2}


@dataclass
class UsageDecision:
    enforcement: str | None = None  # None means no limit exceeded, proceed normally
    limit_name: str | None = None
    current_usage: float | None = None
    threshold: float | None = None
    measure: str | None = None
    warnings: list[str] = field(default_factory=list)


def _window_start(window: str, now: datetime) -> datetime:
    """Start of the current window for `now` (UTC).

    daily/weekly/monthly reset at a calendar boundary — usage snaps to
    zero right at that boundary, regardless of what was spent a minute
    before it. "rolling" is a trailing 24h window instead, for admins who
    want a sliding cap with no reset-boundary gaming.
    """
    if window == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "weekly":
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day - timedelta(days=start_of_day.weekday())
    if window == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if window == "rolling":
        return now - timedelta(hours=24)
    logger.warning("Unknown usage limit window %r, defaulting to daily", window)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _limit_matches_scope(limit: UsageLimit, username: str, groups: list[str]) -> bool:
    scope = limit.get_scope()
    if scope.get("type") == "user":
        return scope.get("username") == username
    if scope.get("type") == "group":
        return scope.get("group") in groups
    return False


def _limit_matches_target(target: dict, model_id: str | None) -> bool:
    if not model_id:
        return False
    target_type = target.get("type", "all")
    if target_type == "all":
        return True
    if target_type == "model":
        return _normalize_model_id(target.get("model_id", "")) == _normalize_model_id(model_id)
    if target_type == "family":
        return target.get("family") == get_model_family(model_id)
    return False


def _matching_limits(db: Session, username: str, groups: list[str], model_id: str) -> list[UsageLimit]:
    """Enabled limits whose scope and target both apply to this request.

    Filtered in Python after one query for all enabled limits, since
    scope/target are JSON text — this table is expected to hold at most a
    few dozen admin-defined rows, not a hot-path performance concern.
    """
    candidates = db.query(UsageLimit).filter(UsageLimit.enabled == True).all()  # noqa: E712
    return [
        limit for limit in candidates
        if _limit_matches_scope(limit, username, groups)
        and _limit_matches_target(limit.get_target(), model_id)
    ]


def _current_usage(db: Session, limit: UsageLimit, window_start: datetime) -> float:
    """Sum of `limit.measure` across invocations matching this limit's
    scope and target, since `window_start`.

    "budget" sums estimated_cost + compute_cost + memory_estimated_cost —
    the three cost components actually charged. idle_* costs are
    deliberately excluded: per their own column comments on Invocation,
    they're an unmeasurable upper bound, not a real charge.
    """
    scope = limit.get_scope()
    query = (
        db.query(Invocation)
        .join(InvocationSession, Invocation.session_id == InvocationSession.session_id)
        .filter(Invocation.created_at >= window_start)
    )
    if scope.get("type") == "user":
        query = query.filter(InvocationSession.user_id == scope.get("username"))
    elif scope.get("type") == "group":
        # groups is a JSON list snapshotted at invoke time; a plain LIKE
        # match on the group name avoids depending on SQLite's optional
        # JSON1 extension being present.
        query = query.filter(InvocationSession.groups.like(f'%"{scope.get("group")}"%'))
    else:
        return 0.0

    invocations = query.all()

    target = limit.get_target()
    if target.get("type") != "all":
        invocations = [inv for inv in invocations if _limit_matches_target(target, inv.model_id)]

    if limit.measure == "tokens":
        return sum((inv.input_tokens or 0) + (inv.output_tokens or 0) for inv in invocations)
    return sum(
        (inv.estimated_cost or 0) + (inv.compute_cost or 0) + (inv.memory_estimated_cost or 0)
        for inv in invocations
    )



def check_usage_limits(db: Session, username: str, groups: list[str], model_id: str) -> UsageDecision:
    
    now = datetime.now(timezone.utc)
    decision = UsageDecision()

    for limit in _matching_limits(db, username, groups, model_id):
        window_start = _window_start(limit.window, now)
        # Cache-first: use the aggregator's precomputed value when it's
        # fresh (refreshed at or after this window started). Otherwise —
        # aggregator hasn't run yet, or we've crossed a window boundary
        # since the last refresh — fall back to a live computation rather
        # than trust a stale number or silently treat usage as zero.
        if limit.cached_usage is not None and limit.cached_usage_updated_at \
                and limit.cached_usage_updated_at >= window_start:
            usage = limit.cached_usage
        else:
            usage = _current_usage(db, limit, window_start)

        if usage < limit.threshold:
            continue

        if limit.enforcement == "warn":
            decision.warnings.append(
                f"Usage limit '{limit.name}' exceeded ({usage}/{limit.threshold} {limit.measure})"
            )

        current_rank = _ENFORCEMENT_RANK.get(decision.enforcement, -1)
        new_rank = _ENFORCEMENT_RANK.get(limit.enforcement, -1)
        if new_rank > current_rank:
            decision.enforcement = limit.enforcement
            decision.limit_name = limit.name
            decision.current_usage = usage
            decision.threshold = limit.threshold
            decision.measure = limit.measure

    return decision

    """Evaluate all matching usage limits and return the single decision
    to act on.

    Precedence: among limits already exceeded, block wins over throttle
    wins over warn (most-restrictive-wins) — an exceeded "warn" limit
    never softens an exceeded "block" limit on a different scope. Limits
    not yet exceeded are ignored entirely, even if enabled and matching.
    """
