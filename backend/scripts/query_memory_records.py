"""Query LTM records from AgentCore memory (data plane API).

Usage:
    python scripts/query_memory_records.py --memory-id <id> --actor-id <actor> [--region <region>]
"""

import argparse
import json

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description="Query AgentCore memory records")
    parser.add_argument("--memory-id", required=True, help="Memory resource ID")
    parser.add_argument("--actor-id", required=True, help="Actor ID (Cognito username or sub)")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    args = parser.parse_args()

    control = boto3.client("bedrock-agentcore-control", region_name=args.region)
    client = boto3.client("bedrock-agentcore", region_name=args.region)

    mem = control.get_memory(memoryId=args.memory_id)
    strategies = mem.get("memory", {}).get("strategies", [])

    records: list[dict] = []
    for strat in strategies:
        # Unwrap tagged union format from AWS get_memory response
        inner = strat
        if "strategyId" not in strat:
            for value in strat.values():
                if isinstance(value, dict) and "strategyId" in value:
                    inner = value
                    break
        strat_id = inner.get("strategyId", "")
        for ns_tmpl in inner.get("namespaces", []):
            ns = ns_tmpl.replace("{memoryStrategyId}", strat_id).replace("{actorId}", args.actor_id)
            brace = ns.find("{")
            if brace != -1:
                ns = ns[:brace]

            next_token = None
            while True:
                params: dict = {"memoryId": args.memory_id, "namespace": ns, "maxResults": 50}
                if next_token:
                    params["nextToken"] = next_token
                resp = client.list_memory_records(**params)
                records.extend(resp.get("memoryRecords", []))
                next_token = resp.get("nextToken")
                if not next_token:
                    break

    output = {
        "actor_id": args.actor_id,
        "memory_id": args.memory_id,
        "total_records": len(records),
        "records": records,
    }
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
