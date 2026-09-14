# Spec 009 — Azure DevOps MCP como primeiro exemplo

- **Status:** Rascunho
- **Data:** 2026-09-12
- **Implementa:** [ADR 0004](../adr/0004-local-mcp-runtime.md)
- **Não é** um adapter. É um template + um secret.

## 1. Objetivo da prova

```text
Loom (catálogo + IdentityContext)
  → Local MCP Runtime
    → stdio: npx -y @azure-devops/mcp <organization>
      → Azure DevOps REST
```

Para o agente e para o Chat, o conector chama-se **Azure DevOps** e usa a
URL interna da fachada. Ninguém no core importa SDK Azure.

## 2. Template (`etc/mcp-templates/azure-devops.yaml`)

Campos conforme spec 007. `organization` é o único param público.
Secret: PAT com o env que o pacote oficial documentar no momento da
implementação (confirmar no README de `@azure-devops/mcp`; não chutar
no código). Pin de versão no `args` (`@azure-devops/mcp@<versão>`).

O core do runtime **não** contém string `azure` exceto neste arquivo e
nos testes de exemplo.

## 3. Registro local (operador)

1. Colocar o PAT no `.env` do compose, por exemplo `AZURE_DEVOPS_PAT=`.
2. No Loom: MCP → New → transport `stdio` → template `azure-devops` →
   organization → secret_ref `env:AZURE_DEVOPS_PAT`.
3. Access: persona do agente de teste → `selected_tools` com o conjunto
   permitido (work items, repos, PRs, pipelines). Negar tools destrutivas
   (`delete_repository`, manage permissions, etc.) pelo nome que o
   `tools/list` devolver — a allowlist é **depois** do primeiro refresh.

## 4. Tools

Não hardcodar nomes de tools Azure no runtime. Depois do `initialize`,
`tools/refresh` preenche `mcp_tools` como hoje. A política é
`McpServerAccess.allowed_tool_names`.

Critério de aceite da prova:

- `test-connection` / initialize = ok
- `tools/list` devolve tools do pacote
- `tools/call` de uma tool allowlisted (ex. get work item) funciona com
  PAT válido
- tool deny-listed → 403 do runtime, filho não é chamado
- PAT não aparece em log do backend, do runtime, nem no SSE do chat
- um MCP `streamable_http` já cadastrado continua igual

## 5. Fora de escopo desta prova

- OAuth Azure AD no lugar do PAT (pode ser um segundo template depois)
- Rodar o `npx` dentro do AgentCore na AWS
- UI específica “Azure DevOps” além do dropdown de template
