"""Gaps the primary-key bind guard found that no report named.

The reported finding was the agent deploy paths binding `mcp_servers`,
`memory_ids` and `a2a_agents` by primary key with no group check. Making that
check mechanical (see `test_router_authorization_guard.py`'s
`TestPrimaryKeyBindsAreAuthorized`) surfaced four more instances of the same
shape, none of which were in the report:

1. `invoke_agent_endpoint` carried an *inlined copy* of
   `check_resource_group_access` whose `if agent_group:` skipped the whole
   check for an untagged agent. When the shared helper was changed to fail
   closed, the copy kept failing open, so an untagged agent stayed invokable
   by anyone holding `invoke`.
2. `connector_ids` on both the HTTP and WebSocket invoke paths resolved MCP
   servers from the request body with no group check — the same bind as the
   deploy paths, on the hot path.
3. `registry.create_record` resolved a caller-supplied `resource_id` to an
   MCP server, A2A agent or agent with no group check, letting one group
   submit another group's resource into the registry.
4. `credential_id` on the invoke path resolved an `AuthorizerCredential` and
   used its client secret to mint an M2M token. The credential carries no
   `loom:group`, so the owning `AuthorizerConfig` is what gets checked.
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.models.agent import Agent
from app.models.integration import Integration
from app.models.mcp import McpServer

WITNESS = "LOOM-PK-BIND-GUARD-WITNESS"


class PkBindTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self) -> None:
        self.db = self.Session()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # An MCP server owned by the "mcp" group, carrying a secret.
        self.victim_mcp = McpServer(
            name="victim-connector", description="victim",
            endpoint_url="https://victim.internal/mcp",
            transport_type="streamable_http", auth_type="oauth2",
            oauth2_client_id="victim-client",
            oauth2_client_secret=WITNESS,  # nosec B106
        )
        self.victim_mcp.set_tags({"loom:group": "mcp"})
        self.db.add(self.victim_mcp)

        # An agent the attacker legitimately owns, so only the bind is at issue.
        self.own_agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/attacker",
            runtime_id="attacker", name="demo_attacker", status="READY",
            region="us-east-1", account_id="123456789012", source="deploy",
        )
        self.own_agent.set_tags({"loom:group": "demo"})
        self.db.add(self.own_agent)
        self.db.commit()
        self.db.refresh(self.victim_mcp)
        self.db.refresh(self.own_agent)

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        app.dependency_overrides.clear()

    def _as(self, groups: list[str]) -> None:
        user = UserInfo(sub="attacker-sub", username="attacker@example.com",
                        groups=groups, scopes=derive_scopes(groups))
        app.dependency_overrides[get_current_user] = lambda: user


class TestUntaggedAgentIsNotInvokable(PkBindTestCase):
    """Gap 1: the inlined check failed open where the shared helper fails closed."""

    def _untagged_agent(self) -> int:
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/orphan",
            runtime_id="orphan", name="orphan_agent", status="READY",
            region="us-east-1", account_id="123456789012", source="deploy",
        )
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent.id

    def test_group_admin_cannot_invoke_an_untagged_agent(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.post(
            f"/api/agents/{self._untagged_agent()}/invoke",
            json={"prompt": "hello", "qualifier": "DEFAULT"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_plain_user_cannot_invoke_an_untagged_agent(self) -> None:
        self._as(["t-user", "g-users-demo"])
        resp = self.client.post(
            f"/api/agents/{self._untagged_agent()}/invoke",
            json={"prompt": "hello", "qualifier": "DEFAULT"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_cross_group_invoke_is_still_refused(self) -> None:
        """The case the inlined copy did handle, kept as a regression guard."""
        self._as(["t-admin", "g-admins-mcp"])
        resp = self.client.post(
            f"/api/agents/{self.own_agent.id}/invoke",
            json={"prompt": "hello", "qualifier": "DEFAULT"},
        )
        self.assertEqual(resp.status_code, 403)


class TestConnectorBindsAreGroupChecked(PkBindTestCase):
    """Gap 2: connector_ids is a request-body bind on the invoke hot path."""

    def test_cannot_attach_another_groups_connector_on_invoke(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.post(
            f"/api/agents/{self.own_agent.id}/invoke",
            json={
                "prompt": "hello", "qualifier": "DEFAULT",
                "connector_ids": [self.victim_mcp.id],
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)


class TestRegistryRecordCreationIsGroupChecked(PkBindTestCase):
    """Gap 3: resource_id is caller-supplied under registry:write."""

    def test_cannot_register_another_groups_mcp_server(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.post("/api/registry/records", json={
            "resource_type": "mcp", "resource_id": self.victim_mcp.id,
        })
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_cannot_register_another_groups_agent(self) -> None:
        victim_agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/victim",
            runtime_id="victim", name="victim_agent", status="READY",
            region="us-east-1", account_id="123456789012", source="deploy",
        )
        victim_agent.set_tags({"loom:group": "mcp"})
        self.db.add(victim_agent)
        self.db.commit()
        self.db.refresh(victim_agent)

        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.post("/api/registry/records", json={
            "resource_type": "agent", "resource_id": victim_agent.id,
        })
        self.assertEqual(resp.status_code, 403)


class TestSkillDependentsAreFiltered(PkBindTestCase):
    """Gap 3b: a reverse lookup is still a read of other groups' agents."""

    def test_dependents_omit_another_groups_agent(self) -> None:
        victim_agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/victim",
            runtime_id="victim", name="victim_agent_name", status="READY",
            region="us-east-1", account_id="123456789012", source="deploy",
        )
        victim_agent.set_tags({"loom:group": "mcp"})
        self.db.add(victim_agent)
        self.db.commit()
        self.db.refresh(victim_agent)
        self.db.add(Integration(
            agent_id=victim_agent.id, integration_type="skill", enabled=True,
            integration_config='{"record_id": "rec-123"}',
        ))
        self.db.commit()

        self._as(["t-admin", "g-admins-demo"])
        with patch("app.services.registry.get_registry_client"):
            resp = self.client.get("/api/registry/records/rec-123/dependents")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("victim_agent_name", resp.text)

    def test_owning_group_still_sees_its_dependent(self) -> None:
        self.db.add(Integration(
            agent_id=self.own_agent.id, integration_type="skill", enabled=True,
            integration_config='{"record_id": "rec-123"}',
        ))
        self.db.commit()

        self._as(["t-admin", "g-admins-demo"])
        with patch("app.services.registry.get_registry_client"):
            resp = self.client.get("/api/registry/records/rec-123/dependents")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("demo_attacker", resp.text)


if __name__ == "__main__":
    unittest.main()
