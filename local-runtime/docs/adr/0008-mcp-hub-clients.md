# 8. MCP Clients do Hub — discovery na conexão + grants na extensão

- **Status:** Proposta (substitui persona=Agent e seeds obrigatórios a priori)
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-14 — auth OAuth ([ADR 0011](0011-mcp-hub-oauth-idp.md)); mint removido
- **Decisores:** Mantenedores da plataforma / extensão local
- **Relacionada a:**
  [ADR 0006 — Extensão local-runtime](0006-local-runtime-extension-repo.md),
  [ADR 0007 — MCP Hub](0007-mcp-hub.md),
  [ADR 0009 — Identificação do MCP Client](0009-mcp-hub-client-identification.md),
  [ADR 0010 — Grants por perfil](0010-mcp-hub-profile-grants.md),
  [ADR 0011 — OAuth Hub](0011-mcp-hub-oauth-idp.md),
  [ADR 0001 — IdP](0001-keycloak-as-identity-provider.md)

## Problema

O MCP Hub precisa de allowlist **por superfície de cliente** (Cursor,
Claude Code, Cowork, …), distinta dos agents de Chat.

Não conhecemos de antemão os `clientInfo.name` estáveis de cada produto.
Pré-cadastrar seeds (`cursor-ide`, …) e obrigar o user a escolher o canal
no mint é frágil e mistura “adivinhar o produto” com auth.

Reusar `Agent` + `McpServerAccess` mistura Chat/IDE e toca o core demais.

Queremos:

1. conceito **MCP Client** na extensão (não Agent);
2. **descobrir** o client quando ele conecta ao Hub;
3. **admin libera tools** depois (deny-by-default até lá);
4. ganchos mínimos no Loom (IdP OAuth, BFF `tools/call`).

## Decisão

### Discovery + enablement

```text
1. User autentica via OAuth no MCP Client (ADR 0011) — sem mint
2. IDE conecta → initialize { clientInfo }
3. mcp-hub UPSERT MCP Client na extensão (slug derivado do name)
     status = discovered | pending   (sem grants)
4. Admin no plugin Local runtime: enable + grants **por perfil IdP**
5. tools/list|call: filtra grants do perfil do user (ADR 0010); senão []
```

```text
MCP Client (extensão)
  → criado/atualizado no initialize (ADR 0009)
  → grants: (perfil IdP, server_id, all|selected tools)   # ADR 0010
  → NÃO é Agent; UI só no plugin Local runtime
```

Não exigimos catálogo fixo de nomes de produtos. Aliases conhecidos
(opcional) só melhoram `display_name` / família; desconhecidos viram
slug normalizado de `clientInfo.name` (ou `unknown-<hash>` se vazio).

### Allowlist

```text
Hub session (user.groups) + canal (slug do discovery)
  → se client enabled → allowlist = grants cujo group casa o perfil
  → senão / sem grant para o perfil → tools/list = []
  → NÃO união de agents de Chat
```

Detalhe do matching: [ADR 0010](0010-mcp-hub-profile-grants.md).

União Fase 1 (ADR 0007) permanece **interina** até implementação.

### Autenticado vs declarado

| Plano | O que é | Uso |
|-------|---------|-----|
| **User autenticado** | Access token OAuth (ADR 0011) | Quem pode falar com o Hub |
| **Client declarado / descoberto** | `clientInfo` → registro MCP Client | Chave do bucket de grants; **não** prova o binário do IDE |
| **Policy** | grants por perfil IdP + `enabled` (admin) | Allowlist (ADR 0010) |

Spoof de `clientInfo`: um script pode apresentar-se como “cursor”. Mitigação
v1: clients novos nascem **sem tools**; só o admin enable+grant. Auth do
**user** é OAuth IdP (não mint). OAuth por produto (futuro) endurece a
prova do aplicativo (ADR 0009).

### Ganchos Loom vs extensão

| Loom (core) | Extensão |
|-------------|----------|
| IdP ativo (Keycloak / Microsoft Entra ID) + BFF `info` / materialize / tools-call | Store MCP Clients + grants |
| Service token Hub↔Loom | UPSERT no initialize; allowlist |
| Mint endpoints → **410** (ADR 0011) | UI: descobertos → enable → grants |

Bind client↔conexão ocorre no Hub após `initialize` (side-state por
`connection_id` OAuth / `sub`).

### Fluxo

```text
IDE ─URL Hub─► 401 + PRM → OAuth PKCE (IdP ativo: Keycloak / Entra) → Bearer JWT
IDE ─initialize + Bearer─► Hub
         │ UPSERT mcp_client (discovered)
         │ connection_id = oauth:{sub}
Admin ─plugin─► enable + grants por perfil (canal × group × tools)
IDE ─tools/list─► grants do perfil do user se enabled, senão []
IDE ─tools/call─► Hub filtra perfil → BFF Loom
```

### Relação com Fase 2

Invoke de agents via Hub = ADR 0007 Fase 2. MCP Clients não são invocáveis.

## Alternativas consideradas

| # | Opção | Resultado |
|---|--------|-----------|
| 1 | União de agents | Interina (0007). |
| 2 | Agent + `hub-channel` | Rejeitada. |
| 3 | MCP Client no core Loom | Rejeitada v1. |
| 4 | Seeds obrigatórios + mint escolhe canal | Rejeitada — supersedida por OAuth (ADR 0011). |
| 5 | Auto-grant tools no discovery | Rejeitada — fail-open. |
| 6 | Authz só com `clientInfo` sem user auth | Rejeitada. |
| 7 | Grants globais no client (sem perfil) | Superseded por [ADR 0010](0010-mcp-hub-profile-grants.md). |
| 8 | Mint Hub session (`hs_…`) | Superseded por [ADR 0011](0011-mcp-hub-oauth-idp.md). |

## Consequências

- Specs 017/024 (OAuth), 018 (allowlist por perfil),
  021 (modelo discovered/enabled), 022 (captura `clientInfo`),
  023 (grants por perfil).
- Plugin: fila “MCP Clients” + editor canal × perfil × tools + URL OAuth.
- Sem tools até enable + grant do perfil — README Hub.

## Specs

1. [017 — Hub session](../specs/017-mcp-hub-session.md)
2. [018 — Allowlist](../specs/018-mcp-hub-allowlist.md)
3. [021 — MCP Clients](../specs/021-mcp-hub-clients.md)
4. [022 — Identificação / discovery](../specs/022-mcp-hub-client-identification.md)
5. [023 — Grants por perfil](../specs/023-mcp-hub-profile-grants.md)
