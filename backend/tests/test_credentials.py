"""Tests for credential provider endpoints."""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent


class TestCredentialsRouter(unittest.TestCase):
    """Test cases for /api/agents/{id}/credential-providers endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        """Set up test client and database session."""
        self.session = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Create a test agent
        self.agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cred-test",
            runtime_id="cred-test",
            name="Credential Test Agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            source="deploy",
        )
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)

    def tearDown(self):
        """Clean up database after each test."""
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @patch("app.routers.credentials.create_oauth2_credential_provider")
    def test_create_credential_provider(self, mock_create_provider):
        """Test creating a credential provider."""
        mock_create_provider.return_value = {
            "callbackUrl": "https://auth.example.com/callback",
        }

        response = self.client.post(
            f"/api/agents/{self.agent.id}/credential-providers",
            json={
                "name": "github-oauth",
                "vendor": "CustomOAuth2",
                "client_id": "client-id-123",
                "client_secret": "client-secret-456",
                "auth_server_url": "https://github.com/login/oauth",
                "scopes": ["read:user", "repo"],
                "provider_type": "mcp_server",
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["name"], "github-oauth")
        self.assertEqual(data["vendor"], "CustomOAuth2")
        self.assertEqual(data["callback_url"], "https://auth.example.com/callback")
        self.assertEqual(data["scopes"], ["read:user", "repo"])
        self.assertEqual(data["provider_type"], "mcp_server")
        self.assertEqual(data["agent_id"], self.agent.id)

    @patch("app.routers.credentials.create_oauth2_credential_provider")
    def test_list_credential_providers(self, mock_create_provider):
        """Test listing credential providers for an agent."""
        mock_create_provider.return_value = {"callbackUrl": "https://callback.example.com"}

        # Create two providers
        self.client.post(
            f"/api/agents/{self.agent.id}/credential-providers",
            json={
                "name": "provider-1",
                "vendor": "CustomOAuth2",
                "client_id": "cid1",
                "client_secret": "cs1",
                "auth_server_url": "https://auth1.example.com",
                "scopes": [],
            },
        )
        self.client.post(
            f"/api/agents/{self.agent.id}/credential-providers",
            json={
                "name": "provider-2",
                "vendor": "CustomOAuth2",
                "client_id": "cid2",
                "client_secret": "cs2",
                "auth_server_url": "https://auth2.example.com",
                "scopes": ["scope1"],
            },
        )

        response = self.client.get(f"/api/agents/{self.agent.id}/credential-providers")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

    @patch("app.routers.credentials.delete_credential_provider")
    @patch("app.routers.credentials.create_oauth2_credential_provider")
    def test_delete_credential_provider(self, mock_create_provider, mock_delete_provider):
        """Test deleting a credential provider."""
        mock_create_provider.return_value = {"callbackUrl": "https://callback.example.com"}

        create_resp = self.client.post(
            f"/api/agents/{self.agent.id}/credential-providers",
            json={
                "name": "to-delete",
                "vendor": "CustomOAuth2",
                "client_id": "cid",
                "client_secret": "cs",
                "auth_server_url": "https://auth.example.com",
                "scopes": [],
            },
        )
        provider_id = create_resp.json()["id"]

        response = self.client.delete(
            f"/api/agents/{self.agent.id}/credential-providers/{provider_id}"
        )
        self.assertEqual(response.status_code, 204)
        mock_delete_provider.assert_called_once_with("to-delete", "us-east-1")

        # Verify it's gone
        list_resp = self.client.get(f"/api/agents/{self.agent.id}/credential-providers")
        self.assertEqual(len(list_resp.json()), 0)

    @patch("app.routers.credentials.create_oauth2_credential_provider")
    def test_create_credential_provider_invalid_agent(self, mock_create_provider):
        """Test creating a credential provider for a non-existent agent returns 404."""
        response = self.client.post(
            "/api/agents/9999/credential-providers",
            json={
                "name": "bad-agent",
                "vendor": "CustomOAuth2",
                "client_id": "cid",
                "client_secret": "cs",
                "auth_server_url": "https://auth.example.com",
                "scopes": [],
            },
        )
        self.assertEqual(response.status_code, 404)
        mock_create_provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
