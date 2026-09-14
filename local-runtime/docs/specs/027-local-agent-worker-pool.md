# Spec 027 — Pool de workers do agent-runtime (escala e sessão)

- **Status:** Rascunho (A0 parcial no compose; A3 = K8s)
- **Data:** 2026-09-14
- **Implementa:** [ADR 0013](../adr/0013-local-agent-templates-worker-pool.md)
- **Depende de:** [Spec 011](011-local-agent-runtime-contract.md),
  [Spec 012](012-local-agent-runtime-security.md),
  [Spec 026](026-local-agent-templates.md),
  [guide/scalability-reliability.md](../guide/scalability-reliability.md)

## 1. Objetivo

Fixar como o **agent-runtime** escala e como a **conversa** permanece
correta com várias réplicas — compose (teste) e Kubernetes (alvo).

Princípio: **registro ≠ instância**. Workers genéricos; escopo no
request; estado de conversa no control plane.

## 2. Comunicação (sem broker)

```text
Chat / Hub MCP
  → BFF (JWT, ACL, sessão DB, resolve template)
  → HTTP POST /v1/invoke  (Bearer service token)
  → SSE session_start | chunk* | session_end | error
```

- **Não** há Kafka (nem fila) no caminho do turno conversacional.
- Mesmos eventos que AgentCore do ponto de vista do Chat.

## 3. Pool de workers

### 3.1 Compose (A0 — feito / baseline)

- Serviço `agent-runtime` **sem** publish de porta no host (evita
  conflito ao escalar).
- `make local.up` usa `--scale agent-runtime=${AGENT_RUNTIME_REPLICAS:-2}`.
- Backend: `AGENT_RUNTIME_URL=http://agent-runtime:8766` — DNS
  round-robin da rede Compose.
- Cada réplica: `AGENT_RUNTIME_MAX_SESSIONS` **por processo**.

### 3.2 Kubernetes (A3)

| Recurso | Papel |
|---------|--------|
| Deployment `agent-runtime` | N réplicas; mesma imagem; env LiteLLM + tokens |
| Service ClusterIP | `agent-runtime:8766` |
| HPA | CPU e/ou métrica custom (sessões ativas / RPS) |
| ConfigMap | templates YAML (Spec 026), se não forem só no BFF |
| NetworkPolicy | só BFF / mesh interno fala com o Service |

Pods **não** recebem `CURSOR_API_KEY` / bind-mount de workspace de
developer. Modelos de prod = LiteLLM → OpenAI/Anthropic/etc.

### 3.3 O que o worker *não* guarda entre turnos

- Histórico completo da conversa
- “Sou o agent X” como identidade de boot
- Knowledge files do host (salvo modelo/dev path explícito fora deste pool)

Escopo chega no JSON do invoke (Spec 011 + prompt resolvido Spec 026).

## 4. Estado de conversa

| Camada | Responsabilidade |
|--------|------------------|
| Postgres (BFF) | `session_id`, invocations, status, `response_text`, user binding |
| BFF | Authz; montar payload; proxy SSE; reabrir sessão em mensagens seguintes |
| Worker | Loop do turno; cancel local (`/v1/sessions/{id}/cancel`) best-effort |
| Browser | UI; reenvia mensagens via BFF com sessão selecionada |

### 4.1 Multi-réplica

1. Turno 1 → LB → pod A → BFF persiste chunks/status.
2. Turno 2 → LB → pod B (pode ser outro).
3. BFF inclui no payload o contexto necessário (`prompt` da vez +
   system + o que a política de histórico exigir). Pod B **não** precisa
   da RAM do pod A.

### 4.2 Cancel

- Hoje: cancel in-memory **por processo** — com 2+ réplicas pode falhar
  se o cancel bater no pod errado.
- Alvo: cancel coordenado no BFF (marcar sessão cancelled; worker
  observa flag no loop **ou** cancel só afeta o stream HTTP atual
  derrubando a conexão).

Critério A3: documentar e testar cancel com N>1.

### 4.3 SSE e fim de stream

Workers **devem** fechar o body HTTP após `session_end` /
`error` (`Connection: close` ou equivalente). Cliente BFF não pode
ficar em `streaming` eterno (já mitigado no agent-runtime).

## 5. Capacidade e limites

- `AGENT_RUNTIME_MAX_SESSIONS` por réplica; pool efetiva ≈
  `replicas × max_sessions` (upper bound otimista).
- Timeouts: `options.timeout_s` no contrato; HPA não substitui timeout.
- Fail-closed: sem `AGENT_RUNTIME_TOKEN` → 401.

## 6. Critérios de aceite

### A0 (compose)

- [x] ≥2 réplicas via `AGENT_RUNTIME_REPLICAS` / `make local.up`
- [x] Sem porta host obrigatória no serviço escalado
- [ ] Dois invokes concorrentes completam `session_end` (teste manual ou CI smoke)

### A3 (K8s)

- [ ] Manifest/helm ou doc de deploy do Deployment+Service+HPA
- [ ] BFF aponta `AGENT_RUNTIME_URL` ao Service
- [ ] Rolling update sem quebrar Chat (readiness = `/health`)
- [ ] Política de histórico entre turnos documentada e coberta por teste

## 7. Não fazer

- Sticky session como requisito de correção (só otimização).
- Um Deployment por `template_id` / agent id como default.
- Estado de conversa só em Redis do worker sem o BFF (evitar segunda
  fonte de verdade sem ADR).
- Kafka no hot path do Chat.
