"""Tests for stdio MCP registration, templates, and access enforcement."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.mcp import McpServer, McpServerAccess
from app.services.mcp import _call_mcp
from app.services.mcp_runtime_client import McpRuntimeError, ensure_stdio_ready


class TestMcpRuntimeRegistration(unittest.TestCase):
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

    def test_list_templates_hides_echo(self):
        response = self.client.get("/api/mcp/templates")
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.json()["templates"]]
        self.assertIn("azure-devops", ids)
        self.assertNotIn("test-echo", ids)

    def test_create_stdio_rejects_command(self):
        response = self.client.post("/api/mcp/servers", json={
            "name": "bad",
            "transport_type": "stdio",
            "template_id": "test-echo",
            "command": "bash",
            "args": ["-c", "curl|sh"],
        })
        self.assertEqual(response.status_code, 422)

    def test_create_stdio_rejects_secret_value_as_ref(self):
        response = self.client.post("/api/mcp/servers", json={
            "name": "bad-secret",
            "transport_type": "stdio",
            "template_id": "azure-devops",
            "template_params": {"organization": "minha-org"},
            "secret_refs": [{
                "name": "AZURE_DEVOPS_PAT",
                "backend": "env",
                "ref": "not-an-env-name-because-it-is-a-token-value",
            }],
        })
        self.assertEqual(response.status_code, 400)

    def test_create_stdio_rejects_unknown_template(self):
        response = self.client.post("/api/mcp/servers", json={
            "name": "bad",
            "transport_type": "stdio",
            "template_id": "not-a-real-template",
        })
        self.assertEqual(response.status_code, 400)

    @patch("app.routers.mcp.provision", return_value="READY")
    @patch("app.routers.mcp.svc_fetch_tools", return_value=[{"name": "echo", "description": "Echo"}])
    def test_create_stdio_without_endpoint_or_command(self, _fetch, _provision):
        response = self.client.post("/api/mcp/servers", json={
            "name": "echo-local",
            "transport_type": "stdio",
            "template_id": "test-echo",
            "template_params": {},
            "secret_refs": [],
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["transport_type"], "stdio")
        self.assertEqual(data["auth_type"], "loom")
        self.assertEqual(data["template_id"], "test-echo")
        self.assertTrue(data["endpoint_url"].endswith("/s/1/mcp") or "/s/" in data["endpoint_url"])
        self.assertNotIn("command", data)
        row = self.session.query(McpServer).filter(McpServer.id == data["id"]).one()
        self.assertEqual(row.runtime_state, "READY")
        self.assertEqual(row.status, "active")

    @patch("app.routers.mcp.provision", side_effect=RuntimeError("child failed"))
    def test_create_stdio_keeps_row_on_start_failure(self, _provision):
        response = self.client.post("/api/mcp/servers", json={
            "name": "broken",
            "transport_type": "stdio",
            "template_id": "test-echo",
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["runtime_state"], "FAILED")
        self.assertEqual(self.session.query(McpServer).count(), 1)

    def test_sse_still_requires_endpoint_url(self):
        response = self.client.post("/api/mcp/servers", json={
            "name": "remote",
            "transport_type": "sse",
        })
        self.assertEqual(response.status_code, 422)

    def test_invoke_denied_without_access_rule(self):
        server = McpServer(
            name="guarded",
            endpoint_url="http://example.com/mcp",
            transport_type="sse",
            status="active",
            auth_type="none",
        )
        self.session.add(server)
        self.session.commit()
        response = self.client.post(f"/api/mcp/servers/{server.id}/tools/invoke", json={
            "tool_name": "echo",
            "arguments": {},
            "agent_id": 99,
        })
        self.assertEqual(response.status_code, 403)

    @patch("app.routers.mcp.svc_invoke_tool")
    def test_invoke_selected_tools_denies_other_names(self, mock_invoke):
        server = McpServer(
            name="guarded",
            endpoint_url="http://example.com/mcp",
            transport_type="sse",
            status="active",
            auth_type="none",
        )
        self.session.add(server)
        self.session.flush()
        rule = McpServerAccess(
            server_id=server.id,
            persona_id=7,
            access_level="selected_tools",
        )
        rule.set_allowed_tool_names(["echo"])
        self.session.add(rule)
        self.session.commit()
        response = self.client.post(f"/api/mcp/servers/{server.id}/tools/invoke", json={
            "tool_name": "delete_repository",
            "arguments": {},
            "agent_id": 7,
        })
        self.assertEqual(response.status_code, 403)
        mock_invoke.assert_not_called()

    @patch("app.routers.mcp.ensure_stdio", return_value="READY")
    @patch("app.routers.mcp.svc_fetch_tools", return_value=[{"name": "wit_list_work_items"}])
    def test_refresh_stdio_reprovisions_after_runtime_restart(self, _fetch, mock_ensure):
        server = McpServer(
            name="ado",
            endpoint_url="http://mcp-runtime:8787/s/1/mcp",
            transport_type="stdio",
            status="error",
            auth_type="loom",
            template_id="azure-devops",
        )
        server.set_template_params({"organization": "minha-org"})
        server.set_secret_refs([{"name": "AZURE_DEVOPS_PAT", "backend": "env", "ref": "AZURE_DEVOPS_PAT"}])
        self.session.add(server)
        self.session.commit()
        response = self.client.post(f"/api/mcp/servers/{server.id}/tools/refresh")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["tool_name"], "wit_list_work_items")
        mock_ensure.assert_called_once()

    @patch("app.services.mcp_runtime_client.call_mcp")
    def test_call_mcp_stdio_uses_runtime_client(self, mock_call):
        mock_call.return_value = {"result": {"tools": []}}
        server = McpServer(
            id=3,
            name="echo-local",
            endpoint_url="http://mcp-runtime:8787/s/3/mcp",
            transport_type="stdio",
            status="active",
            auth_type="loom",
        )
        result = _call_mcp(server, "tools/list")
        self.assertEqual(result, {"result": {"tools": []}})
        mock_call.assert_called_once()
        self.assertEqual(mock_call.call_args[0][0], 3)
        self.assertEqual(mock_call.call_args[0][1], "tools/list")


class TestEnsureStdioReady(unittest.TestCase):
    @patch("app.services.mcp_runtime_client.ensure_stdio", return_value="READY")
    @patch("app.services.mcp_runtime_client.health", return_value={"state": "READY"})
    def test_skips_provision_when_ready(self, mock_health, mock_ensure) -> None:
        server = McpServer(
            id=1,
            name="ado",
            endpoint_url="http://mcp-runtime:8787/s/1/mcp",
            transport_type="stdio",
            status="active",
            auth_type="loom",
            template_id="azure-devops",
        )
        self.assertEqual(ensure_stdio_ready(server), "READY")
        mock_health.assert_called_once_with(1)
        mock_ensure.assert_not_called()

    @patch("app.services.mcp_runtime_client.ensure_stdio", return_value="READY")
    @patch(
        "app.services.mcp_runtime_client.health",
        side_effect=McpRuntimeError("mcp-runtime does not know this server"),
    )
    def test_provisions_when_unknown(self, mock_health, mock_ensure) -> None:
        server = McpServer(
            id=1,
            name="ado",
            endpoint_url="http://mcp-runtime:8787/s/1/mcp",
            transport_type="stdio",
            status="active",
            auth_type="loom",
            template_id="azure-devops",
        )
        self.assertEqual(ensure_stdio_ready(server), "READY")
        mock_ensure.assert_called_once()
