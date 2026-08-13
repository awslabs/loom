"""OpenTelemetry instrumentation for the Loom ADK agent.

Provides application-level tracing spans for invocations, tool calls,
and model calls, matching the exact span names/attributes emitted by
``agents/strands_agent/src/telemetry.py`` so trace consumers (traces UI,
CloudWatch) see equivalent data regardless of which framework built the
agent.  Provider configuration (exporters, resource, etc.) is handled by
the ``opentelemetry-instrument`` CLI wrapper that AgentCore Runtime uses
as the process entry point.  When running locally without the wrapper the
OpenTelemetry API falls back to noop providers automatically.
"""

import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional

from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

logger = logging.getLogger(__name__)

_TRACER_SCOPE = "loom.adk_agent"


def get_tracer() -> trace.Tracer:
    """Return a tracer scoped to the ADK agent."""
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
# ADK plugin telemetry hook
# ---------------------------------------------------------------------------

class TelemetryPlugin(BasePlugin):
    """ADK BasePlugin that creates OTEL spans for tool and model calls.

    ADK routes errors to a dedicated ``on_*_error_callback`` rather than
    passing an exception into the ``after_*_callback`` (Strands' HookProvider
    puts both success and failure through the same AfterXCallEvent). Both
    callback pairs close the same pending span here so the resulting span
    shape (name, attributes, ERROR status on failure) matches Strands' output.
    """

    def __init__(self, name: str = "loom_telemetry_plugin") -> None:
        super().__init__(name=name)
        self._tool_spans: dict[str, Span] = {}
        self._model_spans: dict[int, Span] = {}
        self._model_call_counter: int = 0

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> Optional[dict[str, Any]]:
        tracer = get_tracer()
        span = tracer.start_span("tool.call", attributes={"tool.name": tool.name})
        self._tool_spans[tool.name] = span
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        span = self._tool_spans.pop(tool.name, None)
        if span:
            span.end()
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[dict[str, Any]]:
        span = self._tool_spans.pop(tool.name, None)
        if span:
            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            span.end()
        return None

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> Optional[LlmResponse]:
        tracer = get_tracer()
        self._model_call_counter += 1
        span = tracer.start_span("model.call")
        self._model_spans[self._model_call_counter] = span
        return None

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        self._close_latest_model_span()
        return None

    async def on_model_error_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest, error: Exception
    ) -> Optional[LlmResponse]:
        self._close_latest_model_span(error=error)
        return None

    def _close_latest_model_span(self, error: Optional[Exception] = None) -> None:
        if not self._model_spans:
            return
        key = max(self._model_spans.keys())
        span = self._model_spans.pop(key, None)
        if span:
            if error:
                span.set_status(StatusCode.ERROR, str(error))
                span.record_exception(error)
            span.end()
