"""Tests for grandfathering agents off a model dropped from the catalog,
and surfacing that via AgentResponse.deprecated_model_ids (#64 follow-up:
"how should I handle agents that use a disabled model")."""
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
from app.dependencies.auth import get_current_user
from app.models.agent import Agent
from app.models.config_entry import ConfigEntry

VALID_CATALOG = [
    {"model_id": "us.anthropic.claude-sonnet-5"},
    {"model_id": "us.anthropic.claude-opus-4-8"},
]


def _admin_user():
    return type("UserInfo", (), {
        "sub": "test", "username": "admin", "groups": ["t-admin", "g-admins-super"],
        "scopes": ["agent:read", "agent:write", "admin:read", "admin:write"],
    })()


class TestModelDeprecation(unittest.TestCase):
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
        app.dependency_overrides[get_current_user] = _admin_user
        self.client = TestClient(app)

        self.get_merged_models_patcher = patch(
            "app.routers.agents.get_merged_models", return_value=VALID_CATALOG
        )
        self.get_merged_models_patcher.start()

    def tearDown(self):
        self.get_merged_models_patcher.stop()
        app.dependency_overrides.pop(get_current_user, None)
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _create_agent(self, model_id: str, allowed_models: list[str] | None = None) -> Agent:
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-deprecation-agent",
            runtime_id="test-deprecation-agent",
            name="Test Deprecation Agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            source="register",
            registered_at=datetime.utcnow(),
        )
        if allowed_models is not None:
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

    # ---- deprecated_model_ids on GET ----

    def test_no_deprecated_ids_when_all_models_current(self):
        agent = self._create_agent(
            "us.anthropic.claude-sonnet-5", allowed_models=["us.anthropic.claude-sonnet-5"]
        )
        response = self.client.get(f"/api/agents/{agent.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deprecated_model_ids"], [])

    def test_flags_deprecated_default_model(self):
        agent = self._create_agent("us.anthropic.claude-haiku-4-5-old", allowed_models=None)
        response = self.client.get(f"/api/agents/{agent.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deprecated_model_ids"], ["us.anthropic.claude-haiku-4-5-old"])

    def test_flags_deprecated_entry_in_allowed_model_ids_only(self):
        agent = self._create_agent(
            "us.anthropic.claude-sonnet-5",
            allowed_models=["us.anthropic.claude-sonnet-5", "us.amazon.nova-2-lite-old"],
        )
        response = self.client.get(f"/api/agents/{agent.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deprecated_model_ids"], ["us.amazon.nova-2-lite-old"])

    # ---- Grandfathered PATCH: model_id ----

    def test_patch_model_id_noop_on_deprecated_model_is_allowed(self):
        """Re-submitting the agent's own already-deprecated model_id must
        not 400 — a no-op PATCH (e.g. saving an unrelated field change
        through a form that round-trips the whole record) shouldn't be
        blocked by a model the agent already had."""
        agent = self._create_agent("us.anthropic.claude-haiku-4-5-old", allowed_models=None)
        response = self.client.patch(
            f"/api/agents/{agent.id}",
            json={"model_id": "us.anthropic.claude-haiku-4-5-old"},
        )
        self.assertEqual(response.status_code, 200)

    def test_patch_model_id_switch_to_different_deprecated_model_rejected(self):
        agent = self._create_agent("us.anthropic.claude-sonnet-5", allowed_models=None)
        response = self.client.patch(
            f"/api/agents/{agent.id}",
            json={"model_id": "us.anthropic.claude-haiku-4-5-old"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid model ID", response.json()["detail"])

    # ---- Grandfathered PATCH: allowed_model_ids ----

    def test_patch_allowed_model_ids_keeps_already_assigned_deprecated_model(self):
        agent = self._create_agent(
            "us.anthropic.claude-sonnet-5",
            allowed_models=["us.anthropic.claude-sonnet-5", "us.anthropic.claude-haiku-4-5-old"],
        )
        # Re-submit the same set (e.g. saving after toggling an unrelated model on).
        response = self.client.patch(
            f"/api/agents/{agent.id}",
            json={
                "allowed_model_ids": [
                    "us.anthropic.claude-sonnet-5",
                    "us.anthropic.claude-haiku-4-5-old",
                    "us.anthropic.claude-opus-4-8",
                ]
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()["allowed_model_ids"]),
            {"us.anthropic.claude-sonnet-5", "us.anthropic.claude-haiku-4-5-old", "us.anthropic.claude-opus-4-8"},
        )

    def test_patch_allowed_model_ids_can_drop_deprecated_model(self):
        agent = self._create_agent(
            "us.anthropic.claude-sonnet-5",
            allowed_models=["us.anthropic.claude-sonnet-5", "us.anthropic.claude-haiku-4-5-old"],
        )
        response = self.client.patch(
            f"/api/agents/{agent.id}",
            json={"allowed_model_ids": ["us.anthropic.claude-sonnet-5"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["allowed_model_ids"], ["us.anthropic.claude-sonnet-5"])

    def test_patch_allowed_model_ids_rejects_newly_added_deprecated_model(self):
        """Grandfathering only preserves what the agent already had — it
        must not let an admin newly assign a model that's neither in the
        catalog nor already on this agent."""
        agent = self._create_agent(
            "us.anthropic.claude-sonnet-5", allowed_models=["us.anthropic.claude-sonnet-5"]
        )
        response = self.client.patch(
            f"/api/agents/{agent.id}",
            json={
                "allowed_model_ids": [
                    "us.anthropic.claude-sonnet-5",
                    "us.anthropic.claude-haiku-4-5-old",
                ]
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("us.anthropic.claude-haiku-4-5-old", response.json()["detail"])

    def test_patch_allowed_model_ids_still_rejects_truly_unknown_model(self):
        agent = self._create_agent(
            "us.anthropic.claude-sonnet-5", allowed_models=["us.anthropic.claude-sonnet-5"]
        )
        response = self.client.patch(
            f"/api/agents/{agent.id}",
            json={"allowed_model_ids": ["totally-made-up-model"]},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
