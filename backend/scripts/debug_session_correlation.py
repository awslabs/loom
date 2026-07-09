#!/usr/bin/env python3
"""Debug script to correlate session IDs across runtime and memory logs.

Fetches:
  - Runtime USAGE_LOGS (vended) — session IDs from usage events
  - Runtime APPLICATION_LOGS (vended) — session IDs from app logs
  - Memory APPLICATION_LOGS (vended) — session IDs from memory pipeline logs

Then shows overlap/differences to verify session_id is the correct
correlation key between runtime and memory.

Usage:
    python scripts/debug_session_correlation.py --runtime-id agentcore_advisor-VT5MTxDzm9 --memory-id agentcore_advisor-ef7bTG80Pt --region us-east-1
    python scripts/debug_session_correlation.py --runtime-id agentcore_advisor-VT5MTxDzm9 --memory-id agentcore_advisor-ef7bTG80Pt --region us-east-1 --session 589e7d74-17ac-42dc-81e0-7832ea854be4
"""
import argparse
import json
import boto3
from datetime import datetime, timedelta


def fetch_log_events(client, log_group: str, stream: str | None = None,
                     start_ms: int = 0, limit: int = 10000) -> list[dict]:
    """Fetch log events from CloudWatch, optionally filtering to a stream."""
    params = {"logGroupName": log_group, "startTime": start_ms, "limit": limit}
    if stream:
        params["logStreamNames"] = [stream]

    all_events = []
    try:
        response = client.filter_log_events(**params)
        all_events.extend(response.get("events", []))
        while response.get("nextToken"):
            params["nextToken"] = response["nextToken"]
            response = client.filter_log_events(**params)
            all_events.extend(response.get("events", []))
    except client.exceptions.ResourceNotFoundException:
        print(f"  [!] Log group not found: {log_group}")
    except Exception as e:
        print(f"  [!] Error querying {log_group}: {e}")

    return all_events


def extract_session_ids(events: list[dict], field: str = "session_id") -> dict[str, list[dict]]:
    """Extract session IDs from JSON log events, grouped by session."""
    sessions: dict[str, list[dict]] = {}
    for event in events:
        msg = event.get("message", "")
        if not msg.startswith("{"):
            continue
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            continue
        sid = data.get(field, "")
        if sid:
            sessions.setdefault(sid, []).append(data)
    return sessions


def main():
    parser = argparse.ArgumentParser(description="Correlate session IDs across runtime and memory logs")
    parser.add_argument("--runtime-id", required=True, help="AgentCore runtime ID")
    parser.add_argument("--memory-id", required=True, help="AgentCore memory ID")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default: 7)")
    parser.add_argument("--session", help="Specific session ID to search for")
    args = parser.parse_args()

    client = boto3.client("logs", region_name=args.region)
    start_ms = int((datetime.utcnow() - timedelta(days=args.days)).timestamp() * 1000)

    # 1. Runtime USAGE_LOGS
    rt_usage_group = f"/aws/vendedlogs/bedrock-agentcore/runtimes/{args.runtime_id}"
    rt_usage_stream = "BedrockAgentCoreRuntime_UsageLogs"
    print(f"\n{'='*80}")
    print(f"[1] Runtime USAGE_LOGS")
    print(f"    Log group: {rt_usage_group}")
    print(f"    Stream:    {rt_usage_stream}")
    print(f"{'='*80}")
    rt_usage_events = fetch_log_events(client, rt_usage_group, rt_usage_stream, start_ms)
    rt_usage_sessions = extract_session_ids(rt_usage_events, "session_id")
    print(f"    Total events: {len(rt_usage_events)}")
    print(f"    Unique session IDs: {len(rt_usage_sessions)}")
    for sid in sorted(rt_usage_sessions.keys()):
        count = len(rt_usage_sessions[sid])
        print(f"      {sid}  ({count} events)")

    # 2. Runtime APPLICATION_LOGS
    rt_app_stream = "BedrockAgentCoreRuntime_ApplicationLogs"
    print(f"\n{'='*80}")
    print(f"[2] Runtime APPLICATION_LOGS")
    print(f"    Log group: {rt_usage_group}")
    print(f"    Stream:    {rt_app_stream}")
    print(f"{'='*80}")
    rt_app_events = fetch_log_events(client, rt_usage_group, rt_app_stream, start_ms)
    rt_app_sessions = extract_session_ids(rt_app_events, "session_id")
    print(f"    Total events: {len(rt_app_events)}")
    print(f"    Unique session IDs: {len(rt_app_sessions)}")
    for sid in sorted(rt_app_sessions.keys()):
        count = len(rt_app_sessions[sid])
        print(f"      {sid}  ({count} events)")

    # 3. Memory APPLICATION_LOGS
    mem_group = f"/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/{args.memory_id}"
    mem_stream = "BedrockAgentCoreMemory_ApplicationLogs"
    print(f"\n{'='*80}")
    print(f"[3] Memory APPLICATION_LOGS")
    print(f"    Log group: {mem_group}")
    print(f"    Stream:    {mem_stream}")
    print(f"{'='*80}")
    mem_events = fetch_log_events(client, mem_group, mem_stream, start_ms)
    mem_sessions = extract_session_ids(mem_events, "session_id")
    print(f"    Total events: {len(mem_events)}")
    print(f"    Unique session IDs: {len(mem_sessions)}")
    for sid in sorted(mem_sessions.keys()):
        count = len(mem_sessions[sid])
        # Show what operations happened for this session
        ops = {}
        for evt in mem_sessions[sid]:
            log_text = evt.get("body", {}).get("log", "")
            ops[log_text] = ops.get(log_text, 0) + 1
        ops_str = ", ".join(f"{v}x {k[:60]}" for k, v in ops.items())
        print(f"      {sid}  ({count} events: {ops_str})")

    # 4. Correlation analysis
    rt_all = set(rt_usage_sessions.keys()) | set(rt_app_sessions.keys())
    mem_all = set(mem_sessions.keys())

    print(f"\n{'='*80}")
    print(f"[4] CORRELATION ANALYSIS")
    print(f"{'='*80}")
    print(f"    Runtime session IDs (usage + app): {len(rt_all)}")
    print(f"    Memory session IDs:                {len(mem_all)}")

    both = rt_all & mem_all
    rt_only = rt_all - mem_all
    mem_only = mem_all - rt_all

    print(f"\n    In BOTH runtime and memory: {len(both)}")
    for sid in sorted(both):
        print(f"      {sid}")

    print(f"\n    In runtime ONLY (not in memory): {len(rt_only)}")
    for sid in sorted(rt_only):
        print(f"      {sid}")

    print(f"\n    In memory ONLY (not in runtime): {len(mem_only)}")
    for sid in sorted(mem_only):
        print(f"      {sid}")

    # 5. Specific session lookup
    if args.session:
        target = args.session
        print(f"\n{'='*80}")
        print(f"[5] LOOKING FOR SESSION: {target}")
        print(f"{'='*80}")

        if target in rt_usage_sessions:
            print(f"\n    FOUND in Runtime USAGE_LOGS ({len(rt_usage_sessions[target])} events)")
            for evt in rt_usage_sessions[target][:3]:
                print(f"      ts={evt.get('event_timestamp')} agent={evt.get('agent_name')}")
        else:
            print(f"\n    NOT FOUND in Runtime USAGE_LOGS")

        if target in rt_app_sessions:
            print(f"\n    FOUND in Runtime APPLICATION_LOGS ({len(rt_app_sessions[target])} events)")
            for evt in rt_app_sessions[target][:3]:
                print(f"      requestId={evt.get('requestId')} sessionId={evt.get('sessionId')}")
        else:
            print(f"\n    NOT FOUND in Runtime APPLICATION_LOGS")
            # Check if it's under 'sessionId' instead of 'session_id'
            print(f"    Checking alternative field 'sessionId'...")
            alt_sessions = extract_session_ids(rt_app_events, "sessionId")
            if target in alt_sessions:
                print(f"    FOUND under 'sessionId' field! ({len(alt_sessions[target])} events)")
                for evt in alt_sessions[target][:3]:
                    print(f"      requestId={evt.get('requestId')}")
            else:
                print(f"    NOT FOUND under 'sessionId' either")

        if target in mem_sessions:
            print(f"\n    FOUND in Memory APPLICATION_LOGS ({len(mem_sessions[target])} events)")
            for evt in mem_sessions[target]:
                body = evt.get("body", {})
                print(f"      log={body.get('log', '')[:80]}  requestId={body.get('requestId')}")
        else:
            print(f"\n    NOT FOUND in Memory APPLICATION_LOGS")
            # Scan all memory events for any field containing this session ID
            print(f"    Scanning all memory events for '{target}' in any field...")
            found_in = []
            for event in mem_events:
                msg = event.get("message", "")
                if target in msg:
                    found_in.append(msg[:200])
            if found_in:
                print(f"    FOUND in {len(found_in)} raw messages:")
                for m in found_in[:5]:
                    print(f"      {m}")
            else:
                print(f"    NOT FOUND anywhere in memory log messages")

        # Also check the agent application logs (non-vended)
        agent_log_group = f"/aws/bedrock-agentcore/runtimes/{args.runtime_id}-DEFAULT"
        print(f"\n    Checking agent app logs: {agent_log_group}")
        agent_events = fetch_log_events(client, agent_log_group, None, start_ms)
        agent_sessions = extract_session_ids(agent_events, "sessionId")
        if target in agent_sessions:
            print(f"    FOUND in agent app logs ({len(agent_sessions[target])} events)")
            for evt in agent_sessions[target][:3]:
                print(f"      requestId={evt.get('requestId')}")
        else:
            print(f"    NOT FOUND in agent app logs under 'sessionId'")

    # 6. Show sample memory event structure
    if mem_events:
        print(f"\n{'='*80}")
        print(f"[6] SAMPLE MEMORY EVENT STRUCTURE")
        print(f"{'='*80}")
        for event in mem_events[:2]:
            msg = event.get("message", "")
            if msg.startswith("{"):
                try:
                    data = json.loads(msg)
                    print(f"\n    Top-level keys: {list(data.keys())}")
                    print(f"    session_id: {data.get('session_id')}")
                    print(f"    body keys: {list(data.get('body', {}).keys())}")
                    print(f"    body.log: {data.get('body', {}).get('log', '')[:100]}")
                    print(f"    body.requestId: {data.get('body', {}).get('requestId')}")
                    print(f"    Full event (truncated):")
                    print(f"    {json.dumps(data, indent=2)[:500]}")
                except json.JSONDecodeError:
                    pass


if __name__ == "__main__":
    main()
