"""Regression test: consecutive calls to an OAuth2 A2A tool must all succeed.

Strands runs every ``A2AAgent.__call__`` through ``run_async`` (a new ``asyncio.run`` loop per call).  An httpx client that
outlives one call keeps a pooled keep-alive socket bound to that closed loop, so the next call fails with
``RuntimeError: Event loop is closed`` (every second call).  This drives the real tool through the real ``run_async`` against
a keep-alive HTTP/1.1 server on loopback.
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from bedrock_agentcore.runtime.context import BedrockAgentCoreContext

from src.config import A2AAgentConfig, AuthConfig
from src.integrations import mcp_client
from src.integrations.a2a_client import create_a2a_clients

_TOKEN = "test-bearer-token"
_CARD = {
    "name": "echo",
    "description": "echo agent",
    "url": "http://localhost/",
    "version": "1",
    "capabilities": {"streaming": False},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [],
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, so connections are pooled by the client

    def _reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self._reply(200, _CARD)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != f"Bearer {_TOKEN}":
            self.server.unauthorized += 1
        text = body["params"]["message"]["parts"][0]["text"]
        self._reply(200, {"jsonrpc": "2.0", "id": body["id"], "result": {
            "kind": "message", "messageId": "m", "role": "agent",
            "parts": [{"kind": "text", "text": f"echo:{text}"}],
        }})

    def log_message(self, *args) -> None:
        pass


class TestA2AToolEventLoop(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.unauthorized = 0
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        mcp_client._TOKEN_CACHE.clear()
        self.addCleanup(mcp_client._TOKEN_CACHE.clear)

    def test_consecutive_oauth2_calls_all_succeed(self) -> None:
        fake_identity = MagicMock()
        fake_identity.return_value.dp_client.get_resource_oauth2_token.return_value = {
            "accessToken": _TOKEN, "expiresIn": 3600,
        }
        BedrockAgentCoreContext.set_workload_access_token("wat-" + "0" * 40)
        config = A2AAgentConfig(
            name="echo", enabled=True, endpoint_url=f"http://127.0.0.1:{self.server.server_port}",
            auth=AuthConfig(type="oauth2", credential_provider_name="p", delegation_mode="m2m"),
        )
        with patch.object(mcp_client, "IdentityClient", fake_identity):
            tool = create_a2a_clients([config])[0]
            results = []
            for i in range(6):
                try:
                    results.append(tool(message=f"m{i}"))  # tool -> A2AAgent.__call__ -> strands run_async (new loop)
                except Exception as e:  # noqa: BLE001
                    results.append(f"{type(e).__name__}: {e}")

        # tool() returns the agent message as text; a failed call returns/raises "RuntimeError: Event loop is closed"
        self.assertEqual([r for i, r in enumerate(results) if f"echo:m{i}" not in r], [])
        self.assertEqual(self.server.unauthorized, 0)
        # token cache untouched: one identity exchange serves all calls
        self.assertEqual(fake_identity.return_value.dp_client.get_resource_oauth2_token.call_count, 1)


if __name__ == "__main__":
    unittest.main()
