"""Tests for AgentCore Harness deployment and management."""
import json
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent
from app.models.config_entry import ConfigEntry
from app.models.mcp import McpServer


class TestHarnessDeployment(unittest.TestCase):
    """Test harness deployment via /api/agents endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        self.session = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db

        import app.routers.agents as _agents_mod
        self._original_session_local = _agents_mod.SessionLocal
        _agents_mod.SessionLocal = self.TestingSessionLocal

        self.client = TestClient(app)

    def tearDown(self):
        import app.routers.agents as _agents_mod
        _agents_mod.SessionLocal = self._original_session_local

        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @patch("app.routers.agents.create_harness_api")
    def test_deploy_harness_creates_agent(self, mock_create):
        mock_create.return_value = {
            "harnessId": "h-abc123",
            "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-abc123",
            "status": "CREATING",
            "environment": {
                "agentCoreRuntimeEnvironment": {
                    "agentRuntimeArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/rt-auto",
                    "agentRuntimeId": "rt-auto",
                }
            },
        }

        response = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "my_harness_agent",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["source"], "harness")
        self.assertEqual(data["name"], "my_harness_agent")
        self.assertEqual(data["deployment_status"], "initializing")

        agent = self.session.query(Agent).filter(Agent.name == "my_harness_agent").first()
        self.assertIsNotNone(agent)
        self.assertEqual(agent.harness_id, "h-abc123")
        self.assertEqual(agent.deployment_status, "deployed")
        self.assertEqual(agent.runtime_id, "rt-auto")

    @patch("app.routers.agents.create_harness_api")
    def test_deploy_harness_failure_sets_failed_status(self, mock_create):
        mock_create.side_effect = Exception("AWS error")

        response = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "fail_harness",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
            },
        )

        self.assertEqual(response.status_code, 201)

        agent = self.session.query(Agent).filter(Agent.name == "fail_harness").first()
        self.assertIsNotNone(agent)
        self.assertEqual(agent.deployment_status, "failed")
        self.assertEqual(agent.status, "FAILED")

    def test_deploy_harness_missing_name(self):
        response = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["detail"].lower())

    def test_deploy_harness_missing_model_id(self):
        response = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "test_agent",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("model_id", response.json()["detail"].lower())

    def test_deploy_harness_missing_role_arn(self):
        response = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "test_agent",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("role_arn", response.json()["detail"].lower())

    def test_deploy_harness_invalid_name(self):
        response = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "my-harness",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid agent name", response.json()["detail"])

    @patch("app.routers.agents.create_harness_api")
    def test_deploy_harness_with_mcp_servers(self, mock_create):
        server = McpServer(
            name="test_mcp",
            endpoint_url="http://localhost:3000/mcp",
            transport_type="streamable_http",
            auth_type="none",
        )
        self.session.add(server)
        self.session.commit()
        self.session.refresh(server)

        mock_create.return_value = {
            "harnessId": "h-mcp123",
            "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-mcp123",
            "status": "CREATING",
            "environment": {"agentCoreRuntimeEnvironment": {}},
        }

        response = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "mcp_harness_agent",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
                "mcp_servers": [server.id],
            },
        )

        self.assertEqual(response.status_code, 201)

        call_kwargs = mock_create.call_args[1]
        tools = call_kwargs["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["type"], "remote_mcp")
        self.assertEqual(tools[0]["name"], "test_mcp")
        self.assertEqual(tools[0]["config"]["remoteMcp"]["url"], "http://localhost:3000/mcp")

    @patch("app.routers.agents.create_harness_api")
    def test_deploy_harness_with_model_params(self, mock_create):
        mock_create.return_value = {
            "harnessId": "h-params",
            "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-params",
            "status": "CREATING",
            "environment": {"agentCoreRuntimeEnvironment": {}},
        }

        response = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "params_harness_agent",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
                "harness_max_iterations": 15,
                "harness_max_tokens": 4096,
            },
        )

        self.assertEqual(response.status_code, 201)

        call_kwargs = mock_create.call_args[1]
        self.assertEqual(call_kwargs["max_iterations"], 15)
        self.assertEqual(call_kwargs["max_tokens"], 4096)

    @patch("app.routers.agents.delete_harness_api")
    @patch("app.routers.agents.create_harness_api")
    def test_delete_harness_agent(self, mock_create, mock_delete):
        mock_create.return_value = {
            "harnessId": "h-del",
            "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-del",
            "status": "CREATING",
            "environment": {"agentCoreRuntimeEnvironment": {}},
        }
        mock_delete.return_value = {}

        create_resp = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "delete_harness_agent",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
            },
        )
        agent_id = create_resp.json()["id"]

        response = self.client.delete(f"/api/agents/{agent_id}?cleanup_aws=true")
        self.assertEqual(response.status_code, 200)
        mock_delete.assert_called_once_with("h-del", "us-east-1")

    @patch("app.routers.agents.get_harness_api")
    @patch("app.routers.agents.create_harness_api")
    def test_status_polls_harness(self, mock_create, mock_get):
        mock_create.return_value = {
            "harnessId": "h-status",
            "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-status",
            "status": "CREATING",
            "environment": {"agentCoreRuntimeEnvironment": {}},
        }
        mock_get.return_value = {
            "status": "READY",
            "harnessId": "h-status",
            "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-status",
            "environment": {
                "agentCoreRuntimeEnvironment": {
                    "agentRuntimeId": "rt-harness-auto",
                }
            },
        }

        create_resp = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "status_harness_agent",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
            },
        )
        agent_id = create_resp.json()["id"]

        response = self.client.get(f"/api/agents/{agent_id}/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "READY")

    @patch("app.routers.agents.get_harness_api")
    @patch("app.routers.agents.create_harness_api")
    def test_refresh_harness_agent(self, mock_create, mock_get):
        mock_create.return_value = {
            "harnessId": "h-refresh",
            "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-refresh",
            "status": "CREATING",
            "environment": {"agentCoreRuntimeEnvironment": {}},
        }
        mock_get.return_value = {
            "status": "READY",
            "harnessId": "h-refresh",
            "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-refresh",
            "environment": {"agentCoreRuntimeEnvironment": {}},
        }

        create_resp = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "refresh_harness_agent",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
            },
        )
        agent_id = create_resp.json()["id"]

        response = self.client.post(f"/api/agents/{agent_id}/refresh")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "READY")

    def test_deploy_harness_with_invalid_mcp_ids(self):
        response = self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "bad_mcp_harness",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
                "mcp_servers": [9999],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("MCP server IDs not found", response.json()["detail"])

    @patch("app.routers.agents.create_harness_api")
    def test_deploy_harness_stores_config(self, mock_create):
        mock_create.return_value = {
            "harnessId": "h-cfg",
            "harnessArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-cfg",
            "status": "CREATING",
            "environment": {"agentCoreRuntimeEnvironment": {}},
        }

        self.client.post(
            "/api/agents",
            json={
                "source": "harness",
                "name": "config_harness_agent",
                "model_id": "us.anthropic.claude-sonnet-4-6-v1",
                "role_arn": "arn:aws:iam::123456789012:role/test-role",
            },
        )

        agent = self.session.query(Agent).filter(Agent.name == "config_harness_agent").first()
        config = self.session.query(ConfigEntry).filter(
            ConfigEntry.agent_id == agent.id,
            ConfigEntry.key == "AGENT_CONFIG_JSON",
        ).first()
        self.assertIsNotNone(config)

        config_data = json.loads(config.value)
        self.assertEqual(config_data["model_id"], "us.anthropic.claude-sonnet-4-6-v1")
        self.assertIn("harness_config", config_data)


class TestHarnessService(unittest.TestCase):
    """Test harness service module functions."""

    @patch("boto3.client")
    def test_create_harness_basic(self, mock_boto3_client):
        from app.services.harness import create_harness

        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.create_harness.return_value = {
            "harnessId": "h-test",
            "harnessArn": "arn:test",
            "status": "CREATING",
        }

        result = create_harness(
            name="test",
            execution_role_arn="arn:role",
            model_id="us.anthropic.claude-sonnet-4-6-v1",
            system_prompt="You are helpful.",
        )

        mock_client.create_harness.assert_called_once()
        call_kwargs = mock_client.create_harness.call_args[1]
        self.assertEqual(call_kwargs["harnessName"], "test")
        self.assertEqual(call_kwargs["executionRoleArn"], "arn:role")
        self.assertEqual(call_kwargs["model"]["bedrockModelConfig"]["modelId"], "us.anthropic.claude-sonnet-4-6-v1")
        self.assertEqual(call_kwargs["systemPrompt"], [{"text": "You are helpful."}])
        self.assertEqual(call_kwargs["allowedTools"], ["*"])
        self.assertEqual(result["harnessId"], "h-test")

    @patch("boto3.client")
    def test_create_harness_with_model_params(self, mock_boto3_client):
        from app.services.harness import create_harness

        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.create_harness.return_value = {"harnessId": "h-test2", "status": "CREATING"}

        create_harness(
            name="test2",
            execution_role_arn="arn:role",
            model_id="model",
            system_prompt="prompt",
            max_tokens=4096,
            max_iterations=10,
        )

        call_kwargs = mock_client.create_harness.call_args[1]
        self.assertEqual(call_kwargs["model"]["bedrockModelConfig"]["maxTokens"], 4096)
        self.assertEqual(call_kwargs["maxIterations"], 10)
        self.assertNotIn("temperature", call_kwargs["model"]["bedrockModelConfig"])
        self.assertNotIn("topP", call_kwargs["model"]["bedrockModelConfig"])

    @patch("boto3.client")
    def test_create_harness_with_tools(self, mock_boto3_client):
        from app.services.harness import create_harness

        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.create_harness.return_value = {"harnessId": "h-test3", "status": "CREATING"}

        tools = [{"type": "remote_mcp", "name": "mcp1", "config": {"remoteMcp": {"url": "http://test"}}}]
        create_harness(
            name="test3",
            execution_role_arn="arn:role",
            model_id="model",
            system_prompt="prompt",
            tools=tools,
        )

        call_kwargs = mock_client.create_harness.call_args[1]
        self.assertEqual(call_kwargs["tools"], tools)

    @patch("boto3.client")
    def test_invoke_harness_stream_text(self, mock_boto3_client):
        from app.services.harness import invoke_harness_stream

        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client

        mock_client.invoke_harness.return_value = {
            "stream": [
                {"messageStart": {"role": "assistant"}},
                {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}},
                {"contentBlockDelta": {"delta": {"text": "Hello"}}},
                {"contentBlockDelta": {"delta": {"text": " world"}}},
                {"contentBlockStop": {"contentBlockIndex": 0}},
                {"messageStop": {"stopReason": "end_turn"}},
                {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}}},
            ]
        }

        events = list(invoke_harness_stream(
            harness_arn="arn:harness",
            session_id="sess-1",
            prompt="Hi",
        ))

        text_events = [e for e in events if e["type"] == "text"]
        self.assertEqual(len(text_events), 2)
        self.assertEqual(text_events[0]["content"], "Hello")
        self.assertEqual(text_events[1]["content"], " world")

        meta_events = [e for e in events if e["type"] == "metadata"]
        self.assertEqual(len(meta_events), 1)
        self.assertEqual(meta_events[0]["content"]["input_tokens"], 10)
        self.assertEqual(meta_events[0]["content"]["output_tokens"], 5)

    @patch("boto3.client")
    def test_invoke_harness_stream_tool_use(self, mock_boto3_client):
        from app.services.harness import invoke_harness_stream

        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client

        mock_client.invoke_harness.return_value = {
            "stream": [
                {"messageStart": {"role": "assistant"}},
                {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"name": "search"}}}},
                {"contentBlockDelta": {"delta": {"text": "searching..."}}},
                {"contentBlockStop": {"contentBlockIndex": 0}},
                {"messageStop": {"stopReason": "tool_use"}},
            ]
        }

        events = list(invoke_harness_stream(
            harness_arn="arn:harness",
            session_id="sess-2",
            prompt="Search for something",
        ))

        structured_events = [e for e in events if e["type"] == "structured"]
        self.assertEqual(len(structured_events), 1)
        self.assertEqual(structured_events[0]["content"]["tool_use"]["name"], "search")

    @patch("boto3.client")
    def test_get_harness(self, mock_boto3_client):
        from app.services.harness import get_harness

        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.get_harness.return_value = {"harnessId": "h-1", "status": "READY"}

        result = get_harness("h-1")
        self.assertEqual(result["status"], "READY")
        mock_client.get_harness.assert_called_once_with(harnessId="h-1")

    @patch("boto3.client")
    def test_delete_harness(self, mock_boto3_client):
        from app.services.harness import delete_harness

        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.delete_harness.return_value = {}

        delete_harness("h-1")
        mock_client.delete_harness.assert_called_once_with(harnessId="h-1")


if __name__ == "__main__":
    unittest.main()
