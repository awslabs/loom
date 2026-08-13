"""Tests for A2A client vending from agent configuration."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.config import A2AAgentConfig
from src.integrations.a2a_client import (
    _BearerAuth,
    _sanitize_agent_name,
    create_a2a_tools,
)


class TestSanitizeAgentName(unittest.TestCase):
    def test_hyphens_replaced(self) -> None:
        self.assertEqual(_sanitize_agent_name("my-agent"), "my_agent")

    def test_valid_identifier_unchanged(self) -> None:
        self.assertEqual(_sanitize_agent_name("my_agent"), "my_agent")

    def test_leading_digit_prefixed(self) -> None:
        self.assertEqual(_sanitize_agent_name("123agent"), "a2a_123agent")

    def test_special_chars_replaced(self) -> None:
        self.assertEqual(_sanitize_agent_name("my.agent!"), "my_agent_")


class TestCreateA2ATools(unittest.IsolatedAsyncioTestCase):
    """Tests for create_a2a_tools."""

    async def test_empty_agent_list(self) -> None:
        tools = await create_a2a_tools([])
        self.assertEqual(tools, [])

    async def test_disabled_agent_skipped(self) -> None:
        agents = [A2AAgentConfig(name="disabled-agent", enabled=False)]
        tools = await create_a2a_tools(agents)
        self.assertEqual(tools, [])

    @patch("src.integrations.a2a_client._build_a2a_tool")
    async def test_enabled_agent_creates_tool(self, mock_build: AsyncMock) -> None:
        mock_tool = MagicMock()
        mock_build.return_value = mock_tool
        agents = [A2AAgentConfig(name="my-agent", enabled=True, endpoint_url="https://example.com")]

        tools = await create_a2a_tools(agents)

        self.assertEqual(len(tools), 1)
        self.assertIs(tools[0], mock_tool)

    @patch("src.integrations.a2a_client._build_a2a_tool")
    async def test_multiple_enabled_agents(self, mock_build: AsyncMock) -> None:
        mock_build.side_effect = [MagicMock(), MagicMock()]
        agents = [
            A2AAgentConfig(name="agent-1", enabled=True, endpoint_url="https://a1.example.com"),
            A2AAgentConfig(name="agent-2", enabled=True, endpoint_url="https://a2.example.com"),
        ]

        tools = await create_a2a_tools(agents)
        self.assertEqual(len(tools), 2)

    @patch("src.integrations.a2a_client._build_a2a_tool")
    async def test_unreachable_agent_skipped_gracefully(self, mock_build: AsyncMock) -> None:
        mock_build.side_effect = httpx.ConnectError("connection refused")
        agents = [A2AAgentConfig(name="unreachable", enabled=True, endpoint_url="https://down.example.com")]

        tools = await create_a2a_tools(agents)
        self.assertEqual(tools, [])


class TestBearerAuth(unittest.TestCase):
    def test_injects_bearer_token(self) -> None:
        fetcher = MagicMock()
        fetcher.fetch_bearer_token.return_value = "test-token-123"
        auth = _BearerAuth(fetcher)

        request = httpx.Request("GET", "https://example.com")
        flow = auth.auth_flow(request)
        sent_request = next(flow)
        self.assertEqual(sent_request.headers["Authorization"], "Bearer test-token-123")

    def test_no_token_no_header(self) -> None:
        fetcher = MagicMock()
        fetcher.fetch_bearer_token.return_value = None
        auth = _BearerAuth(fetcher)

        request = httpx.Request("GET", "https://example.com")
        flow = auth.auth_flow(request)
        sent_request = next(flow)
        self.assertNotIn("Authorization", sent_request.headers)


if __name__ == "__main__":
    unittest.main()
