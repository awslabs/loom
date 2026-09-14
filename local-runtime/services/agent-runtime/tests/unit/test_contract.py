"""Domain contract unit tests."""
from __future__ import annotations

import unittest

from agent_runtime.domain.contract import CONTRACT_VERSION, tool_name


class TestContract(unittest.TestCase):
    def test_contract_version_stable(self) -> None:
        self.assertEqual(CONTRACT_VERSION, "2026-09-local-1")

    def test_tool_name(self) -> None:
        self.assertEqual(tool_name("grafana", "ping"), "grafana__ping")


if __name__ == "__main__":
    unittest.main()
