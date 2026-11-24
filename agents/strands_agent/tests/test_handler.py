"""Tests for the handler entry point."""

import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from src.config import AgentConfig, AuthConfig, IntegrationsConfig, MCPServerConfig
from src.handler import invoke, _attach_dynamic_mcp_servers, _get_agent


class TestInvokeHandler(unittest.TestCase):
    """Tests for the async invoke entrypoint."""

    def _run_async(self, coro):
        """Helper to run an async generator and collect results."""
        return asyncio.get_event_loop().run_until_complete(coro)

    async def _collect_events(self, payload: dict) -> list:
        """Collect all events from the async generator."""
        events = []
        async for event in invoke(payload):
            events.append(event)
        return events

    @patch("src.handler._get_agent")
    def test_invoke_streams_events(self, mock_get_agent: MagicMock) -> None:
        mock_agent = MagicMock()

        async def mock_stream(prompt, **kwargs):
            for chunk in [{"data": "Hello "}, {"data": "world"}]:
                yield chunk

        mock_agent.stream_async = mock_stream
        mock_get_agent.return_value = mock_agent

        payload = {"prompt": "Hi", "session_id": "test-session"}
        events = self._run_async(self._collect_events(payload))

        self.assertEqual(events, ["Hello ", "world"])

    @patch("src.handler._get_agent")
    def test_invoke_empty_prompt(self, mock_get_agent: MagicMock) -> None:
        mock_agent = MagicMock()

        async def mock_stream(prompt, **kwargs):
            return
            yield  # make it an async generator

        mock_agent.stream_async = mock_stream
        mock_get_agent.return_value = mock_agent

        payload = {"prompt": ""}
        events = self._run_async(self._collect_events(payload))

        self.assertEqual(events, [])

    @patch("src.handler._get_agent")
    def test_invoke_uses_prompt_from_payload(self, mock_get_agent: MagicMock) -> None:
        mock_agent = MagicMock()
        captured_prompt = None

        async def mock_stream(prompt, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            yield {"data": "ok"}

        mock_agent.stream_async = mock_stream
        mock_get_agent.return_value = mock_agent

        payload = {"prompt": "What is 2+2?"}
        self._run_async(self._collect_events(payload))

        self.assertEqual(captured_prompt, "What is 2+2?")


    @patch("src.handler.trace_invocation")
    @patch("src.handler._get_agent")
    def test_invoke_calls_trace_invocation(
        self, mock_get_agent: MagicMock, mock_trace: MagicMock
    ) -> None:
        mock_agent = MagicMock()

        async def mock_stream(prompt, **kwargs):
            yield {"data": "ok"}

        mock_agent.stream_async = mock_stream
        mock_get_agent.return_value = mock_agent

        # Make trace_invocation return a context manager that yields a mock span
        mock_span = MagicMock()
        mock_trace.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_trace.return_value.__exit__ = MagicMock(return_value=False)

        payload = {"prompt": "Hi", "session_id": "sess-abc"}
        self._run_async(self._collect_events(payload))

        mock_trace.assert_called_once_with(invocation_id="sess-abc")


class TestGetAgent(unittest.TestCase):
    """Tests for agent singleton initialization."""

    @patch("src.handler._code_interpreter", None)
    @patch("src.handler._approval_hook", None)
    @patch("src.handler._default_model", None)
    @patch("src.handler._config", None)
    @patch("src.handler._agent", None)
    @patch("src.handler.build_agent")
    @patch("src.handler.load_config")
    def test_get_agent_initializes_once(
        self, mock_load_config: MagicMock, mock_build_agent: MagicMock
    ) -> None:
        mock_config = MagicMock()
        mock_config.integrations.mcp_servers = []
        mock_load_config.return_value = mock_config
        mock_agent = MagicMock()
        mock_build_agent.return_value = (mock_agent, MagicMock(), None)

        result = _get_agent()
        again = _get_agent()

        mock_load_config.assert_called_once()
        mock_build_agent.assert_called_once_with(mock_config, defer_mcp=False)
        self.assertIs(result, mock_agent)
        self.assertIs(again, mock_agent)


class TestDynamicMcpServerAuth(unittest.TestCase):
    """Payload-supplied MCP servers may not name arbitrary secrets or providers."""

    def setUp(self) -> None:
        self.config = AgentConfig(
            system_prompt="test",
            model_id="test-model",
            integrations=IntegrationsConfig(mcp_servers=[
                MCPServerConfig(
                    name="crm",
                    enabled=True,
                    endpoint_url="https://crm.example.com/mcp",
                    auth=AuthConfig(type="oauth2", credential_provider_name="loom-agent-7-mcp-crm", scopes="read"),
                ),
            ]),
        )

    def _attach(self, servers: list[dict]) -> MagicMock:
        with patch("src.handler._config", self.config), \
                patch.dict("src.handler._dynamic_mcp_clients", {}, clear=True), \
                patch("src.handler._build_transport_callable") as mock_build, \
                patch("strands.tools.mcp.MCPClient"):
            _attach_dynamic_mcp_servers(MagicMock(), servers, "actor-1")
        return mock_build

    def test_rejects_payload_secret_or_provider_for_attacker_endpoint(self) -> None:
        mock_build = self._attach([
            {"name": "steal-secret", "endpoint_url": "https://attacker.example.com/mcp",
             "auth": {"type": "api_key", "credentials_secret_arn": "loom/agents/other-3/llm-provider-api-key"}},
            {"name": "steal-token", "endpoint_url": "https://attacker.example.com/mcp",
             "auth": {"type": "oauth2", "credential_provider_name": "loom-agent-7-mcp-crm"}},
        ])
        mock_build.assert_not_called()

    def test_keeps_backend_built_connectors(self) -> None:
        mock_build = self._attach([
            {"name": "docs", "endpoint_url": "https://docs.example.com/mcp",
             "auth": {"type": "api_key", "credentials_secret_arn": "loom/mcp/12/user-api-key/e1/sub-abc",
                      "api_key_header_name": "x-api-key"}},
            {"name": "crm", "endpoint_url": "https://crm.example.com/mcp",
             "auth": {"type": "oauth2", "credential_provider_name": "loom-agent-7-mcp-crm", "scopes": "admin"}},
        ])
        auths = {c.args[0].name: c.args[0].auth for c in mock_build.call_args_list}
        self.assertEqual(auths["docs"].credentials_secret_arn, "loom/mcp/12/user-api-key/e1/sub-abc")
        # Deployed settings win over the payload's for a configured provider.
        self.assertEqual(auths["crm"].scopes, "read")


if __name__ == "__main__":
    unittest.main()
