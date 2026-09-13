# MCP Hub

User-facing MCP facade (ADR 0007 / 0008). Discovers MCP Clients on
`initialize` (`clientInfo`), deny-by-default until admin enables + grants
catalog tools. Phase 1 = tools only.

```text
IDE
  → POST http://127.0.0.1:8790/mcp   (Bearer <hub_session_token>)
    → mcp-hub (discovery + allowlist from grants)
      → Loom BFF materialize / tools/call
        → mcp-runtime / remote MCP
```

Host port loopback-only (`127.0.0.1:8790`). Health: `GET /health`.
Store: `MCP_HUB_STORE_PATH` (default `/data/hub_clients.json`).

Transport: Streamable HTTP **POST/JSON**; `GET /mcp` → `405 Allow: POST`.

## Flow

1. Loom UI **Local runtime → Mint Hub session** (user auth only).
2. Configure IDE with URL + Bearer; connect once.
3. Hub registers MCP Client (`discovered`).
4. In Local runtime: **Enable** client + **Save grant** (server / tools).
5. IDE `tools/list` shows granted tools only.

## Cursor `mcp.json`

```json
{
  "mcpServers": {
    "loom-hub": {
      "url": "http://127.0.0.1:8790/mcp",
      "headers": {
        "Authorization": "Bearer ${env:LOOM_HUB_SESSION_TOKEN}"
      }
    }
  }
}
```

Bearer must be `hs_…` (Hub session), not IdP JWT. Project `.cursor/mcp.json`
is gitignored.

## Ops

- `MCP_HUB_SERVICE_TOKEN` — Hub ↔ Loom
- `LOOM_BACKEND_URL` — Hub → backend
- Admin APIs on Hub `/v1/clients*` (service token); Loom proxies at
  `/api/ext/local-runtime/mcp-clients*`
- Contract: `2026-09-hub-1`
