# MCP Hub

User-facing MCP facade (ADR 0007 / specs 016–020). Aggregates Loom catalog
tools filtered by Hub session + `McpServerAccess`. Phase 1 = tools only.

```text
IDE / Cursor
  → POST http://127.0.0.1:8790/mcp   (Bearer <hub_session_token>)
    → this container
      → Loom BFF (introspect, allowlist, tools/call)
        → mcp-runtime / remote MCP
```

Host port is loopback-only (`127.0.0.1:8790`). Health: `GET /health` (no auth).

Transport is Streamable HTTP **POST/JSON only**: `GET /mcp` returns `405`
(not `404`) so Cursor skips the SSE listen stream.

Mint a Hub session from the Loom UI (**Local runtime → Mint Hub session**) after
IdP login. Use the returned `mcp_hub_url` and `hub_session_token` (`hs_…`) —
never the IdP JWT as the Hub Bearer.

## Cursor (IDE smoke test)

1. Ensure compose is up and `mcp-hub` is healthy (`curl http://127.0.0.1:8790/health`).
2. In Loom: **Local runtime → Mint Hub session**; copy **URL** and **Bearer**.
3. Cursor → **Settings → Tools & MCP → New MCP Server**, or edit
   `~/.cursor/mcp.json` / project `.cursor/mcp.json`.

   Prefer env interpolation so the Hub token is not committed (project
   `.cursor/mcp.json` is gitignored in this repo):

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

Set `LOOM_HUB_SESSION_TOKEN` to the minted `hs_…` value (shell / Windows user
env), then restart Cursor if needed. Inline Bearer also works for a quick
local test — never commit that file.

Prefer the exact URL from the mint response. Bearer must be `hs_…`, not the
IdP access token.

4. Save; `loom-hub` should show green and list only tools allowed via
   `McpServerAccess` on agents you can use.

When the session expires (default ~8h), mint again and update `Authorization`.
If Cursor reports OAuth / `POST /register` errors, the Bearer is usually
invalid or expired — refresh the Hub session first.

## Ops

Service token for Hub → Loom: `MCP_HUB_SERVICE_TOKEN` (compose overlay).
Contract version: `2026-09-hub-1`.
