# MCP Hub

User-facing MCP facade (ADR 0007 / 0008 / 0010 / **0011** / **0012**).
Discovers MCP Clients on `initialize`. Admin grants catalog tools **per
IdP profile**. IDE auth = **OAuth against the active IdP** (Keycloak /
Microsoft Entra ID / …) — **no mint**, no `hs_…` Bearer in `mcp.json`.

```text
IDE (URL only)
  → 401 + Protected Resource Metadata
  → Active IdP (Keycloak / Microsoft Entra ID) Authorization Code + PKCE
  → Bearer access_token (aud=loom-mcp-hub)
  → mcp-hub validates JWKS → grants for user groups
      → Loom BFF materialize / tools/call (service token)
```

Host port loopback-only (`127.0.0.1:8790`). Health: `GET /health`.
PRM: `GET /.well-known/oauth-protected-resource`.
Store: **`MCP_HUB_DATABASE_URL`** (Postgres DB `mcp_hub`). JSON file
(`MCP_HUB_STORE_PATH`) is fallback only when DSN unset; if PG is empty and the
JSON file exists, clients are imported once at startup.

## Cursor `mcp.json`

```json
{
  "mcpServers": {
    "loom-hub": {
      "url": "http://127.0.0.1:8790/mcp",
      "auth": {
        "CLIENT_ID": "loom-mcp-hub",
        "scopes": ["openid", "profile"]
      }
    }
  }
}
```

Do **not** put `Authorization` headers. Use static `auth.CLIENT_ID` so Cursor
skips Dynamic Client Registration (some IdPs, e.g. Keycloak Trusted Hosts,
reject anonymous DCR). Redirect allowlist includes
`http://localhost:8787/callback`. After connect, configure profile grants
in Local runtime.

Local stack: if Keycloak was created before the Hub OAuth client existed,
either `make local.reset` (fresh import) or run
`scripts/ensure-kc-mcp-hub-client.sh`. With Microsoft Entra ID as the
active IdP, register an equivalent public PKCE app instead.

## Env

| Variable | Purpose |
|----------|---------|
| `MCP_HUB_SERVICE_TOKEN` | Hub ↔ Loom only |
| `LOOM_BACKEND_URL` | Hub → backend |
| `MCP_HUB_DATABASE_URL` | Postgres DSN for Hub store (dedicated DB `mcp_hub`) |
| `MCP_HUB_STORE_PATH` | Optional JSON path (fallback / migrate source) |
| `MCP_HUB_MIGRATE_JSON` | `force` to re-import JSON over PG |
| `MCP_HUB_RESOURCE` | Canonical resource URL (aud/resource check) |
| `MCP_HUB_OIDC_ISSUER` | Token `iss` (browser URL of the **active** IdP) |
| `MCP_HUB_OIDC_AUDIENCE` | Default `loom-mcp-hub` |
| `MCP_HUB_OIDC_JWKS_URL` | JWKS reachable from container (may differ from browser issuer host) |

Contract: `2026-09-hub-1`. Docs: ADR 0011 / 0012, specs 017 / 024 / 025.

## Package layout (hexagonal strangler)

```text
mcp_hub/
  domain/           # pure rules (access, naming, identity, errors)
  application/      # ports + wiring
  adapters/
    inbound/        # http_app (http.server)
    outbound/       # file_store, loom_http, oauth_jwks
  *.py              # compat shims (old import paths)
```

Wire protocol and env unchanged for MCP. Store default = Postgres via
`MCP_HUB_DATABASE_URL` (`HubStore` port). Fresh postgres volume runs
`etc/docker/postgres-init/02-mcp-hub-db.sql`. Existing volumes need reset or
manual `CREATE DATABASE mcp_hub`.
