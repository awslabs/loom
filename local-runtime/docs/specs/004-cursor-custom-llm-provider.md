# Spec 004 — CustomLLM Cursor (somente DEV local)

## 1. Objetivo

Encapsular o Cursor Agent atrás do LiteLLM para que o Loom continue falando só OpenAI-compatible:

```text
Loom (provider=litellm, model_id=cursor-local)
  → LiteLLM CustomLLM `cursor_agent`
    → adapter HTTP no host
      → Cursor SDK (+ Bridge se o processo for longo/async)
        → Cursor Agent (workspace, tools, MCP, terminal)
```

O Loom **não** importa `cursor_sdk`. O container LiteLLM **não** executa o agente do Cursor.

## 2. LLM provider vs agent backend

| | LLM provider (Anthropic, OpenAI, Bedrock) | Agent backend (Cursor Agent) |
| --- | --- | --- |
| Unidade | completion / chat turn | *run* com tools, filesystem, MCP |
| Estado | stateless por request (salvo histórico nas messages) | sessão durável (`Agent.create` + `send`) |
| Falha | HTTP 4xx/5xx do provider | `CursorAgentError` (nem começou) vs `result.status == "error"` (começou e falhou) |
| MCP | não tem | o agente Cursor possui |

O CustomLLM existe para **adaptar** o segundo ao contrato do primeiro. Não tratar Cursor como `prompt → texto`.

## 3. Topologia (escolha)

| Opção | Ideia | Veredito |
| --- | --- | --- |
| A — Cursor no container do LiteLLM | SDK + workspace montado no processo do proxy | **Rejeitada.** Mistura o gateway com o runtime do agente. |
| B — LiteLLM no host falando com Cursor | Sem Docker para o proxy | **Rejeitada.** Quebra o compose único. |
| C — Adapter no compose, LiteLLM no Docker | CustomLLM HTTP para `http://cursor-adapter:8765` | **Escolhida.** |

O adapter é um serviço do `docker-compose.yml` e sobe com `make local.up`. O workspace do host é bind-montado em `/workspace`. MCP/OAuth do IDE e o app Cursor do desenvolvedor continuam limitados dentro do container — completions usam `cursor_sdk` + `CURSOR_API_KEY`, não o IDE aberto.

A porta publicada no host é só `127.0.0.1:8765`. LiteLLM fala pelo DNS interno `cursor-adapter`, não por `host.docker.internal`.

## 4. SDK e Bridge

Linguagem do adapter: **Python**, porque o CustomLLM do LiteLLM e o resto do backend já são Python. Pacote `cursor-sdk` (`cursor_sdk`).

| Precisa | API |
| --- | --- |
| Um prompt, sem follow-up | `Agent.prompt` (descarta o agente sozinho) |
| Multi-turn / streaming / cancel | `Agent.create` + `agent.send` + `run.messages()` / `run.wait()` |
| Processo servidor (este adapter) | `AsyncClient.launch_bridge()` + `AsyncAgent` — um client por event loop, nunca misturar sync e async |
| Retomar depois de restart | `Agent.resume` — MCP inline **não** persiste; passar de novo |

Bridge é necessário aqui: o adapter é um servidor asyncio. Sem Bridge, o SDK sincrono bloqueia o event loop.

Não: scrapear o IDE, simular teclado, falar com o processo do Cursor, nem fingir que o IDE é uma API OpenAI.

Auth: `CURSOR_API_KEY` só no ambiente do **host** (`.env`, gitignored). Sempre passar `api_key=` explicitamente no `Agent.create`. Modelo local é obrigatório; padrão `composer-2.5` (ou `CURSOR_MODEL`). `local=LocalAgentOptions(cwd=workspace)` **sempre** explícito — nunca cair no default silencioso.

## 5. Message translation

Entrada: `messages` OpenAI (`system` / `user` / `assistant` / `tool`).

Algoritmo:

1. Concatenar *contents* `system` numa preamble (o SDK não tem system role nativo).
2. Histórico `user`/`assistant` vira texto intercalado `User:` / `Assistant:`.
3. `tool` / `tool_calls`: serializar como blocos `[tool_call name=…]` e `[tool_result id=…]`. Não descartar — o Cursor não reexecuta as tools do Loom; isso é contexto.
4. Multimodal: se `content` for lista com `image_url`, registrar `unsupported_part` e omitir a imagem no POC. Não falhar o request só por isso.
5. O prompt enviado ao `send()` é: preamble + histórico + último `user`.

Limitações (aceitáveis no POC): o Cursor Agent **não** reproduz as tools do AgentCore; ele usa as tools do próprio Cursor. Dois loops de agente (Loom/AgentCore e Cursor) não devem ser encadeados no mesmo invoke de produção.

## 6. Sessão

`SessionManager` in-memory (sem Postgres novo):

```text
chave = tenant + agent_id + workspace + session_id
valor = { cursor_agent_id, created_at, last_used_at }
```

- Headers (ou `optional_params`) aceitos pelo CustomLLM e repassados ao adapter: `X-Loom-Session-Id`, `X-Loom-Agent-Id`, `X-Loom-Workspace`.
- Se não vier `session_id`, gerar um por request (one-shot, `Agent.prompt`).
- Reuse: `Agent.resume` se o id ainda for válido; senão `create` e substituir.
- TTL: 60 minutos sem uso; cleanup no `finally` / task periódica. `agent.close()` / context manager — sem dispose vaza executor e Bridge.
- Concorrência: um `asyncio.Lock` por chave. Dois POSTs na mesma sessão serializam.
- Restart do adapter: mapa some. O próximo request cria agente novo. Documentado; persistir seria overkill para POC local.

Workspace: **obrigatório**. `CURSOR_WORKSPACE` no `.env` do host, ou header. Nunca `os.getcwd()` acidental do container.

## 7. Streaming

CustomLLM implementa `completion` e `streaming` / `astreaming`.

```text
Cursor SDKMessage
  assistant.text     → chat.completion.chunk delta.content
  tool / status      → chunk com `x_cursor_event` (extensão) + log
  error              → último chunk + finish_reason=stop + HTTP 502 se o run nem começou
  run.wait() finished → finish_reason=stop
```

Sempre chamar `wait()` mesmo quando houver stream. Cancel: se o LiteLLM fechar o cliente, `run.cancel()` se `run.supports("cancel")`.

Se o SDK não entregar tokens incrementais em algum tipo de evento, justificar no log e emitir um único chunk no final — não inventar tokens.

## 8. Erros

| Situação | HTTP para o LiteLLM | `error.message` (sem segredo) |
| --- | --- | --- |
| Adapter inacessível | 503 | `cursor_adapter_unavailable` |
| Bridge/SDK startup (`CursorAgentError`) | 503 se `is_retryable` else 401/500 | `cursor_startup_failed` + `retryable` |
| `result.status == "error"` | 200 com texto de falha **ou** 502 `cursor_run_failed` | incluir `run.id`, não o transcript |
| Workspace inexistente | 400 | `invalid_workspace` |
| Timeout | 504 | `cursor_timeout` |
| Permission / tool / MCP | 502 | `cursor_tool_failed` / `cursor_mcp_failed` |
| Sem `CURSOR_API_KEY` | 401 | `cursor_auth_missing` |

Não logar a API key, o Bearer, nem o prompt completo (só `len(messages)` e `model`).

## 9. MCP — decisão

**Alternativa A — Cursor owns MCP** (POC original: MCP do IDE/projeto via
SDK). Válida para experiments no workspace; **não** é o caminho do Chat
Loom com connectors do catálogo.

**Alternativa B — Loom owns MCP via agent-runtime** (**implementada** no Chat).

Para `cursor-local` no Chat com connectors do catálogo:

1. Backend: ACL `McpServerAccess` + `ensure_stdio_ready` +
   `enrich_mcp_servers_for_runtime` (service bearer).
2. `agent-runtime`: `tools/list`, loop OpenAI-tools, `tools/call` no
   mcp-runtime.
3. LiteLLM → cursor-adapter: com tools presentes, **planner mode**
   (`cursor_adapter/planner.py`):
   - Extrai schemas de `body.tools` **ou** do marker
     `<<<loom_openai_tools>>>` nas messages (LiteLLM CustomLLM dropa
     `tools`).
   - Prompt enxuto; Cursor devolve **somente** JSON
     `{"tool_calls":[…]}` ou `{"content":"…"}`.
   - Resposta OpenAI-compatible; `tool_calls` também em `content` JSON
     se o proxy dropar o campo estruturado.
   - **Não** passa `mcp_servers` ao Cursor SDK.
4. `agent-runtime` executa as tools e re-chama o modelo até a resposta
   final.

Critérios: FastAPI = control plane; agent-runtime = mãos; Cursor = cérebro;
sem misturar trust boundary (ADR 0005 alternativa 2 rejeitada).

Pacote: `local-runtime/services/cursor-adapter/` (não mais
`etc/docker/cursor-adapter`).

## 10. Segurança

- `CURSOR_API_KEY` e `CURSOR_WORKSPACE` só em `.env` (já no `.gitignore`). `.env.example` sem valores reais.
- No compose o adapter escuta `0.0.0.0` só na rede Docker; a porta no host é `127.0.0.1:8765`.
- O CustomLLM no container chama só `CURSOR_ADAPTER_URL`. Sem bind-mount do `$HOME`.
- Filesystem/terminal/MCP: permissões do usuário que rodou o adapter — o mesmo isolamento do Cursor IDE.
- Não commitar `sk-…` de produção nem `cursor_…` keys.

## 11. Observabilidade

Cada request loga (structured): `model`, `loom_session_id`, `cursor_agent_id`, `run.id`, `workspace` (path, sem secrets), `duration_ms`, `status`, `error_code`. Sem API keys, sem tokens, sem conteúdo de arquivo.

## 12. Testes

Pacote `local-runtime/services/cursor-adapter` com `unittest`, sem rede e sem `CURSOR_API_KEY`:

1. Tradução: system+user; tool_call/tool; imagem omitida.
2. SessionManager: create, reuse, lock, expiração, workspace inválido.
3. Registro: o handler CustomLLM encaminha para a URL do adapter (httpx mockado).
4. Request LiteLLM: teste de contrato do adapter (`POST /v1/chat/completions` shape).
5. Streaming: gerador de chunks a partir de mensagens SDK fake.
6. Mapeamento de erro: tabela acima.
7. Cursor unavailable: connection refused → 503.
8. Workspace inválido → 400.
9. Auth missing → 401.
10. Planner: extract tools marker; parse `tool_calls` / `content`; empty → mensagem não vazia.
11. E2E real contra Cursor: marcados `@unittest.skipUnless(os.getenv("CURSOR_API_KEY"), …)` — nunca na CI sem a chave.

## 13. Critérios de aceite

1. LiteLLM `model=cursor-local` não existe no IaC de produção.
2. CustomLLM não importa `cursor_sdk`; só HTTP.
3. Adapter usa `cursor_sdk` + Bridge para o processo servidor.
4. Sessões reusam o mesmo `cursor_agent_id` para o mesmo `(agent, workspace, session)`.
5. Streaming implementado ou, se o SDK não chunkar, um único delta + `wait()` documentado no log.
6. Erros da tabela §8 cobertos por teste.
7. Workspace configurável e obrigatório.
8. MCP: Alternativa B (planner + agent-runtime) documentada e implementada no Chat; Alternativa A só para MCP do IDE fora do catálogo Loom.
9. `docker compose up` (com overlay) sobe LiteLLM, `cursor-adapter`, `mcp-runtime`, `agent-runtime`. Com `CURSOR_API_KEY` no `.env`, Chat `source=local` + `cursor-local` + connector MCP exerce o planner.
10. Sem `CURSOR_API_KEY`, o serviço fica healthy e completions `cursor-local` devolvem 401; `mock-echo` / `orientador-academico` continuam 200.

## 14. Não fazer

Não criar um Agent Runtime **no** processo FastAPI do Loom (o agent-runtime
é serviço separado — ADR 0005). Não fazer o Loom chamar o Cursor SDK
direto. Não tornar Cursor provider de produção. Não persistir sessão Cursor
em Postgres. Não passar MCP do catálogo Loom ao Cursor SDK. Não colocar o
Cursor Agent “dentro” do container do backend.
