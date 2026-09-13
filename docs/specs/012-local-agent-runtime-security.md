# Spec 012 — Segurança do Local Agent Runtime

- **Status:** Implementado (baseline M1); telemetria/redactor avançados ainda parciais
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — BFF + service tokens; ensure_stdio; planner sem MCP no SDK
- **Implementa:** [ADR 0005](../adr/0005-local-agent-runtime.md)
- **Depende de:** [011 — contrato](011-local-agent-runtime-contract.md), [008 — segurança MCP](008-local-mcp-security.md)

## 1. Trust boundary

```text
┌─ zona Loom (authn/authz) ─────────────────────────────────┐
│  IdP → UserInfo → FastAPI                                 │
│    monta payload + McpServerAccess + ensure_stdio_ready   │
│    enrich service_bearer (nunca JWT do usuário no MCP)    │
│    → agent-runtime (Bearer AGENT_RUNTIME_TOKEN)           │
└───────────────────────────────────────────────────────────┘
              │ só invoke já autorizado + allowlists
              ▼
┌─ zona agent-runtime ──────────────────────────────────────┐
│  loop do agente; chama LiteLLM e MCP HTTP                 │
│  sem JWT do usuário; sem Postgres; sem Keycloak           │
└───────────────────────────────────────────────────────────┘
              │
              ├─► LiteLLM (master/virtual key do proxy)
              └─► mcp-runtime / MCP remoto (service token / api_key)
                        │
                        ▼
                 ┌─ zona filho MCP (ADR 0004) ─┐
                 │ PAT só no env do filho      │
                 └─────────────────────────────┘
```

O agent-runtime **não** valida o IdP. Authz User → Agent → MCP → Tool
permanece no control plane (e no mcp-runtime para stdio).

## 2. Autenticação de serviço

- Variável `AGENT_RUNTIME_TOKEN` (compose `.env`; nunca no git).
- Header: `Authorization: Bearer <token>`.
- Token vazio ⇒ runtime **fail-closed** (recusa todo `/v1/*`).
- Não reutilizar o JWT do usuário como token de serviço.
- Pode coincidir com o valor de `MCP_RUNTIME_TOKEN` no dev local; em
  ambientes sérios, tokens distintos.

## 3. Exposição de rede

| Interface | Bind v1 |
| --- | --- |
| agent-runtime HTTP | `127.0.0.1` no host + rede Docker interna |
| LiteLLM | já existente |
| mcp-runtime | já `127.0.0.1:8787` |

Proibido: publicar `0.0.0.0` sem autenticação. Anônimo da internet não
alcança o loop do agente nem o stdio.

## 4. Isolamento de sessão

v1 mínima:

- no máximo **uma sessão ativa por `session_id`**;
- hard limit global `AGENT_RUNTIME_MAX_SESSIONS` (default baixo, ex. 4);
- timeout `options.timeout_s` (default 300);
- `max_tool_rounds` (default 20) — anti-loop;
- ao cancelar/timeout: terminar o worker da sessão.

Preferência: processo ou thread isolada por sessão. Container-por-sessão
é evolução (como `runtime.kind=container` no MCP). Crash de uma sessão
não derruba o listener HTTP do agent-runtime nem o FastAPI.

## 5. Segredos

| Segredo | Onde fica | O que o agent-runtime vê |
| --- | --- | --- |
| JWT do usuário | só no backend | nada |
| `AGENT_RUNTIME_TOKEN` | env do backend + agent-runtime | valor |
| `MCP_RUNTIME_TOKEN` | env; no payload como bearer da fachada | valor no header outbound |
| `AZURE_DEVOPS_PAT` | env do **mcp-runtime** | **nada** |
| LiteLLM master/virtual key | env do agent-runtime ou injetada pelo backend no invoke | só a chave do proxy |

Nunca logar tokens, PAT, Authorization headers ou corpos de tool que
possam ecoar secret.

## 6. Defesa em profundidade (MCP)

Mesmo com payload já filtrado:

1. Ao chamar `tools/call`, se `allowed_tools` for lista, rejeitar nome
   fora dela (`mcp_denied`) **sem** chamar o MCP.
2. Encaminhar `X-Loom-Allowed-Tools` / headers de identity que o
   mcp-runtime já entende (ADR 0004 / spec 008).
3. Não seguir redirects arbitrários para hosts fora da allowlist de
   endpoints do payload (v1: só URLs presentes em `mcp_servers`).

## 7. O que o runtime não pode fazer

- Abrir shell / `eval` a partir do prompt.
- Aceitar `command` ou path de agente enviado pelo cliente.
- Persistir filesystem do workspace do usuário sem opt-in explícito
  (fora de escopo v1; Cursor workspace fica no cursor-adapter).
- Chamar AgentCore ou AWS APIs.

## 8. Relação com `net_guard` e auth bypass

Esta spec **não** altera `net_guard` nem
`LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV`. O bypass fail-closed do backend
permanece. O agent-runtime é outro trust zone, autenticado por token de
serviço.

## 9. Critérios de segurança (aceite)

- Request sem Bearer → 401
- Token errado → 401
- Tool não allowlisted → não chega ao mcp-runtime
- PAT ausente dos logs do agent-runtime e do SSE
- Derrubar o worker de uma sessão não mata o container do backend Loom
