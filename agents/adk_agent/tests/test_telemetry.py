"""Tests for telemetry module."""

import unittest
from typing import Sequence
from unittest.mock import patch, MagicMock

from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

import src.telemetry as telemetry_module
from src.telemetry import trace_invocation, TelemetryPlugin


class _InMemorySpanExporter(SpanExporter):
    """Simple in-memory exporter that collects finished spans."""

    def __init__(self) -> None:
        self._spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def get_finished_spans(self) -> list[ReadableSpan]:
        return list(self._spans)

    def shutdown(self) -> None:
        self._spans.clear()


class _OtelTestBase(unittest.IsolatedAsyncioTestCase):
    """Base class that patches get_tracer to use a test TracerProvider."""

    def setUp(self) -> None:
        self.exporter = _InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self._patcher = patch.object(
            telemetry_module, "get_tracer",
            return_value=self.provider.get_tracer("test"),
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.provider.shutdown()


class TestTraceInvocation(_OtelTestBase):
    """Tests for trace_invocation context manager."""

    def test_creates_span_with_invocation_id(self) -> None:
        with trace_invocation(invocation_id="test-123") as span:
            self.assertIsNotNone(span)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "agent.invocation")
        self.assertEqual(spans[0].attributes["agent.invocation_id"], "test-123")

    def test_creates_span_without_invocation_id(self) -> None:
        with trace_invocation() as span:
            self.assertIsNotNone(span)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertNotIn("agent.invocation_id", spans[0].attributes)

    def test_records_exception_on_error(self) -> None:
        with self.assertRaises(RuntimeError):
            with trace_invocation(invocation_id="err-1"):
                raise RuntimeError("boom")

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].status.status_code, StatusCode.ERROR)


class TestTelemetryPlugin(_OtelTestBase):
    """Tests for TelemetryPlugin class."""

    def _make_tool(self, name: str) -> MagicMock:
        tool = MagicMock()
        tool.name = name
        return tool

    async def test_before_after_tool_call_creates_span(self) -> None:
        plugin = TelemetryPlugin()
        tool = self._make_tool("calculator")
        await plugin.before_tool_callback(tool=tool, tool_args={}, tool_context=MagicMock())
        await plugin.after_tool_callback(tool=tool, tool_args={}, tool_context=MagicMock(), result={})

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "tool.call")
        self.assertEqual(spans[0].attributes["tool.name"], "calculator")

    async def test_tool_error_sets_error_status(self) -> None:
        plugin = TelemetryPlugin()
        tool = self._make_tool("bad_tool")
        await plugin.before_tool_callback(tool=tool, tool_args={}, tool_context=MagicMock())
        await plugin.on_tool_error_callback(
            tool=tool, tool_args={}, tool_context=MagicMock(), error=RuntimeError("tool exploded")
        )

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].status.status_code, StatusCode.ERROR)

    async def test_before_after_model_call_creates_span(self) -> None:
        plugin = TelemetryPlugin()
        await plugin.before_model_callback(callback_context=MagicMock(), llm_request=MagicMock())
        await plugin.after_model_callback(callback_context=MagicMock(), llm_response=MagicMock())

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "model.call")

    async def test_model_error_sets_error_status(self) -> None:
        plugin = TelemetryPlugin()
        await plugin.before_model_callback(callback_context=MagicMock(), llm_request=MagicMock())
        await plugin.on_model_error_callback(
            callback_context=MagicMock(), llm_request=MagicMock(), error=RuntimeError("model failed")
        )

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].status.status_code, StatusCode.ERROR)

    async def test_after_tool_call_without_before_is_safe(self) -> None:
        plugin = TelemetryPlugin()
        tool = self._make_tool("unknown_tool")
        await plugin.after_tool_callback(tool=tool, tool_args={}, tool_context=MagicMock(), result={})

    async def test_after_model_call_without_before_is_safe(self) -> None:
        plugin = TelemetryPlugin()
        await plugin.after_model_callback(callback_context=MagicMock(), llm_response=MagicMock())


class TestNoopOperations(unittest.TestCase):
    """Verify tracing operations succeed even without setup (noop mode)."""

    def test_trace_invocation_noop(self) -> None:
        with trace_invocation(invocation_id="noop-1") as span:
            self.assertIsNotNone(span)


if __name__ == "__main__":
    unittest.main()
