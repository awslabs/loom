"""Tests for MCP Hub BFF (OAuth era — ADR 0011; mint removed)."""
import os
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import UserInfo, get_current_user
from app.models.agent import Agent
from app.models.mcp import McpServer, McpTool
from app.services.mcp_hub import expose_tools
from app.services import mcp_hub_agents as hub_agents


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

    def test_hub_info_oauth(self):
        resp = self.client.get("/api/mcp/hub/info")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["auth"], "oauth")
        self.assertTrue(body["mcp_hub_url"].endswith("/mcp"))

    def test_mint_endpoints_gone(self):
        self.assertEqual(self.client.post("/api/mcp/hub/sessions", json={}).status_code, 410)
        self.assertEqual(
            self.client.post(
                "/api/mcp/hub/sessions/introspect",
                headers={"Authorization": "Bearer test-hub-token"},
                json={"hub_session_token": "hs_x"},
            ).status_code,
            410,
        )
        self.assertEqual(self.client.delete("/api/mcp/hub/sessions/any").status_code, 410)

    def test_service_endpoints_fail_closed_without_token(self):
        os.environ["MCP_HUB_SERVICE_TOKEN"] = ""
        resp = self.client.post(
            "/api/mcp/hub/materialize-allowlist",
            headers={"Authorization": "Bearer x"},
            json={
                "subject": "u1",
                "groups": [],
                "mcp_client_slug": "cursor",
                "client_status": "discovered",
                "grants": [],
            },
        )
        self.assertEqual(resp.status_code, 503)

    def test_tools_call_denied(self):
        resp = self.client.post(
            "/api/mcp/hub/tools/call",
            headers={"Authorization": "Bearer test-hub-token"},
            json={
                "subject": "u1",
                "groups": ["g-users-demo"],
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

        resp = self.client.post(
            "/api/mcp/hub/materialize-allowlist",
            headers={"Authorization": "Bearer test-hub-token"},
            json={
                "subject": "user-1",
                "groups": ["g-users-demo"],
                "connection_id": "oauth:user-1",
                "mcp_client_slug": "cursor",
                "client_status": "enabled",
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
        resp = self.client.post(
            "/api/mcp/hub/materialize-allowlist",
            headers={"Authorization": "Bearer test-hub-token"},
            json={
                "subject": "user-1",
                "groups": ["g-users-demo"],
                "mcp_client_slug": "cursor",
                "client_status": "discovered",
                "grants": [{"server_id": 1, "access_level": "all_tools", "tool_names": []}],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["entries"], [])

    def test_materialize_agents_rbac(self):
        demo = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:1:runtime/demo",
            runtime_id="demo",
            name="Orientador Demo",
            region="us-east-1",
            account_id="1",
            source="local",
            tags='{"loom:group":"demo"}',
            available_qualifiers='["DEFAULT"]',
        )
        other = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:1:runtime/test",
            runtime_id="test",
            name="Other",
            region="us-east-1",
            account_id="1",
            source="local",
            tags='{"loom:group":"test"}',
            available_qualifiers='["DEFAULT"]',
        )
        self.session.add_all([demo, other])
        self.session.commit()

        resp = self.client.post(
            "/api/mcp/hub/materialize-agents",
            headers={"Authorization": "Bearer test-hub-token"},
            json={"subject": "u1", "groups": ["t-user", "g-users-demo"]},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        names = {a["exposed_name"] for a in body["agents"]}
        self.assertEqual(names, {"agent__orientador-demo"})
        self.assertEqual(len(body["monitor_tools"]), 2)

        # direct helper: test-user group should not see demo
        from app.dependencies.auth import UserInfo, derive_scopes

        user = UserInfo(
            sub="u2",
            username="u2",
            groups=["t-user", "g-users-test"],
            scopes=derive_scopes(["t-user", "g-users-test"]),
            idp_type="keycloak",
        )
        mat = hub_agents.materialize_agents(self.session, user)
        exposed = {a["exposed_name"] for a in mat["agents"]}
        self.assertNotIn("agent__orientador-demo", exposed)
        self.assertIn("agent__other", exposed)

    def test_agent_run_forbidden_without_ownership(self):
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:1:runtime/a",
            runtime_id="a",
            name="A",
            region="us-east-1",
            account_id="1",
            source="local",
            tags='{"loom:group":"demo"}',
            available_qualifiers='["DEFAULT"]',
        )
        self.session.add(agent)
        self.session.commit()
        from app.models.session import InvocationSession
        from datetime import datetime

        sess = InvocationSession(
            agent_id=agent.id,
            session_id="sess-1",
            qualifier="DEFAULT",
            status="complete",
            created_at=datetime.utcnow(),
            user_id="owner",
        )
        self.session.add(sess)
        self.session.commit()

        resp = self.client.post(
            "/api/mcp/hub/agents/runs/sess-1",
            headers={"Authorization": "Bearer test-hub-token"},
            json={"subject": "other", "groups": ["t-user", "g-users-demo"]},
        )
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
