"""Tests for configuration loading and validation."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src.config import (
    AgentConfig,
    AuthConfig,
    IntegrationsConfig,
    MCPServerConfig,
    A2AAgentConfig,
    MemoryConfig,
    load_config,
    _parse_config,
)


class TestParseConfig(unittest.TestCase):
    """Tests for _parse_config validation."""

    def test_minimal_config(self) -> None:
        data = {
            "system_prompt": "You are helpful.",
            "model_id": "us.anthropic.claude-sonnet-4-20250514",
        }
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_SYSTEM_PROMPT", None)
            config = _parse_config(data)
        self.assertEqual(config.system_prompt, "You are helpful.")
        self.assertEqual(config.model_id, "us.anthropic.claude-sonnet-4-20250514")
        self.assertEqual(config.integrations.mcp_servers, [])
        self.assertEqual(config.integrations.a2a_agents, [])
        self.assertFalse(config.integrations.memory.enabled)

    def test_missing_system_prompt_and_no_env(self) -> None:
        data = {"model_id": "some-model"}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_SYSTEM_PROMPT", None)
            with self.assertRaises(ValueError) as ctx:
                _parse_config(data)
            self.assertIn("system prompt", str(ctx.exception).lower())

    def test_missing_model_id(self) -> None:
        data = {"system_prompt": "Hello"}
        with self.assertRaises(ValueError) as ctx:
            _parse_config(data)
        self.assertIn("model_id", str(ctx.exception))

    def test_system_prompt_from_env_overrides_config(self) -> None:
        data = {
            "system_prompt": "From config file",
            "model_id": "test-model",
        }
        with patch.dict(os.environ, {"AGENT_SYSTEM_PROMPT": "From env var"}, clear=False):
            config = _parse_config(data)
        self.assertEqual(config.system_prompt, "From env var")

    def test_system_prompt_from_env_when_missing_in_config(self) -> None:
        data = {"model_id": "test-model"}
        with patch.dict(os.environ, {"AGENT_SYSTEM_PROMPT": "Injected prompt"}, clear=False):
            config = _parse_config(data)
        self.assertEqual(config.system_prompt, "Injected prompt")

    def test_full_config_with_integrations(self) -> None:
        data = {
            "system_prompt": "Test prompt",
            "model_id": "test-model",
            "integrations": {
                "mcp_servers": [
                    {
                        "name": "jira",
                        "enabled": True,
                        "transport": "streamable_http",
                        "endpoint_url": "https://mcp.example.com/jira",
                        "auth": {
                            "type": "oauth2",
                            "well_known_endpoint": "https://auth.example.com/.well-known/openid-configuration",
                            "credentials_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:test",
                        },
                    }
                ],
                "a2a_agents": [
                    {
                        "name": "summarizer",
                        "enabled": False,
                        "endpoint_url": "https://a2a.example.com/summarizer",
                    }
                ],
                "memory": {"enabled": True},
            },
        }
        config = _parse_config(data)
        self.assertEqual(len(config.integrations.mcp_servers), 1)
        self.assertTrue(config.integrations.mcp_servers[0].enabled)
        self.assertEqual(config.integrations.mcp_servers[0].name, "jira")
        self.assertEqual(config.integrations.mcp_servers[0].auth.type, "oauth2")
        self.assertEqual(len(config.integrations.a2a_agents), 1)
        self.assertFalse(config.integrations.a2a_agents[0].enabled)
        self.assertTrue(config.integrations.memory.enabled)

    def test_mcp_server_defaults(self) -> None:
        data = {
            "system_prompt": "Test",
            "model_id": "model",
            "integrations": {
                "mcp_servers": [{"name": "basic"}],
            },
        }
        config = _parse_config(data)
        server = config.integrations.mcp_servers[0]
        self.assertFalse(server.enabled)
        self.assertEqual(server.transport, "streamable_http")
        self.assertEqual(server.endpoint_url, "")
        self.assertIsNone(server.auth)

    def test_empty_integrations(self) -> None:
        data = {
            "system_prompt": "Test",
            "model_id": "model",
            "integrations": {},
        }
        config = _parse_config(data)
        self.assertEqual(config.integrations.mcp_servers, [])
        self.assertEqual(config.integrations.a2a_agents, [])
        self.assertFalse(config.integrations.memory.enabled)


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config from environment."""

    def test_load_from_json_env(self) -> None:
        config_data = {
            "system_prompt": "From env",
            "model_id": "env-model",
        }
        with patch.dict(os.environ, {"AGENT_CONFIG_JSON": json.dumps(config_data)}, clear=False):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("AGENT_CONFIG_PATH", None)
                config = load_config()
        self.assertEqual(config.system_prompt, "From env")
        self.assertEqual(config.model_id, "env-model")

    def test_load_from_file(self) -> None:
        config_data = {
            "system_prompt": "From file",
            "model_id": "file-model",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            try:
                env = {"AGENT_CONFIG_PATH": f.name}
                with patch.dict(os.environ, env, clear=False):
                    os.environ.pop("AGENT_CONFIG_JSON", None)
                    config = load_config()
                self.assertEqual(config.system_prompt, "From file")
            finally:
                os.unlink(f.name)

    def test_json_env_takes_precedence_over_file(self) -> None:
        json_config = {"system_prompt": "From JSON", "model_id": "json-model"}
        file_config = {"system_prompt": "From file", "model_id": "file-model"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(file_config, f)
            f.flush()
            try:
                env = {
                    "AGENT_CONFIG_JSON": json.dumps(json_config),
                    "AGENT_CONFIG_PATH": f.name,
                }
                with patch.dict(os.environ, env, clear=False):
                    config = load_config()
                self.assertEqual(config.system_prompt, "From JSON")
            finally:
                os.unlink(f.name)

    def test_no_config_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_CONFIG_JSON", None)
            os.environ.pop("AGENT_CONFIG_PATH", None)
            with self.assertRaises(ValueError) as ctx:
                load_config()
            self.assertIn("No configuration found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
