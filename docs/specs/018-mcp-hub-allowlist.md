# Spec 018 — Allowlist do MCP Hub (união por agents)

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md)
- **Depende de:** [016 — contrato](016-mcp-hub-contract.md), [017 — sessão](017-mcp-hub-session.md), modelo `McpServerAccess` / invoke ACL

## 1. Objetivo

Traduzir **conta logada** → conjunto de tools MCP permitidas, reusando o
modelo atual (**agent-centric**) sem criar ACL user→tool paralela.

## 2. Algoritmo (Fase 1)

Dado `subject` (e grupos/scopes já conhecidos no control plane):

```text
1. agents = agents que o usuário PODE invocar
   (mesma regra de grupo/ACL do POST /api/agents/{id}/invoke)

2. Para cada agent em agents:
     para cada McpServerAccess(persona_id=agent.id):
       se access_level == all_tools:
         incluir todas as tools publicadas daquele server (mcp_tools / tools/list)
       se access_level == selected_tools:
         incluir intersection(allowed_tool_names, tools do server)
       se não há McpServerAccess para (server, agent):
         skip (deny-by-default)

3. allowlist = união dos pares (server_id, tool_name)
   (depois naming/colisão na 016)
```

Deny-by-default: zero agents invocáveis ou zero access → `tools/list` = `[]`
( Hub autenticado, catálogo vazio — não 403 no list ).

## 3. Onde calcula

**Preferência v1:** Loom BFF calcula e devolve ao Hub.

```text
GET /api/mcp/hub/allowlist
Authorization: Bearer <MCP_HUB_SERVICE_TOKEN>
X-Loom-Hub-Session-Id: <hub_session_id>
  (ou body/query com session id já introspectado)

→ 200
{
  "subject": "…",
  "hub_session_id": "…",
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

O Hub **não** lê Postgres. Schemas podem vir do cache `mcp_tools` no Loom
ou de refresh upstream (Loom chama mcp-runtime / remoto).

## 4. Frescor (live vs snapshot)

| Evento | Comportamento v1 |
|--------|------------------|
| `tools/list` | Reavalia allowlist no Loom (ou cache ≤ 30s por `hub_session_id`) |
| `tools/call` | Revalida que `(server_id, original_name)` ∈ allowlist **agora** |
| Revogação de `McpServerAccess` | Próximo list/call já nega |
| Mint | **Não** congela tools; só prova identidade |

## 5. Opção adiada: agent fixo

Query/`agent_id` no mint para restringir a união a um agent = **não** é
default Fase 1. Se implementada depois, documentar como extensão desta
spec sem quebrar `2026-09-hub-1` sem bump.

## 6. Critérios de aceite

- [ ] User com access só a tool A via agent X → list contém A, não B
- [ ] User com dois agents allowlisting A e B → list = {A,B}
- [ ] Remover `McpServerAccess` → call seguinte falha sem rede ao filho
- [ ] User sem agents invocáveis → list `[]`
- [ ] Hub sem DB próprio para ACL
