"""OpenTelemetry instrumentation for the Loom Strands agent.

Provides application-level tracing spans for invocations, tool calls,
and model calls.  Provider configuration (exporters, resource, etc.)
is handled by the ``opentelemetry-instrument`` CLI wrapper that
AgentCore Runtime uses as the process entry point.  When running
locally without the wrapper the OpenTelemetry API falls back to
noop providers automatically.
"""

import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional

from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode

from strands.hooks.registry import HookRegistry
from strands.hooks.events import (
    BeforeToolCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    AfterModelCallEvent,
)

logger = logging.getLogger(__name__)

_TRACER_SCOPE = "loom.strands_agent"


def get_tracer() -> trace.Tracer:
    """Return a tracer scoped to the strands agent."""
    return trace.get_tracer(_TRACER_SCOPE)


@contextmanager
def trace_invocation(
    invocation_id: Optional[str] = None,
) -> Generator[Span, None, None]:
    """Create a span that wraps a full agent invocation.

    Args:
        invocation_id: Optional identifier for the invocation.

    Yields:
        The active ``Span`` so callers can annotate it further.
    """
    tracer = get_tracer()
    attributes: dict[str, str] = {}
    if invocation_id:
        attributes["agent.invocation_id"] = invocation_id

    with tracer.start_as_current_span(
        "agent.invocation", attributes=attributes
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


# ---------------------------------------------------------------------------
# Strands Agent telemetry hook
# ---------------------------------------------------------------------------

class TelemetryHook:
    """Strands Agent HookProvider that creates OTEL spans for tool and model calls."""

    def __init__(self) -> None:
        self._tool_spans: dict[str, Span] = {}
        self._model_spans: dict[int, Span] = {}
        self._model_call_counter: int = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register callbacks for tool and model lifecycle events."""
        registry.add_callback(BeforeToolCallEvent, self._on_before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._on_after_tool_call)
        registry.add_callback(BeforeModelCallEvent, self._on_before_model_call)
        registry.add_callback(AfterModelCallEvent, self._on_after_model_call)

    def _on_before_tool_call(self, event: BeforeToolCallEvent) -> None:
        tool_name = event.tool_use.get("name", "unknown")
        tracer = get_tracer()
        span = tracer.start_span("tool.call", attributes={"tool.name": tool_name})
        self._tool_spans[tool_name] = span

    def _on_after_tool_call(self, event: AfterToolCallEvent) -> None:
        tool_name = event.tool_use.get("name", "unknown")
        span = self._tool_spans.pop(tool_name, None)
        if span:
            if event.exception:
                span.set_status(StatusCode.ERROR, str(event.exception))
                span.record_exception(event.exception)
            span.end()

    def _on_before_model_call(self, event: BeforeModelCallEvent) -> None:
        tracer = get_tracer()
        self._model_call_counter += 1
        span = tracer.start_span("model.call")
        self._model_spans[self._model_call_counter] = span

    def _on_after_model_call(self, event: AfterModelCallEvent) -> None:
        if self._model_spans:
            key = max(self._model_spans.keys())
            span = self._model_spans.pop(key, None)
            if span:
                if event.exception:
                    span.set_status(StatusCode.ERROR, str(event.exception))
                    span.record_exception(event.exception)
                span.end()
