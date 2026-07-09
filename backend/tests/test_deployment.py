"""Tests for deployment service functions."""
import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.deployment import (
    build_agent_artifact,
    create_runtime,
    create_runtime_endpoint,
    get_runtime,
    get_runtime_endpoint,
    delete_runtime,
    delete_runtime_endpoint,
    update_runtime,
    validate_config_values,
    store_secret,
    update_secret,
    delete_secret,
    store_large_config,
)


class TestBuildAgentArtifact(unittest.TestCase):
    """Test cases for build_agent_artifact function."""

    @patch.dict(os.environ, {}, clear=True)
    def test_build_agent_artifact_missing_bucket_env(self) -> None:
        """Test that missing LOOM_ARTIFACT_BUCKET raises ValueError."""
        os.environ.pop("LOOM_ARTIFACT_BUCKET", None)
        with self.assertRaises(ValueError):
            build_agent_artifact("us-east-1")

    @patch("app.services.deployment.shutil")
    @patch("app.services.deployment.subprocess")
    @patch.dict(os.environ, {"LOOM_ARTIFACT_BUCKET": "my-bucket"})
    def test_build_agent_artifact_missing_source_dir(self, mock_subprocess, mock_shutil) -> None:
        """Test that missing agent source directory raises FileNotFoundError."""
        with patch("app.services.deployment.AGENT_SOURCE_DIR") as mock_dir:
            mock_src = MagicMock()
            mock_src.is_dir.return_value = False
            mock_dir.__truediv__ = MagicMock(return_value=mock_src)
            with self.assertRaises(FileNotFoundError):
                build_agent_artifact("us-east-1")


class TestCreateRuntime(unittest.TestCase):
    """Test cases for create_runtime function."""

    @patch("boto3.client")
    def test_create_runtime(self, mock_boto_client: MagicMock) -> None:
        """Test creating a new agent runtime."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_agent_runtime.return_value = {
            "agentRuntimeArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/rt-123",
            "agentRuntimeId": "rt-123",
            "status": "CREATING",
        }

        result = create_runtime(
            name="test-agent",
            description="A test agent",
            role_arn="arn:aws:iam::123456789012:role/test-role",
            env_vars={"KEY": "value"},
            artifact_bucket="my-bucket",
            artifact_prefix="artifacts/agent.zip",
            region="us-east-1",
        )

        mock_boto_client.assert_called_once_with("bedrock-agentcore-control", region_name="us-east-1")
        call_kwargs = mock_client.create_agent_runtime.call_args[1]
        self.assertEqual(call_kwargs["agentRuntimeName"], "test-agent")
        self.assertEqual(call_kwargs["description"], "A test agent")
        self.assertEqual(call_kwargs["roleArn"], "arn:aws:iam::123456789012:role/test-role")
        self.assertEqual(call_kwargs["environmentVariables"], {"KEY": "value"})
        self.assertEqual(call_kwargs["networkConfiguration"], {"networkMode": "PUBLIC"})
        self.assertEqual(call_kwargs["protocolConfiguration"], {"serverProtocol": "HTTP"})
        self.assertIn("tags", call_kwargs)
        self.assertEqual(result["agentRuntimeId"], "rt-123")

    @patch("boto3.client")
    def test_create_runtime_entry_point_uses_otel_instrument(self, mock_boto_client: MagicMock) -> None:
        """Test that the entry point wraps handler with opentelemetry-instrument."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_agent_runtime.return_value = {"agentRuntimeId": "rt-789"}

        create_runtime(
            name="otel-agent",
            description="",
            role_arn="arn:aws:iam::123:role/r",
            env_vars={},
            artifact_bucket="b",
            artifact_prefix="p",
            region="us-east-1",
        )

        call_kwargs = mock_client.create_agent_runtime.call_args[1]
        entry_point = call_kwargs["agentRuntimeArtifact"]["codeConfiguration"]["entryPoint"]
        self.assertEqual(entry_point, ["opentelemetry-instrument", "src/handler.py"])

    @patch("boto3.client")
    def test_create_runtime_with_lifecycle_and_authorizer(self, mock_boto_client: MagicMock) -> None:
        """Test create_runtime with optional lifecycle and authorizer configs."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_agent_runtime.return_value = {"agentRuntimeId": "rt-456"}

        lifecycle = {"idleRuntimeSessionTimeout": 300}
        authorizer = {"customJWTAuthorizer": {"discoveryUrl": "https://example.com"}}

        create_runtime(
            name="agent-with-opts",
            description="",
            role_arn="arn:aws:iam::123:role/r",
            env_vars={},
            lifecycle_config=lifecycle,
            authorizer_config=authorizer,
            region="us-east-1",
        )

        call_kwargs = mock_client.create_agent_runtime.call_args[1]
        self.assertEqual(call_kwargs["lifecycleConfiguration"], lifecycle)
        self.assertEqual(call_kwargs["authorizerConfiguration"], authorizer)


class TestCreateRuntimeEndpoint(unittest.TestCase):
    """Test cases for create_runtime_endpoint function."""

    @patch("boto3.client")
    def test_create_runtime_endpoint(self, mock_boto_client: MagicMock) -> None:
        """Test creating a runtime endpoint."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_agent_runtime_endpoint.return_value = {
            "name": "test-ep",
            "agentRuntimeEndpointArn": "arn:endpoint",
            "status": "CREATING",
        }

        result = create_runtime_endpoint(
            runtime_id="rt-123",
            name="test-ep",
            description="Test endpoint",
            region="us-east-1",
        )

        mock_client.create_agent_runtime_endpoint.assert_called_once()
        call_kwargs = mock_client.create_agent_runtime_endpoint.call_args[1]
        self.assertEqual(call_kwargs["agentRuntimeId"], "rt-123")
        self.assertEqual(call_kwargs["name"], "test-ep")
        self.assertIn("tags", call_kwargs)
        self.assertEqual(result["name"], "test-ep")


class TestGetRuntime(unittest.TestCase):
    """Test cases for get_runtime function."""

    @patch("boto3.client")
    def test_get_runtime(self, mock_boto_client: MagicMock) -> None:
        """Test getting runtime details."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.get_agent_runtime.return_value = {"status": "READY", "agentRuntimeId": "rt-123"}

        result = get_runtime("rt-123", "us-east-1")

        mock_client.get_agent_runtime.assert_called_once_with(agentRuntimeId="rt-123")
        self.assertEqual(result["status"], "READY")


class TestGetRuntimeEndpoint(unittest.TestCase):
    """Test cases for get_runtime_endpoint function."""

    @patch("boto3.client")
    def test_get_runtime_endpoint(self, mock_boto_client: MagicMock) -> None:
        """Test getting runtime endpoint details."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.get_agent_runtime_endpoint.return_value = {
            "status": "READY",
            "name": "my-ep",
        }

        result = get_runtime_endpoint("rt-123", "my-ep", "us-east-1")

        mock_client.get_agent_runtime_endpoint.assert_called_once_with(
            agentRuntimeId="rt-123", endpointName="my-ep"
        )
        self.assertEqual(result["status"], "READY")


class TestDeleteRuntime(unittest.TestCase):
    """Test cases for delete_runtime function."""

    @patch("boto3.client")
    def test_delete_runtime(self, mock_boto_client: MagicMock) -> None:
        """Test deleting an agent runtime."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        delete_runtime("rt-123", "us-east-1")

        mock_boto_client.assert_called_once_with("bedrock-agentcore-control", region_name="us-east-1")
        mock_client.delete_agent_runtime.assert_called_once_with(agentRuntimeId="rt-123")


class TestDeleteRuntimeEndpoint(unittest.TestCase):
    """Test cases for delete_runtime_endpoint function."""

    @patch("boto3.client")
    def test_delete_runtime_endpoint(self, mock_boto_client: MagicMock) -> None:
        """Test deleting a runtime endpoint."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        delete_runtime_endpoint("rt-123", "my-ep", "us-east-1")

        mock_client.delete_agent_runtime_endpoint.assert_called_once_with(
            agentRuntimeId="rt-123", endpointName="my-ep"
        )


class TestCreateRuntimeVpc(unittest.TestCase):
    """Test VPC configuration in create_runtime."""

    @patch("boto3.client")
    def test_create_runtime_public_mode_no_vpc_fields(self, mock_boto_client: MagicMock) -> None:
        """PUBLIC mode should not include vpcSubnetIds or vpcSecurityGroupIds."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_agent_runtime.return_value = {"agentRuntimeId": "rt-pub"}

        create_runtime(
            name="pub-agent",
            description="",
            role_arn="arn:aws:iam::123:role/r",
            env_vars={},
            network_mode="PUBLIC",
            artifact_bucket="b",
            artifact_prefix="p",
            region="us-east-1",
        )

        call_kwargs = mock_client.create_agent_runtime.call_args[1]
        net = call_kwargs["networkConfiguration"]
        self.assertEqual(net["networkMode"], "PUBLIC")
        self.assertNotIn("vpcSubnetIds", net)
        self.assertNotIn("vpcSecurityGroupIds", net)

    @patch("boto3.client")
    def test_create_runtime_vpc_mode_passes_subnet_and_sg(self, mock_boto_client: MagicMock) -> None:
        """VPC mode should include vpcSubnetIds and vpcSecurityGroupIds in networkConfiguration."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_agent_runtime.return_value = {"agentRuntimeId": "rt-vpc"}

        create_runtime(
            name="vpc-agent",
            description="",
            role_arn="arn:aws:iam::123:role/r",
            env_vars={},
            network_mode="VPC",
            vpc_subnet_ids=["subnet-aaa", "subnet-bbb"],
            vpc_security_group_ids=["sg-ccc"],
            artifact_bucket="b",
            artifact_prefix="p",
            region="us-east-1",
        )

        call_kwargs = mock_client.create_agent_runtime.call_args[1]
        net = call_kwargs["networkConfiguration"]
        self.assertEqual(net["networkMode"], "VPC")
        self.assertEqual(net["vpcSubnetIds"], ["subnet-aaa", "subnet-bbb"])
        self.assertEqual(net["vpcSecurityGroupIds"], ["sg-ccc"])

    @patch("boto3.client")
    def test_create_runtime_vpc_mode_no_subnets(self, mock_boto_client: MagicMock) -> None:
        """VPC mode without subnet/SG args should set networkMode without subnet fields."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_agent_runtime.return_value = {"agentRuntimeId": "rt-vpc2"}

        create_runtime(
            name="vpc-agent2",
            description="",
            role_arn="arn:aws:iam::123:role/r",
            env_vars={},
            network_mode="VPC",
            artifact_bucket="b",
            artifact_prefix="p",
            region="us-east-1",
        )

        call_kwargs = mock_client.create_agent_runtime.call_args[1]
        net = call_kwargs["networkConfiguration"]
        self.assertEqual(net["networkMode"], "VPC")
        self.assertNotIn("vpcSubnetIds", net)
        self.assertNotIn("vpcSecurityGroupIds", net)


class TestUpdateRuntimeVpc(unittest.TestCase):
    """Test VPC configuration in update_runtime."""

    @patch("boto3.client")
    def test_update_runtime_vpc_mode_passes_subnet_and_sg(self, mock_boto_client: MagicMock) -> None:
        """Updating to VPC mode should include subnet and SG IDs."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.update_agent_runtime.return_value = {"status": "UPDATING"}

        update_runtime(
            runtime_id="rt-123",
            network_mode="VPC",
            vpc_subnet_ids=["subnet-111", "subnet-222"],
            vpc_security_group_ids=["sg-333"],
            region="us-east-1",
        )

        call_kwargs = mock_client.update_agent_runtime.call_args[1]
        net = call_kwargs["networkConfiguration"]
        self.assertEqual(net["networkMode"], "VPC")
        self.assertEqual(net["vpcSubnetIds"], ["subnet-111", "subnet-222"])
        self.assertEqual(net["vpcSecurityGroupIds"], ["sg-333"])

    @patch("boto3.client")
    def test_update_runtime_public_mode_no_vpc_fields(self, mock_boto_client: MagicMock) -> None:
        """Updating to PUBLIC mode should not include VPC fields."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.update_agent_runtime.return_value = {"status": "UPDATING"}

        update_runtime(
            runtime_id="rt-123",
            network_mode="PUBLIC",
            region="us-east-1",
        )

        call_kwargs = mock_client.update_agent_runtime.call_args[1]
        net = call_kwargs["networkConfiguration"]
        self.assertEqual(net["networkMode"], "PUBLIC")
        self.assertNotIn("vpcSubnetIds", net)
        self.assertNotIn("vpcSecurityGroupIds", net)

    @patch("boto3.client")
    def test_update_runtime_no_network_mode_omits_network_config(self, mock_boto_client: MagicMock) -> None:
        """Omitting network_mode should not include networkConfiguration at all."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.update_agent_runtime.return_value = {"status": "UPDATING"}

        update_runtime(runtime_id="rt-123", region="us-east-1")

        call_kwargs = mock_client.update_agent_runtime.call_args[1]
        self.assertNotIn("networkConfiguration", call_kwargs)


class TestAgentModelVpc(unittest.TestCase):
    """Test VPC helpers on the Agent model."""

    def test_get_vpc_subnet_ids_empty(self) -> None:
        from app.models.agent import Agent
        agent = Agent(arn="a", runtime_id="r", region="us-east-1", account_id="123")
        self.assertEqual(agent.get_vpc_subnet_ids(), [])

    def test_set_get_vpc_subnet_ids(self) -> None:
        from app.models.agent import Agent
        agent = Agent(arn="a", runtime_id="r", region="us-east-1", account_id="123")
        agent.set_vpc_subnet_ids(["subnet-aaa", "subnet-bbb"])
        self.assertEqual(agent.get_vpc_subnet_ids(), ["subnet-aaa", "subnet-bbb"])

    def test_set_vpc_subnet_ids_none_clears(self) -> None:
        from app.models.agent import Agent
        agent = Agent(arn="a", runtime_id="r", region="us-east-1", account_id="123")
        agent.set_vpc_subnet_ids(["subnet-aaa"])
        agent.set_vpc_subnet_ids(None)
        self.assertIsNone(agent.vpc_subnet_ids)
        self.assertEqual(agent.get_vpc_subnet_ids(), [])

    def test_get_vpc_security_group_ids_empty(self) -> None:
        from app.models.agent import Agent
        agent = Agent(arn="a", runtime_id="r", region="us-east-1", account_id="123")
        self.assertEqual(agent.get_vpc_security_group_ids(), [])

    def test_set_get_vpc_security_group_ids(self) -> None:
        from app.models.agent import Agent
        agent = Agent(arn="a", runtime_id="r", region="us-east-1", account_id="123")
        agent.set_vpc_security_group_ids(["sg-abc"])
        self.assertEqual(agent.get_vpc_security_group_ids(), ["sg-abc"])

    def test_to_dict_includes_vpc_config_id(self) -> None:
        from app.models.agent import Agent
        agent = Agent(arn="a", runtime_id="r", region="us-east-1", account_id="123",
                      name="test", status="READY", registered_at=None)
        agent.vpc_config_id = 42
        d = agent.to_dict()
        self.assertEqual(d["vpc_config_id"], 42)


class TestUpdateRuntime(unittest.TestCase):
    """Test cases for update_runtime function."""

    @patch("boto3.client")
    def test_update_runtime_with_env_vars(self, mock_boto_client: MagicMock) -> None:
        """Test updating runtime with new env vars."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.update_agent_runtime.return_value = {"status": "UPDATING"}

        result = update_runtime(
            runtime_id="rt-123",
            env_vars={"KEY": "new_value"},
            region="us-east-1",
        )

        call_kwargs = mock_client.update_agent_runtime.call_args[1]
        self.assertEqual(call_kwargs["agentRuntimeId"], "rt-123")
        self.assertEqual(call_kwargs["environmentVariables"], {"KEY": "new_value"})
        self.assertEqual(result["status"], "UPDATING")

    @patch("boto3.client")
    def test_update_runtime_no_env_vars(self, mock_boto_client: MagicMock) -> None:
        """Test updating runtime without env vars."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.update_agent_runtime.return_value = {"status": "UPDATING"}

        update_runtime(runtime_id="rt-123", region="us-east-1")

        call_kwargs = mock_client.update_agent_runtime.call_args[1]
        self.assertEqual(call_kwargs["agentRuntimeId"], "rt-123")
        self.assertNotIn("environmentVariables", call_kwargs)

    @patch("boto3.client")
    def test_update_runtime_with_role_arn(self, mock_boto_client: MagicMock) -> None:
        """Test updating runtime with a new role ARN."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.update_agent_runtime.return_value = {"status": "UPDATING"}

        update_runtime(
            runtime_id="rt-123",
            role_arn="arn:aws:iam::123:role/new-role",
            region="us-east-1",
        )

        call_kwargs = mock_client.update_agent_runtime.call_args[1]
        self.assertEqual(call_kwargs["roleArn"], "arn:aws:iam::123:role/new-role")


class TestValidateConfigValues(unittest.TestCase):
    """Test cases for validate_config_values function."""

    def test_validate_config_values_clean(self) -> None:
        """Test that normal config values produce no warnings."""
        config = {
            "APP_NAME": "my-agent",
            "LOG_LEVEL": "DEBUG",
            "REGION": "us-east-1",
        }
        warnings = validate_config_values(config)
        self.assertEqual(warnings, [])

    def test_validate_config_values_secret_patterns(self) -> None:
        """Test detection of secret-like patterns in values."""
        config = {
            "OPENAI_KEY": "sk-abcdefghijklmnopqrstuvwx",
            "AWS_KEY": "AKIAIOSFODNN7EXAMPLE",
        }
        warnings = validate_config_values(config)
        self.assertTrue(len(warnings) >= 2)
        self.assertTrue(any("sk-" in w or "secret pattern" in w for w in warnings))
        self.assertTrue(any("AKIA" in w or "secret pattern" in w for w in warnings))

    def test_validate_config_values_secret_keyword_in_key(self) -> None:
        """Test detection of secret keywords in key names."""
        config = {
            "db_password": "some-value",
            "api_key": "some-value",
        }
        warnings = validate_config_values(config)
        self.assertTrue(len(warnings) >= 2)
        self.assertTrue(any("password" in w.lower() for w in warnings))

    def test_validate_config_values_github_token(self) -> None:
        """Test detection of GitHub personal access token pattern."""
        config = {
            "GH_TOKEN": "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        }
        warnings = validate_config_values(config)
        self.assertTrue(len(warnings) >= 1)


class TestStoreSecret(unittest.TestCase):
    """Test cases for store_secret function."""

    @patch("boto3.client")
    def test_store_secret(self, mock_boto_client: MagicMock) -> None:
        """Test storing a secret in Secrets Manager."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.create_secret.return_value = {
            "ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-secret-abc123",
        }

        result = store_secret("my-secret", "secret-value", "us-east-1")

        mock_boto_client.assert_called_once_with("secretsmanager", region_name="us-east-1")
        mock_client.create_secret.assert_called_once_with(
            Name="my-secret",
            SecretString="secret-value",
        )
        self.assertEqual(result, "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-secret-abc123")


class TestUpdateSecret(unittest.TestCase):
    """Test cases for update_secret function."""

    @patch("boto3.client")
    def test_update_secret(self, mock_boto_client: MagicMock) -> None:
        """Test updating an existing secret."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        secret_arn = "arn:aws:secretsmanager:us-east-1:000000000000:secret:test-secret"  # nosec B105
        update_secret(secret_arn, "new-value", "us-east-1")

        mock_client.put_secret_value.assert_called_once_with(
            SecretId=secret_arn,
            SecretString="new-value",
        )


class TestDeleteSecret(unittest.TestCase):
    """Test cases for delete_secret function."""

    @patch("boto3.client")
    def test_delete_secret(self, mock_boto_client: MagicMock) -> None:
        """Test deleting a secret from Secrets Manager."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        secret_arn = "arn:aws:secretsmanager:us-east-1:000000000000:secret:test-secret"  # nosec B105
        delete_secret(secret_arn, "us-east-1")

        mock_client.delete_secret.assert_called_once_with(
            SecretId=secret_arn,
            ForceDeleteWithoutRecovery=True,
        )


class TestStoreLargeConfig(unittest.TestCase):
    """Test cases for store_large_config function."""

    @patch("boto3.client")
    def test_store_large_config(self, mock_boto_client: MagicMock) -> None:
        """Test storing large config in S3."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        result = store_large_config(
            agent_name="my-agent",
            key="large-config",
            value="a" * 10000,
            bucket="my-bucket",
            region="us-east-1",
        )

        mock_boto_client.assert_called_once_with("s3", region_name="us-east-1")
        mock_client.put_object.assert_called_once_with(
            Bucket="my-bucket",
            Key="my-agent/config/large-config",
            Body=("a" * 10000).encode("utf-8"),
            ContentType="text/plain",
        )
        self.assertEqual(result, "s3://my-bucket/my-agent/config/large-config")


class TestFixConsoleScriptShebangs(unittest.TestCase):
    """Test cases for _fix_console_script_shebangs function."""

    def test_fixes_opentelemetry_instrument_shebang(self) -> None:
        """Test that macOS shebangs are replaced with portable shebangs."""
        import tempfile
        import shutil
        from app.services.deployment import _fix_console_script_shebangs

        tmp = tempfile.mkdtemp()
        try:
            bin_dir = os.path.join(tmp, "bin")
            os.makedirs(bin_dir)
            script_path = os.path.join(bin_dir, "opentelemetry-instrument")
            with open(script_path, "w") as f:
                f.write("#!/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12\n"
                        "import sys\n"
                        "from opentelemetry.instrumentation.auto_instrumentation import run\n"
                        "if __name__ == '__main__':\n"
                        "    sys.exit(run())\n")

            _fix_console_script_shebangs(tmp)

            with open(script_path) as f:
                content = f.read()
            self.assertTrue(content.startswith("#!/usr/bin/env python3\n"))
            self.assertIn("from opentelemetry.instrumentation.auto_instrumentation import run", content)
            self.assertEqual(os.stat(script_path).st_mode & 0o777, 0o755)
        finally:
            shutil.rmtree(tmp)

    def test_no_bin_dir_is_noop(self) -> None:
        """Test that missing bin/ directory doesn't raise."""
        import tempfile
        import shutil
        from app.services.deployment import _fix_console_script_shebangs

        tmp = tempfile.mkdtemp()
        try:
            _fix_console_script_shebangs(tmp)  # should not raise
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
