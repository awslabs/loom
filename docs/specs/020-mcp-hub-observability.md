# Spec 020 — Observabilidade do MCP Hub

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md)
- **Depende de:** [016](016-mcp-hub-contract.md), [017](017-mcp-hub-session.md), [010 — obs MCP](010-local-mcp-observability.md), [013 — obs agent-runtime](013-local-agent-runtime-observability.md)

## 1. Princípio

Correlacionar Hub session → subject → tool → server sem APM novo.
Logger estruturado do stack local. **Nunca** logar tokens nem args
completos por default.

## 2. IDs de correlação

Todo log do mcp-hub / BFF Hub:

```text
hub_session_id
subject_hash     (sha256 truncado do sub; não logar sub em claro em prod)
request_id       (uuid por tools/list ou tools/call)
server_id        (nullable em list)
tool_name        (nome exposto)
original_tool    (nullable)
contract_version
```

## 3. Eventos

### Sessão

```text
event=mcp_hub_session
phase=mint|introspect|revoke|expire|reject
hub_session_id
subject_hash
ttl_s
active           (introspect)
```

### tools/list

```text
event=mcp_hub_tools_list
hub_session_id
subject_hash
server_count
tool_count
duration_ms
cache_hit
```

### tools/call

```text
event=mcp_hub_tools_call
hub_session_id
subject_hash
server_id
tool_name
original_tool
phase=start|end|denied|error
duration_ms
error_code       (nullable; sem detalhe de secret)
```

## 4. Métricas (v1 opcional)

Contadores: `hub_sessions_active`, `hub_tools_list_total`,
`hub_tools_call_total{result=ok|denied|error}`.
Histograma: latência list/call.

## 5. Critérios de aceite

- [ ] Call denied aparece com `phase=denied` e sem args
- [ ] Token `hs_…` não ocorre em arquivo de log nos testes
- [ ] `hub_session_id` correlaciona mint (backend) e call (hub/BFF)
