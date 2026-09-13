# Spec 011 — Contrato de invoke do Local Agent Runtime

- **Status:** Implementado (contrato `2026-09-local-1`)
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — path `local-runtime/services/agent-runtime`; BFF; ensure_stdio
- **Implementa:** [ADR 0005](../adr/0005-local-agent-runtime.md)
- **Depende de:** [ADR 0003](../adr/0003-litellm-as-llm-gateway.md), [ADR 0004](../adr/0004-local-mcp-runtime.md), [012 — segurança](012-local-agent-runtime-security.md)

## 1. Objetivo

Definir o **mesmo subconjunto** de payload que o control plane já monta
para AgentCore/harness, consumido pelo `agent-runtime` local. O backend
não executa tool loop; só autoriza, monta o contrato e faz proxy do SSE.

Versionamento: campo `contract_version` (v1 = `"2026-09-local-1"`).
Mudança incompatível → nova versão; runtime rejeita versão desconhecida
com `400 unsupported_contract`.

## 2. Onde vive

```text
POST http://agent-runtime:8766/v1/invoke
Authorization: Bearer <AGENT_RUNTIME_TOKEN>
Accept: text/event-stream
Content-Type: application/json

GET  /health          (público)
GET  /v1/health       (Bearer)
POST /v1/sessions/{id}/cancel  (Bearer)
```

Host bind: `127.0.0.1` no host / rede Docker. Código:
`local-runtime/services/agent-runtime/` (overlay
`local-runtime/compose/overlay.yml`).

O FastAPI **não** chama LiteLLM no caminho `source=local` quando
`AGENT_RUNTIME_URL` está setado. `invoke_local_agent_stream` é o BFF
deste contrato (`backend/app/services/local_invoke.py`).

## 3. Request (JSON)

```text
{
  "contract_version": "2026-09-local-1",
  "prompt": "string",
  "session_id": "string",
  "invocation_id": "string",
  "agent": {
    "id": 0,
    "name": "string",
    "system_prompt": "string | null"
  },
  "model_id": "string",
  "mcp_servers": [
    {
      "name": "string",
      "endpoint_url": "string",
      "transport": "sse | streamable_http",
      "allowed_tools": ["string"] | null,
      "auth": {
        "type": "none | service_bearer | api_key | oauth2",
        "...": "campos mínimos; stdio usa service_bearer + MCP_RUNTIME_TOKEN"
      }
    }
  ],
  "identity": {
    "subject": "string",
    "agent_id": "string",
    "session_id": "string"
  },
  "approval_policies": [] ,
  "options": {
    "timeout_s": 300,
    "max_tool_rounds": 20
  }
}
```

Regras:

1. `mcp_servers` já vem **filtrado** pelo backend (`McpServerAccess`).
   `allowed_tools: null` = todas as tools que o MCP listar; lista = allowlist.
2. Stdio no catálogo chega aqui como `transport=streamable_http` +
   `endpoint_url=http://mcp-runtime:8787/s/{id}/mcp` (ADR 0004).
3. Antes do BFF, para cada connector stdio o backend chama
   `ensure_stdio_ready` (evita `404 unknown_server` após recreate do
   mcp-runtime). Enrichment injeta `service_bearer` + token de serviço
   (`enrich_mcp_servers_for_runtime`); **nunca** o JWT do usuário.
4. `approval_policies` pode ser `[]` em M1.
5. `model_id=cursor-local`: o LiteLLM/CustomLLM + cursor-adapter operam
   em **planner mode** (spec 004 §9). O agent-runtime ainda é quem chama
   MCP; o Cursor só devolve `tool_calls` / `content`.

## 4. Response (SSE)

Mesmos eventos do Chat: `session_start`, `chunk`, `session_end`, `error`.
`token_source=local-agent-runtime`.

## 5. Tool loop (runtime)

1. `tools/list` em cada `mcp_servers[].endpoint_url` (headers de identity +
   allowlist + service bearer).
2. Nomes OpenAI: `{server}__{tool}` (sanitizados).
3. `POST LiteLLM /v1/chat/completions` com `tools` (e, para cursor-local,
   marker `<<<loom_openai_tools>>>` nas messages — workaround CustomLLM).
4. Se `tool_calls` → `tools/call` no MCP; anexar `role=tool`; repetir até
   texto final ou `max_tool_rounds`.
5. Recuperação: se a resposta LiteLLM trouxer JSON `tool_calls` só em
   `content` (drop do campo estruturado), o runtime reconstrói a lista.

## 6. Critérios de aceite

- [x] `contract_version` obrigatório; versão desconhecida → 400
- [x] Bearer vazio → fail-closed 401
- [x] SSE proxy no backend com `AGENT_RUNTIME_URL`
- [x] Stdio provisionado no invoke (`ensure_stdio_ready`)
- [x] `make local.agent-runtime.test`
- [ ] Telemetria estruturada completa (spec 013) — parcial
