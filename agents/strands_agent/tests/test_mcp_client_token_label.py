"""Tests for the token_type label on token_info events emitted by _OAuth2Auth."""

import base64
import json
import unittest
from unittest.mock import patch

from src.integrations.mcp_client import (
    _OAuth2Auth,
    drain_token_info_events,
    reset_token_info_state,
)

EXPECTED_CLAIMS = {
    "iss": "https://issuer.example.com",
    "sub": "user-123",
    "aud": "api://downstream",
    "azp": "client-abc",
    "appid": None,
    "cid": None,
    "scp": None,
    "roles": None,
    "act": None,
    "exp": 1900000000,
    "iat": 1800000000,
}


def _b64url(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def _jwt(claims: dict) -> str:
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(claims)}.sig"


class TestTokenInfoTokenType(unittest.TestCase):
    """token_type must follow the delegation mode, not be hardcoded."""

    def setUp(self) -> None:
        reset_token_info_state()
        drain_token_info_events()

    def _emit_for_mode(self, delegation_mode: str) -> dict:
        with patch(
            "src.integrations.mcp_client.BedrockAgentCoreContext.get_workload_access_token",
            return_value="workload-token",
        ):
            auth = _OAuth2Auth(
                credential_provider_name="downstream-cp",
                scopes=["read"],
                delegation_mode=delegation_mode,
            )
        claims = {**EXPECTED_CLAIMS}
        claims["exp"] = EXPECTED_CLAIMS["exp"]
        auth._emit_token_info(_jwt(claims))
        events = drain_token_info_events()
        self.assertEqual(len(events), 1)
        return events[0]

    def test_m2m_token_is_labelled_m2m(self) -> None:
        event = self._emit_for_mode("m2m")
        self.assertEqual(event["token_type"], "m2m")
        self.assertEqual(event["flow"], "M2M")
        self.assertEqual(event["claims"], EXPECTED_CLAIMS)

    def test_obo_token_is_labelled_obo(self) -> None:
        event = self._emit_for_mode("obo")
        self.assertEqual(event["token_type"], "obo")
        self.assertEqual(event["flow"], "ON_BEHALF_OF_TOKEN_EXCHANGE")
        self.assertEqual(event["claims"], EXPECTED_CLAIMS)


if __name__ == "__main__":
    unittest.main()
