"""Regression tests for the SSRF fix on A2A connection sinks in app.services.a2a.

Follow-up finding to the SSRF/token-leak fix in test_mcp_ssrf.py: the same
report flagged fetch_agent_card / _fetch_salesforce_agent_card, which built
requests from agent.base_url (also user-supplied) and sent them via
httpx.get with follow_redirects=True and no scheme/host validation — and
echoed up to ~200 chars of the response body in error messages, making the
SSRF non-blind. This also allowed a legitimate-looking initial base_url to
redirect the request cross-host to a disallowed address.

Unlike OAuth infrastructure, A2A agents are a legitimate use case for
private/VPC-internal addresses, so guarded_get (net_guard's permissive
guard level) is used here instead of safe_get — these tests confirm
metadata/loopback/link-local targets are blocked (with no body echoed back)
while private (VPC-internal) targets still work.

These tests patch at the httpx.Client boundary (not app.services.a2a's
guarded_get) so the real net_guard SSRF validation logic actually runs.
"""
import socket
import unittest
from unittest.mock import MagicMock, patch

from app.services.a2a import _fetch_salesforce_agent_card, fetch_agent_card


class TestFetchAgentCardSSRFGuard(unittest.TestCase):
    def test_metadata_base_url_is_blocked(self) -> None:
        with patch("httpx.Client") as mock_client_cls:
            with self.assertRaises(ValueError) as ctx:
                fetch_agent_card("http://169.254.169.254")
        mock_client_cls.return_value.__enter__.return_value.send.assert_not_called()
        self.assertIn("Blocked", str(ctx.exception))

    def test_loopback_base_url_is_blocked(self) -> None:
        with patch("httpx.Client") as mock_client_cls:
            with self.assertRaises(ValueError):
                fetch_agent_card("http://127.0.0.1:9011")
        mock_client_cls.return_value.__enter__.return_value.send.assert_not_called()

    def test_blocked_error_does_not_echo_response_body(self) -> None:
        """The finding's non-blind concern: no attacker-controlled response
        content should ever reach the raised error message for a blocked URL."""
        with patch("httpx.Client"):
            with self.assertRaises(ValueError) as ctx:
                fetch_agent_card("http://169.254.169.254/leak-secret-data-here")
        self.assertNotIn("leak-secret-data-here", str(ctx.exception))

    def test_private_vpc_base_url_still_works(self) -> None:
        """A2A agents on VPC-internal addresses must remain reachable — this
        is a supported deployment pattern, unlike OAuth infrastructure."""
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("10.0.5.20", 8080))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_response = MagicMock(status_code=200, is_redirect=False)
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "name": "internal-agent",
                "description": "desc",
                "url": "http://10.0.5.20:8080",
                "version": "1.0",
            }
            mock_client.send.return_value = mock_response

            card = fetch_agent_card("http://10.0.5.20:8080")
        self.assertEqual(card["name"], "internal-agent")

    def test_redirect_to_metadata_is_blocked(self) -> None:
        """A legitimate-looking initial base_url must not be able to redirect
        the request cross-host to a disallowed address."""
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            def _resolve(hostname, *_args, **_kwargs):
                if hostname == "agent.example.com":
                    return [(socket.AF_INET, None, None, None, ("93.184.216.34", 80))]
                if hostname == "169.254.169.254":
                    return [(socket.AF_INET, None, None, None, ("169.254.169.254", 80))]
                raise AssertionError(f"unexpected resolve for {hostname}")
            mock_resolve.side_effect = _resolve

            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            redirect_resp = MagicMock(status_code=302, is_redirect=True)
            redirect_resp.headers = {"location": "http://169.254.169.254/latest/meta-data/"}
            mock_client.send.return_value = redirect_resp

            with self.assertRaises(ValueError):
                fetch_agent_card("http://agent.example.com")


class TestSalesforceAgentCardSSRFGuard(unittest.TestCase):
    def test_metadata_base_url_is_blocked(self) -> None:
        with patch("httpx.Client") as mock_client_cls:
            with self.assertRaises(ValueError):
                _fetch_salesforce_agent_card("http://169.254.169.254", {})
        mock_client_cls.return_value.__enter__.return_value.send.assert_not_called()

    def test_private_vpc_base_url_still_works(self) -> None:
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("10.0.5.20", 8080))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_response = MagicMock(status_code=200, is_redirect=False)
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"name": "sf-agent"}
            mock_client.send.return_value = mock_response

            card = _fetch_salesforce_agent_card("http://10.0.5.20:8080", {})
        self.assertEqual(card["name"], "sf-agent")


if __name__ == "__main__":
    unittest.main()
