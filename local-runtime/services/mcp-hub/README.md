# MCP Hub

User-facing MCP facade (ADR 0007 / 0008 / 0010). Discovers MCP Clients
(channels) on `initialize` (`clientInfo`). Admin grants catalog tools
**per IdP profile** (`g-users-*` / `g-admins-*`), All Tools or Selected
Tools. At `tools/list` the Hub filters grants to the session user's
profile before materializing. Phase 1 = tools only.

```text
IDE
  → POST http://127.0.0.1:8790/mcp   (Bearer <hub_session_token>)
    → mcp-hub
         resolve canal (client slug)
         resolve perfil (session.groups → grants)
         → Loom BFF materialize / tools/call
           → mcp-runtime / remote MCP
```

Host port loopback-only (`127.0.0.1:8790`). Health: `GET /health`.
Store: `MCP_HUB_STORE_PATH` (default `/data/hub_clients.json`).

Transport: Streamable HTTP **POST/JSON**; `GET /mcp` → `405 Allow: POST`.

## Flow

1. Loom UI **Local runtime → Mint Hub session** (user auth; groups on session).
2. Configure IDE with URL + Bearer; connect once (registers channel).
3. Local runtime: select **channel** → select **IdP profile** (required) →
   Hub loads that profile’s grants on demand → Save (All / Selected).
4. Enable channel when ready.
5. IDE `tools/list` shows only tools granted to **that user's profile**
   on that channel.

List clients returns summaries (`granted_profiles`, `grant_count`) without
embedding all grants. On-demand:

```text
GET/PUT /v1/clients/{slug}/profile-grants?group=… | { group, grants }
```

Empty profile → `200` + `grants: []`. Plugin via
`/api/ext/local-runtime/mcp-clients/{slug}/profile-grants`.

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
is gitignored. After changing profile grants, fully quit Cursor to refresh
cached tool lists.

## Ops

- `MCP_HUB_SERVICE_TOKEN` — Hub ↔ Loom
- `LOOM_BACKEND_URL` — Hub → backend
- Admin APIs on Hub `/v1/clients*` (service token); Loom proxies at
  `/api/ext/local-runtime/mcp-clients*`
- Contract: `2026-09-hub-1`
- Docs: ADR 0010, specs 018 / 021 / 023
