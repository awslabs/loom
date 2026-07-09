"""Tests for A2A agent management endpoints."""
import json
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.a2a import A2aAgent, A2aAgentSkill, A2aAgentAccess

SAMPLE_AGENT_CARD = {
    "name": "Recipe Agent",
    "description": "An agent that helps with recipes",
    "url": "https://recipe-agent.example.com",
    "version": "1.0.0",
    "provider": {
        "organization": "Example Corp",
        "url": "https://example.com",
    },
    "capabilities": {
        "streaming": True,
        "pushNotifications": False,
        "stateTransitionHistory": True,
    },
    "authentication": {
        "schemes": ["Bearer"],
    },
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain", "application/json"],
    "skills": [
        {
            "id": "find-recipe",
            "name": "Find Recipe",
            "description": "Find a recipe by ingredients",
            "tags": ["cooking", "search"],
            "examples": ["Find a recipe with chicken and rice"],
        },
        {
            "id": "nutrition-info",
            "name": "Nutrition Info",
            "description": "Get nutrition information for a recipe",
            "tags": ["nutrition"],
        },
    ],
}


class TestA2aRouter(unittest.TestCase):
    """Test cases for /api/a2a/agents endpoints."""

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

    @patch("app.routers.a2a.fetch_agent_card")
    def _create_agent(self, mock_fetch, **overrides) -> dict:
        mock_fetch.return_value = SAMPLE_AGENT_CARD
        payload = {
            "base_url": "https://recipe-agent.example.com",
        }
        payload.update(overrides)
        response = self.client.post("/api/a2a/agents", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    # ----- CREATE -----
    def test_create_agent(self):
        data = self._create_agent()
        self.assertEqual(data["name"], "Recipe Agent")
        self.assertEqual(data["description"], "An agent that helps with recipes")
        self.assertEqual(data["agent_version"], "1.0.0")
        self.assertEqual(data["base_url"], "https://recipe-agent.example.com")
        self.assertEqual(data["provider_organization"], "Example Corp")
        self.assertTrue(data["capabilities"]["streaming"])
        self.assertEqual(data["authentication_schemes"], ["Bearer"])
        self.assertEqual(data["status"], "active")
        self.assertIsNotNone(data["last_fetched_at"])
        self.assertIsNotNone(data["created_at"])

    def test_create_agent_with_oauth2(self):
        data = self._create_agent(
            auth_type="oauth2",
            oauth2_well_known_url="https://auth.example.com/.well-known/openid-configuration",
            oauth2_client_id="my-client-id",
            oauth2_client_secret="my-test-secret",  # nosec B106
            oauth2_scopes="read write",
        )
        self.assertEqual(data["auth_type"], "oauth2")
        self.assertTrue(data["has_oauth2_secret"])
        self.assertNotIn("oauth2_client_secret", data)

    def test_create_agent_secret_not_in_response(self):
        data = self._create_agent(
            auth_type="oauth2",
            oauth2_well_known_url="https://auth.example.com/.well-known/openid-configuration",
            oauth2_client_id="cid",
            oauth2_client_secret="my-test-secret",  # nosec B106
        )
        self.assertNotIn("oauth2_client_secret", data)

    def test_create_agent_oauth2_missing_well_known(self):
        response = self.client.post("/api/a2a/agents", json={
            "base_url": "https://example.com",
            "auth_type": "oauth2",
            "oauth2_client_id": "cid",
        })
        self.assertEqual(response.status_code, 422)

    @patch("app.routers.a2a.fetch_agent_card")
    def test_create_agent_fetch_fails(self, mock_fetch):
        mock_fetch.side_effect = ValueError("Failed to fetch Agent Card")
        response = self.client.post("/api/a2a/agents", json={
            "base_url": "https://bad-agent.example.com",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Failed to fetch", response.json()["detail"])

    # ----- CREATE syncs skills -----
    def test_create_agent_syncs_skills(self):
        data = self._create_agent()
        response = self.client.get(f"/api/a2a/agents/{data['id']}/skills")
        self.assertEqual(response.status_code, 200)
        skills = response.json()
        self.assertEqual(len(skills), 2)
        self.assertEqual(skills[0]["skill_id"], "find-recipe")
        self.assertEqual(skills[0]["name"], "Find Recipe")
        self.assertEqual(skills[0]["tags"], ["cooking", "search"])
        self.assertEqual(skills[1]["skill_id"], "nutrition-info")

    # ----- LIST -----
    def test_list_agents_empty(self):
        response = self.client.get("/api/a2a/agents")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_agents(self):
        self._create_agent()
        self._create_agent()
        response = self.client.get("/api/a2a/agents")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    # ----- GET -----
    def test_get_agent(self):
        created = self._create_agent()
        response = self.client.get(f"/api/a2a/agents/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Recipe Agent")

    def test_get_agent_not_found(self):
        response = self.client.get("/api/a2a/agents/999")
        self.assertEqual(response.status_code, 404)

    # ----- UPDATE -----
    def test_update_agent(self):
        created = self._create_agent()
        response = self.client.put(f"/api/a2a/agents/{created['id']}", json={
            "status": "inactive",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "inactive")

    def test_update_agent_not_found(self):
        response = self.client.put("/api/a2a/agents/999", json={"status": "inactive"})
        self.assertEqual(response.status_code, 404)

    # ----- DELETE -----
    def test_delete_agent(self):
        created = self._create_agent()
        response = self.client.delete(f"/api/a2a/agents/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], created["id"])

        get_response = self.client.get(f"/api/a2a/agents/{created['id']}")
        self.assertEqual(get_response.status_code, 404)

    def test_delete_agent_not_found(self):
        response = self.client.delete("/api/a2a/agents/999")
        self.assertEqual(response.status_code, 404)

    # ----- TEST CONNECTION -----
    @patch("app.routers.a2a.svc_test_connection")
    def test_test_connection(self, mock_test):
        mock_test.return_value = {"success": True, "message": "Connected to Recipe Agent v1.0.0"}
        created = self._create_agent()
        response = self.client.post(f"/api/a2a/agents/{created['id']}/test-connection")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("Connected to", data["message"])

    def test_test_connection_not_found(self):
        response = self.client.post("/api/a2a/agents/999/test-connection")
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.a2a.svc_test_connection")
    def test_test_connection_pre_create(self, mock_test):
        mock_test.return_value = {"success": True, "message": "Connected to Recipe Agent v1.0.0"}
        response = self.client.post("/api/a2a/agents/test-connection", json={
            "base_url": "https://recipe-agent.example.com",
            "auth_type": "none",
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("Connected to", data["message"])

    # ----- AGENT CARD -----
    def test_get_agent_card(self):
        created = self._create_agent()
        response = self.client.get(f"/api/a2a/agents/{created['id']}/card")
        self.assertEqual(response.status_code, 200)
        card = response.json()
        self.assertEqual(card["name"], "Recipe Agent")
        self.assertEqual(len(card["skills"]), 2)

    @patch("app.routers.a2a.fetch_agent_card")
    def test_refresh_agent_card(self, mock_fetch):
        created = self._create_agent()

        updated_card = {**SAMPLE_AGENT_CARD, "version": "2.0.0"}
        mock_fetch.return_value = updated_card

        response = self.client.post(f"/api/a2a/agents/{created['id']}/card/refresh")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_version"], "2.0.0")

    @patch("app.routers.a2a.fetch_agent_card")
    def test_refresh_agent_card_failure_preserves_data(self, mock_fetch):
        created = self._create_agent()

        mock_fetch.side_effect = ValueError("Network error")
        response = self.client.post(f"/api/a2a/agents/{created['id']}/card/refresh")
        self.assertEqual(response.status_code, 400)

        # Original data preserved
        get_response = self.client.get(f"/api/a2a/agents/{created['id']}")
        self.assertEqual(get_response.json()["agent_version"], "1.0.0")

    # ----- SKILLS -----
    def test_get_skills(self):
        created = self._create_agent()
        response = self.client.get(f"/api/a2a/agents/{created['id']}/skills")
        self.assertEqual(response.status_code, 200)
        skills = response.json()
        self.assertEqual(len(skills), 2)

    def test_get_skills_agent_not_found(self):
        response = self.client.get("/api/a2a/agents/999/skills")
        self.assertEqual(response.status_code, 404)

    # ----- ACCESS RULES -----
    def test_get_access_rules_empty(self):
        created = self._create_agent()
        response = self.client.get(f"/api/a2a/agents/{created['id']}/access")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_update_access_rules(self):
        created = self._create_agent()
        response = self.client.put(f"/api/a2a/agents/{created['id']}/access", json={
            "rules": [
                {"persona_id": 1, "access_level": "all_skills"},
                {"persona_id": 2, "access_level": "selected_skills", "allowed_skill_ids": ["find-recipe"]},
            ]
        })
        self.assertEqual(response.status_code, 200)
        rules = response.json()
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0]["persona_id"], 1)
        self.assertEqual(rules[0]["access_level"], "all_skills")
        self.assertIsNone(rules[0]["allowed_skill_ids"])
        self.assertEqual(rules[1]["persona_id"], 2)
        self.assertEqual(rules[1]["access_level"], "selected_skills")
        self.assertEqual(rules[1]["allowed_skill_ids"], ["find-recipe"])

    def test_update_access_rules_replaces(self):
        created = self._create_agent()
        self.client.put(f"/api/a2a/agents/{created['id']}/access", json={
            "rules": [{"persona_id": 1, "access_level": "all_skills"}]
        })

        response = self.client.put(f"/api/a2a/agents/{created['id']}/access", json={
            "rules": [{"persona_id": 99, "access_level": "selected_skills", "allowed_skill_ids": ["x"]}]
        })
        rules = response.json()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["persona_id"], 99)

    def test_access_rules_agent_not_found(self):
        response = self.client.get("/api/a2a/agents/999/access")
        self.assertEqual(response.status_code, 404)

    # ----- CASCADE DELETE -----
    def test_delete_agent_cascades_skills_and_access(self):
        created = self._create_agent()
        aid = created["id"]

        self.client.put(f"/api/a2a/agents/{aid}/access", json={
            "rules": [{"persona_id": 1, "access_level": "all_skills"}]
        })

        self.client.delete(f"/api/a2a/agents/{aid}")

        self.assertEqual(self.session.query(A2aAgentSkill).filter(A2aAgentSkill.agent_id == aid).count(), 0)
        self.assertEqual(self.session.query(A2aAgentAccess).filter(A2aAgentAccess.agent_id == aid).count(), 0)


if __name__ == "__main__":
    unittest.main()
