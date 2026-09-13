# Spec 018 — Allowlist do MCP Hub

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — canal bound ([ADR 0008](../adr/0008-hub-channel-personas.md) / [021](021-mcp-hub-channel-personas.md))
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md), [ADR 0008](../adr/0008-hub-channel-personas.md)
- **Depende de:** [016 — contrato](016-mcp-hub-contract.md), [017 — sessão](017-mcp-hub-session.md), [021 — channel personas](021-mcp-hub-channel-personas.md), modelo `McpServerAccess`

## 1. Objetivo

Traduzir **Hub session (conta + canal)** → conjunto de tools MCP
permitidas, reusando o modelo **persona-centric** (`McpServerAccess`)
sem ACL user→tool paralela.

## 2. Algoritmo

### 2a. Interino (só até ADR 0008 implementado)

Dado `subject` (grupos/scopes no control plane), **sem** bind de canal:

```text
1. agents = agents que o usuário PODE invocar
   — excluir loom:kind=hub-channel
2. união de McpServerAccess desses agents
3. allowlist = união (server_id, tool_name)
```

### 2b. Default ([ADR 0008](../adr/0008-hub-channel-personas.md) / [021](021-mcp-hub-channel-personas.md))

Sessão **com** `channel_slug` / `persona_id` (017):

```text
1. Carregar persona do bind; deve ser hub-channel ativa
2. Revalidar acesso do user ao canal (021); senão entries=[]
3. rules = McpServerAccess(persona_id=canal)
4. Para cada rule:
     all_tools → tools publicadas do server (mcp_tools)
     selected_tools → intersection(allowed_tool_names, tools do server)
5. allowlist = só esse conjunto (sem união de Chat)
6. Naming/colisão → 016
```

Deny-by-default: sem access no canal → `tools/list` = `[]` (Hub
autenticado, catálogo vazio — não 403 no list). `tools/call` fora da
lista → erro / 403.

## 3. Onde calcula

**Preferência v1:** Loom BFF calcula e devolve ao Hub.

```text
GET /api/mcp/hub/allowlist
Authorization: Bearer <MCP_HUB_SERVICE_TOKEN>
X-Loom-Hub-Session-Id: <hub_session_id>

→ 200
{
  "subject": "…",
  "hub_session_id": "…",
  "channel_slug": "cursor-ide",
  "persona_id": "<id>",
  "entries": [
    {
      "server_id": 1,
      "server_slug": "grafana",
      "endpoint_url": "http://mcp-runtime:8787/s/1/mcp",
      "transport": "streamable_http",
      "tools": [
        { "name": "search_dashboards", "description": "…", "inputSchema": {} }
      ]
    }
  ],
  "generated_at": "ISO-8601"
}
```

O Hub **não** lê Postgres.

## 4. Frescor (live vs snapshot)

| Evento | Comportamento v1 |
|--------|------------------|
| `tools/list` | Reavalia allowlist no Loom (ou cache ≤ 30s por `hub_session_id`) |
| `tools/call` | Revalida `(server_id, original_name)` ∈ allowlist **agora** |
| Revogação de `McpServerAccess` no canal | Próximo list/call já nega |
| Mint | **Não** congela tools; só identidade + bind de canal |
| Troca de canal | Novo mint (017); sessão antiga mantém bind |

## 5. Critérios de aceite

- [ ] Sessão bound a canal A com tool X → list contém X; tool só no Chat agent → ausente
- [ ] Canal B com tools diferentes → sessão B não vê tools só de A
- [ ] Remover `McpServerAccess` do canal → call seguinte falha sem rede ao filho
- [ ] User sem acesso ao canal / canal sem rules → list `[]`
- [ ] Hub sem DB próprio para ACL
- [ ] Persona `hub-channel` excluída do algoritmo §2a
