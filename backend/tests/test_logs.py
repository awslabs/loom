"""Tests for CloudWatch log retrieval endpoints."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent


class TestLogsRouter(unittest.TestCase):
    """Test cases for /api/agents/{id}/logs endpoints."""

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

    @patch("app.routers.logs.get_stream_log_events")
    @patch("app.routers.logs.list_log_streams")
    def test_get_agent_logs_success(self, mock_list_streams, mock_get_stream_logs):
        """Test successful log retrieval defaults to latest stream."""
        mock_list_streams.return_value = [
            {"name": "stream-latest", "last_event_time": 1708000002000},
            {"name": "stream-older", "last_event_time": 1708000001000},
        ]
        mock_get_stream_logs.return_value = [
            {
                "timestamp": 1708000001000,
                "message": '{"message": "Agent invoked - Start time: 2026-02-18T10:00:01.123456", "sessionId": "test-session-1"}',
            },
            {
                "timestamp": 1708000002000,
                "message": '{"message": "Processing request", "sessionId": "test-session-1"}',
            }
        ]

        response = self.client.get(
            f"/api/agents/{self.agent.id}/logs",
            params={"qualifier": "DEFAULT", "limit": 100}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["log_group"], "/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT")
        self.assertEqual(data["log_stream"], "stream-latest")
        self.assertEqual(len(data["events"]), 2)
        self.assertIn("Agent invoked", data["events"][0]["message"])
        self.assertEqual(data["events"][0]["session_id"], "test-session-1")

        # Verify it queried the latest stream
        mock_get_stream_logs.assert_called_once()
        call_kwargs = mock_get_stream_logs.call_args.kwargs
        self.assertEqual(call_kwargs["stream_name"], "stream-latest")

    @patch("app.routers.logs.get_stream_log_events")
    def test_get_agent_logs_with_stream_param(self, mock_get_stream_logs):
        """Test log retrieval with explicit stream parameter."""
        mock_get_stream_logs.return_value = [
            {"timestamp": 1708000001000, "message": "Test log"},
        ]

        response = self.client.get(
            f"/api/agents/{self.agent.id}/logs",
            params={"qualifier": "DEFAULT", "stream": "my-specific-stream"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["log_stream"], "my-specific-stream")

        # Verify it queried the specified stream directly (no list_log_streams call)
        call_kwargs = mock_get_stream_logs.call_args.kwargs
        self.assertEqual(call_kwargs["stream_name"], "my-specific-stream")

    @patch("app.routers.logs.list_log_streams")
    def test_get_agent_logs_no_streams(self, mock_list_streams):
        """Test log retrieval when no streams exist."""
        mock_list_streams.return_value = []

        response = self.client.get(
            f"/api/agents/{self.agent.id}/logs",
            params={"qualifier": "DEFAULT"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["log_stream"], "")
        self.assertEqual(len(data["events"]), 0)

    def test_get_agent_logs_agent_not_found(self):
        """Test log retrieval for non-existent agent."""
        response = self.client.get("/api/agents/999/logs")
        self.assertEqual(response.status_code, 404)

    def test_get_agent_logs_invalid_qualifier(self):
        """Test log retrieval with invalid qualifier."""
        response = self.client.get(
            f"/api/agents/{self.agent.id}/logs",
            params={"qualifier": "INVALID"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not available", response.json()["detail"])

    @patch("app.routers.logs.get_stream_log_events")
    @patch("app.routers.logs.list_log_streams")
    def test_get_agent_logs_with_time_filters(self, mock_list_streams, mock_get_stream_logs):
        """Test log retrieval with time filters."""
        mock_list_streams.return_value = [{"name": "stream-1", "last_event_time": 1708000001000}]
        mock_get_stream_logs.return_value = [
            {"timestamp": 1708000001000, "message": "Test log"},
        ]

        response = self.client.get(
            f"/api/agents/{self.agent.id}/logs",
            params={
                "qualifier": "DEFAULT",
                "start_time": "2026-02-18T09:00:00Z",
                "end_time": "2026-02-18T11:00:00Z",
                "limit": 50
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["events"]), 1)

        # Verify time filters were passed to the service
        call_kwargs = mock_get_stream_logs.call_args.kwargs
        self.assertIsNotNone(call_kwargs["start_time_ms"])
        self.assertIsNotNone(call_kwargs["end_time_ms"])

    @patch("app.routers.logs.list_log_streams")
    def test_get_log_streams(self, mock_list_streams):
        """Test listing available log streams."""
        mock_list_streams.return_value = [
            {"name": "stream-latest", "last_event_time": 1708000002000},
            {"name": "stream-older", "last_event_time": 1708000001000},
        ]

        response = self.client.get(
            f"/api/agents/{self.agent.id}/logs/streams",
            params={"qualifier": "DEFAULT"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["log_group"], "/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT")
        self.assertEqual(len(data["streams"]), 2)
        self.assertEqual(data["streams"][0]["name"], "stream-latest")

    @patch("app.routers.logs.get_log_events")
    def test_get_session_logs_success(self, mock_get_logs):
        """Test successful session-specific log retrieval."""
        mock_get_logs.return_value = [
            {
                "timestamp": 1708000001000,
                "message": '{"message": "Agent invoked - Start time: 2026-02-18T10:00:01.123456", "sessionId": "test-session-123"}',
            },
            {
                "timestamp": 1708000002000,
                "message": '{"message": "Processing complete", "sessionId": "test-session-123"}',
            }
        ]

        response = self.client.get(
            f"/api/agents/{self.agent.id}/sessions/test-session-123/logs",
            params={"qualifier": "DEFAULT"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["events"]), 2)
        self.assertEqual(data["events"][0]["session_id"], "test-session-123")

        # Verify get_log_events was called with session_id filter
        mock_get_logs.assert_called_once()
        call_args = mock_get_logs.call_args
        self.assertEqual(call_args.kwargs["session_id"], "test-session-123")

    def test_get_session_logs_agent_not_found(self):
        """Test session log retrieval for non-existent agent."""
        response = self.client.get("/api/agents/999/sessions/test-session/logs")
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.logs.get_stream_log_events")
    @patch("app.routers.logs.list_log_streams")
    def test_get_logs_cloudwatch_error(self, mock_list_streams, mock_get_stream_logs):
        """Test error handling when CloudWatch call fails."""
        mock_list_streams.return_value = [{"name": "stream-1", "last_event_time": 0}]
        mock_get_stream_logs.side_effect = Exception("CloudWatch API error")

        response = self.client.get(f"/api/agents/{self.agent.id}/logs")
        self.assertEqual(response.status_code, 502)
        self.assertIn("Failed to retrieve logs", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
