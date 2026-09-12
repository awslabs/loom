# Spec 002 — Stack local com Docker Compose e Keycloak como microsserviço

- **Status:** Rascunho
- **Data:** 2026-09-12
- **Implementa:** [ADR 0001 — Keycloak como IdP](../adr/0001-keycloak-as-identity-provider.md), [ADR 0002 — PostgreSQL compartilhado com o Keycloak](../adr/0002-postgresql-as-relational-datastore.md)
- **Depende de:** [Spec 001 — Camada de abstração de provedor de identidade](001-idp-abstraction-layer.md)

## 1. Objetivo

Adicionar um `docker-compose.yml` na raiz do repositório que suba a plataforma inteira
localmente com um único comando: PostgreSQL, Keycloak como serviço independente, o backend
FastAPI e o frontend React — autenticado de ponta a ponta, sem exigir recursos AWS para o login e
sem nenhum passo manual de configuração.

## 2. Fronteira de escopo: o que significa "a solução completa" localmente

Isso precisa ser dito com clareza, porque a expressão é fácil de prometer em excesso. O backend
é um orquestrador de serviços AWS, e nenhum container substitui esses serviços.

**Totalmente local, sem necessidade de conta AWS:** login e logout pelo Keycloak, autorização de
grupos para scopes, toda a navegação, as telas administrativas de Settings/Security/Tagging,
gerenciamento de provedores de identidade, persistência em PostgreSQL e migrações de banco.

**Ainda exige credenciais e serviços AWS reais:** deploy e invocação de agentes (Bedrock
AgentCore Runtime), recursos de memória, listagem de modelos e contagem de tokens (Bedrock),
upload de artefatos (S3) e qualquer obtenção de client secret (Secrets Manager). A stack Compose,
portanto, monta as credenciais AWS do host em modo somente leitura para que esses caminhos
funcionem quando houver credenciais, e a UI degrada para erros nessas páginas quando não houver.

**Bloqueado localmente por design:** registrar um MCP server ou agente A2A cuja URL OAuth2
well-known aponte para o Keycloak local. Essas chamadas passam pelo guard estrito de SSRF
(`backend/app/services/net_guard.py::safe_get`/`safe_post`), que exige HTTPS e rejeita endereços
privados. O caminho de login não é afetado — OIDC discovery, JWKS e o proxy de token usam
`urllib`/`httpx` puros (`services/oidc.py:42`, `services/jwt_validator.py:31`,
`routers/auth.py:109`) e aceitam `http://` e hostnames de container. Não enfraqueça o
`net_guard` para contornar isso.

## 3. Serviços

| Serviço | Imagem / build | Porta no host | Propósito |
|---|---|---|---|
| `postgres` | `postgres:17-alpine` | 5432 | Dois bancos: `loom` e `keycloak` (ADR 0002) |
| `keycloak` | `quay.io/keycloak/keycloak:26.6` | 8080 | IdP, realm importado de um arquivo versionado |
| `backend` | build: raiz do repo, `backend/Dockerfile` | 8000 | FastAPI, com hot reload |
| `frontend` | `node:20-alpine` (dev server) | 5173 | Vite dev server, com hot reload |

O PostgreSQL 17 é usado para corresponder à versão que a ADR 0002 define como alvo de instâncias
novas, de modo que o comportamento local acompanhe o comportamento implantado. Está dentro da
faixa 14.x–18.x suportada pelo Keycloak.

## 4. Restrições críticas descobertas no setup atual

**4.1 O build context do backend é a raiz do repositório, não `backend/`.** O
`backend/Dockerfile` copia `backend/requirements.txt`, `backend/app/` e `agents/*/src/` — este
último porque `build_agent_artifact` resolve as fontes dos agentes relativas a `/`. O serviço
precisa, portanto, usar `context: .` com `dockerfile: backend/Dockerfile`. Usar
`context: ./backend` falha no build.

**4.2 A imagem de produção do frontend embute os `VITE_*` em tempo de build.** O
`frontend/Dockerfile` recebe `VITE_API_BASE_URL` e `VITE_COGNITO_USER_CLIENT_ID` como build args
e serve o bundle compilado por nginx **na porta 8000**, não na 80. Essa imagem é inadequada como
padrão para desenvolvimento local: cada mudança de configuração exige rebuild e não há hot
reload. O serviço `frontend` padrão roda o Vite dev server a partir de uma imagem `node`; a
imagem de produção fica disponível atrás de um profile `prod-parity`, para verificação antes do
deploy.

**4.3 A URL do issuer e a URL do JWKS não são o mesmo valor.** O navegador alcança o Keycloak em
`http://localhost:8080`; o backend o alcança em `http://keycloak:8080`. A claim `iss` do Keycloak
é fixada por `KC_HOSTNAME`, então ela precisa permanecer `http://localhost:8080/realms/loom` para
que os tokens emitidos ao navegador sejam internamente consistentes. Como consequência, o
documento de discovery que o backend busca anuncia o `jwks_uri` como `http://localhost:8080/...`,
que o backend não consegue alcançar. É por isso que a Spec 001 introduz `internal_base_url`, e
por isso o adapter do Keycloak precisa reescrever o `jwks_uri` cacheado sobre essa base interna.
Errar aqui produz um login que funciona no navegador e retorna 401 em todas as chamadas de API.

**4.4 O bypass de autenticação não salva um setup quebrado aqui.** Como detalhado na Spec 001 §3
(P2), o bypass exige um endereço de cliente em loopback, o que nunca acontece dentro do Compose.
A stack depende do seeder de bootstrap (Spec 001 §6) para registrar o provider Keycloak na
primeira subida. Sem esse seeder, este Compose não consegue produzir um login utilizável.

**4.5 O CORS do backend já permite a origem de desenvolvimento.** O `backend/app/main.py:82` usa
por padrão `http://localhost:{LOOM_FRONTEND_PORT}` e `http://127.0.0.1:5173`, então a porta 5173
não precisa de configuração extra. Mudar a porta do frontend exige definir `LOOM_FRONTEND_PORT`
também no serviço do backend.

**4.6 Use um client público com PKCE localmente.** Um client confidencial faria o
`POST /api/auth/token` buscar o client secret no AWS Secrets Manager (`routers/auth.py:102`),
reintroduzindo uma dependência de AWS no caminho de login.

## 5. `docker-compose.yml` proposto

```yaml
name: loom

services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: loom
      POSTGRES_PASSWORD: loom
      POSTGRES_DB: loom
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./etc/docker/postgres-init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U loom -d loom"]
      interval: 5s
      timeout: 5s
      retries: 10

  keycloak:
    image: quay.io/keycloak/keycloak:26.6
    command: ["start-dev", "--import-realm"]
    environment:
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak
      KC_DB_USERNAME: keycloak
      KC_DB_PASSWORD: keycloak
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: admin
      # Fixa a claim `iss` na URL visível pelo navegador. Ver 4.3.
      KC_HOSTNAME: http://localhost:8080
      KC_HTTP_ENABLED: "true"
      KC_HEALTH_ENABLED: "true"
    ports:
      - "8080:8080"
    volumes:
      - ./etc/docker/keycloak/realm-loom.json:/opt/keycloak/data/import/realm-loom.json:ro
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      # A imagem do Keycloak nao traz curl/wget; usa-se /dev/tcp do shell.
      test:
        - CMD-SHELL
        - >-
          exec 3<>/dev/tcp/127.0.0.1/9000 &&
          printf 'GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3 &&
          grep -q '"status": "UP"' <&3
      interval: 10s
      timeout: 5s
      retries: 20
      start_period: 30s

  backend:
    build:
      context: .                    # raiz do repo — obrigatorio, ver 4.1
      dockerfile: backend/Dockerfile
    command:
      - uvicorn
      - app.main:app
      - --host
      - 0.0.0.0
      - --port
      - "8000"
      - --reload
    environment:
      LOOM_DATABASE_URL: postgresql+psycopg2://loom:loom@postgres:5432/loom
      LOOM_FRONTEND_PORT: "5173"
      LOOM_OIDC_REDIRECT_URI: http://localhost:5173/oauth/callback
      LOG_LEVEL: debug
      # Semeia o provider Keycloak na primeira subida (Spec 001 §6)
      LOOM_IDP_BOOTSTRAP_NAME: keycloak-local
      LOOM_IDP_BOOTSTRAP_TYPE: keycloak
      LOOM_IDP_BOOTSTRAP_ISSUER_URL: http://localhost:8080/realms/loom
      LOOM_IDP_BOOTSTRAP_INTERNAL_BASE_URL: http://keycloak:8080/realms/loom
      LOOM_IDP_BOOTSTRAP_CLIENT_ID: loom-frontend
      LOOM_IDP_BOOTSTRAP_CLIENT_TYPE: public
      LOOM_IDP_BOOTSTRAP_AUDIENCE: loom-frontend
      LOOM_IDP_BOOTSTRAP_GROUP_CLAIM_PATH: groups
      LOOM_IDP_BOOTSTRAP_SCOPES: openid profile email
      # Acesso AWS para Bedrock/AgentCore/S3/Secrets Manager. Ver secao 2.
      AWS_REGION: ${AWS_REGION:-us-east-1}
      AWS_PROFILE: ${AWS_PROFILE:-default}
      AWS_CONFIG_FILE: /aws/config
      AWS_SHARED_CREDENTIALS_FILE: /aws/credentials
    ports:
      - "8000:8000"
    volumes:
      - ./backend/app:/app/app:ro           # hot reload
      - ${USERPROFILE:-${HOME}}/.aws:/aws:ro
    depends_on:
      postgres:
        condition: service_healthy
      keycloak:
        condition: service_healthy

  frontend:
    image: node:20-alpine
    working_dir: /app
    command: sh -c "npm ci && npm run dev -- --host 0.0.0.0 --port 5173"
    environment:
      VITE_API_BASE_URL: http://localhost:8000
    ports:
      - "5173:5173"
    volumes:
      - ./frontend:/app
      - frontend-node-modules:/app/node_modules
    depends_on:
      - backend

volumes:
  postgres-data:
  frontend-node-modules:
```

Arquivos de apoio:

- `etc/docker/postgres-init/01-keycloak-db.sql` — cria o segundo banco e seu dono, conforme a
  decisão de bancos lógicos separados da ADR 0002:

  ```sql
  CREATE USER keycloak WITH PASSWORD 'keycloak';
  CREATE DATABASE keycloak OWNER keycloak;
  ```

- `etc/docker/keycloak/realm-loom.json` — o artefato de importação de realm que implementa a Spec
  001 §8: realm `loom`, client público com PKCE `loom-frontend`, o **mapper de audience** e o
  **mapper de group membership com `full.path = false` tanto no access token quanto no ID
  token**, os 12 grupos do Loom e os 8 usuários de teste declarados na
  [Spec 001 §8.1](001-idp-abstraction-layer.md#81-usuários-de-teste-do-realm) — `admin`,
  `demo-admin-1`, `security-admin`, `integration-admin`, `registry-admin`, `demo-user-1`,
  `test-user` e `strategics-user`, todos com `temporary: false` na credencial. Este arquivo é a
  única fonte de verdade da configuração do realm; mudanças feitas pelo console que não estejam
  refletidas aqui são perdidas ao resetar o volume.

O volume nomeado `frontend-node-modules` mantém o `node_modules` dentro do container, de modo que
um `npm install` feito no host para outra plataforma não vaze para dentro — e atende à convenção
do projeto de que `node_modules` permaneça no diretório correspondente.

## 6. Ordem de inicialização

`depends_on` com `condition: service_healthy` acerta a ordem no caso normal, mas não deve ser a
única defesa: o seeder de bootstrap da Spec 001 §6 tenta o discovery novamente com um limite de
retentativas, então um Keycloak lento degrada para um registro de provider atrasado em vez de um
backend quebrado. Em um volume totalmente novo, a sequência esperada é: PostgreSQL pronto →
schema do Keycloak criado pelo Liquibase e realm importado → backend rodando `init_db()` para
criar tabelas, semear políticas de tag e então semear e ativar o provider Keycloak → frontend
servindo.

## 7. Targets de make

O `CLAUDE.md` designa o makefile como interface primária e descreve orquestração na raiz, mas
hoje não existe makefile na raiz — os makefiles vivem em `shared/`, `backend/`, `frontend/` e
`agents/*`. Adicionar um `makefile` na raiz encapsulando o Compose para que a convenção
documentada se mantenha:

| Target | Ação |
|---|---|
| `make local.up` | `docker compose up -d --build` |
| `make local.down` | `docker compose down` |
| `make local.reset` | `docker compose down -v` (descarta os dois bancos e o realm) |
| `make local.logs` | `docker compose logs -f` |
| `make local.ps` | `docker compose ps` |
| `make local.keycloak.export` | Exporta o realm em execução de volta para `etc/docker/keycloak/realm-loom.json` |

O `local.keycloak.export` importa: é como uma mudança feita no console de administração se torna
um artefato versionado, em vez de estado local não documentado.

## 8. Critérios de aceite

1. Em um checkout limpo, sem volumes anteriores, `make local.up` resulta em um login funcional em
   `http://localhost:5173` usando um usuário de demonstração do Keycloak, com **zero** passos
   manuais de configuração e sem exigir credenciais AWS.
2. A sidebar e as permissões de escrita de cada um dos 8 usuários de teste correspondem à sua
   atribuição de grupo no Keycloak, confirmando que a claim de grupos chega ao **access** token
   (Spec 001 P4). Nenhum deles é solicitado a trocar de senha no primeiro login.
3. `demo-user-1` vê apenas os recursos do seu perfil de tag semeado, confirmando que o nome de
   usuário casa com o perfil criado por `_seed_demo_tag_profiles()`.
4. `GET /api/auth/config` reporta `provider_type: "keycloak"` com o endpoint de autorização
   visível pelo navegador.
5. Uma sessão sobrevive além do lifespan do access token do Keycloak sem novo login (Spec 001
   P5).
6. Editar um arquivo em `backend/app/` recarrega o uvicorn; editar um arquivo em `frontend/src/`
   faz hot reload no navegador.
7. `make local.reset && make local.up` retorna a um estado funcional, provando que nada depende
   de estado manual do console.
8. Os dados do Keycloak sobrevivem a `make local.down && make local.up` — realm, usuários e
   sessões estão no PostgreSQL, não no filesystem do container.
9. `docker compose config` passa e a imagem do backend builda a partir da raiz do repositório.

## 9. Notas de segurança sobre os artefatos versionados

O arquivo de realm e o arquivo Compose contêm credenciais de desenvolvimento (`admin/admin`,
senhas de banco, senhas de usuários de demonstração). Conforme os requisitos de varredura de
segurança do `CLAUDE.md`, isso é aceitável **apenas** porque são valores locais e não
produtivos, e eles precisam:

- estar claramente marcados como exclusivos de desenvolvimento local no topo dos dois arquivos;
- nunca ser reutilizados em ambiente implantado, onde as credenciais do Keycloak pertencem ao
  Secrets Manager e são injetadas pela IaC;
- vir acompanhados de URLs apenas `http`, inutilizáveis fora da rede local, para que a
  configuração não possa ser levada para produção sem alteração.

Um Keycloak implantado exige ainda `start` (não `start-dev`), terminação TLS, `KC_HOSTNAME`
apontando para o domínio real, proteção contra força bruta habilitada e o console de
administração não exposto publicamente. Isso é trabalho de deployment, fora do escopo desta spec.

## 10. Trabalho subsequente

- Um profile `prod-parity` no Compose que builde o `frontend/Dockerfile` com os build args
  corretos e mapeie sua porta 8000, para verificar o bundle nginx antes do deploy.
- Uma definição de serviço `keycloak` para ambientes implantados (task ECS atrás do ALB
  existente, banco vindo da stack RDS), que é onde as consequências operacionais da ADR 0001
  passam a valer.
- LocalStack opcional para S3 e Secrets Manager, o que reduziria a superfície AWS da seção 2 —
  embora não para Bedrock nem AgentCore, que não têm equivalente local.
