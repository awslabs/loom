# Spec 017 — Hub session (mint / introspect)

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md)
- **Depende de:** [ADR 0001](../adr/0001-keycloak-as-identity-provider.md), [016 — contrato](016-mcp-hub-contract.md), [019 — segurança](019-mcp-hub-security.md)

## 1. Objetivo

Separar **login IdP** (Loom) da **credencial MCP** (Hub). O data plane
só aceita Hub session opaca; nunca JWT do IdP.

## 2. Endpoints BFF (Loom FastAPI)

```text
POST /api/mcp/hub/sessions
Authorization: Bearer <JWT usuário IdP>
Scopes: mcp:read  (mint; detalhe: também exigir que o user exista/ativo)

→ 201
{
  "hub_session_token": "hs_…",
  "hub_session_id": "uuid",
  "mcp_hub_url": "http://127.0.0.1:8790/mcp",
  "expires_at": "ISO-8601",
  "contract_version": "2026-09-hub-1"
}

POST /api/mcp/hub/sessions/introspect
Authorization: Bearer <MCP_HUB_SERVICE_TOKEN>   # token de serviço do mcp-hub
Content-Type: application/json
{ "hub_session_token": "hs_…" }

→ 200
{
  "active": true,
  "hub_session_id": "uuid",
  "subject": "idp-sub",
  "idp_type": "keycloak",
  "scopes": ["mcp:read"],
  "expires_at": "ISO-8601"
}

→ 200 { "active": false }   # expirado / revogado / desconhecido

DELETE /api/mcp/hub/sessions/{hub_session_id}
Authorization: Bearer <JWT usuário>
→ 204  (revoga sessão da conta)
```

Introspect é **só** service-to-service (mcp-hub → Loom). Browser não chama
introspect com o Hub token de forma a vazar o service token.

## 3. Formato do token

- Opaco (`hs_` + secret URL-safe). **Não** JWT.
- Armazenamento: hash no Postgres (ou tabela `mcp_hub_sessions`); valor
  em claro só na resposta do mint.
- Campos mínimos: `id`, `token_hash`, `subject`, `idp_type`, `created_at`,
  `expires_at`, `revoked_at`, `created_by_user_ref` (opcional).

## 4. TTL e renovação

| Parâmetro | v1 |
|-----------|-----|
| TTL default | 8h (configurável via env `MCP_HUB_SESSION_TTL_S`) |
| Máximo | 24h |
| Refresh | novo mint (não há refresh token na v1) |
| Revogação | `DELETE` ou logout Loom (best-effort: listar sessões ativas do sub) |

## 5. Binding (v1)

- Obrigatório: `subject` + `idp_type` do JWT no mint.
- Opcional depois: `client_label` (ex. `cursor`) guardado só para audit.
- Sem binding a IP na v1 (NAT/Docker quebra).

## 6. Uso no mcp-hub

1. Extrai Bearer.
2. Chama introspect (cache em memória TTL ≤ 60s por token_hash; miss em
   401 limpa cache).
3. Se `active=false` → 401.
4. Passa `subject` / `hub_session_id` ao resolvedor de allowlist (018).

## 7. Critérios de aceite

- [ ] Mint sem JWT → 401
- [ ] Mint com JWT válido → token opaco + URL
- [ ] Introspect com service token + hub token ativo → `active: true`
- [ ] Após `DELETE` / expiry → Hub recusa MCP
- [ ] mcp-hub com JWT IdP como Bearer → 401
- [ ] Token em claro não aparece em logs (019/020)
