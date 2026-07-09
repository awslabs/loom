"""Tests for AgentCore Memory hooks (async)."""

import asyncio
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from src.integrations.memory import MemoryHook


def run_async(coro):
    """Helper to run an async coroutine in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


async def _sync_to_thread(fn, **kwargs):
    """Test replacement for asyncio.to_thread that runs synchronously."""
    return fn(**kwargs)


class TestMemoryHook(unittest.TestCase):
    """Tests for MemoryHook HookProvider."""

    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_init_with_memory_store_id(self, mock_boto3: MagicMock) -> None:
        hook = MemoryHook()
        self.assertEqual(hook.memory_store_id, "ms-test123")

    @patch.dict(os.environ, {}, clear=False)
    def test_init_without_memory_store_id(self) -> None:
        os.environ.pop("MEMORY_STORE_ID", None)
        hook = MemoryHook()
        self.assertIsNone(hook.memory_store_id)
        self.assertIsNone(hook.client)

    def test_register_hooks_registers_callbacks(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMORY_STORE_ID", None)
            hook = MemoryHook()
            registry = MagicMock()
            hook.register_hooks(registry)
            self.assertEqual(registry.add_callback.call_count, 2)

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_before_invocation_loads_context(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.retrieve_memory_records.return_value = {
            "memoryRecordSummaries": [{"content": {"text": "previous context"}}]
        }
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        hook = MemoryHook()
        event = MagicMock()
        event.messages = [{"content": [{"text": "hello"}]}]
        event.invocation_state = {}
        run_async(hook._on_before_invocation(event))

        mock_client.retrieve_memory_records.assert_called_once_with(
            memoryId="ms-test123",
            namespace="loom",
            searchCriteria={"searchQuery": "hello"},
        )
        self.assertEqual(
            event.invocation_state["memory"],
            [{"content": {"text": "previous context"}}],
        )
        self.assertEqual(hook.retrievals, 1)

    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_before_invocation_skips_empty_query(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        hook = MemoryHook()
        event = MagicMock()
        event.messages = []
        event.invocation_state = {}
        run_async(hook._on_before_invocation(event))

        mock_client.retrieve_memory_records.assert_not_called()

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_invocation_creates_events(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        hook = MemoryHook()
        event = MagicMock()
        event.agent.messages = [
            {"role": "user", "content": [{"text": "hello"}]},
            {"role": "assistant", "content": [{"text": "hi there"}]},
        ]
        event.invocation_state = {"session_id": "sess-abc"}
        run_async(hook._on_after_invocation(event))

        self.assertEqual(mock_client.create_event.call_count, 2)
        self.assertEqual(hook.events_sent, 2)

        # Verify first call (user message)
        first_call = mock_client.create_event.call_args_list[0]
        self.assertEqual(first_call.kwargs["memoryId"], "ms-test123")
        self.assertEqual(first_call.kwargs["actorId"], "loom-agent")
        self.assertEqual(first_call.kwargs["sessionId"], "sess-abc")
        self.assertEqual(
            first_call.kwargs["payload"][0]["conversational"]["role"], "USER"
        )
        self.assertEqual(
            first_call.kwargs["payload"][0]["conversational"]["content"]["text"], "hello"
        )

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_invocation_handles_string_content(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        hook = MemoryHook()
        event = MagicMock()
        event.agent.messages = [
            {"role": "user", "content": "plain text message"},
        ]
        event.invocation_state = {}
        run_async(hook._on_after_invocation(event))

        self.assertEqual(mock_client.create_event.call_count, 1)
        first_call = mock_client.create_event.call_args_list[0]
        self.assertEqual(
            first_call.kwargs["payload"][0]["conversational"]["content"]["text"],
            "plain text message",
        )
        # No sessionId when empty
        self.assertNotIn("sessionId", first_call.kwargs)

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_invocation_skips_empty_text(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        hook = MemoryHook()
        event = MagicMock()
        event.agent.messages = [
            {"role": "assistant", "content": [{"toolUse": {"name": "search"}}]},
        ]
        event.invocation_state = {}
        run_async(hook._on_after_invocation(event))

        mock_client.create_event.assert_not_called()
        self.assertEqual(hook.events_sent, 0)

    def test_before_invocation_noop_without_store_id(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMORY_STORE_ID", None)
            hook = MemoryHook()
            event = MagicMock()
            event.invocation_state = {}
            run_async(hook._on_before_invocation(event))
            self.assertNotIn("memory", event.invocation_state)

    def test_after_invocation_noop_without_store_id(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMORY_STORE_ID", None)
            hook = MemoryHook()
            event = MagicMock()
            run_async(hook._on_after_invocation(event))

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_invocation_skips_empty_messages(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        hook = MemoryHook()
        event = MagicMock()
        event.agent.messages = []
        event.invocation_state = {}
        run_async(hook._on_after_invocation(event))

        mock_client.create_event.assert_not_called()

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_before_invocation_handles_error_gracefully(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.retrieve_memory_records.side_effect = Exception("API error")
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        hook = MemoryHook()
        event = MagicMock()
        event.messages = [{"content": [{"text": "test"}]}]
        event.invocation_state = {}
        # Should not raise
        run_async(hook._on_before_invocation(event))

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_invocation_handles_error_gracefully(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.create_event.side_effect = Exception("API error")
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        hook = MemoryHook()
        event = MagicMock()
        event.agent.messages = [{"role": "user", "content": [{"text": "hello"}]}]
        event.invocation_state = {}
        # Should not raise
        run_async(hook._on_after_invocation(event))

    @patch("src.integrations.memory.asyncio")
    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_after_invocation_only_saves_new_messages(self, mock_boto3: MagicMock, mock_asyncio: MagicMock) -> None:
        """Verify that only messages added during the invocation are sent to memory."""
        mock_client = MagicMock()
        mock_client.retrieve_memory_records.return_value = {"memoryRecordSummaries": []}
        mock_boto3.client.return_value = mock_client
        mock_asyncio.to_thread = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))

        hook = MemoryHook()

        # --- First invocation: agent has [user1] before running, adds assistant1 ---
        before_event_1 = MagicMock()
        before_event_1.messages = [{"content": [{"text": "hello"}]}]
        # agent.messages at before time = just the user message appended
        before_event_1.agent.messages = [
            {"role": "user", "content": [{"text": "hello"}]},
        ]
        before_event_1.invocation_state = {}
        run_async(hook._on_before_invocation(before_event_1))
        self.assertEqual(hook._pre_invocation_message_count, 1)

        after_event_1 = MagicMock()
        after_event_1.agent.messages = [
            {"role": "user", "content": [{"text": "hello"}]},
            {"role": "assistant", "content": [{"text": "hi there"}]},
        ]
        after_event_1.invocation_state = {"session_id": "sess-1"}
        run_async(hook._on_after_invocation(after_event_1))

        # Only the assistant message is new
        self.assertEqual(mock_client.create_event.call_count, 1)
        self.assertEqual(hook.events_sent, 1)
        call_kwargs = mock_client.create_event.call_args_list[0].kwargs
        self.assertEqual(
            call_kwargs["payload"][0]["conversational"]["content"]["text"], "hi there"
        )

        mock_client.create_event.reset_mock()

        # --- Second invocation: agent has [user1, asst1, user2] before running ---
        before_event_2 = MagicMock()
        before_event_2.messages = [{"content": [{"text": "what is 2+2?"}]}]
        before_event_2.agent.messages = [
            {"role": "user", "content": [{"text": "hello"}]},
            {"role": "assistant", "content": [{"text": "hi there"}]},
            {"role": "user", "content": [{"text": "what is 2+2?"}]},
        ]
        before_event_2.invocation_state = {}
        run_async(hook._on_before_invocation(before_event_2))
        self.assertEqual(hook._pre_invocation_message_count, 3)

        after_event_2 = MagicMock()
        after_event_2.agent.messages = [
            {"role": "user", "content": [{"text": "hello"}]},
            {"role": "assistant", "content": [{"text": "hi there"}]},
            {"role": "user", "content": [{"text": "what is 2+2?"}]},
            {"role": "assistant", "content": [{"text": "4"}]},
        ]
        after_event_2.invocation_state = {"session_id": "sess-1"}
        run_async(hook._on_after_invocation(after_event_2))

        # Only the new assistant message should be sent
        self.assertEqual(mock_client.create_event.call_count, 1)
        self.assertEqual(hook.events_sent, 1)
        call_kwargs = mock_client.create_event.call_args_list[0].kwargs
        self.assertEqual(
            call_kwargs["payload"][0]["conversational"]["content"]["text"], "4"
        )

    @patch.dict(os.environ, {"MEMORY_STORE_ID": "ms-test123", "AWS_REGION": "us-east-1"})
    @patch("src.integrations.memory.boto3")
    def test_telemetry_emitted_after_invocation(self, mock_boto3: MagicMock) -> None:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        hook = MemoryHook()
        # Simulate before with retrievals
        hook.retrievals = 3
        hook.events_sent = 2
        with patch("src.integrations.memory.logger") as mock_logger:
            hook._emit_telemetry()
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0]
            self.assertIn("LOOM_MEMORY_TELEMETRY", call_args[0])


if __name__ == "__main__":
    unittest.main()
