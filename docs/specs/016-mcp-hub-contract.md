# Spec 016 — Contrato MCP do Hub (Fase 1)

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md)
- **Depende de:** [017 — sessão](017-mcp-hub-session.md), [018 — allowlist](018-mcp-hub-allowlist.md), [019 — segurança](019-mcp-hub-security.md)

## 1. Objetivo

Definir o endpoint MCP que o IDE consome: **um** servidor streamable-HTTP
que agrega tools do catálogo Loom filtradas pela conta (Hub session).
Fase 1 = **somente tools MCP**. Sem invoke de agents.

`contract_version`: `"2026-09-hub-1"`. Mudança incompatível → nova versão.

## 2. Onde vive

```text
MCP  http://mcp-hub:8790/mcp     (rede Docker; host 127.0.0.1:8790)
Auth Authorization: Bearer <hub_session_token>

POST /mcp                        JSON-RPC (tools); respostas application/json
GET  /mcp                        405 Allow: POST  (sem SSE standalone; exigido pelo
                                 cliente Streamable HTTP do Cursor — 404 quebra)
DELETE /mcp                      405 Allow: POST  (sessões Hub são stateless no wire)

GET  /health                     (público)
GET  /v1/health                  (Bearer Hub session ou token de serviço ops)
```

Código: `local-runtime/services/mcp-hub/`. Overlay ADR 0006.
Não é segundo catálogo; só fachada.

## 3. Métodos MCP (Fase 1)

| Método | Comportamento |
|--------|----------------|
| `initialize` | Handshake MCP; `serverInfo.name` = `loom-mcp-hub` (nome do processo, não prefixo de tools). Declara capabilities de tools. |
| `notifications/initialized` | Aceito; no-op. |
| `tools/list` | Introspect sessão → allowlist viva (018) → agrega schemas → aplica naming ( §5 ). |
| `tools/call` | Nome ∈ allowlist → resolve `server_id` + tool original → proxy ao endpoint do catálogo (mcp-runtime ou remoto) com service auth + `X-Loom-Allowed-Tools`. Fora da allowlist → erro MCP / 403. |
| `ping` / `resources/*` / `prompts/*` | Fora de escopo v1 (recusar ou capabilities vazias). |

JWT do IdP no Bearer do Hub → **401** (só Hub session).

## 4. Erros

| Situação | Código / comportamento |
|----------|-------------------------|
| Sem Bearer / token inválido / expirado | 401; MCP não inicializa |
| Tool não allowlisted | erro JSON-RPC / application error; não chama upstream |
| Upstream indisponível | erro tipado; sem vazar secret/stderr bruto |
| `contract_version` futuro no Hub interno | N/A ao cliente MCP; versionamento é do BFF Hub↔Loom |

Mensagens de erro **não** incluem PAT, Hub session, JWT nem body de secret.

## 5. Naming de tools

1. **Sem prefixo `loom_`.**
2. Nome preferido = nome original da tool no servidor de origem.
3. **Colisão** (mesmo nome em ≥2 servidores na allowlist da conta):
   namespacar com slug do servidor estável:
   `{server_slug}__{tool_name}`  
   onde `server_slug` = `template_id` se stdio, senão slug de `name` do
   `McpServer` (lowercase, `[a-z0-9-]+`).
4. Se não houver colisão, **não** namespacar (IDE vê nomes limpos).
5. O Hub mantém mapa invertido `exposed_name → (server_id, original_name)`
   por sessão/request; `tools/call` usa o mapa.

## 6. Agregação

- Fontes: todos os `McpServer` que aparecem na allowlist (018).
- Transports: `stdio` (URL interna mcp-runtime), `sse`, `streamable_http`.
- `tools/list` upstream pode ser cacheado por `(hub_session_id, server_id)`
  com TTL curto (ex. 30s); invalidate em 403/revogação.

## 7. Critérios de aceite

- [ ] Cursor/cliente MCP conecta com Hub session e lista só tools allowlisted
- [ ] Call de tool allowlisted alcança Grafana/ADO/Rancher (ou mock) com sucesso
- [ ] Call de tool negada não atinge o filho/remoto
- [ ] Colisão de nomes produz `server_slug__tool` estável e reversível
- [ ] Bearer JWT IdP no Hub → 401
- [ ] Sem tools `list_agents` / `invoke_agent` na Fase 1
