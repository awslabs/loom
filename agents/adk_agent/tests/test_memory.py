"""Tests for AgentCore Memory plugin (async)."""

import asyncio
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from google.genai import types

from src.integrations.memory import MemoryPlugin


def run_async(coro):
    """Helper to run an async coroutine in tests.

    Uses asyncio.run() (fresh event loop per call) rather than
    asyncio.get_event_loop(), since the latter can pick up a loop already
    closed by another test file's IsolatedAsyncioTestCase when the full
    suite runs in one process, causing a RuntimeError that only reproduces
    when this file runs alongside others — not in isolation.
    """
    return asyncio.run(coro)


def _make_event(author: str, text: str | None):
    event = MagicMock()
    event.author = author
    event.content = types.Content(role=author, parts=[types.Part(text=text)]) if text else None
    event.get_function_calls = MagicMock(return_value=[])
    return event


def _make_callback_context(user_content_text=None, events=None, user_id="loom-agent"):
    ctx = MagicMock()
    ctx.user_content = (
        types.Content(role="user", parts=[types.Part(text=user_content_text)])
        if user_content_text else None
    )
    session = MagicMock()
    session.id = "sess-abc"
    session.events = events or []
    ctx.session = session
    ctx.user_id = user_id
    ctx.state = {}
    return ctx


class TestMemoryPlugin(unittest.TestCase):
    """Tests for MemoryPlugin."""

    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_init_with_memory_store_id(self, mock_boto3: MagicMock) -> None:
        plugin = MemoryPlugin()
        self.assertEqual(plugin.memory_store_id, "ms-test123")

    @patch.dict(os.environ, {}, clear=False)
    def test_init_without_memory_store_id(self) -> None:
        os.environ.pop("MEMORY_STORE_ID", None)
        plugin = MemoryPlugin()
        self.assertIsNone(plugin.memory_store_id)
        self.assertIsNone(plugin.client)

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_before_agent_loads_context(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.retrieve_memory_records.return_value = {
            "memoryRecordSummaries": [{"content": {"text": "previous context"}}]
        }
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        plugin = MemoryPlugin()
        ctx = _make_callback_context(user_content_text="hello")
        run_async(plugin.before_agent_callback(agent=MagicMock(), callback_context=ctx))

        mock_client.retrieve_memory_records.assert_called_once_with(
            memoryId="ms-test123",
            namespace="loom",
            searchCriteria={"searchQuery": "hello"},
        )
        self.assertEqual(ctx.state["memory"], [{"content": {"text": "previous context"}}])
        self.assertEqual(plugin.retrievals, 1)

    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_before_agent_skips_empty_query(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        plugin = MemoryPlugin()
        ctx = _make_callback_context(user_content_text=None, events=[])
        run_async(plugin.before_agent_callback(agent=MagicMock(), callback_context=ctx))

        mock_client.retrieve_memory_records.assert_not_called()

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_agent_creates_events(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        plugin = MemoryPlugin()
        events = [
            _make_event("user", "hello"),
            _make_event("loom_agent", "hi there"),
        ]
        ctx = _make_callback_context(events=events)
        plugin._pre_invocation_event_count = 0
        run_async(plugin.after_agent_callback(agent=MagicMock(), callback_context=ctx))

        self.assertEqual(mock_client.create_event.call_count, 2)
        self.assertEqual(plugin.events_sent, 2)

        first_call = mock_client.create_event.call_args_list[0]
        self.assertEqual(first_call.kwargs["memoryId"], "ms-test123")
        self.assertEqual(first_call.kwargs["sessionId"], "sess-abc")
        self.assertEqual(first_call.kwargs["payload"][0]["conversational"]["role"], "USER")
        self.assertEqual(first_call.kwargs["payload"][0]["conversational"]["content"]["text"], "hello")

        second_call = mock_client.create_event.call_args_list[1]
        self.assertEqual(second_call.kwargs["payload"][0]["conversational"]["role"], "ASSISTANT")

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_agent_skips_empty_text(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        plugin = MemoryPlugin()
        events = [_make_event("loom_agent", None)]
        ctx = _make_callback_context(events=events)
        plugin._pre_invocation_event_count = 0
        run_async(plugin.after_agent_callback(agent=MagicMock(), callback_context=ctx))

        mock_client.create_event.assert_not_called()
        self.assertEqual(plugin.events_sent, 0)

    def test_before_agent_noop_without_store_id(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMORY_STORE_ID", None)
            plugin = MemoryPlugin()
            ctx = _make_callback_context()
            run_async(plugin.before_agent_callback(agent=MagicMock(), callback_context=ctx))
            self.assertNotIn("memory", ctx.state)

    def test_after_agent_noop_without_store_id(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMORY_STORE_ID", None)
            plugin = MemoryPlugin()
            ctx = _make_callback_context()
            run_async(plugin.after_agent_callback(agent=MagicMock(), callback_context=ctx))

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_agent_skips_empty_events(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        plugin = MemoryPlugin()
        ctx = _make_callback_context(events=[])
        plugin._pre_invocation_event_count = 0
        run_async(plugin.after_agent_callback(agent=MagicMock(), callback_context=ctx))

        mock_client.create_event.assert_not_called()

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_before_agent_handles_error_gracefully(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.retrieve_memory_records.side_effect = Exception("API error")
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        plugin = MemoryPlugin()
        ctx = _make_callback_context(user_content_text="test")
        # Should not raise
        run_async(plugin.before_agent_callback(agent=MagicMock(), callback_context=ctx))

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_agent_handles_error_gracefully(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.create_event.side_effect = Exception("API error")
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        plugin = MemoryPlugin()
        events = [_make_event("user", "hello")]
        ctx = _make_callback_context(events=events)
        plugin._pre_invocation_event_count = 0
        # Should not raise
        run_async(plugin.after_agent_callback(agent=MagicMock(), callback_context=ctx))

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_agent_only_saves_new_events(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        """Verify only events added during the invocation are sent to memory."""
        mock_client = MagicMock()
        mock_client.retrieve_memory_records.return_value = {"memoryRecordSummaries": []}
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        plugin = MemoryPlugin()

        # --- First invocation ---
        before_ctx = _make_callback_context(user_content_text="hello", events=[_make_event("user", "hello")])
        run_async(plugin.before_agent_callback(agent=MagicMock(), callback_context=before_ctx))
        self.assertEqual(plugin._pre_invocation_event_count, 1)

        after_events = [
            _make_event("user", "hello"),
            _make_event("loom_agent", "hi there"),
        ]
        after_ctx = _make_callback_context(events=after_events)
        after_ctx.state = before_ctx.state
        run_async(plugin.after_agent_callback(agent=MagicMock(), callback_context=after_ctx))

        self.assertEqual(mock_client.create_event.call_count, 1)
        self.assertEqual(plugin.events_sent, 1)
        call_kwargs = mock_client.create_event.call_args_list[0].kwargs
        self.assertEqual(call_kwargs["payload"][0]["conversational"]["content"]["text"], "hi there")

    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_telemetry_emitted_after_invocation(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        plugin = MemoryPlugin()
        plugin.retrievals = 3
        plugin.events_sent = 2
        with patch("src.integrations.memory.logger") as mock_logger:
            plugin._emit_telemetry()
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0]
            self.assertIn("LOOM_MEMORY_TELEMETRY", call_args[0])


if __name__ == "__main__":
    unittest.main()
