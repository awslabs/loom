import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime.http_app import RuntimeHandler
from agent_runtime.loop import CONTRACT_VERSION, validate_payload, AgentRuntimeError, _tool_name


class TestValidatePayload(unittest.TestCase):
    def test_requires_contract(self) -> None:
        with self.assertRaises(AgentRuntimeError) as ctx:
            validate_payload({"prompt": "hi", "model_id": "m"})
        self.assertEqual(ctx.exception.code, "unsupported_contract")

    def test_ok(self) -> None:
        payload = validate_payload({
            "contract_version": CONTRACT_VERSION,
            "prompt": "Olá",
            "model_id": "orientador-academico",
            "session_id": "s1",
            "invocation_id": "i1",
            "agent": {"id": 1, "name": "demo", "system_prompt": "sys"},
            "mcp_servers": [],
            "identity": {"subject": "u1", "agent_id": "1", "session_id": "s1"},
        })
        self.assertEqual(payload["model_id"], "orientador-academico")
        self.assertEqual(payload["agent"]["system_prompt"], "sys")

    def test_tool_name_sanitizes(self) -> None:
        self.assertEqual(_tool_name("Azure DevOps", "list-repos"), "Azure_DevOps__list-repos")


class TestRuntimeHttp(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AGENT_RUNTIME_TOKEN"] = "test-agent-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), RuntimeHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _json(self, method: str, path: str, body: dict | None = None, token: str | None = "test-agent-token") -> tuple[int, dict | str]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(self._url(path), data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8")
                ctype = resp.headers.get("Content-Type", "")
                if "text/event-stream" in ctype:
                    return resp.status, raw
                return resp.status, json.loads(raw)
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_health_public(self) -> None:
        status, payload = self._json("GET", "/health", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_v1_requires_token(self) -> None:
        status, payload = self._json("GET", "/v1/health", token=None)
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "runtime_auth")

    def test_v1_health_ok(self) -> None:
        status, payload = self._json("GET", "/v1/health")
        self.assertEqual(status, 200)
        self.assertIn(CONTRACT_VERSION, payload["contract_versions"])
