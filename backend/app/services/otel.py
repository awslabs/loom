"""OTEL log event parsing for trace visualization.

Parses structured OTEL log events from the ``otel-rt-logs`` CloudWatch
log stream.  Events are grouped by ``traceId`` and ``spanId``, ordered
by ``observedTimeUnixNano``.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import boto3

logger = logging.getLogger(__name__)

OTEL_STREAM = "otel-rt-logs"


def fetch_otel_events(
    log_group: str,
    region: str,
    filter_pattern: str | None = None,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Fetch OTEL log events from the ``otel-rt-logs`` CloudWatch stream.

    Args:
        log_group: CloudWatch log group name.
        region: AWS region name.
        filter_pattern: Optional CloudWatch filterPattern string.
        start_time_ms: Optional start time filter (ms since epoch).
        end_time_ms: Optional end time filter (ms since epoch).
        limit: Maximum events to return.

    Returns:
        List of raw CloudWatch log event dicts.
    """
    client = boto3.client("logs", region_name=region)

    params: dict[str, Any] = {
        "logGroupName": log_group,
        "logStreamNames": [OTEL_STREAM],
        "limit": limit,
    }
    if filter_pattern:
        params["filterPattern"] = filter_pattern
    if start_time_ms is not None:
        params["startTime"] = start_time_ms
    if end_time_ms is not None:
        params["endTime"] = end_time_ms

    all_events: list[dict[str, Any]] = []
    try:
        response = client.filter_log_events(**params)
        all_events.extend(response.get("events", []))
        while response.get("nextToken"):
            params["nextToken"] = response["nextToken"]
            response = client.filter_log_events(**params)
            all_events.extend(response.get("events", []))
    except Exception:
        logger.exception(
            "Failed to fetch OTEL events from %s (filter=%s)",
            log_group, filter_pattern,
        )

    logger.info(
        "[fetch_otel_events] log_group=%s filter=%s events=%d",
        log_group, filter_pattern, len(all_events),
    )
    return all_events


def _nano_to_iso(nano: int) -> str:
    """Convert nanosecond timestamp to UTC ISO 8601 string."""
    return datetime.fromtimestamp(nano / 1e9, tz=timezone.utc).isoformat()


def _nano_to_ms(nano: int) -> float:
    """Convert nanosecond timestamp to milliseconds."""
    return nano / 1e6


def _parse_event(raw_message: str) -> dict[str, Any] | None:
    """Parse a single OTEL log event from a CloudWatch message string."""
    if not raw_message.startswith("{"):
        return None
    try:
        return json.loads(raw_message)
    except json.JSONDecodeError:
        return None


def extract_trace_ids(events: list[dict[str, Any]]) -> set[str]:
    """Extract unique trace IDs from raw CloudWatch log events."""
    trace_ids: set[str] = set()
    for ev in events:
        parsed = _parse_event(ev.get("message", ""))
        if not parsed:
            continue
        tid = parsed.get("traceId")
        if tid:
            trace_ids.add(tid)
    return trace_ids


def _split_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Split a body with both ``input`` and ``output`` into separate bodies.

    If the body contains both keys they are emitted as two distinct bodies
    (input first, then output) so each log event maps to exactly one
    direction.  Bodies with only one or neither key are returned as-is.
    """
    if "input" in body and "output" in body:
        remaining = {k: v for k, v in body.items() if k not in ("input", "output")}
        return [
            {"input": body["input"], **remaining},
            {"output": body["output"], **remaining},
        ]
    return [body]


def parse_otel_traces(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse raw CloudWatch events into trace summaries.

    Groups events by ``traceId``.  For each trace, computes time range
    from min/max ``observedTimeUnixNano`` and counts unique spans.

    Args:
        events: Raw CloudWatch log event dicts.

    Returns:
        List of trace summary dicts sorted by start time descending.
    """
    traces: dict[str, dict[str, Any]] = {}

    for ev in events:
        parsed = _parse_event(ev.get("message", ""))
        if not parsed:
            continue

        trace_id = parsed.get("traceId")
        if not trace_id:
            continue

        observed = parsed.get("observedTimeUnixNano", 0)
        span_id = parsed.get("spanId", "")
        session_id = parsed.get("attributes", {}).get("session.id")
        body = parsed.get("body", {})

        if trace_id not in traces:
            traces[trace_id] = {
                "trace_id": trace_id,
                "session_id": session_id,
                "min_nano": observed,
                "max_nano": observed,
                "span_ids": set(),
                "event_count": 0,
            }

        t = traces[trace_id]
        if observed < t["min_nano"]:
            t["min_nano"] = observed
        if observed > t["max_nano"]:
            t["max_nano"] = observed
        if span_id:
            t["span_ids"].add(span_id)
        # Count split events consistently with parse_otel_trace_detail
        if isinstance(body, dict):
            t["event_count"] += len(_split_body(body))
        else:
            t["event_count"] += 1
        if session_id and not t["session_id"]:
            t["session_id"] = session_id

    result = []
    for t in traces.values():
        duration_ms = round((t["max_nano"] - t["min_nano"]) / 1e6, 2)
        result.append({
            "trace_id": t["trace_id"],
            "session_id": t["session_id"],
            "start_time_iso": _nano_to_iso(t["min_nano"]),
            "end_time_iso": _nano_to_iso(t["max_nano"]),
            "duration_ms": duration_ms,
            "span_count": len(t["span_ids"]),
            "event_count": t["event_count"],
        })

    result.sort(key=lambda x: x["start_time_iso"], reverse=True)
    return result


def parse_otel_trace_detail(
    events: list[dict[str, Any]],
    trace_id: str,
) -> dict[str, Any] | None:
    """Parse raw CloudWatch events into a full trace detail.

    Filters to the specified ``trace_id``, groups by ``spanId``,
    and orders events within each span by ``observedTimeUnixNano``.

    Args:
        events: Raw CloudWatch log event dicts.
        trace_id: The trace ID to filter for.

    Returns:
        Trace detail dict with spans and events, or None if not found.
    """
    spans: dict[str, dict[str, Any]] = {}
    session_id: str | None = None

    for ev in events:
        parsed = _parse_event(ev.get("message", ""))
        if not parsed:
            continue

        if parsed.get("traceId") != trace_id:
            continue

        span_id = parsed.get("spanId", "unknown")
        observed = parsed.get("observedTimeUnixNano", 0)
        scope_name = parsed.get("scope", {}).get("name", "")
        severity = parsed.get("severityNumber", 0)
        body = parsed.get("body", {})
        sid = parsed.get("attributes", {}).get("session.id")
        if sid and not session_id:
            session_id = sid

        # Split bodies that contain both input and output into two events
        if isinstance(body, dict):
            bodies = _split_body(body)
        else:
            bodies = [body]

        if span_id not in spans:
            spans[span_id] = {
                "span_id": span_id,
                "scopes": set(),
                "min_nano": observed,
                "max_nano": observed,
                "events": [],
            }

        s = spans[span_id]
        if scope_name:
            s["scopes"].add(scope_name)
        if observed < s["min_nano"]:
            s["min_nano"] = observed
        if observed > s["max_nano"]:
            s["max_nano"] = observed

        for b in bodies:
            s["events"].append({
                "observed_time_iso": _nano_to_iso(observed),
                "observed_nano": observed,
                "severity_number": severity,
                "scope": scope_name,
                "body": b,
            })

    if not spans:
        return None

    # Sort events within each span by observedTimeUnixNano
    span_list = []
    all_min = None
    all_max = None

    for s in spans.values():
        s["events"].sort(key=lambda e: e["observed_nano"])
        # Remove the sort key from output
        for e in s["events"]:
            del e["observed_nano"]

        duration_ms = round((s["max_nano"] - s["min_nano"]) / 1e6, 2)
        if all_min is None or s["min_nano"] < all_min:
            all_min = s["min_nano"]
        if all_max is None or s["max_nano"] > all_max:
            all_max = s["max_nano"]

        # Use all unique scope names for the span label
        scope_label = ", ".join(sorted(s["scopes"])) if s["scopes"] else ""

        span_list.append({
            "span_id": s["span_id"],
            "scope": scope_label,
            "start_time_iso": _nano_to_iso(s["min_nano"]),
            "end_time_iso": _nano_to_iso(s["max_nano"]),
            "duration_ms": duration_ms,
            "event_count": len(s["events"]),
            "events": s["events"],
        })

    # Sort spans by start time
    span_list.sort(key=lambda x: x["start_time_iso"])

    total_events = sum(s["event_count"] for s in span_list)
    total_duration = round(((all_max or 0) - (all_min or 0)) / 1e6, 2)

    return {
        "trace_id": trace_id,
        "session_id": session_id,
        "start_time_iso": _nano_to_iso(all_min or 0),
        "end_time_iso": _nano_to_iso(all_max or 0),
        "duration_ms": total_duration,
        "span_count": len(span_list),
        "event_count": total_events,
        "spans": span_list,
    }
