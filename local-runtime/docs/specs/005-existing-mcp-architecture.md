# Spec 005 — Análise da arquitetura MCP existente no Loom

- **Status:** Análise (entrada para ADR 0004)
- **Data:** 2026-09-12
- **Relacionada a:** [ADR 0004](../adr/0004-local-mcp-runtime.md)

Esta spec **não implementa** nada. Documenta o que o repositório já faz, para o
runtime de MCP local estender o catálogo atual em vez de criar um segundo.

## 1. Há uma única arquitetura MCP

```text
Catálogo (mcp_servers / mcp_tools / mcp_server_access)
        │
        ├── Control plane FastAPI  (/api/mcp/servers)
        │     test-connection, tools/refresh, tools/invoke, connectors
        │
        ├── Deploy-time
        │     AGENT_CONFIG_JSON.integrations.mcp_servers[]
        │     + credential provider AgentCore (OAuth2)
        │     + harness remote_mcp
        │
        └── Invoke-time
              Chat "Connectors" → connector_ids → dynamic_mcp_servers
              → AgentCore Runtime (Strands/ADK) ou Harness
```

Não existe um segundo *bus* de MCP. Qualquer MCP local deve **entrar nesse
catálogo** e, para o agente, continuar parecendo um servidor HTTP.

## 2. Registro

Modelo `McpServer` (`backend/app/models/mcp.py`):

| Campo | Valores hoje |
| --- | --- |
| `transport_type` | `sse` \| `streamable_http` |
| `auth_type` | `none` \| `oauth2` \| `api_key` |
| `status` | `active` \| `inactive` \| `error` |
| `endpoint_url` | obrigatório (URL HTTP) |
| `delegation_mode` | `m2m` \| `obo` |

Tools em cache: `McpTool`. Acesso por agente: `McpServerAccess`
(`all_tools` \| `selected_tools` + `allowed_tool_names`, `persona_id` = id do
agente).

API: `backend/app/routers/mcp.py`. UI: `McpServersPage`, `McpServerForm`,
`McpAccessControl`, conectores no `ChatPage`.

**Não há `stdio` no repositório** (zero ocorrências).

## 3. Descoberta

- Lista: `GET /api/mcp/servers`
- Conectores de invoke: `GET /api/mcp/servers/connectors` (usuário `t-user`
  só vê `APPROVED` ou sem registry)
- Tools ao vivo: `POST /{id}/tools/refresh` → JSON-RPC `tools/list`
- Registry AWS opcional: só `APPROVED` no deploy se o registry estiver ligado

## 4. Transporte

| Transporte | Backend admin | Runtime Strands/ADK | Harness |
| --- | --- | --- | --- |
| `streamable_http` | sim | sim | `remote_mcp` |
| `sse` | sim | **não** (aviso e skip) | URL apenas |
| `stdio` | **não** | **não** | **não** |

O cliente canônico do control plane é `backend/app/services/mcp.py`
(`_call_mcp`). O runtime canônico é
`agents/strands_agent/src/integrations/mcp_client.py` (só streamable HTTP).

## 5. Autenticação e autorização

Autenticação de MCP remoto: `none`, `api_key` (Secrets Manager
`loom/mcp/{name}/…`) ou `oauth2` (M2M / OBO via Identity AgentCore no
runtime; token direto no backend admin).

Autorização de plataforma: scopes `mcp:read` / `mcp:write` via `UserInfo`
(já independente de Keycloak/Entra — ADR 0001).

**Lacuna:** `McpServerAccess` é editável na UI e **não é aplicado** em
`invocations.py`, no handler do agente nem em `list_connectors`. Deny-by-default
está só na documentação.

## 6. Como o agente chega no MCP

Agentes `deploy` / `harness` no AgentCore falam HTTP com o MCP. Agentes
`source=local` (`local_invoke.py`) **não têm caminho MCP** — só LiteLLM.

Dois modos de consumo (manter):

1. **Deploy-integrated** — MCP sempre ligado no `AGENT_CONFIG_JSON`
2. **Invoke connector** — toggle no chat, chave por usuário, OBO

## 7. Secrets hoje

`backend/app/services/secrets.py` é **acoplado ao AWS Secrets Manager**
(`store_secret` / `get_secret` + região). Chaves MCP de admin/usuário já usam
esse caminho. OAuth2 client secret ainda mora em coluna da tabela.

Não existe `SecretReference` genérico nem backend `env` para o stack local.

## 8. Identidade já abstrata

`UserInfo` (`sub`, `username`, `groups`, `scopes`, `idp_type`, `actor_id`) é o
contexto que o runtime deve receber. Não criar um tipo paralelo que revalide
JWT de um IdP.

## 9. Observabilidade hoje

Logs de logger no serviço MCP; auditoria frontend (`trackAction` categoria
`mcp`); tool-use no stream de invoke. **Não há** spans MCP em `traces.py` nem
métricas de processo.

## 10. Pontos de extensão (usar, não duplicar)

1. `transport_type` no catálogo + `_call_mcp()`
2. Snapshot `integrations.mcp_servers[]` no deploy
3. `dynamic_mcp_servers` no invoke
4. `McpServerAccess` (passar a **enforçar**)
5. `UserInfo` como IdentityContext
6. `net_guard` para qualquer HTTP que o runtime exponha
7. Formulário/UI de MCP existentes

## 11. Implicação para MCP local

O agente (AgentCore) **não sabe stdio**. A fachada correta é: o Local MCP
Runtime fala stdio com o filho e **apresenta streamable HTTP interno** com a
mesma forma que o catálogo já espera. O `endpoint_url` do `McpServer` stdio é
gerado (URL interna do runtime), não digitado pelo operador.

Limitação honesta: um processo `npx` na máquina do desenvolvedor **não é
alcançável** por um runtime AgentCore na AWS. A v1 cobre o stack local
(compose + control plane + agentes `source=local` / invoke mediado). Agente
na AWS continua usando MCP HTTP remoto, a menos que o mesmo runtime rode
como sidecar no ambiente do agente (fora desta iteração).
