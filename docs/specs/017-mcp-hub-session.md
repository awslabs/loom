# Spec 017 — Hub session (mint / introspect)

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — bind de canal ([ADR 0008](../adr/0008-hub-channel-personas.md))
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md), [ADR 0008](../adr/0008-hub-channel-personas.md)
- **Depende de:** [ADR 0001](../adr/0001-keycloak-as-identity-provider.md), [016 — contrato](016-mcp-hub-contract.md), [018 — allowlist](018-mcp-hub-allowlist.md), [021 — channel personas](021-mcp-hub-channel-personas.md), [019 — segurança](019-mcp-hub-security.md)

## 1. Objetivo

Separar **login IdP** (Loom) da **credencial MCP** (Hub). O data plane
só aceita Hub session opaca; nunca JWT do IdP.

Cada sessão Hub está **bound a um canal** (`hub-channel` persona): a
allowlist (018) usa só as tools desse canal, não a união de agents de Chat.

## 2. Endpoints BFF (Loom FastAPI)

```text
POST /api/mcp/hub/sessions
Authorization: Bearer <JWT usuário IdP>
Scopes: mcp:read
Content-Type: application/json

{
  "channel_slug": "cursor-ide",   # obrigatório (ADR 0008)
  "client_label": "cursor"        # opcional; só audit
}

# Alternativa aceita: "persona_id": "<uuid-or-id>" em vez de channel_slug
# (deve resolver para a mesma persona hub-channel).

→ 201
{
  "hub_session_token": "hs_…",
  "hub_session_id": "uuid",
  "channel_slug": "cursor-ide",
  "persona_id": "<id>",
  "mcp_hub_url": "http://127.0.0.1:8790/mcp",
  "expires_at": "ISO-8601",
  "contract_version": "2026-09-hub-1"
}

→ 400  missing_channel | unknown_channel | channel_not_hub_kind
→ 403  channel_forbidden   # user sem acesso ao canal (021)
→ 401  sem JWT / JWT inválido

POST /api/mcp/hub/sessions/introspect
Authorization: Bearer <MCP_HUB_SERVICE_TOKEN>
Content-Type: application/json
{ "hub_session_token": "hs_…" }

→ 200
{
  "active": true,
  "hub_session_id": "uuid",
  "subject": "idp-sub",
  "idp_type": "keycloak",
  "scopes": ["mcp:read"],
  "channel_slug": "cursor-ide",
  "persona_id": "<id>",
  "expires_at": "ISO-8601"
}

→ 200 { "active": false }   # expirado / revogado / desconhecido

DELETE /api/mcp/hub/sessions/{hub_session_id}
Authorization: Bearer <JWT usuário>
→ 204  (revoga sessão da conta)
```

Introspect é **só** service-to-service (mcp-hub → Loom). Browser não chama
introspect com o Hub token de forma a vazar o service token.

### Compatibilidade interina

Até a implementação do ADR 0008: se o body omitir `channel_slug` /
`persona_id`, o mint **pode** ainda emitir sessão sem bind e a allowlist
cair no algoritmo união (018 §2a). Após 0008 implementado, omitir canal
→ **400** `missing_channel`.

## 3. Formato do token

- Opaco (`hs_` + secret URL-safe). **Não** JWT.
- Armazenamento: hash no Postgres (`mcp_hub_sessions`); valor em claro só
  na resposta do mint.
- Campos mínimos: `id`, `token_hash`, `subject`, `idp_type`, `created_at`,
  `expires_at`, `revoked_at`, `created_by_user_ref` (opcional),
  **`channel_slug`**, **`persona_id`** (bind obrigatório pós-0008),
  `client_label` (opcional, audit), `groups_json` / `scopes_json` (snapshot
  para reconstruir `UserInfo` no allowlist).

## 4. TTL e renovação

| Parâmetro | v1 |
|-----------|-----|
| TTL default | 8h (configurável via env `MCP_HUB_SESSION_TTL_S`) |
| Máximo | 24h |
| Refresh | novo mint (não há refresh token na v1) |
| Revogação | `DELETE` ou logout Loom (best-effort: listar sessões ativas do sub) |
| Troca de canal | novo mint (não há rebind in-place) |

## 5. Binding (v1)

| Campo | Obrigatório | Papel |
|-------|-------------|--------|
| `subject` + `idp_type` | sim | identidade IdP |
| `channel_slug` ou `persona_id` | sim (pós-0008) | allowlist (018 §2b) |
| `client_label` | não | audit apenas |
| IP | não | NAT/Docker quebra |

**Não** usar como auth: `initialize.clientInfo`, `X-Loom-Channel`, User-Agent
(apenas telemetria / UX na UI de mint).

**Futuro (fora desta spec):** OAuth `client_id` → mapa para `channel_slug`
no callback; mint implícito já bound.

Validação no mint:

1. Resolver slug → persona com `loom:kind=hub-channel` (021).
2. Persona ativa.
3. User tem acesso ao canal (021 § acesso).
4. Persistir bind na sessão.

## 6. Uso no mcp-hub

1. Extrai Bearer.
2. Chama introspect (cache em memória TTL ≤ 60s por token_hash; miss em
   401 limpa cache).
3. Se `active=false` → 401.
4. Passa `hub_session_id` (+ canal do introspect) ao resolvedor de
   allowlist (018). O Hub **não** escolhe canal sozinho.

## 7. UI (plugin Local Runtime)

- Seletor de canal no mint (lista de personas `hub-channel` que o user
  pode acessar).
- Resposta mostra `channel_slug` + URL + Bearer.
- README mcp-hub: um exemplo `mcp.json` por canal seed.

## 8. Critérios de aceite

- [ ] Mint sem JWT → 401
- [ ] Mint sem canal (pós-0008) → 400 `missing_channel`
- [ ] Mint com canal desconhecido / não `hub-channel` → 400
- [ ] Mint com canal sem acesso do user → 403 `channel_forbidden`
- [ ] Mint OK → token opaco + URL + `channel_slug` / `persona_id`
- [ ] Introspect ativo inclui `channel_slug` e `persona_id`
- [ ] Após `DELETE` / expiry → Hub recusa MCP
- [ ] mcp-hub com JWT IdP como Bearer → 401
- [ ] Token em claro não aparece em logs (019/020)
- [ ] Trocar de canal exige novo mint (sessão antiga mantém bind original)
