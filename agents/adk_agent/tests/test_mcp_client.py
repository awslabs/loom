"""Tests for MCP toolset creation logic."""

import unittest
from unittest.mock import patch, MagicMock

from src.config import MCPServerConfig, AuthConfig
from src.integrations.mcp_client import build_toolsets, build_toolset


class TestBuildToolsets(unittest.TestCase):
    """Tests for MCP toolset creation from configuration."""

    @patch("src.integrations.mcp_client.McpToolset")
    def test_create_single_enabled_toolset(self, mock_toolset_cls: MagicMock) -> None:
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
        toolsets = build_toolsets(servers)

        self.assertEqual(len(toolsets), 1)
        mock_toolset_cls.assert_called_once()

    @patch("src.integrations.mcp_client.McpToolset")
    def test_skip_disabled_servers(self, mock_toolset_cls: MagicMock) -> None:
        servers = [
            MCPServerConfig(name="disabled", enabled=False, endpoint_url="https://example.com"),
            MCPServerConfig(name="enabled", enabled=True, endpoint_url="https://example.com/active"),
        ]
        toolsets = build_toolsets(servers)

        self.assertEqual(len(toolsets), 1)

    def test_empty_servers_list(self) -> None:
        toolsets = build_toolsets([])
        self.assertEqual(toolsets, [])

    @patch("src.integrations.mcp_client.McpToolset")
    def test_multiple_enabled_servers(self, mock_toolset_cls: MagicMock) -> None:
        servers = [
            MCPServerConfig(name="s1", enabled=True, endpoint_url="https://s1.example.com"),
            MCPServerConfig(name="s2", enabled=True, endpoint_url="https://s2.example.com"),
        ]
        toolsets = build_toolsets(servers)
        self.assertEqual(len(toolsets), 2)

    @patch("src.integrations.mcp_client.McpToolset")
    def test_unsupported_transport_skipped(self, mock_toolset_cls: MagicMock) -> None:
        server = MCPServerConfig(
            name="bad-transport",
            enabled=True,
            transport="unknown_protocol",
            endpoint_url="https://example.com",
        )
        toolset = build_toolset(server)
        self.assertIsNone(toolset)
        mock_toolset_cls.assert_not_called()

    @patch("src.integrations.mcp_client.McpToolset")
    def test_oauth2_server_builds_header_provider(self, mock_toolset_cls: MagicMock) -> None:
        server = MCPServerConfig(
            name="oauth-server",
            enabled=True,
            endpoint_url="https://example.com",
            auth=AuthConfig(type="oauth2", credential_provider_name="my-provider"),
        )
        build_toolset(server)
        call_kwargs = mock_toolset_cls.call_args.kwargs
        self.assertIsNotNone(call_kwargs["header_provider"])

    @patch("src.integrations.mcp_client.McpToolset")
    def test_unauthenticated_server_no_header_provider(self, mock_toolset_cls: MagicMock) -> None:
        server = MCPServerConfig(name="plain", enabled=True, endpoint_url="https://example.com")
        build_toolset(server)
        call_kwargs = mock_toolset_cls.call_args.kwargs
        self.assertIsNone(call_kwargs["header_provider"])


if __name__ == "__main__":
    unittest.main()
