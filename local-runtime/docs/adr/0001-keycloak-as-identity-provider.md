# 1. Usar Keycloak como provedor de identidade na versão inicial

- **Status:** Aceita
- **Data:** 2026-09-12
- **Decisores:** Mantenedores da plataforma
- **Substitui:** —
- **Substituída por:** —
- **Relacionada a:** [ADR 0002 — Usar PostgreSQL como banco relacional, compartilhado com o Keycloak](0002-postgresql-as-relational-datastore.md)

## Contexto

O Loom precisa de um provedor de identidade (IdP) para autenticar usuários e emitir os tokens
que alimentam o resto da plataforma. Autenticação aqui não é uma preocupação isolada — o token
emitido no login é reaproveitado por vários subsistemas:

- **Autorização no frontend:** a claim de grupos do ID token é mapeada para o modelo de grupos
  bidimensional (grupos de tipo `t-admin`/`t-user` e grupos de recurso
  `g-admins-*`/`g-users-*`) e expandida nos 21 scopes da plataforma, que controlam a
  visibilidade da sidebar e o acesso de escrita.
- **Enforcement no backend:** todo endpoint é guardado por `require_scopes()`, que valida o JWT
  contra o endpoint JWKS do issuer e deriva os scopes a partir das claims de grupo.
- **Invocação de agentes:** agentes no AgentCore Runtime com authorizer JWT precisam confiar no
  mesmo issuer, e o access token do usuário é repassado para agentes protegidos por OAuth.
- **Delegação:** o fluxo on-behalf-of (OBO) troca o token do usuário para que agentes alcancem
  MCP servers e agentes A2A downstream com permissões no escopo do usuário.

O IdP é, portanto, uma decisão estrutural para a versão inicial, não um detalhe que possa ser
postergado. Escolher tarde significaria refazer o mapeamento de grupos para scopes, a
configuração do authorizer dos agentes e o fluxo de delegação.

Dois fatos sobre o código atual moldam a decisão. Primeiro, a plataforma já suporta provedores
OIDC de forma genérica: `IdentityProvider.provider_type` aceita `generic_oidc`, o registro de
provider roda OIDC discovery para cachear JWKS e os endpoints de autorização e token, e
`jwt_validator.validate_token()` é agnóstico de issuer (RS256 contra qualquer URL de JWKS, com
chaves em cache por uma hora). Segundo, o fluxo de login já ramifica para Authorization Code +
PKCE contra um provider externo, com `group_claim_path` configurável e mapeamento de grupos
externos para grupos do Loom. Em outras palavras, um provider OIDC aderente ao padrão já é uma
forma de primeira classe, não uma nova superfície de integração.

## Fatores de decisão

1. **Completude de protocolo, especialmente token exchange.** O modelo de delegação depende de
   RFC 8693. O Keycloak implementa nativamente; o Amazon Cognito não, o que obriga a delegação
   a ser intermediada em outro lugar.
2. **Portabilidade.** O mesmo IdP precisa rodar em desenvolvimento local, on-premises e em
   qualquer nuvem, sem reimplementar a camada de autenticação por ambiente.
3. **Atrito no desenvolvimento local.** Contribuidores devem conseguir subir um login
   funcional sem provisionar recursos em nuvem nem compartilhar um tenant.
4. **Claims padronizadas.** Uma claim `groups` convencional é preferível a uma claim com
   prefixo de fornecedor (`cognito:groups`), para que o código de mapeamento de grupos
   permaneça genérico.
5. **Previsibilidade de custo.** Sem cobrança por usuário ativo mensal na escala esperada na
   adoção inicial.
6. **Carga operacional.** Qualquer que seja a escolha, precisamos conseguir operar e atualizar
   a solução com o time e a infraestrutura que já temos.

## Opções consideradas

### Opção 1 — Keycloak, auto-hospedado (escolhida)

Provedor OIDC/OAuth 2.0/SAML open source. Cobertura completa dos padrões, incluindo token
exchange (RFC 8693), client scopes granulares, protocol mappers para claims customizadas,
isolamento por realm e uma API REST de administração para automatizar provisionamento de
usuários, grupos e clients.

- **A favor:** superfície de protocolo completa; token exchange nativo; roda de forma idêntica
  em qualquer lugar; trivial de subir localmente como container; sem licenciamento por
  usuário; claims e mapeamento de grupos totalmente sob nosso controle; encaixa no caminho
  `generic_oidc` que já existe.
- **Contra:** passamos a ser responsáveis por disponibilidade, upgrades, backups e TLS; exige
  um banco PostgreSQL e um deployment endurecido; a cadência de releases do Keycloak demanda
  upgrades regulares; não há contrato de suporte com fornecedor.

### Opção 2 — Amazon Cognito

User pool gerenciado da AWS, com grupos, scopes customizados via resource server e integração
nativa com AgentCore e ALB.

- **A favor:** totalmente gerenciado; nenhuma infraestrutura para operar; integração nativa com
  a AWS; free tier generoso; já é o caminho de menor resistência para deployments na AWS.
- **Contra:** não tem token exchange (RFC 8693), que é a lacuna central para delegação;
  lock-in a uma única nuvem; exige recursos AWS reais para desenvolvimento local; claim de
  grupos com prefixo de fornecedor; controle limitado sobre o conteúdo do token e sobre a UX
  de login.

### Opção 3 — IdP SaaS gerenciado (Auth0, Okta ou Microsoft Entra ID)

- **A favor:** operação gerenciada com contrato de suporte; recursos corporativos maduros;
  federação e integração com diretórios robustas.
- **Contra:** preço por usuário ativo ou por assento, que escala mal para uma plataforma
  auto-hospedável; dependência externa para desenvolvimento local; provisionamento de tenant
  não é self-service para contribuidores; a plataforma passaria a depender de uma conta
  comercial para ser utilizável.

### Opção 4 — Autenticação nativa da aplicação

Tabela própria de usuários, hash de senhas e JWTs emitidos localmente.

- **A favor:** nenhuma dependência externa; controle total.
- **Contra:** reimplementaríamos OIDC discovery, PKCE, rotação de refresh, token exchange e
  federação — trabalho crítico de segurança sem valor diferenciador, e que quebraria o modelo
  de authorizer JWT do AgentCore, que espera um issuer OIDC real.

## Decisão

**Usar o Keycloak como provedor de identidade na versão inicial**, registrado através do tipo
de provider `generic_oidc` que já existe.

Concretamente, para a versão inicial:

- O Keycloak é o único emissor de tokens de usuário. Ele é registrado como um registro
  `IdentityProvider` com `provider_type = "generic_oidc"`, `issuer_url` apontando para o realm
  (`https://<host>/realms/<realm>`) e `client_type = "public"`, para que o navegador complete a
  troca Authorization Code + PKCE diretamente.
- O modelo de grupos do Loom vive nos grupos do Keycloak, expostos por um mapper de claim
  `groups`. O `group_claim_path` é definido como `groups`; o `group_mappings` traduz nomes de
  grupos do realm para grupos do Loom quando os nomes divergirem.
- O backend valida tokens contra o JWKS URI do realm, resolvido via OIDC discovery. Nenhum
  código de validação específico do Keycloak é introduzido.
- Agentes do AgentCore Runtime que exigem authorizer JWT são configurados com a URL de
  discovery do realm do Keycloak como provider OIDC customizado, e com o client ID do Keycloak
  em `allowedClients`, para que tokens de usuário sejam aceitos no momento da invocação.
- O Keycloak roda como container com PostgreSQL como armazenamento. Em desenvolvimento local
  isso é um único container com um realm importado; em ambientes implantados é um serviço atrás
  do load balancer existente, com seu próprio banco.
- A configuração do realm (clients, grupos, scopes, mappers de claim) é versionada como um
  arquivo de importação de realm, para que os ambientes sejam reprodutíveis em vez de
  configurados à mão.

## Consequências

### Positivas

- A delegação passa a ter um caminho no próprio provider: o suporte nativo a RFC 8693 no
  Keycloak significa que o token exchange não precisa ser intermediado por outro serviço.
- O login funciona de forma idêntica em desenvolvimento local, on-premises e em qualquer nuvem,
  então a camada de autenticação é escrita e testada uma única vez.
- Contribuidores conseguem rodar a experiência autenticada completa a partir de um container,
  sem conta em nuvem e sem tenant compartilhado.
- O formato das claims é nosso para definir, então o mapeamento de grupos para scopes fica
  livre de nomes de claim específicos de fornecedor.
- Sem custo por usuário conforme a adoção cresce.
- Os destinos de deployment não ficam restritos pela escolha do IdP.

### Negativas

- Passamos a operar um serviço crítico para disponibilidade: se o Keycloak cair, ninguém entra.
  Ele precisa de health checks, backups, um caminho de restauração testado e uma rotina de
  upgrade.
- A cadência de upgrades do Keycloak é frequente e ocasionalmente introduz mudanças
  incompatíveis de administração ou configuração, o que se torna manutenção recorrente.
- Um banco e um container adicionais aumentam custo e superfície em comparação com um user pool
  gerenciado.
- O endurecimento do próprio Keycloak (exposição do console de administração, proteção contra
  força bruta, terminação TLS, rotação de chaves do realm) é nossa responsabilidade.
- Não há fornecedor para escalar durante um incidente.

### Neutras

- Como a integração usa o caminho OIDC genérico em vez de código específico do Keycloak, trocar
  de provider depois é uma mudança de configuração mais uma revisão do mapeamento de grupos, e
  não uma reescrita. Esta escolha é deliberadamente reversível.
- Os caminhos de código específicos do Cognito que já existem na plataforma continuam
  disponíveis e não são removidos por esta decisão; eles simplesmente não são a configuração
  com que a versão inicial vai ao ar. Tudo que depende do Cognito além do login de usuário —
  credenciais machine-to-machine para invocação entre serviços e os scopes customizados do
  resource server do Cognito — precisa de um client e de client scopes equivalentes no Keycloak
  antes que esses fluxos rodem apenas com o Keycloak.

## Revisitar esta decisão se

- Operar o Keycloak consumir mais atenção de manutenção do que a capacidade de delegação
  justifica.
- O Cognito (ou a alternativa escolhida) ganhar token exchange (RFC 8693), o que remove o
  principal fator técnico.
- Um ambiente de destino exigir um IdP que a organização já opera, tornando a integração
  apenas por federação preferível a rodar o nosso próprio.
- Requisitos de escala ou de conformidade tornarem obrigatório um provedor comercial com
  suporte.
