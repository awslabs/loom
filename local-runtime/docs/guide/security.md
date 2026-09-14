# Segurança (APIs, web e sidecars)

Guia **objetivo** para este fork: Loom BFF (FastAPI), UI React, sidecars
(`mcp-hub`, `mcp-runtime`, `agent-runtime`, `cursor-adapter`), OAuth/OIDC,
Postgres. Complementa [rules.md](rules.md) e [development.md](development.md).

Não é um curso OWASP completo — só o que costuma aparecer **aqui**.

---

## 1. Princípios deste projeto

| Princípio | Prática |
|-----------|---------|
| **Fail-closed** | Sem token / JWT inválido / scope ausente → `401`/`403`, nunca “seguir como anônimo” |
| **Least privilege** | Scopes IdP (`mcp:read`/`write`, `invoke`); Hub grants por perfil; service token **só** Hub↔BFF |
| **Segredos fora do git** | `.env`, Secrets Manager / Parameter Store; revisar diff antes de commit |
| **Trust boundaries** | Browser ≠ sidecar; JWT do frontend (`aud` Loom) **não** autentica o Hub; Hub usa `aud`/`resource` próprio |
| **Dados mínimos** | Não logar tokens, refresh, PATs, PII desnecessária |

Specs/ADRs úteis: [0011 OAuth Hub](../adr/0011-mcp-hub-oauth-idp.md),
[019 Hub security](../specs/019-mcp-hub-security.md),
[008 MCP security](../specs/008-local-mcp-security.md).

---

## 2. OWASP Top 10 (2021) — mapa filtrado

| # | Risco | Relevante aqui? | O que fazer neste stack |
|---|--------|-----------------|-------------------------|
| **A01** Broken Access Control | **Sim** | Checar scopes em toda rota; Hub: canal `enabled` + grants + RBAC `loom:group` em agents; não confiar só no UI |
| **A02** Cryptographic Failures | **Sim** | TLS em prod; HTTPS IdP; não armazenar access token em `mcp.json`; cookies Secure/HttpOnly se session cookie |
| **A03** Injection | **Sim** | SQL via SQLAlchemy/params; sem concatenar SQL; MCP tool args tratados como **dados**, não código; stdio allowlist |
| **A04** Insecure Design | **Parcial** | Preferir OAuth (ADR 0011) a mint; ports/adapters não vazam service token ao browser |
| **A05** Security Misconfiguration | **Sim** | Defaults fail-closed; portas Hub em loopback em local; não expor Docker ports abertos; desligar debug em prod |
| **A06** Vulnerable Components | **Sim** | Pin deps; `npm`/`uv` audit periódico; imagens slim |
| **A07** Identification & Auth Failures | **Sim** | Validar JWT (iss, aud, exp, assinatura JWKS); PKCE no IDE; sem fallback `hs_…` |
| **A08** Software/Data Integrity | **Parcial** | Templates MCP allowlisted; não executar YAML arbitrário do usuário sem review |
| **A09** Logging/Monitoring Failures | **Parcial** | Logar `sub`, client slug, negações auth — **não** Bearer completo; alertar 401 em massa se houver ops |
| **A10** SSRF | **Sim** | Sidecars/BFF que fazem fetch (Loom URL, MCP endpoints): allowlist hosts; não passar URL crua do cliente sem validar |

Itens pouco aplicáveis agora (não expandir): XSS em CMS legado, deserialization Java, etc. XSS ainda importa na **SPA** — ver §4.

---

## 3. RFCs e padrões (só os que usamos)

| Referência | Uso aqui |
|------------|----------|
| **RFC 6749** OAuth 2.0 | Code flow IdP ↔ IDE / frontend |
| **RFC 7636** PKCE | Obrigatório no client público do Hub (`loom-mcp-hub`) |
| **RFC 8252** OAuth for Native Apps | Redirect `cursor://…` / localhost callback |
| **RFC 7519** JWT | Access tokens; validar claims, não só “parse” |
| **RFC 8725** JWT Best Practices | `aud` estrito; rejeitar `none`; clock skew limitado |
| **RFC 6750** Bearer Token Usage | `Authorization: Bearer`; `WWW-Authenticate` em 401 do Hub |
| **RFC 9700** (OAuth 2.1 draft family / best current) | Preferir practices 2.1: PKCE, sem implicit |
| **OIDC Core** | `openid`/`profile`; discovery JWKS do IdP ativo |
| **MCP OAuth / PRM** | Protected Resource Metadata; Hub como resource server |

Não inventar segundo protocolo de mint paralelo ao IdP.

---

## 4. Web (React / Vite)

| Ameaça | Mitigação |
|--------|-----------|
| **XSS** | React escapa texto por padrão; evitar `dangerouslySetInnerHTML` / `eval`; sanitizar markdown se renderizar HTML |
| **Token no JS** | Preferir fluxo do host (AuthContext); não persistir access token em `localStorage` se o Loom já tiver padrão mais seguro; nunca logar token |
| **CSRF** | APIs Bearer (header) reduzem CSRF clássico de cookie; se cookie de sessão existir, SameSite + CSRF token |
| **Open redirect** | Validar `redirect_uri` só nas listas do client IdP |
| **Deps front** | Não embutir secrets em `VITE_*` |

---

## 5. APIs (FastAPI / sidecars HTTP)

| Tema | Regra |
|------|--------|
| Authn | Toda rota sensível exige Bearer válido **antes** de lógica |
| Authz | Scope / grupo / ownership de session (`user_id`) — ex.: runs de agent |
| Input | Validar body (Pydantic / checks); limites de tamanho em upload/prompt |
| Erros | Mensagens genéricas ao client (`unauthorized`); detalhe só em log servidor |
| Service token | `MCP_HUB_SERVICE_TOKEN` / `AGENT_RUNTIME_TOKEN`: rede interna, nunca no browser |
| CORS | Origens explícitas em prod; não `*` com credentials |
| Rate / abuse | Em local opcional; em prod considerar limite em Hub OAuth e invoke |

---

## 6. Dados sensíveis e PII

| Classe | Exemplos neste repo | Tratamento |
|--------|---------------------|------------|
| **Segredos** | IdP client secret, `CURSOR_API_KEY`, Azure PAT, service tokens | Só env/secret store; rotação; nunca em ADR/changelog/issue |
| **Credenciais de sessão** | Access/refresh JWT | Cofre do IDE / cookie seguro; TTL curto |
| **PII** | `sub`, username, e-mail de claims | Mínimo necessário; mascarar em logs UI; não gravar prompt completo em log se contiver PII |
| **Conteúdo de tools** | Outputs Grafana/ADO/agent | Respeitar RBAC; não ecoar secrets de tool result em telemetria |

Checklist commit: `git diff` sem `sk-`, `eyJ` (JWT), `pat:`, senhas.

---

## 7. Injection e XSS (checagem rápida)

### SQL injection

- Sempre ORM/SQLAlchemy com binds; **proibido** f-string em SQL
- Raw SQL só com parâmetros nomeados e review

### Command / stdio

- `mcp-runtime`: só templates allowlisted; sem shell a partir de input do usuário
- Argumentos de tool ≠ argv do SO sem escaping/allowlist

### XSS / HTML

- UI: sem HTML não sanitizado
- Respostas API: `Content-Type` correto (`application/json`); não refletir input em HTML server-side (BFF quase não faz SSR)

### Path / header injection

- Não concatenar `session_id` / slug em path de filesystem sem validar charset
- Headers de outbound (Loom URL) sob config de ambiente, não do body do client

---

## 8. Checklist antes de merge (feature local-runtime)

- [ ] Rotas novas: authn + authz fail-closed?
- [ ] Tokens/secrets só em env / store?
- [ ] Sem SQL/command concat com input?
- [ ] UI sem HTML cru / sem token em log?
- [ ] Service token inacessível ao browser?
- [ ] Logs sem Bearer/PII desnecessária?
- [ ] URLs outbound allowlisted ou fixas de config?
- [ ] Se exceção Core: ok do Dev + [CHANGELOG](../CHANGELOG-LOOM-FORK.md)?

---

## 9. Fora de escopo (de propósito)

Não cobrir neste guia (infla sem uso imediato): PCI-DSS detalhado, mobile hardening, threat modeling STRIDE completo, checklist ISO 27001, OWASP ASVS nível 3 página a página. Se surgir necessidade real → item em [backlog](../backlog/refactoring.md) ou nova spec sob `local-runtime/docs/specs/`.
