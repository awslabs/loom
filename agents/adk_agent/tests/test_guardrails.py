"""Tests for Bedrock Guardrails support (issue #17)."""

import asyncio
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

from src.config import AgentConfig, GuardrailConfig, GuardrailRef, _parse_config
from google.adk.models.lite_llm import LiteLLMClient
from google.genai import types
from litellm.llms.bedrock.chat.invoke_handler import AWSEventStreamDecoder

from src.agent import build_model
from src.integrations import guardrails as g
from src.integrations.guardrails import (
    GUARDRAIL_NOT_ALLOWED_MESSAGE,
    GUARDRAIL_NOT_ALLOWED_TEXT,
    GuardrailSession,
    GuardrailTraceClient,
    resolve_invocation_guardrail,
    summarize_assessments,
)
import src.handler as handler


PII_EMAIL = "jane.doe@example.com"


def _guardrail(mode: str = "enforce", **kwargs) -> GuardrailConfig:
    base = dict(
        guardrail_id="abc123def456",
        guardrail_arn="arn:aws:bedrock:us-east-1:111122223333:guardrail/abc123def456",
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


_BLOCKED_INPUT = {"abc123def456": {
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
            "guardrail_id": "abc123def456",
            "guardrail_arn": "arn:aws:bedrock:us-east-1:111122223333:guardrail/abc123def456",
            "guardrail_version": "1",
            "mode": "monitor",
            "stream_processing_mode": "async",
            "redact_history": False,
            "source": "default",
            "allowed": [{"guardrail_id": "zzz999", "guardrail_arn": "", "guardrail_version": "DRAFT"}],
        }).guardrail
        self.assertEqual(cfg.guardrail_id, "abc123def456")
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


class TestResolveInvocationGuardrail(unittest.TestCase):
    def test_no_request_uses_primary(self) -> None:
        primary = _guardrail()
        self.assertEqual(resolve_invocation_guardrail(primary, None), (primary, True))
        self.assertEqual(resolve_invocation_guardrail(None, None), (None, True))

    def test_primary_accepted(self) -> None:
        primary = _guardrail()
        guardrail, ok = resolve_invocation_guardrail(primary, {"guardrail_id": "abc123def456", "guardrail_version": "1"})
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
            {"guardrail_id": "abc123def456"},
            {"guardrail_version": "1"},
            {},
            "abc123def456",
            {"guardrail_id": "", "guardrail_version": "1"},
        ):
            self.assertEqual(resolve_invocation_guardrail(primary, requested), (None, False), requested)
        # Any request on an agent with no guardrail is rejected.
        self.assertEqual(
            resolve_invocation_guardrail(None, {"guardrail_id": "abc123def456", "guardrail_version": "1"}),
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


class TestBuildModelGuardrail(unittest.TestCase):
    @patch("src.agent.LiteLlm")
    def test_no_guardrail_unchanged(self, mock_lite_llm: MagicMock) -> None:
        build_model(_config())
        mock_lite_llm.assert_called_once()
        self.assertNotIn("guardrailConfig", mock_lite_llm.call_args.kwargs)
        self.assertNotIn("llm_client", mock_lite_llm.call_args.kwargs)

    @patch("src.agent.LiteLlm")
    def test_enforce_passes_guardrail_config(self, mock_lite_llm: MagicMock) -> None:
        guardrail = _guardrail()
        build_model(_config(guardrail))
        kwargs = mock_lite_llm.call_args.kwargs
        self.assertEqual(kwargs["model"], "bedrock/us.anthropic.claude-sonnet-4-20250514")
        self.assertEqual(kwargs["guardrailConfig"], {
            "guardrailIdentifier": guardrail.guardrail_arn,
            "guardrailVersion": "1",
            "trace": "enabled",
        })
        self.assertIsInstance(kwargs["llm_client"], GuardrailTraceClient)

    @patch("src.agent.LiteLlm")
    def test_enforce_async_stream_mode(self, mock_lite_llm: MagicMock) -> None:
        build_model(_config(_guardrail(guardrail_arn="", stream_processing_mode="async")))
        cfg = mock_lite_llm.call_args.kwargs["guardrailConfig"]
        self.assertEqual(cfg["guardrailIdentifier"], "abc123def456")
        self.assertEqual(cfg["streamProcessingMode"], "async")

    @patch("src.agent.LiteLlm")
    def test_monitor_does_not_attach(self, mock_lite_llm: MagicMock) -> None:
        build_model(_config(_guardrail(mode="monitor")))
        self.assertNotIn("guardrailConfig", mock_lite_llm.call_args.kwargs)

    @patch("src.agent.LiteLlm")
    @patch("src.agent.resolve_secret", return_value="sk-test")
    def test_enforce_on_non_bedrock_warns_and_skips(self, _secret: MagicMock, mock_lite_llm: MagicMock) -> None:
        with self.assertLogs("src.agent", level="WARNING") as logs:
            build_model(_config(_guardrail(), provider="openai"))
        self.assertTrue(any("NOT be attached" in line for line in logs.output))
        self.assertNotIn("guardrailConfig", mock_lite_llm.call_args.kwargs)

    def test_real_litellm_forwards_guardrail_config(self) -> None:
        """The kwargs reach litellm.acompletion through ADK's LiteLlm unchanged."""
        from google.adk.models.llm_request import LlmRequest

        captured: dict = {}

        async def fake_acompletion(self_, model, messages, tools, **kwargs):
            captured.update(kwargs)

            async def gen():
                for c in _bedrock_stream(blocked=False):
                    yield c
            return gen()

        async def run() -> None:
            model = build_model(_config(_guardrail()))
            req = LlmRequest(
                model=model.model,
                contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
                config=types.GenerateContentConfig(),
            )
            with patch.object(LiteLLMClient, "acompletion", fake_acompletion):
                async for _ in model.generate_content_async(req, stream=True):
                    pass

        asyncio.run(run())
        self.assertEqual(captured["guardrailConfig"]["guardrailVersion"], "1")
        self.assertEqual(captured["guardrailConfig"]["trace"], "enabled")


def _bedrock_stream(blocked: bool = True, source: str = "INPUT") -> list:
    """Raw Bedrock ConverseStream chunks run through LiteLLM's own decoder."""
    decoder = AWSEventStreamDecoder(model="us.anthropic.claude-sonnet-4")
    assessment = {"contentPolicy": {"filters": [{"type": "HATE", "confidence": "HIGH", "action": "BLOCKED", "detected": True}]},
                  "sensitiveInformationPolicy": {"piiEntities": [{"type": "EMAIL", "match": PII_EMAIL, "action": "ANONYMIZED", "detected": True}]}}
    trace = {}
    if blocked:
        trace = {"inputAssessment": {"abc123def456": assessment}} if source == "INPUT" \
            else {"inputAssessment": {}, "outputAssessments": {"abc123def456": [assessment]}}
    raw = [
        {"start": {}, "contentBlockIndex": 0},
        {"delta": {"text": "Sorry, blocked." if blocked else "Hello"}, "contentBlockIndex": 0},
        {"contentBlockIndex": 0},
        {"stopReason": "guardrail_intervened" if blocked else "end_turn"},
        {"usage": {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3}, "metrics": {"latencyMs": 1},
         "trace": {"guardrail": trace}},
    ]
    return [decoder._chunk_parser(c) for c in raw]


class TestGuardrailTraceClient(unittest.IsolatedAsyncioTestCase):
    async def _run(self, chunks: list) -> list:
        async def fake_acompletion(self_, model, messages, tools, **kwargs):
            async def gen():
                for c in chunks:
                    yield c
            return gen()

        token = g.start_trace_capture()
        try:
            with patch.object(LiteLLMClient, "acompletion", fake_acompletion):
                stream = await GuardrailTraceClient().acompletion(model="m", messages=[], tools=None, stream=True)
                passed = [part async for part in stream]
            self.assertEqual(len(passed), len(chunks))  # chunks pass through unchanged
            return g.drain_trace_records()
        finally:
            g.stop_trace_capture(token)

    async def test_records_trace_and_finish_reason(self) -> None:
        records = await self._run(_bedrock_stream(blocked=True))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["finish_reason"], "content_filter")
        self.assertIn("inputAssessment", records[0]["guardrail_trace"])

    async def test_clean_call_not_recorded(self) -> None:
        records = await self._run(_bedrock_stream(blocked=False))
        # A trace block is present but empty; nothing intervened.
        session = GuardrailSession(_guardrail(), "s")
        self.assertEqual(session.observe_model_calls(records), [])

    async def test_no_sink_is_harmless(self) -> None:
        async def fake_acompletion(self_, model, messages, tools, **kwargs):
            async def gen():
                for c in _bedrock_stream(blocked=True):
                    yield c
            return gen()

        with patch.object(LiteLLMClient, "acompletion", fake_acompletion):
            stream = await GuardrailTraceClient().acompletion(model="m", messages=[], tools=None, stream=True)
            parts = [p async for p in stream]
        self.assertEqual(len(parts), 5)
        self.assertEqual(g.drain_trace_records(), [])

    def test_content_filter_without_trace_is_unknown(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            events = GuardrailSession(_guardrail(), "s").observe_model_calls(
                [{"finish_reason": "content_filter", "guardrail_trace": None}])
        self.assertEqual([e["guardrail"]["source"] for e in events], ["UNKNOWN"])
        self.assertEqual(events[0]["guardrail"]["policies"], [])
        self.assertIn("guardrail_intervention", out.getvalue())


def _text_event(text: str, partial: bool = True):
    event = MagicMock()
    event.error_message = None
    event.error_code = None
    event.finish_reason = None
    event.content = types.Content(role="model", parts=[types.Part(text=text)])
    event.partial = partial
    return event


def _safety_event(text: str):
    event = _text_event(text, partial=False)
    event.error_code = types.FinishReason.SAFETY
    event.finish_reason = types.FinishReason.SAFETY
    event.error_message = "Finished with SAFETY"
    return event


class TestRunTurnGuardrails(unittest.IsolatedAsyncioTestCase):
    """_run_turn with a fake runner; the fake runner drives the trace client like ADK would."""

    async def _collect(self, config: AgentConfig, runner_events_factory, payload_guardrail=None, prompt: str = "hi"):
        runner = MagicMock()
        runner.run_async = runner_events_factory
        session = MagicMock()
        session.id = "sess-1"
        kwargs = {} if payload_guardrail is None else {"guardrail_request": payload_guardrail}
        content = types.Content(role="user", parts=[types.Part(text=prompt)])
        out = io.StringIO()
        with patch("src.handler._get_runner", new=AsyncMock(return_value=runner)), \
             patch("src.handler._get_or_create_session", new=AsyncMock(return_value=session)), \
             patch("src.handler._config", config), \
             patch("src.handler._agent", MagicMock()), \
             patch("src.handler._default_model", None), \
             patch("src.handler._model_cache", {}), \
             patch("src.handler.build_model", return_value=MagicMock(name="built")) as mock_build, \
             redirect_stdout(out):
            events = [e async for e in handler._run_turn("sess-1", "actor", content, None, **kwargs)]
        return events, out.getvalue(), mock_build

    @staticmethod
    def _model_call_then(events_after: list, chunks: list | None):
        async def run_async(**kwargs):
            if chunks is not None:
                async def fake_acompletion(self_, model, messages, tools, **kw):
                    async def gen():
                        for c in chunks:
                            yield c
                    return gen()
                with patch.object(LiteLLMClient, "acompletion", fake_acompletion):
                    stream = await GuardrailTraceClient().acompletion(model="m", messages=[], tools=None, stream=True)
                    async for _ in stream:
                        pass
            for e in events_after:
                yield e
        return run_async

    async def test_rejected_override(self) -> None:
        called = []

        async def run_async(**kwargs):
            called.append(True)
            yield _text_event("nope")

        events, _, _ = await self._collect(
            _config(_guardrail()), run_async, payload_guardrail={"guardrail_id": "evil", "guardrail_version": "1"})
        self.assertEqual(events, [GUARDRAIL_NOT_ALLOWED_MESSAGE])
        self.assertEqual(called, [])

    async def test_override_on_agent_without_guardrail_rejected(self) -> None:
        events, _, _ = await self._collect(
            _config(None), self._model_call_then([_text_event("x")], None),
            payload_guardrail={"guardrail_id": "abc123def456", "guardrail_version": "1"})
        self.assertEqual(events, [GUARDRAIL_NOT_ALLOWED_MESSAGE])

    async def test_accepted_override_builds_guardrail_model(self) -> None:
        events, _, mock_build = await self._collect(
            _config(_guardrail()), self._model_call_then([_text_event("ok")], None),
            payload_guardrail={"guardrail_id": "zzz999", "guardrail_version": "DRAFT"})
        self.assertEqual(events, ["ok"])
        self.assertEqual(mock_build.call_args.args[0].guardrail.guardrail_id, "zzz999")

    async def test_enforce_trace_emits_one_event(self) -> None:
        events, stdout, _ = await self._collect(
            _config(_guardrail()),
            self._model_call_then([_text_event("Sorry, blocked."), _text_event("Sorry, blocked.", partial=False)],
                                  _bedrock_stream(blocked=True, source="INPUT")))
        g_events = [e["guardrail"] for e in events if isinstance(e, dict) and "guardrail" in e]
        self.assertEqual(len(g_events), 1)
        self.assertEqual(g_events[0]["source"], "INPUT")
        self.assertEqual(g_events[0]["action"], "intervened")
        self.assertIn({"policy": "contentPolicy", "type": "HATE", "action": "BLOCKED"}, g_events[0]["policies"])
        self.assertIn("Sorry, blocked.", events)
        self.assertEqual(stdout.count('"loom_event":"guardrail_intervention"'), 1)
        self.assertNotIn(PII_EMAIL, stdout)
        self.assertNotIn(PII_EMAIL, json.dumps(g_events))

    async def test_enforce_output_source(self) -> None:
        events, _, _ = await self._collect(
            _config(_guardrail()),
            self._model_call_then([_text_event("Sorry, blocked.")], _bedrock_stream(blocked=True, source="OUTPUT")))
        g_events = [e["guardrail"] for e in events if isinstance(e, dict) and "guardrail" in e]
        self.assertEqual([e["source"] for e in g_events], ["OUTPUT"])

    async def test_enforce_safety_finish_without_trace_is_unknown_and_not_error(self) -> None:
        events, _, _ = await self._collect(
            _config(_guardrail()), self._model_call_then([_safety_event("Sorry, blocked.")], None))
        self.assertIn("Sorry, blocked.", events)
        self.assertFalse(any(isinstance(e, str) and "Error" in e for e in events))
        g_events = [e["guardrail"] for e in events if isinstance(e, dict) and "guardrail" in e]
        self.assertEqual(g_events, [{
            "mode": "enforce", "source": "UNKNOWN", "action": "intervened",
            "guardrail_id": "abc123def456", "guardrail_version": "1", "policies": [],
        }])

    async def test_safety_without_guardrail_is_still_an_error(self) -> None:
        events, _, _ = await self._collect(_config(None), self._model_call_then([_safety_event("x")], None))
        self.assertEqual(events, ["\n\nError: Finished with SAFETY"])

    async def test_enforce_clean_call_no_event(self) -> None:
        events, stdout, _ = await self._collect(
            _config(_guardrail()), self._model_call_then([_text_event("Hello")], _bedrock_stream(blocked=False)))
        self.assertEqual(events, ["Hello"])
        self.assertNotIn("guardrail_intervention", stdout)

    async def test_monitor_mode(self) -> None:
        client = MagicMock()
        client.apply_guardrail.side_effect = lambda **kw: (
            {"action": "GUARDRAIL_INTERVENED", "assessments": [{"contentPolicy": {"filters": [
                {"type": "INSULTS", "action": "BLOCKED", "detected": True}]}}]}
            if kw["source"] == "INPUT" else {"action": "NONE", "assessments": []}
        )
        with patch("src.integrations.guardrails._get_client", return_value=client):
            events, stdout, _ = await self._collect(
                _config(_guardrail(mode="monitor")),
                self._model_call_then([_text_event("Hello "), _text_event("world")], None),
                prompt="you are dumb")
        self.assertEqual([e for e in events if isinstance(e, str)], ["Hello ", "world"])
        g_events = [e["guardrail"] for e in events if isinstance(e, dict) and "guardrail" in e]
        self.assertEqual(len(g_events), 1)
        self.assertEqual(g_events[0]["source"], "INPUT")
        self.assertEqual(g_events[0]["action"], "detected")
        calls = {c.kwargs["source"]: c.kwargs for c in client.apply_guardrail.call_args_list}
        self.assertEqual(calls["INPUT"]["content"], [{"text": {"text": "you are dumb"}}])
        self.assertEqual(calls["OUTPUT"]["content"], [{"text": {"text": "Hello world"}}])
        self.assertEqual(stdout.count("guardrail_intervention"), 1)

    async def test_monitor_failure_does_not_break_stream(self) -> None:
        client = MagicMock()
        client.apply_guardrail.side_effect = RuntimeError("AccessDenied")
        with patch("src.integrations.guardrails._get_client", return_value=client):
            events, _, _ = await self._collect(
                _config(_guardrail(mode="monitor")), self._model_call_then([_text_event("Hello")], None))
        self.assertEqual(events, ["Hello"])


class TestInvokePassesGuardrail(unittest.IsolatedAsyncioTestCase):
    async def test_payload_guardrail_forwarded(self) -> None:
        captured = {}

        async def fake_run_turn(session_id, actor_id, content, runtime_model_id=None, **kwargs):
            captured.update(kwargs)
            yield "ok"

        requested = {"guardrail_id": "zzz999", "guardrail_version": "DRAFT"}
        with patch("src.handler._run_turn", side_effect=fake_run_turn):
            [e async for e in handler.invoke({"prompt": "hi", "guardrail": requested})]
        self.assertEqual(captured, {"guardrail_request": requested})


class TestResolveModelForInvocation(unittest.TestCase):
    def test_runtime_override_keeps_guardrail_and_guardrail_override_cached_separately(self) -> None:
        config = _config(_guardrail())
        alt, _ = resolve_invocation_guardrail(config.guardrail, {"guardrail_id": "zzz999", "guardrail_version": "DRAFT"})
        with patch("src.handler._config", config), patch("src.handler._model_cache", {}), \
             patch("src.handler.build_model", side_effect=lambda cfg: MagicMock()) as mock_build:
            self.assertIsNone(handler._resolve_model_for_invocation(None, config.guardrail))
            m1 = handler._resolve_model_for_invocation("other", config.guardrail)
            self.assertEqual(mock_build.call_args.args[0].guardrail, config.guardrail)
            m2 = handler._resolve_model_for_invocation("other", alt)
            self.assertIsNot(m1, m2)
            self.assertIs(handler._resolve_model_for_invocation("other", alt), m2)
            self.assertEqual(mock_build.call_count, 2)


class TestWebSocketGuardrails(unittest.IsolatedAsyncioTestCase):
    async def _ws(self, prompt_msg: dict, run_turn_events: list) -> list:
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.receive_json = AsyncMock(side_effect=[prompt_msg, RuntimeError("closed")])
        captured = {}

        async def fake_run_turn(session_id, actor_id, content, runtime_model_id=None, **kwargs):
            captured.update(kwargs)
            for e in run_turn_events:
                yield e

        with patch("src.handler._run_turn", side_effect=fake_run_turn):
            await handler.ws_invoke(ws, None)
        self.captured = captured
        return [c.args[0] for c in ws.send_json.call_args_list]

    async def test_rejection_sends_error(self) -> None:
        requested = {"guardrail_id": "evil", "guardrail_version": "1"}
        sent = await self._ws({"type": "prompt", "prompt": "hi", "guardrail": requested}, [GUARDRAIL_NOT_ALLOWED_MESSAGE])
        self.assertEqual(self.captured, {"guardrail_request": requested})
        self.assertEqual(sent[0], {"type": "error", "content": GUARDRAIL_NOT_ALLOWED_TEXT})
        self.assertFalse(any(m.get("type") == "result" for m in sent))

    async def test_guardrail_event_shape(self) -> None:
        body = {"mode": "enforce", "source": "INPUT", "action": "intervened",
                "guardrail_id": "abc123def456", "guardrail_version": "1", "policies": []}
        sent = await self._ws({"type": "prompt", "prompt": "hi"}, ["Sorry.", {"guardrail": body}])
        self.assertIn({"type": "guardrail", "content": body}, sent)
        self.assertIn({"type": "result", "content": "Sorry."}, sent)


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
