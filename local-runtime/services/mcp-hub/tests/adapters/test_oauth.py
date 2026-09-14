"""Unit tests for Hub OAuth validation (ADR 0011) — no Keycloak."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import MagicMock, patch

from mcp_hub.adapters.outbound import oauth_jwks as oauth


class TestOAuthPrm(unittest.TestCase):
    def setUp(self):
        os.environ["MCP_HUB_OIDC_ISSUER"] = "http://localhost:8081/realms/loom"
        os.environ["MCP_HUB_RESOURCE"] = "http://127.0.0.1:8790/mcp"
        os.environ["MCP_HUB_OIDC_AUDIENCE"] = "loom-mcp-hub"
        os.environ["MCP_HUB_PUBLIC_BASE"] = "http://127.0.0.1:8790"

    def test_prm_lists_issuer(self):
        doc = oauth.prm_document()
        self.assertEqual(doc["resource"], "http://127.0.0.1:8790/mcp")
        self.assertEqual(doc["authorization_servers"], ["http://localhost:8081/realms/loom"])
        self.assertIn("header", doc["bearer_methods_supported"])

    def test_www_authenticate_points_at_prm(self):
        value = oauth.www_authenticate_value()
        self.assertIn("resource_metadata=", value)
        self.assertIn("/.well-known/oauth-protected-resource", value)


class TestOAuthValidate(unittest.TestCase):
    def setUp(self):
        os.environ["MCP_HUB_OIDC_ISSUER"] = "http://localhost:8081/realms/loom"
        os.environ["MCP_HUB_RESOURCE"] = "http://127.0.0.1:8790/mcp"
        os.environ["MCP_HUB_OIDC_AUDIENCE"] = "loom-mcp-hub"
        oauth._jwks_client = None
        oauth._jwks_url_cached = None

    def test_rejects_hs_mint_token(self):
        self.assertIsNone(oauth.validate_access_token("hs_legacy_mint_token"))

    def test_rejects_empty(self):
        self.assertIsNone(oauth.validate_access_token(""))

    def test_rejects_when_issuer_unset(self):
        os.environ["MCP_HUB_OIDC_ISSUER"] = ""
        self.assertIsNone(oauth.validate_access_token("eyJhbGciOiJSUzI1NiJ9.e30.x"))

    @patch("mcp_hub.adapters.outbound.oauth_jwks._get_jwks_client")
    @patch("mcp_hub.adapters.outbound.oauth_jwks.jwt.decode")
    def test_accepts_valid_claims(self, mock_decode: MagicMock, mock_jwks: MagicMock) -> None:
        mock_jwks.return_value.get_signing_key_from_jwt.return_value.key = "k"
        mock_decode.return_value = {
            "sub": "user-1",
            "iss": "http://localhost:8081/realms/loom",
            "exp": int(time.time()) + 600,
            "aud": "loom-mcp-hub",
            "groups": ["t-user", "g-users-demo"],
            "preferred_username": "demo",
        }
        identity = oauth.validate_access_token("fake.jwt.token")
        assert identity is not None
        self.assertEqual(identity["sub"], "user-1")
        self.assertIn("g-users-demo", identity["groups"])
        self.assertEqual(identity["connection_id"], "oauth:user-1")

    @patch("mcp_hub.adapters.outbound.oauth_jwks._get_jwks_client")
    @patch("mcp_hub.adapters.outbound.oauth_jwks.jwt.decode")
    def test_rejects_wrong_audience(self, mock_decode: MagicMock, mock_jwks: MagicMock) -> None:
        mock_jwks.return_value.get_signing_key_from_jwt.return_value.key = "k"
        mock_decode.return_value = {
            "sub": "user-1",
            "iss": "http://localhost:8081/realms/loom",
            "exp": int(time.time()) + 600,
            "aud": "loom-frontend",
            "azp": "loom-frontend",
            "groups": ["g-users-demo"],
        }
        self.assertIsNone(oauth.validate_access_token("fake.jwt.token"))


if __name__ == "__main__":
    unittest.main()
