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
| **Notas** | Hoje `MCP_HUB_STORE_PATH` aponta ao JSON. Não executar até o Dev pedir este id. Diagramas C4 já usam “Hub store” genérico. |

## Itens encerrados

_(nenhum ainda)_
