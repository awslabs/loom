"""Tests for the SSRF-safe outbound fetcher used for OAuth2/OIDC well-known
and token-endpoint calls (mcp.py / a2a.py). These calls are attacker
influenced: an MCP server or A2A agent registration supplies the well-known
URL, and the discovery document supplies the token endpoint.
"""
import socket
import unittest
from unittest.mock import patch, MagicMock

from app.services.net_guard import SSRFBlockedError, _is_disallowed_ip, safe_get, safe_post
import ipaddress


class TestIsDisallowedIp(unittest.TestCase):
    def test_private_ipv4_blocked(self) -> None:
        self.assertTrue(_is_disallowed_ip(ipaddress.ip_address("10.0.0.5")))
        self.assertTrue(_is_disallowed_ip(ipaddress.ip_address("192.168.1.1")))
        self.assertTrue(_is_disallowed_ip(ipaddress.ip_address("172.16.0.1")))

    def test_loopback_blocked(self) -> None:
        self.assertTrue(_is_disallowed_ip(ipaddress.ip_address("127.0.0.1")))
        self.assertTrue(_is_disallowed_ip(ipaddress.ip_address("::1")))

    def test_link_local_and_metadata_blocked(self) -> None:
        self.assertTrue(_is_disallowed_ip(ipaddress.ip_address("169.254.169.254")))
        self.assertTrue(_is_disallowed_ip(ipaddress.ip_address("169.254.0.1")))

    def test_ipv4_mapped_ipv6_blocked(self) -> None:
        """::ffff:169.254.169.254 must be unwrapped and checked as the mapped IPv4 address."""
        self.assertTrue(_is_disallowed_ip(ipaddress.ip_address("::ffff:169.254.169.254")))

    def test_public_ip_allowed(self) -> None:
        self.assertFalse(_is_disallowed_ip(ipaddress.ip_address("93.184.216.34")))


class TestSafeGetPost(unittest.TestCase):
    def test_rejects_non_https_scheme(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            safe_get("http://example.com/.well-known/openid-configuration")

    def test_rejects_file_scheme(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            safe_get("file:///etc/passwd")

    def test_rejects_loopback_host(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            safe_get("https://127.0.0.1/attacker")

    def test_rejects_metadata_ip(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            safe_get("https://169.254.169.254/latest/meta-data/")

    def test_rejects_hostname_resolving_to_private_ip(self) -> None:
        """Attacker-controlled DNS pointing a public-looking hostname at a private IP is blocked."""
        with patch("socket.getaddrinfo") as mock_resolve:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("10.1.2.3", 443))]
            with self.assertRaises(SSRFBlockedError):
                safe_get("https://evil.example.com/.well-known/openid-configuration")

    def test_rejects_dns_resolution_failure(self) -> None:
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("nope")):
            with self.assertRaises(SSRFBlockedError):
                safe_get("https://nonexistent.invalid/")

    def test_pins_connection_to_resolved_ip_and_sets_sni(self) -> None:
        """The request goes out to the resolved IP (not left to re-resolve), with SNI/Host preserved."""
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("93.184.216.34", 443))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_response = MagicMock(status_code=200)
            mock_client.send.return_value = mock_response

            safe_get("https://example.com/.well-known/openid-configuration")

            sent_request = mock_client.send.call_args[0][0]
            self.assertIn("93.184.216.34", str(sent_request.url))
            self.assertEqual(sent_request.extensions.get("sni_hostname"), "example.com")
            self.assertEqual(sent_request.headers.get("host"), "example.com")

    def test_safe_post_sends_form_data_to_pinned_ip(self) -> None:
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("93.184.216.34", 443))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.send.return_value = MagicMock(status_code=200)

            safe_post("https://example.com/token", data={"grant_type": "client_credentials"})

            sent_request = mock_client.send.call_args[0][0]
            self.assertIn("93.184.216.34", str(sent_request.url))
            self.assertEqual(sent_request.method, "POST")


if __name__ == "__main__":
    unittest.main()
