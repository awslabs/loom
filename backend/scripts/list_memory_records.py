"""List memory records for a given memory ID and namespace (data plane API).

Usage:
    python scripts/list_memory_records.py --memory-id <id> --namespace <ns> [--region <region>]
"""

import argparse
import json

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description="List AgentCore memory records by namespace")
    parser.add_argument("--memory-id", required=True, help="Memory resource ID")
    parser.add_argument("--namespace", required=True, help="Namespace to query (e.g. /strategy/<id>/actor/<id>/)")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    args = parser.parse_args()

    client = boto3.client("bedrock-agentcore", region_name=args.region)

    records: list[dict] = []
    next_token = None
    while True:
        params: dict = {"memoryId": args.memory_id, "namespace": args.namespace, "maxResults": 50}
        if next_token:
            params["nextToken"] = next_token
        resp = client.list_memory_records(**params)
        records.extend(resp.get("memoryRecords", []))
        next_token = resp.get("nextToken")
        if not next_token:
            break

    output = {
        "memory_id": args.memory_id,
        "namespace": args.namespace,
        "total_records": len(records),
        "records": records,
    }
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
