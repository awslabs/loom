# Spec 023 — Grants do Hub por perfil IdP

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — endpoint `profile-grants` on-demand
- **Implementa:** [ADR 0010](../adr/0010-mcp-hub-profile-grants.md)
- **Depende de:** [018](018-mcp-hub-allowlist.md), [021](021-mcp-hub-clients.md), [017](017-mcp-hub-session.md)

## 1. Objetivo

Antes de `tools/list` / `tools/call` num canal (MCP Client), o Hub resolve
quais tools o **perfil IdP** do user pode ver naquele canal.

Admin edita grants **por demanda**: um perfil por vez (GET/PUT), sem
carregar nem salvar o toolset de todos os perfis juntos.

## 2. Forma do grant (extensão)

```text
{
  "group": "g-users-demo",
  "server_id": 7,
  "access_level": "all_tools" | "selected_tools",
  "tool_names": ["search_dashboards"]   # se selected
}
```

- `group`: nome canônico IdP (`g-users-*` / `g-admins-*`), alinhado a
  `GROUP_SCOPES`. Não usar short `demo`.
- Um Save de UI substitui só os grants daquele `group`.

## 3. Matching (runtime Hub)

| User groups | Casa grant.group |
|-------------|------------------|
| contém `g-admins-super` | todos |
| contém `g-users-demo` | `g-users-demo` |
| contém `g-admins-demo` | `g-admins-demo` **e** `g-users-demo` |
| sem overlap | nenhum → list `[]` |

Grant sem `group` → ignorado.

## 4. APIs (on demand)

Plugin / BFF (`/api/ext/local-runtime/…`) → Hub (`/v1/clients/…`):

```text
GET  .../mcp-clients/{slug}/profile-grants?group=g-users-demo
     → 200 { "slug", "group", "grants": [ ... ] }
     → perfil sem grants: 200 + grants=[]
     → client inexistente: 404

PUT  .../mcp-clients/{slug}/profile-grants
     { "group": "g-users-demo", "grants": [ { server_id, access_level, tool_names } ] }
     → substitui só aquele group; outros perfis intactos
```

List clients: summary (`granted_profiles`, `grant_count`) **sem** embedding
do array completo de grants.

Alias Hub legado `/grants` pode existir; contrato canônico = `profile-grants`.

## 5. UI

1. Canal  
2. Dropdown **Select a profile…** (obrigatório; sem default de perfil)  
3. GET `profile-grants` daquele perfil (vazio = form liberado para 1º registro)  
4. All / Selected Tools  
5. Save → PUT só desse perfil  

## 6. Aceite

- [ ] User `g-users-test` não vê grants só de `g-users-demo`
- [ ] Mesmo canal, dois perfis, toolsets distintos
- [ ] UI não carrega/envia todos os perfis de uma vez
- [ ] GET perfil vazio → 200 `[]` e form editável
- [ ] Client disabled / discovered → `tools/list` `[]`
- [ ] Proxy BFF fino; filtro de perfil no Hub
- [ ] Código em `local-runtime/` (+ proxy mínimo no BFF)
