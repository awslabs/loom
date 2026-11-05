"""The OAuth2 token cache must tell two different workload tokens apart.

_OAuth2Auth._fetch_resource_token caches the exchanged token. The cache key used only the first
32 characters of the workload token. A JWT starts with its header, which is the same for every
token, so two different callers could share a cache entry and one could be served the other's
downstream token until it expired. The key must cover the whole token.
"""

import unittest
from unittest.mock import MagicMock, patch

from src.integrations import mcp_client
from src.integrations.mcp_client import _OAuth2Auth

# Identical for every token of this form, like a JWT header; longer than the old 32-character prefix.
SHARED_HEADER = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9."


def _identity(*access_tokens: str) -> MagicMock:
    identity = MagicMock()
    identity.return_value.dp_client.get_resource_oauth2_token.side_effect = [
        {"accessToken": t, "expiresIn": 3600} for t in access_tokens
    ]
    return identity


class TestTokenCacheKey(unittest.TestCase):
    def setUp(self) -> None:
        mcp_client._TOKEN_CACHE.clear()
        self.addCleanup(mcp_client._TOKEN_CACHE.clear)

    def _auth(self) -> _OAuth2Auth:
        return _OAuth2Auth("provider", ["scope"], "m2m")

    def test_workload_tokens_sharing_a_prefix_do_not_share_a_cached_token(self) -> None:
        identity = _identity("downstream-for-alice", "downstream-for-bob")
        with patch.object(mcp_client, "IdentityClient", identity):
            alice = self._auth()._fetch_resource_token(SHARED_HEADER + "alice-payload")
            bob = self._auth()._fetch_resource_token(SHARED_HEADER + "bob-payload")

        self.assertEqual("downstream-for-alice", alice)
        self.assertEqual("downstream-for-bob", bob)
        self.assertEqual(2, identity.return_value.dp_client.get_resource_oauth2_token.call_count)

    def test_the_same_workload_token_is_still_served_from_the_cache(self) -> None:
        identity = _identity("downstream-for-alice")
        with patch.object(mcp_client, "IdentityClient", identity):
            first = self._auth()._fetch_resource_token(SHARED_HEADER + "alice-payload")
            second = self._auth()._fetch_resource_token(SHARED_HEADER + "alice-payload")

        self.assertEqual(first, second)
        self.assertEqual(1, identity.return_value.dp_client.get_resource_oauth2_token.call_count)


if __name__ == "__main__":
    unittest.main()
