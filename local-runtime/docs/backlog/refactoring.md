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

### REF-2026-09-14-01 — Hub store: JSON file → Postgres (paridade produção)

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/mcp-hub` |
| **Paths** | `mcp_hub/store.py`, compose volume, `architecture.md` § Hub store |
| **Oportunidade** | Substituir `hub_clients.json` (single-writer file) por Postgres (ou schema no PG Loom via interface), com path/DSN só via env |
| **Motivo** | Comportamento próximo de produção: HA, backup, sem estado em arquivo local; alinha a [scalability-reliability.md](../guide/scalability-reliability.md) |
| **Complexidade** | média |
| **Risco** | médio (migração de clients/grants existentes; downtime Hub) |
| **Status** | open |
| **Notas** | Hoje `MCP_HUB_STORE_PATH` aponta ao JSON. Não executar até o Dev pedir este id. Diagramas C4 já usam “Hub store” genérico. Plano: [local-runtime-guideline-refactor-plan.md](local-runtime-guideline-refactor-plan.md) Fase 2. |

### REF-2026-09-14-02 — mcp-hub: layout hexagonal (ports/adapters)

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/mcp-hub` |
| **Paths** | `mcp_hub/http_app.py`, `store.py`, `loom_client.py`, `oauth.py`, `access.py`, `naming.py`, `identity.py` |
| **Oportunidade** | Migrar pacote plano → `domain/` + `application/` + `adapters/{inbound,outbound}/` conforme [python-best-practices.md](../guide/python-best-practices.md) §6 |
| **Motivo** | Isolar regras (grants, naming, agents tools) de HTTP/JSON/JWKS; testabilidade; norte do guideline |
| **Complexidade** | alta |
| **Risco** | médio (regressão MCP OAuth / tools/list|call) |
| **Status** | in_progress — layout + use cases + DI; falta fechar REF e Postgres (`REF-01`) |
| **Notas** | Strangler; wire protocol estável. Plano Fase 1 itens 1–8 feitos. |

### REF-2026-09-14-03 — agent-runtime: layout hexagonal

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/agent-runtime` |
| **Paths** | `agent_runtime/loop.py`, `http_app.py` |
| **Oportunidade** | Separar domínio de sessão/contrato vs I/O LiteLLM/MCP; ports `LlmGateway`, `McpToolsClient` |
| **Motivo** | `loop.py` concentra orquestração + HTTP; alinha guideline e facilita testes |
| **Complexidade** | alta |
| **Risco** | médio (invoke local / contract version) |
| **Status** | open |
| **Notas** | Após ou em paralelo controlado à Fase 1. Plano Fase 3. |

### REF-2026-09-14-04 — mcp-runtime: hexagonal leve

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/mcp-runtime` |
| **Paths** | `supervisor.py`, `http_app.py`, `templates.py`, `stdio.py` |
| **Oportunidade** | Extrair regras de template/allowlist; inbound HTTP fino; outbound process spawn |
| **Motivo** | Consistência entre sidecars; já relativamente isolado |
| **Complexidade** | média |
| **Risco** | médio (stdio children) |
| **Status** | open |
| **Notas** | Plano Fase 4. |

### REF-2026-09-14-05 — cursor-adapter: hexagonal

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/services/cursor-adapter` |
| **Paths** | `translation.py`, `planner.py`, `sdk_runner.py`, `http_app.py`, `sessions.py` |
| **Oportunidade** | Isolar translation pura; ports para SDK Cursor e sessão |
| **Motivo** | Bordas SDK/HTTP misturadas; teste unitário de translation |
| **Complexidade** | média |
| **Risco** | médio (`cursor-local` path) |
| **Status** | open |
| **Notas** | Plano Fase 4. |

### REF-2026-09-14-06 — plugin: fatiar LocalRuntimePage

| Campo | Valor |
|-------|--------|
| **Data** | 2026-09-14 |
| **Área** | `local-runtime/plugin` |
| **Paths** | `plugin/src/pages/LocalRuntimePage.tsx` |
| **Oportunidade** | Componentes por responsabilidade (clients list, grants, agents_enabled) + client API fino |
| **Motivo** | Página monolítica; manutenção e testes de UI |
| **Complexidade** | média |
| **Risco** | baixo |
| **Status** | open |
| **Notas** | Preferir após contratos Hub estáveis (Fase 1–2). Plano Fase 5. |

## Itens encerrados

_(nenhum ainda)_
