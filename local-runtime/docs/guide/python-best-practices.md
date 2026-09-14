# Boas práticas de desenvolvimento Python (`local-runtime`)

Guia canônico para sidecars e código Python sob `local-runtime/services/`.
Complementa [rules.md](rules.md) (colocação Core vs extension) e
[development.md](development.md) (makefile / tooling).

> **Importante:** este documento define o **alvo**. **Não** refatore serviços
> existentes só porque o guia existe. Sem pedido explícito do Dev: registre em
> [../backlog/refactoring.md](../backlog/refactoring.md) e avise — ver
> [rules.md](rules.md).

---

## Índice

1. [Princípios enxutos (KISS, YAGNI, DRY)](#1-princípios-enxutos)
2. [Clean Code (Python)](#2-clean-code-python)
3. [SOLID](#3-solid)
4. [Object Calisthenics](#4-object-calisthenics)
5. [GoF — Design Patterns](#5-gof--design-patterns)
6. [Arquitetura hexagonal (alvo `local-runtime`)](#6-arquitetura-hexagonal-alvo-local-runtime)
7. [Como implementar uma feature nova](#7-como-implementar-uma-feature-nova)

---

## 1. Princípios enxutos

### KISS (Keep It Simple, Stupid)

Prefira a solução mais simples que resolve o problema **agora**.

- Evite frameworks / abstrações “por se acaso”
- Um módulo claro > hierarquia prematura
- Se o leitor junior não entende em 2 minutos, simplifique

### YAGNI (You Aren’t Gonna Need It)

Não implemente o que ninguém pediu.

- Sem flags “para o futuro”
- Sem ports/adapters extras sem segundo consumidor
- Sem config genérica até existir o 2º caso real

### DRY (Don’t Repeat Yourself)

Normalize **conhecimento**, não só texto colado.

- OK duplicar 3 linhas triviais se a abstração for pior
- Extraia quando a **regra de negócio** se repete (não o syntax sugar)
- Um único lugar para política (ex.: validação de grant) — vários call sites

---

## 2. Clean Code (Python)

### Nomes

- Funções/métodos: verbo (`materialize_agents`, `validate_token`)
- Booleanos: `is_`, `has_`, `can_`
- Evite abreviações obscuras (`mgr`, `tmp2`)

### Funções

- Uma responsabilidade; cabe na tela
- Poucos parâmetros (ideal ≤ 3); use dataclass/`TypedDict` se crescer
- Side effects explícitos (I/O, mutate store) — não esconda em property

### Tipagem

- Type hints em **todas** as assinaturas públicas
- Preferir `Protocol` / `ABC` nas bordas (ports)
- Evitar `Any` salvo boundary JSON externo

### Erros

- Exceções de domínio específicas (`AgentNotAllowed`, `HubUnauthorized`)
- Não engolir `except Exception:` sem log + re-raise ou mapeamento HTTP
- Falha fechada em auth (fail-closed)

### Testes

- Preferir `unittest` nos sidecars (padrão do repo)
- Testar domínio **sem** HTTP real (ports fake)
- Um teste = um comportamento

### Estilo

- PEP 8; formatadores ok se o time já usar
- Imports no topo; sem wildcard `from x import *`

---

## 3. SOLID

| Letra | Significado | Em prática no sidecar |
|-------|-------------|------------------------|
| **S** | Single Responsibility | Classe/módulo com um motivo para mudar |
| **O** | Open/Closed | Estender via novo adapter; não editar o use case a cada protocolo |
| **L** | Liskov | Implementações de port honram o contrato (sem surpresa) |
| **I** | Interface Segregation | Ports pequenos (`TokenValidator`, não `GodClient`) |
| **D** | Dependency Inversion | Domínio depende de **ports** (Protocol/ABC), não de FastAPI/httpx |

Exemplo mental:

```text
Use case "InvokeAgent" → depende de AgentRuntimePort
HTTP adapter e LiteLLM adapter → implementam AgentRuntimePort
```

---

## 4. Object Calisthenics

Regras de disciplina (aplicar com bom senso; não dogmatismo).

| Regra | Intenção | Ajuste Python |
|-------|----------|----------------|
| Um nível de indentação por método | Forçar early return / extract | `if not ok: return` / helpers |
| Não usar `else` | Fluxo linear | Preferir guard clauses |
| Encapsular primitivos | Evitar “stringly typed” | Newtypes / small value objects |
| Coleções de 1ª classe | Não espalhar `list` crua | Tipo `GrantSet`, `ToolAllowlist` |
| Um ponto por linha | Clareza | Evitar `a.b().c().d()` |
| Não abreviar | Legibilidade | Nomes completos |
| Manter entidades pequenas | SRP | Separar HTTP de domínio |
| ≤ 2 variáveis de instância | Objetos coesos | Mais → compor objetos |
| Sem getters/setters cegos | Comportamento no objeto | Métodos que expressam intenção |
| Sem `staticmethod` em excesso | Estado e comportamento juntos | Funções de módulo ok se puro |

**Calisthenics ≠ lei.** Se uma regra atrapalha clareza em um script de 20 linhas, documente o desvio.

---

## 5. GoF — Design Patterns

Catálogo clássico (Gamma et al.). Em Python muitos são idiomáticos (funções 1ª classe, módulos). Use **quando** houver dor real (duplicação, variação, ciclo de vida).

### 5.1 Criacionais

| Pattern | O que faz | Quando usar | Quando evitar |
|---------|-----------|-------------|---------------|
| **Singleton** | Uma instância global | Cache JWKS / config process-wide (com cuidado a testes) | Estado mutável escondido; prefira DI |
| **Factory Method** | Subclasse decide qual produto criar | Famílias de adapters por `source=` | Um `if` único e estável |
| **Abstract Factory** | Família de produtos relacionados | Vários IdPs com pares validator+mapper | Um único provider |
| **Builder** | Monta objeto passo a passo | Payloads MCP / SSE complexos | Dataclass simples basta |
| **Prototype** | Clona protótipo | Templates de grant / tool def | `copy.deepcopy` ocasional |

### 5.2 Estruturais

| Pattern | O que faz | Quando usar | Quando evitar |
|---------|-----------|-------------|---------------|
| **Adapter** | Traduz interface externa → port | HTTP Loom BFF, LiteLLM, Keycloak JWKS | Wrapper sem mismatch |
| **Bridge** | Separa abstração de implementação | Protocolo MCP × transport (stdio/HTTP) | Só uma implementação |
| **Composite** | Árvore de componentes | Allowlist hierárquica de tools | Lista flat |
| **Decorator** | Empilha comportamento | Auth, metrics, logging em port | Subclass explosion |
| **Facade** | API simples sobre subsistema | `LoomClient` agregando vários endpoints | Esconder erros importantes |
| **Flyweight** | Compartilha estado intrínseco | Catálogo grande de tool defs imutáveis | Poucos objetos |
| **Proxy** | Controla acesso ao real | Lazy JWKS, rate limit, auth gate | Indireção sem ganho |

### 5.3 Comportamentais

| Pattern | O que faz | Quando usar | Quando evitar |
|---------|-----------|-------------|---------------|
| **Chain of Responsibility** | Pipeline de handlers | Auth → RBAC → allowlist | Um único check |
| **Command** | Encapsula pedido | Filas de invoke / undo / audit | Call direto basta |
| **Interpreter** | Avalia gramática | DSL de grants (raro) | Parser ad hoc |
| **Iterator** | Percorre coleção | Streams SSE / tools | `for` nativo |
| **Mediator** | Centraliza comunicação | Orquestrar Hub ↔ BFF ↔ store | Acoplamento 1:1 |
| **Memento** | Snapshot de estado | Sessão de agent / draft grants | Persistência simples |
| **Observer** | Pub/sub de eventos | Progress MCP / métricas | Callback único |
| **State** | Comportamento por estado | `streaming` / `complete` / `error` | Enum + ifs curtos |
| **Strategy** | Algoritmo intercambiável | `wait=accepted` vs `complete`; naming collision | Um algoritmo só |
| **Template Method** | Esqueleto + hooks | Fluxo invoke comum com passos plugáveis | Herança forçada — prefira composição |
| **Visitor** | Operação nova sem mudar elementos | Transformar AST de tools | Poucos tipos estáveis |

### Esboço Python (Strategy + Port)

```python
from typing import Protocol

class WaitStrategy(Protocol):
    async def run(self, agent_id: int, prompt: str) -> dict: ...

class AcceptedWait:
    async def run(self, agent_id: int, prompt: str) -> dict:
        # cria job e devolve session_id
        ...

class CompleteWait:
    async def run(self, agent_id: int, prompt: str) -> dict:
        # aguarda resultado com timeout
        ...
```

---

## 6. Arquitetura hexagonal (alvo `local-runtime`)

Hexagonal (Ports & Adapters) isola o **domínio / application** de detalhes de
framework, HTTP, disco e rede.

```text
                    ┌─────────────────────────┐
   HTTP / MCP  ──►  │  adapters/inbound       │
                    └───────────┬─────────────┘
                                ▼
                    ┌─────────────────────────┐
                    │  application (use cases)│
                    │  domain (entities/rules)│
                    └───────────┬─────────────┘
                                ▼
                    ┌─────────────────────────┐
   BFF / FS / LLM ◄─│  adapters/outbound      │
                    └─────────────────────────┘
```

- **Inbound adapters:** HTTP (`http.server` / FastAPI futuro), CLI `__main__`
- **Application:** orquestra use cases; não importa `urllib` / JSON wire format
- **Domain:** regras puras, value objects, erros de negócio
- **Outbound ports:** `Protocol` / ABC definidos junto da application/domain
- **Outbound adapters:** `loom_client`, `store` JSON, OAuth JWKS, LiteLLM

### Estrutura de pastas alvo (por serviço)

Exemplo para um sidecar genérico `{service}/` (ex.: `mcp-hub`, `agent-runtime`):

```text
local-runtime/services/{service}/
├── Dockerfile
├── requirements.txt
├── README.md
├── {package}/                    # ex.: mcp_hub/
│   ├── __init__.py
│   ├── __main__.py               # entry: wiring (composition root)
│   ├── domain/                   # puro — sem I/O
│   │   ├── __init__.py
│   │   ├── model.py              # entities / value objects
│   │   └── errors.py
│   ├── application/              # use cases
│   │   ├── __init__.py
│   │   ├── ports.py              # Protocols (inbound opcional + outbound)
│   │   └── use_cases/            # um módulo por caso de uso
│   │       ├── __init__.py
│   │       └── materialize_agents.py
│   └── adapters/
│       ├── inbound/
│       │   ├── http_app.py       # parse request → chama use case → response
│       │   └── mcp_jsonrpc.py    # se aplicável
│       └── outbound/
│           ├── loom_http.py
│           ├── file_store.py
│           └── oauth_jwks.py
└── tests/
    ├── unit/                     # domain + application com fakes
    └── adapters/                 # contratos HTTP / store (opcional)
```

### Regras de dependência

```text
adapters → application → domain
adapters ↛ domain diretamente para orquestração (podem mapear DTO ↔ model)
domain ↛ adapters, ↛ framework HTTP
__main__ / wiring: único lugar que instancia adapters e injeta nos use cases
```

### Serviços atuais vs alvo

Hoje (`mcp_hub/http_app.py`, `store.py`, …) é um layout **plano**. Este guia é o
**norte**. **Não** migrar automaticamente. Quando o Dev pedir, migrar serviço a
serviço (começar pelo que for mexer na feature).

---

## 7. Como implementar uma feature nova

Checklist alinhado a [rules.md](rules.md) (features em `local-runtime`; Core só
com autorização do Dev).

1. **Escopo** — cabe em qual serviço? Precisa de UI no `plugin/`?
2. **Caso de uso** — nomeie o verbo (`EnableAgentsOnClient`, `PollAgentRun`)
3. **Domain** — modelos e erros; sem HTTP
4. **Ports** — o que o use case precisa do mundo (`ClientStore`, `LoomAgentsApi`)
5. **Application** — implemente o use case dependendo só dos ports
6. **Adapters outbound** — implementações reais + fakes de teste
7. **Adapter inbound** — HTTP/MCP só traduz e chama o use case
8. **Wiring** — `__main__` ou factory de app monta o grafo
9. **Testes** — unit no use case com fake ports; 1–2 testes de adapter se crítico
10. **Docs** — se mudar contrato: spec/ADR sob `local-runtime/docs/`; se tocar Core
    (exceção): parar e pedir ok do Dev + changelog

### Anti-padrões

```text
❌ Colocar regra de grant dentro de http_app.py “só dessa vez”
❌ Importar urllib dentro de domain/
❌ Novo endpoint no Loom BFF sem autorização do Dev
❌ Refatorar o serviço inteiro para hexagonal “de passagem”
```

---

## Referências rápidas

| Tema | Onde |
|------|------|
| Colocação fork / Core | [rules.md](rules.md) |
| Makefile / stack | [development.md](development.md) |
| Hub | [mcp-hub.md](mcp-hub.md) |
| ADR extensão | [../adr/0006-local-runtime-extension-repo.md](../adr/0006-local-runtime-extension-repo.md) |
