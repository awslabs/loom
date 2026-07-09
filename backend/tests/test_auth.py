"""Tests for authentication endpoints and JWT validation."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import jwt

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent
from app.services.jwt_validator import validate_cognito_token
from app.dependencies.auth import derive_scopes


class TestAuthConfigEndpoint(unittest.TestCase):
    """Test cases for GET /api/auth/config."""

    def setUp(self) -> None:
        """Set up test client."""
        self.client = TestClient(app)

    @patch.dict("os.environ", {
        "LOOM_COGNITO_USER_POOL_ID": "us-east-1_TestPool",
        "LOOM_COGNITO_REGION": "us-west-2",
    })
    def test_get_auth_config_returns_expected_fields(self) -> None:
        """Test that auth config returns pool ID and region."""
        response = self.client.get("/api/auth/config")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user_pool_id"], "us-east-1_TestPool")
        self.assertEqual(data["region"], "us-west-2")

    @patch.dict("os.environ", {}, clear=True)
    def test_get_auth_config_returns_defaults_when_env_not_set(self) -> None:
        """Test that auth config returns empty strings when env vars are not set."""
        response = self.client.get("/api/auth/config")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user_pool_id"], "")
        self.assertEqual(data["region"], "us-east-1")


class TestDeriveScopes(unittest.TestCase):
    """Test cases for derive_scopes function."""

    def test_derive_scopes_for_admins_demo_includes_mcp_and_a2a_write(self) -> None:
        """Test that g-admins-demo group includes mcp:write and a2a:write scopes."""
        scopes = derive_scopes(["g-admins-demo"])
        self.assertIn("mcp:read", scopes)
        self.assertIn("mcp:write", scopes)
        self.assertIn("a2a:read", scopes)
        self.assertIn("a2a:write", scopes)

    def test_derive_scopes_for_users_demo_has_minimal_scopes(self) -> None:
        """Test that g-users-demo group has agent:read, memory:read, mcp:read, invoke."""
        scopes = derive_scopes(["g-users-demo"])
        self.assertEqual(scopes, {"agent:read", "memory:read", "mcp:read", "invoke"})


class TestJWTValidator(unittest.TestCase):
    """Test cases for JWT token validation."""

    def test_validate_cognito_token_raises_on_invalid_token(self) -> None:
        """Test that an invalid token raises an error."""
        with self.assertRaises(jwt.exceptions.DecodeError):
            validate_cognito_token(
                token="not-a-valid-jwt",  # nosec B106
                user_pool_id="us-east-1_TestPool",
                region="us-east-1",
            )

    def test_validate_cognito_token_raises_on_empty_token(self) -> None:
        """Test that an empty token raises an error."""
        with self.assertRaises(jwt.exceptions.DecodeError):
            validate_cognito_token(
                token="",  # nosec B106
                user_pool_id="us-east-1_TestPool",
                region="us-east-1",
            )


class TestInvokeEndpointWithoutAuth(unittest.TestCase):
    """Regression test: invoke endpoint works without auth headers."""

    @classmethod
    def setUpClass(cls) -> None:
        """Set up test database."""
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self) -> None:
        """Set up test client and database session."""
        self.session = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        self.agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent",
            runtime_id="test-agent",
            name="Test Agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            log_group="/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT",
        )
        self.agent.set_available_qualifiers(["DEFAULT"])
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)

    def tearDown(self) -> None:
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
    def test_invoke_without_auth_header_still_works(
        self,
        mock_compute_duration,
        mock_invoke,
        mock_derive_log_group,
        mock_compute_cold_start,
        mock_parse_agent_start,
        mock_get_log_events,
    ) -> None:
        """Test that invoke works without Authorization header (regression)."""
        mock_invoke.return_value = iter([{"type": "text", "content": "Hello"}])
        mock_compute_duration.return_value = 1000.0
        mock_derive_log_group.return_value = "/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT"
        mock_get_log_events.return_value = []
        mock_parse_agent_start.return_value = None

        response = self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: session_start", response.text)
        self.assertIn("event: chunk", response.text)
        self.assertIn("event: session_end", response.text)


if __name__ == "__main__":
    unittest.main()
