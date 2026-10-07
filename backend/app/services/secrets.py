"""Secrets Manager wrapper with in-memory caching."""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# In-memory cache: secret_name -> (value, expiry_time)
_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


# The kinds of secret this module stores. Matched against a path's segments so
# the logs can say what was written without echoing the path.
_KINDS = (
    "oauth2-client-secret",
    "user-client-secret",
    "cognito-client-secret",
    "client-secret",
    "llm-provider-api-key",
    "litellm-master-key",
    "admin-api-key",
    "api-key",
    "user-tokens",
)


def _kind(name: str) -> str:
    """What kind of secret a path refers to — "admin-api-key", say.

    These logs confirm that a write or delete actually happened, which is the
    operationally useful part. The full path adds only a precise credential
    locator, and it is a deterministic function of the resource id, so every
    caller can identify the resource more readably than `loom/mcp/42/...`
    reads. Logging the kind keeps the signal without a line that looks like a
    leaked secret to a scanner or a reviewer.

    Matched against a vocabulary rather than taken as the trailing segment:
    the per-user paths end in the user's subject identifier
    (`loom/authorizers/3/user-tokens/{sub}`), so "last segment" would have
    swapped a credential locator for a user identifier. An unrecognised shape
    degrades to "secret" rather than echoing whatever it happens to end with.
    """
    segments = set(name.strip("/").split("/"))
    for kind in _KINDS:
        if kind in segments:
            return kind
    return "secret"


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

    from app.services.redaction import redacted_error

    client = boto3.client("secretsmanager", region_name=region)

    try:
        return _write_secret(client, name, secret_value, description)
    except Exception as e:
        # The request body carried the secret, and AWS validation errors can
        # echo an offending parameter back. Re-raise with the value scrubbed
        # and the original suppressed, so none of the ~20 callers that log
        # this exception can write the secret to CloudWatch.
        # The path is deliberately left out of the message. It is a pure
        # function of the resource id and the secret kind, so every caller can
        # say which resource far more readably than `loom/mcp/42/...` reads —
        # and a credential-shaped string in an error that gets logged costs a
        # scanner finding and a security review every time, for no diagnostic
        # gain. The AWS error code is what is actually useful here.
        raise SecretWriteError(
            f"Could not write the secret: {redacted_error(e, secret_value)}"
        ) from None


class SecretWriteError(RuntimeError):
    """A secret could not be written. Message is scrubbed of the value."""


def _write_secret(client, name: str, secret_value: str, description: str) -> str:
    try:
        response = client.create_secret(
            Name=name,
            Description=description,
            SecretString=secret_value,
        )
        arn = response["ARN"]
        logger.info("Created a %s secret", _kind(name))
        return arn
    except client.exceptions.ResourceExistsException:
        # Update existing secret
        response = client.put_secret_value(
            SecretId=name,
            SecretString=secret_value,
        )
        arn = response["ARN"]
        logger.info("Updated an existing %s secret", _kind(name))
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
            logger.info("Restored and updated a %s secret (was pending deletion)", _kind(name))
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
        logger.info("Deleted a %s secret", _kind(name))
    except Exception as e:
        logger.warning("Failed to delete a %s secret: %s", _kind(name), e)

    _cache.pop(name, None)
