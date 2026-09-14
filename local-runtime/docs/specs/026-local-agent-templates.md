# Spec 026 — Templates de agents locais

- **Status:** A2 em curso (create/edit local via BFF/UI; A1 loader ok)
- **Data:** 2026-09-14
- **Atualizado:** 2026-09-14 — A2 create `/api/agents/local` + template genérico `assistente-local`
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

Exemplo **genérico** (um molde → vários agents com objetivos diferentes via `params`):

```yaml
id: assistente-local
display_name: Assistente Local
description: |
  Molde genérico para agents source=local.
system_prompt: |
  Você é um assistente local do Loom.
  Objetivo deste agent: {{params.objective}}
model_id: cursor-local
allowed_model_ids:
  - cursor-local
  - mock-echo
params_schema:
  objective:
    type: string
    description: Objetivo / papel deste agent
tags:
  loom:application: local
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

## 6. UX (alvo A2) — implementado

- Agents → Add → aba **Local**: escolher template → params (`objective`) → Create
- Detail local: editar behavior + **Reset to template**
- APIs: `GET /api/agents/local-templates`, `POST /api/agents/local`,
  `POST /api/agents/{id}/local-behavior`

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
      (ex. `assistente-local.yaml`)
- [x] Loader allowlist (id desconhecido → erro claro)
- [x] Teste unitário: parse + reject schema inválido
- [x] Docs: ADR 0013 + este spec + entrada changelog
- [x] Sem mudança obrigatória de Core nesta fase

### A2

- [x] Create local via BFF/UI a partir do template
- [x] Edit behavior + reset to template no Detail
- [x] Template genérico com `params.objective`

## 9. Não fazer

- Template que spawna container por agent.
- Duplicar catálogo fora de `agents`.
- Tratar `agents/strands_agent` como template local.
