# Spec 019 — Segurança do MCP Hub

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md)
- **Depende de:** [016](016-mcp-hub-contract.md), [017](017-mcp-hub-session.md), [018](018-mcp-hub-allowlist.md), [008 — MCP local](008-local-mcp-security.md), [012 — agent-runtime](012-local-agent-runtime-security.md)

## 1. Trust boundary

```text
┌─ zona cliente MCP (IDE) ─────────────────────────────┐
│  só Hub session (opaca); nunca service tokens Loom   │
└──────────────────────────────────────────────────────┘
              │ Bearer hs_…
              ▼
┌─ zona mcp-hub (data plane) ──────────────────────────┐
│  introspect + allowlist via Loom                     │
│  proxy tools/call com MCP_RUNTIME_TOKEN / creds      │
│    de serviço já usadas pelo catálogo                │
│  SEM IdP, SEM JWT usuário, SEM Postgres              │
└──────────────────────────────────────────────────────┘
              │
              ▼
┌─ zona Loom (control plane) ──────────────────────────┐
│  IdP, mint/revoga, ACL, catálogo                     │
└──────────────────────────────────────────────────────┘
              │
              ▼
     mcp-runtime / MCP remoto (008 / net_guard)
```

## 2. Autenticação

| Interface | Credencial |
|-----------|------------|
| IDE → mcp-hub | Hub session (017) |
| mcp-hub → Loom introspect/allowlist | `MCP_HUB_SERVICE_TOKEN` |
| mcp-hub → mcp-runtime | `MCP_RUNTIME_TOKEN` (existente) |
| mcp-hub → MCP remoto | auth do `McpServer` (enrich no Loom; Hub recebe material **efêmero** só para o call ou Loom faz proxy — v1 preferir **Loom devolver endpoint + instrui Hub a usar service bearer já conhecido no compose** para stdio; remotos: Hub chama Loom BFF `POST /api/mcp/hub/proxy-call` **ou** recebe credencial de curta duração). |

**Decisão v1 (fail-closed, simples):**  
`tools/call` do Hub → **BFF Loom** `POST /api/mcp/hub/tools/call` com service token + `hub_session_id` + tool exposta + args. O Loom revalida allowlist e executa o call com o mesmo caminho seguro do admin/invoke (`_call_mcp` / mcp-runtime). O Hub **não** segura PAT nem API keys de remotos.

Isso reduz o Hub a: MCP wire + session + forward allowlisted calls ao control plane.

(Alternativa “Hub fala direto com mcp-runtime” só para stdio com token de serviço de compose, sem secrets de produto — permitida se documentada; remotos com secret **sempre** via BFF.)

## 3. Exposição de rede

| Interface | Bind v1 |
|-----------|---------|
| mcp-hub | `127.0.0.1:8790` no host + rede Docker |
| Proibido | `0.0.0.0` sem auth; Hub session na query string |

## 4. Fail-closed

- `MCP_HUB_SERVICE_TOKEN` vazio → Hub não sobe rotas MCP (ou recusa tudo).
- Introspect indisponível → 503/401, não “abrir” tools.
- Allowlist indisponível → list vazio ou erro; **não** fallback para todas as tools.
- Call fora da allowlist → negado antes do upstream.

## 5. Dados proibidos em log / erro / MCP response envelope

PAT, Hub session token, JWT, `Authorization`, API keys, stdout/stderr
brutos de filhos, prompts completos por default.

## 6. SSRF

Herdado do catálogo / `net_guard` do Loom. Hub não aceita `endpoint_url`
do cliente MCP — só `server_id` vindos da allowlist Loom.

## 7. Critérios de aceite

- [ ] Testes: JWT IdP no Hub → 401
- [ ] Testes: call sem allowlist → sem hit ao mcp-runtime (mock)
- [ ] Testes: service token Hub ausente → fail-closed
- [ ] Scan: nenhum secret de template no processo Hub além de tokens de serviço compose
