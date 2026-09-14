# Spec 001 — Camada de abstração de provedor de identidade, com Keycloak como primeiro provider

- **Status:** Rascunho
- **Data:** 2026-09-12
- **Implementa:** [ADR 0001 — Usar Keycloak como provedor de identidade na versão inicial](../adr/0001-keycloak-as-identity-provider.md)
- **Spec complementar:** [Spec 002 — Stack local com Docker Compose](002-local-docker-compose-stack.md)

## 1. Objetivo

Tornar o Keycloak o provedor de identidade do Loom, implementado atrás de uma **camada de
anticorrupção (ACL — anti-corruption layer)**, de modo que trocar ou adicionar um provider —
Microsoft Entra ID, Okta, Auth0, Amazon Cognito — seja questão de registrar um adapter e um
registro de configuração, e nunca de alterar lógica de autorização, routers ou componentes de
UI.

A camada tem uma única função: traduzir o que cada IdP emite para o modelo interno de identidade
e autorização do Loom, confinando toda particularidade de provider a um único adapter. O modelo
interno do Loom já está bem definido e não muda:

- **Identidade:** `sub`, `username`, `groups`.
- **Autorização:** grupos são mapeados para scopes via `GROUP_SCOPES`; endpoints são guardados
  por `require_scopes()`; a UI controla navegação e ações de escrita por `hasScope()`.

> **Terminologia.** "ACL" nesta spec significa *anti-corruption layer* (camada de
> anticorrupção — a fronteira de pluggabilidade solicitada), e não *access control list*. O
> controle de acesso do Loom continua sendo o modelo de grupos bidimensional existente (grupos
> de tipo `t-*` e grupos de recurso `g-*`) resolvido nos 21 scopes. A camada de abstração é
> justamente o que normaliza as claims de cada provider **para dentro** desse modelo de controle
> de acesso.

## 2. Estado atual

A plataforma está mais perto desse objetivo do que parece, e as partes reaproveitáveis devem ser
mantidas em vez de reescritas.

| Já é genérico — reaproveitar como está | Local |
|---|---|
| OIDC discovery (`fetch_discovery`) | `backend/app/services/oidc.py` |
| Validação RS256 via JWKS agnóstica de issuer, cache de chaves de 1h | `backend/app/services/jwt_validator.py:47` (`validate_token`) |
| Configuração de provider persistida com metadados de discovery em cache | `backend/app/models/identity_provider.py` |
| CRUD de provider + endpoints de discovery, enforcement de provider único ativo | `backend/app/routers/identity_providers.py` |
| Login Authorization Code + PKCE, proxy de troca para client confidencial | `frontend/src/api/auth.ts:191`, `backend/app/routers/auth.py:78` |
| Mapeamento de grupos e derivação de scopes | `backend/app/dependencies/auth.py:155` (`derive_scopes`), `:163` (`_map_external_groups`) |

| Acoplamento específico de provider — a mover para trás da ACL | Local |
|---|---|
| Ramo de fallback do Cognito dentro da dependência principal de auth | `backend/app/dependencies/auth.py:288` |
| Leitura das claims `cognito:groups` / `cognito:username` | `backend/app/dependencies/auth.py:294`, `frontend/src/contexts/AuthContext.tsx:452` |
| Reescrita de issuer específica do Entra (`sts.windows.net`) dentro de `get_current_user` | `backend/app/dependencies/auth.py:269` |
| `isExternalOIDC(cfg)` = `provider_type !== "cognito"`, usado ~15 vezes | `frontend/src/contexts/AuthContext.tsx:156` |
| URLs de logout do Okta/Entra hard-coded | `frontend/src/contexts/AuthContext.tsx:544` |
| Regex de tenant do Entra para detecção de mesmo IdP | `frontend/src/pages/ChatPage.tsx:149`, `frontend/src/components/InvokePanel.tsx:48` |
| Labels de provider, hints de claim, UI de mapeamento de grupos exclusiva do Entra | `frontend/src/pages/LoginPage.tsx:8`, `frontend/src/components/IdentityProviderPanel.tsx:21` |
| Chamadas HTTP diretas ao Cognito para login e refresh | `frontend/src/api/auth.ts` |
| Obtenção de token M2M apenas via Cognito | `backend/app/services/cognito.py` |

## 3. Problemas que esta spec precisa resolver

São bloqueios concretos encontrados na implementação atual, não questões de estilo. Cada um tem
um critério de aceite na §12.

**P1 — Deadlock de bootstrap.** O provider ativo existe apenas como uma linha em
`identity_providers`, criada por `POST /api/settings/identity-providers`, que exige o scope
`security:write`. Com o Cognito removido e nenhuma linha de provider ainda, `get_current_user`
não encontra pool nem IdP ativo, e retorna 401 a menos que o bypass de desenvolvimento local se
aplique. Não existe forma de registrar o primeiro provider pela API. E o bypass também não é uma
saída geral (ver P2).

**P2 — O bypass é inalcançável de dentro de um container.** O bypass exige
`LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV` **e** um cliente em loopback:

```31:33:backend/app/dependencies/auth.py
def _is_loopback_request(request: Request) -> bool:
    client = request.client
    return bool(client) and client.host in _LOOPBACK_HOSTS
```

`_LOOPBACK_HOSTS` é `{"127.0.0.1", "::1", "localhost"}`. Dentro do Compose o backend vê o
endereço do gateway da bridge (por exemplo `172.18.0.1`), então o bypass nunca é acionado. Esse é
o comportamento correto de falhar fechado e não deve ser relaxado; o bootstrap não pode depender
dele.

**P3 — Access tokens do Keycloak vão falhar na validação de audience por padrão.** O backend
valida com `audience = idp.audience or idp.client_id`:

```272:277:backend/app/dependencies/auth.py
claims = validate_token(
    token,
    jwks_uri=active_idp["jwks_uri"],
    issuer=issuer,
    audience=active_idp.get("audience") or active_idp.get("client_id"),
)
```

O Keycloak não coloca o client ID em `aud` por padrão — ele emite `aud: "account"` e carrega o
client ID em `azp`. Sem um mapper de audience explícito, todo request retorna 401.

**P4 — Os grupos precisam estar no access token, não apenas no ID token.** O frontend lê os
grupos do **ID token** (`AuthContext.tsx:227`), enquanto o backend os lê do **access token** que
recebe no header `Authorization`. Um mapper do Keycloak adicionado só ao ID token produz uma UI
que parece corretamente permissionada, enquanto toda chamada de API resolve zero scopes.

**P5 — IdPs externos não têm refresh de token.** O timer de refresh força logout para qualquer
provider que não seja Cognito, e o interceptor de 401 limpa a sessão:

```347:353:frontend/src/contexts/AuthContext.tsx
          // Only Cognito supports REFRESH_TOKEN_AUTH via direct API
          if (isExternalOIDC(config)) {
            // For external IdPs, force re-login when token expires
            setTokens(null);
            setUser(null);
            setAuthToken(null);
            return;
          }
```

O lifespan padrão de access token do Keycloak é de 5 minutos, então os usuários seriam
redirecionados para o login a cada cinco minutos. Suporte a refresh é requisito funcional, não
um detalhe de conforto.

**P6 — Dualidade da URL de discovery.** O navegador precisa alcançar o Keycloak em uma URL
visível no host, enquanto o backend o alcança pela rede de containers. A claim `iss` é fixada
pela configuração de hostname do Keycloak, então o issuer esperado e a URL usada para buscar
discovery/JWKS não são necessariamente o mesmo valor. O modelo de dados tem um único campo
`issuer_url` servindo aos dois propósitos.

**P7 — A identidade do provider é um booleano.** `provider_type !== "cognito"` confunde "não é
Cognito" com "suporta PKCE", "suporta refresh", "precisa de mapeamento de grupos" e "tem
endpoint de logout no IdP". O Keycloak é um quinto provider que precisa de respostas diferentes
para cada uma dessas perguntas, e responder a elas com mais comparações de string é exatamente o
que esta spec existe para evitar.

## 4. Arquitetura alvo

### 4.1 Backend: adapters de provider

Novo pacote `backend/app/idp/`:

```
backend/app/idp/
├── __init__.py        # get_adapter(provider_type) -> IdpAdapter; registro ADAPTERS
├── base.py            # protocolo IdpAdapter, ProviderCapabilities, NormalizedIdentity
├── keycloak.py        # KeycloakAdapter
├── cognito.py         # CognitoAdapter  (encapsula o comportamento atual)
├── entra.py           # EntraIdAdapter  (reescrita de issuer, claim roles, OBO jwt-bearer)
├── okta.py            # OktaAdapter
├── auth0.py           # Auth0Adapter
└── generic_oidc.py    # GenericOidcAdapter (padrão; comportamento estrito conforme a especificação)
```

`base.py` define o contrato:

```python
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    """O que um provider suporta. Substitui comparações de string nos pontos de uso."""
    authorization_code_pkce: bool = True
    refresh_token: bool = False
    password_grant: bool = False          # apenas Cognito USER_PASSWORD_AUTH
    client_credentials: bool = False      # M2M para invocação de agentes
    rfc8693_token_exchange: bool = False  # OBO
    jwt_bearer_grant: bool = False        # OBO no estilo Entra
    idp_initiated_logout: bool = False
    requires_group_mapping: bool = False  # nomes de grupo externos != grupos do Loom


@dataclass(frozen=True)
class NormalizedIdentity:
    """O único formato de identidade que o resto do backend pode consumir."""
    sub: str
    username: str
    groups: list[str]
    email: str | None = None
    raw_claims: dict[str, Any] = field(default_factory=dict)


class IdpAdapter(Protocol):
    provider_type: str
    capabilities: ProviderCapabilities

    def expected_issuer(self, config: "IdpConfig") -> str:
        """Issuer esperado para validar `iss`. O Entra reescreve v2.0 -> sts.windows.net."""

    def discovery_base_url(self, config: "IdpConfig") -> str:
        """URL base que este processo deve usar para buscar discovery/JWKS (pode ser interna ao container)."""

    def expected_audience(self, config: "IdpConfig") -> str | None:
        """Audience a exigir, ou None para não validar audience."""

    def extract_identity(self, claims: dict[str, Any], config: "IdpConfig") -> NormalizedIdentity:
        """Mapeia as claims do provider para a identidade normalizada, incluindo extração de grupos."""

    def logout_url(self, config: "IdpConfig", post_logout_redirect_uri: str) -> str | None:
        """URL de logout iniciado pelo IdP, ou None se não suportado."""

    def token_exchange_params(self, config: "IdpConfig", subject_token: str, audience: str) -> dict[str, str] | None:
        """Parâmetros da requisição de OBO, ou None se o provider não faz delegação."""
```

O `get_current_user` se reduz a uma orquestração neutra de provider:

1. Resolver a `IdpConfig` ativa (com cache, como hoje).
2. `adapter = get_adapter(config.provider_type)`.
3. `validate_token(token, jwks_uri=config.jwks_uri, issuer=adapter.expected_issuer(config), audience=adapter.expected_audience(config))`.
4. `identity = adapter.extract_identity(claims, config)`.
5. `UserInfo(sub=..., username=..., groups=identity.groups, scopes=derive_scopes(identity.groups), idp_type=config.provider_type)`.

Não há ramo de Cognito nem `if` de Entra dentro da dependência. O fallback do Cognito se torna o
`CognitoAdapter`, selecionado por configuração como qualquer outro provider. `derive_scopes`,
`GROUP_SCOPES`, `require_scopes` e `UserInfo` permanecem inalterados — é justamente esse o
propósito da fronteira.

### 4.2 Frontend: descritores de provider

Novo diretório `frontend/src/auth/providers/` exportando um descritor por provider:

```ts
export interface ProviderDescriptor {
  type: string;
  label: string;                    // substitui PROVIDER_LABELS
  groupClaimHint: string;           // substitui GROUP_CLAIM_HINTS
  capabilities: {
    passwordForm: boolean;          // renderiza usuário/senha em vez do botão de SSO
    refreshToken: boolean;          // agenda refresh em vez de forçar novo login
    idpLogout: boolean;
    groupMappingUi: boolean;        // exibe o editor de mapeamento de grupos
  };
  logoutUrl?(cfg: AuthConfig, returnTo: string): string;
  issuerMatches?(cfg: AuthConfig, discoveryUrl: string): boolean;  // detecção de mesmo IdP
}
```

`isExternalOIDC(cfg)` é removido. Cada ponto de uso atual passa a fazer uma pergunta de
capacidade: `descriptor.capabilities.passwordForm`, `descriptor.capabilities.refreshToken`, e
assim por diante. A detecção de mesmo IdP em `ChatPage`/`InvokePanel` chama
`descriptor.issuerMatches`, que é onde o regex de tenant do Entra passa a viver — e somente lá.

### 4.3 Onde cada particularidade atual vai morar

| Particularidade atual | Novo local |
|---|---|
| `cognito:groups`, `cognito:username` | `idp/cognito.py::extract_identity` |
| Reescrita de issuer do Entra (`sts.windows.net`) | `idp/entra.py::expected_issuer` |
| Claim `roles` do Entra | `groupClaimHint` em `idp/entra.py` |
| URLs de logout do Okta/Entra | `logout_url()` por adapter + `logoutUrl` no descritor |
| Regex de tenant do Entra | `descriptor.issuerMatches` no descritor do Entra |
| Tratamento de `aud`/`azp` do Keycloak | `idp/keycloak.py::expected_audience` |
| Login por senha e refresh do Cognito | `CognitoAdapter` + descritor Cognito com `passwordForm: true` |

## 5. Mudanças no modelo de dados

Adicionar em `IdentityProvider` (`backend/app/models/identity_provider.py`), todas nulas e
retrocompatíveis:

| Coluna | Tipo | Propósito |
|---|---|---|
| `internal_base_url` | String, nula | URL base interna ao container/VPC para discovery e JWKS quando diferir de `issuer_url`. Resolve **P6**. Faz fallback para `issuer_url` quando nula. |
| `end_session_endpoint` | String, nula | Cacheado do discovery; habilita logout neutro de provider. |
| `refresh_enabled` | String/bool, nula | Override do operador para suporte a refresh; por padrão segue a capacidade do adapter. |
| `managed_by` | String, nula | `"bootstrap"` quando a linha foi semeada pelo ambiente (ver §6), senão nula. Impede que o bootstrap sobrescreva edições do operador. |

`provider_type` passa a aceitar `"keycloak"` no comentário do modelo, no schema `CreateIdP`
(`routers/identity_providers.py:31`) e na lista `PROVIDER_TYPES` do frontend
(`IdentityProviderPanel.tsx:21`). Registrar o Keycloak como `generic_oidc` **não** é o plano,
deliberadamente: o comportamento de audience e de claim de grupos descrito em **P3/P4** merece um
adapter nomeado, com defaults que funcionam de imediato.

`_run_discovery` usa `adapter.discovery_base_url(config)` em vez de `issuer_url`, e também
cacheia `end_session_endpoint`.

Uma sutileza merece ser dita explicitamente, porque é o modo de falha por trás do **P6**: quando
`internal_base_url` está definida, o documento de discovery buscado pela rede interna continua
anunciando os endpoints *externos*, já que o provider os deriva do próprio hostname configurado.
Os endpoints de autorização e token devem permanecer externos — o navegador os usa — mas o
`jwks_uri` precisa ser reescrito sobre `internal_base_url` antes de ser cacheado, porque somente
o backend o consome. Trate isso em `_run_discovery` via adapter, não no ponto de chamada da
validação.

## 6. Bootstrap: provider semeado por ambiente (resolve P1, P2)

Adicionar um seeder idempotente de startup, `backend/app/services/idp_bootstrap.py`, invocado
por `init_db()` em `backend/app/db.py` depois das funções de seed existentes.

Comportamento:

1. Ler `LOOM_IDP_BOOTSTRAP_JSON` (um objeto JSON) ou as variáveis discretas da tabela abaixo. Se
   nada estiver definido, não faz nada.
2. Fazer upsert da linha em `identity_providers` casada por `name`, definindo
   `managed_by="bootstrap"`.
3. Rodar discovery contra `internal_base_url` com retentativas limitadas — o Keycloak pode ainda
   estar subindo.
4. Definir `status="active"` e desativar os demais, reaproveitando `_enforce_single_active()`.
5. Nunca sobrescrever uma linha cujo `managed_by` seja nulo (linhas criadas pelo operador
   vencem).
6. Logar em INFO; em caso de falha, logar warning e manter a aplicação de pé, para que o
   operador possa corrigir a configuração pela UI.

| Variável | Exemplo |
|---|---|
| `LOOM_IDP_BOOTSTRAP_NAME` | `keycloak-local` |
| `LOOM_IDP_BOOTSTRAP_TYPE` | `keycloak` |
| `LOOM_IDP_BOOTSTRAP_ISSUER_URL` | `http://localhost:8080/realms/loom` |
| `LOOM_IDP_BOOTSTRAP_INTERNAL_BASE_URL` | `http://keycloak:8080/realms/loom` |
| `LOOM_IDP_BOOTSTRAP_CLIENT_ID` | `loom-frontend` |
| `LOOM_IDP_BOOTSTRAP_CLIENT_TYPE` | `public` |
| `LOOM_IDP_BOOTSTRAP_AUDIENCE` | `loom-frontend` |
| `LOOM_IDP_BOOTSTRAP_GROUP_CLAIM_PATH` | `groups` |
| `LOOM_IDP_BOOTSTRAP_SCOPES` | `openid profile email` |

É isso que viabiliza uma stack local de um comando, e é igualmente útil em ambientes implantados
onde o provider deve vir da IaC em vez de um passo manual na UI.

## 7. Refresh de token para providers externos (resolve P5)

Adicionar `POST /api/auth/refresh` em `backend/app/routers/auth.py`, espelhando o proxy existente
`POST /api/auth/token`:

- **Request:** `{ "refresh_token": "..." }`
- **Comportamento:** carregar o IdP ativo; fazer POST com `grant_type=refresh_token`, o
  `client_id` e, para clients confidenciais, o `client_secret` do Secrets Manager; retornar a
  resposta de token bruta.
- **Rejeita** com 400 quando `adapter.capabilities.refresh_token` é falso.
- **Atenção:** refresh tokens rotativos (o padrão do Keycloak) significam que o novo
  `refresh_token` da resposta precisa substituir o armazenado.

Mudanças no frontend em `AuthContext.tsx`:

- `scheduleRefresh` chama esse endpoint quando `descriptor.capabilities.refreshToken` é
  verdadeiro, em vez de limpar a sessão (substituindo as linhas 347–353).
- O interceptor de 401 tenta um refresh antes de limpar (substituindo as linhas 390–403).
- O Cognito mantém seu caminho direto de `REFRESH_TOKEN_AUTH` dentro do descritor do Cognito.

Independentemente disso, o realm do Keycloak deve usar um lifespan de access token maior (10–15
minutos), com SSO idle/max definidos deliberadamente, para que o volume de refresh se mantenha
razoável — lembrando, pela [ADR 0002](../adr/0002-postgresql-as-relational-datastore.md), que cada
refresh é uma escrita no banco no Keycloak 26.

## 8. Requisitos do realm do Keycloak

Estes são requisitos funcionais, não sugestões: **P3** e **P4** falham silenciosamente se forem
esquecidos. Tudo isso precisa viver em um arquivo de importação de realm versionado (ver Spec
002), e não em estado do console de administração configurado a mão.

**Realm:** `loom`.

**Client `loom-frontend`** (usado pela SPA):
- Client público, Standard Flow habilitado, Direct Access Grants desabilitado.
- PKCE obrigatório: `pkce.code.challenge.method = S256`.
- Valid redirect URIs: `http://localhost:5173/*` localmente, mais a origem implantada.
- Valid post-logout redirect URIs e Web origins nas mesmas origens (`+` para CORS).

**Protocol mappers em `loom-frontend`:**

1. **Mapper de audience** (`oidc-audience-mapper`): `included.client.audience = loom-frontend`,
   `access.token.claim = true`. Sem isso o backend rejeita todos os tokens (**P3**). A
   alternativa — definir `audience` como `account` no registro do IdP — é explicitamente
   rejeitada, pois validaria contra uma claim que o Keycloak emite para todos.
2. **Mapper de group membership** (`oidc-group-membership-mapper`): claim `groups`,
   **`full.path = false`** (senão os grupos chegam como `/g-admins-super` e nunca casam com
   `GROUP_SCOPES`), com **ambos** `access.token.claim = true` e `id.token.claim = true`
   (**P4**).

**Grupos** — criados com nomes idênticos aos grupos internos do Loom, para que `group_mappings`
possa ficar vazio e `requires_group_mapping` seja falso:

`t-admin`, `t-user`, `g-admins-super`, `g-admins-demo`, `g-admins-security`,
`g-admins-memory`, `g-admins-mcp`, `g-admins-a2a`, `g-admins-registry`, `g-users-demo`,
`g-users-test`, `g-users-strategics`.

As regras de atribuição de grupo de `dependencies/auth.py:39-44` continuam valendo: um usuário
`t-admin` tem exatamente um grupo `g-admins-*`; um usuário `t-user` tem um ou mais grupos
`g-users-*`.

**Client `loom-m2m`** (opcional, para invocação entre serviços): confidencial, Service Accounts
habilitado, apenas `client_credentials` — o equivalente Keycloak do client M2M do Cognito.
Necessário apenas ao substituir `services/cognito.py::get_cognito_token`, que é uma fase
posterior (§10).

### 8.1 Usuários de teste do realm

Os nomes de usuário **não são arbitrários**. Duas partes do código dependem deles:

- `App.tsx` faz parse de `^demo-admin-(\d+)$` e mapeia o usuário para o perfil de tag
  `demo-user-N` (`ownerRestriction`), então o sufixo numérico é funcional.
- `_seed_demo_tag_profiles()` em `backend/app/db.py` cria perfis de tag chamados `demo-user-1`
  até `demo-user-9`, com `loom:owner` igual ao nome do usuário. Um usuário `demo-user-N` sem o
  perfil correspondente não exercita a restrição de perfil por proprietário.

A fonte de verdade das atribuições atuais é `shared/iac/cognito.yaml`. O realm local declara o
conjunto **mínimo que cobre todos os 12 grupos** e preserva os nomes numerados de que o código
depende, em vez de replicar as 21 contas do Cognito:

| Usuário | Grupos | Por que está no seed |
|---|---|---|
| `admin` | `t-admin`, `g-admins-super` | Todos os scopes; caminho de administração completo |
| `demo-admin-1` | `t-admin`, `g-admins-demo` | Restrições de escrita do demo-admin; nome numerado exercita o mapeamento para o perfil `demo-user-1` |
| `security-admin` | `t-admin`, `g-admins-security` | Administração de segurança e de provedores de identidade |
| `integration-admin` | `t-admin`, `g-admins-memory`, `g-admins-mcp`, `g-admins-a2a` | Único caso de múltiplos grupos `g-admins-*` |
| `registry-admin` | `t-admin`, `g-admins-registry` | Governança do Agent Registry |
| `demo-user-1` | `t-user`, `g-users-demo` | Visão de usuário final; tem perfil de tag semeado |
| `test-user` | `t-user`, `g-users-test` | Filtragem de recursos por outro grupo de usuário |
| `strategics-user` | `t-user`, `g-users-strategics` | Terceiro grupo de usuário, para validar semântica de união |

Todos com `enabled: true`, `emailVerified: true`, e uma senha de desenvolvimento **não
temporária** — `temporary: false` é obrigatório, senão o Keycloak exige troca de senha no
primeiro login e interrompe o fluxo Authorization Code. Forma da declaração no arquivo de realm:

```json
{
  "username": "demo-admin-1",
  "enabled": true,
  "emailVerified": true,
  "email": "demo-admin-1@local.loom",
  "credentials": [
    { "type": "password", "value": "Loom-Local-Dev-1", "temporary": false }
  ],
  "groups": ["/t-admin", "/g-admins-demo"]
}
```

O campo `groups` usa o caminho com barra porque é assim que a importação de realm referencia
grupos — isso é independente da configuração `full.path = false` do mapper, que afeta apenas
como os grupos aparecem **na claim do token**. Confundir os dois é a origem do modo de falha
descrito em **P4**.

Duas divergências pré-existentes ficam visíveis ao declarar esses usuários, e valem correção
separada:

- Nenhum usuário do Cognito está associado a `g-admins-registry` nem a `g-users-strategics` —
  os grupos existem sem membros, então esses caminhos de scope nunca foram exercitados com um
  login real. O realm local passa a cobri-los.
- A lista `USER_GROUPS` de "View As" em `App.tsx:68` não corresponde ao Cognito: ela contém
  `demo-admin`, `memory-admin`, `mcp-admin`, `a2a-admin` e `registry-admin`, que não existem
  como usuários, e não contém `demo-admin-1..9` nem `integration-admin`, que existem. Como é
  apenas simulação de UI, não quebra nada hoje, mas significa que "View As" não reflete contas
  reais.

## 9. Fora de escopo nesta primeira iteração, deliberadamente

Manter o raio de impacto pequeno importa mais que pureza. Fora de escopo aqui:

- **Authorizers de invocação de agentes.** `routers/agents.py` monta a configuração de authorizer
  JWT do AgentCore com uma URL de discovery do Cognito e adiciona automaticamente
  `LOOM_COGNITO_USER_CLIENT_ID` a `allowedClients` (`agents.py:1428`). O tipo de authorizer
  `"other"` existente, com URL de discovery customizada, já aceita o Keycloak. Refatorar esse
  caminho para trás do adapter é trabalho posterior.
- **Obtenção de token M2M.** `services/cognito.py` permanece até o `loom-m2m` substituí-lo;
  `services/token.py::get_oauth2_token` já é genérico e é o destino da migração.
- **OBO/delegação.** O AgentCore realiza a troca usando seus próprios credential providers
  (`services/credential.py:66`). `token_exchange_params()` fica definido no protocolo agora, mas
  só é ligado ao OBO direto do backend para MCP (`services/mcp.py:81`) em uma fase posterior.
- **Remover o Cognito.** O Cognito permanece um provider registrável via `CognitoAdapter`.

## 10. Fases de implementação

Cada fase deve ser revisável de forma independente e deixar a `main` funcionando.

1. **Adapters, sem mudança de comportamento.** Adicionar `backend/app/idp/` com
   `CognitoAdapter`, `EntraIdAdapter`, `OktaAdapter`, `Auth0Adapter` e `GenericOidcAdapter`
   reproduzindo exatamente o comportamento atual. Refatorar `get_current_user` para delegar. Os
   testes existentes devem passar sem alteração.
2. **Adapter do Keycloak + campos do modelo.** Adicionar `KeycloakAdapter`, as novas colunas e
   `provider_type = "keycloak"` de ponta a ponta (schema do backend + lista na UI de
   administração).
3. **Seeder de bootstrap.** `idp_bootstrap.py` ligado a `init_db()`. Resolve P1/P2.
4. **Suporte a refresh.** `POST /api/auth/refresh` mais as mudanças no `AuthContext`. Resolve P5.
5. **Descritores no frontend.** Introduzir `frontend/src/auth/providers/`, remover
   `isExternalOIDC` e migrar todos os pontos de uso, incluindo `ChatPage`, `InvokePanel`,
   `AgentDetailPage`, `LoginPage` e `IdentityProviderPanel`.
6. **Artefato de realm.** Commitar o arquivo de importação de realm e validá-lo contra a stack
   Compose da Spec 002.

## 11. Testes

Seguindo a convenção `unittest`/pytest do projeto em `backend/tests/`:

- `test_idp_adapters.py` — por adapter: `expected_issuer`, `expected_audience`,
  `extract_identity` (incluindo `groups` do Keycloak com e sem `full.path`) e flags de
  capacidade. Orientado a tabela sobre os adapters.
- `test_idp_keycloak.py` — `get_current_user` de ponta a ponta com um par de chaves RSA gerado
  localmente e um JWKS mockado, verificando que: um token com `aud: ["account"]` e sem mapper de
  audience é **rejeitado**; um token com `aud: ["loom-frontend"]` e claim `groups` resolve os
  scopes corretos; `/g-admins-super` (caminho completo) resolve **nenhum** scope e é reportado de
  forma clara. Seguir o padrão existente em `test_identity_providers.py`.
- `test_idp_bootstrap.py` — semeia a partir do ambiente; idempotente na segunda chamada; não
  sobrescreve linha criada pelo operador; define exatamente um provider ativo; sobrevive a falha
  de discovery sem quebrar o startup.
- `test_auth_refresh.py` — sucesso do proxy de refresh, retorno do refresh token rotacionado, 400
  quando o adapter não tem a capacidade, `client_secret` injetado apenas para clients
  confidenciais.
- Os `test_auth.py`, `test_scopes.py` e `test_identity_providers.py` existentes devem continuar
  passando sem modificação até a fase 1; alterações neles depois disso indicam uma regressão de
  comportamento que precisa de justificativa.
- Frontend: verificação em nível de tipo de que todo `provider_type` em `PROVIDER_TYPES` tem um
  descritor, para que adicionar um provider sem descritor quebre o `npm run typecheck`.

## 12. Critérios de aceite

1. Fazer login no Loom com um usuário do Keycloak produz uma sessão cuja sidebar e permissões de
   escrita correspondem exatamente aos grupos do usuário no Keycloak, e as chamadas de API
   funcionam com esses scopes. (P3, P4)
2. `rg -n 'cognito:groups|cognito:username' backend/app frontend/src` só encontra resultados em
   arquivos dentro de `backend/app/idp/` e `frontend/src/auth/providers/`.
3. `isExternalOIDC` não existe mais no frontend; nenhum arquivo fora de
   `frontend/src/auth/providers/` compara `provider_type` com um literal.
4. Um banco novo mais `LOOM_IDP_BOOTSTRAP_*` resulta em login funcional sem nenhum passo manual
   na UI e sem depender do bypass de autenticação. (P1, P2)
5. Uma sessão sobrevive por mais tempo que o lifespan do access token do Keycloak sem novo login.
   (P5)
6. O backend valida tokens cujo `iss` é uma URL visível no host, enquanto busca o JWKS pela rede
   de containers. (P6)
7. Trocar o provider ativo para Cognito ou Entra ID restaura o comportamento anterior sem
   mudança de código.
8. Adicionar um provider hipotético novo toca exatamente dois arquivos: um adapter no backend e
   um descritor no frontend.

## 13. Riscos

- **Configuração incorreta silenciosa.** Um mapper de audience ou de grupos ausente produz 401s
  ou uma UI sem scopes, sem causa aparente. Mitigação: o adapter do Keycloak deve logar um
  diagnóstico específico quando a validação falhar com `aud` presente mas sem o client ID, e
  quando a claim de grupos estiver ausente ou vier prefixada com barra.
- **Armazenamento de tokens.** Os tokens são persistidos em `sessionStorage`
  (`AuthContext.tsx`, chaves `loom_auth_tokens` / `loom_auth_user`), enquanto o `README.md` e o
  `SPECIFICATIONS.md` afirmam armazenamento apenas em memória. A documentação está errada, não o
  código. Vale corrigir junto com este trabalho, e vale uma decisão deliberada agora que refresh
  tokens também serão armazenados.
- **`oidc_state` não é validado** em `handleOIDCCallback`, mesmo sendo escrito (`auth.ts:217`);
  o `OAuthLinkCallbackPage` valida. Adicionar um provider é um bom momento para fechar essa
  brecha de CSRF.
- **Abrangência da fase 5.** A migração para descritores no frontend toca muitos arquivos; é
  mecânica, mas ampla. Mantê-la como fase própria evita misturá-la com mudança de comportamento.
