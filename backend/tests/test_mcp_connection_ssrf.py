"""Regression tests for the SSRF fix on MCP connection sinks in app.services.mcp.

Follow-up finding to the SSRF/token-leak fix in test_mcp_ssrf.py: that fix
guarded the OAuth2 well-known/token-endpoint calls, but the primary
connection sinks — server.endpoint_url, used by _call_streamable_http,
_initialize_session, and _call_sse — went straight to httpx.post with no
scheme/host validation at all. Unlike OAuth infrastructure, MCP servers are
a legitimate use case for private/VPC-internal addresses (net_guard's
guarded_get/guarded_post), so these tests confirm metadata/loopback/
link-local targets are blocked while private (VPC-internal) targets still
work.

These tests patch at the httpx.Client boundary (not app.services.mcp's
guarded_post) so the real net_guard SSRF validation logic actually runs —
mocking guarded_post itself would bypass the code under test.
"""
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.mcp import _call_sse, _call_streamable_http, _initialize_session


def _make_server(**overrides) -> SimpleNamespace:
    defaults = dict(
        endpoint_url="http://169.254.169.254/mcp",
        transport_type="streamable_http",
        auth_type=None,
        delegation_mode="m2m",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestStreamableHttpSSRFGuard(unittest.TestCase):
    def test_metadata_endpoint_is_blocked(self) -> None:
        server = _make_server(endpoint_url="http://169.254.169.254/mcp")
        with patch("httpx.Client") as mock_client_cls:
            result = _call_streamable_http(server, "tools/list")
        self.assertIsNone(result)
        mock_client_cls.return_value.__enter__.return_value.send.assert_not_called()

    def test_loopback_endpoint_is_blocked(self) -> None:
        server = _make_server(endpoint_url="http://127.0.0.1:9011/mcp")
        with patch("httpx.Client") as mock_client_cls:
            result = _call_streamable_http(server, "tools/list")
        self.assertIsNone(result)
        mock_client_cls.return_value.__enter__.return_value.send.assert_not_called()

    def test_private_vpc_endpoint_still_works(self) -> None:
        """MCP servers on VPC-internal addresses must remain reachable — this
        is a supported deployment pattern, unlike OAuth infrastructure."""
        server = _make_server(endpoint_url="http://10.0.5.20:8080/mcp")
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("10.0.5.20", 8080))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_response = MagicMock(status_code=200)
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json.return_value = {"result": {"tools": []}}
            mock_response.raise_for_status.return_value = None
            mock_client.send.return_value = mock_response

            result = _call_streamable_http(server, "tools/list")
        self.assertIsNotNone(result)
        self.assertTrue(mock_client.send.called)


class TestInitializeSessionSSRFGuard(unittest.TestCase):
    def test_metadata_endpoint_is_blocked(self) -> None:
        server = _make_server(endpoint_url="http://169.254.169.254/mcp")
        with patch("httpx.Client") as mock_client_cls:
            session_id = _initialize_session(server, {})
        self.assertIsNone(session_id)
        mock_client_cls.return_value.__enter__.return_value.send.assert_not_called()


class TestSSESSRFGuard(unittest.TestCase):
    def test_metadata_endpoint_is_blocked(self) -> None:
        server = _make_server(endpoint_url="http://169.254.169.254/mcp", transport_type="sse")
        with patch("httpx.Client") as mock_client_cls:
            result = _call_sse(server, "tools/list")
        self.assertIsNone(result)
        mock_client_cls.return_value.__enter__.return_value.send.assert_not_called()

    def test_link_local_endpoint_is_blocked(self) -> None:
        server = _make_server(endpoint_url="http://169.254.1.1/mcp", transport_type="sse")
        with patch("httpx.Client") as mock_client_cls:
            result = _call_sse(server, "tools/list")
        self.assertIsNone(result)
        mock_client_cls.return_value.__enter__.return_value.send.assert_not_called()

    def test_private_vpc_endpoint_still_works(self) -> None:
        server = _make_server(endpoint_url="http://10.0.5.20:8080/mcp", transport_type="sse")
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("10.0.5.20", 8080))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_response = MagicMock(status_code=200)
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json.return_value = {"result": {}}
            mock_response.raise_for_status.return_value = None
            mock_client.send.return_value = mock_response

            result = _call_sse(server, "tools/list")
        self.assertIsNotNone(result)
        self.assertTrue(mock_client.send.called)


if __name__ == "__main__":
    unittest.main()
