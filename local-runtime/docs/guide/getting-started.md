# Getting started

Comandos a partir da **raiz do monorepo** (onde está o `makefile`).

## Pré-requisitos

- Docker + Compose
- (Opcional) WSL no Windows se o host não tiver `docker` no PATH
- Cópia de `.env` a partir de `.env.example` quando necessário (`CURSOR_API_KEY`, etc.)

## Subir o stack

```bash
make local.up
```

Sobe `docker-compose.yml` **mais** `local-runtime/compose/overlay.yml` (sidecars
mcp-hub, mcp-runtime, agent-runtime, cursor-adapter, LiteLLM, …).

Primeira subida do Keycloak pode levar ~1 minuto (schema). Acompanhe:

```bash
make local.logs
# ou
make local.ps
```

## Parar / reset

```bash
make local.down          # mantém volumes
make local.reset         # apaga volumes (DB + realm frescos)
```

## Rebuild pontual

```bash
make local.build                 # imagem backend
make local.cursor-adapter        # só cursor-adapter
```

## Login local

1. Abra http://localhost:5173
2. IdP local: Keycloak em http://localhost:8081 (console admin: usuário `admin` — ver `.env` / realm)
3. Na UI Loom, use um usuário do realm `loom` com scopes MCP se for operar Hub (`mcp:read` / `mcp:write`)

## Cursor ↔ MCP Hub (resumo)

1. Local Runtime → canal `cursor-vscode` → **Enable** e, se quiser agents, **Expose Loom agents**
2. Grants por perfil IdP (servers MCP) — independente do toggle de agents
3. `.cursor/mcp.json` (exemplo):

```json
{
  "mcpServers": {
    "loom-hub": {
      "url": "http://127.0.0.1:8790/mcp",
      "auth": {
        "CLIENT_ID": "loom-mcp-hub",
        "scopes": ["openid", "profile"]
      }
    }
  }
}
```

4. Após ligar `agents_enabled`, **reinicie** o MCP no Cursor para refrescar `tools/list`

Detalhes de contrato: [ADR 0007–0012](../adr/README.md) e [changelog](../CHANGELOG-LOOM-FORK.md).

## Próximo

- [development.md](development.md) — desenvolver no fork
- [rules.md](rules.md) — o que pode tocar o core
