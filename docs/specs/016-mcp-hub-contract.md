# Spec 016 — Contrato MCP do Hub

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-14 — Fase 2 agents como tools ([ADR 0012](../adr/0012-mcp-hub-agents-as-tools.md))
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md), [ADR 0011](../adr/0011-mcp-hub-oauth-idp.md),
  [ADR 0012](../adr/0012-mcp-hub-agents-as-tools.md)
- **Depende de:** [017](017-mcp-hub-session.md), [024](024-mcp-hub-oauth.md),
  [018](018-mcp-hub-allowlist.md), [019](019-mcp-hub-security.md),
  [025](025-mcp-hub-agents-as-tools.md)

## 1. Objetivo

Definir o endpoint MCP que o IDE consome: **um** servidor streamable-HTTP
que agrega:

1. **tools MCP** do catálogo filtradas por perfil IdP (ADR 0010);
2. **tools de agents** (`agent__*`) quando o canal tem `agents_enabled`
   (ADR 0012 / [025](025-mcp-hub-agents-as-tools.md)).

Auth do IDE = OAuth IdP ([024](024-mcp-hub-oauth.md)); **sem mint**.

`contract_version`: `"2026-09-hub-1"`. Mudança incompatível → nova versão.

## 2. Onde vive

```text
MCP  http://127.0.0.1:8790/mcp     (rede Docker; host loopback)
Auth Authorization: Bearer <access_token OAuth>   # 017 / 024; nunca hs_…

POST /mcp                        JSON-RPC (tools); respostas application/json
GET  /mcp                        405 Allow: POST  (probe Streamable HTTP)
DELETE /mcp                      405 Allow: POST

GET  /.well-known/oauth-protected-resource   # PRM (024)
GET  /health                     (público)
GET  /v1/health                  (Bearer access token ou token de serviço ops)
```

`mcp.json` (IDE): URL do resource + `auth.CLIENT_ID` estático (024);
auth via fluxo OAuth do client.

Código: `local-runtime/services/mcp-hub/`. Overlay ADR 0006.
Não é segundo catálogo; só fachada.

## 3. Métodos MCP

| Método | Comportamento |
|--------|----------------|
| `initialize` | Handshake MCP; `serverInfo.name` = `loom-mcp-hub`. Declara capabilities de tools. |
| `notifications/initialized` | Aceito; no-op. |
| `tools/list` | Access token (017) → allowlist (018) = MCP grants ∪ `agent__*` se `agents_enabled` ([025](025-mcp-hub-agents-as-tools.md)) → naming (§5). |
| `tools/call` | Nome `agent__*` → BFF `agents/invoke` ([025](025-mcp-hub-agents-as-tools.md)). Senão → proxy catálogo MCP. Fora da allowlist / RBAC → erro MCP / 403. |
| `ping` / `resources/*` / `prompts/*` | Fora de escopo v1. |

Bearer inválido / `hs_…` → **401** (017 / 024).

## 4. Erros

| Situação | Código / comportamento |
|----------|-------------------------|
| Sem Bearer / token inválido / expirado | 401; MCP não inicializa |
| Tool MCP não allowlisted / agent RBAC negado | erro JSON-RPC; não chama upstream |
| Upstream indisponível | erro tipado; sem vazar secret/stderr bruto |
| `contract_version` futuro no Hub interno | N/A ao cliente MCP; versionamento é do BFF Hub↔Loom |

Mensagens de erro **não** incluem PAT, JWT nem body de secret.

## 5. Naming de tools

1. **Sem prefixo `loom_`.**
2. Tools MCP: nome preferido = original no servidor; colisão →
   `{server_slug}__{tool_name}` (`server_slug` = `template_id` ou slug de
   `name`, lowercase `[a-z0-9-]+`).
3. Tools de agents: `agent__{slug}` ([025](025-mcp-hub-agents-as-tools.md));
   colisão → `agent__{slug}__{id}`.
4. Sem colisão MCP, **não** namespacar servers.
5. Hub mantém mapa `exposed_name → (kind, server_id|agent_id, original)`
   por request; `tools/call` usa o mapa.

## 6. Agregação

- Fontes MCP: `McpServer` na allowlist de grants (018 §2b).
- Fontes agent: materialize-agents se `agents_enabled` (018 §2c / 025).
- Transports MCP: `stdio` (mcp-runtime), `sse`, `streamable_http`.
- Cache curto opcional para list upstream MCP; agents reavaliam RBAC a
  cada list (revogação rápida).

## 7. Critérios de aceite

- [ ] Cursor conecta com OAuth e lista tools MCP allowlisted
- [ ] Call MCP allowlisted alcança upstream; negada não atinge filho
- [ ] Colisão MCP → `server_slug__tool` estável
- [ ] Bearer inválido / `hs_…` → 401
- [ ] Com `agents_enabled`, `agent__*` respeitam RBAC ([025](025-mcp-hub-agents-as-tools.md))
- [ ] Sem `agents_enabled`, nenhum `agent__*`
