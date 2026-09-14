# Docs do fork (`local-runtime/docs`)

**Única casa de documentação deste fork** (guias, regras, ADRs, specs, changelog).
Não criar documentação nova em `docs/` na raiz do Loom.

## Comece aqui

| Guia | Conteúdo |
|------|----------|
| [guide/overview.md](guide/overview.md) | O que é o fork, mapa do repo, URLs |
| [guide/architecture.md](guide/architecture.md) | C4 L1–L3 + modelo de dados |
| [guide/scalability-reliability.md](guide/scalability-reliability.md) | Escala, HA, falhas, idempotência |
| [guide/getting-started.md](guide/getting-started.md) | `make local.up`, login, Cursor ↔ Hub |
| [guide/development.md](guide/development.md) | Makefile, plugin, sidecars, padrões, segurança |
| [guide/python-best-practices.md](guide/python-best-practices.md) | SOLID, Clean Code, GoF, hexagonal (alvo) |
| [guide/security.md](guide/security.md) | OWASP/RFC filtrados — API, OAuth, PII, injection |
| [guide/mcp-hub.md](guide/mcp-hub.md) | Operar Hub / agents as tools |
| [guide/upstream-sync.md](guide/upstream-sync.md) | Puxar o Loom público com o changelog |
| [guide/rules.md](guide/rules.md) | **Regras canônicas** — Core vs extension |

## Política e decisões

| Documento | Conteúdo |
|-----------|----------|
| [CHANGELOG-LOOM-FORK.md](CHANGELOG-LOOM-FORK.md) | Divergência vs upstream (paths Core) |
| [backlog/refactoring.md](backlog/refactoring.md) | Oportunidades de refactor (aguardar Dev) |
| [adr/README.md](adr/README.md) | ADRs 0001–0012 |
| [specs/README.md](specs/README.md) | Specs 001–025 |

## Agentes de IDE (só pointers)

| Ferramenta | Pointer |
|------------|---------|
| Cursor | `.cursor/rules/prefer-local-runtime-extension.mdc` |
| Claude Code | `CLAUDE.md` (raiz) |

Ordem sugerida: **este README** → [guide/rules.md](guide/rules.md) → guia / ADR / spec da tarefa.
