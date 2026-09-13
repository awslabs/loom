# Spec 017 — Hub session (mint / introspect)

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — mint = user only; client via discovery ([ADR 0008](../adr/0008-mcp-hub-clients.md))
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md), [ADR 0008](../adr/0008-mcp-hub-clients.md)
- **Depende de:** [016](016-mcp-hub-contract.md), [018](018-mcp-hub-allowlist.md), [021](021-mcp-hub-clients.md), [022](022-mcp-hub-client-identification.md), [019](019-mcp-hub-security.md)

## 1. Objetivo

Separar **login IdP** da **credencial MCP**. Sessão Hub autentica o
**usuário**. O **MCP Client** (Cursor, …) é descoberto no `initialize`
(022 / 0008), não escolhido no mint.

## 2. Endpoints BFF (Loom — gancho mínimo)

```text
POST /api/mcp/hub/sessions
Authorization: Bearer <JWT usuário IdP>
Scopes: mcp:read
Content-Type: application/json

{
  "client_label": "local-runtime-ui"   # opcional; audit da UI de mint
}

→ 201
{
  "hub_session_token": "hs_…",
  "hub_session_id": "uuid",
  "mcp_hub_url": "http://127.0.0.1:8790/mcp",
  "expires_at": "ISO-8601",
  "contract_version": "2026-09-hub-1"
}

POST /api/mcp/hub/sessions/introspect
Authorization: Bearer <MCP_HUB_SERVICE_TOKEN>
{ "hub_session_token": "hs_…" }

→ 200
{
  "active": true,
  "hub_session_id": "uuid",
  "subject": "idp-sub",
  "idp_type": "keycloak",
  "scopes": ["mcp:read"],
  "groups": ["g-users-demo"],
  "expires_at": "ISO-8601"
}

→ 200 { "active": false }

DELETE /api/mcp/hub/sessions/{hub_session_id}
Authorization: Bearer <JWT usuário>
→ 204
```

`mcp_client_slug` **não** é campo obrigatório do mint. Após discovery, o
Hub mantém a associação sessão→client no store da extensão (021/022).
Introspect Loom pode permanecer só user; o Hub já sabe o slug localmente.

### Interino

Implementação atual pode ainda aceitar `client_label` apenas. União de
agents na allowlist = interina até 0008.

## 3. Token

Opaco `hs_…`; hash em `mcp_hub_sessions`: `subject`, `idp_type`, TTL,
`groups_json` / `scopes_json`, `client_label?`. Sem bind de client no
Postgres Loom (v1).

## 4. TTL

Default 8h (`MCP_HUB_SESSION_TTL_S`), max 24h; refresh = novo mint.

## 5. UI mint

Plugin: “Mint Hub session” → URL + Bearer. Sem seletor de canal.
Texto: “Conecte o IDE; o Hub registra o client. Libere tools em MCP Clients.”

## 6. Critérios de aceite

- [ ] Mint com JWT → `hs_…` + URL (sem slug obrigatório)
- [ ] Introspect active/inactive
- [ ] JWT IdP no Hub → 401
- [ ] Client discovery não depende de campo no mint
