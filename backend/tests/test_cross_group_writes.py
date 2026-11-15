"""Cross-group write paths reported against the loom:group boundary.

Three ways a group-scoped admin could reach another group's resources:

1. PUT /api/agents/{id}/config wrote any key, including the secret ARNs and
   AGENT_CONFIG_JSON that agent deletion/redeploy later trust for force-deletes,
   credential-provider deletes and LiteLLM key revocation.
2. PUT /api/security/authorizers/{id} derived the secret path from the (renameable)
   display name and overwrote whatever secret lived there.
3. require_group_tag checked that a loom:group tag was present, not that its
   value was one of the caller's groups, so MCP servers, A2A agents and
   others could be planted into another group's catalog.
"""
import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.main import app
from app.models.agent import Agent
from app.models.authorizer_config import AuthorizerConfig
from app.models.config_entry import ConfigEntry
from app.routers import agents as agents_router
from app.routers.utils import caller_group_tags, require_group_tag


def _user(groups: list[str]) -> UserInfo:
    return UserInfo(sub="sub", username="u@example.com", groups=groups, scopes=derive_scopes(groups))


DEMO_ADMIN = ["t-admin", "g-admins-demo"]
SUPER = ["t-admin", "g-admins-super"]


class _ApiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        app.dependency_overrides.clear()

    def _as(self, groups: list[str]) -> None:
        user = _user(groups)
        app.dependency_overrides[get_current_user] = lambda: user

    def _agent(self, name: str = "demo_bot", group: str = "demo", config: dict | None = None) -> Agent:
        agent = Agent(
            arn=f"arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/{name}-x",
            runtime_id=f"{name}-x", name=name, status="READY", region="us-east-1",
            account_id="123456789012", source="deploy", registered_at=datetime.utcnow(),
        )
        agent.set_tags({"loom:group": group})
        self.db.add(agent)
        self.db.commit()
        for key, value in (config or {}).items():
            self.db.add(ConfigEntry(agent_id=agent.id, key=key, value=value,
                                    is_secret=key.endswith("_SECRET_ARN"), source="env_var"))
        self.db.commit()
        self.db.refresh(agent)
        return agent


# ---------------------------------------------------------------------------
# 1. Config API + destructive cleanup ownership
# ---------------------------------------------------------------------------
class TestConfigApiRefusesManagedKeys(_ApiCase):

    def test_managed_keys_refused_before_any_write(self) -> None:
        self._as(DEMO_ADMIN)
        agent = self._agent()
        for key in ("COGNITO_CLIENT_SECRET_ARN", "AGENT_CONFIG_JSON", "LITELLM_VIRTUAL_KEY_ALIAS",
                    "LLM_PROVIDER_API_KEY_SECRET_ARN", "COGNITO_CLIENT_ID", "SOMETHING_SECRET_ARN",
                    "agent_config_json"):
            with self.subTest(key=key):
                resp = self.client.put(f"/api/agents/{agent.id}/config", json={"config": {key: "loom/mcp/1/oauth2-client-secret", "OK_KEY": "x"}})
                self.assertEqual(resp.status_code, 422, resp.text)
                self.assertIn(key, resp.json()["detail"])
        # Nothing was written, not even the harmless key in the same request.
        self.assertEqual(self.db.query(ConfigEntry).filter(ConfigEntry.agent_id == agent.id).count(), 0)

    def test_existing_secret_entries_refused(self) -> None:
        self._as(DEMO_ADMIN)
        agent = self._agent()
        self.db.add(ConfigEntry(agent_id=agent.id, key="CUSTOM_TOKEN", value="v", is_secret=True, source="secrets_manager"))
        self.db.commit()
        resp = self.client.put(f"/api/agents/{agent.id}/config", json={"config": {"CUSTOM_TOKEN": "other"}})
        self.assertEqual(resp.status_code, 422)

    def test_ordinary_keys_still_writable(self) -> None:
        self._as(DEMO_ADMIN)
        agent = self._agent()
        resp = self.client.put(f"/api/agents/{agent.id}/config", json={"config": {"LOG_LEVEL": "debug"}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual({e["key"]: e["value"] for e in resp.json()}["LOG_LEVEL"], "debug")


class TestDeleteOnlyTouchesOwnResources(_ApiCase):
    """Even if a foreign name reached the stored config (e.g. written before this fix)."""

    @patch("app.routers.agents.delete_secret")
    def test_foreign_cognito_secret_not_deleted(self, mock_delete: MagicMock) -> None:
        self._as(DEMO_ADMIN)
        agent = self._agent(config={"COGNITO_CLIENT_SECRET_ARN": "loom/mcp/1/oauth2-client-secret"})
        resp = self.client.delete(f"/api/agents/{agent.id}")
        self.assertEqual(resp.status_code, 200, resp.text)
        mock_delete.assert_not_called()

    @patch("app.routers.agents.delete_secret")
    def test_own_cognito_secret_still_deleted(self, mock_delete: MagicMock) -> None:
        self._as(DEMO_ADMIN)
        agent = self._agent()
        own = f"arn:aws:secretsmanager:us-east-1:123456789012:secret:loom/agents/{agent.id}/cognito-client-secret-AbCdEf"
        self.db.add(ConfigEntry(agent_id=agent.id, key="COGNITO_CLIENT_SECRET_ARN", value=own, is_secret=True, source="secrets_manager"))
        self.db.commit()
        resp = self.client.delete(f"/api/agents/{agent.id}")
        self.assertEqual(resp.status_code, 200, resp.text)
        mock_delete.assert_called_once_with(own, "us-east-1")

    @patch("app.services.litellm.revoke_virtual_key")
    @patch("app.routers.agents.delete_secret")
    def test_foreign_litellm_alias_not_revoked(self, _del: MagicMock, mock_revoke: MagicMock) -> None:
        self._as(DEMO_ADMIN)
        agent = self._agent(config={"LITELLM_VIRTUAL_KEY_ALIAS": "loom-agent-999"})
        self.client.delete(f"/api/agents/{agent.id}")
        mock_revoke.assert_not_called()


class TestOwnershipPredicates(unittest.TestCase):

    def _agent(self, agent_id: int, name: str) -> Agent:
        a = Agent(name=name)
        a.id = agent_id
        return a

    def test_agent_secret_namespace(self) -> None:
        a = self._agent(1, "bot")
        self.assertTrue(agents_router._owns_agent_secret(a, "loom/agents/1/cognito-client-secret"))
        self.assertTrue(agents_router._owns_agent_secret(
            a, "arn:aws:secretsmanager:us-east-1:123456789012:secret:loom/agents/1/cognito-client-secret-AbCdEf"))
        for ref in ("loom/agents/12/cognito-client-secret", "loom/mcp/1/oauth2-client-secret",
                    "loom/authorizers/x/client-secret", "", None):
            self.assertFalse(agents_router._owns_agent_secret(a, ref), ref)

    def test_credential_provider_names(self) -> None:
        a = self._agent(5, "team")
        for name in ("loom-team-5-mcp-github", "loom-team-5-a2a-helper", "loom-team-5-litellm-key"):
            self.assertTrue(agents_router._owns_credential_provider(a, name), name)
        for name in ("loom-team-50-mcp-github",       # another agent id
                     "loom-team-5-agent-12-mcp-x",     # agent named "team-5-agent", id 12
                     "loom-other-5-mcp-github",
                     "loom-team-mcp-github",            # pre-id naming scheme
                     "", None):
            self.assertFalse(agents_router._owns_credential_provider(a, name), name)


# ---------------------------------------------------------------------------
# 2. Authorizer secrets keyed on id, renames can't collide
# ---------------------------------------------------------------------------
class TestAuthorizerSecrets(_ApiCase):

    def setUp(self) -> None:
        super().setUp()
        self.store = patch("app.routers.security.store_secret", side_effect=lambda name, **kw: f"arn:secret:{name}").start()
        self.put = patch("app.routers.security.put_secret_value", side_effect=lambda sid, v, r: sid).start()
        self.addCleanup(patch.stopall)
        self.victim = AuthorizerConfig(name="victim-auth", authorizer_type="other",
                                       client_secret_arn="arn:secret:loom/authorizers/victim-auth/client-secret")
        self.victim.set_tags({"loom:group": "security"})
        self.mine = AuthorizerConfig(name="my-auth", authorizer_type="other",
                                     client_secret_arn="arn:secret:loom/authorizers/my-auth/client-secret")
        self.mine.set_tags({"loom:group": "security"})
        self.db.add_all([self.victim, self.mine])
        self.db.commit()

    def test_rename_onto_existing_name_is_refused_before_any_write(self) -> None:
        self._as(["t-admin", "g-admins-security"])
        resp = self.client.put(f"/api/security/authorizers/{self.mine.id}", json={"name": "victim-auth", "client_secret": "attacker"})
        self.assertEqual(resp.status_code, 409, resp.text)
        self.store.assert_not_called()
        self.put.assert_not_called()

    def test_secret_update_goes_to_own_stored_arn(self) -> None:
        self._as(["t-admin", "g-admins-security"])
        resp = self.client.put(f"/api/security/authorizers/{self.mine.id}", json={"name": "renamed", "client_secret": "new"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.put.assert_called_once()
        self.assertEqual(self.put.call_args.args[0], "arn:secret:loom/authorizers/my-auth/client-secret")
        self.store.assert_not_called()

    def test_new_secret_uses_id_keyed_name(self) -> None:
        self._as(["t-admin", "g-admins-security"])
        resp = self.client.post("/api/security/authorizers", json={
            "name": "fresh", "authorizer_type": "other", "client_secret": "s",
            "tags": {"loom:group": "security"},
        })
        self.assertEqual(resp.status_code, 201, resp.text)
        new_id = resp.json()["id"]
        self.assertEqual(self.store.call_args.kwargs["name"], f"loom/authorizer-secrets/{new_id}/client-secret")

    def test_names_with_slash_refused(self) -> None:
        self._as(["t-admin", "g-admins-security"])
        resp = self.client.post("/api/security/authorizers", json={
            "name": "victim-auth/x", "authorizer_type": "other", "tags": {"loom:group": "security"},
        })
        self.assertEqual(resp.status_code, 422)
        resp = self.client.put(f"/api/security/authorizers/{self.mine.id}", json={"name": "a/b"})
        self.assertEqual(resp.status_code, 422)

    def test_create_into_other_group_writes_no_secret(self) -> None:
        self._as(["t-admin", "g-admins-security"])
        resp = self.client.post("/api/security/authorizers", json={
            "name": "planted", "authorizer_type": "other", "client_secret": "s",
            "tags": {"loom:group": "demo"},
        })
        self.assertEqual(resp.status_code, 403, resp.text)
        self.store.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Group tag value must be the caller's
# ---------------------------------------------------------------------------
class TestRequireGroupTagOwnership(unittest.TestCase):

    def test_caller_group_tags(self) -> None:
        self.assertIsNone(caller_group_tags(_user(SUPER)))
        self.assertEqual(caller_group_tags(_user(DEMO_ADMIN)), ["demo"])
        self.assertEqual(sorted(caller_group_tags(_user(["t-user", "g-users-a", "g-users-b"]))), ["a", "b"])

    def test_admin_cannot_assign_another_group(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            require_group_tag({"loom:group": "test"}, "MCP server", user=_user(DEMO_ADMIN))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(require_group_tag({"loom:group": "demo"}, "MCP server", user=_user(DEMO_ADMIN)),
                         {"loom:group": "demo"})

    def test_super_admin_may_assign_any_group(self) -> None:
        self.assertEqual(require_group_tag({"loom:group": "test"}, "MCP server", user=_user(SUPER)),
                         {"loom:group": "test"})

    def test_caller_is_required(self) -> None:
        with self.assertRaises(TypeError):
            require_group_tag({"loom:group": "demo"}, "agent")  # type: ignore[call-arg]


class TestRedeployTags(unittest.TestCase):

    def test_redeploy_cannot_move_agent_into_another_group(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            agents_router._redeploy_tags({"loom:group": "test"}, _user(DEMO_ADMIN))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_redeploy_without_tags_keeps_current_ones(self) -> None:
        self.assertIsNone(agents_router._redeploy_tags(None, _user(DEMO_ADMIN)))
        self.assertEqual(agents_router._redeploy_tags({"loom:group": "demo"}, _user(DEMO_ADMIN)), {"loom:group": "demo"})


class TestConnectorPlanting(_ApiCase):

    def test_mcp_server_cannot_be_planted_in_another_group(self) -> None:
        self._as(DEMO_ADMIN)
        resp = self.client.post("/api/mcp/servers", json={
            "name": "evil-connector", "endpoint_url": "https://evil.example/mcp",
            "transport_type": "streamable_http", "auth_type": "none", "tags": {"loom:group": "test"},
        })
        self.assertEqual(resp.status_code, 403, resp.text)
        ok = self.client.post("/api/mcp/servers", json={
            "name": "own-connector", "endpoint_url": "https://ok.example/mcp",
            "transport_type": "streamable_http", "auth_type": "none", "tags": {"loom:group": "demo"},
        })
        self.assertEqual(ok.status_code, 201, ok.text)

    def test_mcp_server_cannot_be_retagged_into_another_group(self) -> None:
        self._as(DEMO_ADMIN)
        created = self.client.post("/api/mcp/servers", json={
            "name": "mine", "endpoint_url": "https://ok.example/mcp",
            "transport_type": "streamable_http", "auth_type": "none", "tags": {"loom:group": "demo"},
        }).json()
        resp = self.client.put(f"/api/mcp/servers/{created['id']}", json={"tags": {"loom:group": "test"}})
        self.assertEqual(resp.status_code, 403, resp.text)

    @patch("app.services.a2a.guarded_get")
    def test_a2a_agent_cannot_be_planted_in_another_group(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {
            "name": "evil", "description": "d", "url": "https://evil.example", "version": "1",
            "capabilities": {}, "skills": [], "defaultInputModes": ["text"], "defaultOutputModes": ["text"],
        }, raise_for_status=lambda: None)
        self._as(DEMO_ADMIN)
        resp = self.client.post("/api/a2a/agents", json={
            "base_url": "https://evil.example", "auth_type": "none", "tags": {"loom:group": "test"},
        })
        self.assertEqual(resp.status_code, 403, resp.text)


if __name__ == "__main__":
    unittest.main()
