"""Local agent runtime (ADR 0005).

Separate process from Loom FastAPI. Implements the invoke contract in
`docs/specs/011-local-agent-runtime-contract.md`:

- `POST /v1/invoke` → SSE (`session_start` / `chunk` / `session_end` / `error`)
- LiteLLM for completions; MCP HTTP (incl. mcp-runtime facade) for tools
- `AGENT_RUNTIME_TOKEN` required for `/v1/*`

```text
make local.agent-runtime.test
```
"""
