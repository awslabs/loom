"""Tests for Bedrock Guardrails support (issue #17)."""

import asyncio
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.config import AgentConfig, GuardrailConfig, GuardrailRef, _parse_config
from src.agent import _build_model
from src.integrations import guardrails as g
from src.integrations.guardrails import (
    GUARDRAIL_NOT_ALLOWED_MESSAGE,
    GUARDRAIL_NOT_ALLOWED_TEXT,
    GuardrailSession,
    resolve_invocation_guardrail,
    summarize_assessments,
)
import src.handler as handler


PII_EMAIL = "jane.doe@example.com"


def _guardrail(mode: str = "enforce", **kwargs) -> GuardrailConfig:
    base = dict(
        guardrail_id="testguardrail1",
        guardrail_arn="arn:aws:bedrock:us-east-1:111122223333:guardrail/testguardrail1",
        guardrail_version="1",
        mode=mode,
        allowed=[GuardrailRef(guardrail_id="zzz999", guardrail_version="DRAFT", guardrail_arn="")],
    )
    base.update(kwargs)
    return GuardrailConfig(**base)


def _config(guardrail: GuardrailConfig | None = None, provider: str = "bedrock") -> AgentConfig:
    return AgentConfig(
        system_prompt="Test prompt",
        model_id="us.anthropic.claude-sonnet-4-20250514",
        provider=provider,
        api_key_secret_arn="arn:secret" if provider != "bedrock" else "",
        guardrail=guardrail,
    )


def _trace_chunk(input_assessment: dict | None = None, output_assessments: dict | None = None) -> dict:
    guardrail_trace: dict = {}
    if input_assessment is not None:
        guardrail_trace["inputAssessment"] = input_assessment
    if output_assessments is not None:
        guardrail_trace["outputAssessments"] = output_assessments
    return {"event": {"metadata": {"usage": {}, "metrics": {}, "trace": {"guardrail": guardrail_trace}}}}


_BLOCKED_INPUT = {"testguardrail1": {
    "contentPolicy": {"filters": [{"type": "HATE", "confidence": "HIGH", "action": "BLOCKED", "detected": True}]},
    "sensitiveInformationPolicy": {"piiEntities": [{"type": "EMAIL", "match": PII_EMAIL, "action": "ANONYMIZED", "detected": True}]},
}}


class TestGuardrailConfigParsing(unittest.TestCase):
    def _parse(self, guardrail) -> AgentConfig:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_SYSTEM_PROMPT", None)
            return _parse_config({"system_prompt": "p", "model_id": "m", "guardrail": guardrail})

    def test_absent_or_null_is_none(self) -> None:
        self.assertIsNone(self._parse(None).guardrail)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_SYSTEM_PROMPT", None)
            self.assertIsNone(_parse_config({"system_prompt": "p", "model_id": "m"}).guardrail)

    def test_full_block(self) -> None:
        cfg = self._parse({
            "guardrail_id": "testguardrail1",
            "guardrail_arn": "arn:aws:bedrock:us-east-1:111122223333:guardrail/testguardrail1",
            "guardrail_version": "1",
            "mode": "monitor",
            "stream_processing_mode": "async",
            "redact_history": False,
            "source": "default",
            "allowed": [{"guardrail_id": "zzz999", "guardrail_arn": "", "guardrail_version": "DRAFT"}],
        }).guardrail
        self.assertEqual(cfg.guardrail_id, "testguardrail1")
        self.assertEqual(cfg.guardrail_version, "1")
        self.assertEqual(cfg.mode, "monitor")
        self.assertEqual(cfg.stream_processing_mode, "async")
        self.assertFalse(cfg.redact_history)
        self.assertEqual(cfg.source, "default")
        self.assertEqual(cfg.allowed, [GuardrailRef(guardrail_id="zzz999", guardrail_version="DRAFT", guardrail_arn="")])
        self.assertEqual(cfg.identifier, cfg.guardrail_arn)

    def test_defaults(self) -> None:
        cfg = self._parse({"guardrail_id": "abc", "guardrail_arn": "", "guardrail_version": "DRAFT"}).guardrail
        self.assertEqual(cfg.mode, "enforce")
        self.assertEqual(cfg.stream_processing_mode, "sync")
        self.assertTrue(cfg.redact_history)
        self.assertEqual(cfg.allowed, [])
        self.assertEqual(cfg.identifier, "abc")

    def test_invalid_block_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            self._parse({"guardrail_version": "1"})
        with self.assertRaises(ValueError):
            self._parse({"guardrail_id": "abc", "guardrail_version": "1", "mode": "block"})


class TestBuildModelGuardrail(unittest.TestCase):
    @patch("src.agent.BedrockModel")
    def test_no_guardrail_no_kwargs(self, mock_model: MagicMock) -> None:
        _build_model(_config())
        mock_model.assert_called_once_with(
            model_id="us.anthropic.claude-sonnet-4-20250514", max_tokens=4096, streaming=True,
        )

    @patch("src.agent.BedrockModel")
    def test_enforce_passes_guardrail_kwargs(self, mock_model: MagicMock) -> None:
        guardrail = _guardrail(stream_processing_mode="async", redact_history=False)
        _build_model(_config(guardrail))
        kwargs = mock_model.call_args.kwargs
        self.assertEqual(kwargs["guardrail_id"], guardrail.guardrail_arn)
        self.assertEqual(kwargs["guardrail_version"], "1")
        self.assertEqual(kwargs["guardrail_trace"], "enabled")
        self.assertEqual(kwargs["guardrail_stream_processing_mode"], "async")
        self.assertTrue(kwargs["guardrail_redact_input"])
        self.assertFalse(kwargs["guardrail_redact_output"])

    @patch("src.agent.BedrockModel")
    def test_enforce_uses_id_when_arn_empty(self, mock_model: MagicMock) -> None:
        _build_model(_config(_guardrail(guardrail_arn="")))
        self.assertEqual(mock_model.call_args.kwargs["guardrail_id"], "testguardrail1")

    @patch("src.agent.BedrockModel")
    def test_monitor_does_not_attach(self, mock_model: MagicMock) -> None:
        _build_model(_config(_guardrail(mode="monitor")))
        self.assertNotIn("guardrail_id", mock_model.call_args.kwargs)

    @patch("src.agent.OpenAIModel")
    @patch("src.agent.resolve_secret", return_value="sk-test")
    def test_enforce_on_non_bedrock_warns_and_skips(self, _secret: MagicMock, mock_model: MagicMock) -> None:
        with self.assertLogs("src.agent", level="WARNING") as logs:
            _build_model(_config(_guardrail(), provider="openai"))
        self.assertTrue(any("NOT be attached" in line for line in logs.output))
        self.assertNotIn("guardrail_id", mock_model.call_args.kwargs)


class TestSelectModel(unittest.TestCase):
    """Runtime model overrides keep the guardrail; guardrail overrides get their own model."""

    def setUp(self) -> None:
        self.config = _config(_guardrail())
        self.default_model = MagicMock(name="default")
        self.patches = [
            patch("src.handler._config", self.config),
            patch("src.handler._default_model", self.default_model),
            patch("src.handler._model_cache", {}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()

    @patch("src.handler._build_model")
    def test_default_when_no_override(self, mock_build: MagicMock) -> None:
        self.assertIs(handler._select_model(None, self.config.guardrail), self.default_model)
        mock_build.assert_not_called()

    @patch("src.handler._build_model")
    def test_runtime_model_override_keeps_guardrail(self, mock_build: MagicMock) -> None:
        handler._select_model("other-model", self.config.guardrail)
        built = mock_build.call_args.args[0]
        self.assertEqual(built.model_id, "other-model")
        self.assertEqual(built.guardrail, self.config.guardrail)

    @patch("src.handler._build_model", side_effect=lambda cfg: MagicMock(name=cfg.guardrail.guardrail_id))
    def test_guardrail_override_gets_own_cached_model(self, mock_build: MagicMock) -> None:
        alt, ok = resolve_invocation_guardrail(self.config.guardrail, {"guardrail_id": "zzz999", "guardrail_version": "DRAFT"})
        self.assertTrue(ok)
        m_primary = handler._select_model("other-model", self.config.guardrail)
        m_alt = handler._select_model("other-model", alt)
        self.assertIsNot(m_primary, m_alt)
        self.assertIs(handler._select_model("other-model", alt), m_alt)
        self.assertEqual(mock_build.call_count, 2)
        self.assertEqual(mock_build.call_args.args[0].guardrail.guardrail_id, "zzz999")
        # Guardrail override without a model override still builds a dedicated model.
        m_alt_default = handler._select_model(None, alt)
        self.assertIsNot(m_alt_default, self.default_model)
        self.assertEqual(mock_build.call_args.args[0].model_id, self.config.model_id)


class TestResolveInvocationGuardrail(unittest.TestCase):
    def test_no_request_uses_primary(self) -> None:
        primary = _guardrail()
        self.assertEqual(resolve_invocation_guardrail(primary, None), (primary, True))
        self.assertEqual(resolve_invocation_guardrail(None, None), (None, True))

    def test_primary_accepted(self) -> None:
        primary = _guardrail()
        guardrail, ok = resolve_invocation_guardrail(primary, {"guardrail_id": "testguardrail1", "guardrail_version": "1"})
        self.assertTrue(ok)
        self.assertIs(guardrail, primary)

    def test_allowed_accepted_keeps_primary_settings(self) -> None:
        primary = _guardrail(mode="monitor", stream_processing_mode="async")
        guardrail, ok = resolve_invocation_guardrail(primary, {"guardrail_id": "zzz999", "guardrail_version": "DRAFT"})
        self.assertTrue(ok)
        self.assertEqual(guardrail.guardrail_id, "zzz999")
        self.assertEqual(guardrail.guardrail_version, "DRAFT")
        self.assertEqual(guardrail.identifier, "zzz999")
        self.assertEqual(guardrail.mode, "monitor")
        self.assertEqual(guardrail.stream_processing_mode, "async")

    def test_rejections(self) -> None:
        primary = _guardrail()
        for requested in (
            {"guardrail_id": "zzz999", "guardrail_version": "1"},  # wrong version
            {"guardrail_id": "nope", "guardrail_version": "1"},
            {"guardrail_id": "testguardrail1"},
            {"guardrail_version": "1"},
            {},
            "testguardrail1",
            {"guardrail_id": "", "guardrail_version": "1"},
        ):
            self.assertEqual(resolve_invocation_guardrail(primary, requested), (None, False), requested)
        # Any request on an agent with no guardrail is rejected.
        self.assertEqual(
            resolve_invocation_guardrail(None, {"guardrail_id": "testguardrail1", "guardrail_version": "1"}),
            (None, False),
        )


class TestSummarizeAssessments(unittest.TestCase):
    def test_strips_match_and_regex(self) -> None:
        assessment = {
            "topicPolicy": {"topics": [{"name": "Investment advice", "type": "DENY", "action": "BLOCKED", "detected": True}]},
            "contentPolicy": {"filters": [{"type": "HATE", "confidence": "HIGH", "filterStrength": "HIGH", "action": "BLOCKED", "detected": True}]},
            "wordPolicy": {
                "customWords": [{"match": "secretword", "action": "BLOCKED", "detected": True}],
                "managedWordLists": [{"match": "badword", "type": "PROFANITY", "action": "BLOCKED", "detected": True}],
            },
            "sensitiveInformationPolicy": {
                "piiEntities": [{"match": PII_EMAIL, "type": "EMAIL", "action": "ANONYMIZED", "detected": True}],
                "regexes": [{"name": "employee-id", "match": "E-12345", "regex": "E-\\d+", "action": "BLOCKED", "detected": True}],
            },
            "contextualGroundingPolicy": {"filters": [{"type": "GROUNDING", "threshold": 0.7, "score": 0.2, "action": "BLOCKED", "detected": True}]},
            "invocationMetrics": {"guardrailProcessingLatency": 10},
        }
        policies = summarize_assessments([assessment])
        self.assertIn({"policy": "contentPolicy", "type": "HATE", "action": "BLOCKED"}, policies)
        self.assertIn({"policy": "topicPolicy", "name": "Investment advice", "action": "BLOCKED"}, policies)
        self.assertIn({"policy": "sensitiveInformationPolicy", "type": "EMAIL", "action": "ANONYMIZED"}, policies)
        self.assertIn({"policy": "wordPolicy", "type": "PROFANITY", "action": "BLOCKED"}, policies)
        self.assertIn({"policy": "contextualGroundingPolicy", "type": "GROUNDING", "action": "BLOCKED"}, policies)
        self.assertIn({"policy": "sensitiveInformationPolicy", "type": "REGEX", "name": "employee-id", "action": "BLOCKED"}, policies)
        dumped = json.dumps(policies)
        for leaked in (PII_EMAIL, "secretword", "badword", "E-12345", "E-\\\\d+", "match", "regex\"", "score", "threshold", "confidence"):
            self.assertNotIn(leaked, dumped)
        for p in policies:
            self.assertLessEqual(set(p), {"policy", "type", "name", "action"})

    def test_trace_mapping_and_dedupe(self) -> None:
        trace_input = {"g1": {"contentPolicy": {"filters": [{"type": "HATE", "action": "BLOCKED", "detected": True}]}}}
        trace_output = {"g1": [
            {"contentPolicy": {"filters": [{"type": "HATE", "action": "BLOCKED", "detected": True}]}},
            {"contentPolicy": {"filters": [{"type": "HATE", "action": "BLOCKED", "detected": True}]}},
        ]}
        self.assertEqual(summarize_assessments(trace_input), [{"policy": "contentPolicy", "type": "HATE", "action": "BLOCKED"}])
        self.assertEqual(len(summarize_assessments(trace_output)), 1)

    def test_untriggered_entries_skipped(self) -> None:
        assessment = {"contentPolicy": {"filters": [{"type": "HATE", "action": "NONE", "detected": False}]}}
        self.assertEqual(summarize_assessments([assessment]), [])


class _Runner:
    @staticmethod
    def run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def tearDownModule() -> None:
    # IsolatedAsyncioTestCase leaves no current event loop behind; other test
    # modules (test_handler, test_memory) rely on asyncio.get_event_loop().
    asyncio.set_event_loop(asyncio.new_event_loop())


class TestMonitorMode(unittest.IsolatedAsyncioTestCase):
    def _client(self, action_by_source: dict[str, str]) -> MagicMock:
        client = MagicMock()

        def apply_guardrail(**kwargs):
            action = action_by_source.get(kwargs["source"], "NONE")
            assessments = []
            if action == "GUARDRAIL_INTERVENED":
                assessments = [{"sensitiveInformationPolicy": {"piiEntities": [
                    {"match": PII_EMAIL, "type": "EMAIL", "action": "ANONYMIZED", "detected": True}]}}]
            return {"action": action, "outputs": [], "assessments": assessments}

        client.apply_guardrail.side_effect = apply_guardrail
        return client

    async def test_emits_only_on_intervened(self) -> None:
        client = self._client({"INPUT": "GUARDRAIL_INTERVENED", "OUTPUT": "NONE"})
        out = io.StringIO()
        with patch("src.integrations.guardrails._get_client", return_value=client), redirect_stdout(out):
            session = GuardrailSession(_guardrail(mode="monitor"), "sess-1")
            session.start_input(f"my email is {PII_EMAIL}")
            session.record_output("hello")
            events = await session.finish()
        self.assertEqual(len(events), 1)
        body = events[0]["guardrail"]
        self.assertEqual(body["source"], "INPUT")
        self.assertEqual(body["action"], "detected")
        self.assertEqual(body["mode"], "monitor")
        self.assertEqual(body["policies"], [{"policy": "sensitiveInformationPolicy", "type": "EMAIL", "action": "ANONYMIZED"}])
        sources = [c.kwargs["source"] for c in client.apply_guardrail.call_args_list]
        self.assertEqual(sorted(sources), ["INPUT", "OUTPUT"])
        call = client.apply_guardrail.call_args_list[0].kwargs
        self.assertEqual(call["guardrailIdentifier"], _guardrail().guardrail_arn)
        self.assertEqual(call["guardrailVersion"], "1")
        # Contract 4 log line: one line, marker present, no PII.
        lines = [l for l in out.getvalue().splitlines() if "guardrail_intervention" in l]
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0][lines[0].index("{"):])
        self.assertEqual(record["loom_event"], "guardrail_intervention")
        self.assertEqual(record["session_id"], "sess-1")
        self.assertTrue(record["timestamp"].endswith("Z"))
        self.assertNotIn(PII_EMAIL, out.getvalue())

    async def test_no_events_when_none(self) -> None:
        client = self._client({})
        with patch("src.integrations.guardrails._get_client", return_value=client):
            session = GuardrailSession(_guardrail(mode="monitor"), "s")
            session.start_input("hi")
            session.record_output("hello")
            self.assertEqual(await session.finish(), [])

    async def test_failure_is_swallowed(self) -> None:
        client = MagicMock()
        client.apply_guardrail.side_effect = RuntimeError("AccessDenied")
        with patch("src.integrations.guardrails._get_client", return_value=client):
            session = GuardrailSession(_guardrail(mode="monitor"), "s")
            session.start_input("hi")
            session.record_output("hello")
            with self.assertLogs("src.integrations.guardrails", level="WARNING"):
                self.assertEqual(await session.finish(), [])


def _mock_agent(chunks: list, stop_reason: str = "end_turn") -> MagicMock:
    agent = MagicMock()

    async def mock_stream(prompt, **kwargs):
        for c in chunks:
            yield c
        yield {"result": SimpleNamespace(stop_reason=stop_reason, interrupts=[])}

    agent.stream_async = MagicMock(side_effect=mock_stream)
    return agent


class TestHandlerGuardrails(unittest.TestCase):
    """End-to-end through handler.invoke with a mocked agent."""

    def _invoke(self, payload: dict, agent: MagicMock, config: AgentConfig) -> tuple[list, str]:
        async def collect():
            return [e async for e in handler.invoke(payload)]

        out = io.StringIO()
        with patch("src.handler._get_agent", return_value=agent), \
             patch("src.handler._config", config), \
             patch("src.handler._default_model", None), \
             patch("src.handler._model_cache", {}), \
             patch("src.handler._build_model", return_value=MagicMock()), \
             redirect_stdout(out):
            events = _Runner.run(collect())
        return events, out.getvalue()

    def test_rejected_override_yields_error_without_model_call(self) -> None:
        agent = _mock_agent([{"data": "should not run"}])
        events, _ = self._invoke(
            {"prompt": "hi", "guardrail": {"guardrail_id": "evil", "guardrail_version": "1"}},
            agent, _config(_guardrail()),
        )
        self.assertEqual(events, [GUARDRAIL_NOT_ALLOWED_MESSAGE])
        self.assertEqual(GUARDRAIL_NOT_ALLOWED_MESSAGE, "\n\nError: Requested guardrail is not allowed for this agent.")
        agent.stream_async.assert_not_called()

    def test_override_on_agent_without_guardrail_rejected(self) -> None:
        agent = _mock_agent([{"data": "x"}])
        events, _ = self._invoke(
            {"prompt": "hi", "guardrail": {"guardrail_id": "testguardrail1", "guardrail_version": "1"}},
            agent, _config(None),
        )
        self.assertEqual(events, [GUARDRAIL_NOT_ALLOWED_MESSAGE])
        agent.stream_async.assert_not_called()

    def test_accepted_override_selects_guardrail_model(self) -> None:
        agent = _mock_agent([{"data": "ok"}])
        built = MagicMock(name="alt-model")
        async def collect():
            return [e async for e in handler.invoke(
                {"prompt": "hi", "guardrail": {"guardrail_id": "zzz999", "guardrail_version": "DRAFT"}})]
        with patch("src.handler._get_agent", return_value=agent), \
             patch("src.handler._config", _config(_guardrail())), \
             patch("src.handler._default_model", None), \
             patch("src.handler._model_cache", {}), \
             patch("src.handler._build_model", return_value=built) as mock_build:
            events = _Runner.run(collect())
        self.assertEqual(events, ["ok"])
        self.assertIs(agent.model, built)
        self.assertEqual(mock_build.call_args.args[0].guardrail.guardrail_id, "zzz999")

    def test_enforce_trace_emits_event_once(self) -> None:
        agent = _mock_agent(
            [{"data": "Sorry, blocked."}, _trace_chunk(input_assessment=_BLOCKED_INPUT)],
            stop_reason="guardrail_intervened",
        )
        events, stdout = self._invoke({"prompt": "bad", "session_id": "s-1"}, agent, _config(_guardrail()))
        g_events = [e for e in events if isinstance(e, dict) and "guardrail" in e]
        self.assertEqual(len(g_events), 1)  # trace + stop_reason => still one event
        body = g_events[0]["guardrail"]
        self.assertEqual(body["source"], "INPUT")
        self.assertEqual(body["action"], "intervened")
        self.assertEqual(body["mode"], "enforce")
        self.assertEqual(body["guardrail_id"], "testguardrail1")
        self.assertEqual(body["guardrail_version"], "1")
        self.assertIn({"policy": "contentPolicy", "type": "HATE", "action": "BLOCKED"}, body["policies"])
        self.assertIn("Sorry, blocked.", events)
        self.assertEqual(stdout.count('"loom_event":"guardrail_intervention"'), 1)
        self.assertNotIn(PII_EMAIL, stdout)
        self.assertNotIn(PII_EMAIL, json.dumps(g_events))

    def test_enforce_output_assessment(self) -> None:
        output = {"testguardrail1": [{"topicPolicy": {"topics": [{"name": "Investment advice", "type": "DENY", "action": "BLOCKED", "detected": True}]}}]}
        agent = _mock_agent([_trace_chunk(input_assessment={}, output_assessments=output)], stop_reason="guardrail_intervened")
        events, _ = self._invoke({"prompt": "x"}, agent, _config(_guardrail()))
        g_events = [e["guardrail"] for e in events if isinstance(e, dict) and "guardrail" in e]
        self.assertEqual(len(g_events), 1)
        self.assertEqual(g_events[0]["source"], "OUTPUT")

    def test_enforce_stop_reason_only_emits_unknown(self) -> None:
        agent = _mock_agent([{"data": "Sorry."}], stop_reason="guardrail_intervened")
        events, stdout = self._invoke({"prompt": "x"}, agent, _config(_guardrail()))
        g_events = [e["guardrail"] for e in events if isinstance(e, dict) and "guardrail" in e]
        self.assertEqual(g_events, [{
            "mode": "enforce", "source": "UNKNOWN", "action": "intervened",
            "guardrail_id": "testguardrail1", "guardrail_version": "1", "policies": [],
        }])
        self.assertIn("guardrail_intervention", stdout)

    def test_enforce_no_intervention_no_event(self) -> None:
        clean = {"testguardrail1": {"contentPolicy": {"filters": []}}}
        agent = _mock_agent([{"data": "Hello"}, _trace_chunk(input_assessment=clean, output_assessments={})])
        events, stdout = self._invoke({"prompt": "x"}, agent, _config(_guardrail()))
        self.assertEqual(events, ["Hello"])
        self.assertNotIn("guardrail_intervention", stdout)

    def test_no_guardrail_ignores_trace(self) -> None:
        agent = _mock_agent([{"data": "Hello"}, _trace_chunk(input_assessment=_BLOCKED_INPUT)], stop_reason="guardrail_intervened")
        events, _ = self._invoke({"prompt": "x"}, agent, _config(None))
        self.assertEqual(events, ["Hello"])

    def test_monitor_mode_through_invoke(self) -> None:
        client = MagicMock()
        client.apply_guardrail.side_effect = lambda **kw: (
            {"action": "GUARDRAIL_INTERVENED", "assessments": [{"contentPolicy": {"filters": [
                {"type": "INSULTS", "action": "BLOCKED", "detected": True}]}}]}
            if kw["source"] == "OUTPUT" else {"action": "NONE", "assessments": []}
        )
        agent = _mock_agent([{"data": "Hello "}, {"data": "world"}])
        with patch("src.integrations.guardrails._get_client", return_value=client):
            events, _ = self._invoke({"prompt": "hi"}, agent, _config(_guardrail(mode="monitor"), provider="bedrock"))
        self.assertEqual(events[:2], ["Hello ", "world"])  # content unchanged
        g_events = [e["guardrail"] for e in events if isinstance(e, dict) and "guardrail" in e]
        self.assertEqual(len(g_events), 1)
        self.assertEqual(g_events[0]["source"], "OUTPUT")
        self.assertEqual(g_events[0]["action"], "detected")
        output_call = [c.kwargs for c in client.apply_guardrail.call_args_list if c.kwargs["source"] == "OUTPUT"][0]
        self.assertEqual(output_call["content"], [{"text": {"text": "Hello world"}}])

    def test_monitor_failure_does_not_break_stream(self) -> None:
        client = MagicMock()
        client.apply_guardrail.side_effect = RuntimeError("boom")
        agent = _mock_agent([{"data": "Hello"}])
        with patch("src.integrations.guardrails._get_client", return_value=client):
            events, _ = self._invoke({"prompt": "hi"}, agent, _config(_guardrail(mode="monitor")))
        self.assertEqual(events, ["Hello"])


class TestWebSocketGuardrails(unittest.IsolatedAsyncioTestCase):
    async def _ws(self, prompt_msg: dict, agent: MagicMock, config: AgentConfig) -> list:
        calls = {"n": 0}

        async def receive_json():
            calls["n"] += 1
            if calls["n"] == 1:
                return prompt_msg
            await asyncio.sleep(0.2)
            raise RuntimeError("closed")

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.receive_json = receive_json
        out = io.StringIO()
        with patch("src.handler._get_agent", return_value=agent), \
             patch("src.handler._config", config), \
             patch("src.handler._default_model", None), \
             patch("src.handler._model_cache", {}), \
             patch("src.handler._build_model", return_value=MagicMock()), \
             redirect_stdout(out):
            await handler.ws_invoke(ws, None)
        self.stdout = out.getvalue()
        return [c.args[0] for c in ws.send_json.call_args_list]

    async def test_rejection_sends_error_without_model_call(self) -> None:
        agent = MagicMock()
        sent = await self._ws(
            {"type": "prompt", "prompt": "hi", "guardrail": {"guardrail_id": "evil", "guardrail_version": "1"}},
            agent, _config(_guardrail()))
        self.assertEqual(sent[0], {"type": "error", "content": GUARDRAIL_NOT_ALLOWED_TEXT})
        self.assertEqual(GUARDRAIL_NOT_ALLOWED_TEXT, "Requested guardrail is not allowed for this agent.")
        agent.assert_not_called()
        self.assertFalse(any(m.get("type") == "result" for m in sent))

    async def test_enforce_stop_reason_sends_guardrail_message(self) -> None:
        result = MagicMock()
        result.stop_reason = "guardrail_intervened"
        result.__str__.return_value = "Sorry, blocked."
        agent = MagicMock(return_value=result)
        sent = await self._ws({"type": "prompt", "prompt": "bad", "session_id": "s"}, agent, _config(_guardrail()))
        self.assertIn({"type": "guardrail", "content": {
            "mode": "enforce", "source": "UNKNOWN", "action": "intervened",
            "guardrail_id": "testguardrail1", "guardrail_version": "1", "policies": [],
        }}, sent)
        types_sent = [m["type"] for m in sent]
        self.assertLess(types_sent.index("guardrail"), types_sent.index("result"))
        self.assertIn("guardrail_intervention", self.stdout)


class TestLogLine(unittest.TestCase):
    def test_single_line_json_with_marker(self) -> None:
        out = io.StringIO()
        event = g.build_event(_guardrail(), "OUTPUT", "intervened", [{"policy": "contentPolicy", "type": "HATE", "action": "BLOCKED"}])
        with redirect_stdout(out):
            g.log_intervention("sess-9", event)
        text = out.getvalue()
        self.assertEqual(text.count("\n"), 1)
        record = json.loads(text)
        self.assertEqual(record["loom_event"], "guardrail_intervention")
        self.assertEqual(record["source"], "OUTPUT")
        self.assertEqual(record["policies"], event["guardrail"]["policies"])
        self.assertEqual(
            set(record),
            {"loom_event", "session_id", "timestamp", "mode", "source", "action", "guardrail_id", "guardrail_version", "policies"},
        )


if __name__ == "__main__":
    unittest.main()
