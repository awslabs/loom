"""Unit tests for mcp-hub identity, access, and store (no Loom)."""
from __future__ import annotations

import os
import tempfile
import unittest

from mcp_hub.access import grants_for_user, merge_profile_grants, profile_keys_for_user
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


class TestAccess(unittest.TestCase):
    def test_profile_keys_cohort(self):
        keys = profile_keys_for_user(["t-admin", "g-admins-demo"])
        assert keys is not None
        self.assertIn("g-admins-demo", keys)
        self.assertIn("g-users-demo", keys)

    def test_super_sees_all(self):
        self.assertIsNone(profile_keys_for_user(["g-admins-super"]))

    def test_grants_for_user_filters_profile(self):
        grants = [
            {"group": "g-users-demo", "server_id": 1, "access_level": "all_tools", "tool_names": []},
            {"group": "g-users-test", "server_id": 2, "access_level": "all_tools", "tool_names": []},
            {"server_id": 3, "access_level": "all_tools", "tool_names": []},
        ]
        got = grants_for_user(["t-user", "g-users-test"], grants)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["server_id"], 2)
        self.assertNotIn("group", got[0])

    def test_merge_profile_grants(self):
        existing = [
            {"group": "g-users-demo", "server_id": 1, "access_level": "all_tools", "tool_names": []},
            {"group": "g-users-test", "server_id": 9, "access_level": "all_tools", "tool_names": []},
        ]
        merged = merge_profile_grants(
            existing,
            group="g-users-demo",
            profile_grants=[
                {"server_id": 7, "access_level": "selected_tools", "tool_names": ["a"]},
            ],
        )
        by_group = {}
        for g in merged:
            by_group.setdefault(g["group"], []).append(g["server_id"])
        self.assertEqual(by_group["g-users-demo"], [7])
        self.assertEqual(by_group["g-users-test"], [9])


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

    def test_list_summary_hides_grants(self):
        store.upsert_from_initialize(
            hub_session_id="s1",
            slug="cursor",
            declared_name="cursor",
            declared_version="1",
            declared_family="cursor",
        )
        store.put_profile_grants(
            "cursor",
            "g-users-demo",
            [{"server_id": 7, "access_level": "all_tools", "tool_names": []}],
        )
        rows = store.list_clients()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("grants", rows[0])
        self.assertEqual(rows[0]["granted_profiles"], ["g-users-demo"])
        self.assertEqual(rows[0]["grant_count"], 1)

    def test_empty_profile_grants_is_empty_list(self):
        store.upsert_from_initialize(
            hub_session_id="s1",
            slug="cursor",
            declared_name="cursor",
            declared_version="1",
            declared_family="cursor",
        )
        payload = store.get_profile_grants("cursor", "g-users-demo")
        assert payload is not None
        self.assertEqual(payload["grants"], [])
        self.assertEqual(payload["group"], "g-users-demo")

        store.upsert_from_initialize(
            hub_session_id="s1",
            slug="cursor",
            declared_name="cursor",
            declared_version="1",
            declared_family="cursor",
        )
        store.put_profile_grants(
            "cursor",
            "g-users-demo",
            [{"server_id": 1, "access_level": "all_tools", "tool_names": []}],
        )
        store.put_profile_grants(
            "cursor",
            "g-users-test",
            [{"server_id": 2, "access_level": "selected_tools", "tool_names": ["x"]}],
        )
        demo = store.get_profile_grants("cursor", "g-users-demo")
        assert demo is not None
        self.assertEqual(len(demo["grants"]), 1)
        self.assertEqual(demo["grants"][0]["server_id"], 1)
        # Overwrite demo only — test untouched
        store.put_profile_grants("cursor", "g-users-demo", [])
        test = store.get_profile_grants("cursor", "g-users-test")
        assert test is not None
        self.assertEqual(len(test["grants"]), 1)
        full = store.get_client("cursor", include_grants=True)
        assert full is not None
        self.assertEqual(len(full["grants"]), 1)
        self.assertEqual(full["grants"][0]["group"], "g-users-test")


if __name__ == "__main__":
    unittest.main()
