# Spec 015 — Grafana e Rancher MCP (stdio local)

- **Status:** Aceita (local-runtime)
- **Data:** 2026-09-13
- **Atualizado:** 2026-09-13 — Rancher via rede Docker `kind` + NodePort 30080
- **Implementa:** [ADR 0004](../adr/0004-local-mcp-runtime.md)
- **Não é** adapter no core. São templates + secrets, como [009](009-azure-devops-mcp-example.md).

## 1. Fluxo

```text
Loom (catálogo + ACL)
  → mcp-runtime (rede compose + rede Docker externa `kind`)
    → Grafana:  uvx mcp-grafana     → http://grafana.local:8080 (host-gateway)
    → Rancher:  npx rancher-mcp-server → http://kind-control-plane:30080
```

## 2. Templates

| id | command | param | secret (.env → child) |
|----|---------|-------|------------------------|
| `grafana` | `uvx` | `grafana_url` → env `GRAFANA_URL` | `GRAFANA_SERVICE_ACCOUNT_TOKEN` |
| `rancher` | `npx` | `rancher_server_url` (CLI) | `RANCHER_MCP_RANCHER_TOKEN` |

### URLs Rancher (contrato lab `C:\\work\\k8s`)

| Onde | URL |
|------|-----|
| Outro Compose/Docker (**Loom**) | `http://kind-control-plane:30080` |
| Stdio no WSL/Windows | `http://rancher.local:8080` |

O overlay anexa `mcp-runtime` à rede externa `kind`. O entrypoint resolve
`kind-control-plane` e aliasa `rancher.local` no `/etc/hosts` do container
(para o Ingress bater o `Host` quando útil). Prefira a URL da tabela Loom.

Não use `:8443` / port-forward a partir do `mcp-runtime` (loopback do host).

## 3. Registro (operador)

1. Kind rodando (`docker network ls` mostra `kind`).
2. Secrets no `.env`; recreate `mcp-runtime`.
3. MCP → New → `stdio` → template `rancher` →
   `rancher_server_url=http://kind-control-plane:30080`.
4. Refresh tools + `McpServerAccess`.

Grafana (lab): `http://grafana.local:8080`.

## 4. Fora de escopo

- MCP Grafana/Rancher em HTTP no catálogo Loom (alternativa futura)
- OAuth / tokens rotativos além do env local
- Alterar o repositório `C:\\work\\k8s`
