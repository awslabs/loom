# Spec 026 — Templates de agents locais

- **Status:** A1 implementado (loader + `guia-biblioteca.yaml`; A2+ pendente)
- **Data:** 2026-09-14
- **Atualizado:** 2026-09-14 — A1 loader/tests
- **Implementa:** [ADR 0013](../adr/0013-local-agent-templates-worker-pool.md)
- **Depende de:** [ADR 0005](../adr/0005-local-agent-runtime.md),
  [Spec 011 — contrato](011-local-agent-runtime-contract.md),
  [ADR 0004 / templates MCP](../adr/0004-local-mcp-runtime.md)

## 1. Objetivo

Definir **templates YAML allowlisted** para agents `source=local`, no
mesmo espírito dos templates MCP (`mcp-runtime/templates/*.yaml`):

- behavior / `system_prompt` versionáveis em git;
- create/registro sem depender do formulário AgentCore;
- workers genéricos recebem o escopo resolvido no invoke (ADR 0013).

## 2. Onde vive

```text
local-runtime/services/agent-runtime/templates/*.yaml
```

- Dono: **agent-runtime** (extension).
- Mount ro no compose (espelhar padrão mcp-runtime).
- **Não** colocar em `agents/` na raiz (isso é runtime AgentCore AWS:
  `strands_agent` / `adk_agent`).

## 3. Schema YAML (v1)

Exemplo **fictício** (não é um agent de produção do fork):

```yaml
id: guia-biblioteca                 # slug estável = template_id
display_name: Guia da Biblioteca
description: |
  Atendente fictício de uma biblioteca municipal de demonstração.
system_prompt: |
  Você é o Guia da Biblioteca Municipal de Demonstração.
  Responda em português do Brasil, tom cordial e objetivo.
  Quando pedirem dados do acervo demo, use knowledge.files
  (se o modelo tiver tools de FS) ou knowledge.inline se estiver setado.
  Não invente empréstimos reais nem altere fichas de leitores.
model_id: cursor-local              # default LiteLLM model id
allowed_model_ids:
  - cursor-local
  - mock-echo
knowledge:                          # opcional — NÃO é AgentCore Memory
  files:                            # paths relativos ao workspace do adapter (dev)
    - acervo-faq.txt
  inline: ""                        # trecho opcional injetado no system prompt no resolve
mcp:
  # template_ids ou nomes do catálogo Loom que o BFF pode anexar por default
  default_connector_template_ids: []
params_schema: {}                   # params de instanciação (futuro)
secrets: []                         # refs env (futuro)
tags:
  loom:application: demo
```

Regras:

1. `id` = `^[a-z][a-z0-9-]{1,62}$`; único na allowlist.
2. `system_prompt` obrigatório e não vazio.
3. `model_id` deve existir no catálogo LiteLLM local (ou ser documentado
   como mock).
4. Templates **não** embutem `command`/`Popen` — o worker é sempre o
   mesmo `agent-runtime`.
5. Secrets nunca no YAML em claro; só nomes de env (como MCP).

## 4. Resolução no invoke

Control plane (BFF), antes do `POST /v1/invoke`:

1. Carrega agent `source=local` + `template_id` (+ params salvos).
2. Resolve template → `system_prompt` efetivo (+ `knowledge.inline` se
   houver).
3. Sobrescritas por config persistida do agent (se A2 permitir edit)
   ganham de `template` default, com auditoria.
4. Monta payload Spec 011 (`agent.system_prompt`, `model_id`,
   `mcp_servers`, …).
5. Worker **não** lê o YAML do disco no hot path (opcional cache); recebe
   escopo já resolvido. (Em A1 pode ler ficheiro no BFF ou num helper
   extension; em A3 o template pode ir em ConfigMap.)

## 5. Registro no catálogo Loom

| Campo / conceito | Onde |
|------------------|------|
| `agents.source` | `local` (já existe) |
| `template_id` | coluna fork **ou** chave em `AGENT_CONFIG_JSON` até migração |
| `AGENT_CONFIG_JSON.system_prompt` | resolvido do template no create/update |
| tags / allowed models | como hoje |

**Core:** qualquer coluna nova / endpoint create-local / UI Detail exige
**ok explícito do Dev** ([rules.md](../guide/rules.md)). Até lá: seed /
script extension que materializa a partir do YAML.

Fluxo Postgres (materialização, não sync contínuo):

```text
templates/*.yaml  →  create / seed / update  →  row em agents + AGENT_CONFIG_JSON
invoke usa a config materializada; “reset to template” relê o YAML
```

## 6. UX (alvo A2)

- Create local: escolher template → params → Save (sem Agent Behavior
  do formulário harness como único caminho).
- Detail local: editar behavior = editar override do prompt (ou
  “reset to template”).
- Lista: badge `LOCAL` + nome do template.

## 7. Migração de seeds existentes

1. Extrair system prompts hoje hardcoded no seed →
   `templates/<id>.yaml` (um ficheiro por template).
2. Seed passa a referenciar `template_id` (ou continua a copiar prompt
   uma vez na materialização).
3. Ficheiros de knowledge de **dev** (ex. no `CURSOR_WORKSPACE`)
   permanecem fora do Postgres; o template só **documenta** paths em
   `knowledge.files` e/ou usa `knowledge.inline`.

## 8. Critérios de aceite (A1)

- [x] Diretório `templates/` + pelo menos um YAML de exemplo
      (ex. `guia-biblioteca.yaml`)
- [x] Loader allowlist (id desconhecido → erro claro)
- [x] Teste unitário: parse + reject schema inválido
- [x] Docs: ADR 0013 + este spec + entrada changelog
- [x] Sem mudança obrigatória de Core nesta fase

## 9. Não fazer

- Template que spawna container por agent.
- Duplicar catálogo fora de `agents`.
- Tratar `agents/strands_agent` como template local.
