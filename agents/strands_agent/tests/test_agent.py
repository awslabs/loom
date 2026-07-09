"""Tests for agent initialization and configuration."""

import unittest
from unittest.mock import patch, MagicMock

from src.config import (
    AgentConfig,
    IntegrationsConfig,
    MCPServerConfig,
    A2AAgentConfig,
    MemoryConfig,
)
from src.agent import build_agent
from src.telemetry import TelemetryHook


class TestBuildAgent(unittest.TestCase):
    """Tests for build_agent function."""

    def _make_config(
        self,
        mcp_servers: list[MCPServerConfig] | None = None,
        a2a_agents: list[A2AAgentConfig] | None = None,
        memory_enabled: bool = False,
    ) -> AgentConfig:
        return AgentConfig(
            system_prompt="Test prompt",
            model_id="us.anthropic.claude-sonnet-4-20250514",
            integrations=IntegrationsConfig(
                mcp_servers=mcp_servers or [],
                a2a_agents=a2a_agents or [],
                memory=MemoryConfig(enabled=memory_enabled),
            ),
        )

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    def test_minimal_agent(
        self, mock_model_cls: MagicMock, mock_agent_cls: MagicMock
    ) -> None:
        config = self._make_config()
        build_agent(config)

        mock_model_cls.assert_called_once_with(
            model_id="us.anthropic.claude-sonnet-4-20250514",
            max_tokens=4096,
            streaming=True,
        )
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args[1]
        self.assertEqual(call_kwargs["system_prompt"], "Test prompt")
        self.assertEqual(call_kwargs["tools"], [])
        # TelemetryHook is always added
        self.assertEqual(len(call_kwargs["hooks"]), 1)
        self.assertIsInstance(call_kwargs["hooks"][0], TelemetryHook)

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    @patch("src.agent.create_mcp_clients")
    def test_agent_with_mcp_tools(
        self,
        mock_mcp: MagicMock,
        mock_model_cls: MagicMock,
        mock_agent_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_mcp.return_value = [mock_client]
        config = self._make_config(
            mcp_servers=[
                MCPServerConfig(name="test-mcp", enabled=True, endpoint_url="https://example.com")
            ]
        )
        build_agent(config)

        mock_mcp.assert_called_once()
        call_kwargs = mock_agent_cls.call_args[1]
        self.assertIn(mock_client, call_kwargs["tools"])

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    @patch("src.agent.create_mcp_clients")
    def test_disabled_mcp_not_loaded(
        self,
        mock_mcp: MagicMock,
        mock_model_cls: MagicMock,
        mock_agent_cls: MagicMock,
    ) -> None:
        config = self._make_config(
            mcp_servers=[
                MCPServerConfig(name="disabled-mcp", enabled=False)
            ]
        )
        build_agent(config)
        mock_mcp.assert_not_called()

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    @patch("src.agent.MemoryHook")
    def test_agent_with_memory(
        self,
        mock_memory_hook_cls: MagicMock,
        mock_model_cls: MagicMock,
        mock_agent_cls: MagicMock,
    ) -> None:
        mock_hook = MagicMock()
        mock_memory_hook_cls.return_value = mock_hook
        config = self._make_config(memory_enabled=True)
        build_agent(config)

        call_kwargs = mock_agent_cls.call_args[1]
        self.assertIn(mock_hook, call_kwargs["hooks"])

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    def test_memory_disabled_no_hook(
        self,
        mock_model_cls: MagicMock,
        mock_agent_cls: MagicMock,
    ) -> None:
        config = self._make_config(memory_enabled=False)
        build_agent(config)

        call_kwargs = mock_agent_cls.call_args[1]
        # Only TelemetryHook, no MemoryHook
        self.assertEqual(len(call_kwargs["hooks"]), 1)
        self.assertIsInstance(call_kwargs["hooks"][0], TelemetryHook)

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    def test_telemetry_hook_added(
        self, mock_model_cls: MagicMock, mock_agent_cls: MagicMock
    ) -> None:
        config = self._make_config()
        build_agent(config)
        call_kwargs = mock_agent_cls.call_args[1]
        telemetry_hooks = [h for h in call_kwargs["hooks"] if isinstance(h, TelemetryHook)]
        self.assertEqual(len(telemetry_hooks), 1)


if __name__ == "__main__":
    unittest.main()
