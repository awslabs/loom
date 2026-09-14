"""Composition root helpers — default outbound adapters for the Hub."""
from __future__ import annotations

from mcp_hub.adapters.outbound.file_store import FileHubStore
from mcp_hub.adapters.outbound.loom_http import LoomHttpGateway
from mcp_hub.adapters.outbound.oauth_jwks import OAuthJwksValidator
from mcp_hub.application.ports import HubStore, LoomGateway, TokenValidator


def default_store() -> HubStore:
    return FileHubStore()


def default_loom() -> LoomGateway:
    return LoomHttpGateway()


def default_tokens() -> TokenValidator:
    return OAuthJwksValidator()
