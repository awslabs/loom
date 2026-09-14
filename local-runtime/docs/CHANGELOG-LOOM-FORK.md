# Changelog — divergência do fork vs Loom público

**Upstream:** [awslabs/loom](https://github.com/awslabs/loom) (`upstream/main`)  
**Fork:** [jsmesquita/loom-ext](https://github.com/jsmesquita/loom-ext)  
**Objetivo:** registrar **tudo que toca o core do Loom** versus o que ficou **fora** (`local-runtime/`), para:

1. medir o grau de acoplamento ao upstream;
2. planejar `git fetch upstream` / rebase / merge com conflitos previsíveis;
3. preferir novos ganchos na extension em vez de alargar o core, quando possível.

> **Docs do fork vivem aqui** (`local-runtime/docs/`), não em `docs/` na raiz do
> Loom — assim não concorrem com o upstream no sync. Índice:
> [README.md](README.md).

> Este arquivo **não** substitui o histórico git. É um índice humano, atualizado
> sempre que uma mudança entrar em `backend/`, `frontend/` (fora do plugin),
> `docker-compose.yml`, `makefile` da raiz, ou outros paths “Loom puro”.

**Como atualizar:** ao final de cada entrega, acrescente uma entrada em
[Registro](#registro) (mais recente no topo). Marque a coluna **Zona**.

| Zona | Significado | Risco no pull do upstream |
|------|-------------|---------------------------|
| **Core** | Código/plataforma Loom (`backend/`, `frontend/` host, compose raiz, makefile raiz) | Alto — pode conflitar com awslabs/loom |
| **Extension** | `local-runtime/**` (plugin UI, sidecars, templates, overlay) | Baixo — upstream não tem esse tree |
| **Docs** | `local-runtime/docs/**` (ADRs, specs, guias, este changelog) | Baixo — fora do Loom; raiz `docs/` do fork removida |
| **Config** | `etc/docker/**`, `.env.example`, realm Keycloak, LiteLLM local | Médio — stack local do fork |

**Baseline de comparação:** `main` do fork (`origin/main`).  
**Branch de planejamento (refactor guidelines):** `plan/local-runtime-guideline-refactor`.

**Instruções de agentes:** hub [`README.md`](README.md) → [`guide/rules.md`](guide/rules.md) →
guias em [`guide/`](guide/). Pointers: Cursor
`.cursor/rules/prefer-local-runtime-extension.mdc`; Claude `CLAUDE.md`.

---

## Resumo rápido (grau de alteração)

| Área | Situação no fork | Notas para rebase |
|------|------------------|-------------------|
| IdP ACL (`backend/app/idp/`, auth, settings IdP) | **Core** grande | Conflitos prováveis em `auth.py`, `main.py`, routers |
| MCP catalog / stdio / access | **Core** + templates na extension | Conferir `mcp.py`, `mcp_access.py`, forms |
| Invoke local / Orientador / LiteLLM | **Core** (`local_invoke`, `local_agents`) + LiteLLM em `etc/` + agent-runtime na extension | `invocations.py` / `local_invoke.py` sensíveis |
| Extension Host UI | **Core** fino (`frontend/src/extensions/*`, `App.tsx`, vite alias) | Manter host estável (ADR 0006) |
| MCP Hub (OAuth, clients, agents-as-tools) | **Core** BFF (`mcp_hub*`) + **Extension** sidecar `mcp-hub` + plugin Local runtime | BFF no Loom; data plane fora |
| Model Configuration (Agent Detail) | **Core** UI (`AgentDetailPage`, `DeploymentPanel`, `api/agents.ts`) | Merge Bedrock+LiteLLM no cliente — ver entrada 2026-09-14 |
| Docs do fork | **Docs** em `local-runtime/docs/` (ADRs, specs, guias) | Baixo — sem `docs/` na raiz |

**Regra de ouro (ADR 0006):** feature nova → `local-runtime/`. Docs novas → `local-runtime/docs/`. Core só sem alternativa (BFF, Extension Host, auth, catalog).

---

## Como usar ao puxar o Loom público

```bash
git fetch upstream
git checkout main
git merge upstream/main   # ou rebase da feature em cima
```

1. Abra este changelog e filtre entradas **Core**.
2. Para cada arquivo Core listado, rode `git log upstream/main -- <path>` e compare com o nosso diff.
3. Conflitos em **Extension** / `local-runtime/docs` costumam ser triviais ou inexistentes.
4. Depois do merge, acrescente uma entrada “sync upstream” com a data e o SHA de `upstream/main`.

Checklist pós-merge:

- [ ] `backend` sobe; testes IdP / MCP hub / local_invoke
- [ ] `frontend` build; Extension Host ainda carrega `@loom-ext/local-runtime`
- [ ] overlay `local-runtime/compose/overlay.yml` aplica sem quebrar serviços novos do upstream
- [ ] atualizar este arquivo se o sync tocou Core

---

## Registro

### 2026-09-14 — mcp-hub hexagonal strangler (REF-02)

**Contexto:** decisões do plano aceitas; primeira fatia de layout ports/adapters.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Extension** | `services/mcp-hub/mcp_hub/{domain,application,adapters}/` | Layout hexagonal + ports + FileHubStore/Loom/OAuth classes |
| **Extension** | shims `access.py`…`http_app.py` | Compat de imports |
| **Docs** | plano / backlog REF-02 | Decisões locked; execução iniciada |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Plano de refactor local-runtime × guidelines

**Contexto:** iniciar planejamento (sem código) para aderência hexagonal / SOLID.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `backlog/local-runtime-guideline-refactor-plan.md` | Plano fasado 0–6 |
| **Docs** | `backlog/refactoring.md` | REF-02…06 |
| **Docs** | `README.md`, este changelog | Links / baseline fork |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Guia Python best practices (hexagonal alvo)

**Contexto:** documentar SOLID/Calisthenics/KISS/YAGNI/DRY/Clean Code/GoF e
estrutura hexagonal para sidecars — **sem** refatorar código existente.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/python-best-practices.md` | Guia canônico |
| **Docs** | `local-runtime/docs/README.md`, `guide/development.md` | Links |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Regras: Core só com autorização do Dev

**Contexto:** reforçar gate humano antes de qualquer exceção no Loom.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/rules.md` | Features em local-runtime; Core = exceção + ok explícito do Dev |
| **Extension** | `CLAUDE.md`, `.cursor/rules/…` | Lembrete do hard gate (sem duplicar política) |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — architecture: Mermaid portátil + endpoints via env

**Contexto:** C4 plugin não renderiza em vários previews; arquitetura alinhada a prod (config).

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `guide/architecture.md` | L1–L3 em `flowchart`; tabela env; sem portas como contrato |
| **Docs** | `guide/rules.md` | Manutenção: Mermaid portátil + env |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — architecture.md: dados Core vs Fork vs local-runtime

**Contexto:** deixar explícito o que é schema upstream, extensão PG do fork e stores da extension.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/architecture.md` | Seções 1–4 do modelo de dados |
| **Docs** | `guide/rules.md` | Manutenção exige tag de origem do store |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Guia scalability / reliability

**Contexto:** NFRs de escala, HA, falha e idempotência filtrados ao fork (não em `rules.md`).

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/scalability-reliability.md` | Guia NFR |
| **Docs** | `rules.md`, `architecture.md`, `README.md` | Links |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Arquitetura C4 + regra de atualização

**Contexto:** documentar L1/L2/L3 e modelo de dados; obrigar sync do doc em mudanças.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/architecture.md` | C4 + ER Postgres/JSON Hub |
| **Docs** | `guide/rules.md` | § Manutenção da arquitetura + checklist |
| **Docs** | README, CLAUDE, Cursor pointer | Links |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Guia de segurança (OWASP/RFC filtrados)

**Contexto:** checklist objetivo para API/web/sidecars deste fork — sem inflar.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/security.md` | Top 10 mapeado, RFCs OAuth/JWT, PII, injection, checklist |
| **Docs** | `README.md`, `guide/development.md` | Links |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Regra: sem refactor sem pedido + backlog

**Contexto:** oportunidades de melhoria registradas; atuação só sob demanda do Dev.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/rules.md` | § Não refatorar sem pedido do Dev |
| **Docs** | `local-runtime/docs/backlog/refactoring.md` | Template + lista de itens |
| **Docs** | README, python-best-practices, pointers IDE | Links |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — `rules.md` (rename lowercase)

**Contexto:** alinhar ao padrão kebab/lowercase dos outros guias.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/rules.md` | Renomeado de `RULES.md` |
| **Docs** / pointers | README, CLAUDE, Cursor, guias | Links atualizados |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — `RULES.md` sob `guide/`

**Contexto:** regras junto dos guias operacionais.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/RULES.md` | Movido de `local-runtime/docs/RULES.md` |
| **Docs** / pointers | README, CLAUDE, Cursor rule, changelog | Paths atualizados |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Migração ADRs/specs para `local-runtime/docs/`

**Contexto:** cumprir a política de docs só na extension; remover concorrência com `docs/` do Loom.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/adr/*`, `local-runtime/docs/specs/*` | ADRs 0001–0012 e specs 001–025 movidos da raiz |
| **Docs** | `docs/adr`, `docs/specs` (raiz) | Removidos |
| **Docs** | índices `adr/README`, `specs/README`, guias, RULES, changelog | Links atualizados |

**Impacto no sync upstream:** baixo (add-only sob local-runtime; delete de paths que o upstream não tinha).

---

### 2026-09-14 — Guias de uso em `local-runtime/docs/guide/`

**Contexto:** padronizar how-to do repo fora do Loom; Claude/Cursor só apontam.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/{overview,getting-started,development,upstream-sync,mcp-hub}.md` | Guias de uso |
| **Docs** | `local-runtime/docs/README.md` | Hub de documentação |
| **Extension** | `local-runtime/README.md`, `CLAUDE.md`, `.cursor/rules/…` | Pointers; conteúdo operacional removido de CLAUDE |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Regras canônicas em `RULES.md` (pointers IDE)

**Contexto:** uma única fonte de regras, agnóstica de Cursor/Claude; arquivos de IDE só apontam.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/guide/RULES.md` | Política de colocação Core vs extension (canônica) |
| **Docs** | `local-runtime/docs/README.md`, `CHANGELOG-LOOM-FORK.md` | Índice + refs |
| **Extension** | `.cursor/rules/prefer-local-runtime-extension.mdc`, `CLAUDE.md` | Pointers finos (sem duplicar corpo) |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Docs do fork sob `local-runtime/docs/`

**Contexto:** evitar concorrência com `docs/` do Loom no sync upstream.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Docs** | `local-runtime/docs/CHANGELOG-LOOM-FORK.md` | Changelog movido de `docs/` (raiz) |
| **Docs** | `local-runtime/docs/README.md`, `adr/README.md` | Política + índice; legado apontado na raiz |
| **Extension** | `.cursor/rules/prefer-local-runtime-extension.mdc`, `CLAUDE.md` | Docs só em local-runtime; path do changelog atualizado |

**Impacto no sync upstream:** baixo.

---

### 2026-09-14 — Agents as MCP tools (implementação) + Model Configuration LiteLLM

**Contexto:** Fase 2 do Hub (ADR 0012 / spec 025): expor agents Loom como tools MCP; UI Local runtime `agents_enabled`; correção do editor de models para catálogo LiteLLM; bypass agent-runtime para mocks LiteLLM.

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Core** | `backend/app/routers/mcp_hub.py` | Endpoints Hub: `materialize-agents`, `agents/invoke`, `agents/runs/{id}` |
| **Core** | `backend/app/services/mcp_hub_agents.py` *(novo, WIP)* | Materialize RBAC, invoke async/sync, status/result |
| **Core** | `backend/app/services/local_invoke.py` | Mocks `orientador-academico` / `mock-echo` **não** passam pelo agent-runtime (evita hang) |
| **Core** | `backend/tests/test_mcp_hub.py`, `test_local_invoke.py` | Cobertura materialize/RBAC e path agent-runtime com model não-mock |
| **Core** | `frontend/src/api/agents.ts` | `fetchAllModelOptions()` = Bedrock + LiteLLM |
| **Core** | `frontend/src/pages/AgentDetailPage.tsx` | Model Configuration usa catálogo mesclado (+ fallback dos ids do agente) |
| **Core** | `frontend/src/components/DeploymentPanel.tsx` | Idem para Allowed Models |
| **Extension** | `local-runtime/services/mcp-hub/mcp_hub/{http_app,loom_client,store}.py` | `agents_enabled`; `tools/list`/`tools/call` para `agent__*` / status / result |
| **Extension** | `local-runtime/services/mcp-hub/tests/test_store_identity.py` | Flag `agents_enabled` |
| **Extension** | `local-runtime/plugin/src/pages/LocalRuntimePage.tsx` | Toggle “Expose Loom agents” independente de perfil IdP |

**Por que Core (não só extension):** o Hub precisa de BFF autenticado no FastAPI do Loom (materialize/invoke com sessão/RBAC). O editor de models é página Agent Detail do host — o Extension Host **não** injeta nesse card.

**Alternativa rejeitada:** unificar LiteLLM em `GET /api/agents/models` (quebraria o split Bedrock vs `/models/litellm`).

**Estado:** código Hub agents + UI models em working tree / imagem local; ADRs/specs da Fase 2 ainda sob `docs/` na raiz (legado — migrar depois).

---

### 2026-09-13 — MCP Hub OAuth IdP (sem mint) + clients / profile grants

| Zona | Paths (principais) | O que mudou |
|------|--------------------|-------------|
| **Core** | `backend/app/routers/mcp_hub.py`, `services/mcp_hub.py`, `mcp_hub_proxy.py`, `models/mcp_hub.py` | BFF Hub: clients, grants, materialize allowlist; remoção do fluxo mint |
| **Core** | `backend/tests/test_mcp_hub.py` | Contratos Hub |
| **Extension** | `local-runtime/services/mcp-hub/**` | Sidecar OAuth PRM/PKCE, store de clients, proxy tools |
| **Extension** | `local-runtime/plugin/.../LocalRuntimePage.tsx` | Admin de canais + grants por perfil |
| **Docs** | ADR 0007–0011, specs 016–024 | Contrato Hub, OAuth, grants *(hoje em `local-runtime/docs/`)* |

**Risco upstream:** routers/services novos no backend — merge costuma ser add; cuidado se awslabs criar `mcp_hub` com outro desenho.

---

### 2026-09-12…13 — Local agent-runtime, cursor-local, Orientador

| Zona | Paths (principais) | O que mudou |
|------|--------------------|-------------|
| **Core** | `backend/app/services/local_invoke.py`, `local_agents.py`, `routers/invocations.py` | `source=local`, proxy agent-runtime / LiteLLM, seed Orientador |
| **Core** | testes `test_local_invoke.py` | |
| **Extension** | `local-runtime/services/agent-runtime/**`, `cursor-adapter/**` | Data plane invoke + adapter Cursor |
| **Config** | `etc/docker/litellm/config.yaml`, `cursor_handler.py` | Models mock + cursor-local |
| **Docs** | ADR 0005, specs 011–014 | *(hoje em `local-runtime/docs/`)* |

---

### 2026-09 — Local MCP runtime, stdio catalog, Grafana/Rancher

| Zona | Paths (principais) | O que mudou |
|------|--------------------|-------------|
| **Core** | `backend/.../mcp.py`, `mcp_access.py`, `mcp_templates.py`, `mcp_runtime_client.py`, forms/pages MCP no frontend | Catalog, access, deploy path para stdio |
| **Extension** | `local-runtime/services/mcp-runtime/**`, `templates/*.yaml` | Supervisor stdio + templates |
| **Docs** | ADR 0004, specs 005–010, 015 *(legado)* | |

---

### 2026-09 — Extension Host + extração `local-runtime`

| Zona | Paths (principais) | O que mudou |
|------|--------------------|-------------|
| **Core** | `frontend/src/extensions/*`, `App.tsx`, `vite.config.ts` | Host estável `addExtension` |
| **Extension** | `local-runtime/plugin/**`, `compose/overlay.yml`, `makefile` targets | Plugin + stack sidecar |
| **Docs** | ADR 0006 *(legado)* | |

**Manter estável no rebase:** assinatura de `LoomExtensionHost` / `LoomExtensionRegistration`.

---

### 2026-09 — IdP anti-corruption + stack local (Keycloak / Postgres / LiteLLM)

| Zona | Paths (principais) | O que mudou |
|------|--------------------|-------------|
| **Core** | `backend/app/idp/**`, `dependencies/auth.py`, `routers/auth.py`, `identity_providers.py`, `services/oidc.py`, frontend Login/Auth/IdP panel | Abstração multi-IdP |
| **Config** | `docker-compose.yml`, `etc/docker/keycloak/**`, `postgres-init/**`, `.env.example` | Stack local |
| **Docs** | ADR 0001–0003, specs 001–004 *(legado)* | |

**Risco upstream:** **alto** em auth/OIDC — revisar com cuidado a cada sync.

---

## Inventário WIP (não commitado)

Atualizado em **2026-09-14**. Confirmar com `git status` antes de sync.

**Core**

- `backend/app/routers/mcp_hub.py` (agents endpoints)
- `backend/app/services/mcp_hub_agents.py` (untracked)
- `backend/app/services/local_invoke.py` (skip agent-runtime para mocks)
- `backend/tests/test_mcp_hub.py`, `test_local_invoke.py`
- `frontend/src/api/agents.ts`
- `frontend/src/pages/AgentDetailPage.tsx`
- `frontend/src/components/DeploymentPanel.tsx`

**Extension / Docs**

- `local-runtime/plugin/src/pages/LocalRuntimePage.tsx`
- `local-runtime/services/mcp-hub/mcp_hub/{http_app,loom_client,store}.py`
- `local-runtime/services/mcp-hub/tests/test_store_identity.py`
- `local-runtime/docs/**` (changelog + README de política)

---

## Convenção de novas entradas

```markdown
### YYYY-MM-DD — Título curto

**Contexto:** …

| Zona | Paths | O que mudou |
|------|-------|-------------|
| **Core** | … | … |
| **Extension** | … | … |
| **Docs** | local-runtime/docs/… | … |

**Por que Core (se aplicável):** …
**Impacto no sync upstream:** baixo | médio | alto
```

Relacionado: [ADR 0006](adr/0006-local-runtime-extension-repo.md).
