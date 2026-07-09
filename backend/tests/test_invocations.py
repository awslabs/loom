"""Tests for agent invocation endpoints."""
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent
from app.models.session import InvocationSession
from app.models.invocation import Invocation


class TestInvocationsRouter(unittest.TestCase):
    """Test cases for /api/agents/{id}/invoke and session endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(cls.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        """Set up test client and database session."""
        self.session = self.TestingSessionLocal()

        # Override dependency
        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Create a test agent
        self.agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent",
            runtime_id="test-agent",
            name="Test Agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            log_group="/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT",
        )
        self.agent.set_available_qualifiers(["DEFAULT", "PROD"])
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)

    def tearDown(self):
        """Clean up database after each test."""
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @patch("app.routers.invocations.get_log_events")
    @patch("app.routers.invocations.parse_agent_start_time")
    @patch("app.routers.invocations.compute_cold_start")
    @patch("app.routers.invocations.derive_log_group")
    @patch("app.routers.invocations.invoke_agent")
    @patch("app.routers.invocations.compute_client_duration")
    def test_invoke_agent_success(self, mock_compute_duration, mock_invoke, mock_derive_log_group,
                                  mock_compute_cold_start, mock_parse_agent_start, mock_get_log_events):
        """Test successful agent invocation with SSE streaming."""
        # Mock invoke_agent to return structured chunks
        mock_invoke.return_value = iter([
            {"type": "text", "content": "Hello"},
            {"type": "text", "content": " "},
            {"type": "text", "content": "world"},
            {"type": "text", "content": "!"},
        ])
        mock_compute_duration.return_value = 1500.0

        # Mock CloudWatch functions - no logs found (common case)
        mock_derive_log_group.return_value = "/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT"
        mock_get_log_events.return_value = []
        mock_parse_agent_start.return_value = None

        # Invoke agent
        response = self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/event-stream; charset=utf-8")

        # Parse SSE events
        content = response.text
        self.assertIn("event: session_start", content)
        self.assertIn("event: chunk", content)
        self.assertIn("event: session_end", content)
        self.assertIn("Hello", content)
        self.assertIn("world", content)

    def test_invoke_agent_not_found(self):
        """Test invoking a non-existent agent."""
        response = self.client.post(
            "/api/agents/999/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"}
        )

        self.assertEqual(response.status_code, 404)

    def test_invoke_agent_invalid_qualifier(self):
        """Test invoking with an invalid qualifier."""
        response = self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "INVALID"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not available", response.json()["detail"])

    @patch("app.routers.invocations.get_log_events")
    @patch("app.routers.invocations.parse_agent_start_time")
    @patch("app.routers.invocations.compute_cold_start")
    @patch("app.routers.invocations.derive_log_group")
    @patch("app.routers.invocations.invoke_agent")
    @patch("app.routers.invocations.compute_client_duration")
    def test_invoke_agent_error(self, mock_compute_duration, mock_invoke, mock_derive_log_group,
                                mock_compute_cold_start, mock_parse_agent_start, mock_get_log_events):
        """Test invocation error handling."""
        # Mock invoke_agent to raise an exception
        mock_invoke.side_effect = Exception("Invocation failed")

        # Invoke agent
        response = self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"}
        )

        self.assertEqual(response.status_code, 200)
        content = response.text
        self.assertIn("event: error", content)
        self.assertIn("Invocation failed", content)

    @patch("app.routers.invocations.get_log_events")
    @patch("app.routers.invocations.parse_agent_start_time")
    @patch("app.routers.invocations.compute_cold_start")
    @patch("app.routers.invocations.derive_log_group")
    @patch("app.routers.invocations.invoke_agent")
    @patch("app.routers.invocations.compute_client_duration")
    def test_list_sessions(self, mock_compute_duration, mock_invoke, mock_derive_log_group,
                          mock_compute_cold_start, mock_parse_agent_start, mock_get_log_events):
        """Test listing sessions for an agent."""
        # Mock invoke_agent
        mock_invoke.return_value = iter([{"type": "text", "content": "Test response"}])
        mock_compute_duration.return_value = 1000.0

        # Mock CloudWatch functions
        mock_derive_log_group.return_value = "/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT"
        mock_get_log_events.return_value = []
        mock_parse_agent_start.return_value = None

        # Create a session by invoking
        self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt 1", "qualifier": "DEFAULT"}
        )

        # List sessions
        response = self.client.get(f"/api/agents/{self.agent.id}/sessions")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["qualifier"], "DEFAULT")
        self.assertEqual(len(data[0]["invocations"]), 1)
        self.assertIn("live_status", data[0])

    def test_list_sessions_agent_not_found(self):
        """Test listing sessions for non-existent agent."""
        response = self.client.get("/api/agents/999/sessions")
        self.assertEqual(response.status_code, 404)

    def test_list_sessions_with_user_id_filter(self):
        """Test that list_sessions filters by user_id query parameter."""
        # Create sessions with different user_ids directly in the database
        session_a = InvocationSession(
            agent_id=self.agent.id,
            session_id="sess-user-a",
            qualifier="DEFAULT",
            user_id="user-a",
        )
        session_b = InvocationSession(
            agent_id=self.agent.id,
            session_id="sess-user-b",
            qualifier="DEFAULT",
            user_id="user-b",
        )
        session_none = InvocationSession(
            agent_id=self.agent.id,
            session_id="sess-no-user",
            qualifier="DEFAULT",
            user_id=None,
        )
        self.session.add_all([session_a, session_b, session_none])
        self.session.commit()

        # Without filter: returns all sessions (including any from prior tests)
        response = self.client.get(f"/api/agents/{self.agent.id}/sessions")
        self.assertEqual(response.status_code, 200)
        all_ids = {s["session_id"] for s in response.json()}
        self.assertIn("sess-user-a", all_ids)
        self.assertIn("sess-user-b", all_ids)
        self.assertIn("sess-no-user", all_ids)

        # With user_id=user-a: returns only user-a's session
        response = self.client.get(f"/api/agents/{self.agent.id}/sessions?user_id=user-a")
        self.assertEqual(response.status_code, 200)
        filtered_ids = {s["session_id"] for s in response.json()}
        self.assertIn("sess-user-a", filtered_ids)
        self.assertNotIn("sess-user-b", filtered_ids)
        self.assertNotIn("sess-no-user", filtered_ids)

        # With user_id=user-b: returns only user-b's session
        response = self.client.get(f"/api/agents/{self.agent.id}/sessions?user_id=user-b")
        self.assertEqual(response.status_code, 200)
        filtered_ids = {s["session_id"] for s in response.json()}
        self.assertNotIn("sess-user-a", filtered_ids)
        self.assertIn("sess-user-b", filtered_ids)
        self.assertNotIn("sess-no-user", filtered_ids)

        # With non-existent user_id: returns empty
        response = self.client.get(f"/api/agents/{self.agent.id}/sessions?user_id=nobody")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 0)

    @patch("app.routers.invocations.get_log_events")
    @patch("app.routers.invocations.parse_agent_start_time")
    @patch("app.routers.invocations.compute_cold_start")
    @patch("app.routers.invocations.derive_log_group")
    @patch("app.routers.invocations.invoke_agent")
    @patch("app.routers.invocations.compute_client_duration")
    def test_get_session(self, mock_compute_duration, mock_invoke, mock_derive_log_group,
                        mock_compute_cold_start, mock_parse_agent_start, mock_get_log_events):
        """Test getting a specific session."""
        # Mock invoke_agent
        mock_invoke.return_value = iter([{"type": "text", "content": "Test response"}])
        mock_compute_duration.return_value = 1000.0

        # Mock CloudWatch functions
        mock_derive_log_group.return_value = "/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT"
        mock_get_log_events.return_value = []
        mock_parse_agent_start.return_value = None

        # Create a session
        invoke_response = self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"}
        )

        # Extract session_id from SSE response
        content = invoke_response.text
        import json
        import re
        match = re.search(r'event: session_start\ndata: ({.*?})\n', content)
        self.assertIsNotNone(match)
        session_data = json.loads(match.group(1))
        session_id = session_data["session_id"]

        # Get session
        response = self.client.get(f"/api/agents/{self.agent.id}/sessions/{session_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["session_id"], session_id)
        self.assertEqual(len(data["invocations"]), 1)


    def test_get_session_not_found(self):
        """Test getting a non-existent session."""
        response = self.client.get(f"/api/agents/{self.agent.id}/sessions/invalid-session-id")
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.invocations.get_log_events")
    @patch("app.routers.invocations.parse_agent_start_time")
    @patch("app.routers.invocations.compute_cold_start")
    @patch("app.routers.invocations.derive_log_group")
    @patch("app.routers.invocations.invoke_agent")
    @patch("app.routers.invocations.compute_client_duration")
    def test_invoke_agent_with_cold_start_latency(self, mock_compute_duration, mock_invoke, mock_derive_log_group,
                                                  mock_compute_cold_start, mock_parse_agent_start, mock_get_log_events):
        """Test that cold_start_latency_ms appears in session_end when CloudWatch logs are available."""
        # Mock invoke_agent to return structured chunks
        mock_invoke.return_value = iter([{"type": "text", "content": "Hello"}])
        mock_compute_duration.return_value = 1500.0

        # Mock CloudWatch functions - logs found with agent_start_time
        mock_derive_log_group.return_value = "/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT"
        mock_get_log_events.return_value = [
            {"timestamp": 1234567890000, "message": "Agent invoked - Start time: 2026-02-11T19:44:38.558763"}
        ]
        mock_parse_agent_start.return_value = 1234567890.558
        mock_compute_cold_start.return_value = 558.0

        # Invoke agent
        response = self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"}
        )

        self.assertEqual(response.status_code, 200)

        # Parse SSE events
        content = response.text
        import json
        import re

        # Extract session_end event
        match = re.search(r'event: session_end\ndata: ({.*?})\n', content)
        self.assertIsNotNone(match, "session_end event not found")
        session_end_data = json.loads(match.group(1))

        # Verify cold_start_latency_ms and agent_start_time are present
        self.assertIn("cold_start_latency_ms", session_end_data)
        self.assertIn("agent_start_time", session_end_data)
        self.assertEqual(session_end_data["cold_start_latency_ms"], 558.0)
        self.assertEqual(session_end_data["agent_start_time"], 1234567890.558)


    @patch("app.routers.invocations.get_log_events")
    @patch("app.routers.invocations.parse_agent_start_time")
    @patch("app.routers.invocations.compute_cold_start")
    @patch("app.routers.invocations.derive_log_group")
    @patch("app.routers.invocations.invoke_agent")
    @patch("app.routers.invocations.compute_client_duration")
    def test_invoke_stores_content(self, mock_compute_duration, mock_invoke, mock_derive_log_group,
                                   mock_compute_cold_start, mock_parse_agent_start, mock_get_log_events):
        """Test that prompt_text and response_text are persisted after invocation."""
        mock_invoke.return_value = iter([
            {"type": "text", "content": "Hello "},
            {"type": "text", "content": "world"},
        ])
        mock_compute_duration.return_value = 1000.0
        mock_derive_log_group.return_value = "/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT"
        mock_get_log_events.return_value = []
        mock_parse_agent_start.return_value = None

        response = self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "My test prompt", "qualifier": "DEFAULT"}
        )
        self.assertEqual(response.status_code, 200)

        # Extract invocation_id from SSE
        import json
        import re
        match = re.search(r'event: session_start\ndata: ({.*?})\n', response.text)
        self.assertIsNotNone(match)
        start_data = json.loads(match.group(1))
        invocation_id = start_data["invocation_id"]
        session_id = start_data["session_id"]

        # Fetch the invocation detail and verify content fields
        detail_response = self.client.get(
            f"/api/agents/{self.agent.id}/sessions/{session_id}/invocations/{invocation_id}"
        )
        self.assertEqual(detail_response.status_code, 200)
        data = detail_response.json()
        self.assertEqual(data["prompt_text"], "My test prompt")
        self.assertEqual(data["response_text"], "Hello world")

    def test_live_status_pending_session(self):
        """Test live_status is 'pending' for a pending session."""
        session = InvocationSession(
            agent_id=self.agent.id,
            session_id="pending-session",
            qualifier="DEFAULT",
            status="pending",
            created_at=datetime.utcnow(),
        )
        self.session.add(session)
        self.session.commit()

        response = self.client.get(f"/api/agents/{self.agent.id}/sessions/pending-session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["live_status"], "pending")

    def test_live_status_streaming_session(self):
        """Test live_status is 'streaming' for a streaming session."""
        session = InvocationSession(
            agent_id=self.agent.id,
            session_id="streaming-session",
            qualifier="DEFAULT",
            status="streaming",
            created_at=datetime.utcnow(),
        )
        self.session.add(session)
        self.session.commit()

        response = self.client.get(f"/api/agents/{self.agent.id}/sessions/streaming-session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["live_status"], "streaming")

    def test_live_status_active_complete_session(self):
        """Test live_status is 'active' for a recently completed session."""
        session = InvocationSession(
            agent_id=self.agent.id,
            session_id="active-complete-session",
            qualifier="DEFAULT",
            status="complete",
            created_at=datetime.utcnow(),
        )
        self.session.add(session)
        self.session.commit()

        inv = Invocation(
            session_id="active-complete-session",
            invocation_id="active-inv",
            status="complete",
            client_done_time=time.time() - 60,  # 1 minute ago
            created_at=datetime.utcnow(),
        )
        self.session.add(inv)
        self.session.commit()

        response = self.client.get(f"/api/agents/{self.agent.id}/sessions/active-complete-session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["live_status"], "active")

    def test_live_status_expired_session(self):
        """Test live_status is 'expired' for a session with old invocations."""
        session = InvocationSession(
            agent_id=self.agent.id,
            session_id="expired-session",
            qualifier="DEFAULT",
            status="complete",
            created_at=datetime.utcnow() - timedelta(hours=1),
        )
        self.session.add(session)
        self.session.commit()

        inv = Invocation(
            session_id="expired-session",
            invocation_id="expired-inv",
            status="complete",
            client_done_time=time.time() - 3600,  # 1 hour ago
            created_at=datetime.utcnow() - timedelta(hours=1),
        )
        self.session.add(inv)
        self.session.commit()

        response = self.client.get(f"/api/agents/{self.agent.id}/sessions/expired-session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["live_status"], "expired")

    def test_live_status_no_invocations_recent_created(self):
        """Test live_status falls back to created_at when no invocations exist."""
        session = InvocationSession(
            agent_id=self.agent.id,
            session_id="no-inv-recent",
            qualifier="DEFAULT",
            status="complete",
            created_at=datetime.utcnow(),  # Just created
        )
        self.session.add(session)
        self.session.commit()

        response = self.client.get(f"/api/agents/{self.agent.id}/sessions/no-inv-recent")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["live_status"], "active")

    def test_live_status_no_invocations_old_created(self):
        """Test live_status is 'expired' when no invocations and old created_at."""
        session = InvocationSession(
            agent_id=self.agent.id,
            session_id="no-inv-old",
            qualifier="DEFAULT",
            status="complete",
            created_at=datetime.utcnow() - timedelta(hours=1),
        )
        self.session.add(session)
        self.session.commit()

        response = self.client.get(f"/api/agents/{self.agent.id}/sessions/no-inv-old")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["live_status"], "expired")

    def test_live_status_in_list_sessions(self):
        """Test live_status is included in list sessions response."""
        session = InvocationSession(
            agent_id=self.agent.id,
            session_id="list-status-session",
            qualifier="DEFAULT",
            status="streaming",
            created_at=datetime.utcnow(),
        )
        self.session.add(session)
        self.session.commit()

        response = self.client.get(f"/api/agents/{self.agent.id}/sessions")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["live_status"], "streaming")

    def test_live_status_error_session_recent(self):
        """Test live_status is 'active' for a recently errored session."""
        session = InvocationSession(
            agent_id=self.agent.id,
            session_id="error-recent-session",
            qualifier="DEFAULT",
            status="error",
            created_at=datetime.utcnow(),
        )
        self.session.add(session)
        self.session.commit()

        inv = Invocation(
            session_id="error-recent-session",
            invocation_id="error-recent-inv",
            status="error",
            client_done_time=time.time() - 30,  # 30 seconds ago
            created_at=datetime.utcnow(),
        )
        self.session.add(inv)
        self.session.commit()

        response = self.client.get(f"/api/agents/{self.agent.id}/sessions/error-recent-session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["live_status"], "active")


if __name__ == "__main__":
    unittest.main()
