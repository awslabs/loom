# MCP Hub (uso rápido)

Data plane: `local-runtime/services/mcp-hub` (porta **8790**).  
Control plane / BFF: rotas sob o backend Loom (`/api/mcp/hub/…`, extension
`/api/ext/local-runtime/mcp-clients/…`).

## Conceitos

| Conceito | Onde | Notas |
|----------|------|--------|
| Canal (MCP client) | Store do Hub | Ex.: `cursor-vscode`; status enabled/disabled |
| Grants por perfil IdP | UI Local runtime | Tools de **servers** MCP (Grafana, ADO, …) |
| `agents_enabled` | Canal (não perfil) | Expõe `agent__*` + `agent_run_status` / `agent_run_result` |
| OAuth | IdP ativo (Keycloak / Entra) | Sem mint; client estático `loom-mcp-hub` |

## Operar na UI

1. Nav **Local runtime** (`mcp:read`; escrita com `mcp:write`)
2. Selecione o canal → Channel settings → **Expose Loom agents** (grava na hora)
3. Escolha um **IdP profile** só para editar grants de servers → **Save profile grants**

## IDE (Cursor)

Ver [getting-started.md](getting-started.md#cursor--mcp-hub-resumo). Após mudar
`agents_enabled`, reinicie o MCP para o catálogo incluir `agent__*`.

## Agents locais (ex.: Orientador)

- Seed: agent `source=local` no backend
- Invoke via Hub usa BFF; mocks LiteLLM (`orientador-academico`, `mock-echo`)
  não devem depender do agent-runtime
- Fluxo async: `wait=accepted` → `agent_run_status` → `agent_run_result`

Contrato: [ADR 0012](../adr/0012-mcp-hub-agents-as-tools.md) /
[spec 025](../specs/025-mcp-hub-agents-as-tools.md).
