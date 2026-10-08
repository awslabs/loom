"""
Read-only IAM and Cognito discovery for AgentCore Runtime agents.

This module is deliberately read-only. Loom does not create, modify or
delete IAM roles or policies, and has no code that could: the execution
role an agent runs under is provisioned outside Loom by a platform
engineer (see `shared/iac/role.yaml`) and registered through
Security > Roles. Everything that used to live here — role creation,
trust-policy and base-policy construction, PutRolePolicy syncing on
integration changes, and role deletion — was removed rather than merely
left unused, so there is no latent ability to write IAM.

What remains is discovery: listing roles that already trust
bedrock-agentcore so an operator can pick one, and listing Cognito user
pools. Both are filtered by the caller's entitlement at the router.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def list_agentcore_roles(region: str) -> list[dict[str, Any]]:
    """
    List IAM roles that trust bedrock-agentcore.amazonaws.com.

    Args:
        region: AWS region name

    Returns:
        List of dicts with role_name, role_arn, description
    """
    import boto3

    client = boto3.client("iam", region_name=region)
    roles: list[dict[str, Any]] = []
    marker = None

    while True:
        params: dict[str, Any] = {"MaxItems": 100}
        if marker:
            params["Marker"] = marker

        response = client.list_roles(**params)

        for role in response.get("Roles", []):
            trust_doc = role.get("AssumeRolePolicyDocument", {})
            for statement in trust_doc.get("Statement", []):
                principal = statement.get("Principal", {})
                service = principal.get("Service", "")
                services = [service] if isinstance(service, str) else service
                if "bedrock-agentcore.amazonaws.com" in services:
                    roles.append({
                        "role_name": role["RoleName"],
                        "role_arn": role["Arn"],
                        "description": role.get("Description", ""),
                    })
                    break

        if response.get("IsTruncated"):
            marker = response.get("Marker")
        else:
            break

    return roles


def list_cognito_pools(region: str) -> list[dict[str, Any]]:
    """
    List Cognito user pools accessible in the given region.

    Args:
        region: AWS region name

    Returns:
        List of dicts with pool_id, pool_name
    """
    import boto3

    client = boto3.client("cognito-idp", region_name=region)
    pools: list[dict[str, Any]] = []
    next_token = None

    while True:
        params: dict[str, Any] = {"MaxResults": 60}
        if next_token:
            params["NextToken"] = next_token

        response = client.list_user_pools(**params)

        for pool in response.get("UserPools", []):
            pools.append({
                "pool_id": pool["Id"],
                "pool_name": pool["Name"],
            })

        next_token = response.get("NextToken")
        if not next_token:
            break

    return pools
