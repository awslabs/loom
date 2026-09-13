# Spec 015 — Grafana e Rancher MCP (stdio local)

- **Status:** Aceita (local-runtime)
- **Data:** 2026-09-13
- **Implementa:** [ADR 0004](../adr/0004-local-mcp-runtime.md)
- **Não é** adapter no core. São templates + secrets, como [009](009-azure-devops-mcp-example.md).

## 1. Fluxo

```text
Loom (catálogo + ACL)
  → mcp-runtime
    → Grafana:  uvx --from mcp-grafana==1.4.1 mcp-grafana   (stdio)
    → Rancher:  npx rancher-mcp-server@0.9.1 …              (stdio)
      → APIs no host (kind/k3s): host.docker.internal
```

## 2. Templates

| id | command | param | secret (.env → child) |
|----|---------|-------|------------------------|
| `grafana` | `uvx` | `grafana_url` → env `GRAFANA_URL` | `GRAFANA_SERVICE_ACCOUNT_TOKEN` |
| `rancher` | `npx` | `rancher_server_url` (CLI) | `RANCHER_MCP_RANCHER_TOKEN` |

Opcional no `.env` / compose: `RANCHER_MCP_TLS_INSECURE=true` (TLS self-signed).
O `mcp-runtime` mapeia `host.docker.internal`, `grafana.local` e `rancher.local`
para `host-gateway` (Kind ingress no Windows em `:8080`).

## 3. Registro (operador)

1. Preencher secrets no `.env` na raiz do repo; recrear `mcp-runtime`.
2. MCP → New → `stdio` → template → URL do form → secret_ref env.
3. Refresh tools + `McpServerAccess` na persona do agente local.

Exemplos de URL (lab `C:\\work\\k8s`): `http://grafana.local:8080`,
`http://rancher.local:8080`. Alternativa genérica: `http://host.docker.internal:8080`
(pode falhar no Ingress se o `Host` não bater com o rule).

## 4. Fora de escopo

- MCP Grafana/Rancher em HTTP no catálogo Loom (alternativa futura)
- OAuth / tokens rotativos além do env local
