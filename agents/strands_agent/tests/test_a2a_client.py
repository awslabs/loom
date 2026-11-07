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
                    credential_provider_name="loom-1-authed-a2a-authed",
                    scopes="read write",
                ),
            )
        ]
        with patch("src.integrations.a2a_client.logger") as mock_logger:
            clients = create_a2a_clients(agents)
            info_calls = [str(c).lower() for c in mock_logger.info.call_args_list]
            self.assertTrue(any("oauth2" in c and "loom-1-authed-a2a-authed" in c for c in info_calls))
            mock_logger.warning.assert_not_called()
        self.assertEqual(len(clients), 1)

    @patch("src.integrations.a2a_client._AuthenticatedA2AAgent")
    @patch("src.integrations.a2a_client._OAuth2Auth")
    def test_obo_auth_matches_mcp_construction(self, mock_auth_cls: MagicMock, _agent_cls: MagicMock) -> None:
        """OBO A2A auth is built like MCP auth: grant type and audience, no raw user token."""
        agents = [
            A2AAgentConfig(
                name="obo",
                enabled=True,
                endpoint_url="https://a2a.example.com/obo",
                auth=AuthConfig(
                    type="oauth2",
                    credential_provider_name="loom-1-obo-a2a-obo",
                    scopes="read",
                    delegation_mode="obo",
                    obo_grant_type="TOKEN_EXCHANGE",
                    audience="api://downstream",
                ),
            )
        ]
        create_a2a_clients(agents)
        mock_auth_cls.assert_called_once_with(
            credential_provider_name="loom-1-obo-a2a-obo",
            scopes=["read"],
            delegation_mode="obo",
            obo_grant_type="TOKEN_EXCHANGE",
            audience="api://downstream",
        )

    @patch("src.integrations.a2a_client.A2AAgent")
    def test_oauth2_without_credential_provider_warns(self, mock_a2a_cls: MagicMock) -> None:
        """OAuth2 with no credential provider can't authenticate — say so instead of failing with a bare 401."""
        agents = [
            A2AAgentConfig(
                name="misconfigured",
                enabled=True,
                endpoint_url="https://a2a.example.com/misconfigured",
                auth=AuthConfig(type="oauth2", well_known_endpoint="https://auth.example.com/.well-known/openid-configuration"),
            )
        ]
        with patch("src.integrations.a2a_client.logger") as mock_logger:
            clients = create_a2a_clients(agents)
            warnings = [str(c) for c in mock_logger.warning.call_args_list]
            self.assertTrue(any("misconfigured" in w and "credential provider" in w for w in warnings))
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
