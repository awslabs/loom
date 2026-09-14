# Spec 010 — Observabilidade do MCP local

- **Status:** Rascunho
- **Data:** 2026-09-12
- **Implementa:** [ADR 0004](../adr/0004-local-mcp-runtime.md)

## 1. Princípio

Reusar logger + `trackAction` (categoria `mcp`) + status no catálogo.
Não criar um APM novo. **Nunca** logar secret, PAT, token ou stdout
completo do filho.

## 2. Eventos de lifecycle

Structured log (campos fixos):

```text
event=mcp_runtime_state
server_id
template_id
from_state
to_state
pid          (nullable)
restarts
duration_ms  (startup / stop)
error_code   (sem mensagem bruta do filho se puder vazar secret)
```

Eventos: `register`, `starting`, `ready`, `failed`, `restarting`,
`stopping`, `stopped`.

Espelhar `runtime_state` + `McpServer.status` para a UI existente
(badge active/error).

## 3. Tool execution

Cada `tools/call`:

```text
event=mcp_tool_call
server_id
tool_name
agent_id
subject      (user.sub, não email se for PII demais — sub ok)
status       ok|denied|error|timeout
duration_ms
```

Sem `arguments` completos se o schema puder carregar secret; v1: logar
só `tool_name` + status. Auditoria UI: reusar `invoke_tool`.

No stream de chat, o tool-use já existe; não duplicar o payload.

## 4. Métricas (v1: contadores em memória + log periódico)

| Métrica | Significado |
| --- | --- |
| `mcp_runtime_active_processes` | filhos vivos |
| `mcp_runtime_restarts_total` | por server_id |
| `mcp_runtime_startup_ms` | último start bem-sucedido |
| `mcp_runtime_call_ms` | latência de tools/call |
| `mcp_runtime_calls_total` | ok / denied / error |
| `mcp_runtime_child_exits_total` | exit code ≠ 0 |

Expor `GET /runtime/metrics` em JSON simples (sem Prometheus obrigatório
na v1). Opcional depois: formato Prometheus.

## 5. Traces

Não exigir OpenTelemetry na v1. Se já houver `traces.py` no invoke, um
span `mcp.runtime.call` com `server_id` + `tool_name` (sem args). Sem
novo backend de trace.

## 6. stderr do filho

Arquivo rotativo **dentro do container**, não no volume do repo.
Linhas passam por redactor (token `pat|secret|bearer` case-insensitive).
A API de health **não** devolve stderr.

## 7. Compatibilidade

MCP HTTP remoto continua só com os logs atuais de `services/mcp.py`.
Esta spec aplica-se a `transport_type=stdio`.
