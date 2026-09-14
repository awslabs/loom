# 11. Auth do MCP Hub via OAuth IdP (sem mint)

- **Status:** Aceito
- **Data:** 2026-09-14
- **Decisores:** Mantenedores da plataforma / extensão local
- **Relacionada a:**
  [ADR 0001 — IdP](0001-keycloak-as-identity-provider.md),
  [ADR 0007 — MCP Hub](0007-mcp-hub.md),
  [ADR 0008 — MCP Clients](0008-mcp-hub-clients.md),
  [ADR 0009 — Identificação](0009-mcp-hub-client-identification.md),
  [ADR 0010 — Grants por perfil](0010-mcp-hub-profile-grants.md)
- **Supersede (parcial):** mint / Hub session opaca `hs_…` como credencial
  do IDE em ADR 0007 §sessão, specs 017 (mint) e trechos de 016/019.

## Problema

A Fase 1 do Hub exige **mint manual** na UI Loom: o user copia
`hub_session_token` (`hs_…`) para o `mcp.json` do IDE. Isso:

1. coloca credencial em arquivo / clipboard (não no secret store do client);
2. acopla onboarding do IDE à UI Loom (“mint first”);
3. diverge do modelo MCP Authorization (OAuth 2.1 + PKCE + Protected
   Resource Metadata) que Cursor e outros clients já implementam;
4. mantém um segundo tipo de token (`hs_…`) paralelo ao IdP.

Queremos: o **MCP Client** autentica no **IdP ativo** do Loom e recebe o
token de forma segura; o Hub **não** oferece mint nem fallback `hs_…`.
O comportamento **não depende** de qual adapter está ativo
(Keycloak / Microsoft Entra ID / … — ADR 0001).

## Decisão

### Modelo

```text
Resource (MCP Hub)     = http://127.0.0.1:8790/mcp  (URL canônica do resource)
Authorization Server   = IdP ativo do Loom (Keycloak / Microsoft Entra ID / …)
MCP Client (Cursor, …) = OAuth public client + PKCE
```

1. IDE conecta ao Hub **só com a URL** (sem Bearer no `mcp.json`).
2. Hub responde `401` + `WWW-Authenticate` apontando Protected Resource
   Metadata (PRM).
3. Client descobre AS (issuer do IdP ativo), faz Authorization Code + PKCE +
   `resource=<canonical Hub URL>`.
4. User autentica/consent no browser do IdP.
5. Client guarda `access_token` (e refresh) no cofre do IDE.
6. Calls MCP: `Authorization: Bearer <access_token>`.
7. Hub valida JWT (issuer JWKS, `aud`/`resource` = Hub, exp) e lê
   `groups` → allowlist por perfil (ADR 0010). Discovery `clientInfo`
   (ADR 0009) permanece independente da prova de user.

### Removido (sem fallback)

| Removido | Notas |
|----------|--------|
| `POST /api/mcp/hub/sessions` (mint) | Não há caminho suportado |
| UI “Mint Hub session” | Plugin só documenta URL + OAuth |
| Bearer `hs_…` no IDE | Hub **recusa** token opaco de mint |
| Colar token no `mcp.json` | Só URL do resource |

Introspect/`mcp_hub_sessions` de mint **não** são API do IDE. Se o
código legado existir durante migração, deve falhar fechado para
clientes MCP (não documentar como fallback).

### IdP ativo como AS (Keycloak / Microsoft Entra ID)

Independente do provider registrado no Loom:

- Client OAuth dedicado ao Hub (ex. `loom-mcp-hub`) ou app registration
  equivalente no Entra; preferir client MCP separado do frontend.
- Scopes/claims mínimos: groups Loom + resource Hub (ex. `openid`,
  claim `groups` / groups Entra mapeados ao vocabulário `g-users-*`).
- PKCE `S256` obrigatório.
- Tokens com audiência/resource amarrados à URL canônica do Hub
  (RFC 8707). Tokens emitidos só para o frontend Loom **não** autenticam
  o Hub.

Local compose usa Keycloak como AS de desenvolvimento; produção pode
usar Microsoft Entra ID — Hub só consome `issuer` / JWKS / `groups`.

### Hub (resource server)

Publica:

- `GET /.well-known/oauth-protected-resource` (PRM) → `authorization_servers`,
  `resource`, scopes.
- Em request sem Bearer / Bearer inválido: `401` + `WWW-Authenticate`
  com `resource_metadata`.

Valida access token localmente (JWKS do IdP ativo) **ou** via endpoint de
introspecção do AS se o token for opaco — v1 preferir **JWT validável
por JWKS** para o Hub não depender do BFF a cada request de auth.

Service token `MCP_HUB_SERVICE_TOKEN` continua **só** Hub↔Loom
(materialize / tools/call), nunca no IDE.

### Fronteira Loom

| Extensão (Hub) | Loom / IdP ativo |
|----------------|------------------|
| PRM + 401 challenge | authorize/token/JWKS (Keycloak / Entra / …) |
| Validar JWT do resource | Client OAuth do Hub no IdP ativo |
| Grants / discovery | Intactos (0008–0010) |
| Sem mint UI | Remover endpoints mint do BFF |

## Alternativas consideradas

| # | Opção | Resultado |
|---|--------|-----------|
| 1 | Manter mint + OAuth como fallback | **Rejeitada** — dois caminhos de credencial; mint permanece atrito. |
| 2 | Loom como AS intermediário (code → token Loom) | Adiada; IdP direto é suficiente se `resource`/audience forem configuráveis. Reavaliar se DCR/CIMD ou resource indicators falharem no IdP. |
| 3 | JWT IdP do frontend (aud=loom-frontend) no Hub | **Rejeitada** — audience errada; replay entre superfícies. |
| 4 | Hub valida JWT via BFF a cada request | Possível; v1 prefere JWKS no Hub para latência/fail-closed local. |
| 5 | client_credentials (M2M) para IDE | **Rejeitada** para user tools; IDE é user-delegated. |
| 6 | Acoplar Hub só a Keycloak | **Rejeitada** — comportamento deve seguir o IdP ativo (Keycloak / Microsoft Entra ID). |

## Consequências

- Specs [024](../specs/024-mcp-hub-oauth.md) (OAuth/PRM), [017](../specs/017-mcp-hub-session.md)
  reescrita (validação de token; mint removido), [016](../specs/016-mcp-hub-contract.md) /
  [019](../specs/019-mcp-hub-security.md) atualizadas.
- ADR 0007/0008/0009: Bearer do IDE = access token OAuth do resource Hub.
- Config do IdP ativo: client + audience/resource do Hub; docs de `mcp.json`
  sem `headers.Authorization` fixo.
- Implementação **não** começa até 024 + 017 revistos serem aceitos.

## Specs

1. [024 — OAuth / PRM do Hub](../specs/024-mcp-hub-oauth.md)
2. [017 — Credencial do Hub (token validation)](../specs/017-mcp-hub-session.md)
3. [019 — Segurança](../specs/019-mcp-hub-security.md)
4. [016 — Contrato MCP](../specs/016-mcp-hub-contract.md)
