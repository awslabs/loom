import json
import logging
import boto3
from typing import Any

logger = logging.getLogger(__name__)


def get_role_policy_details(role_name: str, region: str) -> dict[str, Any]:
    """Fetch inline and managed policy details for an IAM role."""
    iam = boto3.client("iam", region_name=region)

    policy_statements: list[dict] = []

    # Get inline policies
    inline_names = iam.list_role_policies(RoleName=role_name)["PolicyNames"]
    for policy_name in inline_names:
        resp = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
        doc = resp["PolicyDocument"]
        if isinstance(doc, str):
            doc = json.loads(doc)
        for stmt in doc.get("Statement", []):
            policy_statements.append(stmt)

    # Get attached managed policies
    attached = iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]
    for policy in attached:
        policy_resp = iam.get_policy(PolicyArn=policy["PolicyArn"])
        version_id = policy_resp["Policy"]["DefaultVersionId"]
        version_resp = iam.get_policy_version(PolicyArn=policy["PolicyArn"], VersionId=version_id)
        doc = version_resp["PolicyVersion"]["Document"]
        if isinstance(doc, str):
            doc = json.loads(doc)
        for stmt in doc.get("Statement", []):
            policy_statements.append(stmt)

    return {"statements": policy_statements}


def create_iam_role_with_policy(
    role_name: str,
    policy_document: dict,
    region: str,
    account_id: str,
    tags: list[dict[str, str]] | None = None,
) -> str:
    """Create a new IAM role with trust policy for bedrock-agentcore and attach inline policy."""
    iam = boto3.client("iam", region_name=region)

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    iam_tags = tags if tags else [
        {"Key": "managed-by", "Value": "loom"},
    ]

    resp = iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description=f"Managed role for Loom agents: {role_name}",
        Tags=iam_tags,
    )
    role_arn = resp["Role"]["Arn"]

    if policy_document.get("Statement"):
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="loom-managed-policy",
            PolicyDocument=json.dumps(policy_document),
        )

    return role_arn


def update_iam_role_policy(role_name: str, policy_document: dict, region: str) -> None:
    """Update the inline policy on a managed IAM role."""
    iam = boto3.client("iam", region_name=region)
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="loom-managed-policy",
        PolicyDocument=json.dumps(policy_document),
    )


def delete_iam_role(role_name: str, region: str) -> None:
    """Delete an IAM role and its inline policies."""
    iam = boto3.client("iam", region_name=region)

    # Delete inline policies first
    inline_names = iam.list_role_policies(RoleName=role_name)["PolicyNames"]
    for name in inline_names:
        iam.delete_role_policy(RoleName=role_name, PolicyName=name)

    # Detach managed policies
    attached = iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]
    for policy in attached:
        iam.detach_role_policy(RoleName=role_name, PolicyArn=policy["PolicyArn"])

    iam.delete_role(RoleName=role_name)


def apply_permissions_to_role(role_name: str, new_actions: list[str], new_resources: list[str], region: str) -> dict:
    """Add permissions to an existing role's inline policy."""
    iam = boto3.client("iam", region_name=region)

    # Get current policy
    try:
        resp = iam.get_role_policy(RoleName=role_name, PolicyName="loom-managed-policy")
        doc = resp["PolicyDocument"]
        if isinstance(doc, str):
            doc = json.loads(doc)
    except iam.exceptions.NoSuchEntityException:
        doc = {"Version": "2012-10-17", "Statement": []}

    # Add new statement
    doc["Statement"].append({
        "Effect": "Allow",
        "Action": new_actions,
        "Resource": new_resources,
    })

    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="loom-managed-policy",
        PolicyDocument=json.dumps(doc),
    )

    return doc
