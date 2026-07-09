"""AgentCore observability configuration via CloudWatch vended logs.

Enables USAGE_LOGS and APPLICATION_LOGS delivery for agent runtimes and
memory resources using the CloudWatch Logs put_delivery_source /
put_delivery_destination / create_delivery APIs.

USAGE_LOGS contain per-second resource consumption data:
  - agent.runtime.vcpu.hours.used
  - agent.runtime.memory.gb_hours.used

APPLICATION_LOGS for memory contain operation-level data:
  - CreateEvent, RetrieveMemoryRecords, Extraction, Consolidation

Reference:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-memory-metrics.html
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def enable_runtime_observability(
    runtime_arn: str,
    runtime_id: str,
    account_id: str,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """Enable USAGE_LOGS and APPLICATION_LOGS delivery for an agent runtime.

    Creates a vendedlogs log group, delivery sources for each log type,
    a delivery destination pointing to the log group, and deliveries
    connecting sources to the destination.

    Args:
        runtime_arn: Full ARN of the agent runtime.
        runtime_id: Agent runtime ID (short form).
        account_id: AWS account ID.
        region: AWS region name.

    Returns:
        Dictionary with ``log_group``, ``usage_delivery_id``, and
        ``app_delivery_id`` keys.
    """
    import boto3

    logs = boto3.client("logs", region_name=region)

    log_group = f"/aws/vendedlogs/bedrock-agentcore/runtimes/{runtime_id}"

    # Ensure log group exists
    try:
        logs.create_log_group(logGroupName=log_group)
        logger.info("Created observability log group: %s", log_group)
    except logs.exceptions.ResourceAlreadyExistsException:
        logger.debug("Log group already exists: %s", log_group)

    result: dict[str, Any] = {"log_group": log_group}

    # Delivery destination (shared by both log types)
    dest_name = f"loom-{runtime_id}-dest"
    log_group_arn = f"arn:aws:logs:{region}:{account_id}:log-group:{log_group}"
    try:
        dest_resp = logs.put_delivery_destination(
            name=dest_name,
            deliveryDestinationType="CWL",
            deliveryDestinationConfiguration={
                "destinationResourceArn": log_group_arn,
            },
        )
        dest_arn = dest_resp["deliveryDestination"]["arn"]
        logger.info("Created delivery destination: %s", dest_name)
    except Exception as e:
        logger.warning("Failed to create delivery destination %s: %s", dest_name, e)
        return result

    # Create delivery for each log type
    for log_type, suffix in [("USAGE_LOGS", "usage"), ("APPLICATION_LOGS", "app")]:
        source_name = f"loom-{runtime_id}-{suffix}-source"
        try:
            logs.put_delivery_source(
                name=source_name,
                logType=log_type,
                resourceArn=runtime_arn,
            )
            logger.info("Created delivery source: %s (%s)", source_name, log_type)
        except Exception as e:
            logger.warning("Failed to create delivery source %s: %s", source_name, e)
            continue

        delivery_key = f"{suffix}_delivery_id"
        try:
            delivery_resp = logs.create_delivery(
                deliverySourceName=source_name,
                deliveryDestinationArn=dest_arn,
            )
            result[delivery_key] = delivery_resp.get("delivery", {}).get("id")
            logger.info("Created delivery for %s: %s", log_type, result.get(delivery_key))
        except Exception as e:
            logger.warning("Failed to create delivery for %s: %s", log_type, e)

    return result


def enable_code_interpreter_observability(
    ci_arn: str,
    ci_id: str,
    account_id: str,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """Enable USAGE_LOGS and APPLICATION_LOGS delivery for a Code Interpreter resource.

    Args:
        ci_arn: Full ARN of the code interpreter resource.
        ci_id: Code interpreter resource ID (short form).
        account_id: AWS account ID.
        region: AWS region name.

    Returns:
        Dictionary with ``log_group``, ``usage_delivery_id``, and
        ``app_delivery_id`` keys.
    """
    import boto3

    logs = boto3.client("logs", region_name=region)

    log_group = f"/aws/vendedlogs/bedrock-agentcore/code-interpreter/{ci_id}"

    try:
        logs.create_log_group(logGroupName=log_group)
        logger.info("Created CI observability log group: %s", log_group)
    except logs.exceptions.ResourceAlreadyExistsException:
        logger.debug("CI log group already exists: %s", log_group)

    result: dict[str, Any] = {"log_group": log_group}

    # Use last 8 chars of ci_id (the random suffix) to keep names short
    ci_short = ci_id[-8:] if len(ci_id) > 8 else ci_id
    dest_name = f"loom-ci-{ci_short}-dest"
    log_group_arn = f"arn:aws:logs:{region}:{account_id}:log-group:{log_group}"
    try:
        dest_resp = logs.put_delivery_destination(
            name=dest_name,
            deliveryDestinationType="CWL",
            deliveryDestinationConfiguration={
                "destinationResourceArn": log_group_arn,
            },
        )
        dest_arn = dest_resp["deliveryDestination"]["arn"]
        logger.info("Created CI delivery destination: %s", dest_name)
    except Exception as e:
        logger.warning("Failed to create CI delivery destination %s: %s", dest_name, e)
        return result

    for log_type, suffix in [("USAGE_LOGS", "usage"), ("APPLICATION_LOGS", "app")]:
        source_name = f"loom-ci-{ci_short}-{suffix}-source"
        try:
            logs.put_delivery_source(
                name=source_name,
                logType=log_type,
                resourceArn=ci_arn,
            )
            logger.info("Created CI delivery source: %s (%s)", source_name, log_type)
        except Exception as e:
            logger.warning("Failed to create CI delivery source %s: %s", source_name, e)
            continue

        delivery_key = f"{suffix}_delivery_id"
        try:
            delivery_resp = logs.create_delivery(
                deliverySourceName=source_name,
                deliveryDestinationArn=dest_arn,
            )
            result[delivery_key] = delivery_resp.get("delivery", {}).get("id")
            logger.info("Created CI delivery for %s: %s", log_type, result.get(delivery_key))
        except Exception as e:
            logger.warning("Failed to create CI delivery for %s: %s", log_type, e)

    return result


def cleanup_runtime_observability(
    runtime_id: str,
    region: str = "us-east-1",
) -> None:
    """Best-effort cleanup of observability resources for a deleted runtime.

    Attempts to delete deliveries, sources, destination, and log group.
    Failures are logged but not raised.

    Args:
        runtime_id: Agent runtime ID.
        region: AWS region name.
    """
    import boto3

    logs = boto3.client("logs", region_name=region)

    dest_name = f"loom-{runtime_id}-dest"

    for suffix in ["usage", "app"]:
        source_name = f"loom-{runtime_id}-{suffix}-source"

        # Delete delivery (need to find it first)
        try:
            deliveries = logs.describe_deliveries()
            for d in deliveries.get("deliveries", []):
                if d.get("deliverySourceName") == source_name:
                    logs.delete_delivery(id=d["id"])
                    logger.info("Deleted delivery %s", d["id"])
        except Exception as e:
            logger.debug("Could not delete delivery for %s: %s", source_name, e)

        # Delete source
        try:
            logs.delete_delivery_source(name=source_name)
            logger.info("Deleted delivery source: %s", source_name)
        except Exception as e:
            logger.debug("Could not delete delivery source %s: %s", source_name, e)

    # Delete destination
    try:
        logs.delete_delivery_destination(name=dest_name)
        logger.info("Deleted delivery destination: %s", dest_name)
    except Exception as e:
        logger.debug("Could not delete delivery destination %s: %s", dest_name, e)

    # Delete log group
    log_group = f"/aws/vendedlogs/bedrock-agentcore/runtimes/{runtime_id}"
    try:
        logs.delete_log_group(logGroupName=log_group)
        logger.info("Deleted observability log group: %s", log_group)
    except Exception as e:
        logger.debug("Could not delete log group %s: %s", log_group, e)


def enable_memory_observability(
    memory_arn: str,
    memory_id: str,
    account_id: str,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """Enable APPLICATION_LOGS delivery for an AgentCore Memory resource.

    Creates a vendedlogs log group, a delivery source for APPLICATION_LOGS,
    a delivery destination, and a delivery connecting them.

    Args:
        memory_arn: Full ARN of the memory resource.
        memory_id: Memory resource ID (short form).
        account_id: AWS account ID.
        region: AWS region name.

    Returns:
        Dictionary with ``log_group`` and ``app_delivery_id`` keys.
    """
    import boto3

    logs = boto3.client("logs", region_name=region)

    log_group = f"/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/{memory_id}"

    # Ensure log group exists
    try:
        logs.create_log_group(logGroupName=log_group)
        logger.info("Created memory observability log group: %s", log_group)
    except logs.exceptions.ResourceAlreadyExistsException:
        logger.debug("Memory log group already exists: %s", log_group)

    result: dict[str, Any] = {"log_group": log_group}

    # Delivery destination
    dest_name = f"loom-mem-{memory_id}-dest"
    log_group_arn = f"arn:aws:logs:{region}:{account_id}:log-group:{log_group}"
    try:
        dest_resp = logs.put_delivery_destination(
            name=dest_name,
            deliveryDestinationType="CWL",
            deliveryDestinationConfiguration={
                "destinationResourceArn": log_group_arn,
            },
        )
        dest_arn = dest_resp["deliveryDestination"]["arn"]
        logger.info("Created memory delivery destination: %s", dest_name)
    except Exception as e:
        logger.warning("Failed to create memory delivery destination %s: %s", dest_name, e)
        return result

    # Delivery source for APPLICATION_LOGS
    source_name = f"loom-mem-{memory_id}-app-source"
    try:
        logs.put_delivery_source(
            name=source_name,
            logType="APPLICATION_LOGS",
            resourceArn=memory_arn,
        )
        logger.info("Created memory delivery source: %s (APPLICATION_LOGS)", source_name)
    except Exception as e:
        logger.warning("Failed to create memory delivery source %s: %s", source_name, e)
        return result

    try:
        delivery_resp = logs.create_delivery(
            deliverySourceName=source_name,
            deliveryDestinationArn=dest_arn,
        )
        result["app_delivery_id"] = delivery_resp.get("delivery", {}).get("id")
        logger.info("Created memory delivery: %s", result.get("app_delivery_id"))
    except Exception as e:
        logger.warning("Failed to create memory delivery: %s", e)

    return result


def cleanup_memory_observability(
    memory_id: str,
    region: str = "us-east-1",
) -> None:
    """Best-effort cleanup of observability resources for a deleted memory.

    Attempts to delete delivery, source, destination, and log group.
    Failures are logged but not raised.

    Args:
        memory_id: Memory resource ID.
        region: AWS region name.
    """
    import boto3

    logs = boto3.client("logs", region_name=region)

    source_name = f"loom-mem-{memory_id}-app-source"
    dest_name = f"loom-mem-{memory_id}-dest"

    # Delete delivery
    try:
        deliveries = logs.describe_deliveries()
        for d in deliveries.get("deliveries", []):
            if d.get("deliverySourceName") == source_name:
                logs.delete_delivery(id=d["id"])
                logger.info("Deleted memory delivery %s", d["id"])
    except Exception as e:
        logger.debug("Could not delete memory delivery for %s: %s", source_name, e)

    # Delete source
    try:
        logs.delete_delivery_source(name=source_name)
        logger.info("Deleted memory delivery source: %s", source_name)
    except Exception as e:
        logger.debug("Could not delete memory delivery source %s: %s", source_name, e)

    # Delete destination
    try:
        logs.delete_delivery_destination(name=dest_name)
        logger.info("Deleted memory delivery destination: %s", dest_name)
    except Exception as e:
        logger.debug("Could not delete memory delivery destination %s: %s", dest_name, e)

    # Delete log group
    log_group = f"/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/{memory_id}"
    try:
        logs.delete_log_group(logGroupName=log_group)
        logger.info("Deleted memory observability log group: %s", log_group)
    except Exception as e:
        logger.debug("Could not delete memory log group %s: %s", log_group, e)
