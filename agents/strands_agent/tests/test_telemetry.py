"""Tests for telemetry module."""

import unittest
from typing import Sequence
from unittest.mock import patch, MagicMock

from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

import src.telemetry as telemetry_module
from src.telemetry import (
    trace_invocation,
    TelemetryHook,
)


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


class _OtelTestBase(unittest.TestCase):
    """Base class that patches get_tracer to use a test TracerProvider."""

    def setUp(self) -> None:
        self.exporter = _InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        # Patch get_tracer so the telemetry module uses our test provider
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


class TestTelemetryHook(_OtelTestBase):
    """Tests for TelemetryHook class."""

    def _make_before_tool_event(self, tool_name: str) -> MagicMock:
        event = MagicMock()
        event.tool_use = {"name": tool_name, "toolUseId": "test-id"}
        return event

    def _make_after_tool_event(self, tool_name: str, exception: Exception | None = None) -> MagicMock:
        event = MagicMock()
        event.tool_use = {"name": tool_name, "toolUseId": "test-id"}
        event.exception = exception
        return event

    def _make_before_model_event(self) -> MagicMock:
        return MagicMock()

    def _make_after_model_event(self, exception: Exception | None = None) -> MagicMock:
        event = MagicMock()
        event.exception = exception
        return event

    def test_register_hooks_registers_callbacks(self) -> None:
        hook = TelemetryHook()
        registry = MagicMock()
        hook.register_hooks(registry)
        self.assertEqual(registry.add_callback.call_count, 4)

    def test_before_after_tool_call_creates_span(self) -> None:
        hook = TelemetryHook()
        hook._on_before_tool_call(self._make_before_tool_event("calculator"))
        hook._on_after_tool_call(self._make_after_tool_event("calculator"))

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "tool.call")
        self.assertEqual(spans[0].attributes["tool.name"], "calculator")

    def test_after_tool_call_with_error_sets_error_status(self) -> None:
        hook = TelemetryHook()
        err = RuntimeError("tool exploded")
        hook._on_before_tool_call(self._make_before_tool_event("bad_tool"))
        hook._on_after_tool_call(self._make_after_tool_event("bad_tool", exception=err))

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].status.status_code, StatusCode.ERROR)

    def test_before_after_model_call_creates_span(self) -> None:
        hook = TelemetryHook()
        hook._on_before_model_call(self._make_before_model_event())
        hook._on_after_model_call(self._make_after_model_event())

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "model.call")

    def test_after_model_call_with_error_sets_error_status(self) -> None:
        hook = TelemetryHook()
        hook._on_before_model_call(self._make_before_model_event())
        hook._on_after_model_call(self._make_after_model_event(exception=RuntimeError("model failed")))

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].status.status_code, StatusCode.ERROR)

    def test_after_tool_call_without_before_is_safe(self) -> None:
        hook = TelemetryHook()
        hook._on_after_tool_call(self._make_after_tool_event("unknown_tool"))

    def test_after_model_call_without_before_is_safe(self) -> None:
        hook = TelemetryHook()
        hook._on_after_model_call(self._make_after_model_event())


class TestNoopOperations(unittest.TestCase):
    """Verify tracing operations succeed even without setup (noop mode)."""

    def test_trace_invocation_noop(self) -> None:
        with trace_invocation(invocation_id="noop-1") as span:
            self.assertIsNotNone(span)


if __name__ == "__main__":
    unittest.main()
