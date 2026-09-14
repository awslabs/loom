# local-runtime — Loom extension (ADR 0006)

Out-of-tree data plane + UI plugin for local MCP, agent runtime, and MCP Hub.

```text
local-runtime/
├── plugin/                 # @loom-ext/local-runtime — UI only (Loom bundle)
├── services/               # mcp-hub, mcp-runtime, cursor-adapter, agent-runtime
├── templates/              # MCP allowlist YAML
├── compose/overlay.yml     # merged by `make local.up`
└── docs/                   # fork docs (rules, guides, changelog) — start here
```

## Documentation

**Start here:** [docs/README.md](docs/README.md)

- [Getting started](docs/guide/getting-started.md)
- [Rules (Core vs extension)](docs/guide/rules.md)
- [Development](docs/guide/development.md)
- [MCP Hub](docs/guide/mcp-hub.md)
- [Upstream sync](docs/guide/upstream-sync.md)
- [Fork changelog](docs/CHANGELOG-LOOM-FORK.md)

## Run with Loom

From the monorepo root:

```bash
make local.up
```

Uses `docker-compose.yml` + `local-runtime/compose/overlay.yml`.

## UI plugin

The Loom frontend Extension Host loads `@loom-ext/local-runtime`. Sidebar:
**Local runtime** (requires `mcp:read`).
