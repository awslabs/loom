"""Tests for registry management endpoints."""
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
from app.models.mcp import McpServer, McpTool
from app.models.a2a import A2aAgent


SAMPLE_REGISTRY_RECORD = {
    "recordId": "rec-123",
    "name": "test-server",
    "descriptorType": "MCP",
    "status": "DRAFT",
    "description": "Test MCP server",
    "createdAt": "2025-01-01T00:00:00Z",
    "updatedAt": "2025-01-01T00:00:00Z",
    "descriptors": {"mcp": {"server": "{}"}},
    "recordVersion": "1",
}

SAMPLE_AGENT_CARD = {
    "name": "Test Agent",
    "description": "A test agent",
    "url": "https://test-agent.example.com",
    "version": "1.0.0",
}


class TestRegistryRouter(unittest.TestCase):
    """Test cases for /api/registry endpoints."""

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
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _create_mcp_server(self, **overrides) -> McpServer:
        server = McpServer(
            name=overrides.get("name", "test-server"),
            endpoint_url=overrides.get("endpoint_url", "http://localhost:3000/mcp"),
            transport_type=overrides.get("transport_type", "sse"),
        )
        self.session.add(server)
        self.session.commit()
        self.session.refresh(server)
        return server

    def _create_agent(self, **overrides) -> Agent:
        agent = Agent(
            arn=overrides.get("arn", "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime"),
            runtime_id=overrides.get("runtime_id", "test-runtime"),
            name=overrides.get("name", "test-agent"),
            description=overrides.get("description", "A test agent"),
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            source="deploy",
            protocol=overrides.get("protocol", "HTTP"),
            network_mode=overrides.get("network_mode", "PUBLIC"),
        )
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        return agent

    def _create_a2a_agent(self, **overrides) -> A2aAgent:
        agent = A2aAgent(
            base_url=overrides.get("base_url", "https://test-agent.example.com"),
            name=overrides.get("name", "Test Agent"),
            description=overrides.get("description", "A test agent"),
            agent_version="1.0.0",
            agent_card_raw=json.dumps(SAMPLE_AGENT_CARD),
        )
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        return agent

    # ----- LIST RECORDS -----
    @patch("app.routers.registry.get_registry_client")
    def test_list_records(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.list_records.return_value = {
            "registryRecords": [SAMPLE_REGISTRY_RECORD]
        }
        mock_get_client.return_value = mock_client

        response = self.client.get("/api/registry/records")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["record_id"], "rec-123")
        self.assertEqual(data[0]["name"], "test-server")
        self.assertEqual(data[0]["status"], "DRAFT")

    @patch("app.routers.registry.get_registry_client")
    def test_list_records_with_status_filter(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.list_records.return_value = {
            "registryRecords": [
                {**SAMPLE_REGISTRY_RECORD, "status": "DRAFT"},
                {**SAMPLE_REGISTRY_RECORD, "recordId": "rec-456", "status": "APPROVED"},
            ]
        }
        mock_get_client.return_value = mock_client

        response = self.client.get("/api/registry/records?status=APPROVED")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["status"], "APPROVED")

    @patch("app.routers.registry.get_registry_client")
    def test_list_records_with_type_filter(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.list_records.return_value = {
            "registryRecords": [
                {**SAMPLE_REGISTRY_RECORD, "descriptorType": "MCP"},
                {**SAMPLE_REGISTRY_RECORD, "recordId": "rec-789", "descriptorType": "A2A"},
            ]
        }
        mock_get_client.return_value = mock_client

        response = self.client.get("/api/registry/records?descriptor_type=A2A")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["descriptor_type"], "A2A")

    # ----- GET RECORD -----
    @patch("app.routers.registry.get_registry_client")
    def test_get_record(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_record.return_value = SAMPLE_REGISTRY_RECORD
        mock_get_client.return_value = mock_client

        response = self.client.get("/api/registry/records/rec-123")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["record_id"], "rec-123")
        self.assertIn("descriptors", data)
        self.assertEqual(data["record_version"], "1")

    @patch("app.routers.registry.get_registry_client")
    def test_get_record_not_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_record.return_value = {}
        mock_get_client.return_value = mock_client

        response = self.client.get("/api/registry/records/nonexistent")
        self.assertEqual(response.status_code, 404)

    # ----- CREATE RECORD -----
    @patch("app.routers.registry.get_registry_client")
    def test_create_record_mcp(self, mock_get_client):
        server = self._create_mcp_server()
        mock_client = MagicMock()
        mock_client.create_record.return_value = {"recordId": "rec-new"}
        mock_client.wait_for_record.return_value = {
            **SAMPLE_REGISTRY_RECORD,
            "recordId": "rec-new",
            "status": "DRAFT",
        }
        mock_client.build_mcp_descriptors = MagicMock(return_value={"mcp": {"server": {"inlineContent": "{}"}, "tools": {"inlineContent": "[]"}}})
        mock_get_client.return_value = mock_client

        response = self.client.post("/api/registry/records", json={
            "resource_type": "mcp",
            "resource_id": server.id,
            "namespace": "remote.mcp",
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["record_id"], "rec-new")
        mock_client.build_mcp_descriptors.assert_called_once()
        call_kwargs = mock_client.build_mcp_descriptors.call_args
        self.assertEqual(call_kwargs.kwargs.get("namespace"), "remote.mcp")

        self.session.refresh(server)
        self.assertEqual(server.registry_record_id, "rec-new")
        self.assertEqual(server.registry_status, "DRAFT")

    @patch("app.routers.registry.get_registry_client")
    def test_create_record_mcp_invalid_namespace(self, mock_get_client):
        server = self._create_mcp_server()
        mock_get_client.return_value = MagicMock()
        response = self.client.post("/api/registry/records", json={
            "resource_type": "mcp",
            "resource_id": server.id,
            "namespace": "invalid.ns",
        })
        self.assertEqual(response.status_code, 400)

    @patch("app.routers.registry.get_registry_client")
    def test_create_record_a2a(self, mock_get_client):
        agent = self._create_a2a_agent()
        mock_client = MagicMock()
        mock_client.create_record.return_value = {"recordId": "rec-a2a"}
        mock_client.wait_for_record.return_value = {
            **SAMPLE_REGISTRY_RECORD,
            "recordId": "rec-a2a",
            "descriptorType": "A2A",
            "status": "DRAFT",
        }
        mock_client.build_a2a_descriptors = MagicMock(return_value={"a2a": {"agentCard": {"inlineContent": "{}"}}})
        mock_get_client.return_value = mock_client

        response = self.client.post("/api/registry/records", json={
            "resource_type": "a2a",
            "resource_id": agent.id,
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["record_id"], "rec-a2a")

        self.session.refresh(agent)
        self.assertEqual(agent.registry_record_id, "rec-a2a")
        self.assertEqual(agent.registry_status, "DRAFT")

    def test_create_record_invalid_resource_type(self):
        response = self.client.post("/api/registry/records", json={
            "resource_type": "invalid",
            "resource_id": 1,
        })
        self.assertEqual(response.status_code, 400)

    @patch("app.routers.registry.get_registry_client")
    def test_create_record_mcp_not_found(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        response = self.client.post("/api/registry/records", json={
            "resource_type": "mcp",
            "resource_id": 999,
        })
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.registry.get_registry_client")
    def test_create_record_a2a_not_found(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        response = self.client.post("/api/registry/records", json={
            "resource_type": "a2a",
            "resource_id": 999,
        })
        self.assertEqual(response.status_code, 404)

    # ----- SUBMIT FOR APPROVAL -----
    @patch("app.routers.registry.get_registry_client")
    def test_submit_for_approval(self, mock_get_client):
        server = self._create_mcp_server()
        server.registry_record_id = "rec-123"
        server.registry_status = "DRAFT"
        self.session.commit()

        mock_client = MagicMock()
        mock_client.submit_for_approval.return_value = {
            **SAMPLE_REGISTRY_RECORD,
            "status": "PENDING_APPROVAL",
        }
        mock_get_client.return_value = mock_client

        response = self.client.post("/api/registry/records/rec-123/submit")
        self.assertEqual(response.status_code, 200)

        self.session.refresh(server)
        self.assertEqual(server.registry_status, "PENDING_APPROVAL")

    # ----- APPROVE -----
    @patch("app.routers.registry.get_registry_client")
    def test_approve_record(self, mock_get_client):
        server = self._create_mcp_server()
        server.registry_record_id = "rec-123"
        server.registry_status = "PENDING_APPROVAL"
        self.session.commit()

        mock_client = MagicMock()
        mock_client.approve_record.return_value = {
            **SAMPLE_REGISTRY_RECORD,
            "status": "APPROVED",
        }
        mock_get_client.return_value = mock_client

        response = self.client.post(
            "/api/registry/records/rec-123/approve",
            json={"reason": "Meets all requirements"},
        )
        self.assertEqual(response.status_code, 200)

        self.session.refresh(server)
        self.assertEqual(server.registry_status, "APPROVED")

    # ----- REJECT -----
    @patch("app.routers.registry.get_registry_client")
    def test_reject_record(self, mock_get_client):
        server = self._create_mcp_server()
        server.registry_record_id = "rec-123"
        server.registry_status = "PENDING_APPROVAL"
        self.session.commit()

        mock_client = MagicMock()
        mock_client.reject_record.return_value = {
            **SAMPLE_REGISTRY_RECORD,
            "status": "REJECTED",
        }
        mock_get_client.return_value = mock_client

        response = self.client.post("/api/registry/records/rec-123/reject", json={
            "reason": "Does not meet security requirements",
        })
        self.assertEqual(response.status_code, 200)

        self.session.refresh(server)
        self.assertEqual(server.registry_status, "REJECTED")

    def test_reject_record_missing_reason(self):
        response = self.client.post("/api/registry/records/rec-123/reject", json={})
        self.assertEqual(response.status_code, 422)

    # ----- DELETE -----
    @patch("app.routers.registry.get_registry_client")
    def test_delete_record(self, mock_get_client):
        server = self._create_mcp_server()
        server.registry_record_id = "rec-123"
        server.registry_status = "REJECTED"
        self.session.commit()

        mock_client = MagicMock()
        mock_client.delete_record.return_value = {}
        mock_get_client.return_value = mock_client

        response = self.client.delete("/api/registry/records/rec-123")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["deleted"])

        self.session.refresh(server)
        self.assertIsNone(server.registry_record_id)
        self.assertIsNone(server.registry_status)

    # ----- SEARCH -----
    @patch("app.routers.registry.get_registry_client")
    def test_search_records(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.search_records.return_value = {
            "results": [{"recordId": "rec-123", "name": "test"}]
        }
        mock_get_client.return_value = mock_client

        response = self.client.get("/api/registry/search?q=test+query")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)

    def test_search_records_missing_query(self):
        response = self.client.get("/api/registry/search")
        self.assertEqual(response.status_code, 422)

    # ----- CREATE RECORD (AGENT) -----
    @patch("app.routers.registry.get_registry_client")
    def test_create_record_agent(self, mock_get_client):
        agent = self._create_agent()
        mock_client = MagicMock()
        mock_client.create_record.return_value = {"recordId": "rec-agent"}
        mock_client.wait_for_record.return_value = {
            **SAMPLE_REGISTRY_RECORD,
            "recordId": "rec-agent",
            "descriptorType": "A2A",
            "status": "DRAFT",
        }
        mock_client.build_agent_descriptors = MagicMock(return_value={"a2a": {"agentCard": {"inlineContent": "{}"}}})
        mock_get_client.return_value = mock_client

        response = self.client.post("/api/registry/records", json={
            "resource_type": "agent",
            "resource_id": agent.id,
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["record_id"], "rec-agent")

        self.session.refresh(agent)
        self.assertEqual(agent.registry_record_id, "rec-agent")
        self.assertEqual(agent.registry_status, "DRAFT")

    @patch("app.routers.registry.get_registry_client")
    def test_create_record_agent_not_found(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        response = self.client.post("/api/registry/records", json={
            "resource_type": "agent",
            "resource_id": 999,
        })
        self.assertEqual(response.status_code, 404)

    def test_agent_registry_columns_in_response(self):
        agent = self._create_agent()
        agent.registry_record_id = "rec-agent-test"
        agent.registry_status = "APPROVED"
        self.session.commit()

        response = self.client.get(f"/api/agents/{agent.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["registry_record_id"], "rec-agent-test")
        self.assertEqual(data["registry_status"], "APPROVED")

    # ----- DELETE AGENT WITH REGISTRY CLEANUP -----
    @patch("app.services.registry.get_registry_client")
    def test_delete_agent_cleans_up_registry_record(self, mock_get_reg_client):
        agent = self._create_agent()
        agent.registry_record_id = "rec-to-delete"
        agent.registry_status = "DRAFT"
        self.session.commit()

        mock_reg_client = MagicMock()
        mock_reg_client.delete_record.return_value = {}
        mock_get_reg_client.return_value = mock_reg_client

        response = self.client.delete(f"/api/agents/{agent.id}?cleanup_aws=true")
        self.assertIn(response.status_code, [200, 202])
        mock_reg_client.delete_record.assert_called_once_with("rec-to-delete")

    # ----- VISIBILITY FILTERING -----
    def test_mcp_registry_columns_in_response(self):
        server = self._create_mcp_server()
        server.registry_record_id = "rec-test"
        server.registry_status = "APPROVED"
        self.session.commit()

        response = self.client.get(f"/api/mcp/servers/{server.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["registry_record_id"], "rec-test")
        self.assertEqual(data["registry_status"], "APPROVED")

    @patch("app.routers.a2a.fetch_agent_card")
    def test_a2a_registry_columns_in_response(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_AGENT_CARD
        agent = self._create_a2a_agent()
        agent.registry_record_id = "rec-a2a-test"
        agent.registry_status = "DRAFT"
        self.session.commit()

        response = self.client.get(f"/api/a2a/agents/{agent.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["registry_record_id"], "rec-a2a-test")
        self.assertEqual(data["registry_status"], "DRAFT")


class TestRegistryService(unittest.TestCase):
    """Test cases for RegistryClient methods."""

    def test_build_mcp_descriptors(self):
        from app.services.registry import RegistryClient

        server = McpServer(
            name="test-server",
            description="A test server",
            endpoint_url="http://localhost:3000/mcp",
            transport_type="sse",
        )
        tool = McpTool(
            server_id=1,
            tool_name="hello",
            description="Says hello",
        )
        tool.set_input_schema({"type": "object", "properties": {"name": {"type": "string"}}})

        descriptors = RegistryClient.build_mcp_descriptors(server, [tool])
        self.assertIn("mcp", descriptors)
        mcp = descriptors["mcp"]
        self.assertIn("server", mcp)
        self.assertIn("tools", mcp)
        self.assertNotIn("schemaVersion", mcp["server"])
        server_info = json.loads(mcp["server"]["inlineContent"])
        self.assertEqual(server_info["name"], "aws.agentcore/test-server")
        self.assertEqual(server_info["description"], "A test server")
        self.assertEqual(server_info["protocolVersion"], "2025-12-11")
        self.assertEqual(server_info["version"], "1.0.0")
        self.assertIn("capabilities", server_info)
        self.assertEqual(server_info["serverInfo"]["name"], "aws.agentcore/test-server")
        self.assertEqual(server_info["serverInfo"]["version"], "1.0.0")
        self.assertEqual(server_info["instructions"], "A test server")
        self.assertEqual(server_info["packages"][0]["identifier"], "aws.agentcore/test-server")
        self.assertNotIn("protocolVersion", mcp["tools"])
        tools_wrapper = json.loads(mcp["tools"]["inlineContent"])
        self.assertIn("tools", tools_wrapper)
        self.assertEqual(len(tools_wrapper["tools"]), 1)
        self.assertEqual(tools_wrapper["tools"][0]["name"], "hello")
        self.assertIn("inputSchema", tools_wrapper["tools"][0])

    def test_build_mcp_descriptors_truncates_long_descriptions(self):
        from app.services.registry import RegistryClient

        long_desc = "A" * 150
        server = McpServer(
            name="test-server",
            description=long_desc,
            endpoint_url="http://localhost:3000/mcp",
            transport_type="sse",
        )
        tool = McpTool(server_id=1, tool_name="hello", description=long_desc)
        tool.set_input_schema({"type": "object", "properties": {}})

        descriptors = RegistryClient.build_mcp_descriptors(server, [tool])
        mcp = descriptors["mcp"]
        server_info = json.loads(mcp["server"]["inlineContent"])
        self.assertEqual(len(server_info["description"]), 100)
        self.assertEqual(len(server_info["instructions"]), 100)
        tools_wrapper = json.loads(mcp["tools"]["inlineContent"])
        self.assertEqual(len(tools_wrapper["tools"][0]["description"]), 100)

    def test_build_mcp_descriptors_custom_namespace(self):
        from app.services.registry import RegistryClient

        server = McpServer(
            name="exa-search",
            description="Exa search",
            endpoint_url="http://localhost:3000/mcp",
            transport_type="sse",
        )
        descriptors = RegistryClient.build_mcp_descriptors(server, [], namespace="remote.mcp")
        server_info = json.loads(descriptors["mcp"]["server"]["inlineContent"])
        self.assertEqual(server_info["name"], "remote.mcp/exa-search")
        self.assertEqual(server_info["serverInfo"]["name"], "remote.mcp/exa-search")
        self.assertEqual(server_info["packages"][0]["identifier"], "remote.mcp/exa-search")

    def test_build_agent_descriptors(self):
        from app.services.registry import RegistryClient

        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime",
            runtime_id="test-runtime",
            name="Test Agent",
            description="A test agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            protocol="HTTP",
            network_mode="PUBLIC",
        )

        descriptors = RegistryClient.build_agent_descriptors(agent)
        self.assertIn("a2a", descriptors)
        agent_card_wrapper = descriptors["a2a"]["agentCard"]
        self.assertEqual(agent_card_wrapper["schemaVersion"], "0.3")
        card = json.loads(agent_card_wrapper["inlineContent"])
        self.assertEqual(card["name"], "Test Agent")
        self.assertEqual(card["description"], "A test agent")
        self.assertEqual(card["version"], "1.0.0")
        self.assertEqual(card["protocolVersion"], "0.3")
        self.assertIn("capabilities", card)
        self.assertIn("skills", card)
        self.assertEqual(len(card["skills"]), 1)
        self.assertEqual(card["skills"][0]["id"], "default")
        self.assertIn("defaultInputModes", card)
        self.assertIn("defaultOutputModes", card)
        self.assertNotIn("provider", card)
        self.assertNotIn("_meta", card)

    def test_build_a2a_descriptors(self):
        from app.services.registry import RegistryClient

        agent = A2aAgent(
            base_url="https://test-agent.example.com",
            name="Test Agent",
            description="A test agent",
            agent_version="1.0.0",
            agent_card_raw=json.dumps(SAMPLE_AGENT_CARD),
        )

        descriptors = RegistryClient.build_a2a_descriptors(agent)
        self.assertIn("a2a", descriptors)
        agent_card_wrapper = descriptors["a2a"]["agentCard"]
        self.assertEqual(agent_card_wrapper["schemaVersion"], "0.3")
        card = json.loads(agent_card_wrapper["inlineContent"])
        self.assertEqual(card["name"], "Test Agent")
        self.assertEqual(card["protocolVersion"], "0.3")
        self.assertNotIn("provider", card)
        self.assertNotIn("_meta", card)

    def test_client_without_registry_id(self):
        from app.services.registry import RegistryClient
        client = RegistryClient(registry_id="", region="us-east-1")
        self.assertIsNone(client.control)
        self.assertIsNone(client.data)
        self.assertEqual(client.list_records(), {"registryRecords": []})
        self.assertEqual(client.search_records("test"), {"results": []})
        self.assertEqual(client.get_record("rec-123"), {})


class TestRegistryConfigFunctions(unittest.TestCase):
    """Test cases for registry ARN validation and singleton management."""

    def test_validate_registry_arn_valid(self):
        from app.services.registry import validate_registry_arn
        arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:registry/loom-prod"
        result = validate_registry_arn(arn)
        self.assertEqual(result, "loom-prod")

    def test_validate_registry_arn_invalid(self):
        from app.services.registry import validate_registry_arn
        with self.assertRaises(ValueError):
            validate_registry_arn("not-an-arn")
        with self.assertRaises(ValueError):
            validate_registry_arn("arn:aws:bedrock-agentcore:us-east-1:short:registry/id")
        with self.assertRaises(ValueError):
            validate_registry_arn("")

    def test_configure_registry(self):
        import app.services.registry as reg_module
        from app.services.registry import configure_registry
        old_client = reg_module._client
        try:
            client = configure_registry("test-registry-id", region="us-west-2")
            self.assertEqual(client.registry_id, "test-registry-id")
            self.assertEqual(client.region, "us-west-2")
            self.assertIs(reg_module._client, client)
        finally:
            reg_module._client = old_client

    def test_parse_registry_id_from_arn(self):
        from app.services.registry import parse_registry_id_from_arn
        self.assertEqual(
            parse_registry_id_from_arn(
                "arn:aws:bedrock-agentcore:us-east-1:123456789012:registry/my-reg"
            ),
            "my-reg",
        )
        self.assertEqual(parse_registry_id_from_arn("no-slash"), "")

    def test_init_registry_from_db(self):
        import app.services.registry as reg_module
        from app.services.registry import init_registry_from_db
        from app.models.site_setting import SiteSetting

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        session = TestSession()

        # Insert a registry ARN into site_settings
        setting = SiteSetting(
            key="loom_registry_id",
            value="arn:aws:bedrock-agentcore:us-east-1:123456789012:registry/loom-test",
        )
        session.add(setting)
        session.commit()

        old_client = reg_module._client
        try:
            reg_module._client = None
            init_registry_from_db(session)
            self.assertIsNotNone(reg_module._client)
            self.assertEqual(reg_module._client.registry_id, "loom-test")
        finally:
            reg_module._client = old_client
            session.close()


class TestRegistryConfigEndpoints(unittest.TestCase):
    """Test cases for /api/settings/registry endpoints."""

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
        self.client = TestClient(app)

        # Reset the registry singleton to a known state
        import app.services.registry as reg_module
        self._old_client = reg_module._client
        reg_module._client = None

    def tearDown(self):
        import app.services.registry as reg_module
        reg_module._client = self._old_client
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def test_get_registry_config_default(self):
        response = self.client.get("/api/settings/registry")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["registry_arn"], "")
        self.assertEqual(data["registry_id"], "")
        self.assertFalse(data["enabled"])

    def test_update_registry_config_valid(self):
        arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:registry/loom-prod"
        response = self.client.put("/api/settings/registry", json={"registry_arn": arn})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["registry_arn"], arn)
        self.assertEqual(data["registry_id"], "loom-prod")
        self.assertTrue(data["enabled"])

        # Verify persisted in DB
        from app.models.site_setting import SiteSetting
        row = self.session.query(SiteSetting).filter(SiteSetting.key == "loom_registry_id").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.value, arn)

    def test_update_registry_config_invalid(self):
        response = self.client.put("/api/settings/registry", json={"registry_arn": "bad-arn"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid registry ARN", response.json()["detail"])

    def test_update_registry_config_disable(self):
        # First enable
        arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:registry/loom-prod"
        self.client.put("/api/settings/registry", json={"registry_arn": arn})

        # Then disable
        response = self.client.put("/api/settings/registry", json={"registry_arn": ""})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["registry_arn"], "")
        self.assertEqual(data["registry_id"], "")
        self.assertFalse(data["enabled"])


if __name__ == "__main__":
    unittest.main()
