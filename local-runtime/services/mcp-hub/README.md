# MCP Hub

User-facing MCP facade (ADR 0007 / 0008 / 0010 / **0011**). Discovers MCP
Clients on `initialize`. Admin grants catalog tools **per IdP profile**.
IDE auth = **OAuth IdP** (Keycloak) — **no mint**, no `hs_…` Bearer in
`mcp.json`.

```text
IDE (URL only)
  → 401 + Protected Resource Metadata
  → Keycloak Authorization Code + PKCE
  → Bearer access_token (aud=loom-mcp-hub)
  → mcp-hub validates JWKS → grants for user groups
      → Loom BFF materialize / tools/call (service token)
```

Host port loopback-only (`127.0.0.1:8790`). Health: `GET /health`.
PRM: `GET /.well-known/oauth-protected-resource`.
Store: `MCP_HUB_STORE_PATH` (default `/data/hub_clients.json`).

## Cursor `mcp.json`

```json
{
  "mcpServers": {
    "loom-hub": {
      "url": "http://127.0.0.1:8790/mcp"
    }
  }
}
```

Do **not** put `Authorization` headers. Cursor runs OAuth against Keycloak
client `loom-mcp-hub` (realm import). After connect, configure profile
grants in Local runtime.

If Keycloak was created before this client existed, either
`make local.reset` (fresh import) or run
`scripts/ensure-kc-mcp-hub-client.sh` against the running stack.

## Env

| Variable | Purpose |
|----------|---------|
| `MCP_HUB_SERVICE_TOKEN` | Hub ↔ Loom only |
| `LOOM_BACKEND_URL` | Hub → backend |
| `MCP_HUB_RESOURCE` | Canonical resource URL (aud/resource check) |
| `MCP_HUB_OIDC_ISSUER` | Token `iss` (browser Keycloak URL) |
| `MCP_HUB_OIDC_AUDIENCE` | Default `loom-mcp-hub` |
| `MCP_HUB_OIDC_JWKS_URL` | JWKS reachable from container |

Contract: `2026-09-hub-1`. Docs: ADR 0011, specs 017 / 024.
