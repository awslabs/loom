# Spec 011 — Contrato de invoke do Local Agent Runtime

- **Status:** Rascunho
- **Data:** 2026-09-13
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
```

Host bind: `127.0.0.1` / rede Docker. Pacote sugerido:
`etc/docker/agent-runtime/` (espelho de `mcp-runtime` e `cursor-adapter`).

O FastAPI **não** chama LiteLLM no caminho `source=local` após M1.
`invoke_local_agent_stream` vira cliente deste contrato (ou some a favor
de um `AgentRuntimeClient` compartilhado).

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
3. `approval_policies` pode ser `[]` em M1; formato = o que
   `invocations.py` já serializa para AgentCore.
4. O runtime **não** consulta Postgres nem o IdP.

## 4. Response (SSE)

Mesmos eventos que o Chat já consome no path AgentCore:

| Evento | Quando |
| --- | --- |
| `session_start` | início; inclui `session_id`, `invocation_id`, `token_source=local-agent-runtime` |
| `chunk` | texto parcial `{ "text": "..." }` |
| `tool_call` / `tool_result` | opcional M2 se a UI já souber renderizar; senão embutir resumo em chunk |
| `session_end` | sucesso; métricas mínimas (`input_tokens`, `output_tokens` estimados ok na v1) |
| `error` | falha; `{ "message": "...", "code": "..." }` sem secret |

Proxy: o backend reencaminha bytes SSE ao browser **sem** reinterpretar o
tool loop. Pode enriquecer `session_start` com campos de auth Loom já
usados hoje.

## 5. Cancelamento

```text
POST /v1/sessions/{session_id}/cancel
Authorization: Bearer <AGENT_RUNTIME_TOKEN>
```

Runtime mata o processo/sessão e encerra o SSE com `error` código
`cancelled` ou `session_end` com status cancelado (escolher um na
implementação e documentar no OpenAPI interno). M1: best-effort; M3:
garantia de kill + timeout.

## 6. Health

```text
GET /health → { "status": "ok" }   (público na rede interna)
GET /v1/health → { "status", "active_sessions", "contract_versions": [...] }
  (autenticado)
```

## 7. Erros estáveis (`code`)

| code | HTTP / SSE | Significado |
| --- | --- | --- |
| `runtime_auth` | 401 | token de serviço inválido |
| `unsupported_contract` | 400 | `contract_version` desconhecida |
| `invalid_payload` | 400 | schema |
| `model_unreachable` | SSE error | LiteLLM down / 5xx |
| `model_auth` | SSE error | chave do proxy |
| `mcp_unreachable` | SSE error | fachada MCP |
| `mcp_denied` | SSE error | tool fora da allowlist (defesa em profundidade) |
| `timeout` | SSE error | `options.timeout_s` |
| `cancelled` | SSE error | cancel |
| `internal` | 500 / SSE | genérico; sem stack com secret |

## 8. Adapters no control plane

```text
AgentRuntimeClient
  ├─ agentcore   → invoke_agent (existente)
  ├─ harness     → InvokeHarness (existente)
  └─ local       → POST agent-runtime /v1/invoke (esta spec)
```

`source=local` ⇒ adapter `local`. Não criar `source=agent-runtime`.

## 9. Fora de escopo desta spec

- Escolha do framework interno (Strands vs ADK vs loop OpenAI-tools) —
  decisão de implementação na spec de aceite / README do pacote; o
  contrato HTTP não muda.
- Memory, A2A, OBO (M3).
- Implementação do compose (porta final, Dockerfile).
