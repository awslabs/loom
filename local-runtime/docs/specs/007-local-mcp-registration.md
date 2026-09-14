# Spec 007 — Registro de MCP local (templates)

- **Status:** Rascunho
- **Data:** 2026-09-12
- **Implementa:** [ADR 0004](../adr/0004-local-mcp-runtime.md)

## 1. Objetivo

Encaixar MCP stdio no **mesmo** `POST /api/mcp/servers` / `McpServerForm`,
sem YAML paralelo e sem `command` livre.

## 2. Extensão do modelo existente

Novos campos em `McpServer` (migração `_migrate_add_columns`):

| Campo | Tipo | Uso |
| --- | --- | --- |
| `transport_type` | inclui `stdio` | já existe; só ampliar o enum |
| `template_id` | VARCHAR nullable | obrigatório se stdio |
| `template_params` | TEXT JSON | parâmetros não secretos (org, projeto) |
| `secret_refs` | TEXT JSON | lista de `SecretReference` |
| `runtime_state` | VARCHAR | ver spec 006 |
| `endpoint_url` | nullable se stdio | preenchido pelo runtime após register |

`endpoint_url` no create stdio: omitir ou mandar `""`. O backend grava
`http://mcp-runtime:8787/s/{id}/mcp` depois do insert.

`auth_type` para stdio: `loom` (o chamador precisa de token Loom). Não usar
`none` na fachada. O **filho** recebe secrets por env, não por OAuth2 do MCP.

Não criar tabela `local_mcp_servers`.

## 3. Templates (allowlist no repo)

Diretório `etc/mcp-templates/*.yaml` (ou JSON). Só o que está commitado
(ou allowlist de Settings) pode ser escolhido.

Esquema de um template:

```yaml
id: azure-devops
display_name: Azure DevOps
command: npx
args:
  - "-y"
  - "@azure-devops/mcp"
  - "{{params.organization}}"
params_schema:
  organization:
    type: string
    pattern: "^[A-Za-z0-9][A-Za-z0-9-]*$"
secrets:
  - name: AZURE_DEVOPS_PAT
    env: AZURE_DEVOPS_EXT_PAT   # nome injetado no filho; ajustar ao pacote real
startup_timeout_s: 45
max_restarts: 3
```

Regras:

- `command` só pode ser um dos binários allowlisted globais:
  `npx`, `uvx`, `python`, `python3`, `node` (lista no template **e** no
  runtime; interseção).
- `args` são estáticos + placeholders `{{params.*}}` validados pelo
  `params_schema`. Sem shell. Sem `args` vindos crus do cliente.
- Novo MCP no catálogo = novo arquivo de template + review. Zero mudança no
  supervisor.

`GET /api/mcp/templates` lista templates para o formulário (`mcp:read`).

## 4. Create request (stdio)

Estender `McpServerCreateRequest`:

```text
transport_type: "stdio"
template_id: "azure-devops"
template_params: { "organization": "minha-org" }
secret_refs: [
  { "name": "AZURE_DEVOPS_PAT", "backend": "env", "ref": "AZURE_DEVOPS_PAT" }
]
name: "Azure DevOps"
```

Sem `endpoint_url`. Sem `command`. Sem `args`.

Fluxo:

1. Validar `template_id` na allowlist
2. Validar params contra o schema
3. Inserir `McpServer`
4. `runtime.register` + `start` + `initialize` + `list_tools` → popular `mcp_tools`
5. Gravar `endpoint_url` interno

Falha no start: registro permanece `runtime_state=FAILED`, `status=error`;
não apagar a linha (o admin corrige secret/param e dá restart).

## 5. Acesso por agente (já existe)

Continuar `PUT /api/mcp/servers/{id}/access` com `McpServerAccess`.
Na v1 **enforçar** no `call_tool` e ao montar `dynamic_mcp_servers` /
conectores: se o agente não tem regra, **deny**.

`allowed_agents` do YAML de exemplo do pedido **não** vira coluna nova —
é `persona_id` nas rules.

`allowed_tools` do YAML = `access_level=selected_tools` +
`allowed_tool_names`.

## 6. Snapshot de deploy / invoke

O JSON em `integrations.mcp_servers[]` para um MCP stdio é o de sempre,
com `transport: streamable_http` e `endpoint_url` da fachada (o agente não
vê `stdio`). `auth.type` na fachada: bearer do usuário ou do backend,
documentado como `loom`.

Agentes na AWS que não alcançam `mcp-runtime` **não** devem receber esse
MCP no snapshot de deploy (filtrar `transport_type=stdio` no
`_deploy_agent_background`). No compose local, o backend e o runtime
compartilham a rede.

## 7. UI

`McpServerForm`: se transporte = stdio, esconder URL; mostrar dropdown de
templates + campos do `params_schema` + referências de secret. Reutilizar
a página e o access control.
