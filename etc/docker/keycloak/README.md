# Realm `loom` (apenas desenvolvimento local)

Este diretório é montado em `/opt/keycloak/data/import` e importado por
`start-dev --import-realm`. O importador do Keycloak rejeita campos desconhecidos,
então `realm-loom.json` não pode conter comentários — o motivo de cada escolha está
aqui.

**Todas as credenciais deste diretório são valores descartáveis de desenvolvimento.**
Nunca as reutilize em um ambiente implantado, onde elas pertencem ao AWS Secrets
Manager. As senhas locais são `Loom-Local-Dev-1` para os usuários do realm e
`admin`/`admin` para o console administrativo.

## Decisões que não são óbvias

- **`sslRequired: "none"`** — o padrão do Keycloak (`external`) recusa requisições
  HTTP que não venham de loopback. Dentro do Docker, o endereço de origem é o
  gateway da rede bridge, não loopback, então o login falharia com "HTTPS required".

- **Mapper `loom-audience`** (`oidc-audience-mapper`) — o Keycloak coloca o client ID
  em `azp`, não em `aud`. O backend valida `aud` contra o client ID, então sem este
  mapper todo access token é rejeitado. `access.token.claim` precisa estar habilitado;
  `id.token.claim` não é necessário.

- **Mapper `groups`** (`oidc-group-membership-mapper`) — `full.path` precisa ser
  `false`, porque os nomes de grupo do Loom não têm barra inicial e `/g-admins-super`
  não corresponderia a nenhum scope. A claim é necessária nos **dois** tokens: o
  frontend lê os grupos do `id_token` e o backend, do access token.

- **Client público com PKCE S256** — o SPA não pode guardar um segredo. O
  `client_type` do provider no Loom é `public`, então a troca do código acontece
  direto entre o navegador e o Keycloak.

- **Client `loom-mcp-hub`** — OAuth público + PKCE para MCP Clients (Cursor).
  Audience `loom-mcp-hub` no access token; redirects `cursor://…` e
  `http://localhost:8787/callback` (loopback atual do Cursor). No `mcp.json`
  use `auth.CLIENT_ID: "loom-mcp-hub"` para evitar DCR (Trusted Hosts).
  Este client é o AS **local** (Keycloak); com Microsoft Entra ID como IdP
  ativo, use app registration equivalente — o Hub só lê issuer/JWKS/groups.
  Ver ADR 0011 / spec 024.

## Usuários

| Usuário | Grupos |
| --- | --- |
| `admin` | `t-admin`, `g-admins-super` |
| `demo-admin-1` | `t-admin`, `g-admins-demo` |
| `security-admin` | `t-admin`, `g-admins-security` |
| `integration-admin` | `t-admin`, `g-admins-memory`, `g-admins-mcp`, `g-admins-a2a` |
| `registry-admin` | `t-admin`, `g-admins-registry` |
| `demo-user-1` | `t-user`, `g-users-demo` |
| `test-user` | `t-user`, `g-users-test` |
| `strategics-user` | `t-user`, `g-users-strategics` |

Os nomes de usuário são funcionais, não decorativos: `App.tsx` extrai o índice de
`^demo-admin-(\d+)$` para restringir a visão a `demo-user-N`, e o backend semeia
perfis de tag para `demo-user-1` a `demo-user-9`.

Os grupos usam caminhos com barra (`/t-admin`) na declaração do usuário. Isso é
independente de `full.path`, que afeta apenas a claim no token.
