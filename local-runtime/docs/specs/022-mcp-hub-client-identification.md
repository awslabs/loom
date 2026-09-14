# Spec 022 — Identificação e discovery do MCP Client no Hub

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Implementa:** [ADR 0009](../adr/0009-mcp-hub-client-identification.md), [ADR 0008](../adr/0008-mcp-hub-clients.md)
- **Depende de:** [016](016-mcp-hub-contract.md), [017](017-mcp-hub-session.md), [020](020-mcp-hub-observability.md), [021](021-mcp-hub-clients.md)

## 1. Objetivo

No `initialize` do **mcp-hub**: capturar `clientInfo`, **registrar** o
MCP Client na extensão e ligar a sessão Hub a esse client. Distinguir
declaração (spoofável) de user autenticado e de policy (admin grants).

## 2. Baseline

Hub ignora `params.clientInfo` hoje. Downstream continua `loom` /
`loom-mcp-runtime`.

## 3. Handshake

```text
POST /mcp  Authorization: Bearer hs_…
{ "method": "initialize", "params": {
    "protocolVersion": "…",
    "clientInfo": { "name": "…", "version": "…" }
}}

Hub:
  1. introspect hs_… → active?
  2. slug = normalize(clientInfo.name)   # §4
  3. UPSERT MCP Client (021) status=discovered se novo
  4. bind hub_session_id → slug
  5. log 020: subject_hash, hub_session_id, slug, declared_*
  6. return serverInfo loom-mcp-hub
```

Sem `clientInfo` / name vazio: slug = `unknown` (único global) **ou**
`unknown-<short-hash(hub_session_id)>` — preferência v1: um client
`unknown` compartilhado (admin decide se libera tools genéricas). Spec
de implementação escolhe e documenta; default recomendado = **`unknown`**
único para simplificar.

## 4. Normalização de slug

```text
raw = clientInfo.name.trim().lower()
slug = regex replace [^a-z0-9]+ → '-' ; trim '-' ; max 64 chars
se vazio → unknown
```

`declared_family`: tabela opcional de aliases (substring) para UI
(`cursor`, `claude-code`, …); não bloqueia discovery de nomes novos.

## 5. Planos

| Plano | Fonte | Autoriza tools? |
|-------|--------|-----------------|
| A Declarada | `clientInfo` → slug / UPSERT | Não sozinha |
| B User | Hub session | Acesso ao Hub |
| C Policy | enabled + grants | **Sim** |

## 6. Fluxos

### Cursor
Mint user → Cursor `initialize` com seu `clientInfo.name` → client
`discovered` → admin enable+grants → tools aparecem.

### Claude Code
Idem; outro name → outro slug/bucket. Token do user + name spoofado
como Cursor só herda grants se admin tiver enabled o slug “cursor…”.

### Loom
Mint na UI sem MCP. Teste Loom→Hub com `clientInfo.name=loom` → client
`loom`. Chat Loom não usa Hub.

## 7. Spoofing (explícito)

`clientInfo` é declarativo. Mitigação v1: **deny-by-default** até admin
enable. Mitigação futura: OAuth `client_id` → slug confiável.

## 8. Critérios de aceite

- [ ] initialize faz UPSERT + bind sessão
- [ ] Novo client sem tools até enable
- [ ] Allowlist usa slug bound, não mint
- [ ] Spoof de name não concede tools sem grant admin
- [ ] Logs correlacionam session + slug + declared
