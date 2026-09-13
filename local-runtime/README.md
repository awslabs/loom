# local-runtime — Loom extension (ADR 0006)

Out-of-tree data plane + UI plugin for local MCP and (later) agent runtime.

```text
local-runtime/
├── plugin/                 # @loom-ext/local-runtime — UI only (Loom bundle)
├── services/
│   ├── mcp-runtime/        # stdio MCP facade
│   ├── cursor-adapter/     # LiteLLM CustomLLM
│   └── agent-runtime/      # deferred (ADR 0005)
├── templates/              # MCP allowlist YAML
└── compose/overlay.yml     # merged by `make local.up`
```

## Run with Loom

From the Loom repository root:

```bash
make local.up
```

Uses `docker-compose.yml` + `local-runtime/compose/overlay.yml`.

## UI plugin

The Loom frontend Extension Host loads `@loom-ext/local-runtime` (Vite alias /
Docker mount). Sidebar: **Local runtime** (requires `mcp:read`).

## Docs

- [ADR 0006](../docs/adr/0006-local-runtime-extension-repo.md) (in Loom tree while co-located)
- Agent runtime: see `services/agent-runtime/README.md`
