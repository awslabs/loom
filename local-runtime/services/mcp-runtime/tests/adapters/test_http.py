import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_runtime.adapters.inbound.http_app import RuntimeHandler
from mcp_runtime.adapters.outbound.process_supervisor import SUPERVISOR


class TestRuntimeHttp(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["MCP_RUNTIME_TOKEN"] = "test-runtime-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), RuntimeHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        try:
            SUPERVISOR.stop_all()
        except Exception:
            pass
        self.server.shutdown()
        self.server.server_close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _json(self, method: str, path: str, body: dict | None = None, token: str | None = "test-runtime-token") -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(self._url(path), data=data, headers=headers, method=method)
        try:
            with urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_health_is_public(self) -> None:
        status, payload = self._json("GET", "/health", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_register_requires_token(self) -> None:
        status, payload = self._json(
            "POST",
            "/runtime/servers/register",
            {"server_id": 1, "template_id": "test-echo", "params": {}},
            token=None,
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "runtime_auth")

    def test_register_start_and_echo(self) -> None:
        status, payload = self._json(
            "POST",
            "/runtime/servers/register",
            {"server_id": 9, "template_id": "test-echo", "params": {}, "secret_refs": []},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "REGISTERED")
        status, payload = self._json("POST", "/runtime/servers/9/start", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "READY")
        status, payload = self._json(
            "POST",
            "/s/9/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "echo", "arguments": {"text": "ping"}}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["content"][0]["text"], "ping")
