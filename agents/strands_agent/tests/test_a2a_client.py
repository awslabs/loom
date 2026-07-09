"""Tests for A2A client vending."""

import unittest
from unittest.mock import patch, MagicMock

from src.config import A2AAgentConfig, AuthConfig
from src.integrations.a2a_client import create_a2a_clients, _build_a2a_tool


class TestCreateA2AClients(unittest.TestCase):
    """Tests for A2A agent tool creation from configuration."""

    def test_empty_agents_list(self) -> None:
        clients = create_a2a_clients([])
        self.assertEqual(clients, [])

    def test_disabled_agents_skipped(self) -> None:
        agents = [
            A2AAgentConfig(name="disabled", enabled=False, endpoint_url="https://example.com"),
        ]
        with patch("src.integrations.a2a_client.A2AAgent"):
            clients = create_a2a_clients(agents)
        self.assertEqual(clients, [])

    @patch("src.integrations.a2a_client.A2AAgent")
    def test_enabled_agent_creates_tool(self, mock_a2a_cls: MagicMock) -> None:
        agents = [
            A2AAgentConfig(
                name="summarizer",
                enabled=True,
                endpoint_url="https://a2a.example.com/summarizer",
            )
        ]
        clients = create_a2a_clients(agents)
        self.assertEqual(len(clients), 1)
        mock_a2a_cls.assert_called_once_with(
            endpoint="https://a2a.example.com/summarizer",
            name="summarizer",
        )

    @patch("src.integrations.a2a_client.A2AAgent")
    def test_multiple_enabled_agents(self, mock_a2a_cls: MagicMock) -> None:
        agents = [
            A2AAgentConfig(name="agent1", enabled=True, endpoint_url="https://a1.example.com"),
            A2AAgentConfig(name="agent2", enabled=True, endpoint_url="https://a2.example.com"),
            A2AAgentConfig(name="agent3", enabled=False, endpoint_url="https://a3.example.com"),
        ]
        clients = create_a2a_clients(agents)
        self.assertEqual(len(clients), 2)
        self.assertEqual(mock_a2a_cls.call_count, 2)

    @patch("src.integrations.a2a_client.A2AAgent")
    def test_auth_config_logged(self, mock_a2a_cls: MagicMock) -> None:
        agents = [
            A2AAgentConfig(
                name="authed",
                enabled=True,
                endpoint_url="https://a2a.example.com/authed",
                auth=AuthConfig(
                    type="oauth2",
                    well_known_endpoint="https://auth.example.com/.well-known/openid-configuration",
                    credentials_secret_arn="arn:aws:secretsmanager:us-east-1:000000000000:secret:test-secret",  # nosec B106
                ),
            )
        ]
        with patch("src.integrations.a2a_client.logger") as mock_logger:
            clients = create_a2a_clients(agents)
            # Verify auth info was logged
            info_calls = [str(c) for c in mock_logger.info.call_args_list]
            auth_logged = any("oauth2" in c for c in info_calls)
            self.assertTrue(auth_logged)
        self.assertEqual(len(clients), 1)


class TestBuildA2ATool(unittest.TestCase):
    """Tests for _build_a2a_tool function."""

    @patch("src.integrations.a2a_client.A2AAgent")
    def test_tool_invokes_a2a_agent(self, mock_a2a_cls: MagicMock) -> None:
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.message = "Hello from remote"
        mock_agent.return_value = mock_result
        mock_a2a_cls.return_value = mock_agent

        config = A2AAgentConfig(
            name="helper",
            enabled=True,
            endpoint_url="https://a2a.example.com/helper",
        )
        tool_fn = _build_a2a_tool(config)
        result = tool_fn(message="test message")

        mock_agent.assert_called_once_with("test message")
        self.assertEqual(result, "Hello from remote")


if __name__ == "__main__":
    unittest.main()
