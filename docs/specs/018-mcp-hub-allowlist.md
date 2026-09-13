# Spec 018 — Allowlist do MCP Hub

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — grants do MCP Client descoberto ([ADR 0008](../adr/0008-mcp-hub-clients.md))
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md), [ADR 0008](../adr/0008-mcp-hub-clients.md)
- **Depende de:** [016](016-mcp-hub-contract.md), [017](017-mcp-hub-session.md), [021](021-mcp-hub-clients.md), [022](022-mcp-hub-client-identification.md)

## 1. Objetivo

Allowlist = tools liberadas pelo admin para o **MCP Client** associado à
conexão Hub (descoberto via `clientInfo`), não união de agents de Chat.

## 2. Algoritmo

### 2a. Interino

União `McpServerAccess` de agents invocáveis (código atual).

### 2b. Default (0008)

```text
1. Sessão user ativa (introspect)
2. Resolver mcp_client_slug ligado à sessão (pós-initialize / 022)
   — se ainda não houve initialize → entries [] 
3. Carregar MCP Client na extensão
4. Se status ≠ enabled → entries []
5. grants do client → entries (+ schemas do catálogo Loom)
6. Naming → 016
```

Deny-by-default: discovered/pending, disabled, sem grants, ou sem
discovery → `tools/list` = `[]`. Call fora → 403.

Cálculo na **extensão/Hub**. BFF Loom `tools/call` revalida grant
(consulta extensão) antes de executar.

## 3. Contrato interno

```text
{
  "hub_session_id": "…",
  "mcp_client_slug": "cursor-vscode",   # ou null se pré-initialize
  "client_status": "enabled|discovered|disabled",
  "entries": [ { "server_id", "server_slug", "endpoint_url", "transport", "tools": [...] } ],
  "generated_at": "ISO-8601"
}
```

## 4. Frescor

Reavaliar em list/call; revogar grant → próximo call nega; discovery não
congela grants.

## 5. Critérios de aceite

- [ ] Client só discovered → list `[]`
- [ ] Enable + grant → list reflete tools
- [ ] Outro client (outro `clientInfo`) → outro bucket de grants
- [ ] Agents Chat não vazam para Hub
- [ ] Call negada não atinge upstream
