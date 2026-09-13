# Local MCP runtime

Compose service that supervises allowlisted stdio MCP children and exposes an
internal streamable-HTTP facade. The Loom catalog stays the only MCP catalog.

```text
Backend FastAPI
  → POST http://mcp-runtime:8787/s/{id}/mcp   (Bearer MCP_RUNTIME_TOKEN)
    → this container
      → Popen(template command, shell=False)
        → child stdio JSON-RPC
```

Templates live in `local-runtime/templates/`. The client never sends `command` or `args`.

Host port is loopback-only (`127.0.0.1:8787`). Health: `GET /health` (no auth).

```text
make local.mcp-runtime.test
```
