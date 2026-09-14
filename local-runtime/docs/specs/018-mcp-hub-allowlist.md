# Spec 018 — Allowlist do MCP Hub

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-14 — união com tools de agents ([ADR 0012](../adr/0012-mcp-hub-agents-as-tools.md))
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md), [ADR 0008](../adr/0008-mcp-hub-clients.md), [ADR 0010](../adr/0010-mcp-hub-profile-grants.md),
  [ADR 0012](../adr/0012-mcp-hub-agents-as-tools.md)
- **Depende de:** [016](016-mcp-hub-contract.md), [017](017-mcp-hub-session.md), [021](021-mcp-hub-clients.md), [022](022-mcp-hub-client-identification.md), [023](023-mcp-hub-profile-grants.md), [025](025-mcp-hub-agents-as-tools.md)

## 1. Objetivo

Allowlist efetiva na conexão Hub = **união** de:

1. tools MCP liberadas pelo admin para o par (MCP Client × perfil IdP)
   — não união de agents de Chat;
2. tools `agent__*` se `agents_enabled` (filtradas por RBAC de tags —
   [025](025-mcp-hub-agents-as-tools.md)).

## 2. Algoritmo

### 2a. Interino

União `McpServerAccess` de agents invocáveis (legado).

### 2b. Default (0008 + 0010) — tools MCP

```text
1. JWT user ativo → groups
2. Resolver mcp_client_slug (pós-initialize / 022)
   — se ainda não houve initialize → entries MCP []
3. Carregar MCP Client na extensão
4. Se status ≠ enabled → entries MCP []
5. Filtrar grants onde grant.group casa o perfil do user (023)
6. grants filtrados → entries (+ schemas do catálogo Loom via BFF)
7. Naming → 016
```

### 2c. Agents (0012)

```text
8. Se status = enabled AND agents_enabled:
     materialize-agents(subject, groups) → entries agent__*
   senão → nenhuma entry agent
9. Allowlist = entries MCP ∪ entries agent
```

Deny-by-default MCP: discovered/pending, disabled, sem grant para o perfil,
ou sem discovery → subset MCP `[]`. Call MCP fora → 403.

Deny-by-default agents: `agents_enabled=false` ou RBAC negar → sem
`agent__*`; call → 403.

Filtro de **perfil de grants MCP** na extensão/Hub. Filtro **RBAC de
agent** no BFF (revalidado no invoke).

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

Reavaliar em list/call; revogar grant do perfil → próximo call nega;
discovery não congela grants.

## 5. Critérios de aceite

- [ ] Client só discovered → list MCP `[]`
- [ ] Enable + grant do perfil do user → list reflete tools MCP
- [ ] Outro perfil no mesmo canal → toolset MCP distinto (ou `[]`)
- [ ] Outro client (outro `clientInfo`) → outro bucket de grants
- [ ] `agents_enabled=false` → sem `agent__*` mesmo com agents no RBAC
- [ ] `agents_enabled=true` → `agent__*` só com `loom:group` permitido ([025](025-mcp-hub-agents-as-tools.md))
- [ ] Call negada não atinge upstream
