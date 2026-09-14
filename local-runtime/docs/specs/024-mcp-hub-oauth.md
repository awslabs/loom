# Spec 024 — OAuth do MCP Hub (Protected Resource + IdP)

- **Status:** Rascunho
- **Data:** 2026-09-14
- **Atualizado:** 2026-09-14 — IdP ativo (Keycloak / Microsoft Entra ID)
- **Implementa:** [ADR 0011](../adr/0011-mcp-hub-oauth-idp.md)
- **Depende de:** [ADR 0001](../adr/0001-keycloak-as-identity-provider.md),
  [016](016-mcp-hub-contract.md), [017](017-mcp-hub-session.md),
  [019](019-mcp-hub-security.md)

## 1. Objetivo

Definir como o MCP Client obtém e apresenta credencial ao Hub **sem mint**:
OAuth 2.1 Authorization Code + PKCE contra o **IdP ativo** do Loom
(Keycloak / Microsoft Entra ID / …), resource = Hub. O fluxo é o mesmo
qualquer que seja o provider registrado.

## 2. Identificadores

| Nome | Valor v1 (local) |
|------|------------------|
| Resource (canônico) | `http://127.0.0.1:8790/mcp` |
| AS | Issuer do IdP ativo (ADR 0001); local compose = Keycloak realm Loom |
| OAuth client | Client dedicado no IdP (ex. `loom-mcp-hub`) — public + PKCE |

Mudança da URL canônica do resource exige novo `aud`/`resource` e
atualização do PRM.

## 3. Protected Resource Metadata (Hub)

```text
GET http://127.0.0.1:8790/.well-known/oauth-protected-resource
→ 200 application/json
{
  "resource": "http://127.0.0.1:8790/mcp",
  "authorization_servers": [ "<active-idp-issuer>" ],
  "scopes_supported": [ "openid", "profile" ],
  "bearer_methods_supported": [ "header" ]
}
```

(`authorization_servers` = `MCP_HUB_OIDC_ISSUER` do IdP ativo. Groups via
claim no access token, alinhada ao vocabulário Loom — independente de
Keycloak ou Entra.)

Opcional: documentar também sob path relativo ao resource se a spec MCP
do client exigir; v1 = host root do Hub `:8790`.

## 4. Challenge

Request a `/mcp` sem Bearer ou com token inválido:

```text
401 Unauthorized
WWW-Authenticate: Bearer realm="loom-mcp-hub",
  resource_metadata="http://127.0.0.1:8790/.well-known/oauth-protected-resource"
```

Não retornar corpo com secrets. Não aceitar token na query string.

## 5. Jornada do MCP Client

```text
1. POST /mcp (sem auth) → 401 + PRM URL
2. GET PRM → authorization_servers  (= IdP ativo)
3. GET AS metadata (RFC 8414 / OIDC discovery no issuer)
4. Authorization Code + PKCE S256
     + resource=http://127.0.0.1:8790/mcp
     + redirect_uri do IDE
5. Token endpoint → access_token (+ refresh_token)
6. IDE armazena token no secret store do client
7. POST /mcp Authorization: Bearer <access_token>
```

Registro do OAuth client: **pré-registrado** no IdP ativo (redirect URIs
conhecidos do Cursor/outros). DCR/CIMD = fora do v1 mínimo (pode ser
extensão depois). Em local, isso é o client Keycloak `loom-mcp-hub`; em
Entra, o app registration equivalente.

## 6. Validação no Hub (017)

Ver [017](017-mcp-hub-session.md): JWKS, issuer, exp, audience/resource,
extrair `sub` + `groups` → allowlist (018/023).

## 7. Critérios de aceite

- [ ] `mcp.json` só com URL (+ `auth.CLIENT_ID` estático); sem Bearer fixo
- [ ] Sem auth → 401 + `resource_metadata`
- [ ] PRM lista issuer do **IdP ativo** (Keycloak ou Entra)
- [ ] Token com aud/resource errado → 401
- [ ] Token válido + perfil com grants → tools/list ok
- [ ] Token `hs_…` (mint legado) → 401
- [ ] Nenhum endpoint de mint documentado ou usável pelo IDE
- [ ] Trocar IdP ativo (sem mudar contrato Hub) continua o mesmo fluxo
