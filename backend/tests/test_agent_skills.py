"""Tests for attaching approved SKILL registry records to an agent (issue #61)."""
import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.agent import Agent
from app.models.integration import Integration
from app.routers.agents import AgentCreateRequest, _build_system_prompt, _get_attached_skill_prompt_text


class TestAttachedSkillPromptText(unittest.TestCase):
    """Unit tests for _get_attached_skill_prompt_text and its effect on
    _build_system_prompt — exercised directly against real DB rows rather
    than through the HTTP layer, since none of this logic depends on auth."""

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

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _create_agent(self) -> Agent:
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-runtime",
            runtime_id="test-runtime",
            name="test-agent",
            region="us-east-1",
            account_id="123456789012",
            registered_at=datetime.utcnow(),
        )
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        return agent

    def _attach_skill(self, agent_id: int, record_id: str, enabled: bool = True) -> Integration:
        integration = Integration(
            agent_id=agent_id,
            integration_type="skill",
            integration_config=json.dumps({"record_id": record_id}),
            enabled=enabled,
        )
        self.session.add(integration)
        self.session.commit()
        self.session.refresh(integration)
        return integration

    def test_no_attached_skills_returns_empty_string(self):
        agent = self._create_agent()
        text = _get_attached_skill_prompt_text(agent.id, self.session)
        self.assertEqual(text, "")

    @patch("app.services.registry.get_registry_client")
    def test_approved_skill_content_is_included(self, mock_get_client):
        agent = self._create_agent()
        self._attach_skill(agent.id, "rec-skill-1")

        mock_client = MagicMock()
        mock_client.get_record.return_value = {
            "status": "APPROVED",
            "descriptors": {
                "agentSkillsDefinition": {
                    "additionalData": {"skillMd": {"data": "# Security Scan\n\nDo the scan."}},
                },
            },
        }
        mock_get_client.return_value = mock_client

        text = _get_attached_skill_prompt_text(agent.id, self.session)
        self.assertIn("# Security Scan", text)
        self.assertIn("## Attached Skills", text)

    @patch("app.services.registry.get_registry_client")
    def test_unapproved_skill_is_skipped(self, mock_get_client):
        """A skill that was approved at attach time but has since been
        un-approved (or was never approved) must not appear — this is
        re-checked live on every call, never cached."""
        agent = self._create_agent()
        self._attach_skill(agent.id, "rec-skill-pending")

        mock_client = MagicMock()
        mock_client.get_record.return_value = {
            "status": "PENDING_APPROVAL",
            "descriptors": {
                "agentSkillsDefinition": {
                    "additionalData": {"skillMd": {"data": "# Should not appear"}},
                },
            },
        }
        mock_get_client.return_value = mock_client

        text = _get_attached_skill_prompt_text(agent.id, self.session)
        self.assertEqual(text, "")

    @patch("app.services.registry.get_registry_client")
    def test_disabled_integration_is_skipped(self, mock_get_client):
        agent = self._create_agent()
        self._attach_skill(agent.id, "rec-skill-disabled", enabled=False)
        mock_get_client.return_value = MagicMock()

        text = _get_attached_skill_prompt_text(agent.id, self.session)
        self.assertEqual(text, "")
        mock_get_client.return_value.get_record.assert_not_called()

    @patch("app.services.registry.get_registry_client")
    def test_multiple_approved_skills_are_all_included(self, mock_get_client):
        agent = self._create_agent()
        self._attach_skill(agent.id, "rec-skill-1")
        self._attach_skill(agent.id, "rec-skill-2")

        def _get_record(record_id):
            return {
                "status": "APPROVED",
                "descriptors": {
                    "agentSkillsDefinition": {
                        "additionalData": {"skillMd": {"data": f"# Skill {record_id}"}},
                    },
                },
            }

        mock_client = MagicMock()
        mock_client.get_record.side_effect = _get_record
        mock_get_client.return_value = mock_client

        text = _get_attached_skill_prompt_text(agent.id, self.session)
        self.assertIn("# Skill rec-skill-1", text)
        self.assertIn("# Skill rec-skill-2", text)

    @patch("app.services.registry.get_registry_client")
    def test_registry_lookup_failure_is_skipped_not_raised(self, mock_get_client):
        """A transient registry error for one attached skill must not break
        the whole redeploy — skip it and continue."""
        agent = self._create_agent()
        self._attach_skill(agent.id, "rec-skill-broken")

        mock_client = MagicMock()
        mock_client.get_record.side_effect = RuntimeError("registry unavailable")
        mock_get_client.return_value = mock_client

        text = _get_attached_skill_prompt_text(agent.id, self.session)
        self.assertEqual(text, "")

    def test_build_system_prompt_appends_skill_text(self):
        request = AgentCreateRequest(source="deploy", agent_description="You are a helpful bot.")
        prompt = _build_system_prompt(request, skill_prompt_text="## Attached Skills\n\n# Security Scan")
        self.assertIn("You are a helpful bot.", prompt)
        self.assertIn("## Attached Skills", prompt)

    def test_build_system_prompt_without_skills_unchanged(self):
        request = AgentCreateRequest(source="deploy", agent_description="You are a helpful bot.")
        prompt = _build_system_prompt(request)
        self.assertEqual(prompt, "You are a helpful bot.")


if __name__ == "__main__":
    unittest.main()
