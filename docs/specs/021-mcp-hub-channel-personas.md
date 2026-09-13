# Spec 021 — Hub channel personas (policy de tools por canal)

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Implementa:** [ADR 0008](../adr/0008-hub-channel-personas.md)
- **Depende de:** [ADR 0007](../adr/0007-mcp-hub.md), [017 — sessão](017-mcp-hub-session.md), [018 — allowlist](018-mcp-hub-allowlist.md), modelo `Agent` / `McpServerAccess`

## 1. Objetivo

Definir **Hub channel personas**: controladores de ACL de tools por canal
de cliente MCP (Cursor, Claude Code, Cowork, …).

Não são agents invocáveis. Não planejam, não fazem deploy, não aparecem
no Chat. Só carregam `McpServerAccess` para o MCP Hub.

## 2. Modelo de dados

### 2.1 Representação v1

Reusar a entidade já referenciada por `McpServerAccess.persona_id`
(tabela `Agent` / persona Loom) com marcador canônico:

| Campo | Valor |
|-------|--------|
| Tag | `loom:kind` = `hub-channel` (**obrigatória**) |
| Slug | estável, URL-safe: `cursor-ide`, `claude-code`, … |
| Onde vive o slug | preferência: `tags["loom:channel"]` = slug **ou** `name` normalizado; spec de implementação escolhe um e documenta. API pública expõe sempre `channel_slug`. |
| Modelo / runtime / endpoint AgentCore | não exigidos; podem ficar vazios / placeholder |
| Status | `active` \| `inactive` (inactive → mint 400) |

Índice/unicidade: no máximo uma persona ativa por `channel_slug`.

### 2.2 O que a persona NÃO é

- Não entra em `POST /api/agents/{id}/invoke`.
- Não aparece em listas de agents do Chat / picker invocável.
- Não é alvo de agent-runtime / cursor-local planner.
- Não conta como “agent invocável” no algoritmo interino 018 §2a
  (excluir `loom:kind=hub-channel`).

Filtro recomendado em listagens de agents: omitir por default quando
`loom:kind=hub-channel`; admin UI de MCP Hub / Integrations pode listar
só canais.

## 3. Acesso do usuário ao canal

Mesma família de grupos do Chat, aplicada à **persona do canal**
(não ao caminho invoke):

```text
tags["loom:group"] no canal (opcional)
  - vazio → qualquer user autenticado com mcp:read pode mintar o canal
    (dev local); produção deve preferir grupo explícito
  - preenchido → user precisa do grupo correspondente
    (g-users-{group} / g-admins-{group} / g-admins-super),
    espelhando a lógica de user_can_invoke_agent MAS
    sem marcar o canal como invocável
```

Nome da função na implementação: preferir `user_can_access_hub_channel`
(separado de `user_can_invoke_agent`) mesmo que a regra de grupos seja
idêntica — evita regressão que “libere invoke” do canal.

Deny: mint → 403 `channel_forbidden`; allowlist → `entries: []` se a
sessão for inválida para o canal.

## 4. Tools do canal

```text
McpServerAccess(persona_id = canal.id)
  access_level = all_tools | selected_tools
```

Admin concede tools na UI de MCP access escolhendo a **persona canal**
(não um agent de Chat). Allowlist Hub (018 §2b) = só essas rules.

Revogar access → próximo `tools/list` / `tools/call` já nega (live).

## 5. Seeds locais (híbrido)

Compose/local-runtime **pode** garantir na subida (idempotente):

| channel_slug | Uso típico |
|--------------|------------|
| `cursor-ide` | Cursor IDE MCP |
| `claude-code` | Claude Code |
| `claude-cowork` | Claude Cowork / superfícies análogas |

- Seeds criam a persona + `loom:kind=hub-channel` + slug; **não** criam
  `McpServerAccess` (admin liga Grafana/ADO/Rancher depois).
- Admin pode criar canais adicionais (`vscode-mcp`, `custom-…`).
- Remover um seed da tabela não é automático no upgrade; migração /
  docs se necessário.

## 6. APIs (mínimo)

Além do mint (017):

```text
GET /api/mcp/hub/channels
Authorization: Bearer <JWT usuário>
Scopes: mcp:read

→ 200
{
  "channels": [
    {
      "channel_slug": "cursor-ide",
      "persona_id": "<id>",
      "display_name": "Cursor IDE",
      "accessible": true
    }
  ]
}
```

Lista personas `hub-channel` ativas; `accessible` reflete §3 para o
caller (UI do mint só habilita os `accessible: true`).

CRUD admin de canais: reusar criação/edição de Agent com validação
`loom:kind=hub-channel` **ou** endpoints dedicados — detalhe de UI;
obrigatório que não exponha o canal como invocável.

## 7. Identificação do canal (resumo)

| Fonte | Auth? |
|-------|-------|
| `channel_slug` / `persona_id` no mint → bind na sessão | **Sim** |
| OAuth `client_id` → mapa canal (futuro) | **Sim** (fase OAuth) |
| MCP `clientInfo` / headers / UA | **Não** (audit/UX only) |

## 8. Observabilidade

Logs / métricas (020): incluir `channel_slug` + `persona_id` +
`hub_session_id` em mint, allowlist e tools/call. Sem Bearer em claro.

## 9. Critérios de aceite

- [ ] Persona com `loom:kind=hub-channel` não aparece no Chat / invoke
- [ ] `POST …/invoke` nessa persona → 403/404 (não invocável)
- [ ] Mint exige canal; bind persiste; introspect devolve slug
- [ ] Allowlist Hub = só `McpServerAccess` do canal (018 §2b)
- [ ] Tools de agent Chat **não** vazam para sessão de outro canal
- [ ] User sem grupo do canal → 403 no mint
- [ ] Seeds locais criáveis idempotentes sem access rules
- [ ] `GET /api/mcp/hub/channels` reflete `accessible` corretamente
