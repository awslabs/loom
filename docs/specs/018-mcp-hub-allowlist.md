# Spec 018 — Allowlist do MCP Hub

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — filtro por perfil IdP ([ADR 0010](../adr/0010-mcp-hub-profile-grants.md))
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md), [ADR 0008](../adr/0008-mcp-hub-clients.md), [ADR 0010](../adr/0010-mcp-hub-profile-grants.md)
- **Depende de:** [016](016-mcp-hub-contract.md), [017](017-mcp-hub-session.md), [021](021-mcp-hub-clients.md), [022](022-mcp-hub-client-identification.md), [023](023-mcp-hub-profile-grants.md)

## 1. Objetivo

Allowlist = tools liberadas pelo admin para o **par (MCP Client × perfil
IdP)** da conexão Hub — não união de agents de Chat e não o mesmo
toolset para todos os users do canal.

## 2. Algoritmo

### 2a. Interino

União `McpServerAccess` de agents invocáveis (legado).

### 2b. Default (0008 + 0010)

```text
1. Sessão user ativa (introspect) → groups
2. Resolver mcp_client_slug ligado à sessão (pós-initialize / 022)
   — se ainda não houve initialize → entries []
3. Carregar MCP Client na extensão
4. Se status ≠ enabled → entries []
5. Filtrar grants onde grant.group casa o perfil do user (023)
6. grants filtrados → entries (+ schemas do catálogo Loom via BFF)
7. Naming → 016
```

Deny-by-default: discovered/pending, disabled, sem grant para o perfil,
ou sem discovery → `tools/list` = `[]`. Call fora → 403.

Cálculo do **filtro de perfil na extensão/Hub**. BFF Loom materializa
apenas o subset já filtrado.

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

- [ ] Client só discovered → list `[]`
- [ ] Enable + grant do perfil do user → list reflete tools
- [ ] Outro perfil no mesmo canal → toolset distinto (ou `[]`)
- [ ] Outro client (outro `clientInfo`) → outro bucket de grants
- [ ] Agents Chat não vazam para Hub
- [ ] Call negada não atinge upstream
