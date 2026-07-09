"""Tests for MCP client initialization logic."""

import unittest
from unittest.mock import patch, MagicMock

from src.config import MCPServerConfig, AuthConfig
from src.integrations.mcp_client import create_mcp_clients


class TestCreateMCPClients(unittest.TestCase):
    """Tests for MCP tool client creation from configuration."""

    @patch("src.integrations.mcp_client.MCPClient")
    @patch("src.integrations.mcp_client.streamablehttp_client")
    def test_create_single_enabled_client(
        self, mock_http_client: MagicMock, mock_mcp_client: MagicMock
    ) -> None:
        servers = [
            MCPServerConfig(
                name="jira",
                enabled=True,
                transport="streamable_http",
                endpoint_url="https://mcp.example.com/jira",
                auth=AuthConfig(
                    type="oauth2",
                    well_known_endpoint="https://auth.example.com/.well-known/openid-configuration",
                    credentials_secret_arn="arn:aws:secretsmanager:us-east-1:000000000000:secret:test-secret",  # nosec B106
                ),
            )
        ]
        clients = create_mcp_clients(servers)

        self.assertEqual(len(clients), 1)
        mock_mcp_client.assert_called_once()

    @patch("src.integrations.mcp_client.MCPClient")
    @patch("src.integrations.mcp_client.streamablehttp_client")
    def test_skip_disabled_servers(
        self, mock_http_client: MagicMock, mock_mcp_client: MagicMock
    ) -> None:
        servers = [
            MCPServerConfig(name="disabled", enabled=False, endpoint_url="https://example.com"),
            MCPServerConfig(name="enabled", enabled=True, endpoint_url="https://example.com/active"),
        ]
        clients = create_mcp_clients(servers)

        self.assertEqual(len(clients), 1)

    def test_empty_servers_list(self) -> None:
        clients = create_mcp_clients([])
        self.assertEqual(clients, [])

    @patch("src.integrations.mcp_client.MCPClient")
    @patch("src.integrations.mcp_client.streamablehttp_client")
    def test_multiple_enabled_servers(
        self, mock_http_client: MagicMock, mock_mcp_client: MagicMock
    ) -> None:
        servers = [
            MCPServerConfig(name="s1", enabled=True, endpoint_url="https://s1.example.com"),
            MCPServerConfig(name="s2", enabled=True, endpoint_url="https://s2.example.com"),
        ]
        clients = create_mcp_clients(servers)
        self.assertEqual(len(clients), 2)

    @patch("src.integrations.mcp_client.MCPClient")
    @patch("src.integrations.mcp_client.streamablehttp_client")
    def test_unsupported_transport_skipped(
        self, mock_http_client: MagicMock, mock_mcp_client: MagicMock
    ) -> None:
        servers = [
            MCPServerConfig(
                name="bad-transport",
                enabled=True,
                transport="unknown_protocol",
                endpoint_url="https://example.com",
            )
        ]
        clients = create_mcp_clients(servers)
        self.assertEqual(clients, [])
        mock_mcp_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
