"""Regression test: OAuth2 A2A tools must build and send the exchanged Bearer token, for m2m and obo.

``_build_a2a_tool`` used to call ``_OAuth2Auth(..., user_access_token=...)``, a parameter ``_OAuth2Auth`` does not have, so
building ANY oauth2 A2A tool raised TypeError.  ``_OAuth2Auth`` never takes the user's token: for obo the AgentCore Identity
exchange derives the user from the workload token (the runtime already did GetWorkloadAccessTokenForJWT), and
``get_resource_oauth2_token`` has no user-token parameter.  So the A2A call site must mirror ``mcp_client._build_transport_callable``
(delegation_mode, obo_grant_type, audience) and nothing else.  Drives the real ``create_a2a_clients`` against a loopback server.
"""

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from bedrock_agentcore.runtime.context import BedrockAgentCoreContext

from src.config import A2AAgentConfig, AuthConfig
from src.integrations import mcp_client
from src.integrations.a2a_client import create_a2a_clients

_WORKLOAD = "wat-" + "0" * 40
_USER = "user-access-token-SECRET"
_CARD = {
    "name": "echo", "description": "echo agent", "url": "http://localhost/", "version": "1",
    "capabilities": {"streaming": False}, "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"], "skills": [],
}


class _Handler(BaseHTTPRequestHandler):
    def _reply(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self.server.auth_seen.append(("GET", self.headers.get("Authorization")))
        self._reply(_CARD)

    def do_POST(self) -> None:
        self.server.auth_seen.append(("POST", self.headers.get("Authorization")))
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        text = body["params"]["message"]["parts"][0]["text"]
        self._reply({"jsonrpc": "2.0", "id": body["id"], "result": {
            "kind": "message", "messageId": "m", "role": "agent",
            "parts": [{"kind": "text", "text": f"echo:{text}"}],
        }})

    def log_message(self, *args) -> None:
        pass


class TestOAuth2A2ATool(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.auth_seen = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        mcp_client._TOKEN_CACHE.clear()
        self.addCleanup(mcp_client._TOKEN_CACHE.clear)
        BedrockAgentCoreContext.set_workload_access_token(_WORKLOAD)

    def _run(self, auth: AuthConfig, token: str, env: dict | None = None) -> dict:
        fake_identity = MagicMock()
        exchange = fake_identity.return_value.dp_client.get_resource_oauth2_token
        exchange.return_value = {"accessToken": token, "expiresIn": 3600}
        config = A2AAgentConfig(
            name="echo", enabled=True, endpoint_url=f"http://127.0.0.1:{self.server.server_port}", auth=auth,
        )
        with patch.dict(os.environ, env or {}), patch.object(mcp_client, "IdentityClient", fake_identity):
            tool = create_a2a_clients([config])[0]  # TypeError here before the fix
            self.assertIn("echo:hi", tool(message="hi"))
        self.assertEqual(exchange.call_count, 1)
        self.assertTrue(self.server.auth_seen)
        self.assertEqual({a for _, a in self.server.auth_seen}, {f"Bearer {token}"})  # card fetch and message send
        return exchange.call_args.kwargs

    def test_m2m(self) -> None:
        kw = self._run(AuthConfig(type="oauth2", credential_provider_name="p", scopes="a b", delegation_mode="m2m"), "tok-m2m")
        self.assertEqual(kw, {
            "workloadIdentityToken": _WORKLOAD, "resourceCredentialProviderName": "p",
            "scopes": ["a", "b"], "oauth2Flow": "M2M",
        })

    def test_obo_token_exchange(self) -> None:
        kw = self._run(
            AuthConfig(type="oauth2", credential_provider_name="p", scopes="a", delegation_mode="obo",
                       obo_grant_type="TOKEN_EXCHANGE", audience="api://down"),
            "tok-obo", env={"USER_ACCESS_TOKEN": _USER},
        )
        # Same exchange as for an MCP server: the user is carried by the workload token; the API has no user-token parameter.
        self.assertEqual(kw["oauth2Flow"], "ON_BEHALF_OF_TOKEN_EXCHANGE")
        self.assertEqual(kw["workloadIdentityToken"], _WORKLOAD)
        self.assertEqual(kw["audiences"], ["api://down"])
        self.assertEqual(kw["customParameters"], {"subject_token_type": "urn:ietf:params:oauth:token-type:access_token"})
        self.assertNotIn(_USER, json.dumps(kw))

    def test_obo_jwt_authorization_grant(self) -> None:
        kw = self._run(
            AuthConfig(type="oauth2", credential_provider_name="p", scopes="a", delegation_mode="obo",
                       obo_grant_type="JWT_AUTHORIZATION_GRANT"),
            "tok-obo2",
        )
        self.assertEqual(kw["oauth2Flow"], "ON_BEHALF_OF_TOKEN_EXCHANGE")
        self.assertEqual(kw["customParameters"], {"requested_token_use": "on_behalf_of"})


if __name__ == "__main__":
    unittest.main()
