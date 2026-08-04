"""Regression tests for the SSRF / user-token-leak fix in app.services.mcp.

Reproduces the reported attack: an MCP server's oauth2_well_known_url is
attacker-controlled (set via POST /api/mcp/servers or the test-connection
endpoint). Before the fix, _get_oauth2_token/_get_obo_token fetched that URL
and the token_endpoint it returned with no validation — reaching internal
addresses (SSRF) and, in OBO mode, forwarding the caller's real access
token as the OAuth subject_token to whatever host the attacker named.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.mcp import _get_oauth2_token, _get_obo_token


def _make_server(**overrides) -> SimpleNamespace:
    defaults = dict(
        auth_type="oauth2",
        oauth2_well_known_url="https://169.254.169.254/.well-known/openid-configuration",
        oauth2_client_id="client",
        oauth2_client_secret="secret",  # nosec B106
        oauth2_scopes=None,
        oauth2_audience=None,
        delegation_mode="obo",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestOauth2TokenSSRFGuard(unittest.TestCase):
    """_get_oauth2_token (client-credentials / m2m path)."""

    def test_well_known_url_pointing_at_metadata_address_is_blocked(self) -> None:
        server = _make_server()
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            token = _get_oauth2_token(server)
        self.assertIsNone(token)
        mock_get.assert_not_called()
        mock_post.assert_not_called()

    def test_well_known_url_pointing_at_loopback_is_blocked(self) -> None:
        server = _make_server(oauth2_well_known_url="http://127.0.0.1:9011/.well-known/openid-configuration")
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            token = _get_oauth2_token(server)
        self.assertIsNone(token)
        mock_get.assert_not_called()
        mock_post.assert_not_called()

    def test_discovered_token_endpoint_pointing_at_private_ip_is_blocked(self) -> None:
        """Even a legitimate-looking https well-known host must not be able to
        redirect the token exchange to an internal token_endpoint."""
        server = _make_server(oauth2_well_known_url="https://auth.example.com/.well-known/openid-configuration")
        with patch("app.services.mcp.safe_get") as mock_safe_get, \
             patch("httpx.post") as mock_post:
            mock_safe_get.return_value.raise_for_status.return_value = None
            mock_safe_get.return_value.json.return_value = {"token_endpoint": "http://10.0.0.5/collect"}
            token = _get_oauth2_token(server)
        self.assertIsNone(token)
        mock_post.assert_not_called()


class TestOboTokenSSRFGuardAndTokenLeak(unittest.TestCase):
    """_get_obo_token — the finding's headline scenario: a real user access
    token must never be forwarded to an attacker-controlled endpoint."""

    def test_well_known_url_pointing_at_attacker_listener_blocks_before_forwarding_user_token(self) -> None:
        server = _make_server(oauth2_well_known_url="http://127.0.0.1:9011/.well-known/openid-configuration")
        victim_token = "victim-cognito-access-token"  # nosec B105
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            result = _get_obo_token(server, victim_token)
        self.assertIsNone(result)
        # The victim's token must never have been sent anywhere.
        mock_get.assert_not_called()
        mock_post.assert_not_called()

    def test_discovered_token_endpoint_pointing_at_metadata_blocks_before_forwarding_user_token(self) -> None:
        server = _make_server(oauth2_well_known_url="https://auth.example.com/.well-known/openid-configuration")
        victim_token = "victim-cognito-access-token"  # nosec B105
        with patch("app.services.mcp.safe_get") as mock_safe_get, \
             patch("httpx.post") as mock_post:
            mock_safe_get.return_value.raise_for_status.return_value = None
            mock_safe_get.return_value.json.return_value = {
                "token_endpoint": "http://169.254.169.254/latest/meta-data/collect",
            }
            result = _get_obo_token(server, victim_token)
        self.assertIsNone(result)
        mock_post.assert_not_called()

    def test_legitimate_https_endpoints_still_work(self) -> None:
        """Sanity check: the guard doesn't break the legitimate Okta OBO path."""
        server = _make_server(
            oauth2_well_known_url="https://auth.example.com/.well-known/openid-configuration",
            oauth2_audience="api://downstream",
        )
        victim_token = "victim-cognito-access-token"  # nosec B105
        with patch("app.services.mcp.safe_get") as mock_safe_get, \
             patch("app.services.mcp.safe_post") as mock_safe_post:
            mock_safe_get.return_value.raise_for_status.return_value = None
            mock_safe_get.return_value.json.return_value = {
                "token_endpoint": "https://auth.example.com/oauth2/v1/token",
            }
            mock_safe_post.return_value.status_code = 200
            mock_safe_post.return_value.json.return_value = {"access_token": "downstream-token"}
            result = _get_obo_token(server, victim_token)
        self.assertEqual(result, "downstream-token")
        # Confirm the victim token was sent only to the validated https endpoint.
        _, kwargs = mock_safe_post.call_args
        self.assertEqual(kwargs["data"]["subject_token"], victim_token)


if __name__ == "__main__":
    unittest.main()
