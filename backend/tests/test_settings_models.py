"""Tests for the enabled-models settings endpoint's model-id validation."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db


class TestUpdateEnabledModelsValidation(unittest.TestCase):
    """update_enabled_models must validate against the dynamic merged
    catalog, not just the static models.json list — otherwise admins can
    never enable a dynamically-discovered LiteLLM or Bedrock model id."""

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

    @patch("app.services.model_catalog.get_merged_models")
    def test_accepts_dynamically_discovered_model_id(self, mock_get_merged_models):
        mock_get_merged_models.return_value = [
            {"model_id": "gpt-4o", "display_name": "gpt-4o", "provider": "litellm"},
        ]

        response = self.client.put("/api/settings/models", json={"model_ids": ["gpt-4o"]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model_ids"], ["gpt-4o"])

    @patch("app.services.model_catalog.get_merged_models")
    def test_rejects_truly_unknown_model_id(self, mock_get_merged_models):
        mock_get_merged_models.return_value = [
            {"model_id": "gpt-4o", "display_name": "gpt-4o", "provider": "litellm"},
        ]

        response = self.client.put("/api/settings/models", json={"model_ids": ["not-a-real-model"]})

        self.assertEqual(response.status_code, 400)
        self.assertIn("not-a-real-model", response.json()["detail"])


class TestModelsEndpointsSplit(unittest.TestCase):
    """GET /api/agents/models must stay Bedrock-only (never touch the
    LiteLLM proxy); GET /api/agents/models/litellm is the separate,
    on-demand endpoint scoped to just the proxy's live catalog."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
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

    @patch("app.routers.agents.get_litellm_models_live")
    @patch("app.routers.agents.get_bedrock_models")
    def test_models_endpoint_only_calls_bedrock(self, mock_bedrock, mock_litellm):
        mock_bedrock.return_value = [{"model_id": "anthropic.claude-sonnet-4-6", "provider": "bedrock"}]

        response = self.client.get("/api/agents/models")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"model_id": "anthropic.claude-sonnet-4-6", "provider": "bedrock"}])
        mock_bedrock.assert_called_once()
        mock_litellm.assert_not_called()

    @patch("app.routers.agents.get_bedrock_models")
    @patch("app.routers.agents.get_litellm_models_live")
    def test_litellm_endpoint_only_calls_litellm(self, mock_litellm, mock_bedrock):
        mock_litellm.return_value = [{"model_id": "gpt-4o", "provider": "litellm"}]

        response = self.client.get("/api/agents/models/litellm")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"model_id": "gpt-4o", "provider": "litellm"}])
        mock_litellm.assert_called_once()
        mock_bedrock.assert_not_called()

    @patch("app.routers.agents.get_litellm_models_live")
    def test_litellm_endpoint_respects_enabled_models_allowlist(self, mock_litellm):
        from app.models.site_setting import SiteSetting

        mock_litellm.return_value = [
            {"model_id": "gpt-4o", "provider": "litellm"},
            {"model_id": "claude-3-opus", "provider": "litellm"},
        ]
        # Seed the allowlist directly — bypasses update_enabled_models'
        # validation (which calls the real, unmocked get_merged_models).
        self.session.add(SiteSetting(key="enabled_model_ids", value='["gpt-4o"]'))
        self.session.commit()

        response = self.client.get("/api/agents/models/litellm")

        self.assertEqual([m["model_id"] for m in response.json()], ["gpt-4o"])


class TestProvidersAvailability(unittest.TestCase):
    """GET /api/agents/providers marks litellm unavailable until its
    connection is enabled — bedrock is always available."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
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

    @patch("app.services.litellm.is_enabled", return_value=False)
    def test_litellm_unavailable_when_disabled(self, mock_is_enabled):
        response = self.client.get("/api/agents/providers")

        self.assertEqual(response.status_code, 200)
        by_id = {p["id"]: p for p in response.json()}
        self.assertTrue(by_id["bedrock"]["available"])
        self.assertFalse(by_id["litellm"]["available"])

    @patch("app.services.litellm.is_enabled", return_value=True)
    def test_litellm_available_when_enabled(self, mock_is_enabled):
        response = self.client.get("/api/agents/providers")

        self.assertEqual(response.status_code, 200)
        by_id = {p["id"]: p for p in response.json()}
        self.assertTrue(by_id["litellm"]["available"])


if __name__ == "__main__":
    unittest.main()
