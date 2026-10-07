"""Tests for IAM service functions."""
import json
import unittest
from unittest.mock import MagicMock, patch

from app.services.iam import (
    list_agentcore_roles,
    list_cognito_pools,
)


class TestListAgentcoreRoles(unittest.TestCase):
    """Test cases for list_agentcore_roles function."""

    def test_list_agentcore_roles(self) -> None:
        """Test listing IAM roles that trust bedrock-agentcore."""
        with patch("boto3.client") as mock_boto_client:
            mock_client = MagicMock()
            mock_boto_client.return_value = mock_client
            mock_client.list_roles.return_value = {
                "Roles": [
                    {
                        "RoleName": "loom-agent-rt-123",
                        "Arn": "arn:aws:iam::123:role/loom-agent-rt-123",
                        "Description": "Loom agent role",
                        "AssumeRolePolicyDocument": {
                            "Statement": [{
                                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                                "Effect": "Allow",
                                "Action": "sts:AssumeRole",
                            }]
                        },
                    },
                    {
                        "RoleName": "other-role",
                        "Arn": "arn:aws:iam::123:role/other-role",
                        "AssumeRolePolicyDocument": {
                            "Statement": [{
                                "Principal": {"Service": "lambda.amazonaws.com"},
                                "Effect": "Allow",
                                "Action": "sts:AssumeRole",
                            }]
                        },
                    },
                ],
                "IsTruncated": False,
            }

            roles = list_agentcore_roles("us-east-1")

            self.assertEqual(len(roles), 1)
            self.assertEqual(roles[0]["role_name"], "loom-agent-rt-123")
            self.assertEqual(roles[0]["description"], "Loom agent role")

    def test_list_agentcore_roles_pagination(self) -> None:
        """Test pagination handling."""
        with patch("boto3.client") as mock_boto_client:
            mock_client = MagicMock()
            mock_boto_client.return_value = mock_client
            mock_client.list_roles.side_effect = [
                {
                    "Roles": [{
                        "RoleName": "r1",
                        "Arn": "arn:aws:iam::123:role/r1",
                        "AssumeRolePolicyDocument": {
                            "Statement": [{"Principal": {"Service": "bedrock-agentcore.amazonaws.com"}}]
                        },
                    }],
                    "IsTruncated": True,
                    "Marker": "abc",
                },
                {
                    "Roles": [{
                        "RoleName": "r2",
                        "Arn": "arn:aws:iam::123:role/r2",
                        "AssumeRolePolicyDocument": {
                            "Statement": [{"Principal": {"Service": "bedrock-agentcore.amazonaws.com"}}]
                        },
                    }],
                    "IsTruncated": False,
                },
            ]

            roles = list_agentcore_roles("us-east-1")
            self.assertEqual(len(roles), 2)


class TestListCognitoPools(unittest.TestCase):
    """Test cases for list_cognito_pools function."""

    def test_list_cognito_pools(self) -> None:
        """Test listing Cognito user pools."""
        with patch("boto3.client") as mock_boto_client:
            mock_client = MagicMock()
            mock_boto_client.return_value = mock_client
            mock_client.list_user_pools.return_value = {
                "UserPools": [
                    {"Id": "us-east-1_abc", "Name": "my-pool"},
                    {"Id": "us-east-1_def", "Name": "other-pool"},
                ],
            }

            pools = list_cognito_pools("us-east-1")

            mock_boto_client.assert_called_once_with("cognito-idp", region_name="us-east-1")
            self.assertEqual(len(pools), 2)
            self.assertEqual(pools[0]["pool_id"], "us-east-1_abc")
            self.assertEqual(pools[0]["pool_name"], "my-pool")

    def test_list_cognito_pools_empty(self) -> None:
        """Test listing when no pools exist."""
        with patch("boto3.client") as mock_boto_client:
            mock_client = MagicMock()
            mock_boto_client.return_value = mock_client
            mock_client.list_user_pools.return_value = {"UserPools": []}

            pools = list_cognito_pools("us-east-1")
            self.assertEqual(len(pools), 0)


if __name__ == "__main__":
    unittest.main()
