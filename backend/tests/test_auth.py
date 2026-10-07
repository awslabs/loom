"""Tests for authentication endpoints and JWT validation."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import jwt
import pytest

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent
from app.services.jwt_validator import validate_cognito_token
from app.dependencies.auth import derive_scopes


@pytest.fixture(autouse=True)
def _default_auth_bypass():
    """Override the suite-wide auto-bypass fixture — this module tests bypass mechanics directly."""
    yield


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
        """g-users-demo holds agent:read, session:read, memory:read, mcp:read, invoke.

        session:read is separate from agent:read so conversation content can be
        granted independently of agent visibility; a user still needs it to see
        their own chat history."""
        scopes = derive_scopes(["g-users-demo"])
        self.assertEqual(scopes, {"agent:read", "session:read", "memory:read", "mcp:read", "invoke"})


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
    """Auth bypass now fails closed by default and requires explicit opt-in + loopback."""

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

    @patch.dict("os.environ", {}, clear=True)
    def test_invoke_without_auth_header_rejected_by_default(self) -> None:
        """No IdP configured and no bypass opt-in: invoke is rejected, not silently admin."""
        response = self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"},
        )
        self.assertEqual(response.status_code, 401)
        # Assert *which* 401. get_current_user can reject for two different
        # reasons, and only this one is the fail-closed guard — an active IdP
        # leaking in would skip the bypass branch entirely and reject with
        # "Missing authorization token" instead, letting this test pass while
        # the guard itself was gone.
        self.assertEqual(response.json()["detail"], "No identity provider configured")

    @patch.dict("os.environ", {"LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV": "true"}, clear=True)
    @patch("app.routers.invocations.get_log_events")
    @patch("app.routers.invocations.parse_agent_start_time")
    @patch("app.routers.invocations.compute_cold_start")
    @patch("app.routers.invocations.derive_log_group")
    @patch("app.routers.invocations.invoke_agent")
    @patch("app.routers.invocations.compute_client_duration")
    def test_invoke_without_auth_header_works_with_explicit_loopback_bypass(
        self,
        mock_compute_duration,
        mock_invoke,
        mock_derive_log_group,
        mock_compute_cold_start,
        mock_parse_agent_start,
        mock_get_log_events,
    ) -> None:
        """With LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV set and a loopback client, bypass still works."""
        mock_invoke.return_value = iter([{"type": "text", "content": "Hello"}])
        mock_compute_duration.return_value = 1000.0
        mock_derive_log_group.return_value = "/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT"
        mock_get_log_events.return_value = []
        mock_parse_agent_start.return_value = None

        loopback_client = TestClient(app, client=("127.0.0.1", 12345))
        response = loopback_client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: session_start", response.text)
        self.assertIn("event: chunk", response.text)
        self.assertIn("event: session_end", response.text)

    @patch.dict("os.environ", {"LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV": "true"}, clear=True)
    def test_invoke_without_auth_header_still_rejected_when_not_loopback(self) -> None:
        """Bypass opt-in alone is not enough — a non-loopback client is still rejected."""
        response = self.client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "No identity provider configured")

    @patch.dict("os.environ", {"LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV": "true"}, clear=True)
    @patch("app.dependencies.auth._get_active_idp_cached")
    def test_configured_idp_takes_the_bypass_off_the_table(self, mock_active_idp) -> None:
        """An active external IdP must disable the bypass outright.

        This is the dangerous combination, and the one with no coverage until
        now: a deployment that has wired up a real IdP but still carries the
        local-dev opt-in, reached from loopback. Both bypass preconditions are
        satisfied, so the only thing between an unauthenticated caller and
        every scope is get_current_user checking for a configured IdP *before*
        it ever considers the bypass.

        The detail assertion is the point of the test. A bare 401 here would
        also be produced by the bypass branch failing closed, which would pass
        even if the IdP check had been reordered after it; "Missing
        authorization token" can only come from the token-validation path, and
        so proves the bypass was never reachable.
        """
        mock_active_idp.return_value = {
            "id": 1,
            "provider_type": "okta",
            "issuer_url": "https://example.okta.com/oauth2/default",
            "client_id": "test-client",
            "audience": None,
            "jwks_uri": "https://example.okta.com/oauth2/default/v1/keys",
            "group_claim_path": "groups",
            "group_mappings": {},
        }

        loopback_client = TestClient(app, client=("127.0.0.1", 12345))
        response = loopback_client.post(
            f"/api/agents/{self.agent.id}/invoke",
            json={"prompt": "Test prompt", "qualifier": "DEFAULT"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Missing authorization token")


if __name__ == "__main__":
    unittest.main()
