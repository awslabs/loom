"""Tests for Postgres HubStore (skipped without MCP_HUB_TEST_DATABASE_URL)."""
from __future__ import annotations

import os
import unittest
import uuid


@unittest.skipUnless(
    os.environ.get("MCP_HUB_TEST_DATABASE_URL", "").strip(),
    "set MCP_HUB_TEST_DATABASE_URL to run Postgres store tests",
)
class TestPostgresHubStore(unittest.TestCase):
    def setUp(self) -> None:
        from mcp_hub.adapters.outbound.pg_store import PostgresHubStore

        self.store = PostgresHubStore(os.environ["MCP_HUB_TEST_DATABASE_URL"])
        self.slug = f"test-{uuid.uuid4().hex[:8]}"

    def tearDown(self) -> None:
        self.store.delete_client(self.slug)

    def test_upsert_patch_grants_roundtrip(self) -> None:
        row = self.store.upsert_from_initialize(
            hub_session_id=f"oauth:{self.slug}",
            slug=self.slug,
            declared_name="Test Client",
            declared_version="1",
            declared_family="cursor",
        )
        self.assertEqual(row["slug"], self.slug)
        self.assertEqual(row["status"], "discovered")
        patched = self.store.patch_client(self.slug, {"status": "enabled", "agents_enabled": True})
        assert patched is not None
        self.assertTrue(patched["agents_enabled"])
        self.assertEqual(patched["status"], "enabled")
        grants = self.store.put_profile_grants(
            self.slug,
            "g-users-demo",
            [{"server_id": 1, "access_level": "all_tools", "tool_names": []}],
        )
        assert grants is not None
        self.assertEqual(len(grants["grants"]), 1)
        self.assertEqual(
            self.store.session_client_slug(f"oauth:{self.slug}"),
            self.slug,
        )


class TestNormalizeDsn(unittest.TestCase):
    def test_strips_sqlalchemy_prefix(self) -> None:
        from mcp_hub.adapters.outbound.pg_store import _normalize_dsn

        self.assertEqual(
            _normalize_dsn("postgresql+psycopg2://u:p@h:5432/db"),
            "postgresql://u:p@h:5432/db",
        )


if __name__ == "__main__":
    unittest.main()
