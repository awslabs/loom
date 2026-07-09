"""
Bedrock AgentCore Memory API wrapper.

This module provides functions to interact with AWS Bedrock AgentCore Memory API
for creating, describing, listing, and deleting memory resources.
"""
from typing import Any


def create_memory(
    name: str,
    event_expiry_duration: int,
    description: str | None = None,
    encryption_key_arn: str | None = None,
    memory_execution_role_arn: str | None = None,
    memory_strategies: list[dict] | None = None,
    tags: dict[str, str] | None = None,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """
    Create a new AgentCore Memory resource.

    The create_memory API does not accept tags inline. Tags are applied
    separately via ``tag_resource`` after creation.

    Args:
        name: Name for the memory resource
        event_expiry_duration: Duration in days before memory events expire
        description: Optional description
        encryption_key_arn: Optional KMS key ARN for encryption
        memory_execution_role_arn: Optional IAM role ARN for memory execution
        memory_strategies: Optional list of memory strategy configurations
        tags: Optional tags (applied via tag_resource after creation)
        region: AWS region name

    Returns:
        Dictionary containing the create_memory API response
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)

    params: dict[str, Any] = {
        "name": name,
        "eventExpiryDuration": event_expiry_duration,
    }
    if description:
        params["description"] = description
    if encryption_key_arn:
        params["encryptionKeyArn"] = encryption_key_arn
    if memory_execution_role_arn:
        params["memoryExecutionRoleArn"] = memory_execution_role_arn
    if memory_strategies:
        params["memoryStrategies"] = memory_strategies

    response = client.create_memory(**params)

    # Apply tags via tag_resource (not supported inline by create_memory)
    if tags:
        memory_arn = response.get("memory", {}).get("arn")
        if memory_arn:
            try:
                client.tag_resource(resourceArn=memory_arn, tags=tags)
            except Exception:
                pass  # Best-effort; tags stored locally regardless

    return response


def get_memory(memory_id: str, region: str = "us-east-1") -> dict[str, Any]:
    """
    Get details of an AgentCore Memory resource.

    Args:
        memory_id: The memory resource ID
        region: AWS region name

    Returns:
        Dictionary containing the get_memory API response
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)
    response = client.get_memory(memoryId=memory_id)
    return response


def list_memories(region: str = "us-east-1") -> dict[str, Any]:
    """
    List all AgentCore Memory resources.

    Args:
        region: AWS region name

    Returns:
        Dictionary containing the list_memories API response
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)
    response = client.list_memories()
    return response


def list_memory_records(
    memory_id: str,
    actor_id: str,
    strategies: list[dict] | None = None,
    max_records: int = 100,
    region: str = "us-east-1",
) -> list[dict[str, Any]]:
    """
    List stored memory records for a specific actor (user) within a memory resource.

    The data plane ``list_memory_records`` API requires a ``namespace`` parameter
    (not ``actorId``).  Each LTM strategy defines a namespace template such as
    ``/strategy/{memoryStrategyId}/actor/{actorId}/``.  This function queries
    each strategy's namespace with the given ``actor_id`` substituted and
    aggregates the results.

    Args:
        memory_id: The AWS memory resource ID (e.g. my_memory-zYcvlyGXsK)
        actor_id: The actor identifier to scope the query (Cognito username)
        strategies: List of strategy dicts from the Memory model's
            ``strategies_response``.  Each dict should contain ``strategyId``
            and ``namespaces`` (list of namespace templates).
        max_records: Maximum total records to return across all pages
        region: AWS region name

    Returns:
        List of memory record dicts with keys:
        memoryRecordId, text, memoryStrategyId, createdAt, updatedAt
    """
    import boto3

    # list_memory_records is a data plane operation (bedrock-agentcore),
    # not a control plane operation (bedrock-agentcore-control).
    client = boto3.client("bedrock-agentcore", region_name=region)

    # Build the list of namespaces to query by substituting actor_id into
    # each strategy's namespace template.
    #
    # strategies_response from AWS uses a tagged union format where each
    # entry is e.g. {"userPreferenceMemoryStrategy": {"strategyId": "...", "namespaces": [...]}}
    # We need to unwrap the inner dict to access strategyId and namespaces.
    namespaces: list[str] = []
    for strat in (strategies or []):
        # Unwrap tagged union: get the inner dict from the first (only) key
        inner = strat
        if "strategyId" not in strat:
            for value in strat.values():
                if isinstance(value, dict) and "strategyId" in value:
                    inner = value
                    break

        strat_id = inner.get("strategyId", "")
        for ns_template in inner.get("namespaces", []):
            ns = ns_template.replace("{memoryStrategyId}", strat_id).replace("{actorId}", actor_id)
            # Remove remaining placeholders (e.g. {sessionId} for summary strategies)
            # by trimming at the first unresolved '{'.
            brace = ns.find("{")
            if brace != -1:
                ns = ns[:brace]
            namespaces.append(ns)

    # Fallback: if no strategies provided, try the root namespace
    if not namespaces:
        namespaces = ["/"]

    records: list[dict[str, Any]] = []

    for namespace in namespaces:
        next_token: str | None = None
        while len(records) < max_records:
            params: dict[str, Any] = {
                "memoryId": memory_id,
                "namespace": namespace,
                "maxResults": min(max_records - len(records), 50),
            }
            if next_token:
                params["nextToken"] = next_token

            response = client.list_memory_records(**params)

            for raw in response.get("memoryRecords", []):
                # R5: Improved content field mapping to handle various structures
                content = raw.get("content", {})
                if isinstance(content, dict):
                    text = content.get("text", "")
                elif isinstance(content, str):
                    text = content
                else:
                    text = str(content) if content else ""

                records.append({
                    "memoryRecordId": raw.get("memoryRecordId", ""),
                    "text": text,
                    "memoryStrategyId": raw.get("memoryStrategyId", ""),
                    "createdAt": raw.get("createdAt", ""),
                    "updatedAt": raw.get("updatedAt", ""),
                })

            next_token = response.get("nextToken")
            if not next_token:
                break

    return records


def delete_memory(memory_id: str, region: str = "us-east-1") -> dict[str, Any]:
    """
    Delete an AgentCore Memory resource.

    Args:
        memory_id: The memory resource ID
        region: AWS region name

    Returns:
        Dictionary containing the delete_memory API response
    """
    import boto3

    client = boto3.client('bedrock-agentcore-control', region_name=region)
    response = client.delete_memory(memoryId=memory_id)
    return response
