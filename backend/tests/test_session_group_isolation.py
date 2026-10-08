"""Conversation reads must respect loom:group and session ownership.

`GET /api/agents/{id}` already returned 403 for an agent outside the caller's
group, but the session and invocation readers never got the same check — so the
agent was 403 and its chats were 200. `list_sessions` loaded the Agent by ID
with no check and, for any `t-admin`, returned every conversation on it;
`get_session` and `get_invocation` resolved by session UUID with no group check
*and* no owner filter, so any holder of `agent:read` could read any
conversation anywhere. `GET /api/settings/approvals/logs?agent_id=` returned
`tool_input_summary` the same way, keyed on a sequential integer.

The data at risk is `prompt_text`, `thinking_text`, `response_text` and
`tool_input_summary` — the actual content of conversations.
"""
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.models.agent import Agent
from app.models.approval_log import ApprovalLog
from app.models.invocation import Invocation
from app.models.session import InvocationSession

WITNESS = "LOOM-SESSION-ISOLATION-WITNESS"


class TestSessionReadsRespectGroupAndOwner(unittest.TestCase):
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

        # An agent owned by the "mcp" group, with a conversation on it.
        self.agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/victim",
            runtime_id="victim", name="victim_agent", status="READY",
            region="us-east-1", account_id="123456789012",
        )
        self.agent.set_tags({"loom:group": "mcp"})
        self.db.add(self.agent)
        self.db.commit()
        self.db.refresh(self.agent)

        self.session_id = "11111111-2222-3333-4444-555555555555"
        self.db.add(InvocationSession(
            agent_id=self.agent.id, session_id=self.session_id,
            qualifier="DEFAULT", status="complete", user_id="victim@example.com",
        ))
        self.db.add(Invocation(
            session_id=self.session_id, invocation_id="inv-1", status="complete",
            prompt_text=WITNESS, response_text=WITNESS,
        ))
        self.db.add(ApprovalLog(
            request_id="req-1", session_id=self.session_id, agent_id=self.agent.id,
            tool_name="delete_user_data", tool_input_summary=WITNESS,
            policy_name="delete_*", pattern_type="loop_hook", status="approved",
        ))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()
        # The in-memory database is shared for the class, so reset the schema
        # rather than let rows (and the unique agent ARN) leak between tests.
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        app.dependency_overrides.clear()

    def _as(self, groups: list[str]) -> None:
        user = UserInfo(sub="u", username="attacker@example.com", groups=groups,
                        scopes=derive_scopes(groups))
        app.dependency_overrides[get_current_user] = lambda: user

    # -- a group admin for a *different* group --

    def test_other_group_admin_cannot_list_sessions(self) -> None:
        """The reported path: the agent GET is 403, so the chats must be too."""
        self._as(["t-admin", "g-admins-demo"])
        self.assertEqual(self.client.get(f"/api/agents/{self.agent.id}").status_code, 403)
        resp = self.client.get(f"/api/agents/{self.agent.id}/sessions")
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_other_group_admin_cannot_read_session_by_uuid(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/agents/{self.agent.id}/sessions/{self.session_id}")
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_other_group_admin_cannot_read_invocation(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.get(
            f"/api/agents/{self.agent.id}/sessions/{self.session_id}/invocations/inv-1"
        )
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_other_group_admin_cannot_read_approval_logs(self) -> None:
        """tool_input_summary is conversation content, and agent_id is a
        sequential integer, so this one needs no UUID to enumerate."""
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.get(f"/api/settings/approvals/logs?agent_id={self.agent.id}")
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(WITNESS, resp.text)

    def test_unfiltered_approval_logs_exclude_other_groups(self) -> None:
        """Omitting agent_id must not fall back to returning everything."""
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.get("/api/settings/approvals/logs")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(WITNESS, resp.text)

    # -- an ordinary user, who is not an admin at all --

    def test_non_admin_user_cannot_read_another_users_session(self) -> None:
        """get_session and get_invocation had no owner filter at all, so this
        was reachable by a plain user, not just an admin."""
        self._as(["t-user", "g-users-mcp"])  # same group name, still not the owner
        resp = self.client.get(f"/api/agents/{self.agent.id}/sessions/{self.session_id}")
        self.assertIn(resp.status_code, (403, 404))
        self.assertNotIn(WITNESS, resp.text)

    # -- positive controls: the right people still get through --

    def test_owning_group_admin_can_read_the_conversation(self) -> None:
        self._as(["t-admin", "g-admins-super"])
        resp = self.client.get(f"/api/agents/{self.agent.id}/sessions/{self.session_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(WITNESS, resp.text)

    def test_super_admin_sees_approval_logs(self) -> None:
        self._as(["t-admin", "g-admins-super"])
        resp = self.client.get(f"/api/settings/approvals/logs?agent_id={self.agent.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(WITNESS, resp.text)


if __name__ == "__main__":
    unittest.main()
