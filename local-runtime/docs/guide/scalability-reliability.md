# Escalabilidade, resiliência e alta disponibilidade

Padrões de **larga escala / HA** filtrados para este fork (BFF Loom, sidecars
`local-runtime`, MCP Hub, Postgres, IdP). Objetivo — não é catálogo SRE completo.

Política de processo (onde colocar código, ok do Dev): [rules.md](rules.md).  
Visão estrutural: [architecture.md](architecture.md).  
Segurança: [security.md](security.md).

**Última revisão:** 2026-09-14

---

## Onde isto se aplica

| Camada | Escala horizontal? | Notas |
|--------|--------------------|--------|
| Frontend SPA | Sim (CDN/static) | Stateless |
| Backend FastAPI | Sim (várias réplicas) | Sessão em Postgres; JWT stateless |
| mcp-hub | Cuidado | Store JSON em volume **não** é multi-writer HA |
| mcp-runtime / agent-runtime | Sim (réplicas) | Stateful short-lived por request; sem sticky obrigatório se não guardar memória local |
| LiteLLM / cursor-adapter | Sim / limitado | Adapter depende de workspace/API key |
| Postgres / Keycloak | HA clássica | Primário+réplica / cluster IdP — fora do escopo local compose |

Ambiente **local** (`make local.up`) é single-node. Os padrões abaixo são o
**alvo** quando for além do laptop; não exige cluster no dia a dia.

---

## 1. Escalabilidade

| Técnica | Uso neste projeto |
|---------|-------------------|
| **Stateless app tier** | BFF e sidecars sem estado em memória de processo que precise sticky session |
| **Work fora do BFF** | Tool loops / stdio / agent loop nos sidecars (ADR 0006) — escala H/V por serviço |
| **Filas / async** | Hub agents: `wait=accepted` + poll status/result (não segurar HTTP longo no IDE) |
| **Connection pooling** | SQLAlchemy `pool_pre_ping` / `pool_recycle` no backend |
| **Cache com cuidado** | JWKS cache no Hub (TTL); invalidar com rotação de chaves IdP |
| **Backpressure** | Timeouts em invoke (`timeout_s`); não aceitar prompt/tool ilimitado sem limite de tamanho |
| **Particionar por tenant/grupo** | Grants Hub por perfil IdP; RBAC `loom:group` — isola carga lógica |

**Evitar “escalar” o JSON do Hub** com vários writers. Para HA real do registry de
clients: evoluir para store compartilhado (Postgres/Redis) — registrar em
[backlog](../backlog/refactoring.md) se for o caso; **não** refatorar sem pedido.

---

## 2. Tolerância a falha

| Técnica | Prática |
|---------|---------|
| **Timeouts** | Todo HTTP outbound (Loom↔Hub, LiteLLM, agent-runtime) com timeout explícito |
| **Fail-closed** | Auth/JWKS indisponível → `401`/`403`, não degradar para anônimo ([security](security.md)) |
| **Healthchecks** | Compose já usa `/health` nos sidecars — manter em serviços novos |
| **Retry com jitter** | Só em erros **transitórios** (rede, 502/503); **nunca** retry cego em POST não idempotente |
| **Circuit / bulkhead (leve)** | Isolar falha do LiteLLM da falha do mcp-runtime (não derrubar o BFF inteiro) |
| **Graceful shutdown** | Sidecars: parar de aceitar work; deixar request em voo terminar ou marcar run `error` |
| **Dependências opcionais** | Cursor-adapter down → erro claro no model `cursor-local`; mocks LiteLLM seguem |

---

## 3. Idempotência

| Operação | Expectativa |
|----------|-------------|
| `tools/list` / GET-like | Idempotente |
| OAuth token | Refresh/code single-use (IdP) |
| `PATCH` client Hub (`agents_enabled`, status) | Idempotente no estado final |
| `PUT` profile-grants | Replace set — reenviar mesmo body = mesmo estado |
| `agents/invoke` (nova run) | **Não** idempotente — cada call cria session/invocation |
| Retentar invoke | Só com **idempotency key** explícita (hoje: não inventar; se precisar, spec + ok do Dev) |
| Poll `agent_run_status` / `result` | Idempotente (leitura) |
| `create_all` / migrate columns | Idempotente no boot |

Regra: se o client pode **repetir** o request (timeout, retry IDE), o servidor
deve ou ser idempotente ou devolver o mesmo `session_id` via chave acordada —
não duplicar side effects caros sem desenho.

---

## 4. Consistência e disponibilidade

| Tema | Escolha típica aqui |
|------|---------------------|
| Catalog MCP (Postgres) | Fonte de verdade do BFF; Hub materializa allowlist sob demanda |
| Hub clients (JSON) | Fonte de verdade do canal; consistente em **single instance** |
| Agent runs | Estado em `invocation_sessions` / `invocations`; poll até `complete`/`error` |
| IdP | Disponibilidade do login/MCP amarrada ao IdP — sem fallback inseguro |

Preferir **disponibilidade com fail-closed** a “continuar sem auth”.

---

## 5. Observabilidade (mínimo para HA)

- Logs estruturados: `sub`, client slug, `session_id`, status — sem tokens
- Métricas futuras (latência Hub tools/call, taxa 401, runs stuck `streaming`) → backlog se não existir
- Não depender só de log local em multi-réplica (agregar depois)

---

## 6. Checklist (feature / serviço novo)

- [ ] Stateless ou estado externalizado (DB/store)?
- [ ] Timeouts em todos os I/O?
- [ ] Retries só onde é seguro / idempotente?
- [ ] Healthcheck + fail-closed auth?
- [ ] Fluxos longos async (accepted + poll) em vez de HTTP infinito?
- [ ] Store multi-instance pensado (ou documentado como single-writer)?
- [ ] [architecture.md](architecture.md) atualizado se mudou topologia?

---

## 7. Fora de escopo (agora)

Kubernetes HPA detalhado, multi-region active-active, Raft/Paxos, saga full
framework, chaos engineering playbooks. Quando necessário: item no backlog ou
spec sob `local-runtime/docs/specs/`.
