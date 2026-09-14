"""Outbound ports for the MCP Hub (hexagonal)."""
from __future__ import annotations

from typing import Any, Protocol

from mcp_hub.domain.records import (
    ClientRecord,
    GrantRecord,
    HubIdentity,
    ProfileGrantsPayload,
)


class HubStore(Protocol):
    """Persistence for MCP clients, grants, and session bindings."""

    def store_path(self) -> str: ...

    def list_clients(self, status: str | None = None) -> list[ClientRecord]: ...

    def get_client(self, slug: str, *, include_grants: bool = False) -> ClientRecord | None: ...

    def get_profile_grants(self, slug: str, group: str) -> ProfileGrantsPayload | None: ...

    def put_profile_grants(
        self, slug: str, group: str, grants: list[GrantRecord]
    ) -> ClientRecord | None: ...

    def put_grants(self, slug: str, grants: list[GrantRecord]) -> ClientRecord | None: ...

    def upsert_from_initialize(
        self,
        *,
        hub_session_id: str,
        slug: str,
        declared_name: str,
        declared_version: str,
        declared_family: str,
        display_name: str | None = None,
    ) -> ClientRecord: ...

    def session_client_slug(self, hub_session_id: str) -> str | None: ...

    def patch_client(self, slug: str, patch: dict[str, Any]) -> ClientRecord | None: ...

    def delete_client(self, slug: str) -> bool: ...


class LoomGateway(Protocol):
    """HTTP gateway to the Loom BFF (service token)."""

    def service_token(self) -> str: ...

    def materialize_allowlist(
        self,
        *,
        subject: str,
        groups: list[str],
        connection_id: str,
        mcp_client_slug: str,
        client_status: str,
        grants: list[GrantRecord],
    ) -> tuple[int, dict[str, Any]]: ...

    def tools_call(
        self,
        *,
        subject: str,
        groups: list[str],
        tool_name: str,
        arguments: dict[str, Any],
        server_id: int,
        original_tool_name: str,
    ) -> tuple[int, dict[str, Any]]: ...

    def materialize_agents(
        self, *, subject: str, groups: list[str]
    ) -> tuple[int, dict[str, Any]]: ...

    def agents_invoke(
        self,
        *,
        subject: str,
        groups: list[str],
        agent_id: int,
        prompt: str,
        session_id: str | None = None,
        mode: str = "async",
        timeout_s: int = 120,
    ) -> tuple[int, dict[str, Any]]: ...

    def agents_run(
        self, *, subject: str, groups: list[str], session_id: str
    ) -> tuple[int, dict[str, Any]]: ...


class TokenValidator(Protocol):
    """Validate IDE OAuth access tokens for the Hub resource."""

    def validate_access_token(self, token: str) -> HubIdentity | None: ...

    def www_authenticate_value(self) -> str: ...

    def resource_url(self) -> str: ...

    def oidc_issuer(self) -> str: ...

    def warm_jwks(self) -> bool: ...

    def prm_document(self) -> dict[str, Any]: ...
