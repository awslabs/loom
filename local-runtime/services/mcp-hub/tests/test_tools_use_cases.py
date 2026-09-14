"""Unit tests for tools use cases with fake ports."""
from __future__ import annotations

import unittest
from typing import Any


class FakeStore:
    def __init__(self) -> None:
        self.clients: dict[str, dict[str, Any]] = {}
        self.bindings: dict[str, str] = {}

    def store_path(self) -> str:
        return "/tmp/fake.json"

    def list_clients(self, status: str | None = None) -> list[dict[str, Any]]:
        rows = list(self.clients.values())
        if status:
            rows = [c for c in rows if c.get("status") == status]
        return rows

    def get_client(self, slug: str, *, include_grants: bool = False) -> dict[str, Any] | None:
        row = self.clients.get(slug)
        return None if row is None else dict(row)

    def get_profile_grants(self, slug: str, group: str) -> dict[str, Any] | None:
        return None

    def put_profile_grants(self, slug: str, group: str, grants: list[dict[str, Any]]) -> dict[str, Any] | None:
        return None

    def put_grants(self, slug: str, grants: list[dict[str, Any]]) -> dict[str, Any] | None:
        return None

    def upsert_from_initialize(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def session_client_slug(self, hub_session_id: str) -> str | None:
        return self.bindings.get(hub_session_id)

    def patch_client(self, slug: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def delete_client(self, slug: str) -> bool:
        return False


class FakeLoom:
    def __init__(self) -> None:
        self.allowlist_code = 200
        self.allowlist_payload: dict[str, Any] = {"entries": []}
        self.agents_code = 200
        self.agents_payload: dict[str, Any] = {"agents": [], "monitor_tools": []}
        self.call_status = 200
        self.call_result: dict[str, Any] = {"success": True, "result": {"ok": True}}

    def service_token(self) -> str:
        return "tok"

    def materialize_allowlist(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        return self.allowlist_code, self.allowlist_payload

    def tools_call(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        return self.call_status, self.call_result

    def materialize_agents(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        return self.agents_code, self.agents_payload

    def agents_invoke(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {"status": "accepted", "session_id": "s1"}

    def agents_run(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {"status": "complete", "text": "done"}


class TestToolsUseCases(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeStore()
        self.loom = FakeLoom()
        self.identity = {
            "sub": "u1",
            "groups": ["g-users-demo"],
            "connection_id": "oauth:u1",
        }
        self.store.bindings["oauth:u1"] = "cursor"
        self.store.clients["cursor"] = {
            "slug": "cursor",
            "status": "enabled",
            "agents_enabled": True,
            "grants": [{
                "group": "g-users-demo",
                "server_id": 1,
                "access_level": "all_tools",
                "tool_names": [],
            }],
        }
        self.loom.allowlist_payload = {
            "entries": [{
                "server_id": 1,
                "server_slug": "echo",
                "tools": [{
                    "name": "ping",
                    "description": "ping",
                    "inputSchema": {"type": "object", "properties": {}},
                }],
            }],
        }
        self.loom.agents_payload = {
            "agents": [{
                "exposed_name": "agent__demo",
                "agent_id": 9,
                "description": "Demo agent",
                "name": "Demo",
                "inputSchema": {"type": "object", "properties": {"prompt": {"type": "string"}}},
            }],
            "monitor_tools": [{
                "name": "agent_run_status",
                "description": "status",
                "inputSchema": {"type": "object", "properties": {}},
            }],
        }

    def test_list_tools_merges_mcp_and_agents(self) -> None:
        from mcp_hub.application.use_cases.tools import list_tools

        tools = list_tools(self.identity, store=self.store, loom=self.loom)
        names = {t["name"] for t in tools}
        self.assertIn("ping", names)
        self.assertIn("agent__demo", names)
        self.assertIn("agent_run_status", names)

    def test_call_tool_mcp(self) -> None:
        from mcp_hub.application.use_cases.tools import call_tool

        out = call_tool(
            self.identity,
            name="ping",
            arguments={},
            store=self.store,
            loom=self.loom,
        )
        self.assertEqual(out.get("result"), {"ok": True})

    def test_call_tool_agents_disabled(self) -> None:
        from mcp_hub.application.use_cases.tools import call_tool

        self.store.clients["cursor"]["agents_enabled"] = False
        out = call_tool(
            self.identity,
            name="agent__demo",
            arguments={"prompt": "hi"},
            store=self.store,
            loom=self.loom,
        )
        self.assertEqual(out["error"]["message"], "agents_disabled")

    def test_call_agent_accepted(self) -> None:
        from mcp_hub.application.use_cases.tools import call_tool

        out = call_tool(
            self.identity,
            name="agent__demo",
            arguments={"prompt": "hi"},
            store=self.store,
            loom=self.loom,
        )
        self.assertIn("result", out)
        self.assertIn("accepted", out["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
