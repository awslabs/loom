"""Tests for the SSRF-safe outbound fetcher used for OAuth2/OIDC well-known
and token-endpoint calls (mcp.py / a2a.py). These calls are attacker
influenced: an MCP server or A2A agent registration supplies the well-known
URL, and the discovery document supplies the token endpoint.
"""
import socket
import unittest
from unittest.mock import patch, MagicMock

from app.services.net_guard import (
    SSRFBlockedError,
    _is_always_disallowed_ip,
    _is_disallowed_ip,
    guarded_get,
    guarded_post,
    safe_get,
    safe_post,
)
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


class TestIsAlwaysDisallowedIp(unittest.TestCase):
    """The permissive guard level: private/VPC addresses are allowed, but
    metadata/loopback/link-local/multicast/reserved/unspecified never are."""

    def test_private_ipv4_allowed(self) -> None:
        self.assertFalse(_is_always_disallowed_ip(ipaddress.ip_address("10.0.0.5")))
        self.assertFalse(_is_always_disallowed_ip(ipaddress.ip_address("192.168.1.1")))
        self.assertFalse(_is_always_disallowed_ip(ipaddress.ip_address("172.16.0.1")))

    def test_loopback_still_blocked(self) -> None:
        self.assertTrue(_is_always_disallowed_ip(ipaddress.ip_address("127.0.0.1")))
        self.assertTrue(_is_always_disallowed_ip(ipaddress.ip_address("::1")))

    def test_metadata_and_link_local_still_blocked(self) -> None:
        self.assertTrue(_is_always_disallowed_ip(ipaddress.ip_address("169.254.169.254")))
        self.assertTrue(_is_always_disallowed_ip(ipaddress.ip_address("169.254.0.1")))

    def test_public_ip_allowed(self) -> None:
        self.assertFalse(_is_always_disallowed_ip(ipaddress.ip_address("93.184.216.34")))


class TestGuardedGetPost(unittest.TestCase):
    """guarded_get/guarded_post — used for MCP endpoint_url / A2A base_url,
    where private/VPC-internal targets are a legitimate, supported use case."""

    def test_allows_http_scheme(self) -> None:
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("93.184.216.34", 80))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.send.return_value = MagicMock(status_code=200, is_redirect=False)

            resp = guarded_get("http://example.com/mcp")
            self.assertEqual(resp.status_code, 200)

    def test_allows_private_ip_target(self) -> None:
        """VPC-internal MCP servers/A2A agents must remain reachable."""
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("10.0.5.20", 8080))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.send.return_value = MagicMock(status_code=200, is_redirect=False)

            resp = guarded_get("http://internal-mcp.vpc.local:8080/mcp")
            self.assertEqual(resp.status_code, 200)
            sent_request = mock_client.send.call_args[0][0]
            self.assertIn("10.0.5.20", str(sent_request.url))

    def test_blocks_metadata_target(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            guarded_get("http://169.254.169.254/latest/meta-data/")

    def test_blocks_loopback_target(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            guarded_get("http://127.0.0.1:9011/mcp")

    def test_blocks_disallowed_scheme(self) -> None:
        with self.assertRaises(SSRFBlockedError):
            guarded_get("file:///etc/passwd")

    def test_redirect_to_metadata_is_blocked(self) -> None:
        """A legitimate-looking initial target must not be able to redirect
        the request to a disallowed address (non-blind SSRF via redirect)."""
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            def _resolve(hostname, *_args, **_kwargs):
                if hostname == "example.com":
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

            with self.assertRaises(SSRFBlockedError):
                guarded_get("http://example.com/mcp")

    def test_redirect_to_allowed_private_target_is_followed(self) -> None:
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            def _resolve(hostname, *_args, **_kwargs):
                if hostname == "gateway.internal":
                    return [(socket.AF_INET, None, None, None, ("10.0.0.9", 80))]
                if hostname == "backend.internal":
                    return [(socket.AF_INET, None, None, None, ("10.0.0.10", 80))]
                raise AssertionError(f"unexpected resolve for {hostname}")
            mock_resolve.side_effect = _resolve

            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            redirect_resp = MagicMock(status_code=302, is_redirect=True)
            redirect_resp.headers = {"location": "http://backend.internal/mcp"}
            final_resp = MagicMock(status_code=200, is_redirect=False)
            mock_client.send.side_effect = [redirect_resp, final_resp]

            resp = guarded_get("http://gateway.internal/mcp")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(mock_client.send.call_count, 2)

    def test_exceeds_max_redirects_raises(self) -> None:
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("93.184.216.34", 80))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            redirect_resp = MagicMock(status_code=302, is_redirect=True)
            redirect_resp.headers = {"location": "http://example.com/next"}
            mock_client.send.return_value = redirect_resp

            with self.assertRaises(SSRFBlockedError):
                guarded_get("http://example.com/mcp")

    def test_guarded_post_sends_json_to_pinned_ip(self) -> None:
        with patch("socket.getaddrinfo") as mock_resolve, \
             patch("httpx.Client") as mock_client_cls:
            mock_resolve.return_value = [(socket.AF_INET, None, None, None, ("10.0.0.5", 80))]
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.send.return_value = MagicMock(status_code=200, is_redirect=False)

            guarded_post("http://internal-mcp.vpc.local/mcp", json={"jsonrpc": "2.0", "method": "initialize"})

            sent_request = mock_client.send.call_args[0][0]
            self.assertIn("10.0.0.5", str(sent_request.url))
            self.assertEqual(sent_request.method, "POST")


if __name__ == "__main__":
    unittest.main()
