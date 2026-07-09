"""Tests for runtime model selection feature (issue #78)."""
import json
import unittest
from datetime import datetime
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent
from app.models.config_entry import ConfigEntry


class TestModelSelection(unittest.TestCase):
    """Test cases for allowed_model_ids and runtime model selection."""

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
        cls.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=cls.engine
        )

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

    def _create_agent_with_models(self, allowed_models=None, model_id="us.anthropic.claude-sonnet-4-6"):
        """Helper to create a registered agent with config and allowed models."""
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-model-agent",
            runtime_id="test-model-agent",
            name="Test Model Agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            source="register",
            registered_at=datetime.utcnow(),
        )
        if allowed_models:
            agent.set_allowed_model_ids(allowed_models)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)

        config = ConfigEntry(
            agent_id=agent.id,
            key="AGENT_CONFIG_JSON",
            value=json.dumps({"model_id": model_id}),
            is_secret=False,
            source="env_var",
        )
        self.session.add(config)
        self.session.commit()
        return agent

    # ---- Agent model ----

    def test_agent_allowed_model_ids_default_empty(self):
        """Agent with no allowed_model_ids returns empty list."""
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/empty-models",
            runtime_id="empty-models",
            name="Empty",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            registered_at=datetime.utcnow(),
        )
        self.assertEqual(agent.get_allowed_model_ids(), [])

    def test_agent_allowed_model_ids_roundtrip(self):
        """Setting and getting allowed_model_ids preserves values."""
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/roundtrip",
            runtime_id="roundtrip",
            name="Roundtrip",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            registered_at=datetime.utcnow(),
        )
        models = ["us.anthropic.claude-sonnet-4-6", "us.anthropic.claude-haiku-4-5-20251001-v1:0"]
        agent.set_allowed_model_ids(models)
        self.assertEqual(agent.get_allowed_model_ids(), models)

    # ---- Registration with allowed_model_ids ----

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_register_agent_with_model_id_sets_allowed(self, mock_list, mock_describe):
        """Registering with model_id sets allowed_model_ids to [model_id]."""
        mock_describe.return_value = {"agentRuntimeName": "Test", "status": "READY"}
        mock_list.return_value = ["DEFAULT"]

        response = self.client.post("/api/agents", json={
            "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/reg-model",
            "model_id": "us.anthropic.claude-sonnet-4-6",
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["model_id"], "us.anthropic.claude-sonnet-4-6")
        self.assertEqual(data["allowed_model_ids"], ["us.anthropic.claude-sonnet-4-6"])

    @patch("app.routers.agents.describe_runtime")
    @patch("app.routers.agents.list_runtime_endpoints")
    def test_register_agent_with_allowed_model_ids(self, mock_list, mock_describe):
        """Registering with explicit allowed_model_ids preserves them."""
        mock_describe.return_value = {"agentRuntimeName": "Test", "status": "READY"}
        mock_list.return_value = ["DEFAULT"]

        response = self.client.post("/api/agents", json={
            "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/reg-allowed",
            "model_id": "us.anthropic.claude-sonnet-4-6",
            "allowed_model_ids": [
                "us.anthropic.claude-sonnet-4-6",
                "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            ],
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("us.anthropic.claude-sonnet-4-6", data["allowed_model_ids"])
        self.assertIn("us.anthropic.claude-haiku-4-5-20251001-v1:0", data["allowed_model_ids"])

    # ---- Response includes allowed_model_ids ----

    def test_agent_response_includes_allowed_model_ids(self):
        """GET /api/agents/{id} includes allowed_model_ids in response."""
        allowed = ["us.anthropic.claude-sonnet-4-6", "us.anthropic.claude-haiku-4-5-20251001-v1:0"]
        agent = self._create_agent_with_models(allowed_models=allowed)

        response = self.client.get(f"/api/agents/{agent.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["allowed_model_ids"], allowed)

    def test_agent_response_defaults_allowed_to_model_id(self):
        """When no allowed_model_ids set, response defaults to [model_id]."""
        agent = self._create_agent_with_models(allowed_models=None)

        response = self.client.get(f"/api/agents/{agent.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["allowed_model_ids"], ["us.anthropic.claude-sonnet-4-6"])

    # ---- PATCH allowed_model_ids ----

    def test_patch_allowed_model_ids(self):
        """PATCH /api/agents/{id} can update allowed_model_ids."""
        agent = self._create_agent_with_models(
            allowed_models=["us.anthropic.claude-sonnet-4-6"]
        )

        new_allowed = ["us.anthropic.claude-sonnet-4-6", "us.anthropic.claude-haiku-4-5-20251001-v1:0"]
        response = self.client.patch(
            f"/api/agents/{agent.id}",
            json={"allowed_model_ids": new_allowed},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["allowed_model_ids"], new_allowed)

    def test_patch_allowed_model_ids_rejects_invalid(self):
        """PATCH rejects model IDs not in SUPPORTED_MODELS."""
        agent = self._create_agent_with_models(
            allowed_models=["us.anthropic.claude-sonnet-4-6"]
        )

        response = self.client.patch(
            f"/api/agents/{agent.id}",
            json={"allowed_model_ids": ["invalid-model-id"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid model IDs", response.json()["detail"])

    # ---- Invoke with model_id ----

    def test_invoke_rejects_disallowed_model(self):
        """POST /api/agents/{id}/invoke rejects model_id not in allowed list."""
        allowed = ["us.anthropic.claude-sonnet-4-6"]
        agent = self._create_agent_with_models(allowed_models=allowed)

        response = self.client.post(
            f"/api/agents/{agent.id}/invoke",
            json={
                "prompt": "Hello",
                "model_id": "us.anthropic.claude-opus-4-6-v1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not in this agent's allowed models", response.json()["detail"])

    def test_invoke_accepts_allowed_model(self):
        """POST /api/agents/{id}/invoke accepts model_id in allowed list (returns streaming response)."""
        allowed = [
            "us.anthropic.claude-sonnet-4-6",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        ]
        agent = self._create_agent_with_models(allowed_models=allowed)
        agent.set_available_qualifiers(["DEFAULT"])
        self.session.commit()

        # We can't fully test SSE streaming in unit test, but we can verify the
        # request doesn't fail validation — it will fail at the actual AWS call.
        # The 400 we'd get is from qualifier or auth, not from model validation.
        response = self.client.post(
            f"/api/agents/{agent.id}/invoke",
            json={
                "prompt": "Hello",
                "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            },
        )
        # Should not be 400 for model validation (may be 500 from AWS call, that's OK)
        self.assertNotEqual(response.status_code, 400)

    def test_invoke_without_model_id_is_valid(self):
        """POST /api/agents/{id}/invoke without model_id still works."""
        allowed = ["us.anthropic.claude-sonnet-4-6"]
        agent = self._create_agent_with_models(allowed_models=allowed)
        agent.set_available_qualifiers(["DEFAULT"])
        self.session.commit()

        response = self.client.post(
            f"/api/agents/{agent.id}/invoke",
            json={"prompt": "Hello"},
        )
        # Should not be 400 (may be 500 from AWS call)
        self.assertNotEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
