# Spec 008 — Modelo de segurança do MCP local

- **Status:** Rascunho
- **Data:** 2026-09-12
- **Implementa:** [ADR 0004](../adr/0004-local-mcp-runtime.md)

## 1. Trust boundary

```text
┌─ zona Loom (authn/authz) ─────────────────────────┐
│  IdP → UserInfo → API ─► mcp-runtime (fachada)    │
└───────────────────────────────────────────────────┘
                         │ só JSON-RPC já autorizado
                         ▼
┌─ zona filho ──────────────────────────────────────┐
│  processo template (npx …) + env de secrets       │
│  rede: só o que o binário do template precisar    │
└───────────────────────────────────────────────────┘
```

O filho **não** recebe o JWT do usuário. Recebe só env de secret + params
públicos. O runtime **não** revalida o IdP.

## 2. IdentityContext

Não criar um tipo novo se `UserInfo` cobrir. Alias documentado:

```text
IdentityContext
  subject     = user.sub
  username    = user.username
  groups      = user.groups
  scopes      = user.scopes
  agent_id    = agente do invoke
  session_id  = InvocationSession.session_id (opcional)
```

O runtime exige `mcp:read` para `list_tools` / health e o mesmo scope (ou
`invoke` no caminho de chat) para `call_tool`. Escrita de catálogo continua
`mcp:write`.

Independência: nenhum import de Keycloak/Entra no pacote do runtime.

## 3. Autorização User → Agent → MCP → Tool

Ordem no `call_tool` e ao anexar conector:

1. Usuário autenticado (`get_current_user`)
2. Scope suficiente
3. Agente existe e o usuário pode invocá-lo (regra de grupo já em
   `invocations.py`)
4. `McpServerAccess` para `(server_id, persona_id=agent.id)`:
   - sem regra → **deny** (fecha a lacuna atual)
   - `all_tools` → ok
   - `selected_tools` → `name` ∈ `allowed_tool_names`
5. Só então encaminha `tools/call` ao stdio

O mesmo filtro aplica em `tools/list` (não vazar tools negadas).

## 4. Registration confiável (anti RCE)

| Controle | Regra |
| --- | --- |
| Allowlist de template | só ids em `etc/mcp-templates/` |
| Allowlist de command | interseção template ∩ `{npx,uvx,python,python3,node}` |
| Args | só os do arquivo + placeholders validados |
| Sem shell | `Popen(list, shell=False)` |
| Params | regex/schema; rejeitar `..`, espaços, metachar de shell |
| Path | cwd fixo do template ou workspace allowlisted |
| Sem download arbitrário de URL como command | |

Ataque “`command=bash -c curl|sh`” é impossível se o cliente não envia
`command`.

## 5. Secrets

```text
SecretReference { name, backend: env | secrets_manager, ref }
```

- `env`: lê `os.environ[ref]` **no host do runtime** (compose `.env`),
  injeta no filho com o nome que o template pede.
- `secrets_manager`: `get_secret(ref, region)` — implementação atual.

Interface `SecretBackend.resolve(ref) -> str` no runtime. O FastAPI não
repassa o valor em JSON para o browser.

Nunca retornar secret em: respostas MCP, logs, traces, erros, prompts,
`token_info`. Mascarar valores que casem com o secret conhecido (prefixo).

Não acoplar o **tipo** `SecretReference` ao AWS. Só o backend
`secrets_manager` chama `secrets.py`.

## 6. Isolamento

v1 (compose):

- um container `mcp-runtime`; filhos são subprocessos desse container;
- sem bind do `$HOME`;
- rede: o container precisa alcançar a API do Azure DevOps (saída HTTPS);
  não publicar a fachada além de `127.0.0.1`.

v2 (opcional, spec 006): `runtime.kind=container` por template.

O MCP **não** acessa o processo do uvicorn (PID namespace do serviço).

## 7. Ameaças e mitigação

| Ameaça | Mitigação |
| --- | --- |
| Command injection no registro | templates + `shell=False` |
| Usuário sem role chama Azure DevOps | token Loom + scopes + access rules |
| PAT no log do LiteLLM/agente | redaction; filho não ecoa PAT; runtime não loga env |
| SSRF via fachada | fachada só no runtime; `net_guard` no backend ao chamar o runtime |
| MCP malicioso no template | review de PR do yaml; pin de pacote (`@azure-devops/mcp@x.y`) |
| Escape do stdio (tool devolve secret) | redaction best-effort no envelope de resposta |
| Agente AWS alcança runtime local | não incluir stdio no snapshot de deploy AgentCore (007) |
| Replay de tools/call | authz por request; sem session cookie no runtime |

## 8. MCP remotos

Nenhuma mudança de auth OAuth2/API key dos servidores HTTP. A branch
`stdio` é aditiva. Testes SSRF existentes (`test_mcp_ssrf.py`) permanecem.
