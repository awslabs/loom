# 9. Identificação e discovery do MCP Client no Hub

- **Status:** Proposta
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — `clientInfo` dispara registro na extensão (ADR 0008)
- **Decisores:** Mantenedores da plataforma / extensão local
- **Relacionada a:**
  [ADR 0007](0007-mcp-hub.md),
  [ADR 0008 — MCP Clients](0008-mcp-hub-clients.md),
  [Spec 022](../specs/022-mcp-hub-client-identification.md)

## Problema

O Hub precisa saber **qual produto** conectou, sem catálogo a priori de
nomes. O protocolo MCP envia `clientInfo` no `initialize` — spoofável,
mas suficiente para **descobrir e registrar** um MCP Client e deixar o
admin liberar tools.

## Decisão

| Plano | Fonte | Anti-spoof? | Uso |
|-------|--------|-------------|-----|
| **A — Declarada / discovery** | `initialize.clientInfo` | Não | UPSERT MCP Client; logs; chave de grants |
| **B — User autenticado** | Hub session `hs_…` | Sim (IdP + token) | Acesso ao Hub |
| **C — Policy** | `enabled` + grants **por perfil IdP** (ADR 0010) | Sim (admin) | Allowlist |

Fluxo no Hub `initialize`:

1. Validar Bearer (sessão user ativa).
2. Ler `clientInfo` → normalizar slug/family (spec 022).
3. UPSERT MCP Client na extensão (`status=discovered` se novo).
4. Associar `hub_session_id` → `mcp_client_slug` (memória/store).
5. Responder `serverInfo` como hoje.

**Não** auto-enable nem auto-grant. Sem `clientInfo` → client
`unknown` / slug estável por sessão (detalhe 022) — ainda deny tools até
admin agir.

Authz de tools = C, não A sozinho. OAuth por produto (futuro) pode
promover A→prova de app.

## Spec

[022](../specs/022-mcp-hub-client-identification.md)
