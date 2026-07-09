"""SSE streaming client for agent invocation.

Makes a streaming HTTP request directly to the backend API and prints
text tokens in real-time as they arrive.

Usage:
    python scripts/stream.py <base_url> <agent_id> <prompt> [qualifier]
"""
import json
import sys

import httpx


def main() -> None:
    if len(sys.argv) < 4:
        print(
            "Usage: python scripts/stream.py <base_url> <agent_id> <prompt> [qualifier]",
            file=sys.stderr,
        )
        sys.exit(1)

    base_url = sys.argv[1]
    agent_id = sys.argv[2]
    prompt = sys.argv[3]
    qualifier = sys.argv[4] if len(sys.argv) > 4 else "DEFAULT"

    url = f"{base_url}/api/agents/{agent_id}/invoke"
    payload = {"prompt": prompt, "qualifier": qualifier}

    event_type: str = ""

    with httpx.stream("POST", url, json=payload, timeout=300.0) as response:
        response.raise_for_status()

        for line in response.iter_lines():
            if line.startswith("event: "):
                event_type = line[7:]
                continue

            if not line.startswith("data: "):
                continue

            data = json.loads(line[6:])

            if event_type == "chunk":
                print(data.get("text", ""), end="", flush=True)

            elif event_type == "session_end":
                # Ensure text output ends with a newline before the summary
                print()
                print("---")
                print(f"session_id:              {data['session_id']}")
                print(f"invocation_id:           {data.get('invocation_id', 'N/A')}")
                print(f"qualifier:               {data.get('qualifier', 'DEFAULT')}")
                print(f"client_duration_ms:      {data['client_duration_ms']:.1f}")

                # Display cold_start_latency_ms if available
                if "cold_start_latency_ms" in data:
                    print(f"cold_start_latency_ms:   {data['cold_start_latency_ms']:.1f}")

                # Display agent_start_time if available
                if "agent_start_time" in data:
                    print(f"agent_start_time:        {data['agent_start_time']}")

            elif event_type == "error":
                print(f"\nERROR: {data.get('message', data)}", file=sys.stderr)


if __name__ == "__main__":
    main()
