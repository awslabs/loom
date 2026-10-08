"""Tests for integration management endpoints."""
import json
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent


class TestIntegrationsRouter(unittest.TestCase):
    """Test cases for /api/agents/{id}/integrations endpoints."""

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

        # Create a test agent with execution role (needed for IAM policy sync)
        self.agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/integ-test",
            runtime_id="integ-test",
            name="Integration Test Agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            source="deploy",
            execution_role_arn="arn:aws:iam::123456789012:role/loom-agent-integ-test",
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

    def test_create_integration(self):
        """Test creating an integration for an agent."""
        response = self.client.post(
            f"/api/agents/{self.agent.id}/integrations",
            json={
                "integration_type": "s3",
                "integration_config": {"bucket": "my-bucket", "prefix": "data/*"},
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["integration_type"], "s3")
        self.assertEqual(data["integration_config"]["bucket"], "my-bucket")
        self.assertTrue(data["enabled"])
        self.assertEqual(data["agent_id"], self.agent.id)

    def test_list_integrations(self):
        """Test listing integrations for an agent."""
        # Create two integrations
        self.client.post(
            f"/api/agents/{self.agent.id}/integrations",
            json={"integration_type": "s3", "integration_config": {"bucket": "b1"}},
        )
        self.client.post(
            f"/api/agents/{self.agent.id}/integrations",
            json={"integration_type": "bedrock", "integration_config": {"model_id": "claude-v2"}},
        )

        response = self.client.get(f"/api/agents/{self.agent.id}/integrations")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        types = {i["integration_type"] for i in data}
        self.assertIn("s3", types)
        self.assertIn("bedrock", types)

    def test_update_integration_toggle(self):
        """Test toggling an integration's enabled status."""
        create_resp = self.client.post(
            f"/api/agents/{self.agent.id}/integrations",
            json={"integration_type": "sqs", "integration_config": {"queue_arn": "arn:aws:sqs:us-east-1:123:q"}},
        )
        integration_id = create_resp.json()["id"]

        # Disable
        response = self.client.put(
            f"/api/agents/{self.agent.id}/integrations/{integration_id}",
            json={"enabled": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])

        # Re-enable
        response = self.client.put(
            f"/api/agents/{self.agent.id}/integrations/{integration_id}",
            json={"enabled": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])

    def test_delete_integration(self):
        """Test deleting an integration."""
        create_resp = self.client.post(
            f"/api/agents/{self.agent.id}/integrations",
            json={"integration_type": "sns", "integration_config": {"topic_arn": "arn:aws:sns:us-east-1:123:t"}},
        )
        integration_id = create_resp.json()["id"]

        response = self.client.delete(
            f"/api/agents/{self.agent.id}/integrations/{integration_id}"
        )
        self.assertEqual(response.status_code, 204)

        # Verify it's gone
        list_resp = self.client.get(f"/api/agents/{self.agent.id}/integrations")
        self.assertEqual(len(list_resp.json()), 0)

    def test_integration_does_not_touch_iam(self) -> None:
        """Integrations used to PutRolePolicy-replace the agent role's inline
        policy on every change. Loom no longer writes IAM at all, so adding an
        integration must not reach boto3 — the operator grants the permission
        on the role themselves, outside Loom.
        """
        with patch("boto3.client") as mock_boto:
            resp = self.client.post(
                f"/api/agents/{self.agent.id}/integrations",
                json={
                    "integration_type": "dynamodb",
                    "integration_config": {"table_arn": "arn:aws:dynamodb:us-east-1:123:table/t"},
                },
            )
        self.assertEqual(201, resp.status_code)
        iam_clients = [
            c for c in mock_boto.call_args_list
            if c.args and c.args[0] == "iam"
        ]
        self.assertEqual([], iam_clients, "integrations must not construct an IAM client")

    def test_create_integration_invalid_agent(self):
        """Test creating an integration for a non-existent agent returns 404."""
        response = self.client.post(
            "/api/agents/9999/integrations",
            json={"integration_type": "s3", "integration_config": {}},
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_nonexistent_integration(self):
        """Test deleting a non-existent integration returns 404."""
        response = self.client.delete(
            f"/api/agents/{self.agent.id}/integrations/9999"
        )
        self.assertEqual(response.status_code, 404)

    def test_update_nonexistent_integration(self):
        """Test updating a non-existent integration returns 404."""
        response = self.client.put(
            f"/api/agents/{self.agent.id}/integrations/9999",
            json={"enabled": False},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
