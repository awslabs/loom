"""Tests for MCP Hub sessions, allowlist, and service auth (ADR 0007)."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import UserInfo, get_current_user
from app.models.agent import Agent
from app.models.mcp import McpServer, McpTool, McpServerAccess
from app.models.mcp_hub import McpHubSession
from app.services.mcp_hub import expose_tools, hash_token


def _admin() -> UserInfo:
    return UserInfo(
        sub="user-1",
        username="admin",
        groups=["t-admin", "g-admins-super"],
        scopes={"mcp:read", "mcp:write", "invoke", "admin:write", "agent:read"},
        idp_type="keycloak",
    )


class TestMcpHub(unittest.TestCase):
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
        app.dependency_overrides[get_current_user] = _admin
        os.environ["MCP_HUB_SERVICE_TOKEN"] = "test-hub-token"
        os.environ["MCP_HUB_PUBLIC_URL"] = "http://127.0.0.1:8790/mcp"
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        app.dependency_overrides.clear()

    def test_mint_introspect_revoke(self):
        mint = self.client.post("/api/mcp/hub/sessions", json={"client_label": "test"})
        self.assertEqual(mint.status_code, 201, mint.text)
        body = mint.json()
        self.assertTrue(body["hub_session_token"].startswith("hs_"))
        self.assertEqual(body["contract_version"], "2026-09-hub-1")

        intro = self.client.post(
            "/api/mcp/hub/sessions/introspect",
            headers={"Authorization": "Bearer test-hub-token"},
            json={"hub_session_token": body["hub_session_token"]},
        )
        self.assertEqual(intro.status_code, 200)
        self.assertTrue(intro.json()["active"])
        self.assertEqual(intro.json()["hub_session_id"], body["hub_session_id"])

        revoke = self.client.delete(f"/api/mcp/hub/sessions/{body['hub_session_id']}")
        self.assertEqual(revoke.status_code, 204)

        intro2 = self.client.post(
            "/api/mcp/hub/sessions/introspect",
            headers={"Authorization": "Bearer test-hub-token"},
            json={"hub_session_token": body["hub_session_token"]},
        )
        self.assertEqual(intro2.status_code, 200)
        self.assertFalse(intro2.json()["active"])

    def test_service_endpoints_fail_closed_without_token(self):
        os.environ["MCP_HUB_SERVICE_TOKEN"] = ""
        resp = self.client.post(
            "/api/mcp/hub/sessions/introspect",
            headers={"Authorization": "Bearer x"},
            json={"hub_session_token": "hs_x"},
        )
        self.assertEqual(resp.status_code, 503)

    def test_allowlist_empty_without_access(self):
        mint = self.client.post("/api/mcp/hub/sessions", json={}).json()
        resp = self.client.get(
            "/api/mcp/hub/allowlist",
            headers={
                "Authorization": "Bearer test-hub-token",
                "X-Loom-Hub-Session-Id": mint["hub_session_id"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["entries"], [])

    def test_allowlist_with_access_includes_tool(self):
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:1:runtime/r1",
            runtime_id="r1",
            name="Orientador",
            region="us-east-1",
            account_id="1",
            source="local",
        )
        self.session.add(agent)
        self.session.flush()
        server = McpServer(
            name="Grafana",
            endpoint_url="http://mcp-runtime:8787/s/1/mcp",
            transport_type="stdio",
            template_id="grafana",
            status="active",
        )
        self.session.add(server)
        self.session.flush()
        self.session.add(McpTool(
            server_id=server.id,
            tool_name="search_dashboards",
            description="Search",
            input_schema='{"type":"object"}',
        ))
        self.session.add(McpServerAccess(
            server_id=server.id,
            persona_id=agent.id,
            access_level="all_tools",
        ))
        self.session.commit()

        mint = self.client.post("/api/mcp/hub/sessions", json={}).json()
        resp = self.client.get(
            "/api/mcp/hub/allowlist",
            headers={
                "Authorization": "Bearer test-hub-token",
                "X-Loom-Hub-Session-Id": mint["hub_session_id"],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        entries = resp.json()["entries"]
        self.assertEqual(len(entries), 1)
        names = [t["name"] for t in entries[0]["tools"]]
        self.assertIn("search_dashboards", names)

    def test_tools_call_denied(self):
        mint = self.client.post("/api/mcp/hub/sessions", json={}).json()
        resp = self.client.post(
            "/api/mcp/hub/tools/call",
            headers={"Authorization": "Bearer test-hub-token"},
            json={
                "hub_session_id": mint["hub_session_id"],
                "tool_name": "nope",
                "arguments": {},
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_expose_tools_collision_namespaces(self):
        entries = [
            {
                "server_id": 1,
                "server_slug": "grafana",
                "tools": [{"name": "search", "description": "a", "inputSchema": {}}],
            },
            {
                "server_id": 2,
                "server_slug": "rancher",
                "tools": [{"name": "search", "description": "b", "inputSchema": {}}],
            },
        ]
        exposed, mapping = expose_tools(entries)
        names = {t["name"] for t in exposed}
        self.assertEqual(names, {"grafana__search", "rancher__search"})
        self.assertEqual(mapping["grafana__search"], (1, "search"))

    def test_materialize_from_grants_enabled(self):
        server = McpServer(
            name="Grafana",
            endpoint_url="http://mcp-runtime:8787/s/1/mcp",
            transport_type="stdio",
            template_id="grafana",
            status="active",
        )
        self.session.add(server)
        self.session.flush()
        self.session.add(McpTool(
            server_id=server.id,
            tool_name="search_dashboards",
            description="Search",
            input_schema='{"type":"object"}',
        ))
        self.session.commit()

        mint = self.client.post("/api/mcp/hub/sessions", json={}).json()
        resp = self.client.post(
            "/api/mcp/hub/materialize-allowlist",
            headers={"Authorization": "Bearer test-hub-token"},
            json={
                "hub_session_id": mint["hub_session_id"],
                "mcp_client_slug": "cursor",
                "client_status": "enabled",
                "allowed_groups": [],
                "grants": [
                    {
                        "server_id": server.id,
                        "access_level": "selected_tools",
                        "tool_names": ["search_dashboards"],
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["mcp_client_slug"], "cursor")
        self.assertEqual(len(body["entries"]), 1)
        names = [t["name"] for t in body["entries"][0]["tools"]]
        self.assertEqual(names, ["search_dashboards"])

    def test_materialize_discovered_empty(self):
        mint = self.client.post("/api/mcp/hub/sessions", json={}).json()
        resp = self.client.post(
            "/api/mcp/hub/materialize-allowlist",
            headers={"Authorization": "Bearer test-hub-token"},
            json={
                "hub_session_id": mint["hub_session_id"],
                "mcp_client_slug": "cursor",
                "client_status": "discovered",
                "grants": [{"server_id": 1, "access_level": "all_tools", "tool_names": []}],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["entries"], [])

    def test_introspect_includes_groups(self):
        mint = self.client.post("/api/mcp/hub/sessions", json={}).json()
        intro = self.client.post(
            "/api/mcp/hub/sessions/introspect",
            headers={"Authorization": "Bearer test-hub-token"},
            json={"hub_session_token": mint["hub_session_token"]},
        )
        self.assertEqual(intro.status_code, 200)
        self.assertIn("g-admins-super", intro.json().get("groups") or [])


if __name__ == "__main__":
    unittest.main()
