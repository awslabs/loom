# 8. MCP Clients do Hub — discovery na conexão + grants na extensão

- **Status:** Proposta (substitui persona=Agent e seeds obrigatórios a priori)
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — grants por perfil IdP ([ADR 0010](0010-mcp-hub-profile-grants.md))
- **Decisores:** Mantenedores da plataforma / extensão local
- **Relacionada a:**
  [ADR 0006 — Extensão local-runtime](0006-local-runtime-extension-repo.md),
  [ADR 0007 — MCP Hub](0007-mcp-hub.md),
  [ADR 0009 — Identificação do MCP Client](0009-mcp-hub-client-identification.md),
  [ADR 0010 — Grants por perfil](0010-mcp-hub-profile-grants.md),
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
4. ganchos mínimos no Loom (IdP, mint de sessão user, BFF `tools/call`).

## Decisão

### Discovery + enablement

```text
1. User mint Hub session (prova IdP) — sem escolher “canal” a priori
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
| **User autenticado** | Hub session `hs_…` (mint com JWT) | Quem pode falar com o Hub |
| **Client declarado / descoberto** | `clientInfo` → registro MCP Client | Chave do bucket de grants; **não** prova o binário do IDE |
| **Policy** | grants por perfil IdP + `enabled` (admin) | Allowlist (ADR 0010) |

Spoof de `clientInfo`: um script pode apresentar-se como “cursor”. Mitigação
v1: clients novos nascem **sem tools**; só o admin enable+grant. Colar o
Bearer de outro user continua sendo risco de sessão (TTL/revogação). OAuth
por produto (futuro) endurece a prova do aplicativo (ADR 0009).

### Ganchos Loom vs extensão

| Loom (core) | Extensão |
|-------------|----------|
| IdP + mint/introspect/revoke Hub session (user) | Store MCP Clients + grants |
| `tools/call` BFF (secrets) | UPSERT no initialize; allowlist |
| | UI: descobertos → enable → grants |

Mint **não** exige `mcp_client_slug`. O bind client↔sessão ocorre no
Hub após `initialize` (side-state por `hub_session_id`).

### Fluxo

```text
User ─mint─► hs_… (só user)
IDE ─initialize + Bearer─► Hub
         │ UPSERT mcp_client (discovered)
         │ session → slug
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
| 4 | Seeds obrigatórios + mint escolhe canal | Rejeitada como default — nomes de produtos desconhecidos/instáveis. Seeds **opcionais** só como atalho de UI. |
| 5 | Auto-grant tools no discovery | Rejeitada — fail-open. |
| 6 | Authz só com `clientInfo` sem Hub session | Rejeitada. |
| 7 | Grants globais no client (sem perfil) | Superseded por [ADR 0010](0010-mcp-hub-profile-grants.md). |

## Consequências

- Specs 017 (mint sem slug obrigatório), 018 (allowlist por perfil),
  021 (modelo discovered/enabled), 022 (captura `clientInfo`),
  023 (grants por perfil).
- Plugin: fila “MCP Clients” + editor canal × perfil × tools.
- Sem tools até enable + grant do perfil — README Hub.

## Specs

1. [017 — Hub session](../specs/017-mcp-hub-session.md)
2. [018 — Allowlist](../specs/018-mcp-hub-allowlist.md)
3. [021 — MCP Clients](../specs/021-mcp-hub-clients.md)
4. [022 — Identificação / discovery](../specs/022-mcp-hub-client-identification.md)
5. [023 — Grants por perfil](../specs/023-mcp-hub-profile-grants.md)
