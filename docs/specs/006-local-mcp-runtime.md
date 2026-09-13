# Spec 006 — Local MCP Runtime

- **Status:** Rascunho
- **Data:** 2026-09-12
- **Implementa:** [ADR 0004](../adr/0004-local-mcp-runtime.md)
- **Depende de:** [005 — análise](005-existing-mcp-architecture.md), [007 — registro](007-local-mcp-registration.md)

## 1. Objetivo

Um supervisor de processos que:

- sobe MCPs locais a partir de **templates**;
- fala MCP em stdio com o filho;
- expõe **streamable HTTP interno** com o contrato que `_call_mcp` e o
  runtime Strands já usam;
- aplica IdentityContext + `McpServerAccess` em `tools/call`.

Não é um catálogo novo. Cada instância corresponde a um `McpServer` com
`transport_type=stdio`.

## 2. Onde vive

Serviço compose `mcp-runtime` (v1). O backend Loom chama
`http://mcp-runtime:8787` na rede Docker. Porta no host: `127.0.0.1:8787`.

O processo FastAPI **não** faz `Popen` do MCP. Isola crash, env e secrets.

Pacote sugerido: `etc/docker/mcp-runtime/` (mesmo padrão do cursor-adapter),
**ou** `backend/app/services/mcp_runtime/` se a v1 for só in-process — a ADR
rejeita in-process; usar o serviço.

## 3. Interfaces (Python, type hints)

```text
register(server_id, template_id, params, secret_refs) → Handle
start(server_id) → State
initialize(server_id) → InitializeResult
list_tools(server_id, identity) → list[Tool]
call_tool(server_id, name, arguments, identity) → CallResult
stop(server_id) → State
restart(server_id) → State
health(server_id) → Health
```

`Handle` é o id do `McpServer`. O runtime persiste estado em memória + o
status no catálogo via callback HTTP ao backend (`PATCH` interno) ou o
backend consulta `GET /runtime/servers/{id}/health`.

Fachada MCP (o que o agente vê):

```text
POST http://mcp-runtime:8787/s/{server_id}/mcp
Authorization: Bearer <token Loom ou service token do backend>
```

JSON-RPC: `initialize`, `tools/list`, `tools/call` — protocolo `2025-03-26`,
igual a `services/mcp.py`.

## 4. Máquina de estados

```text
REGISTERED
    → STARTING
        → READY          (initialize ok, tools/list ok)
            → RUNNING    (pelo menos um call, ou READY e healthy)
        → FAILED
    → STOPPING → STOPPED

RUNNING / READY → FAILED
FAILED → RESTARTING → STARTING
STOPPING → STOPPED
```

Mapear para `McpServer.status` existente:

| Estado runtime | `McpServer.status` |
| --- | --- |
| REGISTERED, STOPPED | `inactive` |
| STARTING, RESTARTING | `active` (ou `error` se falhar) |
| READY, RUNNING | `active` |
| FAILED | `error` |

Não inventar coluna de status se `status` + um JSON `runtime_state` em
config bastar. Preferir coluna texto `runtime_state` nova (migração
`_migrate_add_columns`).

## 5. Transporte stdio

- stdin/stdout: JSON-RPC MCP, uma mensagem por linha (MCP stdio).
- stderr: só log (nunca ecoar para o cliente). Redigir se parecer secret.
- Um filho por `server_id`. Sem multiplexar vários servidores no mesmo
  processo, salvo o template declarar *shared* (v1: não).
- `initialize` após o spawn; timeout de startup configurável no template
  (default 30s).

## 6. Processo

| Evento | Comportamento |
| --- | --- |
| start | `Popen` com cwd do template, env = secrets resolvidos + params não secretos |
| exit ≠ 0 | FAILED; backoff restart (max N do template, default 3) |
| timeout de call | mata o request, não necessariamente o processo |
| timeout de idle | opcional no template; v1: não mata por idle |
| stop | SIGTERM, espera 5s, SIGKILL |
| cleanup | stop de todos no shutdown do serviço |

Concurrency: uma fila de JSON-RPC por processo (stdio é half-duplex na
prática). Calls paralelos no mesmo server_id **serializam**.

## 7. Health

`GET /runtime/servers/{id}/health`:

```json
{
  "state": "READY",
  "pid": 12,
  "restarts": 0,
  "started_at": "...",
  "last_error_code": null
}
```

Sem secret, sem stdout bruto.

## 8. Compatibilidade com MCP remoto

`_call_mcp` ganha branch `stdio`: se `transport_type==stdio`, o backend
**não** abre stdio — chama a fachada HTTP do runtime (como se fosse
`streamable_http` interno). O runtime Strands/ADK também usa essa URL.
MCPs `sse` / `streamable_http` existentes não passam pelo supervisor.
