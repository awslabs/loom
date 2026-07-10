"""
IAM execution role management for AgentCore Runtime agents.

This module provides functions to create, update, and delete IAM roles
used by AgentCore Runtime agents, including trust policies and
integration-specific permissions. Also provides discovery functions
for listing existing AgentCore roles and Cognito user pools.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

def _iam_tags(
    tag_policies: list[dict[str, Any]] | None = None,
    extra: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Build IAM-format tags from tag policies and extra overrides.

    Args:
        tag_policies: List of dicts with keys: key, default_value.
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
    return [{"Key": k, "Value": v} for k, v in tags.items()]


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


def create_execution_role(
    agent_name: str,
    runtime_id: str,
    region: str,
    account_id: str,
    tag_policies: list[dict[str, Any]] | None = None,
    extra_tags: dict[str, str] | None = None,
    code_interpreter: bool = False,
    agent_id: int | str | None = None,
) -> str:
    """
    Create an IAM execution role for an agent runtime.

    Args:
        agent_name: Name of the agent (used for resource scoping)
        runtime_id: AgentCore Runtime ID (used in role naming)
        region: AWS region name
        account_id: AWS account ID
        code_interpreter: If True, include Code Interpreter permissions
        agent_id: Loom agent DB ID (used to scope access to its LLM provider
            API key secret, if any)

    Returns:
        ARN of the created IAM role
    """
    import boto3

    client = boto3.client("iam")

    role_name = f"loom-agent-{runtime_id}"
    trust_policy = build_trust_policy()
    base_policy = build_base_policy(
        region, account_id, agent_name, code_interpreter=code_interpreter, agent_id=agent_id
    )

    response = client.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description=f"Execution role for Loom agent: {agent_name}",
        MaxSessionDuration=3600,
        Tags=_iam_tags(tag_policies=tag_policies, extra=extra_tags),
    )

    client.put_role_policy(
        RoleName=role_name,
        PolicyName="loom-agent-base-policy",
        PolicyDocument=json.dumps(base_policy),
    )

    return response["Role"]["Arn"]


def build_trust_policy() -> dict:
    """
    Build the trust policy document for an AgentCore Runtime execution role.

    Returns:
        IAM trust policy allowing bedrock-agentcore.amazonaws.com as service principal
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
            }
        ],
    }


def build_base_policy(
    region: str,
    account_id: str,
    agent_name: str,
    code_interpreter: bool = False,
    agent_id: int | str | None = None,
) -> dict:
    """
    Build the base IAM policy for workload access token permissions.

    Args:
        region: AWS region name
        account_id: AWS account ID
        agent_name: Name of the agent (used for resource scoping). When this
            role is shared across a family of agents (e.g. a managed role
            like "loom-role-demo"), this is the common name prefix (e.g.
            "demo") rather than one agent's exact name — matching the
            wildcard scoping already used for logs/workload-identity above.
        code_interpreter: If True, include Code Interpreter sandbox permissions
        agent_id: Unused (kept for backward-compatible call signatures).
            Secrets Manager access is scoped by agent_name below, not by
            agent_id, since agent_id isn't known at shared-role creation time.

    Returns:
        IAM policy document with bedrock-agentcore workload identity permissions
    """
    statements = [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:GetWorkloadAccessToken",
                "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
            ],
            "Resource": [
                f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default",
                f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default/workload-identity/{agent_name}-*",
                f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default/workload-identity/harness_{agent_name}-*",
            ],
        },
        {
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:GetResourceOauth2Token",
            ],
            "Resource": [
                f"arn:aws:bedrock-agentcore:{region}:{account_id}:token-vault/default/oauth2credentialprovider/*",
            ],
        },
        {
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:GetResourceApiKey",
            ],
            "Resource": [
                f"arn:aws:bedrock-agentcore:{region}:{account_id}:token-vault/default/apikeycredentialprovider/*",
            ],
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:DescribeLogGroups",
                "logs:DescribeLogStreams",
            ],
            "Resource": [
                f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/{agent_name}*",
                f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/{agent_name}*:*",
                f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/harness_{agent_name}*",
                f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/harness_{agent_name}*:*",
            ],
        },
    ]
    statements.append({
        "Effect": "Allow",
        "Action": [
            "secretsmanager:GetSecretValue",
        ],
        "Resource": [
            f"arn:aws:secretsmanager:{region}:{account_id}:secret:loom/agents/{agent_name}*",
            f"arn:aws:secretsmanager:{region}:{account_id}:secret:loom/agents/harness_{agent_name}*",
        ],
    })
    if code_interpreter:
        statements.append({
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:CreateCodeInterpreter",
                "bedrock-agentcore:DeleteCodeInterpreter",
                "bedrock-agentcore:GetCodeInterpreter",
                "bedrock-agentcore:ListCodeInterpreters",
                "bedrock-agentcore:StartCodeInterpreterSession",
                "bedrock-agentcore:StopCodeInterpreterSession",
                "bedrock-agentcore:InvokeCodeInterpreter",
                "bedrock-agentcore:GetCodeInterpreterSession",
                "bedrock-agentcore:ListCodeInterpreterSessions",
            ],
            "Resource": [
                f"arn:aws:bedrock-agentcore:{region}:aws:code-interpreter/*",
                f"arn:aws:bedrock-agentcore:{region}:{account_id}:code-interpreter/*",
                f"arn:aws:bedrock-agentcore:{region}:{account_id}:code-interpreter-custom/*",
            ],
        })
    return {
        "Version": "2012-10-17",
        "Statement": statements,
    }


def build_integration_policy_statements(integrations: list[dict]) -> list[dict]:
    """
    Generate IAM policy statements for each enabled integration.

    Supports integration types: s3, bedrock, lambda, dynamodb, sqs, sns.

    Args:
        integrations: List of integration dicts, each with:
            - integration_type: Type of integration (e.g., 's3', 'bedrock')
            - integration_config: JSON string with integration-specific config

    Returns:
        List of IAM policy statement dicts

    Raises:
        ValueError: If required config fields are missing for an integration type
    """
    statements: list[dict] = []

    for integration in integrations:
        integration_type = integration.get("integration_type", "")
        config_str = integration.get("integration_config", "{}")

        try:
            config = json.loads(config_str) if isinstance(config_str, str) else config_str
        except json.JSONDecodeError:
            logger.warning(
                "Skipping integration '%s': invalid JSON config: %s",
                integration_type,
                config_str,
            )
            continue

        if integration_type == "s3":
            bucket = config.get("bucket")
            if not bucket:
                raise ValueError(
                    "S3 integration requires 'bucket' in config"
                )
            prefix = config.get("prefix", "*")
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket}",
                    f"arn:aws:s3:::{bucket}/{prefix}",
                ],
            })

        elif integration_type == "bedrock":
            region = config.get("region")
            model_id = config.get("model_id")
            if not region or not model_id:
                raise ValueError(
                    "Bedrock integration requires 'region' and 'model_id' in config"
                )
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                "Resource": f"arn:aws:bedrock:{region}::foundation-model/{model_id}",
            })

        elif integration_type == "lambda":
            function_arn = config.get("function_arn")
            if not function_arn:
                raise ValueError(
                    "Lambda integration requires 'function_arn' in config"
                )
            statements.append({
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": function_arn,
            })

        elif integration_type == "dynamodb":
            table_arn = config.get("table_arn")
            if not table_arn:
                raise ValueError(
                    "DynamoDB integration requires 'table_arn' in config"
                )
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:Query",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                ],
                "Resource": [
                    table_arn,
                    f"{table_arn}/index/*",
                ],
            })

        elif integration_type == "sqs":
            queue_arn = config.get("queue_arn")
            if not queue_arn:
                raise ValueError(
                    "SQS integration requires 'queue_arn' in config"
                )
            statements.append({
                "Effect": "Allow",
                "Action": [
                    "sqs:SendMessage",
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                ],
                "Resource": queue_arn,
            })

        elif integration_type == "sns":
            topic_arn = config.get("topic_arn")
            if not topic_arn:
                raise ValueError(
                    "SNS integration requires 'topic_arn' in config"
                )
            statements.append({
                "Effect": "Allow",
                "Action": "sns:Publish",
                "Resource": topic_arn,
            })

    return statements


def update_role_policy(
    role_name: str,
    integrations: list[dict],
    region: str,
    account_id: str,
    agent_name: str,
    code_interpreter: bool = False,
    agent_id: int | str | None = None,
) -> None:
    """
    Update the inline policy on an execution role.

    Args:
        role_name: IAM role name to update
        integrations: List of integration dicts for policy generation
        region: AWS region name
        account_id: AWS account ID
        agent_name: Name of the agent (used for resource scoping)
        code_interpreter: If True, include Code Interpreter permissions
        agent_id: Loom agent DB ID (used to scope access to its LLM provider
            API key secret, if any)
    """
    import boto3

    client = boto3.client("iam")

    base_policy = build_base_policy(
        region, account_id, agent_name, code_interpreter=code_interpreter, agent_id=agent_id
    )
    integration_statements = build_integration_policy_statements(integrations)

    if integration_statements:
        base_policy["Statement"].extend(integration_statements)

    client.put_role_policy(
        RoleName=role_name,
        PolicyName="loom-agent-base-policy",
        PolicyDocument=json.dumps(base_policy),
    )


def delete_execution_role(role_name: str) -> None:
    """
    Delete an IAM role and its inline policies.

    Args:
        role_name: IAM role name to delete
    """
    import boto3

    client = boto3.client("iam")

    policies_response = client.list_role_policies(RoleName=role_name)
    for policy_name in policies_response.get("PolicyNames", []):
        client.delete_role_policy(RoleName=role_name, PolicyName=policy_name)

    client.delete_role(RoleName=role_name)
