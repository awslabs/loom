"""Unit tests for mcp-hub identity + store (no Loom)."""
from __future__ import annotations

import os
import tempfile
import unittest

from mcp_hub.identity import declared_family, normalize_slug, parse_client_info
from mcp_hub import store


class TestIdentity(unittest.TestCase):
    def test_normalize_slug(self):
        self.assertEqual(normalize_slug("Cursor IDE"), "cursor-ide")
        self.assertEqual(normalize_slug(""), "unknown")
        self.assertEqual(normalize_slug("!!!"), "unknown")

    def test_family(self):
        self.assertEqual(declared_family("cursor-vscode"), "cursor")
        self.assertEqual(declared_family("Claude Code"), "claude-code")
        self.assertEqual(declared_family("other"), "unknown")

    def test_parse_client_info(self):
        slug, name, version, family = parse_client_info(
            {"clientInfo": {"name": "cursor", "version": "1.0"}}
        )
        self.assertEqual(slug, "cursor")
        self.assertEqual(name, "cursor")
        self.assertEqual(version, "1.0")
        self.assertEqual(family, "cursor")


class TestStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self._tmp.close()
        os.environ["MCP_HUB_STORE_PATH"] = self._tmp.name
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)

    def tearDown(self):
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)

    def test_upsert_discovered_and_grants(self):
        row = store.upsert_from_initialize(
            hub_session_id="s1",
            slug="cursor",
            declared_name="cursor",
            declared_version="1",
            declared_family="cursor",
        )
        self.assertEqual(row["status"], "discovered")
        self.assertEqual(store.session_client_slug("s1"), "cursor")
        store.patch_client("cursor", {"status": "enabled"})
        updated = store.put_grants(
            "cursor",
            [{"server_id": 7, "access_level": "all_tools", "tool_names": []}],
        )
        assert updated is not None
        self.assertEqual(updated["status"], "enabled")
        self.assertEqual(len(updated["grants"]), 1)


if __name__ == "__main__":
    unittest.main()
