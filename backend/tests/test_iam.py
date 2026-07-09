"""Tests for IAM service functions."""
import json
import unittest
from unittest.mock import MagicMock, patch

from app.services.iam import (
    create_execution_role,
    build_trust_policy,
    build_base_policy,
    build_integration_policy_statements,
    update_role_policy,
    delete_execution_role,
    list_agentcore_roles,
    list_cognito_pools,
)


class TestCreateExecutionRole(unittest.TestCase):
    """Test cases for create_execution_role function."""

    @patch("boto3.client")
    def test_create_execution_role(self, mock_boto_client: MagicMock) -> None:
        """Test creating an IAM execution role."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_role.return_value = {
            "Role": {
                "Arn": "arn:aws:iam::123456789012:role/loom-agent-rt-123",
            }
        }

        tag_policies = [
            {"key": "deployed-by", "default_value": "loom"},
            {"key": "owner", "default_value": "heeki"},
        ]
        result = create_execution_role(
            agent_name="test-agent",
            runtime_id="rt-123",
            region="us-east-1",
            account_id="123456789012",
            tag_policies=tag_policies,
        )

        mock_client.create_role.assert_called_once()
        call_kwargs = mock_client.create_role.call_args[1]
        self.assertEqual(call_kwargs["RoleName"], "loom-agent-rt-123")
        self.assertIn("bedrock-agentcore.amazonaws.com", call_kwargs["AssumeRolePolicyDocument"])

        mock_client.put_role_policy.assert_called_once()
        policy_kwargs = mock_client.put_role_policy.call_args[1]
        self.assertEqual(policy_kwargs["RoleName"], "loom-agent-rt-123")
        self.assertEqual(policy_kwargs["PolicyName"], "loom-agent-base-policy")

        self.assertEqual(result, "arn:aws:iam::123456789012:role/loom-agent-rt-123")

        # Verify tags are included
        self.assertIn("Tags", call_kwargs)
        tag_keys = {t["Key"] for t in call_kwargs["Tags"]}
        self.assertIn("deployed-by", tag_keys)
        self.assertIn("owner", tag_keys)


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


class TestBuildTrustPolicy(unittest.TestCase):
    """Test cases for build_trust_policy function."""

    def test_build_trust_policy(self) -> None:
        """Test trust policy structure."""
        policy = build_trust_policy()

        self.assertEqual(policy["Version"], "2012-10-17")
        self.assertEqual(len(policy["Statement"]), 1)
        stmt = policy["Statement"][0]
        self.assertEqual(stmt["Effect"], "Allow")
        self.assertEqual(stmt["Principal"]["Service"], "bedrock-agentcore.amazonaws.com")
        self.assertEqual(stmt["Action"], "sts:AssumeRole")


class TestBuildBasePolicy(unittest.TestCase):
    """Test cases for build_base_policy function."""

    def test_build_base_policy(self) -> None:
        """Test base policy structure and resource scoping."""
        policy = build_base_policy("us-east-1", "123456789012", "my-agent")

        self.assertEqual(policy["Version"], "2012-10-17")
        self.assertEqual(len(policy["Statement"]), 2)
        # Workload identity statement
        stmt = policy["Statement"][0]
        self.assertEqual(stmt["Effect"], "Allow")
        self.assertIn("bedrock-agentcore:GetWorkloadAccessToken", stmt["Action"])
        self.assertIn("bedrock-agentcore:GetWorkloadAccessTokenForJWT", stmt["Action"])
        self.assertIn("bedrock-agentcore:GetWorkloadAccessTokenForUserId", stmt["Action"])
        # Verify resource scoping includes region, account, and agent name
        self.assertTrue(any("us-east-1" in r for r in stmt["Resource"]))
        self.assertTrue(any("123456789012" in r for r in stmt["Resource"]))
        self.assertTrue(any("my-agent" in r for r in stmt["Resource"]))
        # OAuth2 credential provider statement
        oauth2_stmt = policy["Statement"][1]
        self.assertEqual(oauth2_stmt["Effect"], "Allow")
        self.assertIn("bedrock-agentcore:GetResourceOauth2Token", oauth2_stmt["Action"])
        self.assertTrue(any("token-vault" in r for r in oauth2_stmt["Resource"]))


class TestBuildIntegrationPolicyStatements(unittest.TestCase):
    """Test cases for build_integration_policy_statements function."""

    def test_s3_integration(self) -> None:
        """Test S3 integration policy statement."""
        integrations = [
            {
                "integration_type": "s3",
                "integration_config": json.dumps({"bucket": "my-bucket", "prefix": "data/*"}),
            }
        ]
        statements = build_integration_policy_statements(integrations)

        self.assertEqual(len(statements), 1)
        self.assertIn("s3:GetObject", statements[0]["Action"])
        self.assertIn("s3:PutObject", statements[0]["Action"])
        self.assertTrue(any("my-bucket" in r for r in statements[0]["Resource"]))

    def test_bedrock_integration(self) -> None:
        """Test Bedrock integration policy statement."""
        integrations = [
            {
                "integration_type": "bedrock",
                "integration_config": json.dumps({"region": "us-east-1", "model_id": "anthropic.claude-v2"}),
            }
        ]
        statements = build_integration_policy_statements(integrations)

        self.assertEqual(len(statements), 1)
        self.assertIn("bedrock:InvokeModel", statements[0]["Action"])
        self.assertIn("anthropic.claude-v2", statements[0]["Resource"])

    def test_lambda_integration(self) -> None:
        """Test Lambda integration policy statement."""
        integrations = [
            {
                "integration_type": "lambda",
                "integration_config": json.dumps({"function_arn": "arn:aws:lambda:us-east-1:123:function:my-fn"}),
            }
        ]
        statements = build_integration_policy_statements(integrations)

        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0]["Action"], "lambda:InvokeFunction")
        self.assertEqual(statements[0]["Resource"], "arn:aws:lambda:us-east-1:123:function:my-fn")

    def test_dynamodb_integration(self) -> None:
        """Test DynamoDB integration policy statement."""
        integrations = [
            {
                "integration_type": "dynamodb",
                "integration_config": json.dumps({"table_arn": "arn:aws:dynamodb:us-east-1:123:table/my-table"}),
            }
        ]
        statements = build_integration_policy_statements(integrations)

        self.assertEqual(len(statements), 1)
        self.assertIn("dynamodb:GetItem", statements[0]["Action"])
        self.assertIn("dynamodb:PutItem", statements[0]["Action"])
        self.assertTrue(any("my-table" in r for r in statements[0]["Resource"]))

    def test_sqs_integration(self) -> None:
        """Test SQS integration policy statement."""
        integrations = [
            {
                "integration_type": "sqs",
                "integration_config": json.dumps({"queue_arn": "arn:aws:sqs:us-east-1:123:my-queue"}),
            }
        ]
        statements = build_integration_policy_statements(integrations)

        self.assertEqual(len(statements), 1)
        self.assertIn("sqs:SendMessage", statements[0]["Action"])
        self.assertEqual(statements[0]["Resource"], "arn:aws:sqs:us-east-1:123:my-queue")

    def test_sns_integration(self) -> None:
        """Test SNS integration policy statement."""
        integrations = [
            {
                "integration_type": "sns",
                "integration_config": json.dumps({"topic_arn": "arn:aws:sns:us-east-1:123:my-topic"}),
            }
        ]
        statements = build_integration_policy_statements(integrations)

        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0]["Action"], "sns:Publish")
        self.assertEqual(statements[0]["Resource"], "arn:aws:sns:us-east-1:123:my-topic")

    def test_multiple_integrations(self) -> None:
        """Test multiple integration types generate multiple statements."""
        integrations = [
            {"integration_type": "s3", "integration_config": json.dumps({"bucket": "b1"})},
            {"integration_type": "bedrock", "integration_config": json.dumps({"region": "us-east-1", "model_id": "m1"})},
        ]
        statements = build_integration_policy_statements(integrations)
        self.assertEqual(len(statements), 2)

    def test_unknown_integration_type_ignored(self) -> None:
        """Test that unknown integration types produce no statements."""
        integrations = [
            {"integration_type": "unknown", "integration_config": "{}"},
        ]
        statements = build_integration_policy_statements(integrations)
        self.assertEqual(len(statements), 0)

    def test_invalid_json_config_skipped(self) -> None:
        """Test that invalid JSON in integration_config is skipped."""
        integrations = [
            {"integration_type": "s3", "integration_config": "not-json"},
        ]
        statements = build_integration_policy_statements(integrations)
        self.assertEqual(len(statements), 0)

    def test_dict_config_accepted(self) -> None:
        """Test that dict config (already parsed) is accepted."""
        integrations = [
            {"integration_type": "s3", "integration_config": {"bucket": "b1", "prefix": "p1"}},
        ]
        statements = build_integration_policy_statements(integrations)
        self.assertEqual(len(statements), 1)


class TestUpdateRolePolicy(unittest.TestCase):
    """Test cases for update_role_policy function."""

    @patch("boto3.client")
    def test_update_role_policy(self, mock_boto_client: MagicMock) -> None:
        """Test updating an IAM role policy with integrations."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        integrations = [
            {"integration_type": "s3", "integration_config": json.dumps({"bucket": "my-bucket"})},
        ]
        update_role_policy(
            role_name="loom-agent-rt-123",
            integrations=integrations,
            region="us-east-1",
            account_id="123456789012",
            agent_name="test-agent",
        )

        mock_client.put_role_policy.assert_called_once()
        call_kwargs = mock_client.put_role_policy.call_args[1]
        self.assertEqual(call_kwargs["RoleName"], "loom-agent-rt-123")
        policy = json.loads(call_kwargs["PolicyDocument"])
        # Base policy statements (workload identity + OAuth2 credential provider) + S3 integration
        self.assertEqual(len(policy["Statement"]), 3)


class TestDeleteExecutionRole(unittest.TestCase):
    """Test cases for delete_execution_role function."""

    @patch("boto3.client")
    def test_delete_execution_role(self, mock_boto_client: MagicMock) -> None:
        """Test deleting an IAM role and its inline policies."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.list_role_policies.return_value = {
            "PolicyNames": ["loom-agent-base-policy", "extra-policy"],
        }

        delete_execution_role("loom-agent-rt-123")

        # Should delete each inline policy
        self.assertEqual(mock_client.delete_role_policy.call_count, 2)
        mock_client.delete_role_policy.assert_any_call(
            RoleName="loom-agent-rt-123", PolicyName="loom-agent-base-policy"
        )
        mock_client.delete_role_policy.assert_any_call(
            RoleName="loom-agent-rt-123", PolicyName="extra-policy"
        )
        # Then delete the role itself
        mock_client.delete_role.assert_called_once_with(RoleName="loom-agent-rt-123")


if __name__ == "__main__":
    unittest.main()
