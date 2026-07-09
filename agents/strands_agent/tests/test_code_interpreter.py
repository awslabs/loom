"""Tests for Code Interpreter integration."""

import unittest
from unittest.mock import patch, MagicMock

from src.config import (
    AgentConfig,
    CodeInterpreterConfig,
    IntegrationsConfig,
    MemoryConfig,
)
from src.agent import build_agent


class TestCodeInterpreterIntegration(unittest.TestCase):
    """Tests for Code Interpreter tool registration in build_agent."""

    def _make_config(self, ci_enabled: bool = False, ci_region: str = "", ci_identifier: str = "") -> AgentConfig:
        return AgentConfig(
            system_prompt="Test prompt",
            model_id="us.anthropic.claude-sonnet-4-20250514",
            integrations=IntegrationsConfig(
                memory=MemoryConfig(enabled=False),
                code_interpreter=CodeInterpreterConfig(
                    enabled=ci_enabled,
                    region=ci_region,
                    identifier=ci_identifier,
                ),
            ),
        )

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    @patch("src.agent.AgentCoreCodeInterpreter")
    def test_code_interpreter_enabled(
        self,
        mock_ci_cls: MagicMock,
        mock_model_cls: MagicMock,
        mock_agent_cls: MagicMock,
    ) -> None:
        mock_ci_instance = MagicMock()
        mock_tool = MagicMock()
        mock_ci_instance.code_interpreter = mock_tool
        mock_ci_cls.return_value = mock_ci_instance

        config = self._make_config(ci_enabled=True, ci_region="us-west-2")
        build_agent(config)

        mock_ci_cls.assert_called_once_with(region="us-west-2")
        call_kwargs = mock_agent_cls.call_args[1]
        self.assertIn(mock_tool, call_kwargs["tools"])

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    @patch("src.agent.AgentCoreCodeInterpreter")
    def test_code_interpreter_with_identifier(
        self,
        mock_ci_cls: MagicMock,
        mock_model_cls: MagicMock,
        mock_agent_cls: MagicMock,
    ) -> None:
        mock_ci_instance = MagicMock()
        mock_ci_instance.code_interpreter = MagicMock()
        mock_ci_cls.return_value = mock_ci_instance

        config = self._make_config(ci_enabled=True, ci_region="us-east-1", ci_identifier="my-custom-ci")
        build_agent(config)

        mock_ci_cls.assert_called_once_with(region="us-east-1", identifier="my-custom-ci")

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    @patch("src.agent.AgentCoreCodeInterpreter")
    def test_code_interpreter_disabled(
        self,
        mock_ci_cls: MagicMock,
        mock_model_cls: MagicMock,
        mock_agent_cls: MagicMock,
    ) -> None:
        config = self._make_config(ci_enabled=False)
        build_agent(config)

        mock_ci_cls.assert_not_called()
        call_kwargs = mock_agent_cls.call_args[1]
        self.assertEqual(call_kwargs["tools"], [])

    @patch("src.agent.Agent")
    @patch("src.agent.BedrockModel")
    @patch("src.agent.AgentCoreCodeInterpreter")
    def test_code_interpreter_no_region_uses_default(
        self,
        mock_ci_cls: MagicMock,
        mock_model_cls: MagicMock,
        mock_agent_cls: MagicMock,
    ) -> None:
        mock_ci_instance = MagicMock()
        mock_ci_instance.code_interpreter = MagicMock()
        mock_ci_cls.return_value = mock_ci_instance

        config = self._make_config(ci_enabled=True)
        build_agent(config)

        mock_ci_cls.assert_called_once_with()


class TestCodeInterpreterConfig(unittest.TestCase):
    """Tests for CodeInterpreterConfig parsing."""

    def test_default_config(self) -> None:
        config = CodeInterpreterConfig()
        self.assertFalse(config.enabled)
        self.assertEqual(config.region, "")
        self.assertEqual(config.identifier, "")

    def test_config_with_values(self) -> None:
        config = CodeInterpreterConfig(enabled=True, region="us-west-2", identifier="custom-ci")
        self.assertTrue(config.enabled)
        self.assertEqual(config.region, "us-west-2")
        self.assertEqual(config.identifier, "custom-ci")


class TestCodeInterpreterConfigParsing(unittest.TestCase):
    """Tests for parsing code_interpreter from JSON config."""

    def test_parse_with_code_interpreter(self) -> None:
        from src.config import _parse_config
        import os
        from unittest.mock import patch as mock_patch

        data = {
            "system_prompt": "Test",
            "model_id": "test-model",
            "integrations": {
                "code_interpreter": {
                    "enabled": True,
                    "region": "us-west-2",
                    "identifier": "my-ci",
                }
            },
        }
        with mock_patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_SYSTEM_PROMPT", None)
            config = _parse_config(data)

        self.assertTrue(config.integrations.code_interpreter.enabled)
        self.assertEqual(config.integrations.code_interpreter.region, "us-west-2")
        self.assertEqual(config.integrations.code_interpreter.identifier, "my-ci")

    def test_parse_without_code_interpreter(self) -> None:
        from src.config import _parse_config
        import os
        from unittest.mock import patch as mock_patch

        data = {
            "system_prompt": "Test",
            "model_id": "test-model",
            "integrations": {},
        }
        with mock_patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_SYSTEM_PROMPT", None)
            config = _parse_config(data)

        self.assertFalse(config.integrations.code_interpreter.enabled)


if __name__ == "__main__":
    unittest.main()
