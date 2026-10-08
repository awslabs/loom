"""Resources bound to an agent by primary key must be group-checked.

`GET /api/mcp/servers/{id}` and `GET /api/memories/{id}` have returned 403
across groups since the single-object helpers landed, but the agent deploy
paths resolved `mcp_servers`, `memory_ids` and `a2a_agents` straight from
primary keys in the request body and never ran that check. So the IDs were a
second way in: a caller holding `agent:write` in one group could attach
another group's MCP server — whose deploy snapshot carries
`oauth2_client_secret` into a credential provider created under the caller's
own agent — or another group's `memory_id` into their own
`AGENT_CONFIG_JSON`.

Ten bind sites across the four entry points (`_deploy_agent`,
`_deploy_harness`, `redeploy_deploy_agent`, `redeploy_harness_agent`) now go
through `assert_bindable`.

`code_interpreter_role_id` had the same shape and is covered here too. It was
not in the report, and it is worse: `ci_role.role_arn` becomes the code
interpreter's `execution_role_arn`, so an unchecked bind hands another group's
IAM role to the caller's agent — privilege escalation, not just disclosure.
"""
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.models.managed_role import ManagedRole
from app.models.mcp import McpServer
from app.models.memory import Memory
from app.models.a2a import A2aAgent

WITNESS = "LOOM-DEPLOY-BIND-WITNESS"


class TestAgentBindsRespectGroup(unittest.TestCase):
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

        # Every victim resource belongs to the "mcp" group and carries the
        # witness in whichever field the deploy path would propagate.
        self.mcp = McpServer(
            name="victim-mcp", description="victim", endpoint_url="https://victim.internal/mcp",
            transport_type="streamable_http", auth_type="oauth2",
            oauth2_well_known_url="https://victim.example.com/.well-known/openid-configuration",
            oauth2_client_id="victim-client",
            oauth2_client_secret=WITNESS,  # nosec B106
        )
        self.mcp.set_tags({"loom:group": "mcp"})

        self.memory = Memory(
            name="victim-memory", memory_id=WITNESS,
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/victim",
            status="ACTIVE", region="us-east-1", account_id="123456789012",
            event_expiry_duration=90,
        )
        self.memory.set_tags({"loom:group": "mcp"})

        self.a2a = A2aAgent(
            base_url="https://victim.internal/a2a", name="victim-a2a", description="victim",
            agent_version="1.0.0", status="active", auth_type="oauth2",
            oauth2_client_id="victim-client",
            oauth2_client_secret=WITNESS,  # nosec B106
        )
        self.a2a.set_tags({"loom:group": "mcp"})

        self.role = ManagedRole(
            role_name="victim-role", role_type="code_interpreter",
            role_arn="arn:aws:iam::123456789012:role/victim-code-interpreter",
        )
        self.role.set_tags({"loom:group": "mcp"})

        # An execution role the attacker legitimately owns. Loom no longer
        # creates roles, so a deploy must name a registered one — without this
        # every deploy below would 400 before the bind check it is testing.
        self.own_role = ManagedRole(
            role_name="demo-exec", role_type="agent",
            role_arn="arn:aws:iam::123456789012:role/demo-exec",
        )
        self.own_role.set_tags({"loom:group": "demo"})

        rows = (self.mcp, self.memory, self.a2a, self.role, self.own_role)
        for row in rows:
            self.db.add(row)
        self.db.commit()
        for row in rows:
            self.db.refresh(row)

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

    def _deploy(self, source: str = "deploy", **extra):
        payload = {
            "source": source,
            "name": "demo_attacker",
            "model_id": "us.anthropic.claude-sonnet-4-6",
            "tags": {"loom:group": "demo"},
            "role_arn": "arn:aws:iam::123456789012:role/demo-exec",
        }
        if source == "harness":
            payload["role_arn"] = "arn:aws:iam::123456789012:role/test-role"
        payload.update(extra)
        return self.client.post("/api/agents", json=payload)

    # -- the reported paths --

    def test_cannot_bind_another_groups_mcp_server_on_create(self) -> None:
        """The reported chain: GET is 403, so the bind must be too."""
        self._as(["t-admin", "g-admins-demo"])
        self.assertEqual(
            self.client.get(f"/api/mcp/servers/{self.mcp.id}").status_code, 403,
        )
        resp = self._deploy(mcp_servers=[self.mcp.id])
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_cannot_bind_another_groups_memory_on_create(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self._deploy(memory_ids=[self.memory.id])
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_cannot_bind_another_groups_a2a_agent_on_create(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self._deploy(a2a_agents=[self.a2a.id])
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_cannot_bind_another_groups_mcp_server_on_harness_create(self) -> None:
        """The harness entry point binds the same way the custom one does."""
        self._as(["t-admin", "g-admins-demo"])
        resp = self._deploy(source="harness", mcp_servers=[self.mcp.id])
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_cannot_bind_another_groups_memory_on_harness_create(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self._deploy(source="harness", memory_ids=[self.memory.id])
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    # -- the redeploy paths, named in the report as the second way in --

    def _own_agent(self, harness: bool = False) -> int:
        """An agent the attacker legitimately owns, to redeploy."""
        from app.models.agent import Agent

        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/attacker",
            runtime_id="attacker", name="demo_attacker", status="READY",
            region="us-east-1", account_id="123456789012",
            source="harness" if harness else "deploy",
            harness_id="h-attacker" if harness else None,
        )
        agent.set_tags({"loom:group": "demo"})
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent.id

    def test_cannot_bind_another_groups_mcp_server_on_redeploy(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        agent_id = self._own_agent()
        resp = self.client.put(f"/api/agents/{agent_id}/redeploy-deploy", json={
            "source": "deploy", "name": "demo_attacker",
            "model_id": "us.anthropic.claude-sonnet-4-6",
            "role_arn": "arn:aws:iam::123456789012:role/demo-exec",
            "mcp_servers": [self.mcp.id],
        })
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_cannot_bind_another_groups_memory_on_harness_redeploy(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        agent_id = self._own_agent(harness=True)
        resp = self.client.put(f"/api/agents/{agent_id}/redeploy-harness", json={
            "source": "harness", "name": "demo_attacker",
            "model_id": "us.anthropic.claude-sonnet-4-6",
            "role_arn": "arn:aws:iam::123456789012:role/demo-exec",
            "memory_ids": [self.memory.id],
        })
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    # -- not in the report: the IAM role bind --

    def test_cannot_bind_another_groups_code_interpreter_role(self) -> None:
        """role_arn becomes the code interpreter's execution role, so this is
        escalation rather than disclosure."""
        self._as(["t-admin", "g-admins-demo"])
        resp = self._deploy(code_interpreter_role_id=self.role.id)
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn("victim-code-interpreter", resp.text)

    def test_cannot_bind_another_groups_role_on_harness_create(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self._deploy(source="harness", code_interpreter_role_id=self.role.id)
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn("victim-code-interpreter", resp.text)

    # -- untagged resources are nobody's to bind --

    def test_cannot_bind_an_untagged_resource(self) -> None:
        """Consistent with check_resource_group_access failing closed: a
        resource nobody has assigned to a group is not bindable either."""
        orphan = McpServer(
            name="orphan", description="untagged", endpoint_url="https://orphan.internal/mcp",
            transport_type="streamable_http", auth_type="none",
        )
        self.db.add(orphan)
        self.db.commit()
        self.db.refresh(orphan)

        self._as(["t-admin", "g-admins-demo"])
        self.assertEqual(self._deploy(mcp_servers=[orphan.id]).status_code, 403)

    # -- positive controls: a nonexistent id is still a 400, not a 403 --

    def test_unknown_id_still_reports_not_found(self) -> None:
        """The bind check must not turn a missing row into an access error,
        which would make every bad ID look like someone else's resource."""
        self._as(["t-admin", "g-admins-super"])
        resp = self._deploy(mcp_servers=[424242])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not found", resp.text.lower())

    def test_super_admin_may_still_bind_across_groups(self) -> None:
        """Keyed on what the caller can reach, so a super-admin composing
        across groups stays possible — deliberately, to avoid breaking
        deployments that share one integration between groups."""
        self._as(["t-admin", "g-admins-super"])
        resp = self._deploy(mcp_servers=[self.mcp.id])
        self.assertNotEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
