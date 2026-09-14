# Specs da extensão

ADRs: [../adr/README.md](../adr/README.md)

Todas as specs do fork moram **aqui** (`local-runtime/docs/specs/`). Não criar em `docs/` na raiz do Loom.

## Índice

### IdP / stack local

- [001 — IdP abstraction](001-idp-abstraction-layer.md)
- [002 — Docker compose stack](002-local-docker-compose-stack.md)
- [003 — LiteLLM sole gateway](003-litellm-as-sole-llm-gateway.md)
- [004 — Cursor custom LLM](004-cursor-custom-llm-provider.md)

### MCP local

- [005 — Existing MCP architecture](005-existing-mcp-architecture.md)
- [006 — Local MCP runtime](006-local-mcp-runtime.md)
- [007 — Registration](007-local-mcp-registration.md)
- [008 — Security](008-local-mcp-security.md)
- [009 — Azure DevOps example](009-azure-devops-mcp-example.md)
- [010 — Observability](010-local-mcp-observability.md)
- [015 — Grafana / Rancher stdio](015-grafana-rancher-mcp-stdio.md)

### Agent runtime

- [011 — Contract](011-local-agent-runtime-contract.md)
- [012 — Security](012-local-agent-runtime-security.md)
- [013 — Observability](013-local-agent-runtime-observability.md)
- [014 — Orientador / ADO acceptance](014-local-agent-orientador-ado-acceptance.md)
- [026 — Local agent templates](026-local-agent-templates.md)
- [027 — Worker pool / escala / sessão](027-local-agent-worker-pool.md)

### MCP Hub

- [016 — Contract](016-mcp-hub-contract.md)
- [017 — Session](017-mcp-hub-session.md)
- [018 — Allowlist](018-mcp-hub-allowlist.md)
- [019 — Security](019-mcp-hub-security.md)
- [020 — Observability](020-mcp-hub-observability.md)
- [021 — Clients](021-mcp-hub-clients.md)
- [022 — Client identification](022-mcp-hub-client-identification.md)
- [023 — Profile grants](023-mcp-hub-profile-grants.md)
- [024 — OAuth](024-mcp-hub-oauth.md)
- [025 — Agents as tools](025-mcp-hub-agents-as-tools.md)
