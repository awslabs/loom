"""Tests for agent registration and management endpoints."""
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy import event

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent
from app.models.session import InvocationSession
from app.models.invocation import Invocation


class TestAgentsRouter(unittest.TestCase):
    """Test cases for /api/agents endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        # Use in-memory SQLite for tests with StaticPool to share across connections
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        # Enable foreign key constraints for SQLite (required for CASCADE deletes)
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

    def tearDown(self):
        """Clean up database after each test."""
        self.session.rollback()
        self.session.close()
        # Clear all tables
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_register_agent_success(self, mock_list_endpoints, mock_describe):
        """Test successful agent registration."""
        # Mock AWS responses
        mock_describe.return_value = {
            "agentRuntimeName": "Test Agent",
            "status": "READY",
        }
        mock_list_endpoints.return_value = ["DEFAULT", "PROD"]

        # Register agent
        response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent-abc123"}
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["arn"], "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent-abc123")
        self.assertEqual(data["runtime_id"], "test-agent-abc123")
        self.assertEqual(data["name"], "Test Agent")
        self.assertEqual(data["status"], "READY")
        self.assertEqual(data["region"], "us-east-1")
        self.assertEqual(data["account_id"], "123456789012")
        self.assertIn("DEFAULT", data["available_qualifiers"])
        self.assertIn("PROD", data["available_qualifiers"])
        self.assertEqual(data["active_session_count"], 0)

    def test_register_agent_invalid_arn(self):
        """Test registration with invalid ARN format."""
        response = self.client.post(
            "/api/agents",
            json={"arn": "invalid-arn-format"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid AgentCore Runtime ARN format", response.json()["detail"])

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_register_agent_duplicate(self, mock_list_endpoints, mock_describe):
        """Test registering the same agent twice."""
        # Mock AWS responses
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent-abc123"

        # Register first time
        response1 = self.client.post("/api/agents", json={"arn": arn})
        self.assertEqual(response1.status_code, 201)

        # Register second time (should fail)
        response2 = self.client.post("/api/agents", json={"arn": arn})
        self.assertEqual(response2.status_code, 409)
        self.assertIn("already registered", response2.json()["detail"])

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_list_agents(self, mock_list_endpoints, mock_describe):
        """Test listing all registered agents."""
        # Mock AWS responses
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        # Register two agents
        self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/agent1"}
        )
        self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/agent2"}
        )

        # List agents
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_get_agent_by_id(self, mock_list_endpoints, mock_describe):
        """Test getting a specific agent by ID."""
        # Mock AWS responses
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        # Register agent
        register_response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent"}
        )
        agent_id = register_response.json()["id"]

        # Get agent
        response = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], agent_id)
        self.assertEqual(data["runtime_id"], "test-agent")

    def test_get_agent_not_found(self):
        """Test getting a non-existent agent."""
        response = self.client.get("/api/agents/999")
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_delete_agent(self, mock_list_endpoints, mock_describe):
        """Test deleting an agent."""
        # Mock AWS responses
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        # Register agent
        register_response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent"}
        )
        agent_id = register_response.json()["id"]

        # Delete agent (no cleanup_aws — immediate removal, returns AgentResponse)
        response = self.client.delete(f"/api/agents/{agent_id}")
        self.assertEqual(response.status_code, 200)

        # Verify it's gone
        get_response = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(get_response.status_code, 404)

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_refresh_agent(self, mock_list_endpoints, mock_describe):
        """Test refreshing agent metadata."""
        # Initial mock responses
        mock_describe.return_value = {"agentRuntimeName": "Old Name", "status": "CREATING"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        # Register agent
        register_response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent"}
        )
        agent_id = register_response.json()["id"]

        # Update mock responses
        mock_describe.return_value = {"agentRuntimeName": "New Name", "status": "READY"}

        # Refresh agent
        response = self.client.post(f"/api/agents/{agent_id}/refresh")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "New Name")
        self.assertEqual(data["status"], "READY")


    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_delete_agent_cascades_sessions_and_invocations(self, mock_list_endpoints, mock_describe):
        """Test that deleting an agent also removes all associated sessions and invocations."""
        # Mock AWS responses
        mock_describe.return_value = {"agentRuntimeName": "Cascade Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        # Register agent via API
        register_response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cascade-test"}
        )
        self.assertEqual(register_response.status_code, 201)
        agent_id = register_response.json()["id"]

        # Create sessions and invocations directly in DB
        session1 = InvocationSession(
            agent_id=agent_id,
            session_id="session-cascade-1",
            qualifier="DEFAULT",
            status="complete",
            created_at=datetime.utcnow(),
        )
        session2 = InvocationSession(
            agent_id=agent_id,
            session_id="session-cascade-2",
            qualifier="DEFAULT",
            status="complete",
            created_at=datetime.utcnow(),
        )
        self.session.add_all([session1, session2])
        self.session.commit()

        inv1 = Invocation(
            session_id="session-cascade-1",
            invocation_id="inv-cascade-1",
            status="complete",
            prompt_text="Hello",
            response_text="World",
            created_at=datetime.utcnow(),
        )
        inv2 = Invocation(
            session_id="session-cascade-1",
            invocation_id="inv-cascade-2",
            status="complete",
            prompt_text="Foo",
            response_text="Bar",
            created_at=datetime.utcnow(),
        )
        inv3 = Invocation(
            session_id="session-cascade-2",
            invocation_id="inv-cascade-3",
            status="complete",
            prompt_text="Baz",
            response_text="Qux",
            created_at=datetime.utcnow(),
        )
        self.session.add_all([inv1, inv2, inv3])
        self.session.commit()

        # Verify data exists before delete
        self.assertEqual(self.session.query(InvocationSession).filter_by(agent_id=agent_id).count(), 2)
        self.assertEqual(self.session.query(Invocation).filter(
            Invocation.session_id.in_(["session-cascade-1", "session-cascade-2"])
        ).count(), 3)

        # Delete the agent via API (no cleanup_aws — immediate removal)
        delete_response = self.client.delete(f"/api/agents/{agent_id}")
        self.assertEqual(delete_response.status_code, 200)

        # Verify agent is gone
        self.assertIsNone(self.session.query(Agent).filter_by(id=agent_id).first())

        # Verify all sessions are cascade-deleted
        self.assertEqual(self.session.query(InvocationSession).filter_by(agent_id=agent_id).count(), 0)

        # Verify all invocations are cascade-deleted
        self.assertEqual(self.session.query(Invocation).filter(
            Invocation.session_id.in_(["session-cascade-1", "session-cascade-2"])
        ).count(), 0)

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_active_session_count_zero_sessions(self, mock_list_endpoints, mock_describe):
        """Test active_session_count is 0 when agent has no sessions."""
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        register_response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/no-sessions"}
        )
        agent_id = register_response.json()["id"]

        response = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active_session_count"], 0)

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_active_session_count_with_streaming_session(self, mock_list_endpoints, mock_describe):
        """Test active_session_count includes streaming sessions."""
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        register_response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/streaming-test"}
        )
        agent_id = register_response.json()["id"]

        # Create a streaming session
        session = InvocationSession(
            agent_id=agent_id,
            session_id="streaming-session",
            qualifier="DEFAULT",
            status="streaming",
            created_at=datetime.utcnow(),
        )
        self.session.add(session)
        self.session.commit()

        response = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active_session_count"], 1)

    @patch.dict("os.environ", {"LOOM_SESSION_IDLE_TIMEOUT_SECONDS": "15"})
    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_active_session_count_with_recent_complete_session(self, mock_list_endpoints, mock_describe):
        """Test active_session_count includes recently completed sessions."""
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        register_response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/recent-complete"}
        )
        agent_id = register_response.json()["id"]

        # Create a complete session with a recent invocation
        session = InvocationSession(
            agent_id=agent_id,
            session_id="recent-complete-session",
            qualifier="DEFAULT",
            status="complete",
            created_at=datetime.utcnow(),
        )
        self.session.add(session)
        self.session.commit()

        inv = Invocation(
            session_id="recent-complete-session",
            invocation_id="recent-inv",
            status="complete",
            client_done_time=time.time() - 5,  # 5 seconds ago (within 15-second timeout)
            created_at=datetime.utcnow(),
        )
        self.session.add(inv)
        self.session.commit()

        response = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active_session_count"], 1)

    @patch.dict("os.environ", {"LOOM_SESSION_IDLE_TIMEOUT_SECONDS": "15"})
    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_active_session_count_with_expired_session(self, mock_list_endpoints, mock_describe):
        """Test active_session_count excludes expired sessions."""
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        register_response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/expired-test"}
        )
        agent_id = register_response.json()["id"]

        # Create a complete session with an old invocation
        session = InvocationSession(
            agent_id=agent_id,
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
            client_done_time=time.time() - 3600,  # 1 hour ago (beyond 15 min timeout)
            created_at=datetime.utcnow() - timedelta(hours=1),
        )
        self.session.add(inv)
        self.session.commit()

        response = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active_session_count"], 0)

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_active_session_count_mixed_sessions(self, mock_list_endpoints, mock_describe):
        """Test active_session_count with a mix of active and expired sessions."""
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        register_response = self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/mixed-test"}
        )
        agent_id = register_response.json()["id"]

        # Streaming session (active)
        s1 = InvocationSession(
            agent_id=agent_id, session_id="mix-streaming",
            qualifier="DEFAULT", status="streaming", created_at=datetime.utcnow(),
        )
        # Recent complete session (active)
        s2 = InvocationSession(
            agent_id=agent_id, session_id="mix-recent",
            qualifier="DEFAULT", status="complete", created_at=datetime.utcnow(),
        )
        # Old complete session (expired)
        s3 = InvocationSession(
            agent_id=agent_id, session_id="mix-old",
            qualifier="DEFAULT", status="complete", created_at=datetime.utcnow() - timedelta(hours=1),
        )
        self.session.add_all([s1, s2, s3])
        self.session.commit()

        # Recent invocation for s2
        inv_recent = Invocation(
            session_id="mix-recent", invocation_id="mix-inv-recent",
            status="complete", client_done_time=time.time() - 60,
            created_at=datetime.utcnow(),
        )
        # Old invocation for s3
        inv_old = Invocation(
            session_id="mix-old", invocation_id="mix-inv-old",
            status="complete", client_done_time=time.time() - 3600,
            created_at=datetime.utcnow() - timedelta(hours=1),
        )
        self.session.add_all([inv_recent, inv_old])
        self.session.commit()

        response = self.client.get(f"/api/agents/{agent_id}")
        self.assertEqual(response.status_code, 200)
        # streaming + recent complete = 2 active, old = expired
        self.assertEqual(response.json()["active_session_count"], 2)

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_active_session_count_in_list_agents(self, mock_list_endpoints, mock_describe):
        """Test active_session_count is included in list agents response."""
        mock_describe.return_value = {"agentRuntimeName": "Test Agent", "status": "READY"}
        mock_list_endpoints.return_value = ["DEFAULT"]

        self.client.post(
            "/api/agents",
            json={"arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/list-test"}
        )

        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertIn("active_session_count", data[0])
        self.assertEqual(data[0]["active_session_count"], 0)


if __name__ == "__main__":
    unittest.main()
