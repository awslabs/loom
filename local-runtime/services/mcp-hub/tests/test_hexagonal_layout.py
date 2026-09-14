"""Smoke tests for hexagonal layout / ports (no I/O)."""
from __future__ import annotations

import unittest

from mcp_hub.adapters.outbound.file_store import FileHubStore
from mcp_hub.adapters.outbound.loom_http import LoomHttpGateway
from mcp_hub.adapters.outbound.oauth_jwks import OAuthJwksValidator
from mcp_hub.application import wiring
from mcp_hub.application.ports import HubStore, LoomGateway, TokenValidator
from mcp_hub.domain.access import profile_keys_for_user
from mcp_hub.domain.errors import AgentsDisabled, HubUnauthorized, ToolNotAllowed
from mcp_hub.domain.identity import normalize_slug


class TestHexagonalLayout(unittest.TestCase):
    def test_domain_imports(self):
        self.assertEqual(normalize_slug("Cursor IDE"), "cursor-ide")
        self.assertIsNone(profile_keys_for_user(["g-admins-super"]))
        self.assertEqual(HubUnauthorized().code, "unauthorized")
        self.assertEqual(ToolNotAllowed().code, "tool_not_allowed")
        self.assertEqual(AgentsDisabled().code, "agents_disabled")

    def test_wiring_defaults(self):
        self.assertIsInstance(wiring.default_store(), FileHubStore)
        self.assertIsInstance(wiring.default_loom(), LoomHttpGateway)
        self.assertIsInstance(wiring.default_tokens(), OAuthJwksValidator)

    def test_ports_are_protocols(self):
        store = FileHubStore()
        self.assertTrue(callable(store.list_clients))
        self.assertTrue(callable(LoomHttpGateway().service_token))
        self.assertTrue(callable(OAuthJwksValidator().validate_access_token))
        self.assertTrue(HubStore)
        self.assertTrue(LoomGateway)
        self.assertTrue(TokenValidator)


if __name__ == "__main__":
    unittest.main()
