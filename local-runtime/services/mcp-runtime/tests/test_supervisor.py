import os
import sys
import unittest
from pathlib import Path

# Ensure echo_child can be imported as mcp_runtime.echo_child
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_runtime.stdio import sanitize_stderr
from mcp_runtime.supervisor import REGISTERED, READY, SUPERVISOR, Supervisor
from mcp_runtime.templates import TemplateError


class TestSupervisor(unittest.TestCase):
    def setUp(self) -> None:
        root = str(Path(__file__).resolve().parents[1])
        current = os.environ.get("PYTHONPATH", "")
        os.environ["PYTHONPATH"] = root if not current else f"{root}{os.pathsep}{current}"
        self.supervisor = Supervisor()

    def tearDown(self) -> None:
        self.supervisor.stop_all()

    def test_register_echo_then_tools_call(self) -> None:
        handle = self.supervisor.register(1, "test-echo", {}, [])
        self.assertEqual(handle.state, REGISTERED)
        handle = self.supervisor.start(1)
        self.assertEqual(handle.state, READY)
        listed = self.supervisor.call(1, "tools/list")
        names = [tool["name"] for tool in listed["result"]["tools"]]
        self.assertIn("echo", names)
        called = self.supervisor.call(1, "tools/call", {"name": "echo", "arguments": {"text": "oi"}})
        self.assertEqual(called["result"]["content"][0]["text"], "oi")

    def test_unknown_template_rejected(self) -> None:
        with self.assertRaises(TemplateError):
            self.supervisor.register(2, "not-real", {}, [])


class TestStderrSanitize(unittest.TestCase):
    def test_redacts_token_lines(self) -> None:
        text = sanitize_stderr([
            "mcp-server-azuredevops: not found",
            "Authorization: Bearer super-secret",
        ])
        self.assertIn("mcp-server-azuredevops: not found", text)
        self.assertNotIn("super-secret", text)
        self.assertIn("[redacted]", text)


class TestGlobalSupervisorIsolation(unittest.TestCase):
    def test_module_supervisor_exists(self) -> None:
        self.assertIsNotNone(SUPERVISOR)
