# Visão geral do fork

Este monorepo combina o [Loom público](https://github.com/awslabs/loom) com a
extensão **local-runtime** (plugin UI + sidecars + docs do fork).

| Camada | Onde | Papel |
|--------|------|--------|
| **Core Loom** | `backend/`, `frontend/` (host), `docker-compose.yml`, `makefile` | Plataforma, auth, catalog, BFF, Extension Host |
| **Extension** | `local-runtime/` | Features locais: MCP Hub, mcp-runtime, agent-runtime, cursor-adapter, UI Local runtime |
| **Docs do fork** | `local-runtime/docs/` | Regras, guias, changelog, ADRs novas — **não** em `docs/` na raiz |

## Mapa rápido

```text
.
├── backend/                 # FastAPI Loom (+ BFFs do fork quando inevitável)
├── frontend/                # SPA Loom + Extension Host
├── local-runtime/
│   ├── plugin/              # UI @loom-ext/local-runtime
│   ├── services/            # mcp-hub, mcp-runtime (+templates/), …
│   ├── compose/overlay.yml  # sidecars no `make local.up`
│   └── docs/                # ← regras, guias, ADRs, specs, changelog
├── etc/docker/              # Keycloak, LiteLLM, postgres-init (stack local)
└── makefile                 # orquestra compose raiz + overlay
```

## Por onde começar

1. [getting-started.md](guide/getting-started.md) — subir o stack
2. [rules.md](rules.md) — onde colocar código e docs
3. [development.md](guide/development.md) — makefile, padrões, plugin
4. [upstream-sync.md](guide/upstream-sync.md) — puxar awslabs/loom
5. [CHANGELOG-LOOM-FORK.md](CHANGELOG-LOOM-FORK.md) — o que já tocou o core

## URLs típicas (após `make local.up`)

| Serviço | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend OpenAPI | http://localhost:8000/docs |
| Keycloak | http://localhost:8081 |
| MCP Hub | http://127.0.0.1:8790 |
| LiteLLM | http://127.0.0.1:4000 |

Nav da extension: **Local runtime** (precisa `mcp:read`).
