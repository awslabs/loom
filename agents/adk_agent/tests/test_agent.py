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
from src.agent import build_agent, build_model
from src.telemetry import TelemetryPlugin
from src.integrations.memory import MemoryPlugin


def _make_config(
    mcp_servers=None,
    a2a_agents=None,
    memory_enabled: bool = False,
    **overrides,
) -> AgentConfig:
    base = dict(
        system_prompt="Test prompt",
        model_id="us.anthropic.claude-sonnet-4-20250514",
        integrations=IntegrationsConfig(
            mcp_servers=mcp_servers or [],
            a2a_agents=a2a_agents or [],
            memory=MemoryConfig(enabled=memory_enabled),
        ),
    )
    base.update(overrides)
    return AgentConfig(**base)


class TestBuildAgent(unittest.IsolatedAsyncioTestCase):
    """Tests for build_agent."""

    async def test_minimal_agent(self) -> None:
        config = _make_config()
        agent, plugins, ci = await build_agent(config)

        self.assertEqual(agent.instruction, "Test prompt")
        self.assertEqual(agent.tools, [])
        self.assertIsNone(ci)
        # TelemetryPlugin is always added
        self.assertEqual(len(plugins), 1)
        self.assertIsInstance(plugins[0], TelemetryPlugin)

    @patch("src.agent.build_toolsets")
    async def test_agent_with_mcp_tools(self, mock_build_toolsets: MagicMock) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"

        async def _get_tools(readonly_context=None):
            return [mock_tool]

        mock_toolset = MagicMock()
        mock_toolset.get_tools = _get_tools
        mock_build_toolsets.return_value = [mock_toolset]

        config = _make_config(
            mcp_servers=[
                MCPServerConfig(name="test-mcp", enabled=True, endpoint_url="https://example.com")
            ]
        )
        agent, plugins, ci = await build_agent(config)

        mock_build_toolsets.assert_called_once()
        self.assertIn(mock_tool, agent.tools)

    @patch("src.agent.build_toolsets")
    async def test_disabled_mcp_not_loaded(self, mock_build_toolsets: MagicMock) -> None:
        config = _make_config(
            mcp_servers=[MCPServerConfig(name="disabled-mcp", enabled=False)]
        )
        await build_agent(config)
        mock_build_toolsets.assert_not_called()

    async def test_agent_with_memory(self) -> None:
        config = _make_config(memory_enabled=True)
        agent, plugins, ci = await build_agent(config)

        memory_plugins = [p for p in plugins if isinstance(p, MemoryPlugin)]
        self.assertEqual(len(memory_plugins), 1)

    async def test_memory_disabled_no_plugin(self) -> None:
        config = _make_config(memory_enabled=False)
        agent, plugins, ci = await build_agent(config)

        # Only TelemetryPlugin, no MemoryPlugin
        self.assertEqual(len(plugins), 1)
        self.assertIsInstance(plugins[0], TelemetryPlugin)

    async def test_telemetry_plugin_added(self) -> None:
        config = _make_config()
        agent, plugins, ci = await build_agent(config)
        telemetry_plugins = [p for p in plugins if isinstance(p, TelemetryPlugin)]
        self.assertEqual(len(telemetry_plugins), 1)

    @patch("src.agent.create_a2a_tools")
    async def test_disabled_a2a_not_loaded(self, mock_create_a2a: MagicMock) -> None:
        config = _make_config(
            a2a_agents=[A2AAgentConfig(name="disabled-agent", enabled=False)]
        )
        await build_agent(config)
        mock_create_a2a.assert_not_called()

    @patch("src.agent.build_code_interpreter_tools")
    async def test_code_interpreter_enabled(self, mock_build_ci: MagicMock) -> None:
        from src.config import CodeInterpreterConfig
        mock_ci_tools = MagicMock()
        mock_build_ci.return_value = ([MagicMock(name="ci_tool")], mock_ci_tools)

        config = _make_config()
        config.integrations.code_interpreter = CodeInterpreterConfig(enabled=True, region="us-west-2")
        agent, plugins, ci = await build_agent(config)

        mock_build_ci.assert_called_once()
        self.assertIs(ci, mock_ci_tools)

    async def test_code_interpreter_disabled_no_tools(self) -> None:
        config = _make_config()
        agent, plugins, ci = await build_agent(config)
        self.assertIsNone(ci)
        self.assertEqual(agent.tools, [])


class TestBuildModel(unittest.TestCase):
    """Tests for the build_model provider dispatch."""

    def _make_config(self, **overrides) -> AgentConfig:
        base = dict(
            system_prompt="Test prompt",
            model_id="us.anthropic.claude-sonnet-4-20250514",
        )
        base.update(overrides)
        return AgentConfig(**base)

    @patch("src.agent.LiteLlm")
    def test_defaults_to_bedrock(self, mock_lite_llm: MagicMock) -> None:
        config = self._make_config()
        build_model(config)
        mock_lite_llm.assert_called_once()
        call_kwargs = mock_lite_llm.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "bedrock/us.anthropic.claude-sonnet-4-20250514")
        self.assertIn("aws_region_name", call_kwargs)

    @patch("src.agent.resolve_secret", return_value="sk-test-key")
    @patch("src.agent.LiteLlm")
    def test_openai_provider(self, mock_lite_llm: MagicMock, mock_resolve: MagicMock) -> None:
        config = self._make_config(
            model_id="gpt-4o",
            provider="openai",
            base_url="https://api.example.com/v1",
            api_key_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key",
        )
        build_model(config)
        mock_resolve.assert_called_once_with("arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key")
        call_kwargs = mock_lite_llm.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "openai/gpt-4o")
        self.assertEqual(call_kwargs["api_key"], "sk-test-key")
        self.assertEqual(call_kwargs["base_url"], "https://api.example.com/v1")
        self.assertEqual(call_kwargs["timeout"], 30.0)

    @patch("src.agent.resolve_secret", return_value="sk-ant-test-key")
    @patch("src.agent.LiteLlm")
    def test_anthropic_provider(self, mock_lite_llm: MagicMock, mock_resolve: MagicMock) -> None:
        config = self._make_config(
            model_id="claude-3-7-sonnet-latest",
            provider="anthropic",
            api_key_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key",
        )
        build_model(config)
        call_kwargs = mock_lite_llm.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "anthropic/claude-3-7-sonnet-latest")
        self.assertEqual(call_kwargs["api_key"], "sk-ant-test-key")

    @patch("src.agent.resolve_secret", return_value="litellm-key")
    @patch("src.agent.LiteLlm")
    def test_litellm_provider(self, mock_lite_llm: MagicMock, mock_resolve: MagicMock) -> None:
        config = self._make_config(
            model_id="openai/gpt-4o",
            provider="litellm",
            base_url="https://litellm.internal.example.com",
            api_key_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key",
        )
        build_model(config)
        call_kwargs = mock_lite_llm.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "litellm_proxy/openai/gpt-4o")
        self.assertTrue(call_kwargs["use_litellm_proxy"])
        self.assertEqual(call_kwargs["base_url"], "https://litellm.internal.example.com")

    @patch("src.agent.resolve_secret", return_value="litellm-key")
    @patch("src.agent.LiteLlm")
    def test_litellm_provider_with_bare_model_id_still_routes_through_proxy(
        self, mock_lite_llm: MagicMock, mock_resolve: MagicMock
    ) -> None:
        """A bare model id (no "openai/"/"anthropic/" prefix) — e.g.
        "claude-sonnet-5" as configured on a LiteLLM proxy's model list —
        must still set use_litellm_proxy=True and the litellm_proxy/ prefix.
        Without it, litellm's SDK-side provider auto-detection would route
        straight at the real upstream provider using our proxy's virtual key,
        instead of through base_url."""
        config = self._make_config(
            model_id="claude-sonnet-5",
            provider="litellm",
            base_url="https://litellm.internal.example.com",
            api_key_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key",
        )
        build_model(config)
        call_kwargs = mock_lite_llm.call_args.kwargs
        self.assertTrue(call_kwargs["use_litellm_proxy"])
        self.assertEqual(call_kwargs["model"], "litellm_proxy/claude-sonnet-5")

    def test_non_bedrock_provider_requires_secret_arn(self) -> None:
        config = self._make_config(model_id="gpt-4o", provider="openai")
        with self.assertRaises(ValueError) as ctx:
            build_model(config)
        self.assertIn("api_key_secret_arn", str(ctx.exception))

    def test_unknown_provider_raises(self) -> None:
        config = self._make_config(model_id="some-model", provider="cohere")
        with self.assertRaises(ValueError) as ctx:
            build_model(config)
        self.assertIn("Unsupported model provider", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
