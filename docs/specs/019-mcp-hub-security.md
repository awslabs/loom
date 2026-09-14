# Spec 019 — Segurança do MCP Hub

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-14 — OAuth IdP; mint removido ([ADR 0011](../adr/0011-mcp-hub-oauth-idp.md))
- **Implementa:** [ADR 0007](../adr/0007-mcp-hub.md), [ADR 0011](../adr/0011-mcp-hub-oauth-idp.md)
- **Depende de:** [016](016-mcp-hub-contract.md), [017](017-mcp-hub-session.md),
  [024](024-mcp-hub-oauth.md), [018](018-mcp-hub-allowlist.md),
  [008 — MCP local](008-local-mcp-security.md), [012 — agent-runtime](012-local-agent-runtime-security.md)

## 1. Trust boundary

```text
┌─ zona MCP Client (IDE) ──────────────────────────────┐
│  OAuth PKCE → access_token no secret store do client │
│  nunca service tokens Loom / MCP_HUB_SERVICE_TOKEN   │
└──────────────────────────────────────────────────────┘
              │ Bearer <access_token>  (024 / 017)
              ▼
┌─ zona mcp-hub (data plane) ──────────────────────────┐
│  valida JWT (JWKS IdP) + PRM/401                     │
│  allowlist por perfil; forward tools/call ao Loom    │
│  SEM mint; SEM aceitar hs_…                          │
└──────────────────────────────────────────────────────┘
              │ MCP_HUB_SERVICE_TOKEN + user context
              ▼
┌─ zona Loom (control plane) ──────────────────────────┐
│  catálogo, materialize, tools/call, ACL grants       │
│  IdP = Keycloak (AS do resource Hub)                 │
└──────────────────────────────────────────────────────┘
              │
              ▼
     mcp-runtime / MCP remoto (008 / net_guard)
```

## 2. Autenticação

| Interface | Credencial |
|-----------|------------|
| IDE → mcp-hub | Access token OAuth (017 / 024) |
| mcp-hub → Loom materialize/call | `MCP_HUB_SERVICE_TOKEN` + contexto user |
| mcp-hub → mcp-runtime | via BFF Loom (preferido) / `MCP_RUNTIME_TOKEN` só compose |
| Usuário → IdP | Authorization Code + PKCE (Keycloak) |

**Proibido:** mint UI; Bearer `hs_…`; JWT com audience do frontend Loom;
token na query string.

**Decisão v1:** `tools/call` Hub → BFF Loom; Hub não guarda PAT/API keys
de remotos.

## 3. Exposição de rede

| Interface | Bind v1 |
|-----------|---------|
| mcp-hub | `127.0.0.1:8790` no host + rede Docker |
| PRM / well-known | mesmo bind (necessário ao client OAuth) |
| Proibido | `0.0.0.0` sem auth; secrets em log |

## 4. Fail-closed

- `MCP_HUB_SERVICE_TOKEN` vazio → Hub não opera calls ao Loom.
- JWKS/issuer indisponível → 401/503; **não** abrir tools.
- Allowlist indisponível → list vazio ou erro; **não** todas as tools.
- Call fora da allowlist → negado antes do upstream.
- Token mint legado → 401.

## 5. Dados proibidos em log / erro / MCP envelope

PAT, access/refresh tokens, JWT completos, `Authorization`, API keys,
stdout/stderr brutos de filhos, prompts completos por default.

## 6. SSRF

Herdado do catálogo / `net_guard`. Hub não aceita `endpoint_url` do
cliente MCP — só entradas da allowlist.

## 7. Critérios de aceite

- [ ] JWT IdP com aud errada → 401
- [ ] `hs_…` → 401
- [ ] Call sem allowlist → sem hit ao mcp-runtime (mock)
- [ ] Service token Hub ausente → fail-closed para BFF
- [ ] Scan: nenhum secret de template no processo Hub além de tokens de serviço compose
