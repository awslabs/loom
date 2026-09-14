# 10. Grants do MCP Hub por perfil IdP (canal × perfil × tools)

- **Status:** Aceito
- **Data:** 2026-09-13
- **Decisores:** Mantenedores da plataforma / extensão local
- **Relacionada a:**
  [ADR 0001 — IdP](0001-keycloak-as-identity-provider.md),
  [ADR 0008 — MCP Clients](0008-mcp-hub-clients.md),
  [ADR 0009 — Identificação](0009-mcp-hub-client-identification.md)

## Problema

Com [ADR 0008](0008-mcp-hub-clients.md), grants viviam no **MCP Client**
(canal: Cursor, Claude Code, …) de forma uniforme: qualquer user com Hub
session via um client `enabled` via as mesmas tools.

Isso não espelha Chat, onde o **perfil IdP** (`g-users-demo`, …) delimita
o que o user enxerga. No Hub precisamos: antes de `tools/list`, resolver
quais tools **aquele perfil** pode ver **naquele canal**.

Não queremos ACL nova no core Loom nem misturar com `Agent` /
`McpServerAccess`.

## Decisão

### Modelo

```text
MCP Client (canal, extensão)
  status: discovered | enabled | disabled
  grants[]:
    group          # perfil IdP canônico: g-users-demo, g-admins-mcp, …
    server_id      # catálogo Loom
    access_level   # all_tools | selected_tools
    tool_names     # se selected_tools
```

- **Canal** = superfície descoberta (`clientInfo` → slug).
- **Perfil** = grupo IdP completo (mesmo vocabulário de `GROUP_SCOPES`;
  **não** o short tag `loom:group=demo` dos agents).
- **Tools** = All / Selected por server, por perfil, por canal.

`allowed_groups` no client passa a ser **derivado** dos `group` presentes
nos grants (índice/UI), não uma allowlist separada.

### Resolução em list/call (extensão)

```text
1. Hub session ativa → groups do user (mint/introspect)
2. Resolver canal (slug bound no initialize)
3. Se client status ≠ enabled → []
4. Filtrar grants onde grant.group ∈ perfis do user
   — g-admins-super → todos os grants do canal
   — g-admins-{name} também casa grants g-users-{name} (cohort)
5. Materializar só esses grants via BFF Loom (schemas/secrets)
6. Naming → spec 016
```

Deny-by-default: sem grant para o perfil do user → `tools/list` = `[]`.
Grants legados sem `group` são ignorados (obrigam re-save na UI).

### UI (plugin Local runtime)

```text
1. Selecionar canal (MCP Client)
2. Dropdown "Select a profile…" (obrigatório — sem perfil default)
3. GET profile-grants?group=…  (vazio → 200 []; form liberado)
4. Marcar servers → All Tools | Selected Tools
5. PUT profile-grants { group, grants } — só aquele perfil
6. Enable canal quando houver grant em algum perfil
```

Listagem de clients não embute grants; só `granted_profiles` / `grant_count`.

### Fronteira Loom

| Extensão (local-runtime) | Loom core |
|--------------------------|-----------|
| Store grants com `group` | Mint/introspect (groups na sessão) |
| Filtro perfil → grants antes do list | `materialize-allowlist` / `tools/call` com grants **já filtrados** |
| UI + Hub `…/profile-grants` | Proxy fino `/api/ext/local-runtime/mcp-clients/…/profile-grants` |

Hub envia `allowed_groups: []` no materialize e só os grants do perfil do
user; o BFF materializa o payload recebido (sem ACL user→tool no core).

## Alternativas consideradas

| # | Opção | Resultado |
|---|--------|-----------|
| 1 | `allowed_groups` no client + grants globais | Rejeitada — não diferencia tools por perfil |
| 2 | Reusar `loom:group` short tag nos grants | Rejeitada — JWT traz `g-users-*`; short exige strip inconsistente |
| 3 | União de tools dos agents do user | Já rejeitada no 0008 |
| 4 | ACL user→tool no core Loom | Rejeitada — fora do escopo da extensão |

## Consequências

- Specs [018](../specs/018-mcp-hub-allowlist.md), [021](../specs/021-mcp-hub-clients.md),
  [023](../specs/023-mcp-hub-profile-grants.md) atualizadas/criadas.
- Admin configura **por canal e por perfil**; dois users no mesmo Cursor
  podem ver toolsets diferentes.
- Código em `local-runtime/services/mcp-hub` + plugin; core Loom intocado
  neste ADR.

## Specs

1. [023 — Grants por perfil](../specs/023-mcp-hub-profile-grants.md)
2. [018 — Allowlist](../specs/018-mcp-hub-allowlist.md) (algoritmo 2b)
3. [021 — MCP Clients](../specs/021-mcp-hub-clients.md)
