# Spec 003 — LiteLLM como único gateway de LLM do Loom

## 1. Objetivo

O Loom deve enxergar **apenas** o proxy LiteLLM como provider de modelo. Não deve saber se o *backend* é Bedrock, Anthropic, OpenAI, Google, Azure ou o Cursor local.

Esta spec **não recria** a integração. Ela completa o que já existe em `backend/app/services/litellm.py`, `GET /api/settings/litellm-proxy`, `GET /api/agents/models/litellm` e o *dispatch* `provider=litellm` nos artefatos Strands/ADK.

**ACL aqui = anti-corruption layer** (o proxy), não access-control list.

## 2. O que o repositório já faz (não reinventar)

| Peça | Onde | Reusar |
| --- | --- | --- |
| Resolução de URL + master key | `services/litellm.py` | `LOOM_LITELLM_PROXY_BASE_URL`, `LOOM_LITELLM_DISCOVERY_BASE_URL`, `LOOM_LITELLM_PROXY_API_KEY`; Settings ganha do env |
| Virtual key por agente | `vend_virtual_key` / `revoke_virtual_key` | alias `loom-agent-{id}`; best-effort |
| Catálogo ao vivo | `model_catalog.get_litellm_models_live()` | `GET {discovery}/model/info` |
| Registro de providers | `backend/etc/providers.json` | ids `bedrock` e `litellm` |
| Cliente no agente | `agents/*/src` com `use_litellm_proxy=True` e prefixo `litellm_proxy/` | obrigatório para não vazar para o provider real |
| Harness | `liteLlmModelConfig` + API-key credential provider no AgentCore | não mudar o formato |
| Invoke | `POST /api/agents/{id}/invoke` → AgentCore | **não** passar a chamar o LiteLLM do backend |

O backend do Loom **não é** um cliente de chat. Invoke continua no AgentCore. O LiteLLM entra no caminho do *modelo do agente*, não no lugar do runtime.

## 3. Requisitos

### Provider

- Novos agentes e harnesses no stack local nascem com `provider=litellm`.
- `GET /api/agents/providers` marca `litellm.available=true` quando as env vars do compose estão setadas (já é o comportamento de `is_enabled()`).
- `bedrock` permanece no JSON nesta iteração para agentes já implantados e para o harness AWS. Não adicionar `openai`, `anthropic` nem `cursor` ao registro do Loom.
- O frontend continua usando `fetchLitellmModels()` quando o provider ativo é `litellm`. Não criar um terceiro catálogo.

### Endpoint

Usar **somente** as variáveis que o código já lê. Não introduzir `LITELLM_BASE_URL`.

| Variável | Compose local | Quem usa |
| --- | --- | --- |
| `LOOM_LITELLM_PROXY_BASE_URL` | `http://localhost:4000` | valor “de agente” / Settings (host) |
| `LOOM_LITELLM_DISCOVERY_BASE_URL` | `http://litellm:4000` | backend no Docker (`/model/info`, `/key/generate`) |
| `LOOM_LITELLM_PROXY_API_KEY` | `sk-loom-local-dev` | master key local, só compose |

O Loom **não** recebe `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID` nem `CURSOR_API_KEY` para inferência. Essas chaves, quando existirem, pertencem ao processo LiteLLM ou ao adapter no host.

AWS credentials no volume `LOOM_AWS_CREDS_DIR` continuam só para AgentCore/S3 — fora do escopo desta spec.

### Modelo

O Loom já representa modelo como `model_id` string no agente (`agents.model_id`, `allowed_model_ids`). Não inventar um tipo novo.

No proxy local o `model_name` que o Loom pede é o alias do `model_list`:

| Alias no LiteLLM | Backend real | Quando |
| --- | --- | --- |
| `mock-echo` | resposta fixa do proxy (sem rede externa) | validar o contrato Loom → LiteLLM |
| `cursor-local` | CustomLLM `cursor_agent` | DEV com Cursor no host |
| (produção) | `bedrock/…`, `anthropic/…`, `openai/…` | `config.yaml` do ambiente implantado |

O agente guarda `model_id=mock-echo` ou `model_id=cursor-local`. O LiteLLM resolve o resto.

## 4. Docker Compose

Serviço `litellm` no `docker-compose.yml` existente (não um compose paralelo):

- imagem oficial `ghcr.io/berriai/litellm`;
- `litellm --config /app/config.yaml --port 4000`;
- volume `./etc/docker/litellm:/app:ro`;
- `LITELLM_MASTER_KEY` = mesma master key do backend;
- `CURSOR_ADAPTER_URL` = `http://cursor-adapter:8765` (o CustomLLM só usa se o modelo for `cursor-local`);
- healthcheck em `GET /health`;
- porta `4000:4000`;
- `depends_on` do backend **não** espera o LiteLLM — o bootstrap do IdP não pode ficar preso se o proxy atrasar; o discovery de modelos já falha fechado e devolve lista vazia.

O `docker compose up` sobe Postgres, Keycloak, backend, frontend **e** LiteLLM. O adapter Cursor **não** sobe como container obrigatório (spec 004).

## 5. Fases (esta spec = fase 3)

1. Discovery (feito; ver ADR 0003).
2. ADR 0003.
3. **Agora:** proxy no compose + env do backend + `mock-echo` + o backend lista modelos do proxy.
4. CustomLLM Cursor (spec 004).
5. Bridge no host, só se o SDK sincrono não bastar para o processo adapter.
6. Serviço `cursor-adapter` no mesmo compose.
7. E2E: `GET /api/agents/models/litellm` devolve `mock-echo`; um `POST /v1/chat/completions` no proxy com `mock-echo` responde 200. Invoke completo de agente Loom ainda exige AgentCore/AWS — isso **não** é regressão e não deve ser “consertado” criando um runtime local.

## 6. Testes

- Reusar `test_litellm_service.py` e `test_settings_litellm_proxy.py` (não mudar o contrato das env vars).
- Novo: o CustomLLM `cursor_agent` **não** é testado aqui; fica na spec 004.
- Integração local: `curl` no `/health` e `/v1/models` do proxy após `docker compose up`.

## 7. Critérios de aceite (fase 3)

1. `docker compose config` continua válido com o serviço `litellm`.
2. Com o stack no ar, `GET http://localhost:4000/health/liveliness` retorna 200 (`/health` exige a master key).
3. Backend com as três `LOOM_LITELLM_*` setadas: `GET /api/settings/litellm-proxy` mostra `enabled: true` e a discovery URL interna.
4. `GET /api/agents/models/litellm` (autenticado) inclui `mock-echo`.
5. `POST http://localhost:4000/v1/chat/completions` com `model=mock-echo` e a master key local devolve 200 sem chamar Anthropic/OpenAI/Bedrock.
6. Nenhuma chave de provider final entra em arquivo rastreado pelo git.
7. O backend **não** ganha um cliente Anthropic/OpenAI/Cursor.

## 8. Fora de escopo

- Remover o provider `bedrock` do AgentCore, do IAM ou do harness.
- Invoke local sem AWS.
- LocalStack / Bedrock fake.
- Kubernetes.
- Tornar o LiteLLM obrigatório em contas AWS que ainda não têm proxy (o env vazio continua desligando o provider, como hoje).
