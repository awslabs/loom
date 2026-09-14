"""Typed records shared across Hub ports and domain helpers."""
from __future__ import annotations

from typing import TypedDict


class GrantRecord(TypedDict):
    group: str
    server_id: int
    access_level: str
    tool_names: list[str]


class ClientRecord(TypedDict, total=False):
    slug: str
    display_name: str
    declared_name: str
    declared_version: str
    declared_family: str
    status: str
    agents_enabled: bool
    allowed_groups: list[str]
    granted_profiles: list[str]
    grant_count: int
    grants: list[GrantRecord]
    first_seen_at: str
    last_seen_at: str


class HubIdentity(TypedDict):
    """Normalized identity after OAuth access-token validation."""

    sub: str
    username: str
    groups: list[str]
    connection_id: str


class ProfileGrantsPayload(TypedDict):
    group: str
    grants: list[GrantRecord]
