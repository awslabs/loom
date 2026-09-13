# Spec 021 — MCP Clients do Hub (extensão; discovery + grants)

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — registro no connect; admin enable/grants
- **Implementa:** [ADR 0008](../adr/0008-mcp-hub-clients.md)
- **Depende de:** [ADR 0006](../adr/0006-local-runtime-extension-repo.md), [017](017-mcp-hub-session.md), [018](018-mcp-hub-allowlist.md), [022](022-mcp-hub-client-identification.md)

## 1. Objetivo

MCP Client = superfície descoberta pelo Hub + grants de tools na
extensão. Não é Agent. Nomes de produtos **não** precisam ser
conhecidos a priori.

## 2. Modelo (extensão)

### 2.1 MCP Client

| Campo | Descrição |
|-------|-----------|
| `slug` | único; derivado de `clientInfo.name` (022) |
| `display_name` | UI (name raw ou alias conhecido) |
| `declared_name` / `declared_version` | último `clientInfo` visto |
| `declared_family` | cursor \| claude-code \| … \| unknown |
| `status` | `discovered` \| `enabled` \| `disabled` |
| `first_seen_at` / `last_seen_at` | |
| `allowed_groups` | opcional; restringe quais users usam grants deste client |

Novo no `initialize`: se slug não existe → `status=discovered`, sem
grants. Se existe → atualiza `last_seen_at` + declared_* .

### 2.2 Tool grant

| Campo | Descrição |
|-------|-----------|
| `mcp_client_slug` | |
| `server_id` | catálogo Loom |
| `access_level` | `all_tools` \| `selected_tools` |
| `tool_names` | se selected |

Só aplicados se `status=enabled`.

### 2.3 Sessão → client (Hub)

| Campo | Descrição |
|-------|-----------|
| `hub_session_id` | |
| `mcp_client_slug` | setado no initialize |
| `bound_at` | |

Store na extensão (não exige coluna no Loom v1).

## 3. Ciclo de vida

```text
discovered ──(admin enable + opcional grants)──► enabled
enabled ──(admin)──► disabled
disabled ──(admin)──► enabled
```

`discovered` / `disabled` → allowlist vazia.

Seeds opcionais (atalho): admin pode pré-criar slug+grants; o initialize
ainda faz UPSERT por `clientInfo` (pode criar **outro** slug se o name
real diferir do seed — UI pode “merge” depois; fora do v1 mínimo).

## 4. APIs (extensão / plugin)

```text
GET    .../mcp-clients                 # lista (filtro status)
GET    .../mcp-clients/{slug}
PATCH  .../mcp-clients/{slug}          # status, display_name, allowed_groups
PUT    .../mcp-clients/{slug}/grants
DELETE .../mcp-clients/{slug}          # admin; cuidado com sessões ativas

# interno Hub
POST   .../mcp-clients/upsert-from-initialize
  { hub_session_id, clientInfo, user_agent? }
```

Auth UI: JWT user com escopo admin/`mcp:write`. Upsert interno: service
token Hub ou processo local do mcp-hub com store embutido.

## 5. Critérios de aceite

- [ ] Primeiro connect cria `discovered` sem tools
- [ ] Enable + grants → list/call ok
- [ ] Sem Agent / sem Chat
- [ ] Dois `clientInfo.name` distintos → dois clients
- [ ] Código/UI em `local-runtime/`
