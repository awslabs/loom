"""Tests for MCP server management endpoints."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.mcp import McpServer, McpTool, McpServerAccess


class TestMcpRouter(unittest.TestCase):
    """Test cases for /api/mcp/servers endpoints."""

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

    def _create_server(self, **overrides) -> dict:
        payload = {
            "name": "test-server",
            "endpoint_url": "http://localhost:3000/mcp",
            "transport_type": "sse",
        }
        payload.update(overrides)
        response = self.client.post("/api/mcp/servers", json=payload)
        self.assertEqual(response.status_code, 201)
        return response.json()

    # ----- CREATE -----
    def test_create_server_minimal(self):
        data = self._create_server()
        self.assertEqual(data["name"], "test-server")
        self.assertEqual(data["endpoint_url"], "http://localhost:3000/mcp")
        self.assertEqual(data["transport_type"], "sse")
        self.assertEqual(data["status"], "active")
        self.assertEqual(data["auth_type"], "none")
        self.assertFalse(data["has_oauth2_secret"])
        self.assertIsNotNone(data["created_at"])

    def test_create_server_with_oauth2(self):
        data = self._create_server(
            auth_type="oauth2",
            oauth2_well_known_url="http://auth.example.com/.well-known/openid-configuration",
            oauth2_client_id="my-client-id",
            oauth2_client_secret="my-test-secret",  # nosec B106
            oauth2_scopes="read write",
        )
        self.assertEqual(data["auth_type"], "oauth2")
        self.assertEqual(data["oauth2_well_known_url"], "http://auth.example.com/.well-known/openid-configuration")
        self.assertEqual(data["oauth2_client_id"], "my-client-id")
        self.assertTrue(data["has_oauth2_secret"])
        self.assertEqual(data["oauth2_scopes"], "read write")

    def test_create_server_secret_not_in_response(self):
        data = self._create_server(
            auth_type="oauth2",
            oauth2_well_known_url="http://auth.example.com/.well-known/openid-configuration",
            oauth2_client_id="cid",
            oauth2_client_secret="my-test-secret",  # nosec B106
        )
        self.assertNotIn("oauth2_client_secret", data)

    def test_create_server_oauth2_missing_well_known(self):
        response = self.client.post("/api/mcp/servers", json={
            "name": "bad",
            "endpoint_url": "http://localhost:3000/mcp",
            "transport_type": "sse",
            "auth_type": "oauth2",
            "oauth2_client_id": "cid",
        })
        self.assertEqual(response.status_code, 422)

    def test_create_server_oauth2_missing_client_id(self):
        response = self.client.post("/api/mcp/servers", json={
            "name": "bad",
            "endpoint_url": "http://localhost:3000/mcp",
            "transport_type": "sse",
            "auth_type": "oauth2",
            "oauth2_well_known_url": "http://auth.example.com/.well-known/openid-configuration",
        })
        self.assertEqual(response.status_code, 422)

    def test_create_server_missing_required_fields(self):
        response = self.client.post("/api/mcp/servers", json={"name": "only-name"})
        self.assertEqual(response.status_code, 422)

        response = self.client.post("/api/mcp/servers", json={})
        self.assertEqual(response.status_code, 422)

    # ----- LIST -----
    def test_list_servers_empty(self):
        response = self.client.get("/api/mcp/servers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_servers(self):
        self._create_server(name="server-1")
        self._create_server(name="server-2")
        response = self.client.get("/api/mcp/servers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    # ----- GET -----
    def test_get_server(self):
        created = self._create_server()
        response = self.client.get(f"/api/mcp/servers/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "test-server")

    def test_get_server_not_found(self):
        response = self.client.get("/api/mcp/servers/999")
        self.assertEqual(response.status_code, 404)

    # ----- UPDATE -----
    def test_update_server(self):
        created = self._create_server()
        response = self.client.put(f"/api/mcp/servers/{created['id']}", json={
            "name": "updated-name",
            "description": "new desc",
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "updated-name")
        self.assertEqual(data["description"], "new desc")
        self.assertEqual(data["endpoint_url"], "http://localhost:3000/mcp")

    def test_update_server_not_found(self):
        response = self.client.put("/api/mcp/servers/999", json={"name": "x"})
        self.assertEqual(response.status_code, 404)

    # ----- DELETE -----
    def test_delete_server(self):
        created = self._create_server()
        response = self.client.delete(f"/api/mcp/servers/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], created["id"])

        get_response = self.client.get(f"/api/mcp/servers/{created['id']}")
        self.assertEqual(get_response.status_code, 404)

    def test_delete_server_not_found(self):
        response = self.client.delete("/api/mcp/servers/999")
        self.assertEqual(response.status_code, 404)

    # ----- TEST CONNECTION -----
    @patch("app.routers.mcp.svc_test_connection")
    def test_test_connection(self, mock_test):
        mock_test.return_value = {"success": True, "message": "Connection successful (stub)"}
        created = self._create_server()
        response = self.client.post(f"/api/mcp/servers/{created['id']}/test-connection")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("Connection successful", data["message"])

    def test_test_connection_not_found(self):
        response = self.client.post("/api/mcp/servers/999/test-connection")
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.mcp.svc_test_connection")
    def test_test_connection_pre_create(self, mock_test):
        mock_test.return_value = {"success": True, "message": "Connected to test-server v1.0"}
        response = self.client.post("/api/mcp/servers/test-connection", json={
            "endpoint_url": "https://example.com/mcp",
            "transport_type": "sse",
            "auth_type": "none",
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("Connected to", data["message"])

    # ----- TOOLS -----
    def test_get_tools_empty(self):
        created = self._create_server()
        response = self.client.get(f"/api/mcp/servers/{created['id']}/tools")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    @patch("app.routers.mcp.svc_fetch_tools")
    def test_refresh_tools(self, mock_fetch):
        mock_fetch.return_value = [
            {"name": "tool_a", "description": "Does A", "input_schema": {"type": "object"}},
            {"name": "tool_b", "description": "Does B"},
        ]
        created = self._create_server()
        response = self.client.post(f"/api/mcp/servers/{created['id']}/tools/refresh")
        self.assertEqual(response.status_code, 200)
        tools = response.json()
        self.assertEqual(len(tools), 2)
        self.assertEqual(tools[0]["tool_name"], "tool_a")
        self.assertEqual(tools[0]["input_schema"], {"type": "object"})
        self.assertEqual(tools[1]["tool_name"], "tool_b")
        self.assertIsNone(tools[1]["input_schema"])

    @patch("app.routers.mcp.svc_fetch_tools")
    def test_refresh_tools_replaces_existing(self, mock_fetch):
        created = self._create_server()
        mock_fetch.return_value = [{"name": "old_tool"}]
        self.client.post(f"/api/mcp/servers/{created['id']}/tools/refresh")

        mock_fetch.return_value = [{"name": "new_tool"}]
        self.client.post(f"/api/mcp/servers/{created['id']}/tools/refresh")

        response = self.client.get(f"/api/mcp/servers/{created['id']}/tools")
        tools = response.json()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["tool_name"], "new_tool")

    def test_get_tools_server_not_found(self):
        response = self.client.get("/api/mcp/servers/999/tools")
        self.assertEqual(response.status_code, 404)

    # ----- ACCESS RULES -----
    def test_get_access_rules_empty(self):
        created = self._create_server()
        response = self.client.get(f"/api/mcp/servers/{created['id']}/access")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_update_access_rules(self):
        created = self._create_server()
        response = self.client.put(f"/api/mcp/servers/{created['id']}/access", json={
            "rules": [
                {"persona_id": 1, "access_level": "all_tools"},
                {"persona_id": 2, "access_level": "selected_tools", "allowed_tool_names": ["tool_a", "tool_b"]},
            ]
        })
        self.assertEqual(response.status_code, 200)
        rules = response.json()
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0]["persona_id"], 1)
        self.assertEqual(rules[0]["access_level"], "all_tools")
        self.assertIsNone(rules[0]["allowed_tool_names"])
        self.assertEqual(rules[1]["persona_id"], 2)
        self.assertEqual(rules[1]["access_level"], "selected_tools")
        self.assertEqual(rules[1]["allowed_tool_names"], ["tool_a", "tool_b"])

    def test_update_access_rules_replaces(self):
        created = self._create_server()
        self.client.put(f"/api/mcp/servers/{created['id']}/access", json={
            "rules": [{"persona_id": 1, "access_level": "all_tools"}]
        })

        response = self.client.put(f"/api/mcp/servers/{created['id']}/access", json={
            "rules": [{"persona_id": 99, "access_level": "selected_tools", "allowed_tool_names": ["x"]}]
        })
        rules = response.json()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["persona_id"], 99)

    def test_access_rules_server_not_found(self):
        response = self.client.get("/api/mcp/servers/999/access")
        self.assertEqual(response.status_code, 404)

    # ----- TOOL INVOKE -----
    @patch("app.routers.mcp.svc_invoke_tool")
    def test_invoke_tool(self, mock_invoke):
        mock_invoke.return_value = {
            "success": True,
            "request": {"name": "hello_world", "arguments": {"name": "Loom"}},
            "result": {"content": [{"type": "text", "text": "Hello, Loom!"}]},
        }
        created = self._create_server()
        sid = created["id"]
        response = self.client.post(f"/api/mcp/servers/{sid}/tools/invoke", json={
            "tool_name": "hello_world",
            "arguments": {"name": "Loom"},
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("content", data["result"])
        mock_invoke.assert_called_once()

    @patch("app.routers.mcp.svc_invoke_tool")
    def test_invoke_tool_error(self, mock_invoke):
        mock_invoke.return_value = {
            "success": False,
            "request": {"name": "bad_tool", "arguments": {}},
            "error": "Tool not found",
        }
        created = self._create_server()
        sid = created["id"]
        response = self.client.post(f"/api/mcp/servers/{sid}/tools/invoke", json={
            "tool_name": "bad_tool",
            "arguments": {},
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "Tool not found")

    def test_invoke_tool_server_not_found(self):
        response = self.client.post("/api/mcp/servers/999/tools/invoke", json={
            "tool_name": "hello_world",
            "arguments": {},
        })
        self.assertEqual(response.status_code, 404)

    # ----- CASCADE DELETE -----
    @patch("app.routers.mcp.svc_fetch_tools")
    def test_delete_server_cascades_tools_and_access(self, mock_fetch):
        mock_fetch.return_value = [{"name": "tool_1"}]
        created = self._create_server()
        sid = created["id"]

        self.client.post(f"/api/mcp/servers/{sid}/tools/refresh")
        self.client.put(f"/api/mcp/servers/{sid}/access", json={
            "rules": [{"persona_id": 1, "access_level": "all_tools"}]
        })

        self.client.delete(f"/api/mcp/servers/{sid}")

        # Verify tools and access rules are gone
        self.assertEqual(self.session.query(McpTool).filter(McpTool.server_id == sid).count(), 0)
        self.assertEqual(self.session.query(McpServerAccess).filter(McpServerAccess.server_id == sid).count(), 0)


if __name__ == "__main__":
    unittest.main()
