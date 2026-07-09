"""Tests for per-user authorizer linking service."""
import json
import unittest
from unittest.mock import patch, MagicMock

from app.services.authorizer_linking import (
    _secret_name,
    check_link_status,
    store_user_tokens,
    delete_user_tokens,
    resolve_access_token,
    exchange_code_for_tokens,
    _token_cache,
)


class TestSecretName(unittest.TestCase):
    def test_format(self):
        self.assertEqual(
            _secret_name(42, "user-abc"),
            "loom/authorizers/42/user-tokens/user-abc",
        )


class TestCheckLinkStatus(unittest.TestCase):
    @patch("app.services.authorizer_linking.get_secret")
    def test_linked(self, mock_get):
        mock_get.return_value = '{"refresh_token": "rt"}'
        self.assertTrue(check_link_status(1, "u1", "us-east-1"))
        mock_get.assert_called_once_with("loom/authorizers/1/user-tokens/u1", "us-east-1")

    @patch("app.services.authorizer_linking.get_secret")
    def test_not_linked(self, mock_get):
        mock_get.side_effect = Exception("not found")
        self.assertFalse(check_link_status(1, "u1", "us-east-1"))


class TestStoreUserTokens(unittest.TestCase):
    @patch("app.services.authorizer_linking.store_secret")
    def test_stores_json(self, mock_store):
        mock_store.return_value = "arn:aws:secretsmanager:us-east-1:123:secret:test"
        result = store_user_tokens(5, "user-x", "refresh-token-abc", "us-east-1")
        self.assertIn("arn:", result)

        call_args = mock_store.call_args
        stored = json.loads(call_args[1]["secret_value"] if "secret_value" in call_args[1] else call_args[0][1])
        self.assertEqual(stored["refresh_token"], "refresh-token-abc")
        self.assertIn("linked_at", stored)


class TestDeleteUserTokens(unittest.TestCase):
    @patch("app.services.authorizer_linking.delete_secret")
    def test_deletes_and_clears_cache(self, mock_delete):
        _token_cache[(10, "u1")] = ("token", 9999999999)
        delete_user_tokens(10, "u1", "us-east-1")
        mock_delete.assert_called_once_with("loom/authorizers/10/user-tokens/u1", "us-east-1")
        self.assertNotIn((10, "u1"), _token_cache)


class TestResolveAccessToken(unittest.TestCase):
    def tearDown(self):
        _token_cache.clear()

    @patch("app.services.authorizer_linking.get_secret")
    def test_returns_none_when_not_linked(self, mock_get):
        mock_get.side_effect = Exception("not found")
        result = resolve_access_token(1, "u1", "us-east-1", "https://issuer", "cid", "csecret")
        self.assertIsNone(result)

    @patch("app.services.authorizer_linking.urllib.request.urlopen")
    @patch("app.services.authorizer_linking.fetch_discovery")
    @patch("app.services.authorizer_linking.get_secret")
    def test_resolves_token(self, mock_get, mock_disc, mock_urlopen):
        mock_get.return_value = json.dumps({"refresh_token": "rt123"})
        mock_disc.return_value = {"token_endpoint": "https://idp/token", "authorization_endpoint": "https://idp/auth", "jwks_uri": "https://idp/jwks"}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "access_token": "at-new",
            "expires_in": 3600,
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = resolve_access_token(1, "u1", "us-east-1", "https://issuer", "cid", "csecret")
        self.assertEqual(result, "at-new")
        self.assertIn((1, "u1"), _token_cache)

    def test_returns_cached_token(self):
        import time
        _token_cache[(99, "u2")] = ("cached-token", time.time() + 3600)
        result = resolve_access_token(99, "u2", "us-east-1", "https://issuer", "cid", "csecret")
        self.assertEqual(result, "cached-token")


class TestExchangeCodeForTokens(unittest.TestCase):
    @patch("app.services.authorizer_linking.urllib.request.urlopen")
    @patch("app.services.authorizer_linking.fetch_discovery")
    def test_exchanges_code(self, mock_disc, mock_urlopen):
        mock_disc.return_value = {"token_endpoint": "https://idp/token", "authorization_endpoint": "https://idp/auth", "jwks_uri": "https://idp/jwks"}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = exchange_code_for_tokens(
            discovery_url="https://issuer",
            user_client_id="cid",
            user_client_secret="my-test-secret",  # nosec B106
            code="auth-code",
            code_verifier="verifier",
            redirect_uri="https://app/callback",
        )
        self.assertEqual(result["access_token"], "at")
        self.assertEqual(result["refresh_token"], "rt")


if __name__ == "__main__":
    unittest.main()
