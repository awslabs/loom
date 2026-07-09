"""Secrets Manager wrapper with in-memory caching."""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# In-memory cache: secret_name -> (value, expiry_time)
_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def store_secret(name: str, secret_value: str, region: str, description: str = "") -> str:
    """
    Store a secret in AWS Secrets Manager.

    Args:
        name: Secret name (e.g., 'loom/agents/{agent_id}/cognito-client-secret')
        secret_value: The secret string to store
        region: AWS region name
        description: Optional description for the secret

    Returns:
        The ARN of the created secret
    """
    import boto3

    client = boto3.client("secretsmanager", region_name=region)

    try:
        response = client.create_secret(
            Name=name,
            Description=description,
            SecretString=secret_value,
        )
        arn = response["ARN"]
        logger.info("Created secret %s", name)
        return arn
    except client.exceptions.ResourceExistsException:
        # Update existing secret
        response = client.put_secret_value(
            SecretId=name,
            SecretString=secret_value,
        )
        arn = response["ARN"]
        logger.info("Updated existing secret %s", name)
        return arn
    except client.exceptions.InvalidRequestException as e:
        if "scheduled for deletion" in str(e):
            # Restore the secret then update its value
            client.restore_secret(SecretId=name)
            response = client.put_secret_value(
                SecretId=name,
                SecretString=secret_value,
            )
            arn = response["ARN"]
            logger.info("Restored and updated secret %s (was pending deletion)", name)
            return arn
        raise


def get_secret(name: str, region: str) -> str:
    """
    Retrieve a secret from AWS Secrets Manager with in-memory caching.

    Args:
        name: Secret name or ARN
        region: AWS region name

    Returns:
        The secret string value
    """
    now = time.time()
    cached = _cache.get(name)
    if cached and cached[1] > now:
        return cached[0]

    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=name)
    value = response["SecretString"]

    _cache[name] = (value, now + _CACHE_TTL_SECONDS)
    return value


def delete_secret(name: str, region: str) -> None:
    """
    Delete a secret from AWS Secrets Manager.

    Args:
        name: Secret name or ARN
        region: AWS region name
    """
    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    try:
        client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        logger.info("Deleted secret %s", name)
    except Exception as e:
        logger.warning("Failed to delete secret %s: %s", name, e)

    _cache.pop(name, None)
