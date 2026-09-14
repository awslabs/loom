# Spec 017 — Credencial do MCP Hub (validação de token OAuth)

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-14 — mint removido; OAuth IdP ([ADR 0011](../adr/0011-mcp-hub-oauth-idp.md))
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md), [ADR 0011](../adr/0011-mcp-hub-oauth-idp.md)
- **Depende de:** [016](016-mcp-hub-contract.md), [024](024-mcp-hub-oauth.md),
  [018](018-mcp-hub-allowlist.md), [019](019-mcp-hub-security.md),
  [021](021-mcp-hub-clients.md), [022](022-mcp-hub-client-identification.md)

## 1. Objetivo

Definir como o Hub autentica o **usuário** em cada request MCP.
Credencial = **access token OAuth** emitido pelo Keycloak para o
**resource** Hub (024). O **MCP Client** continua sendo descoberto no
`initialize` (022), não na auth.

**Mint / `hs_…`:** removidos. Sem fallback.

## 2. Entrada

```text
Authorization: Bearer <access_token>
```

Somente header. Token deve ser JWT validável via JWKS do issuer Keycloak
(v1).

## 3. Validação (Hub)

Ordem fail-closed:

1. Bearer presente e não vazio.
2. Prefixo `hs_` → **rejeitar** (legado mint).
3. JWT: assinatura (JWKS), `iss` = issuer configurado, `exp` (clock skew
   pequeno), `aud` ou claim `resource` contém URL canônica do Hub
   (`http://127.0.0.1:8790/mcp` em local — 024).
4. Extrair `sub` (subject) e grupos Loom (`groups` / claim path alinhado
   ao IdP Loom).
5. Derivar identidade de sessão **em memória** no Hub para o wire MCP
   (bind a `initialize` / `hub_session_id` interno opcional) — **não** é
   token opaco mintido na UI.

Falha em qualquer passo → `401` (+ challenge 024 se aplicável).

### Config Hub

| Env | Uso |
|-----|-----|
| `MCP_HUB_RESOURCE` | URL canônica do resource (default local acima) |
| `MCP_HUB_OIDC_ISSUER` | Issuer Keycloak |
| `MCP_HUB_OIDC_AUDIENCE` | Audience esperada (se distinta do resource URL) |
| JWKS | Discovery do issuer (`/.well-known/openid-configuration`) |

## 4. Relação com Loom BFF

- **Materialize / tools/call:** Hub → Loom com `MCP_HUB_SERVICE_TOKEN` +
  identidade do user (`sub`, `groups`) derivada do access token
  validado (header interno ou body). Loom **não** re-emite `hs_…` para o IDE.
- Endpoints `POST /api/mcp/hub/sessions` (mint) e UI de mint: **removidos**
  / não suportados.

## 5. TTL / refresh

TTL = `exp` do access token IdP. Refresh = fluxo OAuth do MCP Client
(refresh_token), não “novo mint” na UI Loom.

## 6. Critérios de aceite

- [ ] Access token válido → initialize / tools/list conforme grants
- [ ] Token expirado / aud errada / `hs_…` → 401
- [ ] Groups do token alimentam filtro de perfil (023)
- [ ] Sem mint no BFF nem no plugin
- [ ] JWT do client frontend (aud distinto) → 401 no Hub
