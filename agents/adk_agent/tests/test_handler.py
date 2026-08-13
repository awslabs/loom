"""Tests for the handler entry point."""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from google.genai import types

from src.handler import (
    invoke,
    _run_turn,
    _extract_text,
    _extract_tool_use,
    _extract_confirmation_request,
    _build_confirmation_response_content,
    _REQUEST_CONFIRMATION_FUNCTION_CALL_NAME,
)


def _text_event(text: str, partial: bool = True, author: str = "loom_agent"):
    event = MagicMock()
    event.error_message = None
    event.content = types.Content(role="model", parts=[types.Part(text=text)])
    event.partial = partial
    event.turn_complete = None
    event.author = author
    return event


def _tool_use_event(name: str, call_id: str = "fc-1"):
    event = MagicMock()
    event.error_message = None
    fc = types.FunctionCall(name=name, id=call_id, args={})
    event.content = types.Content(role="model", parts=[types.Part(function_call=fc)])
    event.partial = False
    event.turn_complete = None
    return event


def _confirmation_event(tool_name: str, call_id: str = "fc-confirm-1"):
    event = MagicMock()
    event.error_message = None
    fc = types.FunctionCall(
        name=_REQUEST_CONFIRMATION_FUNCTION_CALL_NAME,
        id=call_id,
        args={
            "originalFunctionCall": {"name": tool_name, "args": {"x": 1}},
            "toolConfirmation": {"hint": "please confirm"},
        },
    )
    event.content = types.Content(role="model", parts=[types.Part(function_call=fc)])
    event.partial = False
    event.turn_complete = None
    return event


def _error_event(message: str):
    event = MagicMock()
    event.error_message = message
    event.content = None
    event.partial = False
    return event


class TestExtractHelpers(unittest.TestCase):
    def test_extract_text_returns_text(self) -> None:
        content = types.Content(role="model", parts=[types.Part(text="hello")])
        self.assertEqual(_extract_text(content), "hello")

    def test_extract_text_none_content(self) -> None:
        self.assertIsNone(_extract_text(None))

    def test_extract_tool_use_returns_name_and_id(self) -> None:
        fc = types.FunctionCall(name="my_tool", id="fc-1", args={})
        content = types.Content(role="model", parts=[types.Part(function_call=fc)])
        result = _extract_tool_use(content)
        self.assertEqual(result, {"name": "my_tool", "id": "fc-1"})

    def test_extract_tool_use_skips_confirmation_call(self) -> None:
        fc = types.FunctionCall(name=_REQUEST_CONFIRMATION_FUNCTION_CALL_NAME, id="fc-1", args={})
        content = types.Content(role="model", parts=[types.Part(function_call=fc)])
        self.assertIsNone(_extract_tool_use(content))

    def test_extract_confirmation_request(self) -> None:
        event = _confirmation_event("dangerous_tool", call_id="fc-99")
        result = _extract_confirmation_request(event.content)
        self.assertEqual(result["id"], "fc-99")
        self.assertEqual(result["name"], "dangerous_tool")
        self.assertEqual(result["reason"]["tool_name"], "dangerous_tool")
        self.assertEqual(result["reason"]["hint"], "please confirm")

    def test_extract_confirmation_request_none_when_absent(self) -> None:
        content = types.Content(role="model", parts=[types.Part(text="hi")])
        self.assertIsNone(_extract_confirmation_request(content))


class TestBuildConfirmationResponseContent(unittest.TestCase):
    def test_approve(self) -> None:
        content = _build_confirmation_response_content("fc-1", "y")
        fr = content.parts[0].function_response
        self.assertEqual(fr.id, "fc-1")
        self.assertEqual(fr.name, _REQUEST_CONFIRMATION_FUNCTION_CALL_NAME)
        self.assertTrue(fr.response["confirmed"])
        self.assertIsNone(fr.response["payload"])

    def test_trust(self) -> None:
        content = _build_confirmation_response_content("fc-1", "t")
        fr = content.parts[0].function_response
        self.assertTrue(fr.response["confirmed"])
        self.assertEqual(fr.response["payload"], {"trust": True})

    def test_deny(self) -> None:
        content = _build_confirmation_response_content("fc-1", "n")
        fr = content.parts[0].function_response
        self.assertFalse(fr.response["confirmed"])


class TestRunTurn(unittest.IsolatedAsyncioTestCase):
    """Tests for _run_turn's event-shape translation."""

    async def _collect(self, runner_events, runtime_model_id=None):
        mock_runner = MagicMock()

        async def fake_run_async(**kwargs):
            for e in runner_events:
                yield e

        mock_runner.run_async = fake_run_async

        mock_session = MagicMock()
        mock_session.id = "sess-1"

        with patch("src.handler._get_runner", new=AsyncMock(return_value=mock_runner)), \
             patch("src.handler._get_or_create_session", new=AsyncMock(return_value=mock_session)), \
             patch("src.handler._resolve_model_for_invocation", return_value=None):
            events = []
            async for event in _run_turn("sess-1", "loom-agent", None, runtime_model_id):
                events.append(event)
            return events

    async def test_streams_partial_text(self) -> None:
        events = await self._collect([_text_event("Hello "), _text_event("world")])
        self.assertEqual(events, ["Hello ", "world"])

    async def test_tool_use_yielded_as_dict(self) -> None:
        events = await self._collect([_tool_use_event("search_tool")])
        self.assertEqual(events, [{"tool_use": {"name": "search_tool", "id": "fc-1"}}])

    async def test_confirmation_request_yielded_as_interrupt(self) -> None:
        events = await self._collect([_confirmation_event("dangerous_tool", call_id="fc-99")])
        self.assertEqual(len(events), 1)
        interrupt = events[0]["interrupt"]
        self.assertEqual(interrupt["stopReason"], "interrupt")
        self.assertEqual(len(interrupt["interrupts"]), 1)
        self.assertEqual(interrupt["interrupts"][0]["id"], "fc-99")
        self.assertEqual(interrupt["interrupts"][0]["name"], "dangerous_tool")

    async def test_error_event_yields_error_text(self) -> None:
        events = await self._collect([_error_event("model unavailable")])
        self.assertEqual(len(events), 1)
        self.assertIn("model unavailable", events[0])

    async def test_non_partial_text_yielded_when_no_partial_seen(self) -> None:
        """A backend that never streams (no partial=True deltas) should still
        surface its complete text rather than silently dropping it."""
        events = await self._collect([_text_event("full response", partial=False)])
        self.assertEqual(events, ["full response"])

    async def test_final_non_partial_after_partials_not_duplicated(self) -> None:
        events = await self._collect([
            _text_event("Hello ", partial=True),
            _text_event("world", partial=True),
            _text_event("Hello world", partial=False),
        ])
        self.assertEqual(events, ["Hello ", "world"])


class TestInvokeEntrypoint(unittest.IsolatedAsyncioTestCase):
    """Tests for the invoke() entrypoint's payload branching."""

    async def test_normal_prompt_routes_to_run_turn(self) -> None:
        captured = {}

        async def fake_run_turn(session_id, actor_id, content, runtime_model_id=None):
            captured["session_id"] = session_id
            captured["actor_id"] = actor_id
            captured["content"] = content
            yield "ok"

        with patch("src.handler._run_turn", side_effect=fake_run_turn):
            events = [e async for e in invoke({"prompt": "hi", "session_id": "s1", "actor_id": "a1"})]

        self.assertEqual(events, ["ok"])
        self.assertEqual(captured["session_id"], "s1")
        self.assertEqual(captured["actor_id"], "a1")
        self.assertEqual(captured["content"].parts[0].text, "hi")

    async def test_interrupt_response_builds_confirmation_content(self) -> None:
        captured = {}

        async def fake_run_turn(session_id, actor_id, content, runtime_model_id=None):
            captured["content"] = content
            yield "resumed"

        payload = {
            "session_id": "s1",
            "interruptResponse": [
                {"interruptResponse": {"interruptId": "fc-99", "name": "dangerous_tool", "response": "y"}}
            ],
        }
        with patch("src.handler._run_turn", side_effect=fake_run_turn):
            events = [e async for e in invoke(payload)]

        self.assertEqual(events, ["resumed"])
        fr = captured["content"].parts[0].function_response
        self.assertEqual(fr.id, "fc-99")
        self.assertTrue(fr.response["confirmed"])


if __name__ == "__main__":
    unittest.main()
