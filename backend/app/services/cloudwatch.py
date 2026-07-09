"""
CloudWatch Logs wrapper for retrieving and parsing AgentCore Runtime logs.

This module provides functions to interact with AWS CloudWatch Logs API
for retrieving log events related to AgentCore Runtime invocations and
parsing agent start times from log messages.
"""

import json
import logging
import time
from datetime import datetime, timezone as tz
from typing import Any

logger = logging.getLogger(__name__)


def list_log_streams(log_group: str, region: str) -> list[dict[str, Any]]:
    """
    List all log streams in a CloudWatch log group, filtered and ordered by last event time.

    Args:
        log_group: CloudWatch log group name (e.g., '/aws/bedrock-agentcore/runtimes/...')
        region: AWS region name

    Returns:
        List of log stream dictionaries with 'name' and 'last_event_time' keys,
        excluding validation streams, ordered by most recent first
    """
    import boto3

    client = boto3.client('logs', region_name=region)

    try:
        response = client.describe_log_streams(
            logGroupName=log_group,
            orderBy='LastEventTime',
            descending=True
        )
        streams = response.get('logStreams', [])
    except Exception:
        # Fallback: try without ordering if that fails
        try:
            response = client.describe_log_streams(logGroupName=log_group)
            streams = response.get('logStreams', [])
        except Exception:
            return []

    # Filter out AWS validation streams and return normalized results
    result = []
    for stream in streams:
        stream_name = stream['logStreamName']
        if 'log_stream_created_by_aws_to_validate_log_delivery_subscriptions' not in stream_name:
            result.append({
                'name': stream_name,
                'last_event_time': stream.get('lastEventTimestamp', 0)
            })

    return result


def get_stream_log_events(
    log_group: str,
    stream_name: str,
    region: str,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    limit: int = 10000
) -> list[dict[str, Any]]:
    """
    Retrieve log events from a single CloudWatch log stream.

    Unlike get_log_events(), this does not retry or filter by session ID.
    It queries a single stream directly, suitable for general log browsing.

    Args:
        log_group: CloudWatch log group name
        stream_name: Name of the specific log stream to query
        region: AWS region name
        start_time_ms: Optional start time filter (milliseconds since epoch)
        end_time_ms: Optional end time filter (milliseconds since epoch)
        limit: Maximum number of events to return

    Returns:
        List of log event dictionaries with 'timestamp' and 'message' keys
    """
    import boto3

    client = boto3.client('logs', region_name=region)

    params: dict[str, Any] = {
        'logGroupName': log_group,
        'logStreamNames': [stream_name],
        'limit': limit
    }

    if start_time_ms is not None:
        params['startTime'] = start_time_ms
    if end_time_ms is not None:
        params['endTime'] = end_time_ms

    all_events: list[dict[str, Any]] = []
    response = client.filter_log_events(**params)
    all_events.extend(response.get('events', []))

    while response.get('nextToken'):
        params['nextToken'] = response['nextToken']
        response = client.filter_log_events(**params)
        all_events.extend(response.get('events', []))

    logger.info(
        "[get_stream_log_events] stream=%s events=%d",
        stream_name, len(all_events),
    )
    return all_events


def get_log_events(
    log_group: str,
    session_id: str,
    region: str,
    start_time_ms: int | None = None,
    limit: int = 100,
    max_retries: int = 12,
    retry_interval: float = 5.0,
    required_marker: str | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve CloudWatch log events matching a session ID, with retry logic.

    Polls CloudWatch for up to `max_retries` attempts, waiting `retry_interval` seconds
    between attempts. This handles log ingestion delays.

    Args:
        log_group: CloudWatch log group name
        session_id: Session ID to filter logs by
        region: AWS region name
        start_time_ms: Optional start time in milliseconds since epoch (filter events after this time)
        limit: Maximum number of events to return (not strictly enforced due to pagination)
        max_retries: Maximum number of polling attempts
        retry_interval: Seconds to wait between retry attempts
        required_marker: If set, keep retrying even when events are found until at
            least one event message contains this substring, or retries are exhausted.

    Returns:
        List of log event dictionaries with keys:
        - 'timestamp': milliseconds since epoch
        - 'message': log message string
    """
    import boto3

    client = boto3.client('logs', region_name=region)

    # Get available log streams
    streams = list_log_streams(log_group, region)
    stream_names = [s['name'] for s in streams]

    if not stream_names:
        # Fallback to default stream name if none found
        stream_names = ['BedrockAgentCoreRuntime_ApplicationLogs']

    # Find log streams whose name contains the session ID
    # (e.g. "2026/03/18/[runtime-logs-<session_id>]<uuid>")
    session_streams = [s for s in stream_names if session_id in s]
    logger.info(
        "[get_log_events] log_group=%s session_id=%s matched_streams=%d total_streams=%d",
        log_group, session_id, len(session_streams), len(stream_names),
    )

    all_events: list[dict[str, Any]] = []
    retry_count = 0

    while retry_count < max_retries:
        if retry_count > 0:
            time.sleep(retry_interval)

        # Strategy 1: fetch ALL events from session-specific streams
        if session_streams:
            try:
                params: dict[str, Any] = {
                    'logGroupName': log_group,
                    'logStreamNames': session_streams,
                    'limit': 10000,
                }
                if start_time_ms is not None:
                    params['startTime'] = start_time_ms

                page = 0
                response = client.filter_log_events(**params)
                all_events.extend(response.get('events', []))
                page += 1

                while response.get('nextToken'):
                    params['nextToken'] = response['nextToken']
                    response = client.filter_log_events(**params)
                    all_events.extend(response.get('events', []))
                    page += 1

                logger.info(
                    "[get_log_events] Strategy 1 (stream match): %d events across %d page(s) from streams %s",
                    len(all_events), page, session_streams,
                )
            except Exception as e:
                logger.warning("[get_log_events] Strategy 1 error after %d events: %s", len(all_events), e)

        # Strategy 2: fall back to filterPattern search across all streams
        # (catches events in shared streams like ApplicationLogs)
        if not all_events:
            try:
                params = {
                    'logGroupName': log_group,
                    'filterPattern': f'"{session_id}"',
                    'limit': 10000,
                }
                if start_time_ms is not None:
                    params['startTime'] = start_time_ms

                page = 0
                response = client.filter_log_events(**params)
                all_events.extend(response.get('events', []))
                page += 1

                while response.get('nextToken'):
                    params['nextToken'] = response['nextToken']
                    response = client.filter_log_events(**params)
                    all_events.extend(response.get('events', []))
                    page += 1

                logger.info(
                    "[get_log_events] Strategy 2 (filterPattern): %d events across %d page(s)",
                    len(all_events), page,
                )
            except Exception as e:
                logger.warning("[get_log_events] Strategy 2 error after %d events: %s", len(all_events), e)

        if all_events:
            if not required_marker:
                return all_events
            # Check if any event contains the required marker
            if any(required_marker in e.get("message", "") for e in all_events):
                return all_events
            logger.info(
                "[get_log_events] Found %d events but missing marker '%s'; retrying (%d/%d)",
                len(all_events), required_marker, retry_count + 1, max_retries,
            )

        retry_count += 1
        all_events = []

    return []


def _filter_events_by_session_id(events: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    """
    Filter log events to only those containing the specified session ID.

    Checks both raw message content and parsed JSON messages for session ID matches.

    Args:
        events: List of CloudWatch log event dictionaries
        session_id: Session ID to match

    Returns:
        List of matching log events
    """
    matching = []

    for event in events:
        message = event.get('message', '')

        # Direct string match
        if session_id in message:
            matching.append(event)
            continue

        # Try parsing as JSON and checking sessionId field
        if message.startswith('{'):
            try:
                log_data = json.loads(message)
                if session_id in log_data.get('sessionId', ''):
                    matching.append(event)
                    continue
                # Also check inner message field
                if session_id in log_data.get('message', ''):
                    matching.append(event)
            except json.JSONDecodeError:
                pass

    return matching


def parse_agent_start_time(log_events: list[dict[str, Any]]) -> float | None:
    """
    Parse the agent start time from log events.

    First searches for the "Agent invoked - Start time:" pattern. If not found,
    falls back to the earliest CloudWatch event timestamp as an approximation of
    when the agent started processing.

    Log message format examples:
        - "Agent invoked - Start time: 2026-02-11T19:44:38.558763, Request ID: ..."
        - {"message": "Agent invoked - Start time: ...", "sessionId": "..."}

    Args:
        log_events: List of CloudWatch log event dictionaries

    Returns:
        Unix timestamp (seconds since epoch) of agent start time, or None if not found
    """
    import logging
    logger = logging.getLogger(__name__)

    for event in log_events:
        message = event.get('message', '')

        # Parse JSON-wrapped messages
        if message.startswith('{'):
            try:
                log_data = json.loads(message)
                inner_message = log_data.get('message', '')
            except json.JSONDecodeError:
                inner_message = message
        else:
            inner_message = message

        # Look for "Agent invoked" pattern
        if 'Agent invoked' not in inner_message:
            continue

        # Extract timestamp after "Start time:"
        if 'Start time:' not in inner_message:
            continue

        try:
            # Extract the timestamp portion
            start_time_str = inner_message.split('Start time:')[1].strip()

            # Handle different formats: "2026-02-11T19:44:38.558763, Request ID: ..."
            if ',' in start_time_str:
                start_time_str = start_time_str.split(',')[0].strip()

            # Normalize timezone format for parsing
            if '.' in start_time_str and '+' not in start_time_str and 'Z' not in start_time_str:
                # Add UTC timezone if missing
                start_time_str += '+00:00'
            elif start_time_str.endswith('Z'):
                # Replace Z with +00:00
                start_time_str = start_time_str[:-1] + '+00:00'

            # Parse ISO format timestamp
            start_time_dt = datetime.fromisoformat(start_time_str)
            return start_time_dt.timestamp()

        except (ValueError, IndexError):
            continue

    # Fallback: use the earliest CloudWatch event timestamp.
    # This approximates when the agent started processing, since
    # not all agents emit the "Agent invoked - Start time:" log pattern.
    earliest_ts = None
    for event in log_events:
        ts = event.get('timestamp')
        if ts is not None:
            # CloudWatch timestamps are in milliseconds
            ts_seconds = ts / 1000.0
            if earliest_ts is None or ts_seconds < earliest_ts:
                earliest_ts = ts_seconds

    if earliest_ts is not None:
        logger.info("Used earliest CloudWatch event timestamp as agent_start_time fallback: %.3f", earliest_ts)

    return earliest_ts


def parse_agentcore_request_id(log_events: list[dict[str, Any]]) -> str | None:
    """Extract the AgentCore Request ID from agent application log events.

    The AgentCore runtime injects a ``requestId`` field into the structured
    JSON log lines emitted by the ``bedrock_agentcore.app`` logger.  This ID
    is distinct from the ``ResponseMetadata.RequestId`` (API Gateway request
    ID) and is the value users see in the CloudWatch console.

    Args:
        log_events: List of CloudWatch log event dictionaries.

    Returns:
        The AgentCore request ID string, or ``None`` if not found.
    """
    for event in log_events:
        message = event.get("message", "")
        if not message.startswith("{"):
            continue
        try:
            data = json.loads(message)
            req_id = data.get("requestId")
            if req_id:
                return req_id
        except json.JSONDecodeError:
            continue
    return None


def parse_memory_telemetry(log_events: list[dict[str, Any]]) -> dict[str, int]:
    """Parse memory usage telemetry from agent log events.

    Searches for the ``LOOM_MEMORY_TELEMETRY`` structured log line emitted
    by the agent's MemoryHook after each invocation.

    Log format:
        LOOM_MEMORY_TELEMETRY: retrievals=N, events_sent=M

    Args:
        log_events: List of CloudWatch log event dictionaries.

    Returns:
        Dictionary with ``retrievals`` and ``events_sent`` counts.
        Both default to 0 if no telemetry line is found.
    """
    result = {"retrievals": 0, "events_sent": 0}

    for event in log_events:
        message = event.get("message", "")

        # Parse JSON-wrapped messages
        if message.startswith("{"):
            try:
                log_data = json.loads(message)
                message = log_data.get("message", "")
            except json.JSONDecodeError:
                pass

        if "LOOM_MEMORY_TELEMETRY:" not in message:
            continue

        # Extract values from "LOOM_MEMORY_TELEMETRY: retrievals=N, events_sent=M"
        try:
            telemetry_str = message.split("LOOM_MEMORY_TELEMETRY:")[1].strip()
            for part in telemetry_str.split(","):
                part = part.strip()
                if "=" in part:
                    key, val = part.split("=", 1)
                    key = key.strip()
                    if key in result:
                        result[key] = int(val.strip())
        except (ValueError, IndexError):
            continue

    return result


def get_usage_log_events(
    runtime_id: str,
    session_id: str,
    region: str,
    start_time_ms: int | None = None,
    max_retries: int = 6,
    retry_interval: float = 5.0,
) -> list[dict[str, Any]]:
    """Retrieve USAGE_LOGS events for a session from the vendedlogs log group.

    USAGE_LOGS are written to a separate vendedlogs log group with 1-second
    granularity and contain ``agent.runtime.vcpu.hours.used`` and
    ``agent.runtime.memory.gb_hours.used`` fields.

    Args:
        runtime_id: Agent runtime ID.
        session_id: Session ID to filter by.
        region: AWS region name.
        start_time_ms: Optional start time filter (ms since epoch).
        max_retries: Maximum polling attempts (usage data can be delayed).
        retry_interval: Seconds between retries.

    Returns:
        List of matching log event dicts.
    """
    import boto3

    log_group = f"/aws/vendedlogs/bedrock-agentcore/runtimes/{runtime_id}"
    client = boto3.client("logs", region_name=region)

    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(retry_interval)

        try:
            params: dict[str, Any] = {
                "logGroupName": log_group,
                "filterPattern": f'"{session_id}"',
                "limit": 200,
            }
            if start_time_ms is not None:
                params["startTime"] = start_time_ms

            response = client.filter_log_events(**params)
            events = response.get("events", [])
            if events:
                return events
        except client.exceptions.ResourceNotFoundException:
            return []
        except Exception:
            pass

    return []


def parse_usage_telemetry(log_events: list[dict[str, Any]]) -> dict[str, float]:
    """Parse vCPU and memory usage from USAGE_LOGS events.

    Handles two USAGE_LOGS formats:
      - Flat: top-level ``agent.runtime.vcpu.hours.used`` / ``agent.runtime.memory.gb_hours.used``
      - Nested: ``metrics.agent.runtime.vcpu.hours.used`` / ``metrics.agent.runtime.memory.gb_hours.used``

    We sum the values across all matching events to get total session
    resource consumption for cost calculation.

    Args:
        log_events: List of CloudWatch log event dicts from USAGE_LOGS.

    Returns:
        Dictionary with ``vcpu_hours``, ``memory_gb_hours``, and
        ``elapsed_seconds`` totals.  All default to 0.0.
    """
    result: dict[str, float] = {
        "vcpu_hours": 0.0,
        "memory_gb_hours": 0.0,
        "elapsed_seconds": 0.0,
    }

    for event in log_events:
        message = event.get("message", "")
        if not message.startswith("{"):
            continue

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            continue

        # Handle nested metrics format
        metrics = data.get("metrics", {})

        vcpu = data.get("agent.runtime.vcpu.hours.used") or metrics.get("agent.runtime.vcpu.hours.used")
        mem = data.get("agent.runtime.memory.gb_hours.used") or metrics.get("agent.runtime.memory.gb_hours.used")
        elapsed = data.get("elapsed_time_seconds")

        if vcpu is not None:
            result["vcpu_hours"] += float(vcpu)
        if mem is not None:
            result["memory_gb_hours"] += float(mem)
        if elapsed is not None:
            result["elapsed_seconds"] = max(result["elapsed_seconds"], float(elapsed))

    return result


def parse_usage_events(log_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse individual usage events with timestamps for matching to invocations.

    Each returned dict contains:
      - ``event_timestamp``: ISO timestamp string from the usage log
      - ``event_timestamp_epoch``: Unix epoch seconds (float)
      - ``vcpu_hours``: vCPU-hours used
      - ``memory_gb_hours``: GB-hours used
      - ``session_id``: session ID from the log event

    Args:
        log_events: Raw CloudWatch log event dicts from USAGE_LOGS.

    Returns:
        List of parsed usage event dicts.
    """
    parsed = []

    for event in log_events:
        message = event.get("message", "")
        if not message.startswith("{"):
            continue

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            continue

        metrics = data.get("metrics", {})
        vcpu = data.get("agent.runtime.vcpu.hours.used") or metrics.get("agent.runtime.vcpu.hours.used")
        mem = data.get("agent.runtime.memory.gb_hours.used") or metrics.get("agent.runtime.memory.gb_hours.used")

        if vcpu is None and mem is None:
            continue

        # Extract event_timestamp and convert to epoch
        event_ts = data.get("event_timestamp")
        epoch = None
        if event_ts:
            if isinstance(event_ts, (int, float)):
                # Epoch milliseconds
                epoch = float(event_ts) / 1000.0
            elif isinstance(event_ts, str):
                try:
                    if event_ts.endswith("Z"):
                        event_ts = event_ts[:-1] + "+00:00"
                    epoch = datetime.fromisoformat(event_ts).timestamp()
                except (ValueError, TypeError):
                    pass

        # Fall back to CloudWatch event timestamp
        if epoch is None:
            cw_ts = event.get("timestamp")
            if cw_ts is not None:
                epoch = cw_ts / 1000.0

        if epoch is None:
            continue

        # Normalize event_timestamp to ISO 8601 UTC string
        iso_ts = datetime.fromtimestamp(epoch, tz=tz.utc).isoformat()

        # Extract agent name and session ID from attributes or top-level
        attributes = data.get("attributes", {})
        agent_name = attributes.get("agent.name") or data.get("agent.name")
        session_id = attributes.get("session.id") or data.get("session.id") or data.get("session_id")

        parsed.append({
            "event_timestamp": iso_ts,
            "event_timestamp_epoch": epoch,
            "vcpu_hours": float(vcpu) if vcpu is not None else 0.0,
            "memory_gb_hours": float(mem) if mem is not None else 0.0,
            "agent_name": agent_name,
            "session_id": session_id,
        })

    return parsed


USAGE_LOG_STREAM = "BedrockAgentCoreRuntime_UsageLogs"

# Pricing for AgentCore Memory operations (per 1000)
MEMORY_STM_PRICE_PER_1K = 0.25       # New events (short-term memory)
MEMORY_LTM_RETRIEVAL_PRICE_PER_1K = 0.50  # Memory record retrievals (long-term memory)
MEMORY_LTM_STORAGE_PRICE_PER_1K = 0.75    # Records stored per month (built-in strategies)


def get_usage_log_events_by_time(
    runtime_id: str,
    region: str,
    start_time_ms: int,
    end_time_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Retrieve USAGE_LOGS events for a runtime in a time window.

    Queries only the ``BedrockAgentCoreRuntime_UsageLogs`` log stream
    within the runtime's vendedlogs log group.

    Args:
        runtime_id: Agent runtime ID.
        region: AWS region name.
        start_time_ms: Start time filter (ms since epoch).
        end_time_ms: Optional end time filter (ms since epoch).

    Returns:
        List of raw log event dicts.
    """
    import boto3

    log_group = f"/aws/vendedlogs/bedrock-agentcore/runtimes/{runtime_id}"
    client = boto3.client("logs", region_name=region)

    try:
        params: dict[str, Any] = {
            "logGroupName": log_group,
            "logStreamNames": [USAGE_LOG_STREAM],
            "startTime": start_time_ms,
            "limit": 500,
        }
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        all_events: list[dict[str, Any]] = []
        response = client.filter_log_events(**params)
        all_events.extend(response.get("events", []))

        # Handle pagination
        while response.get("nextToken"):
            params["nextToken"] = response["nextToken"]
            response = client.filter_log_events(**params)
            all_events.extend(response.get("events", []))

        return all_events
    except Exception as e:
        logger.warning("Failed to query USAGE_LOGS for runtime %s: %s", runtime_id, e)
        return []


def get_memory_log_events(
    memory_id: str,
    region: str,
    start_time_ms: int,
    end_time_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Retrieve APPLICATION_LOGS for an AgentCore Memory resource.

    Log group: ``/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/{memory_id}``

    Args:
        memory_id: The AgentCore Memory resource ID.
        region: AWS region name.
        start_time_ms: Start time filter (ms since epoch).
        end_time_ms: Optional end time filter (ms since epoch).

    Returns:
        List of raw CloudWatch log event dicts.
    """
    import boto3

    log_group = f"/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/{memory_id}"
    client = boto3.client("logs", region_name=region)

    try:
        params: dict[str, Any] = {
            "logGroupName": log_group,
            "startTime": start_time_ms,
            "limit": 10000,
        }
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        all_events: list[dict[str, Any]] = []
        response = client.filter_log_events(**params)
        all_events.extend(response.get("events", []))

        while response.get("nextToken"):
            params["nextToken"] = response["nextToken"]
            response = client.filter_log_events(**params)
            all_events.extend(response.get("events", []))

        return all_events
    except client.exceptions.ResourceNotFoundException:
        logger.info("Memory log group not found for %s (not yet created)", memory_id)
        return []
    except Exception as e:
        logger.warning("Failed to query memory logs for %s: %s", memory_id, e)
        return []


def parse_memory_log_events(
    log_events: list[dict[str, Any]],
    tracked_session_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Parse memory APPLICATION_LOGS to count operations and compute costs.

    APPLICATION_LOGS are structured JSON with ``body.log`` describing the
    pipeline step and ``body.requestId`` grouping events per API call.

    These logs capture the LTM processing pipeline (extraction →
    consolidation → storage) that runs asynchronously after STM events
    are written via ``create_event``.  STM event counts are NOT in these
    logs — they are tracked by the agent's MemoryHook telemetry in
    runtime APPLICATION_LOGS.

    Pricing mapping (from APPLICATION_LOGS only):

      - ``"Retrieving memories."`` → LTM retrievals ($0.50 / 1K)
      - ``"Succeeded to upsert N records."`` → LTM records stored ($0.75 / 1K / month, built-in)
      - ``"Processing extraction input"`` → extraction pipeline steps (informational)
      - ``"Processing consolidation input"`` → consolidation pipeline steps (informational)

    Args:
        log_events: Raw CloudWatch log event dicts.
        tracked_session_ids: If provided, only count events whose
            ``session_id`` is in this set.  Events without a
            ``session_id`` are skipped when the filter is active.

    Returns dict with counts and computed costs.
    """
    retrieve_records = 0
    records_stored = 0
    extractions = 0
    consolidations = 0
    errors = 0
    matched_events = 0

    # Per-session accumulators
    session_agg: dict[str, dict[str, Any]] = {}

    import re

    for event in log_events:
        message = event.get("message", "")
        if not message.startswith("{"):
            continue
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            continue

        # Filter by tracked session IDs when provided
        if tracked_session_ids is not None:
            event_session_id = data.get("session_id", "")
            if not event_session_id or event_session_id not in tracked_session_ids:
                continue

        matched_events += 1
        body = data.get("body", {})
        log_text = body.get("log", "")
        sid = data.get("session_id", "unknown")

        if sid not in session_agg:
            session_agg[sid] = {
                "session_id": sid,
                "log_events": 0,
                "retrieve_records": 0,
                "records_stored": 0,
                "extractions": 0,
                "consolidations": 0,
                "errors": 0,
            }
        sess = session_agg[sid]
        sess["log_events"] += 1

        # Classify by body.log message
        if log_text == "Processing extraction input":
            extractions += 1
            sess["extractions"] += 1
        elif log_text == "Processing consolidation input":
            consolidations += 1
            sess["consolidations"] += 1
        elif log_text == "Retrieving memories.":
            retrieve_records += 1
            sess["retrieve_records"] += 1
        elif log_text.startswith("Succeeded to upsert"):
            m = re.search(r"upsert (\d+) records", log_text)
            if m:
                count = int(m.group(1))
                records_stored += count
                sess["records_stored"] += count

        if body.get("isError"):
            errors += 1
            sess["errors"] += 1

    ltm_retrieval_cost = round(retrieve_records / 1000 * MEMORY_LTM_RETRIEVAL_PRICE_PER_1K, 6)
    ltm_storage_cost = round(records_stored / 1000 * MEMORY_LTM_STORAGE_PRICE_PER_1K, 6)

    # Build per-session output with costs
    sessions_out: list[dict[str, Any]] = []
    for sess in session_agg.values():
        s_retrieval_cost = round(sess["retrieve_records"] / 1000 * MEMORY_LTM_RETRIEVAL_PRICE_PER_1K, 6)
        s_storage_cost = round(sess["records_stored"] / 1000 * MEMORY_LTM_STORAGE_PRICE_PER_1K, 6)
        sessions_out.append({
            **sess,
            "ltm_retrieval_cost": s_retrieval_cost,
            "ltm_storage_cost": s_storage_cost,
            "total_cost": round(s_retrieval_cost + s_storage_cost, 6),
        })
    sessions_out.sort(key=lambda s: s["session_id"])

    return {
        "total_log_events": matched_events,
        "retrieve_records": retrieve_records,
        "records_stored": records_stored,
        "extractions": extractions,
        "consolidations": consolidations,
        "errors": errors,
        "ltm_retrieval_cost": ltm_retrieval_cost,
        "ltm_storage_cost": ltm_storage_cost,
        "total_cost": round(ltm_retrieval_cost + ltm_storage_cost, 6),
        "sessions": sessions_out,
    }
