"""The invoke WebSocket must authenticate like the HTTP invoke route.

`WS /api/agents/{id}/ws` used to call accept() and then serve invocations with
no authentication at all (CWE-306): no identity, no `invoke` scope check, and
no `loom:group` check, while `POST /api/agents/{id}/invoke` beside it required
all three. Anyone able to reach the socket got a `session_start`, could probe
which agent IDs existed, and — with a runtime bearer of their own — could drive
an agent with no Loom session and no group check.

These tests pin the three gates and the ordering: nothing may be emitted and no
agent may be looked up before the caller is authenticated.
"""
import unittest
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.db import SessionLocal
from app.dependencies.auth import UserInfo, derive_scopes
from app.models.agent import Agent


@pytest.fixture(autouse=True)
def _default_auth_bypass():
    """Override the suite-wide auto-bypass fixture.

    It sets LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV and forces the loopback check,
    which would authenticate the very requests this module asserts are
    rejected — the bypass would hand them super-admin.
    """
    yield


def _user(groups: list[str]) -> UserInfo:
    return UserInfo(sub="u", username="u", groups=groups, scopes=derive_scopes(groups))


class TestInvokeWebsocketRequiresAuth(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        # The handler builds its own SessionLocal rather than taking get_db, so
        # the agent has to exist in the app's own (throwaway) database.
        self.db = SessionLocal()
        self.agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/ws-test",
            runtime_id="ws-test",
            name="ws_test_agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
        )
        self.agent.set_tags({"loom:group": "demo"})
        self.db.add(self.agent)
        self.db.commit()
        self.db.refresh(self.agent)
        self.agent_id = self.agent.id

    def tearDown(self) -> None:
        self.db.query(Agent).filter(Agent.id == self.agent_id).delete()
        self.db.commit()
        self.db.close()
        app.dependency_overrides.clear()

    def _frames_until_close(self, agent_id: int, message: dict, max_frames: int = 8) -> list[dict]:
        """Send one frame and collect replies until the server closes.

        Only safe for the rejection paths, where the server does close. On an
        authorized invocation it stays open waiting for the next prompt, so
        receive_json() would block forever — use _frames_until() for that.
        """
        received: list[dict] = []
        with self.client.websocket_connect(f"/api/agents/{agent_id}/ws") as ws:
            ws.send_json(message)
            try:
                for _ in range(max_frames):
                    received.append(ws.receive_json())
            except (WebSocketDisconnect, RuntimeError):
                pass
        return received

    def _frames_until(self, agent_id: int, message: dict, frame_type: str,
                      max_frames: int = 4) -> list[dict]:
        """Send one frame and read only until `frame_type` arrives.

        The server keeps an authorized socket open for further prompts, so the
        test has to stop reading once it has seen what it came for.
        """
        received: list[dict] = []
        with self.client.websocket_connect(f"/api/agents/{agent_id}/ws") as ws:
            ws.send_json(message)
            try:
                for _ in range(max_frames):
                    frame = ws.receive_json()
                    received.append(frame)
                    if frame.get("type") == frame_type:
                        break
            except (WebSocketDisconnect, RuntimeError):
                pass
        return received

    def test_unauthenticated_prompt_is_rejected_without_session_start(self) -> None:
        """No token, no IdP configured, bypass off: the socket must close."""
        frames = self._frames_until_close(self.agent_id, {"type": "prompt", "prompt": "hi"})

        self.assertTrue(any(f.get("type") == "error" for f in frames), frames)
        # The critical assertion: the caller never reaches an invocation.
        self.assertFalse(
            any(f.get("type") == "session_start" for f in frames),
            f"session_start emitted to an unauthenticated caller: {frames}",
        )

    def test_unauthenticated_caller_cannot_probe_agent_existence(self) -> None:
        """Authentication happens before the agent lookup, so the "not found"
        reply can't be used to enumerate agent IDs."""
        frames = self._frames_until_close(999999, {"type": "prompt", "prompt": "hi"})

        joined = " ".join(str(f.get("content", "")) for f in frames)
        self.assertNotIn("not found", joined.lower(), frames)
        self.assertFalse(any(f.get("type") == "session_start" for f in frames), frames)

    @patch("app.routers.invocations.authenticate_bearer_token")
    def test_token_without_invoke_scope_is_rejected(self, mock_auth) -> None:
        """A valid Loom session is not enough — the HTTP route requires the
        invoke scope, so this one must too."""
        mock_auth.return_value = _user(["t-user"])  # no invoke scope

        frames = self._frames_until_close(
            self.agent_id, {"type": "prompt", "prompt": "hi", "token": "valid"}
        )

        self.assertTrue(any("invoke" in str(f.get("content", "")) for f in frames), frames)
        self.assertFalse(any(f.get("type") == "session_start" for f in frames), frames)

    @patch("app.routers.invocations.authenticate_bearer_token")
    def test_other_groups_agent_is_rejected(self, mock_auth) -> None:
        """loom:group is enforced, as it is on the HTTP route.

        The caller must hold `invoke` for this to prove anything — a group
        without it (g-admins-security, say) is stopped by the scope gate above
        and never reaches the group check, so such a test would pass whether
        or not the check existed.
        """
        mock_auth.return_value = _user(["t-user", "g-users-test"])  # invoke, wrong group
        self.assertIn("invoke", mock_auth.return_value.scopes)

        frames = self._frames_until_close(
            self.agent_id, {"type": "prompt", "prompt": "hi", "token": "valid"}
        )

        self.assertFalse(
            any(f.get("type") == "session_start" for f in frames),
            f"group check did not stop the invocation: {frames}",
        )

    @patch("app.routers.invocations.authenticate_bearer_token")
    def test_own_group_agent_reaches_the_invocation(self, mock_auth) -> None:
        """Positive control: a caller with invoke in the agent's own group gets
        through to session_start. Without this, a check that denied everything
        would satisfy every other test here."""
        mock_auth.return_value = _user(["t-user", "g-users-demo"])  # agent is tagged demo

        frames = self._frames_until(
            self.agent_id, {"type": "prompt", "prompt": "hi", "token": "valid"}, "session_start"
        )

        self.assertTrue(
            any(f.get("type") == "session_start" for f in frames),
            f"an authorized caller was blocked: {frames}",
        )

    @patch("app.routers.invocations.authenticate_bearer_token")
    def test_rejection_happens_before_any_agent_lookup(self, mock_auth) -> None:
        """Ordering guard: a failed authentication must not reach the database."""
        mock_auth.side_effect = HTTPException(status_code=401, detail="Invalid or expired token")

        with patch("app.routers.invocations.SessionLocal") as mock_session:
            frames = self._frames_until_close(
                self.agent_id, {"type": "prompt", "prompt": "hi", "token": "bad"}
            )
            # SessionLocal() is opened for the connection, but no query may run
            # against it before the caller is authenticated.
            mock_session.return_value.query.assert_not_called()

        self.assertFalse(any(f.get("type") == "session_start" for f in frames), frames)


if __name__ == "__main__":
    unittest.main()
