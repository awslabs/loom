"""Group-isolation follow-ups reported against v1.9.0 / v1.10.3.

One test class per finding; the agent-side findings (ADK A2A approval, code
interpreter rule names, WebSocket approval handling in the agents) are tested
in agents/*/tests. Each class includes a positive control where it matters, so
a refusal can only come from the rule under test.

1. IdP issuer swap kept super-admin mappings and the confidential client secret.
2. Per-user MCP API keys followed an endpoint_url move.
3. Logs, traces and the eval exchange skipped the session-owner check.
4. registry:write could rewrite a skill attached to another group's agent.
5. WebSocket invoke omitted approval policies (backend half).
8. A legacy-row OAuth secret followed a URL move when has_oauth2_secret wasn't "true".
9. Harness code interpreter names could collide with, adopt and delete another group's.
"""
import ast
import asyncio
import json
import pathlib
import re
import unittest
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.main import app
from app.models.a2a import A2aAgent
from app.models.agent import Agent
from app.models.approval_policy import ApprovalPolicy
from app.models.identity_provider import IdentityProvider
from app.models.integration import Integration
from app.models.mcp import McpServer
from app.models.session import InvocationSession
from app.services.mcp import resolve_api_key, resolve_oauth2_client_secret, user_api_key_secret_name

SUPER = ["t-admin", "g-admins-super"]
DEMO_ADMIN = ["t-admin", "g-admins-demo"]
SECURITY_ADMIN = ["t-admin", "g-admins-security"]
DEMO_USER = ["t-user", "g-users-demo"]

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


def _user(groups: list[str], username: str = "alice@example.com") -> UserInfo:
    return UserInfo(sub=f"sub-{username}", username=username, groups=groups, scopes=derive_scopes(groups))


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

    def _as(self, groups: list[str], username: str = "alice@example.com") -> None:
        user = _user(groups, username)
        app.dependency_overrides[get_current_user] = lambda: user

    def _agent(self, name: str = "demo_bot", group: str = "demo") -> Agent:
        agent = Agent(
            arn=f"arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/{name}-abc1234567",
            runtime_id=f"{name}-abc1234567", name=name, status="READY", region="us-east-1",
            account_id="123456789012", source="deploy", registered_at=datetime.utcnow(),
        )
        agent.set_tags({"loom:group": group})
        agent.set_available_qualifiers(["DEFAULT"])
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent


# ---------------------------------------------------------------------------
# 1. IdP issuer swap
# ---------------------------------------------------------------------------

_DISCOVERY = {
    "jwks_uri": "https://new.example.com/jwks",
    "authorization_endpoint": "https://new.example.com/authorize",
    "token_endpoint": "https://new.example.com/token",
}


class TestIdpIssuerSwap(_ApiCase):
    def _idp(self, mappings: dict[str, list[str]], secret: bool = True) -> IdentityProvider:
        idp = IdentityProvider(
            name="corp-sso", provider_type="okta", issuer_url="https://old.example.com",
            client_id="cid", client_type="confidential", status="active",
            client_secret_arn="arn:aws:secretsmanager:us-east-1:1:secret:loom/identity-providers/corp-sso/client-secret" if secret else None,
            token_endpoint="https://old.example.com/token",
        )
        idp.set_group_mappings(mappings)
        self.db.add(idp)
        self.db.commit()
        self.db.refresh(idp)
        return idp

    def _put(self, idp_id: int, body: dict[str, Any]):
        with patch("app.routers.identity_providers.fetch_discovery", return_value=_DISCOVERY), \
                patch("app.routers.identity_providers.delete_secret") as delete_secret, \
                patch("app.routers.identity_providers.store_secret", return_value="arn:new") as store_secret:
            resp = self.client.put(f"/api/settings/identity-providers/{idp_id}", json=body)
        return resp, delete_secret, store_secret

    def test_issuer_only_change_cannot_keep_a_super_admin_mapping(self) -> None:
        idp = self._idp({"Admins": ["t-admin", "g-admins-super"]})
        self._as(SECURITY_ADMIN)
        resp, delete_secret, _ = self._put(idp.id, {"issuer_url": "https://attacker.example.com"})
        self.assertEqual(resp.status_code, 403, resp.text)
        self.db.refresh(idp)
        self.assertEqual(idp.issuer_url, "https://old.example.com")
        self.assertIsNotNone(idp.client_secret_arn)
        delete_secret.assert_not_called()

    def test_group_claim_change_cannot_rebind_a_super_admin_mapping(self) -> None:
        # The stored table maps "Admins" to super-admin; pointing group_claim_path
        # at a claim the caller controls (an app role, a profile field) would hand
        # that mapping to whoever can put "Admins" in it.
        idp = self._idp({"Admins": ["t-admin", "g-admins-super"]})
        self._as(SECURITY_ADMIN)
        resp, _, _ = self._put(idp.id, {"group_claim_path": "roles"})
        self.assertEqual(resp.status_code, 403, resp.text)
        self.db.refresh(idp)
        self.assertIsNone(idp.group_claim_path)

    def test_issuer_change_clears_the_client_secret(self) -> None:
        idp = self._idp({"Users": ["t-user"]})
        self._as(SECURITY_ADMIN)
        resp, delete_secret, _ = self._put(idp.id, {"issuer_url": "https://new.example.com"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.db.refresh(idp)
        self.assertIsNone(idp.client_secret_arn)
        self.assertEqual(idp.token_endpoint, "https://new.example.com/token")
        delete_secret.assert_called_once()

    def test_new_secret_in_the_same_request_is_kept(self) -> None:
        idp = self._idp({"Users": ["t-user"]})
        self._as(SECURITY_ADMIN)
        resp, delete_secret, store_secret = self._put(
            idp.id, {"issuer_url": "https://new.example.com", "client_secret": "new-secret"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.db.refresh(idp)
        self.assertEqual(idp.client_secret_arn, "arn:new")
        delete_secret.assert_not_called()
        store_secret.assert_called_once()

    def test_super_admin_may_move_an_idp_with_super_admin_mappings(self) -> None:
        idp = self._idp({"Admins": ["t-admin", "g-admins-super"]})
        self._as(SUPER)
        resp, _, _ = self._put(idp.id, {"issuer_url": "https://new.example.com"})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_unchanged_issuer_keeps_the_secret(self) -> None:
        idp = self._idp({"Admins": ["t-admin", "g-admins-super"]})
        self._as(SECURITY_ADMIN)
        resp, delete_secret, _ = self._put(idp.id, {"issuer_url": "https://old.example.com", "scopes": "openid"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.db.refresh(idp)
        self.assertIsNotNone(idp.client_secret_arn)
        delete_secret.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Per-user MCP keys and an endpoint move
# ---------------------------------------------------------------------------

class TestPerUserMcpKeysDoNotFollowAMove(_ApiCase):
    def _server(self, epoch: int | None = 1, name: str = "tools") -> McpServer:
        server = McpServer(
            name=name, endpoint_url="https://old.example.com/mcp", transport_type="streamable_http",
            auth_type="api_key", status="active",
        )
        server.set_tags({"loom:group": "demo"})
        self.db.add(server)
        self.db.commit()
        server.user_key_epoch = epoch
        self.db.commit()
        self.db.refresh(server)
        return server

    def _put(self, server_id: int, body: dict[str, Any]):
        with patch("app.routers.mcp.delete_secret"), patch("app.routers.mcp.store_secret"):
            return self.client.put(f"/api/mcp/servers/{server_id}", json=body)

    def test_new_servers_start_on_the_id_keyed_path(self) -> None:
        server = McpServer(name="fresh", endpoint_url="https://h/mcp", transport_type="sse", auth_type="api_key")
        server.set_tags({"loom:group": "demo"})
        self.db.add(server)
        self.db.commit()
        self.assertEqual(server.user_key_epoch, 1)
        self.assertEqual(user_api_key_secret_name(server, "s"), f"loom/mcp/{server.id}/user-api-key/e1/s")

    def test_endpoint_move_points_every_reader_at_a_new_namespace(self) -> None:
        server = self._server(epoch=1)
        before = user_api_key_secret_name(server, "bob")
        self._as(DEMO_ADMIN)
        resp = self._put(server.id, {"endpoint_url": "https://attacker.example.com/mcp"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.db.refresh(server)
        self.assertEqual(server.user_key_epoch, 2)
        after = user_api_key_secret_name(server, "bob")
        self.assertNotEqual(before, after)
        # The invoke-time resolver reads the new location, not the old key.
        with patch("app.services.mcp.get_secret", side_effect=Exception("absent")) as get_secret:
            self.assertIsNone(resolve_api_key(server, user_sub="bob"))
        get_secret.assert_called_once_with(after, "us-east-1")

    def test_legacy_server_leaves_the_name_keyed_path_on_a_move(self) -> None:
        server = self._server(epoch=None)
        self.assertEqual(user_api_key_secret_name(server, "bob"), "loom/mcp/tools/api-key/bob")
        self._as(DEMO_ADMIN)
        self.assertEqual(self._put(server.id, {"endpoint_url": "https://new.example.com/mcp"}).status_code, 200)
        self.db.refresh(server)
        self.assertEqual(user_api_key_secret_name(server, "bob"), f"loom/mcp/{server.id}/user-api-key/e1/bob")

    def test_rename_also_leaves_the_old_namespace(self) -> None:
        server = self._server(epoch=None)
        self._as(DEMO_ADMIN)
        self.assertEqual(self._put(server.id, {"name": "tools2"}).status_code, 200)
        self.db.refresh(server)
        self.assertNotIn("/api-key/", user_api_key_secret_name(server, "bob").replace("user-api-key", ""))

    def test_unrelated_update_keeps_the_keys(self) -> None:
        server = self._server(epoch=1)
        self._as(DEMO_ADMIN)
        self.assertEqual(self._put(server.id, {"description": "x"}).status_code, 200)
        self.db.refresh(server)
        self.assertEqual(server.user_key_epoch, 1)

    def test_deploy_embeds_the_same_path_the_backend_reads(self) -> None:
        source = (APP_DIR / "routers" / "agents.py").read_text()
        self.assertNotIn('user_api_key_secret_name(server["name"]', source)
        self.assertEqual(source.count('"user_api_key_path": user_api_key_secret_name('), 4)


# ---------------------------------------------------------------------------
# 3. Session owner on logs, traces and the eval exchange
# ---------------------------------------------------------------------------

def _otel_event(trace_id: str, session_id: str, body: dict | None = None) -> dict:
    record = {
        "traceId": trace_id, "spanId": "span-1", "observedTimeUnixNano": 1_000_000_000_000_000_000,
        "timeUnixNano": 1_000_000_000_000_000_000, "severityNumber": 9, "severityText": "",
        "scope": {"name": "strands.telemetry.tracer"}, "body": body or {},
        "attributes": {"event.name": "strands.telemetry.tracer", "session.id": session_id},
        "resource": {"attributes": {"service.name": "demo_bot.DEFAULT"}}, "flags": 1,
    }
    return {"timestamp": 1_000_000_000_000, "message": json.dumps(record)}


TRACE_ID = "0123456789abcdef0123456789abcdef"


class TestSessionOwnerOnLogsAndTraces(_ApiCase):
    def setUp(self) -> None:
        super().setUp()
        self.agent = self._agent()
        self.db.add(InvocationSession(agent_id=self.agent.id, session_id="bob-sess", qualifier="DEFAULT",
                                      user_id="bob@example.com"))
        self.db.add(InvocationSession(agent_id=self.agent.id, session_id="alice-sess", qualifier="DEFAULT",
                                      user_id="alice@example.com"))
        self.db.commit()

    def test_session_logs_follow_the_owner_rule(self) -> None:
        self._as(DEMO_USER)
        with patch("app.routers.logs.get_log_events", return_value=[]):
            other = self.client.get(f"/api/agents/{self.agent.id}/sessions/bob-sess/logs")
            own = self.client.get(f"/api/agents/{self.agent.id}/sessions/alice-sess/logs")
        self.assertEqual(other.status_code, 403, other.text)
        self.assertEqual(own.status_code, 200, own.text)

    def test_session_traces_follow_the_owner_rule(self) -> None:
        self._as(DEMO_USER)
        with patch("app.routers.traces.fetch_otel_events", return_value=[]):
            other = self.client.get(f"/api/agents/{self.agent.id}/sessions/bob-sess/traces")
            own = self.client.get(f"/api/agents/{self.agent.id}/sessions/alice-sess/traces")
        self.assertEqual(other.status_code, 403, other.text)
        self.assertEqual(own.status_code, 200, own.text)

    def test_trace_detail_is_checked_against_the_traces_session(self) -> None:
        self._as(DEMO_USER)
        for session_id, expected in (("bob-sess", 403), ("alice-sess", 200), ("unknown-sess", 403)):
            with self.subTest(session_id=session_id), \
                    patch("app.routers.traces.fetch_otel_events", return_value=[_otel_event(TRACE_ID, session_id)]):
                resp = self.client.get(f"/api/agents/{self.agent.id}/traces/{TRACE_ID}")
                self.assertEqual(resp.status_code, expected, resp.text)

    def test_eval_exchange_is_checked_against_the_traces_session(self) -> None:
        body = {"input": {"messages": [{"role": "user", "content": [{"text": "secret question"}]}]}}
        self._as(DEMO_USER)
        for session_id, expected in (("bob-sess", 403), ("alice-sess", 200)):
            with self.subTest(session_id=session_id), \
                    patch("app.routers.evaluations.fetch_otel_events",
                          return_value=[_otel_event(TRACE_ID, session_id, body)]):
                resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/traces/{TRACE_ID}/exchange")
                self.assertEqual(resp.status_code, expected, resp.text)
                if expected == 403:
                    self.assertNotIn("secret question", resp.text)

    def test_eval_exchange_needs_session_read(self) -> None:
        # agent:read used to be enough; g-admins-registry holds neither scope,
        # so use a user with agent:read only.
        user = UserInfo(sub="s", username="carol@example.com", groups=["t-user", "g-users-demo"],
                        scopes={"agent:read"})
        app.dependency_overrides[get_current_user] = lambda: user
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/traces/{TRACE_ID}/exchange")
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_agent_wide_logs_are_admin_only(self) -> None:
        with patch("app.routers.logs.list_log_streams", return_value=[{"name": "s", "last_event_time": 1}]), \
                patch("app.routers.logs.get_stream_log_events", return_value=[]):
            self._as(DEMO_USER)
            user_resp = self.client.get(f"/api/agents/{self.agent.id}/logs")
            self._as(DEMO_ADMIN)
            admin_resp = self.client.get(f"/api/agents/{self.agent.id}/logs")
        self.assertEqual(user_resp.status_code, 403, user_resp.text)
        self.assertEqual(admin_resp.status_code, 200, admin_resp.text)

    def test_vended_logs_are_admin_only(self) -> None:
        self._as(DEMO_USER)
        resp = self.client.get(f"/api/agents/{self.agent.id}/logs/vended",
                               params={"log_group": "g", "stream": "s"})
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertIn("other users", resp.json()["detail"])


# ---------------------------------------------------------------------------
# 4. Skill records attached to another group's agent
# ---------------------------------------------------------------------------

class TestSkillWritesNeedEveryDependentAgent(_ApiCase):
    RECORD = "rec-skill-1"

    def _attach(self, agent: Agent, enabled: bool = True) -> None:
        self.db.add(Integration(agent_id=agent.id, integration_type="skill", enabled=enabled,
                                integration_config=json.dumps({"record_id": self.RECORD})))
        self.db.commit()

    def _approve(self):
        client = MagicMock()
        client.approve_record.return_value = None
        with patch("app.routers.registry.get_registry_client", return_value=client):
            resp = self.client.post(f"/api/registry/records/{self.RECORD}/approve", json={"reason": "ok"})
        return resp, client

    def test_cannot_approve_a_skill_another_groups_agent_uses(self) -> None:
        self._attach(self._agent(name="victim_bot", group="strategics"))
        self._as(DEMO_ADMIN)
        resp, client = self._approve()
        self.assertEqual(resp.status_code, 403, resp.text)
        client.approve_record.assert_not_called()

    def test_disabled_attachment_still_counts(self) -> None:
        self._attach(self._agent(name="victim_bot", group="strategics"), enabled=False)
        self._as(DEMO_ADMIN)
        resp, client = self._approve()
        self.assertEqual(resp.status_code, 403, resp.text)
        client.approve_record.assert_not_called()

    def test_skill_used_only_by_own_group_is_writable(self) -> None:
        self._attach(self._agent(name="own_bot", group="demo"))
        self._as(DEMO_ADMIN)
        resp, client = self._approve()
        self.assertEqual(resp.status_code, 200, resp.text)
        client.approve_record.assert_called_once()

    def test_unattached_skill_is_writable(self) -> None:
        self._as(DEMO_ADMIN)
        resp, client = self._approve()
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_update_delete_submit_reject_are_guarded_too(self) -> None:
        self._attach(self._agent(name="victim_bot", group="strategics"))
        self._as(DEMO_ADMIN)
        client = MagicMock()
        with patch("app.routers.registry.get_registry_client", return_value=client):
            calls = [
                self.client.put(f"/api/registry/records/{self.RECORD}", json={"skill_md": "# planted"}),
                self.client.delete(f"/api/registry/records/{self.RECORD}"),
                self.client.post(f"/api/registry/records/{self.RECORD}/submit"),
                self.client.post(f"/api/registry/records/{self.RECORD}/reject", json={"reason": "x"}),
            ]
        for resp in calls:
            with self.subTest(url=str(resp.url)):
                self.assertEqual(resp.status_code, 403, resp.text)
        for method in ("update_record", "delete_record", "submit_for_approval", "reject_record"):
            getattr(client, method).assert_not_called()


# ---------------------------------------------------------------------------
# 5. WebSocket invoke carries approval policies (backend half)
# ---------------------------------------------------------------------------

class TestWebSocketInvokeSendsApprovalPolicies(_ApiCase):
    def test_loader_returns_enabled_policies_only(self) -> None:
        from app.routers.invocations import _active_approval_policies
        self.db.add(ApprovalPolicy(name="on", policy_type="loop_hook", tool_match_rules=json.dumps(["*"]), enabled=True))
        self.db.add(ApprovalPolicy(name="off", policy_type="loop_hook", tool_match_rules=json.dumps(["*"]), enabled=False))
        self.db.commit()
        self.assertEqual([p["name"] for p in _active_approval_policies(self.db)], ["on"])

    def _sent_payload(self, policies: list[dict[str, Any]] | None) -> dict[str, Any]:
        from app.services.agentcore import invoke_agent_ws

        sent: list[str] = []

        class _FakeWs:
            async def send(self, msg: str) -> None:
                sent.append(msg)

            async def recv(self) -> str:
                return json.dumps({"type": "result", "content": "ok"})

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

        async def _drain() -> None:
            gen = invoke_agent_ws(
                arn="arn:aws:bedrock-agentcore:us-east-1:1:runtime/x", qualifier="DEFAULT",
                session_id="s", prompt="p", region="us-east-1", approval_policies=policies,
            )
            async for _ in gen:
                pass

        with patch("websockets.connect", return_value=_FakeWs()):
            asyncio.run(_drain())
        return json.loads(sent[0])

    def test_policies_reach_the_socket_payload(self) -> None:
        policy = {"name": "gate", "tool_match_rules": ["*"], "enabled": True}
        self.assertEqual(self._sent_payload([policy])["approval_policies"], [policy])

    def test_empty_set_is_sent_explicitly(self) -> None:
        self.assertEqual(self._sent_payload(None)["approval_policies"], [])

    def test_ws_route_passes_the_loaded_policies(self) -> None:
        tree = ast.parse((APP_DIR / "routers" / "invocations.py").read_text())
        ws_route = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.AsyncFunctionDef) and n.name == "invoke_agent_websocket")
        calls = [n for n in ast.walk(ws_route) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "invoke_agent_ws"]
        self.assertEqual(len(calls), 1)
        self.assertIn("approval_policies", {kw.arg for kw in calls[0].keywords})


# ---------------------------------------------------------------------------
# 8. Legacy-row OAuth secret on a URL move
# ---------------------------------------------------------------------------

class TestLegacyOauthSecretDoesNotFollowAMove(_ApiCase):
    def test_mcp_legacy_plaintext_secret_is_cleared(self) -> None:
        server = McpServer(name="legacy", endpoint_url="https://old.example.com/mcp", transport_type="sse",
                           auth_type="oauth2", oauth2_client_secret="plaintext", has_oauth2_secret=None)
        server.set_tags({"loom:group": "demo"})
        self.db.add(server)
        self.db.commit()
        self._as(DEMO_ADMIN)
        with patch("app.routers.mcp.delete_secret") as delete_secret, patch("app.routers.mcp.store_secret"):
            resp = self.client.put(f"/api/mcp/servers/{server.id}",
                                   json={"endpoint_url": "https://attacker.example.com/mcp"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.db.refresh(server)
        self.assertIsNone(server.oauth2_client_secret)
        self.assertEqual(server.has_oauth2_secret, "false")
        delete_secret.assert_called()

    def test_a2a_legacy_plaintext_secret_is_cleared(self) -> None:
        agent = A2aAgent(base_url="https://old.example.com", name="partner", description="d", agent_version="1",
                         oauth2_client_secret="plaintext", has_oauth2_secret=None)
        agent.set_tags({"loom:group": "demo"})
        self.db.add(agent)
        self.db.commit()
        self._as(DEMO_ADMIN)
        with patch("app.routers.a2a.delete_secret") as delete_secret, patch("app.routers.a2a.store_secret"):
            resp = self.client.put(f"/api/a2a/agents/{agent.id}", json={"base_url": "https://attacker.example.com"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.db.refresh(agent)
        self.assertIsNone(agent.oauth2_client_secret)
        self.assertEqual(agent.has_oauth2_secret, "false")
        delete_secret.assert_called()

    def test_unmoved_legacy_row_keeps_its_secret(self) -> None:
        server = McpServer(name="legacy", endpoint_url="https://old.example.com/mcp", transport_type="sse",
                           auth_type="oauth2", oauth2_client_secret="plaintext", has_oauth2_secret=None)
        server.set_tags({"loom:group": "demo"})
        self.db.add(server)
        self.db.commit()
        self._as(DEMO_ADMIN)
        with patch("app.routers.mcp.delete_secret") as delete_secret, patch("app.routers.mcp.store_secret"):
            resp = self.client.put(f"/api/mcp/servers/{server.id}", json={"description": "x"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.db.refresh(server)
        self.assertEqual(server.oauth2_client_secret, "plaintext")
        delete_secret.assert_not_called()

    def test_cleared_flag_ignores_a_secret_still_cached_by_another_task(self) -> None:
        """After a move the row says has_oauth2_secret="false", but another
        task's get_secret cache can still hold the old value for five minutes.
        The resolver must take the row's word for it."""
        moved = [
            McpServer(id=41, name="moved", endpoint_url="https://attacker.example.com/mcp", transport_type="sse",
                      auth_type="oauth2", oauth2_client_secret=None, has_oauth2_secret="false"),
            A2aAgent(id=42, base_url="https://attacker.example.com", name="moved", description="d",
                     agent_version="1", auth_type="oauth2", oauth2_client_secret=None, has_oauth2_secret="false"),
        ]
        for row in moved:
            with patch("app.services.mcp.get_secret", return_value="CACHED-OLD-SECRET") as get_secret:
                self.assertIsNone(resolve_oauth2_client_secret(row))
            get_secret.assert_not_called()
        # Positive control: a flagged row still reads Secrets Manager.
        current = McpServer(id=43, name="current", endpoint_url="https://old.example.com/mcp", transport_type="sse",
                            auth_type="oauth2", has_oauth2_secret="true")
        with patch("app.services.mcp.get_secret", return_value="CURRENT-SECRET"):
            self.assertEqual(resolve_oauth2_client_secret(current), "CURRENT-SECRET")


# ---------------------------------------------------------------------------
# 9. Harness code interpreter names
# ---------------------------------------------------------------------------

class TestCodeInterpreterNamesAreNeverAdopted(unittest.TestCase):
    def test_names_are_unique_and_valid(self) -> None:
        from app.routers.agents import _new_code_interpreter_name
        names = {_new_code_interpreter_name("victim_code_interpreter") for _ in range(50)}
        self.assertEqual(len(names), 50)
        for name in names | {_new_code_interpreter_name("x" * 200), _new_code_interpreter_name("a-b.c d")}:
            self.assertRegex(name, r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$")
            self.assertTrue(name.startswith("loom_ci_"))
        self.assertTrue(next(iter(names)).startswith("loom_ci_victim_"))

    def test_no_code_path_finds_an_interpreter_by_name(self) -> None:
        """Adopt-by-name (create) and delete-by-name (cleanup) both went through
        list_code_interpreters; an agent may only touch the id it recorded."""
        source = (APP_DIR / "routers" / "agents.py").read_text()
        self.assertNotIn("list_code_interpreters", source)
        self.assertIsNone(re.search(r'f"loom_ci_\{base_name', source))


if __name__ == "__main__":
    unittest.main()
