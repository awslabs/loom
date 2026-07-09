"""Tests for agent external integration info endpoint."""
import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent


class TestIntegrationInfoEndpoint(unittest.TestCase):
    """Test cases for GET /api/agents/{id}/integration."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        self.session = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)

    def _create_agent(self, **overrides) -> Agent:
        defaults = {
            "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/rt-abc123",
            "runtime_id": "rt-abc123",
            "name": "test-agent",
            "status": "READY",
            "region": "us-east-1",
            "account_id": "123456789012",
            "source": "deploy",
            "protocol": "HTTP",
            "network_mode": "PUBLIC",
            "available_qualifiers": json.dumps(["DEFAULT"]),
        }
        defaults.update(overrides)
        agent = Agent(**defaults)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        return agent

    def test_integration_sigv4_custom_agent(self):
        agent = self._create_agent()
        resp = self.client.get(f"/api/agents/{agent.id}/integration")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["protocol"], "HTTP")
        self.assertEqual(data["network_mode"], "PUBLIC")
        self.assertEqual(data["region"], "us-east-1")
        self.assertEqual(len(data["endpoints"]), 1)
        ep = data["endpoints"][0]
        self.assertEqual(ep["qualifier"], "DEFAULT")
        self.assertIn("/runtimes/", ep["invocation_url"])
        self.assertIn("/invocations", ep["invocation_url"])
        self.assertIsNone(ep["protocol_url"])
        auth = data["auth"]
        self.assertEqual(auth["method"], "SigV4")
        self.assertEqual(auth["iam_action"], "bedrock-agentcore:InvokeAgentRuntime")
        self.assertIn("example_boto3", auth)
        self.assertIn("example_cli", auth)

    def test_integration_sigv4_harness_agent(self):
        agent = self._create_agent(source="harness")
        resp = self.client.get(f"/api/agents/{agent.id}/integration")
        self.assertEqual(resp.status_code, 200)
        auth = resp.json()["auth"]
        self.assertEqual(auth["iam_action"], "bedrock-agentcore:InvokeHarness")

    def test_integration_oauth2_cognito(self):
        auth_config = json.dumps({
            "type": "cognito",
            "pool_id": "us-east-1_abcXYZ",
            "allowed_clients": ["client-1", "client-2"],
            "allowed_scopes": ["openid", "profile"],
        })
        agent = self._create_agent(authorizer_config=auth_config)
        resp = self.client.get(f"/api/agents/{agent.id}/integration")
        self.assertEqual(resp.status_code, 200)
        auth = resp.json()["auth"]
        self.assertEqual(auth["method"], "OAuth2")
        self.assertEqual(auth["authorizer_type"], "cognito")
        self.assertIn("cognito-idp.us-east-1.amazonaws.com/us-east-1_abcXYZ", auth["discovery_url"])
        self.assertIn("oauth2/token", auth["token_endpoint"])
        self.assertEqual(auth["allowed_client_ids"], ["client-1", "client-2"])
        self.assertEqual(auth["allowed_scopes"], ["openid", "profile"])
        auth_json = json.dumps(auth)
        self.assertNotIn("real_secret_value", auth_json)
        self.assertIn("YOUR_SECRET", auth_json)

    def test_integration_oauth2_custom_oidc(self):
        auth_config = json.dumps({
            "type": "custom",
            "discovery_url": "https://idp.example.com/.well-known/openid-configuration",
            "allowed_clients": ["my-app"],
            "allowed_scopes": ["api"],
        })
        agent = self._create_agent(authorizer_config=auth_config)
        resp = self.client.get(f"/api/agents/{agent.id}/integration")
        self.assertEqual(resp.status_code, 200)
        auth = resp.json()["auth"]
        self.assertEqual(auth["method"], "OAuth2")
        self.assertEqual(auth["authorizer_type"], "custom")
        self.assertEqual(auth["discovery_url"], "https://idp.example.com/.well-known/openid-configuration")
        self.assertIn("oauth2/token", auth["token_endpoint"])

    def test_integration_mcp_protocol_url(self):
        agent = self._create_agent(protocol="MCP")
        resp = self.client.get(f"/api/agents/{agent.id}/integration")
        self.assertEqual(resp.status_code, 200)
        ep = resp.json()["endpoints"][0]
        self.assertIn("/mcp", ep["protocol_url"])
        self.assertEqual(ep["protocol_url_label"], "MCP Streamable HTTP")

    def test_integration_a2a_protocol_url(self):
        agent = self._create_agent(protocol="A2A")
        resp = self.client.get(f"/api/agents/{agent.id}/integration")
        self.assertEqual(resp.status_code, 200)
        ep = resp.json()["endpoints"][0]
        self.assertIn("/.well-known/agent.json", ep["protocol_url"])
        self.assertEqual(ep["protocol_url_label"], "A2A Agent Card")

    def test_integration_multiple_qualifiers(self):
        agent = self._create_agent(available_qualifiers=json.dumps(["DEFAULT", "STAGING"]))
        resp = self.client.get(f"/api/agents/{agent.id}/integration")
        self.assertEqual(resp.status_code, 200)
        endpoints = resp.json()["endpoints"]
        self.assertEqual(len(endpoints), 2)
        qualifiers = [e["qualifier"] for e in endpoints]
        self.assertIn("DEFAULT", qualifiers)
        self.assertIn("STAGING", qualifiers)

    def test_integration_vpc_network_mode(self):
        agent = self._create_agent(network_mode="VPC")
        resp = self.client.get(f"/api/agents/{agent.id}/integration")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["network_mode"], "VPC")

    def test_integration_not_ready(self):
        agent = self._create_agent(status="CREATING")
        resp = self.client.get(f"/api/agents/{agent.id}/integration")
        self.assertEqual(resp.status_code, 400)

    def test_integration_not_found(self):
        resp = self.client.get("/api/agents/99999/integration")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
