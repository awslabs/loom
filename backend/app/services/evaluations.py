"""Read-only access to AgentCore Evaluations results for a Loom agent.

AgentCore Evaluations scores agent traces with built-in or custom evaluators.
Two kinds of source produce results:

- **Online evaluation configs** sample live sessions continuously.
- **Batch evaluations** score a chosen set of sessions once (for example the
  sessions created by running a list of test prompts).

Both write one ``gen_ai.evaluation.result`` log record per evaluator per
trace, either to a dedicated results log group or back into the log group the
traces came from (``resultDestination = SOURCE_LOG_GROUP``). This module finds
the sources that evaluate a given agent and parses their result records. It
never creates or changes evaluation resources.

Scoping rule: a source belongs to an agent when its CloudWatch data source
reads only that agent's runtime log groups (**exclusive**), or when it names
one of the agent's OTEL service names (**shared**). Results from a shared
source are filtered to the agent's service names, so one agent never sees
another agent's sessions.

Reference:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html
"""

import json
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, NamedTuple

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

RESULT_EVENT_NAME = "gen_ai.evaluation.result"
RESULT_FILTER_PATTERN = '{ $.name = "gen_ai.evaluation.result" }'
DEFAULT_RESULTS_PREFIX = "/aws/bedrock-agentcore/evaluations/results/"
SOURCE_LOG_GROUP = "SOURCE_LOG_GROUP"

MAX_BATCH_RUNS = 50  # newest batch runs inspected per overview request
MAX_RESULT_RECORDS = 1000  # cap on result records returned per results request
MAX_PAGES = 60  # cap on CloudWatch pages read per results request
DAY_MS = 86_400_000
LAST_EVALUATED_LOOKBACK_DAYS = 30
MAX_WORKERS = 8


class AgentTarget(NamedTuple):
    """How to recognise an agent in evaluation data."""
    log_groups: frozenset[str]
    service_names: frozenset[str]


class SourceScope(NamedTuple):
    """Whether a source evaluates the agent, and how to isolate its results."""
    matches: bool
    service_filter: frozenset[str] | None  # None = every record belongs to the agent
    result_groups: frozenset[str]  # agent log groups this source reads (for SOURCE_LOG_GROUP)


NO_MATCH = SourceScope(False, None, frozenset())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(value: Any) -> str | None:
    """Return an ISO-8601 string for a datetime or epoch-milliseconds value."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    return str(value)


def _nanos_to_iso(value: Any) -> str | None:
    """Return an ISO-8601 string for an epoch-nanoseconds value."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc).isoformat()


def _to_ms(value: Any) -> int | None:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    return None


def _paginate(call: Callable[..., dict], key: str, **kwargs: Any) -> list[dict]:
    """Collect every page of a nextToken-paginated list call."""
    items: list[dict] = []
    while True:
        page = call(**kwargs)
        items.extend(page.get(key, []))
        token = page.get("nextToken")
        if not token:
            return items
        kwargs["nextToken"] = token


def _is_not_found(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException"


def _evaluator_ids(evaluators: Iterable[dict] | None) -> list[str]:
    return [e["evaluatorId"] for e in evaluators or [] if e.get("evaluatorId")]


def _output_config(detail: dict) -> dict:
    return (detail.get("outputConfig") or {}).get("cloudWatchConfig") or {}


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------

def source_scope(cloudwatch_source: dict, target: AgentTarget) -> SourceScope:
    """Decide whether a ``cloudWatchLogs`` data source evaluates the agent."""
    groups = set(cloudwatch_source.get("logGroupNames") or [])
    prefixes = list(cloudwatch_source.get("logGroupNamePrefixes") or [])
    services = set(cloudwatch_source.get("serviceNames") or [])

    read_groups = frozenset(
        g for g in target.log_groups
        if g in groups or any(g.startswith(p) for p in prefixes)
    )
    # The source reads only this agent's log groups: every result is the agent's.
    if groups and groups <= target.log_groups and not prefixes:
        return SourceScope(True, None, read_groups)
    # Otherwise the source may cover several agents; it is ours only if it names
    # one of the agent's service names, and its results are filtered to them.
    shared_names = frozenset(services & target.service_names)
    if shared_names and (read_groups or (not groups and not prefixes)):
        return SourceScope(True, shared_names, read_groups)
    return NO_MATCH


def online_config_scope(detail: dict, target: AgentTarget) -> SourceScope:
    return source_scope((detail.get("dataSourceConfig") or {}).get("cloudWatchLogs") or {}, target)


def batch_run_scope(detail: dict, target: AgentTarget,
                    online_scopes: dict[str, SourceScope]) -> SourceScope:
    """Scope of a batch run: its own log source, or the online config it re-scores."""
    source = detail.get("dataSourceConfig") or {}
    if source.get("cloudWatchLogs"):
        return source_scope(source["cloudWatchLogs"], target)
    parent = (source.get("onlineEvaluationConfigSource") or {}).get("onlineEvaluationConfigArn")
    return online_scopes.get(parent or "", NO_MATCH)


# ---------------------------------------------------------------------------
# Log reading
# ---------------------------------------------------------------------------

def _read_stream(logs: Any, group: str, stream: str,
                 cap: int | None = None) -> tuple[list[dict], bool]:
    """Read one log stream from the start. Returns (events, truncated)."""
    cap = cap or MAX_RESULT_RECORDS
    events: list[dict] = []
    kwargs: dict[str, Any] = {"logGroupName": group, "logStreamName": stream, "startFromHead": True}
    try:
        for _ in range(MAX_PAGES):
            page = logs.get_log_events(**kwargs)
            events.extend(page.get("events", []))
            token = page.get("nextForwardToken")
            if len(events) >= cap or not token or token == kwargs.get("nextToken"):
                break
            kwargs["nextToken"] = token
        else:
            return events[:cap], True
    except ClientError as exc:
        if _is_not_found(exc):
            return [], False
        raise
    return events[:cap], len(events) > cap


def _read_recent(logs: Any, groups: Iterable[str], start_ms: int, end_ms: int,
                 cap: int | None = None, window_ms: int = DAY_MS) -> tuple[list[dict], bool]:
    """Read the NEWEST result events in [start_ms, end_ms] across log groups.

    CloudWatch returns events oldest first, so the range is read in windows
    from the newest one backwards and the scan stops once ``cap`` events are
    held. Within a window only the newest ``cap`` events are kept. Returns
    (events oldest first, truncated).
    """
    cap = cap or MAX_RESULT_RECORDS
    kept: list[dict] = []
    truncated = False
    pages = 0
    window_end = end_ms
    while window_end > start_ms and len(kept) < cap:
        window_start = max(start_ms, window_end - window_ms)
        window: deque[dict] = deque(maxlen=cap)
        for group in sorted(groups):
            kwargs: dict[str, Any] = {"logGroupName": group, "startTime": window_start,
                                      "endTime": window_end, "filterPattern": RESULT_FILTER_PATTERN}
            try:
                while True:
                    page = logs.filter_log_events(**kwargs)
                    pages += 1
                    for event in page.get("events", []):
                        if len(window) == window.maxlen:
                            truncated = True
                        window.append(event)
                    if not page.get("nextToken"):
                        break
                    if pages >= MAX_PAGES:
                        truncated = True
                        break
                    kwargs["nextToken"] = page["nextToken"]
            except ClientError as exc:
                if not _is_not_found(exc):
                    raise
        batch = sorted(window, key=lambda e: e.get("timestamp", 0))
        kept = batch + kept
        if pages >= MAX_PAGES:
            truncated = True
            break
        window_end = window_start
    if len(kept) > cap:
        kept = kept[-cap:]
        truncated = True
    return kept, truncated


def _newest_event_ms(logs: Any, group: str) -> int | None:
    """Timestamp of the newest event in a dedicated results log group."""
    try:
        streams = logs.describe_log_streams(
            logGroupName=group, orderBy="LastEventTime", descending=True, limit=1,
        ).get("logStreams", [])
        if not streams:
            return None
        # lastEventTimestamp is eventually consistent (can lag up to an hour);
        # read the stream's last event for the exact time.
        tail = logs.get_log_events(logGroupName=group, logStreamName=streams[0]["logStreamName"],
                                   startFromHead=False, limit=1).get("events", [])
        return tail[-1]["timestamp"] if tail else streams[0].get("lastEventTimestamp")
    except ClientError as exc:
        if _is_not_found(exc):
            return None
        raise


# ---------------------------------------------------------------------------
# Result locations
# ---------------------------------------------------------------------------

class ResultsLocation(NamedTuple):
    groups: frozenset[str]
    stream: str | None
    service_filter: frozenset[str] | None
    source_arn: str | None  # keep only records written by this config / batch run
    time_range_ms: tuple[int, int] | None = None  # fixed search window (batch runs)


def _batch_window_ms(detail: dict) -> tuple[int, int] | None:
    """Time window holding a batch run's results when they share a log group."""
    start, end = _to_ms(detail.get("createdAt")), _to_ms(detail.get("updatedAt"))
    if start is None:
        return None
    return start - 5 * 60_000, (end or int(time.time() * 1000)) + 60 * 60_000


def online_results_location(detail: dict, scope: SourceScope) -> ResultsLocation | None:
    output = _output_config(detail)
    arn = detail.get("onlineEvaluationConfigArn")
    if output.get("resultDestination") == SOURCE_LOG_GROUP:
        # Results are written back next to the traces: the agent's own log groups.
        return ResultsLocation(scope.result_groups, None, None, arn) if scope.result_groups else None
    group = output.get("logGroupName") or (
        DEFAULT_RESULTS_PREFIX + detail["onlineEvaluationConfigId"]
        if detail.get("onlineEvaluationConfigId") else None)
    return ResultsLocation(frozenset({group}), None, scope.service_filter, arn) if group else None


def batch_results_location(detail: dict, scope: SourceScope) -> ResultsLocation | None:
    output = _output_config(detail)
    arn = detail.get("batchEvaluationArn")
    if output.get("resultDestination") == SOURCE_LOG_GROUP:
        if not scope.result_groups:
            return None
        return ResultsLocation(scope.result_groups, None, None, arn, _batch_window_ms(detail))
    group = output.get("logGroupName")
    if not group:
        return None
    stream = output.get("logStreamName")
    window = None if stream else _batch_window_ms(detail)
    return ResultsLocation(frozenset({group}), stream, scope.service_filter, arn, window)


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------

def _last_evaluated_ms(logs: Any, location: ResultsLocation | None) -> int | None:
    """When the source last wrote a result for this agent."""
    if location is None:
        return None
    only_group = next(iter(location.groups)) if len(location.groups) == 1 else None
    # The service-managed default group holds only this config's results.
    if location.service_filter is None and only_group and only_group.startswith(DEFAULT_RESULTS_PREFIX):
        return _newest_event_ms(logs, only_group)
    now = int(time.time() * 1000)
    events, _ = _read_recent(logs, location.groups, now - LAST_EVALUATED_LOOKBACK_DAYS * DAY_MS, now,
                             window_ms=7 * DAY_MS)
    records = filter_records(parse_result_records(events), location)
    stamps = [r["evaluated_ms"] for r in records if r["evaluated_ms"] is not None]
    return max(stamps) if stamps else None


def online_config_entry(detail: dict, scope: SourceScope, logs: Any) -> dict:
    """Summarise an online evaluation config for one agent."""
    rule = detail.get("rule") or {}
    location = online_results_location(detail, scope)
    return {
        "id": detail.get("onlineEvaluationConfigId"),
        "arn": detail.get("onlineEvaluationConfigArn"),
        "name": detail.get("onlineEvaluationConfigName"),
        "status": detail.get("status"),
        "execution_status": detail.get("executionStatus"),
        "sampling_percentage": (rule.get("samplingConfig") or {}).get("samplingPercentage"),
        "session_timeout_minutes": (rule.get("sessionConfig") or {}).get("sessionTimeoutMinutes"),
        "evaluators": _evaluator_ids(detail.get("evaluators")),
        "shared": scope.service_filter is not None,
        "last_evaluated_at": _iso(_last_evaluated_ms(logs, location)),
        "updated_at": _iso(detail.get("updatedAt")),
    }


def batch_run_entry(detail: dict, scope: SourceScope | None = None) -> dict:
    """Summarise a batch evaluation run and its per-evaluator averages."""
    cloudwatch = (detail.get("dataSourceConfig") or {}).get("cloudWatchLogs") or {}
    totals = detail.get("evaluationResults") or {}
    return {
        "id": detail.get("batchEvaluationId"),
        "name": detail.get("batchEvaluationName"),
        "description": detail.get("description"),
        "status": detail.get("status"),
        "created_at": _iso(detail.get("createdAt")),
        "updated_at": _iso(detail.get("updatedAt")),
        "evaluators": _evaluator_ids(detail.get("evaluators")),
        "shared": bool(scope and scope.service_filter is not None),
        "targeted_session_count": len((cloudwatch.get("filterConfig") or {}).get("sessionIds") or []),
        "sessions_total": totals.get("totalNumberOfSessions"),
        "sessions_completed": totals.get("numberOfSessionsCompleted"),
        "sessions_failed": totals.get("numberOfSessionsFailed"),
        "sessions_ignored": totals.get("numberOfSessionsIgnored"),
        "evaluator_summaries": [
            {
                "evaluator_id": s.get("evaluatorId"),
                "average_score": (s.get("statistics") or {}).get("averageScore"),
                "total_evaluated": s.get("totalEvaluated"),
                "total_failed": s.get("totalFailed"),
            }
            for s in totals.get("evaluatorSummaries") or []
        ],
    }


def _get_all(fetch: Callable[[str], dict], ids: list[str]) -> list[dict]:
    """Fetch details in parallel, skipping any that vanished since the list call."""
    def one(item_id: str) -> dict | None:
        try:
            return fetch(item_id)
        except ClientError as exc:
            if _is_not_found(exc):
                logger.info("Evaluation source %s disappeared before it could be read", item_id)
                return None
            raise
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        return [d for d in pool.map(one, ids) if d is not None]


def discover_sources(target: AgentTarget, region: str) -> dict[str, list[dict]]:
    """Find every online config and batch run that evaluates the agent."""
    session = boto3.Session(region_name=region)
    control = session.client("bedrock-agentcore-control")
    data = session.client("bedrock-agentcore")
    logs = session.client("logs")

    config_ids = [s["onlineEvaluationConfigId"] for s in _paginate(
        control.list_online_evaluation_configs, "onlineEvaluationConfigs", maxResults=100)]
    configs = _get_all(lambda i: control.get_online_evaluation_config(onlineEvaluationConfigId=i), config_ids)
    online_scopes = {c.get("onlineEvaluationConfigArn", ""): online_config_scope(c, target) for c in configs}
    matching = [(c, online_scopes[c.get("onlineEvaluationConfigArn", "")]) for c in configs]
    matching = [(c, s) for c, s in matching if s.matches]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        online = list(pool.map(lambda cs: online_config_entry(cs[0], cs[1], logs), matching))

    summaries = _paginate(data.list_batch_evaluations, "batchEvaluations", maxResults=100)
    summaries.sort(key=lambda s: s.get("createdAt") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    runs = _get_all(lambda i: data.get_batch_evaluation(batchEvaluationId=i),
                    [s["batchEvaluationId"] for s in summaries[:MAX_BATCH_RUNS]])
    batch = []
    for run in runs:
        scope = batch_run_scope(run, target, online_scopes)
        if scope.matches:
            batch.append(batch_run_entry(run, scope))
    return {"online": online, "batch": batch}


def resolve_results_location(source_type: str, source_id: str, target: AgentTarget,
                             region: str) -> ResultsLocation | None:
    """Where a source's results for this agent live, or None if it does not evaluate the agent.

    The source is re-read from AWS and scoped against the agent, so a caller
    can only reach results that belong to this agent.
    """
    session = boto3.Session(region_name=region)
    control = session.client("bedrock-agentcore-control")
    if source_type == "online":
        detail = control.get_online_evaluation_config(onlineEvaluationConfigId=source_id)
        scope = online_config_scope(detail, target)
        return online_results_location(detail, scope) if scope.matches else None

    detail = session.client("bedrock-agentcore").get_batch_evaluation(batchEvaluationId=source_id)
    online_scopes: dict[str, SourceScope] = {}
    parent_arn = ((detail.get("dataSourceConfig") or {}).get("onlineEvaluationConfigSource") or {}).get(
        "onlineEvaluationConfigArn")
    if parent_arn:
        try:
            parent = control.get_online_evaluation_config(onlineEvaluationConfigId=parent_arn.rsplit("/", 1)[-1])
            online_scopes[parent_arn] = online_config_scope(parent, target)
        except ClientError as exc:
            if not _is_not_found(exc):
                raise
    scope = batch_run_scope(detail, target, online_scopes)
    return batch_results_location(detail, scope) if scope.matches else None


def read_results(location: ResultsLocation, region: str, days: int = 7) -> tuple[list[dict], bool]:
    """Read and filter the result records at a location. Returns (records, truncated)."""
    logs = boto3.client("logs", region_name=region)
    if location.stream:
        events, truncated = _read_stream(logs, next(iter(location.groups)), location.stream)
    else:
        now = int(time.time() * 1000)
        start, end = location.time_range_ms or (now - days * DAY_MS, now)
        events, truncated = _read_recent(logs, location.groups, start, end)
    return filter_records(parse_result_records(events), location), truncated


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def parse_result_records(events: Iterable[dict]) -> list[dict]:
    """Parse ``gen_ai.evaluation.result`` log events into flat score records."""
    records: list[dict] = []
    for event in events:
        try:
            record = json.loads(event.get("message", ""))
        except (TypeError, ValueError):
            continue
        if not isinstance(record, dict) or record.get("name") != RESULT_EVENT_NAME:
            continue
        attrs = record.get("attributes") or {}
        if not isinstance(attrs, dict):
            continue
        resource = (record.get("resource") or {}).get("attributes") or {}
        value = attrs.get("gen_ai.evaluation.score.value")
        observed = record.get("observedTimeUnixNano")
        records.append({
            "session_id": attrs.get("session.id"),
            "trace_id": record.get("traceId") or attrs.get("gen_ai.response.id"),
            "trace_time": _nanos_to_iso(record.get("timeUnixNano")),
            "evaluated_at": _nanos_to_iso(observed),
            "evaluated_ms": int(observed // 1_000_000)
            if isinstance(observed, (int, float)) and not isinstance(observed, bool) else event.get("timestamp"),
            "evaluator": attrs.get("gen_ai.evaluation.name"),
            "value": float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
            "label": attrs.get("gen_ai.evaluation.score.label"),
            "explanation": attrs.get("gen_ai.evaluation.explanation"),
            "level": attrs.get("aws.bedrock_agentcore.evaluation_level"),
            "service_name": record.get("service.name") or resource.get("service.name"),
            "source_arn": attrs.get("aws.bedrock_agentcore.online_evaluation_config.arn")
            or attrs.get("aws.bedrock_agentcore.evaluation_job.arn") or record.get("evaluationJobId"),
        })
    return records


def filter_records(records: Iterable[dict], location: ResultsLocation) -> list[dict]:
    """Keep only the records that belong to this agent and to this evaluation source."""
    out = []
    for rec in records:
        if location.service_filter is not None and rec.get("service_name") not in location.service_filter:
            continue
        if location.source_arn and rec.get("source_arn") and rec["source_arn"] != location.source_arn:
            continue
        out.append(rec)
    return out


def group_by_trace(records: Iterable[dict]) -> list[dict]:
    """Group score records by evaluated trace, newest evaluation first."""
    grouped: dict[tuple[Any, Any], dict] = {}
    for rec in records:
        key = (rec["session_id"], rec["trace_id"])
        entry = grouped.setdefault(key, {
            "session_id": rec["session_id"],
            "trace_id": rec["trace_id"],
            "trace_time": rec["trace_time"],
            "evaluated_at": rec["evaluated_at"],
            "scores": [],
        })
        if rec["evaluated_at"] and (entry["evaluated_at"] or "") < rec["evaluated_at"]:
            entry["evaluated_at"] = rec["evaluated_at"]
        entry["scores"].append({k: rec[k] for k in ("evaluator", "value", "label", "explanation", "level")})
    for entry in grouped.values():
        entry["scores"].sort(key=lambda s: s["evaluator"] or "")
    return sorted(grouped.values(), key=lambda e: e["evaluated_at"] or "", reverse=True)


# ---------------------------------------------------------------------------
# Evaluated exchange (what the user asked, what the agent answered)
# ---------------------------------------------------------------------------

def _texts(blocks: Any) -> str:
    """Join the ``text`` fields of a list of content blocks."""
    if not isinstance(blocks, list):
        return ""
    return "\n".join(b["text"] for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str)).strip()


def _message_text(message: dict) -> str:
    """Text of a Strands tracer message, whose content is a JSON-encoded block list."""
    raw = (message.get("content") or {}).get("content") if isinstance(message.get("content"), dict) \
        else message.get("content")
    if isinstance(raw, list):
        return _texts(raw)
    if not isinstance(raw, str):
        return ""
    try:
        return _texts(json.loads(raw))
    except ValueError:
        return raw.strip()


def extract_exchange(events: Iterable[dict]) -> dict[str, str | None]:
    """Pull the user prompt and final agent answer from a trace's OTEL log events.

    The prompt is the LAST user message that carries text (earlier ones can be
    replayed history; tool results carry no text). The answer is the last
    assistant message returned by the model. Events are ordered by time first.
    Frameworks that log a different shape return ``None`` for the missing part.
    """
    prompt: str | None = None
    answer: str | None = None
    for event in sorted(events, key=lambda e: e.get("timestamp", 0)):
        try:
            record = json.loads(event.get("message", ""))
        except (TypeError, ValueError):
            continue
        body = record.get("body") if isinstance(record, dict) else None
        if not isinstance(body, dict):
            continue
        for message in (body.get("input") or {}).get("messages") or []:
            if isinstance(message, dict) and message.get("role") == "user":
                text = _message_text(message)
                if text:
                    prompt = text
        message = body.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            text = _texts(message.get("content"))
            if text:
                answer = text
    return {"prompt": prompt, "answer": answer}
