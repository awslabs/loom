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
from src.agent import build_agent, _build_model
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


class TestBuildModel(unittest.TestCase):
    """Tests for the _build_model provider dispatch."""

    def _make_config(self, **overrides) -> AgentConfig:
        base = dict(
            system_prompt="Test prompt",
            model_id="us.anthropic.claude-sonnet-4-20250514",
        )
        base.update(overrides)
        return AgentConfig(**base)

    @patch("src.agent.BedrockModel")
    def test_defaults_to_bedrock(self, mock_bedrock_cls: MagicMock) -> None:
        config = self._make_config()
        model = _build_model(config)
        mock_bedrock_cls.assert_called_once_with(
            model_id="us.anthropic.claude-sonnet-4-20250514",
            max_tokens=4096,
            streaming=True,
        )
        self.assertEqual(model, mock_bedrock_cls.return_value)

    @patch("src.agent.resolve_secret", return_value="sk-test-key")
    @patch("src.agent.OpenAIModel")
    def test_openai_provider(self, mock_openai_cls: MagicMock, mock_resolve: MagicMock) -> None:
        config = self._make_config(
            model_id="gpt-4o",
            provider="openai",
            base_url="https://api.example.com/v1",
            api_key_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key",
        )
        _build_model(config)
        mock_resolve.assert_called_once_with("arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key")
        mock_openai_cls.assert_called_once_with(
            client_args={"api_key": "sk-test-key", "timeout": 30.0, "base_url": "https://api.example.com/v1"},
            model_id="gpt-4o",
            params={"max_tokens": 4096},
        )

    @patch("src.agent.resolve_secret", return_value="sk-ant-test-key")
    @patch("src.agent.AnthropicModel")
    def test_anthropic_provider(self, mock_anthropic_cls: MagicMock, mock_resolve: MagicMock) -> None:
        config = self._make_config(
            model_id="claude-3-7-sonnet-latest",
            provider="anthropic",
            api_key_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key",
        )
        _build_model(config)
        mock_anthropic_cls.assert_called_once_with(
            client_args={"api_key": "sk-ant-test-key", "timeout": 30.0},
            model_id="claude-3-7-sonnet-latest",
            max_tokens=4096,
        )

    @patch("src.agent.resolve_secret", return_value="litellm-key")
    @patch("src.agent.LiteLLMModel")
    def test_litellm_provider(self, mock_litellm_cls: MagicMock, mock_resolve: MagicMock) -> None:
        config = self._make_config(
            model_id="openai/gpt-4o",
            provider="litellm",
            base_url="https://litellm.internal.example.com",
            api_key_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key",
        )
        _build_model(config)
        mock_litellm_cls.assert_called_once_with(
            client_args={
                "api_key": "litellm-key",
                "timeout": 30.0,
                "base_url": "https://litellm.internal.example.com",
                "use_litellm_proxy": True,
            },
            model_id="openai/gpt-4o",
            params={"max_tokens": 4096},
        )

    @patch("src.agent.resolve_secret", return_value="litellm-key")
    @patch("src.agent.LiteLLMModel")
    def test_litellm_provider_with_bare_model_id_still_routes_through_proxy(
        self, mock_litellm_cls: MagicMock, mock_resolve: MagicMock
    ) -> None:
        """A bare model id (no "openai/"/"anthropic/" prefix) — e.g.
        "claude-sonnet-5" as configured on a LiteLLM proxy's model list —
        must still set use_litellm_proxy=True. Without it, litellm's SDK-side
        provider auto-detection would route straight at the real upstream
        provider using our proxy's virtual key, instead of through base_url."""
        config = self._make_config(
            model_id="claude-sonnet-5",
            provider="litellm",
            base_url="https://litellm.internal.example.com",
            api_key_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:llm-key",
        )
        _build_model(config)
        call_kwargs = mock_litellm_cls.call_args.kwargs
        self.assertTrue(call_kwargs["client_args"]["use_litellm_proxy"])

    def test_non_bedrock_provider_requires_secret_arn(self) -> None:
        config = self._make_config(model_id="gpt-4o", provider="openai")
        with self.assertRaises(ValueError) as ctx:
            _build_model(config)
        self.assertIn("api_key_secret_arn", str(ctx.exception))

    def test_unknown_provider_raises(self) -> None:
        config = self._make_config(model_id="some-model", provider="cohere")
        with self.assertRaises(ValueError) as ctx:
            _build_model(config)
        self.assertIn("Unsupported model provider", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
