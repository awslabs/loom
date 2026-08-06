"""
AgentCore Runtime deployment and configuration management.

This module provides functions to deploy and manage AgentCore Runtime agents,
manage secrets via AWS Secrets Manager, and store large configuration values in S3.

Artifact bundling has been moved to the platforms package
(see app.services.platforms) which provides a provider-agnostic interface.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AGENT_SOURCE_DIR = Path(__file__).resolve().parents[3] / "agents" / "strands_agent"


def _merge_tags(
    tag_policies: list[dict[str, Any]] | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a merged tag dict from tag policies and extra overrides.

    Args:
        tag_policies: List of dicts with keys: key, default_value.
            If None, returns only extra tags (backwards-compatible fallback).
        extra: Additional tag key-value pairs that override policy defaults.
    """
    tags: dict[str, str] = {}
    if tag_policies:
        for policy in tag_policies:
            val = policy.get("default_value")
            if val:
                tags[policy["key"]] = val
    if extra:
        tags.update(extra)
    return tags


def create_runtime(
    name: str,
    description: str,
    role_arn: str,
    env_vars: dict[str, str],
    network_mode: str = "PUBLIC",
    vpc_subnet_ids: list[str] | None = None,
    vpc_security_group_ids: list[str] | None = None,
    protocol: str = "HTTP",
    lifecycle_config: dict | None = None,
    authorizer_config: dict | None = None,
    artifact_bucket: str = "",
    artifact_prefix: str = "",
    tags: dict[str, str] | None = None,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """
    Create a new AgentCore agent runtime.

    Args:
        name: Name for the agent runtime
        description: Description of the agent
        role_arn: IAM role ARN for execution
        env_vars: Environment variables to inject
        network_mode: Network mode (PUBLIC or VPC)
        vpc_subnet_ids: Subnet IDs for VPC network mode
        vpc_security_group_ids: Security group IDs for VPC network mode
        protocol: Server protocol (HTTP or MCP)
        lifecycle_config: Optional lifecycle configuration
        authorizer_config: Optional authorizer configuration
        artifact_bucket: S3 bucket containing the artifact
        artifact_prefix: S3 key/prefix for the artifact
        tags: Additional tags to merge with defaults
        region: AWS region name

    Returns:
        create_agent_runtime API response
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)

    params: dict[str, Any] = {
        "agentRuntimeName": name,
        "description": description,
        "agentRuntimeArtifact": {
            "codeConfiguration": {
                "code": {
                    "s3": {
                        "bucket": artifact_bucket,
                        "prefix": artifact_prefix,
                    }
                },
                "runtime": "PYTHON_3_13",
                "entryPoint": ["opentelemetry-instrument", "src/handler.py"],
            }
        },
        "roleArn": role_arn,
        "protocolConfiguration": {"serverProtocol": protocol},
        "environmentVariables": env_vars,
        "tags": _merge_tags(extra=tags),
    }

    network_config: dict[str, Any] = {"networkMode": network_mode}
    if network_mode == "VPC" and (vpc_subnet_ids or vpc_security_group_ids):
        network_config["networkModeConfig"] = {
            "subnets": vpc_subnet_ids or [],
            "securityGroups": vpc_security_group_ids or [],
        }
    params["networkConfiguration"] = network_config

    if lifecycle_config is not None:
        params["lifecycleConfiguration"] = lifecycle_config
    if authorizer_config is not None:
        params["authorizerConfiguration"] = authorizer_config

    response = client.create_agent_runtime(**params)
    return response


def create_runtime_endpoint(
    runtime_id: str,
    name: str,
    description: str = "",
    tags: dict[str, str] | None = None,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """
    Create an endpoint for an existing agent runtime.

    Args:
        runtime_id: AgentCore Runtime ID
        name: Name for the endpoint
        description: Optional endpoint description
        tags: Additional tags to merge with defaults
        region: AWS region name

    Returns:
        create_agent_runtime_endpoint API response
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)

    response = client.create_agent_runtime_endpoint(
        agentRuntimeId=runtime_id,
        name=name,
        description=description,
        tags=_merge_tags(extra=tags),
    )
    return response


def get_runtime(runtime_id: str, region: str) -> dict[str, Any]:
    """
    Get the full details of an agent runtime.

    Args:
        runtime_id: AgentCore Runtime ID
        region: AWS region name

    Returns:
        Full get_agent_runtime API response
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    return client.get_agent_runtime(agentRuntimeId=runtime_id)


def get_runtime_endpoint(
    runtime_id: str, endpoint_name: str, region: str
) -> dict[str, Any]:
    """
    Get the full details of a runtime endpoint.

    Args:
        runtime_id: AgentCore Runtime ID
        endpoint_name: Name of the endpoint
        region: AWS region name

    Returns:
        Full get_agent_runtime_endpoint API response
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    return client.get_agent_runtime_endpoint(
        agentRuntimeId=runtime_id, endpointName=endpoint_name
    )


def delete_runtime_endpoint(
    runtime_id: str, endpoint_name: str, region: str
) -> None:
    """
    Delete a runtime endpoint.

    Args:
        runtime_id: AgentCore Runtime ID
        endpoint_name: Name of the endpoint to delete
        region: AWS region name
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    client.delete_agent_runtime_endpoint(
        agentRuntimeId=runtime_id, endpointName=endpoint_name
    )


def delete_runtime(runtime_id: str, region: str) -> None:
    """
    Delete an agent runtime.

    Args:
        runtime_id: AgentCore Runtime ID to delete
        region: AWS region name
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    client.delete_agent_runtime(agentRuntimeId=runtime_id)


def update_runtime(
    runtime_id: str,
    description: str | None = None,
    env_vars: dict[str, str] | None = None,
    role_arn: str | None = None,
    authorizer_config: dict[str, Any] | None = None,
    artifact_bucket: str | None = None,
    artifact_prefix: str | None = None,
    network_mode: str | None = None,
    vpc_subnet_ids: list[str] | None = None,
    vpc_security_group_ids: list[str] | None = None,
    lifecycle_config: dict | None = None,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """
    Update an existing agent runtime.

    Args:
        runtime_id: AgentCore Runtime ID to update
        description: Optional updated description
        env_vars: Optional updated environment variables
        role_arn: Optional updated role ARN
        authorizer_config: Optional authorizer configuration (e.g., {"customJWTAuthorizer": {...}})
        artifact_bucket: Optional S3 bucket for updated artifact
        artifact_prefix: Optional S3 key for updated artifact
        network_mode: Optional updated network mode
        lifecycle_config: Optional updated lifecycle configuration
        region: AWS region name

    Returns:
        update_agent_runtime API response
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)

    params: dict[str, Any] = {"agentRuntimeId": runtime_id}
    if description is not None:
        params["description"] = description
    if env_vars is not None:
        params["environmentVariables"] = env_vars
    if role_arn is not None:
        params["roleArn"] = role_arn
    if authorizer_config is not None:
        params["authorizerConfiguration"] = authorizer_config
    if artifact_bucket and artifact_prefix:
        params["agentRuntimeArtifact"] = {
            "codeConfiguration": {
                "code": {
                    "s3": {
                        "bucket": artifact_bucket,
                        "prefix": artifact_prefix,
                    }
                },
                "runtime": "PYTHON_3_13",
                "entryPoint": ["opentelemetry-instrument", "src/handler.py"],
            }
        }
    if network_mode is not None:
        network_config: dict[str, Any] = {"networkMode": network_mode}
        if network_mode == "VPC" and (vpc_subnet_ids or vpc_security_group_ids):
            network_config["networkModeConfig"] = {
                "subnets": vpc_subnet_ids or [],
                "securityGroups": vpc_security_group_ids or [],
            }
        params["networkConfiguration"] = network_config
    if lifecycle_config is not None:
        params["lifecycleConfiguration"] = lifecycle_config

    return client.update_agent_runtime(**params)


# Patterns that indicate a value may contain a secret
_SECRET_PATTERNS = [
    re.compile(r"^sk-[a-zA-Z0-9]{20,}"),       # OpenAI-style API keys
    re.compile(r"^AKIA[A-Z0-9]{16}"),            # AWS access key IDs
    re.compile(r"^ghp_[a-zA-Z0-9]{36,}"),        # GitHub personal access tokens
    re.compile(r"^gho_[a-zA-Z0-9]{36,}"),        # GitHub OAuth tokens
    re.compile(r"^xox[bpsar]-"),                  # Slack tokens
    re.compile(r"^eyJ[a-zA-Z0-9_-]{10,}\."),     # JWT tokens
]

_SECRET_KEYWORDS = ["password", "secret", "token", "api_key", "apikey", "private_key"]


def validate_config_values(config: dict[str, str]) -> list[str]:
    """
    Validate that configuration values do not appear to contain secrets.

    Args:
        config: Dictionary of configuration key-value pairs

    Returns:
        List of warning messages for suspicious values
    """
    warnings: list[str] = []

    for key, value in config.items():
        key_lower = key.lower()

        for keyword in _SECRET_KEYWORDS:
            if keyword in key_lower:
                warnings.append(
                    f"Key '{key}' appears to be a secret based on its name. "
                    f"Consider using Secrets Manager instead."
                )
                break

        for pattern in _SECRET_PATTERNS:
            if pattern.match(value):
                warnings.append(
                    f"Value for key '{key}' matches a known secret pattern. "
                    f"Use Secrets Manager to store this value securely."
                )
                break

    return warnings


def store_secret(name: str, value: str, region: str) -> str:
    """
    Store a secret in AWS Secrets Manager.

    Args:
        name: Name for the secret
        value: Secret value to store
        region: AWS region name

    Returns:
        The ARN of the created secret
    """
    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    response = client.create_secret(Name=name, SecretString=value)
    return response["ARN"]


def update_secret(secret_arn: str, value: str, region: str) -> None:
    """
    Update an existing secret value in Secrets Manager.

    Args:
        secret_arn: ARN of the secret to update
        value: New secret value
        region: AWS region name
    """
    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    client.put_secret_value(SecretId=secret_arn, SecretString=value)


def delete_secret(secret_arn: str, region: str) -> None:
    """
    Delete a secret from Secrets Manager.

    Args:
        secret_arn: ARN of the secret to delete
        region: AWS region name
    """
    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    client.delete_secret(SecretId=secret_arn, ForceDeleteWithoutRecovery=True)


def store_large_config(
    agent_name: str,
    key: str,
    value: str,
    bucket: str,
    region: str,
) -> str:
    """
    Store a large configuration value in S3.

    Args:
        agent_name: Name of the agent (used as S3 key prefix)
        key: Configuration key name
        value: Configuration value to store
        bucket: S3 bucket name
        region: AWS region name

    Returns:
        S3 URI in the format s3://{bucket}/{agent_name}/config/{key}
    """
    import boto3

    client = boto3.client("s3", region_name=region)
    s3_key = f"{agent_name}/config/{key}"

    client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=value.encode("utf-8"),
        ContentType="text/plain",
    )

    return f"s3://{bucket}/{s3_key}"
