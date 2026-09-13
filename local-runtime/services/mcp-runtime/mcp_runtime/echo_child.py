"""Minimal MCP stdio server used by the test-echo template and unit tests."""
from __future__ import annotations

import json
import sys


def _reply(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = message.get("method")
        req_id = message.get("id")
        if req_id is None:
            continue
        if method == "initialize":
            _reply({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "test-echo", "version": "1.0.0"},
                },
            })
        elif method == "tools/list":
            _reply({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [{
                        "name": "echo",
                        "description": "Echo the text argument",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                    }],
                },
            })
        elif method == "tools/call":
            params = message.get("params") or {}
            text = (params.get("arguments") or {}).get("text", "")
            _reply({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": str(text)}]},
            })
        else:
            _reply({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "method not found"},
            })


if __name__ == "__main__":
    main()
