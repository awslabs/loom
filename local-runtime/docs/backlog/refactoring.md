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
