# Regras do fork (IDE-agnostic)

**Fonte canônica** das regras de colocação de código e docs neste fork.
Ferramentas de agente (Cursor, Claude Code, etc.) **não** devem duplicar o
texto — apenas apontar para este arquivo e pedir leitura/cumprimento.

Relacionados:

- Changelog: [CHANGELOG-LOOM-FORK.md](../CHANGELOG-LOOM-FORK.md)
- Arquitetura C4 + dados: [architecture.md](architecture.md)
- Escalabilidade / HA / idempotência: [scalability-reliability.md](scalability-reliability.md)
- Backlog de refactors: [refactoring.md](../backlog/refactoring.md)
- Índice docs: [README.md](../README.md)
- ADR 0006: [0006-local-runtime-extension-repo.md](../adr/0006-local-runtime-extension-repo.md)
- ADRs / specs: [../adr/](../adr/) · [../specs/](../specs/)

Upstream: [awslabs/loom](https://github.com/awslabs/loom).

---

## Princípio (obrigatório)

**Alterações e features novas moram em `local-runtime/`.**

Isso inclui UI (`plugin/`), sidecars (`services/`), overlay, templates e
documentação (`docs/`). O default é **nunca** editar o core do Loom.

Tocar o Loom (`backend/`, `frontend/` do host fora do Extension Host,
`docker-compose.yml` / `makefile` da raiz, ou outros paths da plataforma) é
**exceção**, não atalho.

---

## Não refatorar sem pedido do Dev

**Não refatore nada** (local-runtime, plugin, sidecars, Core, “limpeza” de
passagem, migração hexagonal, rename em massa, etc.) **sem solicitação
explícita do Dev**.

- Feature pedida ≠ licença para reescrever o módulo ao redor
- Guia de boas práticas / hexagonal = **alvo**; não dispara migração sozinho
- “Encontrei cheiro de código” ≠ “vou arrumar agora”

### Se algo merecer refatoração

1. **Não** abra diff de refactor
2. Registre a oportunidade em [../backlog/refactoring.md](../backlog/refactoring.md) com:
   - **id** (ex.: `REF-2026-09-14-01`)
   - **data de registro**
   - **área / paths**
   - **oportunidade** (o que melhorar)
   - **motivo** (por que importa)
   - **complexidade** (`baixa` | `média` | `alta`)
   - **risco** (`baixo` | `médio` | `alto` — testes, sync upstream, runtime)
   - **status** (`open` até o Dev mudar)
3. **Avise o Dev** no chat (resumo + link/id do item)
4. **Aguarde** o Dev pedir atuação em um item específico

Só então implemente o escopo que ele autorizar.

---

## Colocação padrão

| Tipo de trabalho | Onde colocar |
| --- | --- |
| UI (telas, nav, ops) | `local-runtime/plugin/` via Extension Host (`register` → `host.addExtension`) |
| Sidecars, supervisors, MCP Hub data plane, adapters | `local-runtime/services/` + `local-runtime/compose/overlay.yml` |
| **Docs** (ADRs, specs, changelogs, estas regras) | `local-runtime/docs/` **somente** — nunca arquivos novos em `docs/` na raiz |
| Templates / config local de stack | `local-runtime/templates/`, `etc/docker/` quando for stack local |

---

## Exceções que tocam o Loom — só com autorização do Dev

Antes de **qualquer** diff em paths Core, o agente **deve parar** e pedir
validação/autorização explícita do **Dev** (humano dono do fork).

Não implementar, commitutar nem “já deixar pronto” o Core sem esse ok.

### Quando uma exceção *pode* fazer sentido (ainda assim pedir ok)

Só depois de concluir que **não** há alternativa em `local-runtime/`, por exemplo:

- Ganchos estáveis do **Extension Host** (`frontend/src/extensions/*`)
- Auth / IdP / RBAC fail-closed
- **BFF** de catálogo / invoke que precisa rodar no FastAPI do Loom com JWT do usuário
- Bugs no Agent Detail / Chat compartilhados que não possam ser uma página do plugin

### O que pedir ao Dev (obrigatório na mensagem)

1. **Motivo** — por que `local-runtime/` é impossível ou insuficiente
2. **Alternativas rejeitadas** — o que foi considerado na extension e por que não serve
3. **Escopo mínimo** — arquivos/áreas Core que seriam tocados e o gancho menor possível
4. **Impacto no sync** — risco frente a `upstream` (awslabs/loom)
5. Pedido explícito: *autoriza esta exceção Core? (sim/não)*

Só após **autorização explícita** do Dev:

1. Preferir o gancho **menor** (BFF / host API) a editar UI global do Loom
2. Implementar o escopo autorizado (nada além)
3. Registrar em [CHANGELOG-LOOM-FORK.md](../CHANGELOG-LOOM-FORK.md) (Zona **Core**), citando o motivo e que houve ok do Dev
4. Atualizar [architecture.md](architecture.md) se a mudança alterar containers, fluxos ou dados

---

## Manutenção da arquitetura (obrigatório)

O documento [architecture.md](architecture.md) (C4 L1/L2/L3 + modelo de dados)
é a visão viva do sistema.

**Sempre que** mudar (no mesmo PR / entrega):

- containers, portas, redes ou dependências entre serviços
- fluxos de auth (IdP, Hub OAuth, service tokens)
- stores (Postgres, Hub store, novos persistentes) — indicar se **Core Loom**, **Fork (PG)** ou **local-runtime**
- tabelas/colunas ORM relevantes ao fork
- limites Extension Host ↔ plugin ↔ sidecars

Ações:

1. Atualizar diagramas / seções afetadas em `architecture.md`
2. Diagramas: Mermaid **portátil** (`flowchart`, `sequenceDiagram`, `erDiagram`) — **não** `C4Context` / `C4Container` / `C4Component`
3. Endpoints descritos por **papel + env**, não por host:porta hardcoded como contrato
4. Bump da linha **Última revisão** (data)
5. Se Zona **Core** ou store novo: também [CHANGELOG-LOOM-FORK.md](../CHANGELOG-LOOM-FORK.md)

Não deixar a arquitetura “para depois”. Entrega incompleta sem doc alinhada.

---

## Exemplos

```text
✅ Feature/UI/ops em local-runtime/plugin ou services
✅ Novo ADR/spec/guia sob local-runtime/docs/
✅ Registrar refactor no backlog e avisar o Dev (sem diff)
✅ Parar e pedir ok do Dev antes de qualquer patch em backend/ ou frontend/ host
❌ Refatorar “de passagem” ou migrar hexagonal sem pedido
❌ Alterar Loom “porque é mais rápido” sem autorização
❌ Abrir PR/diff Core sem detalhar motivos e alternativas
❌ Novos arquivos em docs/ na raiz do repo
✅ Atualizar architecture.md no mesmo PR em que muda o Hub/BFF/store
❌ Entregar feature de infra sem revisar C4 / modelo de dados
```

---

## Checklist

### Sempre

- [ ] A mudança cabe em `local-runtime/plugin`, `services` ou `docs`?
- [ ] Docs novos só sob `local-runtime/docs/`?
- [ ] Sem refactor não pedido? (oportunidades → backlog + aviso ao Dev)
- [ ] [architecture.md](architecture.md) atualizado se containers/fluxos/dados mudaram?

### Se achar que precisa de Core (exceção)

- [ ] Parei **antes** de editar paths Loom?
- [ ] Detalhei motivos, alternativas rejeitadas, escopo e risco upstream?
- [ ] Obtive **autorização explícita** do Dev?
- [ ] Changelog do fork atualizado (Zona **Core**) após o ok?

---

## Como os agentes devem carregar isto

Ler o hub [`README.md`](../README.md), depois **este arquivo**, depois o guia da
tarefa. Pointers de IDE (sem duplicar texto):

| Ferramenta | Arquivo ponte |
| --- | --- |
| Cursor | `.cursor/rules/prefer-local-runtime-extension.mdc` |
| Claude Code | `CLAUDE.md` (raiz) |

Qualquer nova IDE: pointer fino → `local-runtime/docs/README.md` + `guide/rules.md`.
