"""A credential provider is never created from an untrusted OAuth2 discovery.

AgentCore fetches a CustomOauth2 provider's discovery document itself and, for
OBO, exchanges the invoking user's access token at the token_endpoint it
names. services/mcp.py and services/a2a.py refuse untrusted token endpoints
for their own exchanges; create_oauth2_credential_provider must refuse them
too, or every deploy path hands the same redirect to AgentCore instead.
"""
import unittest
from unittest.mock import MagicMock, patch

from app.services.credential import (
    UntrustedOAuthDiscovery,
    create_oauth2_credential_provider,
)


class TestUntrustedTokenEndpointIsRefused(unittest.TestCase):
    def test_trusted_discovery_naming_an_untrusted_token_endpoint_creates_nothing(self) -> None:
        client = MagicMock()
        discovery = MagicMock()
        discovery.raise_for_status.return_value = None
        discovery.json.return_value = {
            "issuer": "https://idp.example.com",
            "token_endpoint": "https://attacker.example.net/oauth2/token",
        }
        with patch("boto3.client", return_value=client), \
                patch("app.services.credential.get_trusted_oauth_hosts", return_value={"idp.example.com"}), \
                patch("app.services.credential.safe_get", return_value=discovery) as fetch:
            with self.assertRaises(UntrustedOAuthDiscovery):
                create_oauth2_credential_provider(
                    name="loom-agent-1-mcp-github",
                    client_id="cid",
                    client_secret="SECRET",  # nosec B106
                    auth_server_url="https://idp.example.com/.well-known/openid-configuration",
                    region="us-east-1",
                    delegation_mode="obo",
                    obo_grant_type="TOKEN_EXCHANGE",
                    allow_update=True,
                )
        fetch.assert_called_once()
        client.create_oauth2_credential_provider.assert_not_called()
        client.update_oauth2_credential_provider.assert_not_called()
