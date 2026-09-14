# Plano — refatorar `local-runtime` para aderência aos guidelines

- **Branch:** `plan/local-runtime-guideline-refactor`
- **Status:** rascunho de planejamento (sem código de migração nesta fase)
- **Data:** 2026-09-14
- **Alvos canônicos:**
  - [guide/rules.md](../guide/rules.md)
  - [guide/python-best-practices.md](../guide/python-best-practices.md) (hexagonal, SOLID, Clean Code)
  - [guide/architecture.md](../guide/architecture.md)
  - [guide/scalability-reliability.md](../guide/scalability-reliability.md)
  - [guide/security.md](../guide/security.md)
  - [guide/development.md](../guide/development.md)
- **Registro operacional:** itens em [refactoring.md](refactoring.md) — só executar com id autorizado pelo Dev

---

## 1. Objetivo

Trazer sidecars e plugin de `local-runtime/` para o **norte** já documentado
(hexagonal por serviço, ports/adapters, testes unitários do domínio, config via
env, stores com paridade de produção), **sem** big-bang e **sem** tocar Core
Loom salvo exceção autorizada.

Não-objetivos nesta iniciativa:

- Reescrever BFF / frontend host “de passagem”
- Migrar todos os serviços no mesmo PR
- Introduzir frameworks HTTP só por estética

---

## 2. Estado atual (gap)

| Área | Hoje | Alvo (guideline) |
|------|------|------------------|
| Layout Python | Pacotes **planos** (`http_app.py`, `store.py`, `loop.py`, …) | `domain/` · `application/` · `adapters/{inbound,outbound}/` + composition root em `__main__` |
| Dependências | HTTP ↔ store ↔ loom_client misturados | `adapters → application → domain`; domain sem I/O |
| Persistência Hub | `hub_clients.json` (single-writer) | Store via port; adapter Postgres (ou DSN env) — [REF-2026-09-14-01](refactoring.md) |
| Testes | Mistura HTTP/store; pouco `tests/unit` de domínio | Unit com fakes nos ports; adapters opcionais |
| Config | Env parcial; ports “exemplo local” na memória | Papel + env; sem host:porta como contrato |
| Plugin | Página grande (`LocalRuntimePage.tsx`) | Componentes por responsabilidade; API client fino |
| Core acoplado | Ganchos BFF já no changelog | Manter; não expandir sem autorização |

### Serviços no escopo

Ordem proposta (maior valor / churn / clareza → menor):

1. **mcp-hub** — superfície MCP + OAuth + store + agents tools (mais regras de negócio)
2. **agent-runtime** — loop / sessão / MCP outbound
3. **mcp-runtime** — supervisor stdio (já relativamente isolado)
4. **cursor-adapter** — translation / sessions / planner
5. **plugin** — UI Local runtime (após contratos HTTP estáveis)

---

## 3. Princípios de execução

1. **Um serviço por fatia** — PR pequeno; comportamento externo estável (HTTP/MCP contract).
2. **Strangler** — extrair domain/application primeiro; adapters thin wrapping do código atual; depois apagar plano.
3. **Testes antes ou junto** — cobrir use cases com fakes; regressão `make local.*.test`.
4. **KISS / YAGNI** — ports só onde há I/O ou segundo adapter real (ex.: JSON → PG).
5. **Fail-closed** auth permanece; sem relaxar OAuth/JWKS.
6. **Docs no mesmo PR** — `architecture.md` + changelog se containers/stores mudarem; REF → `done`.

---

## 4. Fases

### Fase 0 — Inventário e contratos (esta branch)

- [x] Branch de planejamento
- [ ] Checklist por serviço: módulos, I/O, regras puras candidatas a `domain/`
- [ ] Congelar contratos externos a preservar (paths Hub, JSON-RPC methods, env vars)
- [ ] Priorizar backlog REF (abaixo) e obter ok do Dev para a **primeira** fatia

**Entrega:** este plano + itens REF; zero mudança de runtime.

### Fase 1 — mcp-hub hexagonal (mínimo viável)

Escopo (strangler; wire estável):

1. [x] Pastas alvo `domain/` · `application/` · `adapters/{inbound,outbound}/`
2. [x] Mover regras puras: `access`, `naming`, `identity` → `domain/`
3. [x] Ports: `HubStore`, `LoomGateway`, `TokenValidator` + wiring defaults
4. [x] Outbound: `file_store`, `loom_http`, `oauth_jwks` (+ classes adapter)
5. [x] Inbound: `http_app` sob `adapters/inbound/` (ainda orquestra use cases inline)
6. [x] Shims de compat nos imports antigos + testes verdes
7. [x] Extrair use cases (`tools_list` / `tools_call`) para `application/use_cases/`
8. [x] Injetar ports no handler (composition root em `serve()`)

Critério de aceite: mesmos testes verdes; smoke Cursor `tools/list` + `agent__*`.

### Fase 2 — Hub store produção ([REF-2026-09-14-01](refactoring.md))

- [x] Port `HubStore` (Fase 1)
- [x] Adapter Postgres (DSN via env); migrate one-shot do JSON quando PG vazio
- [x] Atualizar architecture + compose (`mcp_hub` DB)

### Fase 3 — agent-runtime

- [x] Separar domain de sessão/contrato vs loop I/O
- [x] Ports: `LlmGateway`, `McpToolsClient`, `SessionStore`
- [x] Manter contract version `2026-09-local-1` estável

### Fase 4 — mcp-runtime + cursor-adapter

- [x] mcp-runtime: layout leve + `ProcessSupervisor` port
- [x] cursor-adapter: translation/planner no domain; SDK outbound

### Fase 5 — plugin UI

- Fatiar `LocalRuntimePage` (lista clients / grants / agents toggle)
- Sem mudar contratos BFF/Hub

### Fase 6 — Higiene transversal

- Tipagem pública sem `Any` nas bordas onde possível
- `tests/unit` vs `tests/adapters` em todos os serviços
- Revisar secrets/logging vs [security.md](../guide/security.md)

---

## 5. Itens de backlog ligados

| Id | Título | Fase |
|----|--------|------|
| [REF-2026-09-14-01](refactoring.md) | Hub store JSON → Postgres | 2 |
| REF-2026-09-14-02 | mcp-hub → layout hexagonal | 1 |
| REF-2026-09-14-03 | agent-runtime → hexagonal | 3 |
| REF-2026-09-14-04 | mcp-runtime → hexagonal (leve) | 4 |
| REF-2026-09-14-05 | cursor-adapter → hexagonal | 4 |
| REF-2026-09-14-06 | plugin LocalRuntimePage split | 5 |

Detalhe tabular em [refactoring.md](refactoring.md).

---

## 6. Decisões (aceitas 2026-09-14)

Pacote fechado pelo Dev (seguir recomendações do agente):

| # | Tema | Decisão |
|---|------|---------|
| 1 | Primeira fatia | Congelar plano em `main` (PR docs); em seguida **`REF-2026-09-14-02`** (mcp-hub hexagonal mínimo) |
| 2 | Compat | **Zero breaking change** nas fases 1–3 (paths, JSON-RPC, `agent__*`, env, contract agent-runtime) |
| 3 | Ordem | Hexagonal fino do Hub **com port `HubStore`** → depois Postgres (`REF-01`) |
| 4 | Hub store | Postgres **dedicado ao Hub** (DSN/env); preferir DB/schema `mcp_hub` — **não** ORM/schema Core Loom |
| 5 | HTTP inbound | Manter **`http.server`** na 1ª leva; FastAPI/Starlette só se surgir necessidade real |
| 6 | Profundidade | **Strangler mínimo** (domain + application + ports + adapters); sem big-bang |

---

## 7. Próximo passo

1. ~~Commit do plano na branch `plan/local-runtime-guideline-refactor`~~ (feito)
2. PR docs-only → merge em `main` do fork
3. Branch `refactor/mcp-hub-hexagonal` — implementar `REF-2026-09-14-02` sob as decisões acima
4. Depois: `REF-2026-09-14-01` (adapter Postgres no port `HubStore`)
