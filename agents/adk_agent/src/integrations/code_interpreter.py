"""AgentCore Code Interpreter tools for the ADK agent.

Strands wires this integration through ``strands_tools.code_interpreter
.AgentCoreCodeInterpreter``, a package that itself depends on the full
``strands-agents`` SDK — pulling it into this package would defeat the point
of having a separate, independently-installable framework implementation.
Instead, this module is a lean, from-scratch wrapper directly against
``bedrock_agentcore.tools.code_interpreter_client.CodeInterpreter`` (the
underlying SDK client Strands' own wrapper delegates to, already a
dependency of this package via ``bedrock-agentcore``), replicating the same
session lifecycle:

- Sessions are tracked in a module-level cache keyed by session name, so a
  fresh instance in a later invocation (a new object, same long-running
  AgentCore Runtime container) can reconnect instead of re-creating a
  session (session creation is the expensive step; reconnection is fast).
- A session is auto-created on first use if it doesn't exist yet.
- Sessions are never proactively stopped (``persist_sessions``-equivalent
  behavior) — they survive across invocations in the same container.
"""

import logging
import os
import uuid
from typing import Any, Optional

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter as _CodeInterpreterClient

from src.config import CodeInterpreterConfig

logger = logging.getLogger(__name__)

# Module-level cache: session_name -> (aws_session_id, client). Persists
# across object instances within the same long-running container, matching
# Strands' AgentCoreCodeInterpreter session-reconnection behavior.
_session_cache: dict[str, tuple[str, _CodeInterpreterClient]] = {}


class AgentCoreCodeInterpreterTools:
    """Builds ADK ``FunctionTool``s that execute code/commands and manage
    files in an AgentCore Code Interpreter sandbox, with automatic session
    creation and reconnection.
    """

    def __init__(self, region: Optional[str] = None, identifier: Optional[str] = None) -> None:
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.identifier = identifier or "aws.codeinterpreter.v1"
        self.default_session = f"session-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _drain_response(response: dict[str, Any]) -> dict[str, Any]:
        """Consume ``response["stream"]`` (a ``botocore.eventstream.EventStream``,
        not JSON/Pydantic serializable) into a plain dict, matching Strands'
        ``AgentCoreCodeInterpreter._create_tool_result`` behavior.
        """
        if "stream" not in response:
            return response
        for event in response["stream"]:
            if "result" in event:
                return event["result"]
        return {"content": []}

    def _ensure_session(self, session_name: Optional[str]) -> _CodeInterpreterClient:
        """Return a started client for the given (or default) session name,
        creating or reconnecting to it as needed.
        """
        target = session_name or self.default_session

        cached = _session_cache.get(target)
        if cached is not None:
            _, client = cached
            return client

        client = _CodeInterpreterClient(region=self.region)
        client.start(identifier=self.identifier, name=target)
        _session_cache[target] = (client.session_id, client)
        logger.info("Initialized code interpreter session '%s' (id=%s)", target, client.session_id)
        return client

    def prewarm(self) -> None:
        """Pre-warm the default session. Session creation takes 30-60s; calling
        this at container startup means the session is READY before the first
        tool invocation, avoiding the AgentCore Runtime HTTP streaming timeout —
        matching the pre-warm behavior handler.py applies to the Strands agent.
        """
        try:
            self._ensure_session(None)
        except Exception as e:
            logger.warning("Code interpreter pre-warm failed: %s. Session will be created on first use.", e)

    def build_tools(self) -> list[FunctionTool]:
        """Build the set of code-interpreter FunctionTools for this instance."""

        def code_interpreter_execute_code(
            code: str, tool_context: ToolContext, language: str = "python", clear_context: bool = False
        ) -> dict[str, Any]:
            """Execute code in a persistent sandboxed session and return its output."""
            client = self._ensure_session(None)
            return self._drain_response(client.execute_code(code=code, language=language, clear_context=clear_context))

        def code_interpreter_execute_command(command: str, tool_context: ToolContext) -> dict[str, Any]:
            """Execute a shell command in the sandboxed session and return its output."""
            client = self._ensure_session(None)
            return self._drain_response(client.execute_command(command=command))

        def code_interpreter_write_files(
            files: list[dict[str, str]], tool_context: ToolContext
        ) -> dict[str, Any]:
            """Write one or more files into the sandbox. Each entry needs 'path' and 'content'."""
            client = self._ensure_session(None)
            return self._drain_response(
                client.upload_files([{"path": f["path"], "content": f["content"]} for f in files])
            )

        def code_interpreter_read_files(paths: list[str], tool_context: ToolContext) -> dict[str, Any]:
            """Read one or more files from the sandbox by path."""
            client = self._ensure_session(None)
            return client.download_files(paths)

        def code_interpreter_list_files(path: str, tool_context: ToolContext) -> dict[str, Any]:
            """List files in a sandbox directory."""
            client = self._ensure_session(None)
            return self._drain_response(client.invoke("listFiles", {"path": path}))

        def code_interpreter_remove_files(paths: list[str], tool_context: ToolContext) -> dict[str, Any]:
            """Remove one or more files from the sandbox by path."""
            client = self._ensure_session(None)
            return self._drain_response(client.invoke("removeFiles", {"paths": paths}))

        return [
            FunctionTool(code_interpreter_execute_code),
            FunctionTool(code_interpreter_execute_command),
            FunctionTool(code_interpreter_write_files),
            FunctionTool(code_interpreter_read_files),
            FunctionTool(code_interpreter_list_files),
            FunctionTool(code_interpreter_remove_files),
        ]


def build_code_interpreter_tools(config: CodeInterpreterConfig) -> tuple[list[FunctionTool], AgentCoreCodeInterpreterTools]:
    """Build code interpreter tools from configuration.

    Returns the tool list plus the ``AgentCoreCodeInterpreterTools`` instance
    itself so the caller (see ``agent.py``/``handler.py``) can trigger a
    background pre-warm of the sandbox session, matching Strands' behavior
    of pre-warming at cold start to avoid the first invocation paying the
    30-60s session-creation cost inline.
    """
    kwargs: dict[str, Any] = {}
    if config.region:
        kwargs["region"] = config.region
    if config.identifier:
        kwargs["identifier"] = config.identifier
    ci = AgentCoreCodeInterpreterTools(**kwargs)
    return ci.build_tools(), ci
