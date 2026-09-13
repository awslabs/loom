# Spec 014 — Aceite: Orientador local + LiteLLM + Azure DevOps MCP

- **Status:** Rascunho
- **Data:** 2026-09-13
- **Implementa:** [ADR 0005](../adr/0005-local-agent-runtime.md)
- **Depende de:** [011](011-local-agent-runtime-contract.md), [012](012-local-agent-runtime-security.md), [013](013-local-agent-runtime-observability.md), [009 — Azure DevOps MCP](009-azure-devops-mcp-example.md)
- **Não é** um adapter Azure. É o critério de maturidade **M1+M2**.

## 1. Objetivo da prova

Demonstrar que um agente `source=local` (Orientador Acadêmico) no Chat
usa o catálogo MCP do Loom **de verdade**, inclusive stdio via
`mcp-runtime`, com o mesmo gesto de UI dos agentes AgentCore/harness.

```text
Usuario (Chat)
  → Backend (ACL + payload)
    → agent-runtime
      → LiteLLM (modelo: orientador-academico ou cursor-local)
      → mcp-runtime → Azure DevOps MCP (stdio)
```

## 2. Pré-condições

1. Stack compose saudável: backend, LiteLLM, mcp-runtime, agent-runtime,
   Keycloak, frontend.
2. `AZURE_DEVOPS_PAT` no `.env`; MCP `azure-devops` cadastrado; tools
   refreshed; `McpServerAccess` para o agente Orientador com
   `selected_tools` (sem tools destrutivas).
3. Usuário `admin` / grupo com `invoke` + acesso ao agente.
4. Modelo LiteLLM disponível (mock `orientador-academico` basta para
   provar o **fio** MCP; `cursor-local` é opcional e só valida o hop do
   adapter — o tool loop continua no agent-runtime).

## 3. Cenários de aceite

### 3.1 Connector habilitado funciona

1. Abrir Chat → agente Orientador.
2. Habilitar connector Azure DevOps.
3. Prompt que force tool use (ex. listar projetos / work items da org).
4. **Esperado:** SSE com resposta que use dados reais do ADO; logs
   `agent_runtime_tool` + `mcp_tool_call` com `status=ok`; PAT ausente
   do log e do SSE.

### 3.2 ACL deny

1. Remover a tool usada da allowlist (ou negar o server no access).
2. Repetir prompt.
3. **Esperado:** 403 no resolve **ou** `mcp_denied` sem chamada ao
   filho; usuário vê erro claro; processo Azure não é invocado.

### 3.3 Sem connector

1. Desmarcar o connector.
2. Prompt pedindo ADO.
3. **Esperado:** modelo responde sem tools ADO (não inventa sucesso de
   API); payload `mcp_servers` vazio no agent-runtime.

### 3.4 Isolamento

1. Durante um invoke longo, matar só o worker/sessão do agent-runtime
   (ou cancelar).
2. **Esperado:** backend e UI de catálogo continuam; nova invoke sobe
   sessão nova; mcp-runtime permanece healthy.

### 3.5 Paridade de transporte

1. (Se existir) um MCP `streamable_http` remoto de teste no catálogo +
   access.
2. Invoke local com esse connector.
3. **Esperado:** mesmo caminho de UI; agent-runtime chama o endpoint
   HTTP; stdio e HTTP coexistindo no mesmo payload.

### 3.6 Regressão AgentCore

1. Agente deploy/harness (se houver credencial AWS no ambiente).
2. **Esperado:** comportamento anterior; tentativa de anexar MCP stdio
   no deploy continua **400** (ADR 0004).

## 4. Não-critérios (fora desta prova)

- OBO / Memory / A2A / elicitation
- Container-por-sessão
- Paridade de custo AgentCore
- Trocar o framework interno do agent-runtime

## 5. Definição de pronto (M1+M2)

- [ ] `source=local` não chama LiteLLM a partir do uvicorn
- [ ] Specs 011–013 respeitadas (contrato, token, logs)
- [ ] Cenários 3.1–3.4 verdes no compose local
- [ ] 3.5 e 3.6 verdes ou explicitamente N/A documentado
- [ ] Documentação do `make local.up` menciona `agent-runtime`
- [ ] ADR 0005 status pode ir para **Aceita** após esta prova
