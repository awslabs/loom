# Desenvolvimento

## Interface de comandos

Sempre consulte o `makefile` na raiz antes de inventar scripts:

```bash
make help
```

Targets locais relevantes: `local.up`, `local.down`, `local.reset`, `local.logs`,
`local.ps`, `local.build`, `local.cursor-adapter`, `local.*.test`, `extension.install`.

Compose efetivo:

```text
docker compose -f docker-compose.yml -f local-runtime/compose/overlay.yml …
```

## Configuração

- Parâmetros injetáveis: preferir `etc/environment.sh` / `.env` (gitignored) conforme o stack.
- Não commitatar secrets; ver [security.md](security.md) e secção [Segurança](#segurança) abaixo.

## Dependências

| Stack | Ferramenta | Notas |
|-------|------------|--------|
| Python (agents / sidecars) | `uv` (`uv venv`, `uv pip install`) | `.venv` por serviço/agent quando aplicável |
| TypeScript (frontend / plugin) | `npm` | `node_modules` no diretório do pacote |
| JSON na CLI | Preferir `jq` a `python -m json.tool` | |

Testes unitários de sidecars (sem PAT/API key quando possível):

```bash
make local.mcp-runtime.test
make local.cursor-adapter.test
make local.agent-runtime.test
```

## Plugin UI (`local-runtime/plugin`)

- Entry: `local-runtime/plugin/src/register.tsx` → `host.addExtension({…})`
- Alias Vite / mount Docker: `@loom-ext/local-runtime` → `local-runtime/plugin`
- `make extension.install` só valida que o entry existe (alias já resolve)

Telas novas de ops → **plugin**, não páginas novas no `frontend/src/pages` do host,
salvo impossibilidade (ver [rules.md](rules.md)).

## Sidecars (`local-runtime/services`)

| Serviço | Porta típica | Função |
|---------|--------------|--------|
| mcp-hub | 8790 | MCP OAuth + tools allowlist / agents |
| mcp-runtime | (internal) | Supervisor stdio MCP |
| agent-runtime | 8766 | Loop de agent local |
| cursor-adapter | 8765 | Provider LiteLLM `cursor-local` |

Lógica de runtime, Popen, tool loop e PATs **não** vão no FastAPI do Loom nem no
bundle do plugin.

## Padrões de código (fork)

Boas práticas Python (SOLID, GoF, hexagonal **alvo**):
[python-best-practices.md](python-best-practices.md).
**Não** refatorar sidecars até o Dev pedir explicitamente.

### Python

- Type hints em todas as assinaturas
- Preferir `unittest` nos testes de sidecars/agents
- Preferir SQLAlchemy no backend Loom (quando tocar Core — só com ok do Dev)
- PEP 8

### TypeScript

- ESM
- Tipagem estrita (`any` só se inevitável)
- UI: alinhada ao host (React, Tailwind/shadcn quando no bundle Loom)

### Backends Loom (quando Core for inevitável)

- FastAPI + testes de contrato das respostas
- BFF autenticado com JWT do usuário; tokens de sidecar via service token
- Exige autorização do Dev — ver [rules.md](rules.md)

### AWS / IaC (se aplicável no Core)

- Least privilege em IAM
- Naming `resource-name-${STAGE}`
- Deploy via SAM CLI quando o fluxo Loom usar IaC

## Segurança

Guia completo (OWASP filtrado, OAuth/JWT, PII, injection): [security.md](security.md).

Antes de commit:

- Sem credenciais/tokens em arquivos trackeados
- Secrets só em `.env` (gitignored), secrets manager, ou Parameter Store
- Revisar o diff; `git-secrets` se disponível

## Documentação

- **Novos** ADRs/specs/guias → `local-runtime/docs/`
- Toda mudança **Core** → entrada em [CHANGELOG-LOOM-FORK.md](../CHANGELOG-LOOM-FORK.md)
- Não criar docs novas em `docs/` na raiz do Loom

## Deploy / parâmetros

1. Ajustar `.env` / `etc/environment.sh` conforme o alvo
2. `make <target>` (ex.: `local.up`)

## Próximo

- [python-best-practices.md](python-best-practices.md)
- [upstream-sync.md](upstream-sync.md)
- [mcp-hub.md](mcp-hub.md)
