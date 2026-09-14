# Arquitetura (C4 + modelo de dados)

Visão atual do **fork** Loom + `local-runtime` (co-located).  
Atualizar **sempre** que a arquitetura mudar — ver [rules.md](rules.md) § Manutenção desta arquitetura.

**Princípio:** `local-runtime` **estende** o Loom — não substitui o data plane de
produção. AgentCore / harness na AWS e Bedrock (no caminho AgentCore) continuam
no desenho; sidecars locais são caminhos **adicionais** (laptop / compose), com
o mesmo BFF como control plane. LiteLLM é o único front de modelo e aponta para
provedores de chat (OpenAI, Anthropic, …) — **não** para Bedrock.

| Nível C4 | Conteúdo |
|----------|----------|
| **L1 Context** | Sistema no mundo (pessoas + sistemas externos) |
| **L2 Containers** | Processos / deployables (Core + extensão local) |
| **L3 Components** | Peças internas dos containers críticos |
| **Dados** | Postgres (Loom) + store Hub + IdP |

Diagramas em **Mermaid portátil** (`flowchart` / `erDiagram`) — equivalentes C4.
Não usar sintaxe `C4Context`/`C4Container`/`C4Component` (muitos previews não renderizam).

**Produção vs local:** URLs, portas e secrets vêm de **variáveis de ambiente / compose**
(`MCP_HUB_*`, `AGENT_RUNTIME_*`, `LOOM_DATABASE_URL`, issuer IdP, etc.). Nada disso
é contrato fixo da arquitetura — o diagrama descreve **papéis e relações**.

Relacionados: [ADR 0005](../adr/0005-local-agent-runtime.md),
[ADR 0006](../adr/0006-local-runtime-extension-repo.md),
[spec 003 LiteLLM](../specs/003-litellm-as-sole-llm-gateway.md),
[overview](overview.md), [scalability-reliability.md](scalability-reliability.md),
[CHANGELOG-LOOM-FORK.md](../CHANGELOG-LOOM-FORK.md).

**Última revisão:** 2026-09-14 (ADR 0013 templates + worker pool; templates MCP; LiteLLM ≠ Bedrock)

---

## L1 — System Context

```mermaid
flowchart TB
  subgraph People
    DEV[Developer / Operator]
    ADM[Admin IdP]
  end

  SYS[Loom + local-runtime<br/>control plane + extensões]

  IDP[Identity Provider<br/>OIDC / OAuth AS]
  IDE[Cursor IDE<br/>MCP client]
  AC[AWS AgentCore / Harness<br/>data plane produção]
  BR[Amazon Bedrock<br/>modelos AgentCore]
  LLMGW[LiteLLM gateway<br/>único front de modelo]
  PROV[LLM providers<br/>OpenAI, Anthropic, …]
  MCPX[MCP servers externos<br/>ADO, Grafana, Rancher, …]

  DEV -->|HTTPS UI| SYS
  DEV --> IDE
  IDE -->|MCP OAuth + tools| SYS
  SYS -->|discover JWKS token| IDP
  IDE -->|PKCE client loom-mcp-hub| IDP
  ADM --> IDP
  SYS -->|invoke deploy/harness| AC
  SYS --> LLMGW
  AC --> BR
  LLMGW --> PROV
  SYS -->|tools allowlisted| MCPX
```

AgentCore (e Bedrock no data plane AWS) e os provedores atrás do LiteLLM são
**sistemas externos** do produto Loom. O stack `local-runtime` não os remove —
acrescenta runtimes/MCP locais e o Hub OAuth no mesmo control plane. LiteLLM
**não** roteia para Bedrock; Bedrock fica no caminho AgentCore.

---

## L2 — Containers

```mermaid
flowchart TB
  USER[User browser / IDE]

  subgraph LoomExt[Loom-ext deployables]
    FE[Frontend SPA<br/>Extension Host + plugin]
    BE[Backend BFF<br/>FastAPI control plane]
    PG[(PostgreSQL<br/>estado Loom)]
    HUB[mcp-hub<br/>MCP resource server]
    HSTORE[(Hub store<br/>clients / grants)]
    MCPR[mcp-runtime<br/>stdio supervisor]
    AR[agent-runtime<br/>loop local — extensão]
    CA[cursor-adapter]
    LL[LiteLLM proxy]
    IDPL[IdP deploy<br/>ex. Keycloak ou Entra]
  end

  AC[AgentCore / Harness AWS<br/>data plane produção]
  BR[Amazon Bedrock]
  PROV[OpenAI / Anthropic / …]
  MCPX[MCP externos]
  CURSOR[Cursor Agent SDK]

  USER --> FE
  USER -->|MCP OAuth| HUB
  FE -->|REST + user JWT| BE
  BE --> PG
  BE -->|OIDC bootstrap / JWKS config| IDPL
  BE -->|service token| HUB
  BE -->|service token| MCPR
  BE -->|source=local invoke| AR
  BE -->|source=deploy/harness invoke_agent| AC
  BE --> LL
  HUB -->|materialize / tools / agents| BE
  HUB --> HSTORE
  HUB -->|validate access_token| IDPL
  AR --> LL
  AR --> MCPR
  AC --> BR
  LL --> PROV
  LL -->|cursor-local| CA
  CA --> CURSOR
  MCPR --> MCPX
```

Invoke no BFF escolhe o **adapter** (`local` | `agentcore` | `harness`) — ver
[ADR 0005](../adr/0005-local-agent-runtime.md). LiteLLM serve o **caminho local**
(agent-runtime / BFF) com OpenAI, Anthropic e `cursor-local`
([spec 003](../specs/003-litellm-as-sole-llm-gateway.md)). AgentCore usa
**Bedrock** no data plane AWS — sem seta LiteLLM ↔ AgentCore neste desenho.

### Endpoints (configuráveis)

Contrato = **nome do serviço + env**. Valores abaixo são só referência do compose
local de desenvolvimento; em produção use DNS/TLS e secrets store.

| Papel | Env / config típica | Exemplo local (não normativo) |
|-------|---------------------|-------------------------------|
| UI | frontend origin | `http://localhost:5173` |
| BFF | API base | `http://localhost:8000` |
| MCP Hub resource | `MCP_HUB_PUBLIC_URL` | `http://127.0.0.1:8790/mcp` |
| Hub → BFF | `MCP_HUB_INTERNAL_URL` + `MCP_HUB_SERVICE_TOKEN` | service network |
| mcp-runtime | `MCP_RUNTIME_URL` + `MCP_RUNTIME_TOKEN` | service network |
| agent-runtime (extensão) | `AGENT_RUNTIME_URL` + `AGENT_RUNTIME_TOKEN` | service network; **pool** de réplicas ([ADR 0013](../adr/0013-local-agent-templates-worker-pool.md), [spec 027](../specs/027-local-agent-worker-pool.md)) |
| AgentCore / harness (produção) | credenciais AWS / ARNs no BFF | conta AWS |
| LiteLLM | discovery / proxy URL | compose service |
| LLM backends (via LiteLLM) | config LiteLLM (OpenAI, Anthropic, …) | API keys em env/secrets |
| Bedrock (via AgentCore) | ARNs / IAM no data plane AWS | conta AWS |
| Postgres | `LOOM_DATABASE_URL` | compose service |
| IdP | issuer / JWKS from `identity_providers` or env bootstrap | Keycloak ou Entra |

---

## L3 — Components (recortes críticos)

### L3a — MCP Hub

```mermaid
flowchart LR
  subgraph hub[mcp-hub]
    HTTP[http_app<br/>MCP JSON-RPC + management]
    OAUTH[oauth<br/>JWT / JWKS]
    STORE[store<br/>Hub persistence]
    LOOMC[loom_client<br/>BFF HTTP]
    ACC[access / naming]
  end
  BE[Loom Backend]
  IDP[IdP JWKS]

  HTTP --> OAUTH
  HTTP --> STORE
  HTTP --> ACC
  HTTP --> LOOMC
  OAUTH --> IDP
  LOOMC -->|service token| BE
```

Fluxo: IDE OAuth → JWT → `tools/list` (grants + `agent__*` se habilitado) → `tools/call` → BFF.

### L3b — Backend BFF (fork-relevant)

```mermaid
flowchart TB
  subgraph be[Backend FastAPI]
    AUTH[auth / idp ACL]
    MCPR[routers mcp* / hub proxy]
    INV[invocations<br/>adapter: local / agentcore / harness]
    HSVC[mcp_hub* services]
    ORM[SQLAlchemy models]
  end
  AR[agent-runtime<br/>extensão local]
  AC[AgentCore / Harness AWS]
  MCPR --> AUTH
  MCPR --> HSVC
  HSVC --> ORM
  INV --> ORM
  INV --> AUTH
  INV -->|source=local| AR
  INV -->|source=deploy/harness| AC
```

### L3c — Frontend + plugin

```mermaid
flowchart LR
  subgraph fe[SPA]
    HOST[extensions host]
    PAGES[host pages<br/>Chat Agents MCP]
    PLUG[plugin: LocalRuntimePage + local-runtime/*]
  end
  HOST --> PLUG
  PLUG -.->|apiFetch + AuthProvider| PAGES
```

---

## Modelo de dados

Legenda de **origem**:

| Tag | Significado |
|-----|-------------|
| **Core Loom** | Schema da plataforma [awslabs/loom](https://github.com/awslabs/loom) — tabelas/conceitos upstream |
| **Fork (PG)** | Objetos ou colunas no **mesmo Postgres do backend Loom**, introduzidos/estendidos por este fork (ainda em `backend/` — Zona Core no changelog) |
| **local-runtime** | Persistência **fora** do Postgres Loom (sidecars / IdP local) |

Criação no backend: `init_db()` → `create_all` + `_migrate_add_columns` (sem Alembic). Boot do backend.

---

### 1) Core Loom — PostgreSQL (plataforma)

Tabelas upstream típicas (não é inventário exaustivo de colunas):

| Área | Tabelas |
|------|---------|
| Agents / invoke | `agents`, `agent_config_entries`, `invocation_sessions`, `invocations` |
| MCP catalog | `mcp_servers`, `mcp_tools`, `mcp_server_access` |
| Memória / A2A | `memories`, `a2a_agents`, `a2a_agent_skills`, `a2a_agent_access` |
| Authz / creds | `authorizer_configs`, `authorizer_credentials`, `credential_providers` |
| Políticas / tags | `tag_profiles`, `tag_policies`, `approval_*`, `permission_requests` |
| Ops | `audit_*`, `site_settings`, `managed_roles`, `vpc_configs`, `agent_integrations` |

#### ER — agents / invoke (**Core Loom**)

```mermaid
erDiagram
    agents ||--o{ agent_config_entries : has
    agents ||--o{ invocation_sessions : has
    invocation_sessions ||--o{ invocations : has
    agents {
        int id PK
        string arn
        string source
        string allowed_model_ids
        string tags
    }
    invocation_sessions {
        string session_id PK
        int agent_id FK
        string user_id
        string status
    }
    invocations {
        string invocation_id PK
        string session_id FK
        string status
        text prompt_text
        text response_text
    }
```

#### ER — MCP catalog (**Core Loom** + extensão de colunas no fork)

Tabelas `mcp_*` são **Core Loom**. Colunas de runtime/template no fork: ver §2.

```mermaid
erDiagram
    mcp_servers ||--o{ mcp_tools : has
    mcp_servers ||--o{ mcp_server_access : grants
    mcp_servers {
        int id PK
        string name
        string status
    }
    mcp_tools {
        int id PK
        int server_id FK
        string tool_name
    }
    mcp_server_access {
        int id PK
        int server_id FK
    }
```

---

### 2) Fork (PG) — customizações no Postgres do Loom

Objetos/colunas que **não** devem ser tratados como “só local-runtime”: vivem no BFF e no schema Loom (impacto em sync `upstream`).

| Objeto | Tipo | Notas |
|--------|------|--------|
| `identity_providers` | **Tabela nova (fork)** | ACL multi-IdP (Keycloak/Entra/…) |
| `mcp_hub_sessions` | **Tabela nova (fork)** | Legado mint Hub (`hs_…`); fluxo atual = JWT IdP |
| `mcp_servers.template_id` | **Coluna (fork)** | Templates stdio (`azure-devops`, grafana, …) |
| `mcp_servers.runtime_endpoint_url` | **Coluna (fork)** | URL facade mcp-runtime |
| `mcp_servers.runtime_state` | **Coluna (fork)** | Estado do runtime local |
| `mcp_servers.template_params` / `secret_refs` | **Colunas (fork)** | Params + refs de segredo |
| `mcp_servers.delegation_mode` / OBO fields | **Colunas (fork)** | Delegação m2m/obo |
| Seeds Orientador (`agents` source=local) | **Dados (fork)** | Linhas/config; tabela `agents` continua Core |

```mermaid
erDiagram
    identity_providers {
        int id PK
        string provider_type
        string issuer_url
        string client_id
        string jwks_uri
        text group_mappings
    }
    mcp_hub_sessions {
        string id PK
        string token_hash
        string subject
        datetime expires_at
        datetime revoked_at
    }
```

`mcp_hub_sessions`: mint removido (ADR 0011). Tabela pode permanecer até limpeza **autorizada** pelo Dev.

---

### 3) local-runtime — stores fora do Postgres Loom

| Store | Onde | Conteúdo |
|-------|------|----------|
| **Postgres DB `mcp_hub`** | Mesmo servidor PG do compose; DSN `MCP_HUB_DATABASE_URL` | Canais MCP, `agents_enabled`, profile grants, session bindings (`hub_clients`, `hub_session_bindings`) |
| **JSON fallback** | `MCP_HUB_STORE_PATH` (só se DSN unset; ou fonte de migrate) | Snapshot legado |
| **Keycloak DB** | Container Keycloak | Realm `loom`, users/groups, client `loom-mcp-hub` |
| **Templates YAML** | `local-runtime/services/mcp-runtime/templates/` (ro no container) | Allowlist stdio — dono: **mcp-runtime** |

#### Hub store schema (Postgres `mcp_hub`)

```text
hub_clients(slug PK, display_name, declared_*, status, agents_enabled, grants JSONB, first_seen_at, last_seen_at)
hub_session_bindings(hub_session_id PK, mcp_client_slug FK, bound_at)
```

Init: `etc/docker/postgres-init/02-mcp-hub-db.sql` (volume Postgres **novo**).  
Não misturar com schema/ORM do Loom Core.

---

### 4) Relação lógica entre origens

| Conceito | Origem | Liga a |
|----------|--------|--------|
| `profile_grants[].server_id` | **local-runtime** Hub PG | **Core** `mcp_servers.id` |
| `agents_enabled` | **local-runtime** Hub PG | **Core** `agents` + RBAC tags (invoke via BFF) |
| Runs `agent__*` / Chat invoke | BFF cria **Core** `invocation_sessions` / `invocations` | Adapter **local** → agent-runtime; **deploy/harness** → AgentCore (produção) |
| Modelo LLM | LiteLLM (único gateway do control plane) | OpenAI / Anthropic / …; `cursor-local` → cursor-adapter. Bedrock → AgentCore |
| IdP ativo | **Fork (PG)** `identity_providers` | Keycloak/Entra (**local-runtime** / SaaS) |
| Template stdio | **Fork** colunas em `mcp_servers` | **mcp-runtime** YAML allowlist |
| Template agent local | **Extension** YAML (`agent-runtime/templates/`, [spec 026](../specs/026-local-agent-templates.md)) | `agents.source=local` + escopo no invoke ([ADR 0013](../adr/0013-local-agent-templates-worker-pool.md)) |

```text
                    ┌──────────────────────────┐
                    │  local-runtime           │
                    │  Postgres DB mcp_hub     │
                    │  mcp-runtime/templates/*.yaml │
                    │  Keycloak (realm)        │
                    └────────────┬─────────────┘
                                 │ server_id / OAuth
                    ┌────────────▼─────────────┐
                    │  Postgres Loom           │
                    │  Core tables             │
                    │  + Fork tables/columns   │
                    └──────────────────────────┘
```

---

## Manutenção

Qualquer mudança de containers, portas, fluxos auth, stores ou tabelas **deve** atualizar este arquivo no mesmo PR/entrega — e marcar se a mudança é **Core Loom**, **Fork (PG)** ou **local-runtime**. Regra canônica em [rules.md](rules.md).
