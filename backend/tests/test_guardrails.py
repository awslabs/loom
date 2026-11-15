"""Tests for Bedrock Guardrails support (issue #17).

Loom is control plane only: it resolves the effective guardrail at deploy
time, validates per-invocation selections, relays agent-reported events and
reads intervention history from runtime logs.
"""
import json
import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models.agent import Agent
from app.models.config_entry import ConfigEntry
from app.services import guardrails as gr
from app.services.harness import _build_model_config, invoke_harness_stream

_GUARDRAIL_ENV = {
    "LOOM_GUARDRAIL_ID": "",
    "LOOM_GUARDRAIL_VERSION": "",
    "LOOM_GUARDRAIL_MODE": "",
    "LOOM_GUARDRAIL_LOCKED": "",
}

_ARN = "arn:aws:bedrock:us-east-1:123456789012:guardrail/abc123"


def _cfg(**overrides: object) -> dict:
    base = {
        "guardrail_id": "abc123",
        "guardrail_version": "1",
        "mode": "enforce",
        "stream_processing_mode": "sync",
        "redact_history": True,
        "allowed": [],
    }
    base.update(overrides)
    return base


class _DbTestCase(unittest.TestCase):
    """In-memory database shared by the endpoint and service tests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self) -> None:
        self.env = patch.dict(os.environ, _GUARDRAIL_ENV)
        self.env.start()
        self.session = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        import app.routers.agents as agents_mod
        self._original_session_local = agents_mod.SessionLocal
        agents_mod.SessionLocal = self.TestingSessionLocal
        self.client = TestClient(app)

    def tearDown(self) -> None:
        import app.routers.agents as agents_mod
        agents_mod.SessionLocal = self._original_session_local
        self.env.stop()
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _set_default(self, enabled: bool = True, locked: bool = False, **cfg: object) -> None:
        gr.save_guardrail_default(
            self.session,
            gr.GuardrailDefault(
                enabled=enabled, locked=locked,
                config=gr.GuardrailConfig(**_cfg(**cfg)) if enabled else None,
            ),
        )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
class TestGuardrailSchemas(unittest.TestCase):

    def test_accepts_id_and_arn(self) -> None:
        self.assertEqual(gr.GuardrailRef(guardrail_id="abc123").guardrail_version, "DRAFT")
        ref = gr.GuardrailRef(guardrail_id=_ARN, guardrail_version="3")
        self.assertEqual(ref.key(), ("abc123", "3"))

    def test_rejects_bad_identifier_and_version(self) -> None:
        with self.assertRaises(ValueError):
            gr.GuardrailRef(guardrail_id="bad id!")
        with self.assertRaises(ValueError):
            gr.GuardrailRef(guardrail_id="arn:aws:iam::1:role/x")
        with self.assertRaises(ValueError):
            gr.GuardrailRef(guardrail_id="abc123", guardrail_version="v1")

    def test_rejects_unknown_mode(self) -> None:
        with self.assertRaises(ValueError):
            gr.GuardrailConfig(**_cfg(mode="block"))


# ---------------------------------------------------------------------------
# Default resolution and deploy-time selection
# ---------------------------------------------------------------------------
class TestGuardrailResolution(_DbTestCase):

    def test_no_default_configured(self) -> None:
        default, source = gr.get_guardrail_default(self.session)
        self.assertFalse(default.enabled)
        self.assertEqual(source, "none")

    def test_env_fallback(self) -> None:
        with patch.dict(os.environ, {"LOOM_GUARDRAIL_ID": "envgr1", "LOOM_GUARDRAIL_MODE": "monitor",
                                     "LOOM_GUARDRAIL_LOCKED": "true"}):
            default, source = gr.get_guardrail_default(self.session)
        self.assertEqual(source, "environment")
        self.assertTrue(default.enabled and default.locked)
        self.assertEqual(default.config.guardrail_id, "envgr1")
        self.assertEqual(default.config.guardrail_version, "DRAFT")
        self.assertEqual(default.config.mode, "monitor")

    def test_invalid_env_is_ignored(self) -> None:
        with patch.dict(os.environ, {"LOOM_GUARDRAIL_ID": "envgr1", "LOOM_GUARDRAIL_MODE": "block"}):
            _, source = gr.get_guardrail_default(self.session)
        self.assertEqual(source, "none")

    def test_settings_override_env_even_when_disabled(self) -> None:
        self._set_default(enabled=False)
        with patch.dict(os.environ, {"LOOM_GUARDRAIL_ID": "envgr1"}):
            default, source = gr.get_guardrail_default(self.session)
        self.assertEqual(source, "settings")
        self.assertFalse(default.enabled)

    def test_inherit_default(self) -> None:
        self._set_default()
        selection, block = gr.resolve_agent_guardrail(self.session, None, "deploy", "bedrock")
        self.assertEqual(selection, "default")
        self.assertEqual(block["guardrail_id"], "abc123")
        self.assertEqual(block["source"], "default")
        self.assertEqual(block["mode"], "enforce")

    def test_inherit_without_default_is_unguarded(self) -> None:
        self.assertEqual(gr.resolve_agent_guardrail(self.session, None, "deploy", "bedrock"), ("default", None))

    def test_inherit_skips_unsupported_unlocked_default(self) -> None:
        # Enforce default + LiteLLM custom agent: can't enforce, not locked → not applied.
        self._set_default()
        self.assertEqual(gr.resolve_agent_guardrail(self.session, None, "deploy", "litellm"), ("default", None))

    def test_inherit_refuses_unsupported_locked_default(self) -> None:
        self._set_default(locked=True, mode="monitor")
        with self.assertRaises(gr.GuardrailError):
            gr.resolve_agent_guardrail(self.session, None, "harness", "bedrock")

    def test_custom_selection(self) -> None:
        req = gr.GuardrailSelection(selection="custom", config=gr.GuardrailConfig(**_cfg(
            guardrail_id=_ARN, mode="monitor",
            allowed=[{"guardrail_id": "zzz999", "guardrail_version": "DRAFT"}],
        )))
        selection, block = gr.resolve_agent_guardrail(self.session, req, "deploy", "litellm")
        self.assertEqual(selection, "custom")
        self.assertEqual(block["guardrail_id"], "abc123")
        self.assertEqual(block["guardrail_arn"], _ARN)
        self.assertEqual(block["source"], "agent")
        self.assertEqual(block["allowed"], [{"guardrail_id": "zzz999", "guardrail_arn": "", "guardrail_version": "DRAFT"}])

    def test_custom_requires_config(self) -> None:
        with self.assertRaises(gr.GuardrailError):
            gr.resolve_agent_guardrail(self.session, gr.GuardrailSelection(selection="custom"), "deploy", "bedrock")

    def test_none_selection(self) -> None:
        self._set_default()
        self.assertEqual(
            gr.resolve_agent_guardrail(self.session, gr.GuardrailSelection(selection="none"), "deploy", "bedrock"),
            ("none", None),
        )

    def test_locked_default_blocks_opt_out_and_monitor_downgrade(self) -> None:
        self._set_default(locked=True)
        with self.assertRaises(gr.GuardrailError):
            gr.resolve_agent_guardrail(self.session, gr.GuardrailSelection(selection="none"), "deploy", "bedrock")
        monitor = gr.GuardrailSelection(selection="custom", config=gr.GuardrailConfig(**_cfg(mode="monitor")))
        with self.assertRaises(gr.GuardrailError):
            gr.resolve_agent_guardrail(self.session, monitor, "deploy", "bedrock")
        # A different enforcing guardrail is still allowed under the lock.
        other = gr.GuardrailSelection(selection="custom", config=gr.GuardrailConfig(**_cfg(guardrail_id="def456")))
        self.assertEqual(gr.resolve_agent_guardrail(self.session, other, "deploy", "bedrock")[0], "custom")

    def test_support_matrix(self) -> None:
        self.assertEqual(gr.supported_modes("deploy", "bedrock"), {"enforce": True, "monitor": True})
        self.assertEqual(gr.supported_modes("deploy", "litellm"), {"enforce": False, "monitor": True})
        self.assertEqual(gr.supported_modes("harness", "bedrock"), {"enforce": True, "monitor": False})
        self.assertEqual(gr.supported_modes("harness", "litellm"), {"enforce": False, "monitor": False})
        self.assertEqual(gr.supported_modes("register", "bedrock"), {"enforce": False, "monitor": False})

    def test_support_violations_raise(self) -> None:
        enforce = gr.GuardrailSelection(selection="custom", config=gr.GuardrailConfig(**_cfg()))
        monitor = gr.GuardrailSelection(selection="custom", config=gr.GuardrailConfig(**_cfg(mode="monitor")))
        with self.assertRaisesRegex(gr.GuardrailError, "Enforce mode requires the Bedrock provider"):
            gr.resolve_agent_guardrail(self.session, enforce, "deploy", "openai")
        with self.assertRaisesRegex(gr.GuardrailError, "Monitor mode is not available"):
            gr.resolve_agent_guardrail(self.session, monitor, "harness", "bedrock")
        with self.assertRaisesRegex(gr.GuardrailError, "not supported"):
            gr.resolve_agent_guardrail(self.session, enforce, "harness", "litellm")

    def test_drift(self) -> None:
        self._set_default(guardrail_version="1")
        _, block = gr.resolve_agent_guardrail(self.session, None, "deploy", "bedrock")
        self.assertFalse(gr.compute_drift(self.session, "default", block, "deploy", "bedrock"))
        self._set_default(guardrail_version="2")
        self.assertTrue(gr.compute_drift(self.session, "default", block, "deploy", "bedrock"))
        # Custom/none selections never drift.
        self.assertFalse(gr.compute_drift(self.session, "custom", block, "deploy", "bedrock"))
        # Default added after an unguarded inheriting deploy → drift.
        self.assertTrue(gr.compute_drift(self.session, "default", None, "deploy", "bedrock"))

    def test_drift_ignores_default_the_agent_cannot_run(self) -> None:
        self._set_default(mode="monitor")
        self.assertFalse(gr.compute_drift(self.session, "default", None, "harness", "bedrock"))


# ---------------------------------------------------------------------------
# Per-invocation selection
# ---------------------------------------------------------------------------
class TestInvocationSelection(unittest.TestCase):

    BLOCK = gr.config_to_block(gr.GuardrailConfig(**_cfg(
        allowed=[{"guardrail_id": "zzz999", "guardrail_version": "DRAFT"}],
    )), "agent")

    def test_no_selection(self) -> None:
        self.assertIsNone(gr.validate_invocation_guardrail(self.BLOCK, None, None))

    def test_primary_selection_is_noop(self) -> None:
        self.assertIsNone(gr.validate_invocation_guardrail(self.BLOCK, _ARN, "1"))

    def test_allowed_alternate(self) -> None:
        ref = gr.validate_invocation_guardrail(self.BLOCK, "zzz999", None)
        self.assertEqual(ref["guardrail_id"], "zzz999")
        self.assertEqual(ref["guardrail_version"], "DRAFT")

    def test_rejects_unlisted_and_unguarded(self) -> None:
        with self.assertRaises(gr.GuardrailError):
            gr.validate_invocation_guardrail(self.BLOCK, "other1", "1")
        with self.assertRaises(gr.GuardrailError):
            gr.validate_invocation_guardrail(self.BLOCK, "zzz999", "2")
        with self.assertRaises(gr.GuardrailError):
            gr.validate_invocation_guardrail(None, "zzz999", "DRAFT")


# ---------------------------------------------------------------------------
# Harness model config
# ---------------------------------------------------------------------------
class TestHarnessGuardrailConfig(unittest.TestCase):

    def test_additional_params_enforce(self) -> None:
        block = gr.config_to_block(gr.GuardrailConfig(**_cfg(guardrail_arn=_ARN, stream_processing_mode="async")), "agent")
        params = gr.harness_additional_params(block)
        self.assertEqual(params, {"guardrailConfig": {
            "guardrailIdentifier": _ARN, "guardrailVersion": "1", "trace": "enabled", "streamProcessingMode": "async",
        }})

    def test_additional_params_override_and_monitor(self) -> None:
        block = gr.config_to_block(gr.GuardrailConfig(**_cfg()), "agent")
        params = gr.harness_additional_params(block, {"guardrail_id": "zzz999", "guardrail_arn": "", "guardrail_version": "DRAFT"})
        self.assertEqual(params["guardrailConfig"]["guardrailIdentifier"], "zzz999")
        self.assertNotIn("streamProcessingMode", params["guardrailConfig"])
        self.assertIsNone(gr.harness_additional_params(gr.config_to_block(gr.GuardrailConfig(**_cfg(mode="monitor")), "agent")))
        self.assertIsNone(gr.harness_additional_params(None))

    def test_model_config_carries_additional_params_for_bedrock_only(self) -> None:
        extra = {"guardrailConfig": {"guardrailIdentifier": "abc123", "guardrailVersion": "1"}}
        self.assertEqual(
            _build_model_config("bedrock", "m1", 100, additional_params=extra),
            {"bedrockModelConfig": {"modelId": "m1", "maxTokens": 100, "additionalParams": extra}},
        )
        self.assertNotIn("additionalParams", _build_model_config("bedrock", "m1"))
        self.assertNotIn("additionalParams", _build_model_config("litellm", "m1", additional_params=extra)["liteLlmModelConfig"])

    @patch("boto3.client")
    def test_invoke_stream_emits_guardrail_event(self, mock_client: MagicMock) -> None:
        mock_client.return_value.invoke_harness.return_value = {"stream": [
            {"contentBlockDelta": {"delta": {"text": "Sorry, I can't help with that."}}},
            {"messageStop": {"stopReason": "guardrail_intervened"}},
            {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 0}, "trace": {"guardrail": {
                "inputAssessment": {"abc123": {"contentPolicy": {"filters": [
                    {"type": "HATE", "confidence": "HIGH", "action": "BLOCKED", "detected": True},
                ]}, "sensitiveInformationPolicy": {"piiEntities": [
                    {"type": "EMAIL", "match": "jane@example.com", "action": "ANONYMIZED"},
                ]}}},
            }}}},
        ]}
        extra = {"guardrailConfig": {"guardrailIdentifier": "abc123", "guardrailVersion": "1", "trace": "enabled"}}
        events = list(invoke_harness_stream(
            harness_arn="arn:h", session_id="s1", prompt="hi", region="us-east-1",
            model_id="m1", additional_params=extra,
            guardrail_ref={"guardrail_id": "abc123", "guardrail_version": "1"},
        ))
        sent_model = mock_client.return_value.invoke_harness.call_args.kwargs["model"]
        self.assertEqual(sent_model["bedrockModelConfig"]["additionalParams"], extra)
        guardrail = [e["content"]["guardrail"] for e in events if e["type"] == "structured" and "guardrail" in e["content"]]
        self.assertEqual(len(guardrail), 1)
        self.assertEqual(guardrail[0]["source"], "INPUT")
        self.assertEqual(guardrail[0]["action"], "intervened")
        self.assertEqual(guardrail[0]["guardrail_id"], "abc123")
        self.assertNotIn("jane@example.com", json.dumps(events[1:]))
        self.assertIn({"policy": "contentPolicy", "action": "BLOCKED", "type": "HATE"}, guardrail[0]["policies"])


# ---------------------------------------------------------------------------
# Trace / log summarization never carries matched text
# ---------------------------------------------------------------------------
class TestSummaries(unittest.TestCase):

    def test_summarize_assessment_strips_match(self) -> None:
        policies = gr.summarize_assessment({
            "topicPolicy": {"topics": [{"name": "Investing", "type": "DENY", "action": "BLOCKED"}]},
            "wordPolicy": {"customWords": [{"match": "secretword", "action": "BLOCKED"}],
                           "managedWordLists": [{"match": "darn", "type": "PROFANITY", "action": "BLOCKED"}]},
            "sensitiveInformationPolicy": {"regexes": [{"name": "acct", "regex": "\\d+", "match": "1234", "action": "ANONYMIZED"}]},
            "contentPolicy": {"filters": [{"type": "INSULTS", "action": "NONE", "detected": False}]},
        })
        dumped = json.dumps(policies)
        for leaked in ("secretword", "darn", "1234", "\\\\d+"):
            self.assertNotIn(leaked, dumped)
        self.assertIn({"policy": "topicPolicy", "action": "BLOCKED", "name": "Investing"}, policies)
        self.assertIn({"policy": "wordPolicy", "action": "BLOCKED", "type": "CUSTOM_WORD"}, policies)
        self.assertEqual(len(policies), 4)  # the undetected NONE filter is dropped

    def test_summarize_trace_output(self) -> None:
        source, policies = gr.summarize_trace({"outputAssessments": {"abc123": [
            {"contextualGroundingPolicy": {"filters": [{"type": "GROUNDING", "score": 0.1, "threshold": 0.7, "action": "BLOCKED"}]}},
        ]}})
        self.assertEqual(source, "OUTPUT")
        self.assertEqual(policies, [{"policy": "contextualGroundingPolicy", "action": "BLOCKED", "type": "GROUNDING"}])
        self.assertEqual(gr.summarize_trace(None), ("UNKNOWN", []))

    def test_sanitize_event_whitelists_fields(self) -> None:
        clean = gr.sanitize_event({
            "mode": "monitor", "source": "OUTPUT", "action": "detected", "guardrail_id": "abc123",
            "guardrail_version": "1", "prompt": "leak", "policies": [{"policy": "x", "type": "EMAIL", "match": "leak"}],
        })
        self.assertNotIn("leak", json.dumps(clean))
        self.assertEqual(clean["policies"], [{"policy": "x", "type": "EMAIL"}])

    def test_parse_intervention_message(self) -> None:
        line = 'INFO:src.guardrails:{"loom_event": "guardrail_intervention", "session_id": "s1", ' \
               '"timestamp": "2026-11-03T12:00:00Z", "mode": "enforce", "source": "INPUT", "action": "intervened", ' \
               '"guardrail_id": "abc123", "guardrail_version": "1", "policies": []}'
        record = gr.parse_intervention_message(line)
        self.assertEqual(record["session_id"], "s1")
        self.assertEqual(record["action"], "intervened")
        self.assertIsNone(gr.parse_intervention_message("guardrail_intervention but not json"))
        self.assertIsNone(gr.parse_intervention_message('{"loom_event": "other", "x": "guardrail_intervention"}'))


# ---------------------------------------------------------------------------
# Bedrock / CloudWatch reads
# ---------------------------------------------------------------------------
class TestBedrockReads(unittest.TestCase):

    @patch("boto3.client")
    def test_list_guardrails_with_versions(self, mock_client: MagicMock) -> None:
        def list_guardrails(**kwargs):
            if "guardrailIdentifier" in kwargs:
                return {"guardrails": [{"version": "DRAFT"}, {"version": "1"}, {"version": "10"}, {"version": "2"}]}
            return {"guardrails": [{"id": "abc123", "arn": _ARN, "name": "pii-strict", "status": "READY"}]}
        mock_client.return_value.list_guardrails.side_effect = list_guardrails
        result = gr.list_guardrails("us-east-1")
        self.assertEqual(result, [{
            "guardrail_id": "abc123", "guardrail_arn": _ARN, "name": "pii-strict", "description": "",
            "status": "READY", "versions": ["DRAFT", "10", "2", "1"],
        }])

    @patch("boto3.client")
    def test_query_interventions(self, mock_client: MagicMock) -> None:
        logs = mock_client.return_value
        logs.start_query.return_value = {"queryId": "q1"}
        msg = json.dumps({"loom_event": "guardrail_intervention", "session_id": "s1", "timestamp": "t",
                          "mode": "monitor", "source": "OUTPUT", "action": "detected",
                          "guardrail_id": "abc123", "guardrail_version": "1", "policies": []})
        logs.get_query_results.return_value = {"status": "Complete", "results": [
            [{"field": "@timestamp", "value": "ts"}, {"field": "@message", "value": msg}],
            [{"field": "@message", "value": "unrelated line"}],
        ]}
        records = gr.query_interventions("/aws/bedrock-agentcore/runtimes/rt-DEFAULT", "us-east-1",
                                         session_id='s1" | fields x')
        query = logs.start_query.call_args.kwargs["queryString"]
        self.assertNotIn('"s1" | fields', query)  # session id is sanitized into the query
        self.assertEqual(records, [])  # sanitized id != record session → filtered out
        records = gr.query_interventions("/aws/bedrock-agentcore/runtimes/rt-DEFAULT", "us-east-1", session_id="s1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["mode"], "monitor")

    @patch("boto3.client")
    def test_query_interventions_missing_log_group(self, mock_client: MagicMock) -> None:
        mock_client.return_value.start_query.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "nope"}}, "StartQuery")
        self.assertEqual(gr.query_interventions("/missing", "us-east-1"), [])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
class TestGuardrailEndpoints(_DbTestCase):

    def _agent(self, source: str = "deploy", guardrail: dict | None = None, selection: str | None = "custom") -> Agent:
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/rt-g",
            runtime_id="rt-g", name="g_agent", status="READY", region="us-east-1",
            account_id="123456789012", source=source, registered_at=datetime.utcnow(),
            guardrail_selection=selection,
        )
        self.session.add(agent)
        self.session.commit()
        self.session.add(ConfigEntry(agent_id=agent.id, key="AGENT_CONFIG_JSON", value=json.dumps(
            {"model_id": "us.anthropic.claude-sonnet-4-6", "guardrail": guardrail})))
        self.session.commit()
        self.session.refresh(agent)
        return agent

    def test_default_get_put_roundtrip(self) -> None:
        resp = self.client.get("/api/settings/guardrail-default")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["source"], "none")
        resp = self.client.put("/api/settings/guardrail-default", json={
            "enabled": True, "locked": True, "config": _cfg(mode="monitor"),
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["source"], "settings")
        self.assertTrue(data["locked"])
        self.assertEqual(data["config"]["mode"], "monitor")

    def test_default_put_validation(self) -> None:
        resp = self.client.put("/api/settings/guardrail-default", json={"enabled": True, "locked": False})
        self.assertEqual(resp.status_code, 422)
        resp = self.client.put("/api/settings/guardrail-default", json={
            "enabled": True, "config": _cfg(guardrail_id="NOT VALID"),
        })
        self.assertEqual(resp.status_code, 422)

    @patch("app.services.guardrails.list_guardrails")
    def test_list_guardrails_endpoint(self, mock_list: MagicMock) -> None:
        mock_list.return_value = [{"guardrail_id": "abc123", "guardrail_arn": _ARN, "name": "g",
                                   "description": "", "status": "READY", "versions": ["DRAFT"]}]
        resp = self.client.get("/api/settings/guardrails")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["guardrail_id"], "abc123")
        mock_list.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "ListGuardrails")
        self.assertEqual(self.client.get("/api/settings/guardrails").status_code, 502)

    def test_agent_response_fields(self) -> None:
        self._set_default(guardrail_version="2")
        block = gr.config_to_block(gr.GuardrailConfig(**_cfg()), "default")
        agent = self._agent(guardrail=block, selection="default")
        data = self.client.get(f"/api/agents/{agent.id}").json()
        self.assertEqual(data["guardrail_selection"], "default")
        self.assertEqual(data["guardrail"]["guardrail_version"], "1")
        self.assertTrue(data["guardrail_drift"])
        self.assertEqual(data["guardrail_supported"], {"enforce": True, "monitor": True})

    def test_invoke_rejects_disallowed_guardrail(self) -> None:
        block = gr.config_to_block(gr.GuardrailConfig(**_cfg()), "agent")
        agent = self._agent(source="register", guardrail=block)
        resp = self.client.post(f"/api/agents/{agent.id}/invoke", json={
            "prompt": "hi", "guardrail_id": "zzz999", "guardrail_version": "DRAFT",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not allowed", resp.json()["detail"])

    @patch("app.routers.invocations.invoke_agent")
    def test_invoke_forwards_allowed_guardrail_and_relays_event(self, mock_invoke: MagicMock) -> None:
        block = gr.config_to_block(gr.GuardrailConfig(**_cfg(
            allowed=[{"guardrail_id": "zzz999", "guardrail_version": "DRAFT"}])), "agent")
        agent = self._agent(source="register", guardrail=block)
        mock_invoke.return_value = iter([
            {"type": "structured", "content": {"guardrail": {
                "mode": "enforce", "source": "INPUT", "action": "intervened", "guardrail_id": "zzz999",
                "guardrail_version": "DRAFT", "policies": [{"policy": "contentPolicy", "type": "HATE",
                                                            "action": "BLOCKED", "match": "secret"}]}}},
            {"type": "text", "content": "Blocked."},
        ])
        resp = self.client.post(f"/api/agents/{agent.id}/invoke", json={
            "prompt": "hi", "guardrail_id": "zzz999", "guardrail_version": "DRAFT",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_invoke.call_args.kwargs["guardrail"]["guardrail_id"], "zzz999")
        self.assertIn("event: guardrail", resp.text)
        self.assertNotIn("secret", resp.text)

    @patch("app.services.guardrails.query_interventions")
    def test_interventions_endpoint(self, mock_query: MagicMock) -> None:
        mock_query.return_value = [{"session_id": "s1", "action": "intervened"}]
        agent = self._agent()
        resp = self.client.get(f"/api/agents/{agent.id}/guardrails/interventions?hours=99999&limit=0")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["supported"])
        self.assertEqual(resp.json()["interventions"][0]["session_id"], "s1")
        kwargs = mock_query.call_args.kwargs
        self.assertEqual(kwargs["hours"], 24 * 14)
        self.assertEqual(kwargs["limit"], 1)
        self.assertEqual(mock_query.call_args.args[0], "/aws/bedrock-agentcore/runtimes/rt-g-DEFAULT")

    def test_export_includes_guardrail_selection(self) -> None:
        block = gr.config_to_block(gr.GuardrailConfig(**_cfg(mode="monitor")), "agent")
        agent = self._agent(guardrail=block, selection="custom")
        data = self.client.get(f"/api/agents/{agent.id}/export").json()
        self.assertEqual(data["guardrail"]["selection"], "custom")
        self.assertEqual(data["guardrail"]["config"]["mode"], "monitor")
        self.assertNotIn("source", data["guardrail"]["config"])
        agent.guardrail_selection = "default"
        self.session.commit()
        self.assertNotIn("guardrail", self.client.get(f"/api/agents/{agent.id}/export").json())

    def test_interventions_endpoint_harness_not_supported(self) -> None:
        agent = self._agent(source="harness")
        data = self.client.get(f"/api/agents/{agent.id}/guardrails/interventions").json()
        self.assertFalse(data["supported"])
        self.assertTrue(data["note"])


class TestHarnessDeployGuardrail(_DbTestCase):
    """Deploy-time integration through POST /api/agents (source=harness)."""

    def _post(self, guardrail: dict | None) -> object:
        body = {
            "tags": {"loom:group": "demo"},
            "source": "harness",
            "name": "guarded_harness",
            "model_id": "us.anthropic.claude-sonnet-4-6-v1",
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
        }
        if guardrail is not None:
            body["guardrail"] = guardrail
        return self.client.post("/api/agents", json=body)

    @patch("app.routers.agents.create_harness_api")
    def test_harness_deploy_bakes_guardrail(self, mock_create: MagicMock) -> None:
        mock_create.return_value = {"harnessId": "h-1", "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-1",
                                    "status": "CREATING", "environment": {}}
        resp = self._post({"selection": "custom", "config": _cfg(guardrail_arn=_ARN)})
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(
            mock_create.call_args.kwargs["additional_params"]["guardrailConfig"]["guardrailIdentifier"], _ARN,
        )
        agent = self.session.query(Agent).filter(Agent.name == "guarded_harness").first()
        self.assertEqual(agent.guardrail_selection, "custom")
        stored = next(e.value for e in agent.config_entries if e.key == "AGENT_CONFIG_JSON")
        self.assertEqual(json.loads(stored)["guardrail"]["guardrail_id"], "abc123")

    @patch("app.routers.agents.create_harness_api")
    def test_harness_deploy_rejects_monitor(self, mock_create: MagicMock) -> None:
        resp = self._post({"selection": "custom", "config": _cfg(mode="monitor")})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("Monitor mode is not available", resp.json()["detail"])
        mock_create.assert_not_called()
        self.assertIsNone(self.session.query(Agent).filter(Agent.name == "guarded_harness").first())

    @patch("app.routers.agents.create_harness_api")
    def test_harness_deploy_rejects_opt_out_of_locked_default(self, mock_create: MagicMock) -> None:
        self._set_default(locked=True)
        resp = self._post({"selection": "none"})
        self.assertEqual(resp.status_code, 422)
        mock_create.assert_not_called()

    @patch("app.routers.agents.create_harness_api")
    def test_harness_deploy_without_guardrail_unchanged(self, mock_create: MagicMock) -> None:
        mock_create.return_value = {"harnessId": "h-2", "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-2",
                                    "status": "CREATING", "environment": {}}
        resp = self._post(None)
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertIsNone(mock_create.call_args.kwargs["additional_params"])



class TestCustomDeployGuardrail(_DbTestCase):
    """Deploy-time validation through POST /api/agents (source=deploy)."""

    def test_enforce_rejected_for_litellm_provider_before_side_effects(self) -> None:
        resp = self.client.post("/api/agents", json={
            "tags": {"loom:group": "demo"},
            "source": "deploy",
            "name": "guarded_custom",
            "model_id": "claude-sonnet",
            "provider": "litellm",
            "guardrail": {"selection": "custom", "config": _cfg()},
        })
        self.assertEqual(resp.status_code, 422)
        self.assertIn("Enforce mode requires the Bedrock provider", resp.json()["detail"])
        self.assertIsNone(self.session.query(Agent).filter(Agent.name == "guarded_custom").first())


# ---------------------------------------------------------------------------
# Guardrail details snapshot (read at deploy/update time, stored on the agent)
# ---------------------------------------------------------------------------
_GET_GUARDRAIL_RESPONSE = {
    "guardrailId": "abc123", "guardrailArn": _ARN, "version": "1", "name": "pii-strict",
    "description": "Strict PII", "status": "READY", "updatedAt": datetime(2026, 11, 1, 12, 0, 0),
    "blockedInputMessaging": "Sorry, can't help.", "blockedOutputsMessaging": "Sorry, can't answer.",
    "kmsKeyArn": "arn:aws:kms:us-east-1:123456789012:key/k",
    "contentPolicy": {"filters": [
        {"type": "HATE", "inputStrength": "HIGH", "outputStrength": "HIGH", "inputAction": "BLOCK", "outputAction": "BLOCK"},
        {"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"},
    ]},
    "topicPolicy": {"topics": [{"name": "Investing", "definition": "Investment advice", "examples": ["a", "b"], "type": "DENY"}]},
    "wordPolicy": {"words": [{"text": "secretterm"}, {"text": "othersecret"}], "managedWordLists": [{"type": "PROFANITY"}]},
    "sensitiveInformationPolicy": {
        "piiEntities": [{"type": "EMAIL", "action": "ANONYMIZE", "outputAction": "BLOCK"}],
        "regexes": [{"name": "account-id", "pattern": "ACCT-\\d{6}", "action": "BLOCK"}],
    },
    "contextualGroundingPolicy": {"filters": [{"type": "GROUNDING", "threshold": 0.75, "action": "BLOCK", "enabled": True}]},
    "automatedReasoningPolicy": {"policies": ["arn:p1"]},
    "crossRegionDetails": {"guardrailProfileId": "us.guardrail.v1:0"},
}


class TestGuardrailDetails(unittest.TestCase):

    def test_summarize_guardrail(self) -> None:
        d = gr.summarize_guardrail(_GET_GUARDRAIL_RESPONSE)
        self.assertEqual(d["name"], "pii-strict")
        self.assertEqual(d["updated_at"], "2026-11-01T12:00:00")
        self.assertTrue(d["encrypted_with_cmk"])
        self.assertEqual(d["cross_region_profile"], "us.guardrail.v1:0")
        self.assertEqual(d["content_filters"][1]["output_strength"], "NONE")
        self.assertEqual(d["denied_topics"][0]["example_count"], 2)
        self.assertEqual(d["custom_word_count"], 2)
        # Only `action: ANONYMIZE` (no inputAction): Bedrock masks responses only.
        self.assertIsNone(d["pii_entities"][0]["input_action"])
        self.assertFalse(d["pii_entities"][0]["input_enabled"])
        self.assertEqual(d["pii_entities"][0]["output_action"], "BLOCK")
        self.assertEqual(d["regexes"], [{"name": "account-id", "input_action": "BLOCK", "output_action": "BLOCK",
                                         "input_enabled": True, "output_enabled": True}])
        self.assertEqual(d["contextual_grounding"][0]["threshold"], 0.75)
        self.assertEqual(d["automated_reasoning_policy_count"], 1)
        dumped = json.dumps(d)
        for leaked in ("secretterm", "othersecret", "ACCT-", "arn:aws:kms"):
            self.assertNotIn(leaked, dumped)

    def test_io_action_reflects_effective_direction(self) -> None:
        # General BLOCK applies to prompts and responses.
        self.assertEqual(gr._io_action({"action": "BLOCK"}),
                         {"input_action": "BLOCK", "output_action": "BLOCK", "input_enabled": True, "output_enabled": True})
        # General ANONYMIZE alone never evaluates prompts.
        self.assertEqual(gr._io_action({"action": "ANONYMIZE"}),
                         {"input_action": None, "output_action": "ANONYMIZE", "input_enabled": False, "output_enabled": True})
        # Explicit per-direction fields always win.
        self.assertEqual(gr._io_action({"action": "ANONYMIZE", "inputAction": "ANONYMIZE", "inputEnabled": True}),
                         {"input_action": "ANONYMIZE", "output_action": "ANONYMIZE", "input_enabled": True, "output_enabled": True})

    @patch("boto3.client")
    def test_fetch_uses_arn_region_and_version(self, mock_client: MagicMock) -> None:
        mock_client.return_value.get_guardrail.return_value = _GET_GUARDRAIL_RESPONSE
        d = gr.fetch_guardrail_details(
            {"guardrail_id": "abc123", "guardrail_arn": "arn:aws:bedrock:eu-west-1:123456789012:guardrail/abc123",
             "guardrail_version": "1"}, "us-east-1", strict=True)
        self.assertEqual(mock_client.call_args.kwargs["region_name"], "eu-west-1")
        mock_client.return_value.get_guardrail.assert_called_once_with(
            guardrailIdentifier="arn:aws:bedrock:eu-west-1:123456789012:guardrail/abc123", guardrailVersion="1")
        self.assertEqual(d["region"], "eu-west-1")
        self.assertNotIn("error", d)

    @patch("boto3.client")
    def test_fetch_not_found(self, mock_client: MagicMock) -> None:
        mock_client.return_value.get_guardrail.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "x"}}, "GetGuardrail")
        ref = {"guardrail_id": "abc123", "guardrail_version": "9"}
        with self.assertRaisesRegex(gr.GuardrailError, "version '9' was not found in us-east-1"):
            gr.fetch_guardrail_details(ref, "us-east-1", strict=True)
        self.assertIn("not found", gr.fetch_guardrail_details(ref, "us-east-1", strict=False)["error"])

    @patch("boto3.client")
    def test_fetch_access_denied_never_raises(self, mock_client: MagicMock) -> None:
        mock_client.return_value.get_guardrail.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "GetGuardrail")
        d = gr.fetch_guardrail_details({"guardrail_id": "abc123"}, "us-east-1", strict=True)
        self.assertEqual(d["error"], "Unable to read guardrail details (AccessDeniedException)")
        self.assertEqual(d["version"], "DRAFT")

    @patch("app.services.guardrails.fetch_guardrail_details")
    def test_snapshot_covers_primary_and_alternates(self, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = lambda ref, region, strict: {"guardrail_id": ref["guardrail_id"], "version": ref["guardrail_version"]}
        block = gr.config_to_block(gr.GuardrailConfig(**_cfg(
            allowed=[{"guardrail_id": "zzz999", "guardrail_version": "DRAFT"}])), "agent")
        snap = gr.snapshot_guardrail_details(block, "us-east-1")
        self.assertEqual([g["guardrail_id"] for g in snap["guardrails"]], ["abc123", "zzz999"])
        self.assertTrue(snap["fetched_at"].endswith("Z"))
        self.assertIsNone(gr.snapshot_guardrail_details(None, "us-east-1"))


class TestGuardrailDetailsEndpoints(_DbTestCase):

    def _harness_body(self, guardrail: dict) -> dict:
        return {
            "tags": {"loom:group": "demo"}, "source": "harness", "name": "detail_harness",
            "model_id": "us.anthropic.claude-sonnet-4-6-v1",
            "role_arn": "arn:aws:iam::123456789012:role/test-role", "guardrail": guardrail,
        }

    @patch("app.routers.agents.create_harness_api")
    @patch("boto3.client")
    def test_deploy_stores_details_and_response_returns_them(self, mock_client: MagicMock, mock_create: MagicMock) -> None:
        mock_client.return_value.get_guardrail.return_value = _GET_GUARDRAIL_RESPONSE
        mock_create.return_value = {"harnessId": "h-3", "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:harness/h-3",
                                    "status": "CREATING", "environment": {}}
        resp = self.client.post("/api/agents", json=self._harness_body({"selection": "custom", "config": _cfg()}))
        self.assertEqual(resp.status_code, 201, resp.text)
        agent = self.session.query(Agent).filter(Agent.name == "detail_harness").first()
        self.assertEqual(agent.get_guardrail_details()["guardrails"][0]["name"], "pii-strict")
        calls_before = mock_client.return_value.get_guardrail.call_count
        data = self.client.get(f"/api/agents/{agent.id}").json()
        self.assertEqual(data["guardrail_details"]["guardrails"][0]["denied_topics"][0]["name"], "Investing")
        # Loading the agent never calls Bedrock.
        self.assertEqual(mock_client.return_value.get_guardrail.call_count, calls_before)

    @patch("app.routers.agents.create_harness_api")
    @patch("boto3.client")
    def test_deploy_rejects_missing_guardrail_version(self, mock_client: MagicMock, mock_create: MagicMock) -> None:
        mock_client.return_value.get_guardrail.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "x"}}, "GetGuardrail")
        resp = self.client.post("/api/agents", json=self._harness_body({"selection": "custom", "config": _cfg(guardrail_version="7")}))
        self.assertEqual(resp.status_code, 422)
        self.assertIn("was not found", resp.json()["detail"])
        mock_create.assert_not_called()
        self.assertIsNone(self.session.query(Agent).filter(Agent.name == "detail_harness").first())

    @patch("app.services.guardrails.fetch_guardrail_details")
    def test_refresh_endpoint(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = {"guardrail_id": "abc123", "version": "1", "name": "refreshed"}
        agent = Agent(arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/rt-r", runtime_id="rt-r", name="r",
                      status="READY", region="us-east-1", account_id="123456789012", source="deploy",
                      registered_at=datetime.utcnow(), guardrail_selection="custom")
        self.session.add(agent)
        self.session.commit()
        self.session.add(ConfigEntry(agent_id=agent.id, key="AGENT_CONFIG_JSON", value=json.dumps(
            {"guardrail": gr.config_to_block(gr.GuardrailConfig(**_cfg()), "agent")})))
        self.session.commit()
        resp = self.client.post(f"/api/agents/{agent.id}/guardrails/refresh")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["guardrail_details"]["guardrails"][0]["name"], "refreshed")
        self.assertFalse(mock_fetch.call_args.args[2])  # non-strict: a vanished guardrail is recorded, not raised

    def test_refresh_requires_guardrail(self) -> None:
        agent = Agent(arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/rt-n", runtime_id="rt-n", name="n",
                      status="READY", region="us-east-1", account_id="123456789012", source="deploy",
                      registered_at=datetime.utcnow())
        self.session.add(agent)
        self.session.commit()
        self.assertEqual(self.client.post(f"/api/agents/{agent.id}/guardrails/refresh").status_code, 400)

if __name__ == "__main__":
    unittest.main()
