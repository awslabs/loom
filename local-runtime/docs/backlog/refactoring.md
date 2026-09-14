# Backlog de refatoração

Oportunidades de melhoria **sem** atuação automática. Política:
[guide/rules.md](../guide/rules.md) (§ Não refatorar sem pedido do Dev).

Fluxo:

1. Agente/Dev identifica oportunidade
2. Acrescenta item abaixo (`status: open`)
3. Avisa o Dev no chat
4. Só executa quando o Dev pedir **explicitamente** aquele id (ou escopo)

## Template

```markdown
### REF-YYYY-MM-DD-NN — título curto

| Campo | Valor |
|-------|--------|
| **Data** | YYYY-MM-DD |
| **Área** | ex.: `local-runtime/services/mcp-hub` |
| **Paths** | arquivos principais |
| **Oportunidade** | o que melhorar |
| **Motivo** | por que importa (manutenção, risco, clareza) |
| **Complexidade** | baixa \| média \| alta |
| **Risco** | baixo \| médio \| alto |
| **Status** | open \| done \| dismissed |
| **Notas** | opcional |
```

## Itens abertos

_(nenhum — iniciativa guideline refactor Fases 1–6 concluída na branch `refactor/mcp-hub-hexagonal`)_

## Itens encerrados

### REF-2026-09-14-07 — higiene transversal (Fase 6)

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/*` |
| **Status** | done |
| **Notas** | TypedDict/records nos ports; `tests/{unit,adapters}`; Makefile `local.*.test` + `local.mcp-hub.test`; revisão secrets/logging OK. |

### REF-2026-09-14-06 — plugin: fatiar LocalRuntimePage

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/plugin` |
| **Status** | done |
| **Notas** | Shell em `pages/LocalRuntimePage.tsx`; pieces em `plugin/src/local-runtime/` (api, grants, HubInfo, ClientsList, ChannelAgentsToggle, ProfileGrantsEditor). Contratos BFF/Hub inalterados. |

### REF-2026-09-14-01 — Hub store: JSON file → Postgres (paridade produção)

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/mcp-hub` |
| **Status** | done |
| **Notas** | `PostgresHubStore` + DB `mcp_hub`; JSON fallback; migrate when PG empty. |

### REF-2026-09-14-02 — mcp-hub: layout hexagonal (ports/adapters)

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/mcp-hub` |
| **Status** | done |
| **Notas** | Ver branch `refactor/mcp-hub-hexagonal`. |

### REF-2026-09-14-03 — agent-runtime: layout hexagonal

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/agent-runtime` |
| **Status** | done |
| **Notas** | Ports `LlmGateway` / `McpToolsClient` / `SessionStore`; use case `invoke`. |

### REF-2026-09-14-04 — mcp-runtime: hexagonal leve

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/mcp-runtime` |
| **Status** | done |
| **Notas** | Port `ProcessSupervisor`; YAML/stdio/secrets outbound; HTTP inbound DI. |

### REF-2026-09-14-05 — cursor-adapter: hexagonal

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/cursor-adapter` |
| **Status** | done |
| **Notas** | domain translation/planner; ports CursorAgentRunner/SessionStore; use case chat. |
