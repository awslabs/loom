"""Regression tests for the loom:group ownership check on single-object
fetch-by-ID routes (H1-3954919).

Before this fix, get_agent_or_404, the inline Memory lookups in memories.py,
and the /invocations/{agent_id}/token route resolved resources by ID alone
with no loom:group check, while their list-route siblings correctly filtered
by tag. Any authenticated user in one resource group could read, update,
delete, or export another group's agents/memories, and mint a live Cognito
token for any agent, by ID.
"""
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.main import app
from app.models.agent import Agent
from app.models.memory import Memory
from app.routers.utils import check_resource_group_access
from fastapi import HTTPException


def _make_user(groups: list[str]) -> UserInfo:
    return UserInfo(sub="test-sub", username="test-user", groups=groups, scopes=derive_scopes(groups))


class _FakeResource:
    def __init__(self, group: str | None):
        self._group = group

    def get_tags(self) -> dict:
        return {"loom:group": self._group} if self._group else {}


class TestCheckResourceGroupAccessUnit(unittest.TestCase):
    """Direct unit tests of the shared helper, independent of any route."""

    def test_super_admin_bypasses_any_group(self):
        check_resource_group_access(_FakeResource("mcp"), _make_user(["t-admin", "g-admins-super"]))

    def test_untagged_resource_accessible_to_anyone(self):
        check_resource_group_access(_FakeResource(None), _make_user(["t-admin", "g-admins-demo"]))
        check_resource_group_access(_FakeResource(None), _make_user(["t-user", "g-users-demo"]))

    def test_admin_confined_to_own_group(self):
        check_resource_group_access(_FakeResource("demo"), _make_user(["t-admin", "g-admins-demo"]))
        with self.assertRaises(HTTPException) as ctx:
            check_resource_group_access(_FakeResource("mcp"), _make_user(["t-admin", "g-admins-demo"]))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_user_confined_to_own_groups_union(self):
        check_resource_group_access(_FakeResource("demo"), _make_user(["t-user", "g-users-demo"]))
        with self.assertRaises(HTTPException):
            check_resource_group_access(_FakeResource("strategics"), _make_user(["t-user", "g-users-demo"]))
        # Union semantics: access granted if ANY of the user's groups match.
        check_resource_group_access(
            _FakeResource("strategics"), _make_user(["t-user", "g-users-demo", "g-users-strategics"])
        )


class _GroupIsolationTestBase(unittest.TestCase):
    """Shared DB/client fixture for end-to-end loom:group regression tests.
    No test_ methods here — subclasses provide those so each concrete class
    runs only its own scenarios."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

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
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _override_user(self, groups: list[str]) -> None:
        app.dependency_overrides[get_current_user] = lambda: _make_user(groups)

    def _create_agent(self, group: str | None) -> int:
        agent = Agent(
            arn=f"arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/agent-{group}",
            runtime_id=f"agent-{group}",
            name=f"agent-{group}",
            region="us-east-1",
            account_id="123456789012",
            registered_at=datetime.utcnow(),
        )
        if group:
            agent.set_tags({"loom:group": group})
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        return agent.id

    def _create_memory(self, group: str | None) -> int:
        memory = Memory(
            name=f"memory-{group}",
            region="us-east-1",
            account_id="123456789012",
            status="ACTIVE",
            event_expiry_duration=90,
        )
        if group:
            memory.set_tags({"loom:group": group})
        self.session.add(memory)
        self.session.commit()
        self.session.refresh(memory)
        return memory.id


class TestAgentMemoryGroupIsolationEndToEnd(_GroupIsolationTestBase):
    """End-to-end regression tests: cross-group IDOR must now 403 on the
    routes named in the report, while same-group/super-admin/untagged access
    keeps working."""

    # -- Agents: GET/PATCH/DELETE by ID must respect loom:group --

    def test_demo_admin_cannot_read_other_group_agent_by_id(self):
        agent_id = self._create_agent("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_can_read_own_group_agent_by_id(self):
        agent_id = self._create_agent("demo")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(resp.status_code, 200)

    def test_super_admin_can_read_any_group_agent_by_id(self):
        agent_id = self._create_agent("mcp")
        self._override_user(["t-admin", "g-admins-super"])
        resp = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(resp.status_code, 200)

    def test_untagged_agent_readable_by_any_admin(self):
        agent_id = self._create_agent(None)
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(resp.status_code, 200)

    def test_demo_admin_cannot_patch_other_group_agent_by_id(self):
        agent_id = self._create_agent("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.patch(f"/api/agents/{agent_id}", json={"description": "pwned"})
        self.assertEqual(resp.status_code, 403)

    def test_user_cannot_read_other_group_agent_by_id(self):
        agent_id = self._create_agent("strategics")
        self._override_user(["t-user", "g-users-demo"])
        resp = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(resp.status_code, 403)

    # -- Memories: GET/DELETE by ID must respect loom:group --

    def test_demo_admin_cannot_read_other_group_memory_by_id(self):
        memory_id = self._create_memory("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/memories/{memory_id}")
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_can_read_own_group_memory_by_id(self):
        memory_id = self._create_memory("demo")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/memories/{memory_id}")
        self.assertEqual(resp.status_code, 200)

    def test_mcp_admin_cannot_purge_other_group_memory_by_id(self):
        memory_id = self._create_memory("demo")
        self._override_user(["t-admin", "g-admins-mcp"])
        resp = self.client.delete(f"/api/memories/{memory_id}/purge")
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_delete_still_confined_to_demo_group(self):
        """Preserves the pre-existing demo-admin-specific rule alongside the
        new general check: a demo admin still can't delete an untagged
        memory either (narrower than the general untagged-is-open rule)."""
        memory_id = self._create_memory(None)
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.delete(f"/api/memories/{memory_id}")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("demo", resp.json()["detail"].lower())

    # -- Named high-impact route: POST /invocations/{agent_id}/token --

    def test_cannot_mint_cognito_token_for_other_group_agent(self):
        agent_id = self._create_agent("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.post(f"/api/agents/{agent_id}/token")
        self.assertEqual(resp.status_code, 403)

    @patch("app.routers.invocations.get_cognito_token")
    @patch("app.routers.invocations.get_secret", return_value="client-secret")
    def test_can_mint_cognito_token_for_own_group_agent(self, mock_get_secret, mock_get_token):
        agent_id = self._create_agent("demo")
        agent = self.session.query(Agent).filter(Agent.id == agent_id).first()
        agent.set_authorizer_config({"type": "cognito", "pool_id": "us-east-1_abc123"})
        from app.models.config_entry import ConfigEntry
        self.session.add(ConfigEntry(agent_id=agent_id, key="COGNITO_CLIENT_ID", value="client-id"))
        self.session.add(ConfigEntry(agent_id=agent_id, key="COGNITO_CLIENT_SECRET_ARN", value="arn:aws:secretsmanager:us-east-1:123456789012:secret:test"))
        self.session.commit()
        mock_get_token.return_value = {"access_token": "tok", "token_type": "Bearer", "expires_in": 3600}

        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.post(f"/api/agents/{agent_id}/token")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["access_token"], "tok")


class TestSecurityRouterGroupIsolationEndToEnd(_GroupIsolationTestBase):
    """Same regression, for the ManagedRole/AuthorizerConfig primary-key
    lookups in security.py named in H1-3954919's follow-up: get_role,
    update_role, delete_role, get_authorizer, update_authorizer,
    delete_authorizer, and the credential-token-mint route all previously
    resolved by ID alone with no loom:group check."""

    def _create_role(self, group: str | None) -> int:
        from app.models.managed_role import ManagedRole
        role = ManagedRole(
            role_name=f"role-{group}",
            role_arn=f"arn:aws:iam::123456789012:role/role-{group}",
            role_type="agent",
        )
        if group:
            role.set_tags({"loom:group": group})
        self.session.add(role)
        self.session.commit()
        self.session.refresh(role)
        return role.id

    def _create_authorizer(self, group: str | None) -> int:
        from app.models.authorizer_config import AuthorizerConfig
        auth = AuthorizerConfig(
            name=f"auth-{group}",
            authorizer_type="cognito",
            pool_id="us-east-1_abc123",
        )
        if group:
            auth.set_tags({"loom:group": group})
        self.session.add(auth)
        self.session.commit()
        self.session.refresh(auth)
        return auth.id

    # -- Managed roles: GET/PUT/DELETE by ID must respect loom:group --

    @patch("app.routers.security.get_role_policy_details", return_value={})
    def test_demo_admin_cannot_read_other_group_role_by_id(self, mock_policy):
        role_id = self._create_role("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/security/roles/{role_id}")
        self.assertEqual(resp.status_code, 403)

    @patch("app.routers.security.get_role_policy_details", return_value={})
    def test_demo_admin_can_read_own_group_role_by_id(self, mock_policy):
        role_id = self._create_role("demo")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/security/roles/{role_id}")
        self.assertEqual(resp.status_code, 200)

    def test_demo_admin_cannot_update_other_group_role_by_id(self):
        role_id = self._create_role("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.put(f"/api/security/roles/{role_id}", json={"description": "pwned"})
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_cannot_delete_other_group_role_by_id(self):
        role_id = self._create_role("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.delete(f"/api/security/roles/{role_id}")
        self.assertEqual(resp.status_code, 403)

    # -- Authorizer configs: GET/PUT/DELETE by ID must respect loom:group --

    def test_demo_admin_cannot_read_other_group_authorizer_by_id(self):
        auth_id = self._create_authorizer("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/security/authorizers/{auth_id}")
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_can_read_own_group_authorizer_by_id(self):
        auth_id = self._create_authorizer("demo")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/security/authorizers/{auth_id}")
        self.assertEqual(resp.status_code, 200)

    def test_demo_admin_cannot_update_other_group_authorizer_by_id(self):
        auth_id = self._create_authorizer("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.put(f"/api/security/authorizers/{auth_id}", json={"name": "pwned"})
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_cannot_delete_other_group_authorizer_by_id(self):
        auth_id = self._create_authorizer("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.delete(f"/api/security/authorizers/{auth_id}")
        self.assertEqual(resp.status_code, 403)

    # -- Named high-impact route: POST /authorizers/{auth_id}/credentials/{cred_id}/token --

    def test_cannot_mint_credential_token_for_other_group_authorizer(self):
        from app.models.authorizer_credential import AuthorizerCredential
        auth_id = self._create_authorizer("mcp")
        cred = AuthorizerCredential(authorizer_config_id=auth_id, label="cred", client_id="cid")
        self.session.add(cred)
        self.session.commit()
        self.session.refresh(cred)

        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.post(f"/api/security/authorizers/{auth_id}/credentials/{cred.id}/token")
        self.assertEqual(resp.status_code, 403)


class TestMcpServerGroupIsolationEndToEnd(_GroupIsolationTestBase):
    """Same regression, for McpServer single-object routes. McpServer had no
    loom:group concept at all until this change added a tags column
    (mirroring Agent/Memory/ManagedRole/AuthorizerConfig); _get_server_or_404
    now enforces the same check, closing the admin-key exposure on
    POST /{server_id}/tools/invoke named in the report."""

    def _create_server(self, group: str | None) -> int:
        from app.models.mcp import McpServer
        server = McpServer(
            name=f"server-{group}",
            endpoint_url="https://example.test/mcp",
            transport_type="streamable_http",
        )
        if group:
            server.set_tags({"loom:group": group})
        self.session.add(server)
        self.session.commit()
        self.session.refresh(server)
        return server.id

    def test_demo_admin_cannot_read_other_group_server_by_id(self):
        server_id = self._create_server("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/mcp/servers/{server_id}")
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_can_read_own_group_server_by_id(self):
        server_id = self._create_server("demo")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/mcp/servers/{server_id}")
        self.assertEqual(resp.status_code, 200)

    def test_super_admin_can_read_any_group_server_by_id(self):
        server_id = self._create_server("mcp")
        self._override_user(["t-admin", "g-admins-super"])
        resp = self.client.get(f"/api/mcp/servers/{server_id}")
        self.assertEqual(resp.status_code, 200)

    def test_untagged_server_readable_by_any_admin(self):
        server_id = self._create_server(None)
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/mcp/servers/{server_id}")
        self.assertEqual(resp.status_code, 200)

    def test_demo_admin_cannot_update_other_group_server_by_id(self):
        server_id = self._create_server("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.put(f"/api/mcp/servers/{server_id}", json={"name": "pwned"})
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_cannot_delete_other_group_server_by_id(self):
        server_id = self._create_server("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.delete(f"/api/mcp/servers/{server_id}")
        self.assertEqual(resp.status_code, 403)

    # -- Named high-impact route: POST /{server_id}/tools/invoke (admin-key exposure) --

    def test_cannot_invoke_tool_with_admin_key_for_other_group_server(self):
        server_id = self._create_server("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.post(f"/api/mcp/servers/{server_id}/tools/invoke", json={"tool_name": "x", "arguments": {}})
        self.assertEqual(resp.status_code, 403)

    @patch("app.routers.mcp.svc_invoke_tool", return_value={"success": True, "request": {}, "result": {}})
    @patch("app.routers.mcp.resolve_api_key", return_value="admin-secret")
    def test_can_invoke_tool_for_own_group_server(self, mock_resolve, mock_invoke):
        server_id = self._create_server("demo")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.post(f"/api/mcp/servers/{server_id}/tools/invoke", json={"tool_name": "x", "arguments": {}})
        self.assertEqual(resp.status_code, 200)


class TestA2aAgentGroupIsolationEndToEnd(_GroupIsolationTestBase):
    """Same regression, for A2aAgent single-object routes. A2aAgent had no
    loom:group concept at all until this change added a resource_tags column
    (get_tags()/set_tags() mirror the loom:group convention); _get_agent_or_404
    now enforces the same check across all 10 single-object routes."""

    def _create_a2a_agent(self, group: str | None) -> int:
        from app.models.a2a import A2aAgent
        agent = A2aAgent(
            base_url=f"https://example.test/a2a-{group}",
            name=f"a2a-{group}",
            description="test agent",
            agent_version="1.0",
        )
        if group:
            agent.set_tags({"loom:group": group})
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        return agent.id

    def test_demo_admin_cannot_read_other_group_a2a_agent_by_id(self):
        agent_id = self._create_a2a_agent("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/a2a/agents/{agent_id}")
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_can_read_own_group_a2a_agent_by_id(self):
        agent_id = self._create_a2a_agent("demo")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/a2a/agents/{agent_id}")
        self.assertEqual(resp.status_code, 200)

    def test_super_admin_can_read_any_group_a2a_agent_by_id(self):
        agent_id = self._create_a2a_agent("mcp")
        self._override_user(["t-admin", "g-admins-super"])
        resp = self.client.get(f"/api/a2a/agents/{agent_id}")
        self.assertEqual(resp.status_code, 200)

    def test_demo_admin_cannot_update_other_group_a2a_agent_by_id(self):
        agent_id = self._create_a2a_agent("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.put(f"/api/a2a/agents/{agent_id}", json={"name": "pwned"})
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_cannot_delete_other_group_a2a_agent_by_id(self):
        agent_id = self._create_a2a_agent("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.delete(f"/api/a2a/agents/{agent_id}")
        self.assertEqual(resp.status_code, 403)

    def test_demo_admin_cannot_read_other_group_a2a_skills_by_id(self):
        agent_id = self._create_a2a_agent("mcp")
        self._override_user(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/a2a/agents/{agent_id}/skills")
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
