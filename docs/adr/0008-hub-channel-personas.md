# 8. Hub channel personas — policy de tools por canal (não invocável)

- **Status:** Proposta
- **Data:** 2026-09-13
- **Decisores:** Mantenedores da plataforma / extensão local
- **Relacionada a:**
  [ADR 0007 — MCP Hub](0007-mcp-hub.md),
  [ADR 0001 — IdP](0001-keycloak-as-identity-provider.md),
  [ADR 0006 — Extensão local-runtime](0006-local-runtime-extension-repo.md),
  [Spec 018 — Allowlist](../specs/018-mcp-hub-allowlist.md)

## Problema

O MCP Hub (ADR 0007) precisa expor tools MCP a clientes externos
(Cursor, Claude Code, Cowork, VS Code, …). A allowlist da Fase 1 usa a
**união** das tools de todos os **agents invocáveis** da conta.

Isso mistura dois conceitos:

1. **Agents de Chat / runtime** — planejam, invocam, respondem.
2. **Canais de cliente MCP** — superfícies (IDE, CLI agent, cowork)
   que só precisam de um **conjunto de tools permitido**.

Consequências ruins:

- Cursor herda o mesmo pacote de tools do Chat.
- Não dá para customizar Grafana/ADO/Rancher por produto (Claude Code vs
  Cowork vs Cursor).
- Tratar o canal como “agent invocável” polui Chat, invoke e deploy.

Queremos **policy de tools por canal**, reusando `McpServerAccess`, sem
ACL user→tool paralela e sem tornar o canal invocável.

## Decisão

### Hub channel persona

Introduzir o conceito **Hub channel persona** (persona de canal):

```text
Canal (ex. cursor-ide, claude-code, claude-cowork)
  = persona no Loom com kind=hub-channel
  → carrega só McpServerAccess (tools do canal)
  → NÃO é invocável (Chat / POST invoke / agent-runtime)
  → NÃO exige modelo, deploy AgentCore nem planner
```

Implementação preferida v1: reusar a tabela `Agent` (ou persona já usada
por `McpServerAccess.persona_id`) com marcador estável, por exemplo tag
`loom:kind=hub-channel` (e slug estável em `name` / id conhecido). Spec
deve fixar o campo canônico.

Regras duras:

1. Personas `hub-channel` **excluídas** de listagens invocáveis, Chat e
   `POST /api/agents/{id}/invoke`.
2. Allowlist do Hub para uma sessão = **somente** `McpServerAccess` da
   persona do canal bound — **não** a união de agents de Chat.
3. Quem pode usar o canal: autorização de **acesso ao canal** (grupos /
   `loom:group` ou equivalente), **sem** passar pelo caminho “pode
   invocar agent de Chat”. Deny-by-default se o user não tiver acesso ao
   canal ou o canal não tiver access rules.
4. Admin configura tools por canal na UI de MCP access (mesmo modelo
   agent-centric, persona = canal).

Isto **substitui o default de allowlist** do ADR 0007 para o caminho Hub:
a união por agents invocáveis fica **interina** até esta ADR ser
implementada; depois, Hub = canal bound apenas.

### Identificação do canal

O canal **não** é inferido de forma confiável a partir do tráfego MCP.

| Fonte | Papel |
|-------|--------|
| **Bind no mint (obrigatório v1)** | UI/API escolhe `channel_slug` (ou `persona_id`). A Hub session persiste o bind. Allowlist e `tools/call` usam só essa persona. |
| **OAuth `client_id` (futuro)** | Cada produto registra um OAuth client; no callback o Loom mapeia `client_id` → canal e emite sessão já bound. |
| `initialize.clientInfo` / headers `X-Loom-Channel` / User-Agent | **Somente audit / UX** (sugestão na UI). Nunca autorização. |

Detalhes v1:

- Mint exige canal válido (`hub-channel` existente e ativo).
- Token colado noutro cliente MCP herda a policy do canal mintado
  (mitigado por TTL + segredo do Bearer + revogação).
- URL opcional por canal (`/mcp/c/{slug}`) é conveniência; auth continua
  sendo sessão + bind, não o path sozinho.
- Seeds locais recomendados (híbrido): `cursor-ide`, `claude-code`,
  `claude-cowork` (+ admin pode criar canais adicionais).

### Relação com Fase 2 (invoke de agents)

Invocar agents Loom via Hub (tools `list_agents` / `invoke_agent` ou A2A)
permanece ADR 0007 Fase 2 / ADR futura. Channel personas **não** são o
alvo desse invoke; são só controladores de tools do cliente MCP.

### Fluxo

```text
1. User autentica no Loom (IdP).
2. UI: Mint Hub session → escolhe canal (ex. cursor-ide).
3. Loom verifica acesso do user ao canal; emite hs_… com channel bind.
4. IDE configura URL + Bearer.
5. tools/list|call: Hub → BFF allowlist(session) → McpServerAccess(channel persona).
6. Revogação de access ou logout → próximo list/call nega (live ACL).
```

## Alternativas consideradas

| # | Opção | Resultado |
|---|--------|-----------|
| 1 | Manter união de agents invocáveis (ADR 0007 Fase 1) | Rejeitada como default duradouro; mistura Chat e IDE. |
| 2 | ACL user→tool nova | Rejeitada: duplica modelo; admin já pensa em access por persona. |
| 3 | Canal = agent invocável “falso” | Rejeitada: polui Chat/invoke; mentira de produto. |
| 4 | Detectar canal via `clientInfo` / header | Rejeitada como auth; spoofável. Só audit. |
| 5 | Entidade nova `HubClientProfile` sem reusar persona | Adiada: só se `Agent`+kind for insuficiente. |
| 6 | Um canal por usuário | Rejeitada: overkill; canal é produto, grant é por grupo. |

## Consequências

- Atualizar [018](../specs/018-mcp-hub-allowlist.md): allowlist Hub = canal
  bound; excluir `hub-channel` do caminho invoke.
- Atualizar [017](../specs/017-mcp-hub-session.md): mint exige
  `channel_slug` / `persona_id`; sessão persiste bind; introspect devolve
  canal.
- UI Local Runtime: seletor de canal no mint + docs por canal no README
  do mcp-hub.
- Seed (local): personas `cursor-ide`, `claude-code`, `claude-cowork`.
- Migrar implementação atual de `build_allowlist` (união) → bind de canal.
- ADR 0007: default de união marcado como **supersedido** por esta ADR
  quando implementada.
- Testes: user sem acesso ao canal → list `[]`/401; access só no canal A
  → tools de A; agent Chat com tools não vazam para Hub do canal B;
  persona `hub-channel` não aparece em invoke/Chat.

## Specs a seguir / atualizar

1. [017 — Hub session](../specs/017-mcp-hub-session.md) — bind de canal no mint
2. [018 — Allowlist](../specs/018-mcp-hub-allowlist.md) — canal persona, não união
3. [021 — Hub channel personas](../specs/021-mcp-hub-channel-personas.md) — kind, acesso, seeds, APIs
4. [016](../specs/016-mcp-hub-contract.md) / [019](../specs/019-mcp-hub-security.md) — só se path `/mcp/c/{slug}` ou OAuth client map

Implementação do bind de canal **não** começa até 017/018/021 serem
aceitos sob esta ADR.

