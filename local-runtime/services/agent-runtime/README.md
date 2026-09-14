"""Local agent runtime (ADR 0005).

Separate process from Loom FastAPI. Implements the invoke contract in
`local-runtime/docs/specs/011-local-agent-runtime-contract.md`:

- `POST /v1/invoke` → SSE (`session_start` / `chunk` / `session_end` / `error`)
- LiteLLM for completions; MCP HTTP (incl. mcp-runtime facade) for tools
- `AGENT_RUNTIME_TOKEN` required for `/v1/*`

```text
make local.agent-runtime.test
```

## Package layout (hexagonal strangler)

```text
agent_runtime/
  domain/              # contract, errors (pure)
  application/         # ports, wiring, use_cases/invoke
  adapters/
    inbound/http_app   # HTTP + SSE
    outbound/          # litellm_http, mcp_http, memory_sessions
  loop.py / http_app.py  # compat shims
```

Contract version unchanged: `2026-09-local-1`.
"""
