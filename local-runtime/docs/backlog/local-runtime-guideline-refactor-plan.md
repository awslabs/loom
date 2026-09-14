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

Escopo sugerido (1–2 PRs):

1. Criar pastas alvo sem mover comportamento ainda (`domain/errors`, `application/ports`)
2. Extrair regras puras já quase isoladas: `access`, `naming`, identity parsing
3. Use cases: `tools_list`, `tools_call`, `patch_client`, `materialize` orchestration
4. Inbound: `http_app` só HTTP ↔ use case
5. Outbound ports: `HubStore`, `LoomGateway`, `TokenValidator`
6. Adapters: `file_store` (atual), `loom_http`, `oauth_jwks`
7. Composition root em `__main__`

Critério de aceite: mesmos testes verdes; smoke Cursor `tools/list` + `agent__*`.

### Fase 2 — Hub store produção ([REF-2026-09-14-01](refactoring.md))

- Port `HubStore` já existente na Fase 1
- Adapter Postgres (DSN via env); migração one-shot do JSON
- Atualizar architecture + scalability docs

### Fase 3 — agent-runtime

- Separar domain de sessão/erro de contrato vs loop I/O
- Ports: `LlmGateway`, `McpToolsClient`, `SessionStore`
- Manter contract version `2026-09-local-1` estável

### Fase 4 — mcp-runtime + cursor-adapter

- Mesmo padrão; supervisor/templates já próximos de “application”
- cursor-adapter: isolar translation pura de SDK I/O

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

## 6. Decisões em aberto (precisam do Dev)

1. **Primeira fatia autorizada:** só Fase 0 docs, ou já Fase 1 mcp-hub?
2. **Hub store:** Postgres dedicado do Hub vs schema no PG Loom (via interface / sem ORM Core)?
3. **HTTP stack:** manter `http.server` nos adapters inbound ou migrar FastAPI/Starlette por serviço?
4. **Compat:** exigir zero mudança de wire protocol nas Fases 1–3?

---

## 7. Próximo passo sugerido

1. Dev responde §6 (ao menos itens 1 e 4).
2. Commit deste plano na branch `plan/local-runtime-guideline-refactor`.
3. Abrir PR **docs-only** para `main` do fork (congelar o plano).
4. Nova branch `refactor/mcp-hub-hexagonal` quando o Dev autorizar `REF-2026-09-14-02`.
