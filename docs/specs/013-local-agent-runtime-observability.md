# Spec 013 — Observabilidade do Local Agent Runtime

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Implementa:** [ADR 0005](../adr/0005-local-agent-runtime.md)
- **Depende de:** [011 — contrato](011-local-agent-runtime-contract.md), [010 — obs MCP](010-local-mcp-observability.md)

## 1. Princípio

Correlacionar **session / invocation / tool / model** sem criar APM novo.
Reusar logger estruturado do stack local. **Nunca** logar secret, PAT,
Bearer, prompt completo por padrão, nem stdout bruto de MCP.

## 2. IDs de correlação

Todo log do agent-runtime carrega:

```text
session_id
invocation_id
agent_id      (do identity / agent.id)
subject       (user.sub)
contract_version
```

O backend já conhece `session_id` / `invocation_id` na tabela de
invocations. O runtime **não** escreve no Postgres na v1; o backend
atualiza status a partir do SSE (`streaming` → `complete` / `error`).

## 3. Eventos de lifecycle

```text
event=agent_runtime_session
phase=start|end|cancel|timeout|error
session_id
invocation_id
duration_ms     (em end/error)
error_code      (nullable)
model_id
mcp_server_count
tool_rounds
```

## 4. Model calls

```text
event=agent_runtime_model
session_id
invocation_id
model_id
status=ok|error|timeout
duration_ms
# tokens: opcional se o LiteLLM devolver usage
```

Sem conteúdo das mensagens no log v1 (PII / secret em prompts).

## 5. Tool calls

Alinhar campos à spec 010 quando o destino for mcp-runtime:

```text
event=agent_runtime_tool
session_id
invocation_id
mcp_name
tool_name
status=ok|denied|error|timeout
duration_ms
```

Sem `arguments` completos na v1. Session Detail do Loom continua a fonte
de UI; não duplicar payload no SSE além do necessário para o Chat.

## 6. Métricas (v1)

| Métrica | Significado |
| --- | --- |
| `agent_runtime_active_sessions` | sessões vivas |
| `agent_runtime_invocations_total` | ok / error / cancel / timeout |
| `agent_runtime_tool_rounds` | histograma ou último valor |
| `agent_runtime_model_ms` | latência LiteLLM |
| `agent_runtime_tool_ms` | latência tools/call |

Expor `GET /v1/metrics` JSON autenticado (como `/runtime/metrics` do MCP).
Prometheus opcional depois.

## 7. Relação com o Chat / SSE

- `session_start` / `chunk` / `session_end` / `error` permanecem o
  contrato com o browser (spec 011).
- Erros de modelo/MCP usam `code` estável da 011 para a UI mapear
  mensagens (sem stack trace).

## 8. stderr / crash do worker

Arquivo rotativo **dentro do container** do agent-runtime. Redactor
igual ao MCP (`token|pat|secret|bearer`). Health **não** devolve stderr.

## 9. Compatibilidade

Invoke AgentCore/harness mantém telemetria atual. Esta spec aplica-se só
ao adapter `local`.
