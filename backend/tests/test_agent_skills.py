"""Tests for attaching approved SKILL registry records to an agent (issue #61)."""
import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.main import app
from app.models.agent import Agent
from app.models.config_entry import ConfigEntry
from app.models.integration import Integration
from app.routers.agents import (
    MAX_SYSTEM_PROMPT_BYTES,
    AgentCreateRequest,
    _CODE_INTERPRETER_PROMPT,
    _build_system_prompt,
    _get_attached_skill_prompt_text,
    _strip_generated_prompt_parts,
    _user_system_prompt,
    _validate_system_prompt_size,
)


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

    def test_build_system_prompt_does_not_repeat_code_interpreter_sentence(self):
        request = AgentCreateRequest(
            source="harness",
            agent_description="You are a helpful bot.",
            code_interpreter_enabled=True,
        )
        first = _build_system_prompt(request)
        # A stored prompt fed back in as the description must not grow.
        request.agent_description = first
        second = _build_system_prompt(request)
        self.assertEqual(second, first)
        self.assertEqual(first.count("sandboxed code interpreter"), 1)


SKILLS = "## Attached Skills\n\n# Skill pdf\n\nUse pypdf.\n\n---\n\n# Skill xlsx\n\nUse openpyxl."


class TestPromptRoundTrip(unittest.TestCase):
    """Issue #98: a built prompt fed back in as agent_description must not grow."""

    def test_skill_text_does_not_repeat_on_round_trip(self):
        request = AgentCreateRequest(source="harness", agent_description="You are a helpful bot.")
        first = _build_system_prompt(request, SKILLS)
        request.agent_description = first
        second = _build_system_prompt(request, SKILLS)
        self.assertEqual(second, first)
        self.assertEqual(second.count("## Attached Skills"), 1)

    def test_turning_the_code_interpreter_off_removes_its_sentence(self):
        built = _build_system_prompt(AgentCreateRequest(
            source="harness", agent_description="You are a helpful bot.", code_interpreter_enabled=True,
        ))
        rebuilt = _build_system_prompt(AgentCreateRequest(
            source="harness", agent_description=built, code_interpreter_enabled=False,
        ))
        self.assertEqual(rebuilt, "You are a helpful bot.")

    def test_already_repeated_prompt_is_recovered(self):
        """An agent saved before the fix, with the sentence and skills appended five times."""
        legacy = "\n\n".join(["You are a helpful bot."] + [_CODE_INTERPRETER_PROMPT, SKILLS] * 5)
        self.assertEqual(_strip_generated_prompt_parts(legacy), "You are a helpful bot.")

    def test_strip_keeps_the_users_text_byte_for_byte(self):
        text = "Line one.\nLine two.\n\n\n## My own heading\n\n  Indented paragraph.  \n"
        self.assertEqual(_strip_generated_prompt_parts(text), text)
        self.assertEqual(_strip_generated_prompt_parts(text + "\n\n" + SKILLS), text)

    def test_strip_of_skills_only_prompt_is_empty(self):
        self.assertEqual(_strip_generated_prompt_parts(SKILLS), "")

    def test_user_system_prompt_has_no_generated_parts(self):
        request = AgentCreateRequest(
            source="harness", agent_description="You are a helpful bot.\n\n" + _CODE_INTERPRETER_PROMPT,
            behavioral_guidelines="Be brief.", code_interpreter_enabled=True,
        )
        self.assertEqual(_user_system_prompt(request), "You are a helpful bot.\n\nBe brief.")

    def test_size_check_ignores_generated_parts(self):
        """A legacy prompt that only exceeds the limit because of repeated
        generated text must not block the redeploy that would fix it."""
        bloated = "\n\n".join(["You are a helpful bot."] + [_CODE_INTERPRETER_PROMPT] * 40)
        self.assertGreater(len(bloated.encode("utf-8")), MAX_SYSTEM_PROMPT_BYTES)
        _validate_system_prompt_size(AgentCreateRequest(source="harness", agent_description=bloated))
        too_long = AgentCreateRequest(source="harness", agent_description="x" * (MAX_SYSTEM_PROMPT_BYTES + 1))
        with self.assertRaises(HTTPException):
            _validate_system_prompt_size(too_long)


class TestExportReturnsUserPrompt(unittest.TestCase):
    """The edit form loads an agent through export, then sends system_prompt
    back as agent_description, so export must return the user's own prompt."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        self.db = self.SessionLocal()
        app.dependency_overrides[get_db] = lambda: self.db
        groups = ["g-admins-super"]
        user = UserInfo(sub="admin", username="admin", groups=groups, scopes=derive_scopes(groups))
        app.dependency_overrides[get_current_user] = lambda: user
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _agent(self, built_prompt: str, user_prompt: str | None) -> int:
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-west-2:123456789012:harness/h-1", runtime_id="h-1",
            name="bot", region="us-west-2", account_id="123456789012", source="harness",
            user_system_prompt=user_prompt,
        )
        self.db.add(agent)
        self.db.commit()
        self.db.add(ConfigEntry(agent_id=agent.id, key="AGENT_CONFIG_JSON",
                                value=json.dumps({"system_prompt": built_prompt}), source="env_var"))
        self.db.commit()
        return agent.id

    def _exported_prompt(self, agent_id: int) -> str | None:
        resp = self.client.get(f"/api/agents/{agent_id}/export")
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json().get("system_prompt")

    def test_export_returns_the_stored_user_prompt(self):
        built = "You are a helpful bot.\n\n" + _CODE_INTERPRETER_PROMPT + "\n\n" + SKILLS
        agent_id = self._agent(built, "You are a helpful bot.")
        self.assertEqual(self._exported_prompt(agent_id), "You are a helpful bot.")

    def test_export_of_an_agent_saved_before_the_fix_strips_generated_parts(self):
        built = "\n\n".join(["You are a helpful bot."] + [_CODE_INTERPRETER_PROMPT, SKILLS] * 5)
        agent_id = self._agent(built, None)
        self.assertEqual(self._exported_prompt(agent_id), "You are a helpful bot.")


if __name__ == "__main__":
    unittest.main()
