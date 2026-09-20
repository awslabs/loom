"""Regression tests for the OAuth2 token-endpoint trust check in app.services.a2a.

Companion to test_mcp_ssrf.py: A2A agents support only the client-credentials
(M2M) OAuth2 flow server-side (no OBO here), but the same residual gap
applies — a well-known URL and the token_endpoint it advertises are both
agent-registration input (a2a:write), and safe_get/safe_post alone only
block internal/metadata addresses, not "any public HTTPS host the attacker
happens to control". Sending the agent's own stored client_secret to such a
host would leak it.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.a2a import _get_oauth2_token


def _make_agent(**overrides) -> SimpleNamespace:
    defaults = dict(
        auth_type="oauth2",
        oauth2_well_known_url="https://attacker.example.net/.well-known/openid-configuration",
        oauth2_client_id="client",
        oauth2_client_secret="secret",  # nosec B106
        oauth2_scopes=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestA2aOauth2TokenTrustedHostGuard(unittest.TestCase):
    def test_untrusted_public_https_token_endpoint_blocks_before_leaking_client_secret(self) -> None:
        agent = _make_agent()
        with patch("app.services.a2a.safe_get") as mock_safe_get, \
             patch("app.services.a2a.safe_post") as mock_safe_post, \
             patch("app.services.a2a.get_trusted_oauth_hosts", return_value=set()):
            mock_safe_get.return_value.raise_for_status.return_value = None
            mock_safe_get.return_value.json.return_value = {
                "token_endpoint": "https://attacker.example.net/collect",
            }
            token = _get_oauth2_token(agent)
        self.assertIsNone(token)
        mock_safe_post.assert_not_called()

    def test_trusted_token_endpoint_still_works(self) -> None:
        agent = _make_agent(oauth2_well_known_url="https://auth.example.com/.well-known/openid-configuration")
        with patch("app.services.a2a.safe_get") as mock_safe_get, \
             patch("app.services.a2a.safe_post") as mock_safe_post, \
             patch("app.services.a2a.get_trusted_oauth_hosts", return_value={"auth.example.com"}):
            mock_safe_get.return_value.raise_for_status.return_value = None
            mock_safe_get.return_value.json.return_value = {
                "token_endpoint": "https://auth.example.com/oauth2/v1/token",
            }
            mock_safe_post.return_value.status_code = 200
            mock_safe_post.return_value.json.return_value = {"access_token": "m2m-token"}
            token = _get_oauth2_token(agent)
        self.assertEqual(token, "m2m-token")


if __name__ == "__main__":
    unittest.main()
