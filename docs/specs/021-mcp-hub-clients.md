# Spec 021 — MCP Clients do Hub (extensão; discovery + grants)

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — grants por perfil IdP ([ADR 0010](../adr/0010-mcp-hub-profile-grants.md))
- **Implementa:** [ADR 0008](../adr/0008-mcp-hub-clients.md), [ADR 0010](../adr/0010-mcp-hub-profile-grants.md)
- **Depende de:** [ADR 0006](../adr/0006-local-runtime-extension-repo.md), [017](017-mcp-hub-session.md), [018](018-mcp-hub-allowlist.md), [022](022-mcp-hub-client-identification.md), [023](023-mcp-hub-profile-grants.md)

## 1. Objetivo

MCP Client = **canal** descoberto pelo Hub + grants de tools **por perfil
IdP** na extensão. Não é Agent. Nomes de produtos **não** precisam ser
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
| `allowed_groups` | derivado: união dos `group` nos grants (índice) |

Novo no `initialize`: se slug não existe → `status=discovered`, sem
grants. Se existe → atualiza `last_seen_at` + declared_* .

### 2.2 Tool grant (por perfil)

| Campo | Descrição |
|-------|-----------|
| `group` | perfil IdP canônico (`g-users-demo`, …) — **obrigatório** |
| `server_id` | catálogo Loom |
| `access_level` | `all_tools` \| `selected_tools` |
| `tool_names` | se selected |

Só aplicados se `status=enabled` **e** o perfil do user casa `group`
(ver [023](023-mcp-hub-profile-grants.md)).

### 2.3 Sessão → client (Hub)

| Campo | Descrição |
|-------|-----------|
| `hub_session_id` | |
| `mcp_client_slug` | setado no initialize |
| `bound_at` | |

Store na extensão (não exige coluna no Loom v1).

## 3. Ciclo de vida

```text
discovered ──(admin enable + grants por perfil)──► enabled
enabled ──(admin)──► disabled
disabled ──(admin)──► enabled
```

`discovered` / `disabled` → allowlist vazia.
`enabled` sem grant para o perfil do user → allowlist vazia.

Seeds opcionais (atalho): admin pode pré-criar slug+grants; o initialize
ainda faz UPSERT por `clientInfo`.

## 4. APIs (extensão / plugin)

```text
GET    .../mcp-clients                 # summary (granted_profiles, grant_count)
GET    .../mcp-clients/{slug}
PATCH  .../mcp-clients/{slug}          # status, display_name
GET    .../mcp-clients/{slug}/profile-grants?group=…  # on demand; vazio → 200 []
PUT    .../mcp-clients/{slug}/profile-grants   # { group, grants[] } — um perfil
DELETE .../mcp-clients/{slug}

# interno Hub
POST   .../mcp-clients/upsert-from-initialize
  { hub_session_id, clientInfo, user_agent? }
```

Auth UI: JWT user com escopo admin/`mcp:write`. Upsert interno: service
token Hub ou store embutido no mcp-hub.

## 5. Critérios de aceite

- [ ] Primeiro connect cria `discovered` sem tools
- [ ] Enable + grant do perfil → list/call ok para esse user
- [ ] GET profile-grants vazio → 200 [] e UI editável
- [ ] Outro perfil no mesmo canal → toolset distinto
- [ ] Sem Agent / sem Chat
- [ ] Dois `clientInfo.name` distintos → dois clients
- [ ] Código/UI em `local-runtime/` (+ proxy BFF `profile-grants`)
