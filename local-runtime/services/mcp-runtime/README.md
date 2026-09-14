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

## Package layout (hexagonal leve)

```text
mcp_runtime/
  domain/errors.py
  application/{ports,wiring}.py
  adapters/
    inbound/http_app.py
    outbound/{process_supervisor,yaml_templates,stdio_session,env_secrets}.py
  *.py                 # compat shims
  echo_child.py        # child process for test-echo
```
