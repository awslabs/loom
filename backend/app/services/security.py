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
