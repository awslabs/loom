# Loom: Agent Builder Playground — Specifications

## 1. Overview

Loom is an agent builder playground that simplifies the lifecycle of building, testing, integrating, deploying, and operating AI agents built on Amazon Bedrock AgentCore Runtime and AWS Strands Agents. The platform consists of:

- A **FastAPI backend** that encapsulates all AWS interactions and business logic.
- A **React/TypeScript frontend** (Vite, shadcn, Tailwind CSS) that interacts exclusively through the backend API.
- A **relational database** (via SQLAlchemy) — SQLite for local development or PostgreSQL for cloud deployments — for persisting agent metadata, session history, security configurations, and credential management.

The platform tracks session liveness using a local idle timeout heuristic, providing cold-start indicators so users know whether their next invocation will incur agent startup latency.

### Persona-Based Workflows

The frontend is organized around persona-based workflows, accessible via a sidebar:

- **Platform Catalog** (default) — Browse and manage agents, memory resources, and other platform resources. Includes sections for MCP Servers and A2A Agents.
- **Agents** — Deploy new agents or import existing ones. Includes agent listing with card/table view toggle.
- **Security Admin** — Manage IAM roles, authorizer configurations, credentials, and permission requests.
- **Memory** — Create new AgentCore Memory resources with configurable strategies or import existing ones.
- **Tagging** — Manage tag policies (platform + custom) and tag profiles. Accessible to all scopes; write operations require `*:write`.
- **Settings** — Manage display preferences (theme, timezone). Accessible to all scopes.
- **MCP Servers** — Register and manage MCP servers, view available tools, and control persona access.
- **A2A Agents** — Register and manage A2A (Agent-to-Agent) protocol integrations, view Agent Cards, and control persona access to skills.
- **Registry** (opt-in) — Browse and manage AWS Agent Registry records for governance and discovery. When enabled, agents are auto-registered on deployment and must be approved before end-users can access them. MCP servers and A2A agents must also be approved before they can be used in agent deployments. Supports full record lifecycle (create, submit, approve, reject, delete) and semantic search.
- **Admin Dashboard** — Platform usage analytics for super-admins. Tracks user logins, user actions, and page navigation at the browser session level. Includes summary cards, charts, and per-session drill-down.

---

## 2. Directory Structure

```
loom/
├── agents/                     # Agent blueprint source code
│   └── strands_agent/          # Strands Agent blueprint
│       ├── handler.py          # Agent handler / entry point (trace_invocation wrapped)
│       ├── config.py           # Agent configuration
│       ├── integrations/       # Tool and service integrations
│       │   ├── mcp_client.py   # MCP tool client vending
│       │   ├── a2a_client.py   # A2A agent client vending
│       │   └── memory.py       # AgentCore Memory hooks (MemoryHook)
│       └── telemetry.py        # OTEL setup, ADOT auto-instrumentation, TelemetryHook
├── backend/                    # Backend API (see backend/SPECIFICATIONS.md)
│   ├── app/
│   │   ├── main.py             # FastAPI app (docs at /api/docs, /api/redoc, /api/openapi.json)
│   │   ├── db.py
│   │   ├── models/
│   │   ├── dependencies/
│   │   ├── routers/
│   │   └── services/
│   ├── scripts/
│   ├── tests/
│   ├── etc/                     # Backend environment config (app + ECS backend service)
│   │   ├── environment.sh       # Sources account-specific file + shared outputs
│   │   ├── models.json          # Supported model catalog (model_id, display_name, group, pricing)
│   │   └── runtime_pricing.json # AgentCore Runtime pricing constants
│   ├── iac/                     # Backend infrastructure
│   │   ├── rds.yaml             # RDS PostgreSQL with optional RDS Proxy
│   │   ├── ec2.yaml             # EC2 bastion for SSM tunnel to RDS
│   │   └── ecs.yaml             # Backend ECS Fargate service (task def, service, auto-scaling)
│   ├── Dockerfile               # Backend container image (Python 3.13 slim + uvicorn)
│   ├── makefile
│   └── SPECIFICATIONS.md
├── frontend/                    # Frontend UI (see frontend/SPECIFICATIONS.md)
│   ├── src/
│   ├── etc/                     # Frontend environment config (ECS frontend service)
│   │   └── environment.sh       # Sources account-specific file + shared outputs
│   ├── iac/
│   │   └── ecs.yaml             # Frontend ECS Fargate service (task def, service)
│   ├── Dockerfile               # Frontend container image (multi-stage Node + nginx)
│   ├── nginx.conf               # nginx SPA config with gzip and cache headers
│   ├── makefile
│   └── SPECIFICATIONS.md
├── shared/                      # Shared IaC, deployment, and security
│   ├── iac/
│   │   ├── role.yaml            # SAM template for IAM roles
│   │   ├── cognito.yaml         # SAM template for Cognito pools, groups, users, scopes
│   │   ├── dns.yaml             # Route 53 hosted zone for subdomain delegation
│   │   ├── infra.yaml           # Shared infra: S3, ECR, ACM, ALB, security groups, Route 53
│   │   └── ecs.yaml             # ECS Fargate cluster (shared by frontend and backend)
│   ├── etc/
│   │   ├── environment.sh       # Sources account-specific config
│   │   └── outputs_<profile>.sh # Centralized stack outputs (auto-generated)
│   ├── scripts/
│   │   └── capture_outputs.py   # Query all stacks, write outputs + frontend/.env
│   └── makefile                 # Cognito, infra, ECS, podman build/push, deploy
├── CLAUDE.md
├── README.md
└── SPECIFICATIONS.md            # This file (project-level specification)
```

---

## 3. Component Specifications

Detailed specifications for each component are maintained in their respective directories:

- **Backend:** [`backend/SPECIFICATIONS.md`](backend/SPECIFICATIONS.md) — API endpoints, database schema, service modules, streaming architecture, latency measurement flow, security management, memory resource management, tag policies and profiles.
- **Frontend:** [`frontend/SPECIFICATIONS.md`](frontend/SPECIFICATIONS.md) — Technology stack, persona-based navigation, Platform Catalog/Agents/Security Admin/Memory/Settings workflows, streaming behavior.

---

## 4. Security Considerations

- No credentials, tokens, or secrets are committed to git.
- `etc/environment.sh` and `.env` files are listed in `.gitignore`.
- The backend uses the standard boto3 credential chain (environment variables, AWS profile, instance metadata) — no hardcoded credentials.
- All AWS API calls follow least-privilege IAM.
- CORS is configured to allow `localhost:{FRONTEND_PORT}` in development. When deployed, the `LOOM_ALLOWED_ORIGINS` environment variable adds additional allowed origins (e.g., the ALB domain).
- Cognito client secrets are stored in AWS Secrets Manager, never in the local database.
- The backend retrieves secrets at invocation time with in-memory caching (5-minute TTL).
- Secrets are cleaned up from Secrets Manager when authorizer credentials or agents are deleted.
- Security administration (roles, authorizers, credentials, permissions) is managed through a dedicated persona workflow.
- Human-in-the-loop (HITL) approval policies enforce human oversight for sensitive tool calls. Four HITL methods are supported: agentic loop hooks (custom agents), tool context interrupts (custom agents), MCP elicitation (custom agents with MCP), and harness inline functions (managed agents).
- On-behalf-of (OBO) token exchange (RFC 8693) enables agents to access downstream OAuth2 resources with the invoking user's scoped permissions. Configurable per MCP server and A2A agent via `delegation_mode` (m2m or obo).

### User Authentication

- Users authenticate via an AWS Cognito User Pool using the `USER_PASSWORD_AUTH` flow.
- The frontend stores tokens (id, access, refresh) in React state only — never in localStorage or cookies.
- The backend validates user JWTs against the Cognito JWKS endpoint (keys cached for 1 hour).
- The `GET /api/auth/config` endpoint exposes only the pool ID and region — never client IDs or secrets.
- The user client ID is configured on the frontend via the `VITE_COGNITO_USER_CLIENT_ID` environment variable (Vite `.env` file). The user client has `GenerateSecret: false` since browser-based apps cannot safely store client secrets.
- When a user is authenticated, their access token is forwarded to OAuth-protected AgentCore agents. The backend auto-includes the user app client ID in the agent's `allowedClients` on deploy. M2M credentials remain available for service-to-service integrations.
- Unauthenticated requests are allowed to pass through with a warning (no breaking change to existing flows).
- The `NEW_PASSWORD_REQUIRED` Cognito challenge is handled on first login for admin-created users.
- Access tokens are automatically refreshed before expiry using the refresh token.
- On 401 responses, the frontend automatically refreshes the access token and retries the failed request.
- Token persistence across browser refreshes is out of scope — users must re-login after page reload.

### Cognito User Pool Configuration

The Cognito User Pool is managed via CloudFormation (`shared/iac/cognito.yaml`) and includes:

- **Password policy:** Minimum 12 characters, uppercase, lowercase, numbers required; symbols not required.
- **Resource server scopes (21 total):** `invoke`, `catalog:read`, `catalog:write`, `agent:read`, `agent:write`, `memory:read`, `memory:write`, `security:read`, `security:write`, `settings:read`, `settings:write`, `tagging:read`, `tagging:write`, `costs:read`, `costs:write`, `mcp:read`, `mcp:write`, `a2a:read`, `a2a:write`, `registry:read`, `registry:write`.
- **Two-dimensional group architecture:**
  - **Type groups** (UI view): `t-admin` (admin UI with all pages), `t-user` (user UI with Catalog, Agents, Memory, Costs only)
  - **Admin groups** (t-admin users, single group): `g-admins-super` (all scopes), `g-admins-demo` (read/write to most pages including MCP and A2A + demo group resources), `g-admins-security` (security:read/write, settings:read, tagging:read/write), `g-admins-memory` (memory:read/write, settings:read, tagging:read/write), `g-admins-mcp` (mcp:read/write, settings:read, tagging:read/write), `g-admins-a2a` (a2a:read/write, settings:read, tagging:read/write), `g-admins-registry` (mcp:read, a2a:read, registry:read/write, settings:read/write, tagging:read)
  - **User groups** (t-user users, can have multiple): `g-users-demo`, `g-users-test`, `g-users-strategics` (each grants: catalog:read, agent:read, memory:read, costs:read, costs:write, invoke)
- **Users:** `admin` (t-admin + g-admins-super), `demo-admin` (t-admin + g-admins-demo), `security-admin` (t-admin + g-admins-security), `integration-admin` (t-admin + g-admins-memory + g-admins-mcp + g-admins-a2a), `registry-admin` (t-admin + g-admins-registry), `demo-user` (t-user + g-users-demo) — each assigned to both type and group via `UserPoolUserToGroupAttachment`.
- **Clients:**
  - **M2MClient** — `client_credentials` flow with secret, scoped to `invoke`.
  - **UserClient** — `USER_PASSWORD_AUTH` + `REFRESH_TOKEN_AUTH` flows without secret, scoped to all custom scopes plus `openid`, `email`, `profile`.
- User passwords are set via `make cognito.set-passwords` in the `shared/` directory.

### Scope-Based Frontend Authorization

The frontend enforces scope-based access control derived from Cognito group membership:

| Group | Scopes | Sidebar Access | Write Access |
|-------|--------|----------------|--------------|
| `g-admins-super` | All 21 scopes | All pages (including Admin Dashboard) | All actions |
| `g-admins-demo` | catalog:read, agent:read, agent:write, memory:read, memory:write, security:read, settings:read, settings:write, tagging:read, costs:read, costs:write, mcp:read, mcp:write, a2a:read, a2a:write, invoke | All admin pages | Read/write restricted to demo group resources only |
| `g-admins-security` | security:read, security:write, settings:read, tagging:read, tagging:write | Security, Settings, Tagging | Security + tag policy/profile management |
| `g-admins-memory` | memory:read, memory:write, settings:read, tagging:read, tagging:write | Memory, Settings, Tagging | Memory + tag policy/profile management |
| `g-admins-mcp` | mcp:read, mcp:write, settings:read, tagging:read, tagging:write | MCP Servers, Settings, Tagging | MCP + tag policy/profile management |
| `g-admins-a2a` | a2a:read, a2a:write, settings:read, tagging:read, tagging:write | A2A Agents, Settings, Tagging | A2A + tag policy/profile management |
| `g-admins-registry` | mcp:read, a2a:read, registry:read, registry:write, settings:read, settings:write, tagging:read | Registry, Settings, Tagging | Registry governance + settings management |
| `g-users-*` | catalog:read, agent:read, memory:read, costs:read, costs:write, invoke | Catalog, Agents, Memory, Costs | No write access; costs:write for cost settings only |

- **Sidebar visibility:** Each sidebar item is shown only when the user has the corresponding `*:read` or `*:write` scope. The Platform Catalog is always visible. Type groups determine the overall UI view (t-admin sees all admin pages, t-user sees only Catalog/Agents/Memory/Costs).
- **Write protection:** Components receive a `readOnly` prop that disables or hides add, edit, and delete buttons when the user lacks `*:write` scopes. Demo-admins see delete buttons only for resources tagged with `loom:group=demo`.
- **Resource filtering:** Admins (t-admin) see all resources including untagged. Users (t-user) see only resources matching their group tags (union semantics for multiple groups).
- **Tag profile management:** Only super-admins can edit/delete custom tag policies. Demo-admins can only edit/delete tag profiles with `loom:group=demo`.
- **Bypass mode:** When authentication is not configured (no Cognito pool ID or client ID), all scopes are granted and all features are accessible.

---

## 5. Supported Foundation Models

Model metadata (display names, groups, pricing) and AgentCore Runtime pricing are maintained in external JSON configuration files (`backend/etc/models.json` and `backend/etc/runtime_pricing.json`), loaded at backend startup. Models are organized by vendor group and sorted alphabetically in the UI via the `groupModels()` utility.

**Anthropic:**
- Claude Opus 4.7 (`anthropic.claude-opus-4-7`)
- Claude Opus 4.6 (`us.anthropic.claude-opus-4-6-v1`)
- Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`)
- Claude Opus 4.5 (`us.anthropic.claude-opus-4-5-20251101-v1:0`)
- Claude Sonnet 4.5 (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`)

**Amazon:**
- Nova 2 Lite (`us.amazon.nova-2-lite-v1:0`)
- Nova Pro (`us.amazon.nova-pro-v1:0`)
- Nova Lite (`us.amazon.nova-lite-v1:0`)
- Nova Micro (`us.amazon.nova-micro-v1:0`)

**DeepSeek:**
- DeepSeek v3.2 (`deepseek.v3.2`)
- DeepSeek-R1 (`deepseek.r1-v1:0`)

**Google:**
- Gemma 3 12B IT (`google.gemma-3-12b-it`)
- Gemma 3 27B PT (`google.gemma-3-27b-it`)
- Gemma 3 4B IT (`google.gemma-3-4b-it`)

**Meta:**
- Llama 4 Maverick 17B Instruct (`meta.llama4-maverick-17b-instruct-v1:0`)
- Llama 4 Scout 17B Instruct (`meta.llama4-scout-17b-instruct-v1:0`)
- Llama 3.3 70B Instruct (`meta.llama3-3-70b-instruct-v1:0`)

**MiniMax:**
- MiniMax M2.5 (`minimax.minimax-m2.5`)
- MiniMax M2.1 (`minimax.minimax-m2.1`)
- MiniMax M2 (`minimax.minimax-m2`)

**Moonshot AI:**
- Kimi K2.5 (`moonshotai.kimi-k2.5`)
- Kimi K2 Thinking (`moonshot.kimi-k2-thinking`)

Model selectors in the UI are searchable by both display name and model ID, with grouped sections sorted alphabetically by vendor. No default is pre-selected — the user must explicitly choose a model.

### Admin-Enabled Models

Administrators can restrict which models are available for agent deployment and runtime selection via the Settings page ("Enabled Models" section). The `enabled_model_ids` site setting stores a JSON array of allowed model IDs. When the list is empty (default), all models are available. The `GET /api/agents/models` endpoint filters the full model catalog by this setting before returning results. The `GET /api/settings/models` and `PUT /api/settings/models` endpoints manage the configuration (requires `settings:read` / `settings:write` scopes).

### Alternate Providers (LiteLLM Proxy)

The list above is Bedrock's curated catalog. When a self-hosted LiteLLM proxy connection is configured (Settings → Models → LiteLLM), agents can instead be deployed with `provider="litellm"`, and the model catalog is extended with whatever models the proxy itself reports live (`GET /api/agents/models/litellm`) — no Loom code changes needed to add a new model, since the proxy owns that catalog. See [Phase 32](#phase-32--alternate-llm-providers-litellm-proxy-complete) below and `backend/SPECIFICATIONS.md` § 16 for the full design (provider registry, per-agent virtual key vending, dynamic catalog merging, IAM/IaC).

### Runtime Model Selection

Agents support runtime model selection, allowing users to choose from a set of allowed models at invoke time rather than being locked to a single model:

- **`allowed_model_ids`** — A JSON array stored on the `agents` table specifying which models the agent can use. Defaults to `[model_id]` (the deploy/register model) when not explicitly set.
- **Deploy form** — An "Allowed Models (runtime selection)" checkbox section appears after selecting the default model. The deploy model is always included and cannot be unchecked.
- **Agent detail / Deployment panel** — Displays allowed models grouped by vendor with an inline edit mode (pencil icon) for updating the allowed list and default model post-deployment.
- **Invoke panel** — A model dropdown appears when the agent has multiple allowed models. The dropdown is disabled when only one model is available. Selecting a non-default model passes `model_id` in the invoke request.
- **ChatPage** — A model picker button appears in the input area footer when the agent has multiple allowed models. Click to open a dropdown; selecting a model applies it to subsequent invocations.
- **Backend validation** — `POST /api/agents/{id}/invoke` validates the optional `model_id` parameter against the agent's `allowed_model_ids`. Returns HTTP 400 if the model is not in the allowed list. The validated model overrides the agent's default for that invocation.
- **PATCH endpoint** — `PATCH /api/agents/{id}` accepts `model_id` and `allowed_model_ids` fields for updating model configuration. Description changes are propagated to AgentCore via `update_runtime`.

---

## 6. Implementation Phases

### Phase 1 — MVP (Initial Implementation) *(Complete)*
- Backend: Agent registration, metadata retrieval, SSE invocation with real-time streaming, CloudWatch log retrieval (stream browsing + session-filtered with pagination), integrated cold-start latency calculation, SQLite persistence with session/invocation separation, session liveness tracking via idle timeout heuristic, active session count per agent.
- CLI: Streaming invocation client (`scripts/stream.py`) and comprehensive `makefile` targets for manual testing.
- Frontend: Build tab (ARN registration), Test tab (invocation + streaming + latency display), Operate tab (basic dashboard), active session count display on agent cards, session live status indicators.
- Refactored `tmp/latency/` into reusable service modules.

### Phase 2 — Agent Deployment *(Complete)*
- Agent deployment to AgentCore Runtime from the Strands Agent blueprint.
- Auto-build artifact pipeline (pip cross-compile for ARM64, S3 upload, zip packaging).
- Configurable deploy form: model selection (grouped, searchable), protocol (HTTP; MCP/A2A coming soon), network mode (PUBLIC; VPC coming soon), IAM role (searchable select or auto-create), authorizer (Cognito JWT with auto-populated discovery URL, or custom OIDC provider), lifecycle timeouts, integrations (coming soon).
- Cognito OAuth2 token retrieval for authenticated agent invocations (client credentials grant).
- Secret management via AWS Secrets Manager for Cognito client secrets.
- Agent deletion with optional AgentCore cleanup (runtime + endpoint removal).
- Account ID extraction from runtime ARN on deploy and refresh.

### Phase 3 — Persona-Based Workflows *(Complete)*
- Persona-based frontend navigation: Platform Catalog, Agents, Security Admin, Memory, MCP Servers, A2A Agents.
- Platform Catalog page with sections for agents, memory resources, MCP servers, and A2A agents. Card/table view toggle with cards as default.
- Agents page (formerly Builder) with agent listing (card/table view toggle), Add Agent button with Deploy/Import tabs.
- Security Admin page for managing IAM roles, authorizer configs, authorizer credentials, and permission requests.
- Model selector on both register and deploy forms with no default selection.
- Model ID tracked on agent responses for display on invoke page.
- Credential-based invocation: select a credential from an authorizer config to generate an OAuth token at invoke time.
- Token indicator on invoke responses (`has_token`, `token_source` in SSE session_start).
- Configurable session defaults via `LOOM_SESSION_IDLE_TIMEOUT_SECONDS` and `LOOM_SESSION_MAX_LIFETIME_SECONDS` environment variables, exposed via `/api/agents/defaults`.

### Phase 4 — AgentCore Memory Resources *(Complete)*
- Backend API for creating, managing, and deleting AgentCore Memory resources.
- Memory strategies: semantic, summary, user_preference, episodic, and custom — mapped to AWS tagged union format.
- Local SQLite persistence for memory resource metadata with status tracking.
- Refresh endpoint to poll AWS for latest memory status.
- AWS error mapping: ValidationException→400, ConflictException→409, ResourceNotFoundException→404, AccessDeniedException→403, ThrottledException/ServiceQuotaExceededException→429.
- Makefile curl targets for manual testing of all memory endpoints.
- Frontend Memory persona: memory card and table views with card/table toggle (cards default), create form with strategy configuration, status badges, refresh and delete actions, toast notifications for all operations.
- Memory import endpoint (POST /api/memories/import) for importing existing AgentCore Memory resources.
- Async deletion flow: backend returns DELETING status, frontend polls for updates, detects 404 when resource is fully deleted, then purges locally.
- "Also delete in AgentCore" checkbox on memory deletion for optional upstream cleanup.
- Timer persistence across navigation using server timestamps.
- Purge endpoint (DELETE /api/memories/{id}/purge) for local database cleanup after confirmed deletion.
- View mode (card/table) state lifted to App.tsx and persisted per-page across persona switches.

### Phase 5 — AgentCore Observability *(Complete)*
- Deployment entry point wrapped with `opentelemetry-instrument` CLI for ADOT auto-instrumentation of boto3, HTTP clients, and other libraries at process startup.
- `TelemetryHook` on the Strands Agent that creates OTEL spans for tool calls and model invocations as children of the invocation span.
- `trace_invocation()` wraps each handler invocation with a root span carrying `agent.session_id` and `agent.invocation_id` attributes.
- Noop mode when running locally without the `opentelemetry-instrument` wrapper — no errors, no performance overhead.
- `OTEL_SERVICE_NAME` is automatically set to the agent name at deploy time.
- `AGENT_OBSERVABILITY_ENABLED` is set to `true` at deploy time, which activates the `aws-opentelemetry-distro` export pipeline (OTEL traces exported to CloudWatch logs/metrics).
- Console script shebang fix: the build pipeline rewrites `opentelemetry-instrument` (and `opentelemetry-bootstrap`) scripts with a portable `#!/usr/bin/env python3` shebang so they execute correctly on the Linux-based AgentCore Runtime container.
- Unit tests for telemetry setup idempotency, span creation, hook lifecycle, shebang fix, and noop operation.
- **AgentCore Memory Integration:** `MemoryHook` is a Strands `HookProvider` that registers `BeforeInvocationEvent` and `AfterInvocationEvent` callbacks for automatic memory operations. Before invocation: retrieves memory records via `retrieve_memory_records` using the last user message as search query. After invocation: creates events in memory for each message in the conversation via `create_event`. Emits `LOOM_MEMORY_TELEMETRY: retrievals=N, events_sent=M` structured log line for cost tracking (always emitted, even when counters are 0). All operations logged at INFO level for visibility. Graceful degradation: AccessDeniedException and other errors are caught and logged without interrupting the agent invocation.

### Phase 6 — User Authentication *(Complete)*
- Cognito-based user authentication with `USER_PASSWORD_AUTH` flow.
- Login page with `NEW_PASSWORD_REQUIRED` challenge handling for admin-created users.
- `AuthContext` provider with login, logout, and automatic token refresh.
- User indicator (username) and logout button in the sidebar.
- JWT validation middleware on the backend (JWKS caching, token claim extraction).
- User access token forwarded to AgentCore for authenticated invocations (priority over M2M flow).
- Graceful fallback to existing M2M client credentials flow when no user token is present.
- `GET /api/auth/config` endpoint returns pool ID and region; user client ID is configured on the frontend via `VITE_COGNITO_USER_CLIENT_ID`.
- Tokens stored in memory only (not localStorage); authentication does not persist across page reloads.
- Cognito User Pool IaC: resource server with custom scopes (15 initial scopes, later expanded to 21: `invoke`, `catalog:read/write`, `agent:read/write`, `memory:read/write`, `security:read/write`, `settings:read/write`, `tagging:read/write`, `costs:read/write`, `mcp:read/write`, `a2a:read/write`, `registry:read/write`), user groups, users with group assignments, password policy (12+ chars, no symbols required).
- Security makefile with `cognito.set-passwords` target for setting permanent user passwords.
- Scope-based frontend authorization: `AuthContext` extracts `cognito:groups` from the ID token, maps groups to scopes, and exposes `hasScope()`. Sidebar items are conditionally rendered based on user scopes. Write operations (add, edit, delete buttons) are disabled or hidden via a `readOnly` prop when the user lacks `*:write` scopes. When auth is not configured, all scopes are granted.

### Phase 7 — Resource Tagging *(Complete)*
- Configurable tag policy system: `TagPolicy` model with key, default_value, required, and show_on_card fields. Two-tier designation: `platform:required` (keys starting with `loom:`) and `custom:optional` (all others). Designation is computed from the key, not stored.
- Tag policy CRUD API under `/api/settings/tags` with default seed data (loom:application, loom:group, loom:owner).
- Tag profile system: `TagProfile` model for named sets of tag values. CRUD API under `/api/settings/tag-profiles`. Profiles satisfy required tag policies and are applied to all deployed resources.
- `ResourceTagFields` shared component: fetches tag policies and profiles, renders a profile dropdown with `sessionStorage` persistence (`loom:selectedTagProfileId`), resolves tags from the selected profile + policy defaults, and passes resolved tags to the parent form via `onChange`. Used by both the agent deploy form and memory create form.
- Unified tag resolution: for each policy, use user-supplied value → fall back to `default_value` → error if required and missing. Required tag validation before deployment — missing tags return HTTP 400.
- All AWS resources that support tags (AgentCore runtimes, runtime endpoints, IAM execution roles, managed roles, memory resources) receive the resolved tags.
- Memory resources: `tags` column added to the `memories` table. Tags are resolved from tag policies + selected profile on creation, passed to AWS `create_memory`, and stored locally. Imported memories fetch existing tags from AWS via `list_tags_for_resource` and enforce tag policies (missing required tags default to "missing").
- Registered agents fetch existing tags from AWS via `list_tags_for_resource` and enforce tag policies (missing required tags default to "missing").
- Resolved tags stored on Agent and Memory records as JSON columns, included in API responses.
- Agent and memory cards display tag badges (`variant="secondary"`) for tags with `show_on_card=true`.
- All listing pages (Platform Catalog, Agents, Memory) provide tag-based filtering with multi-select dropdowns (checkbox-based), AND logic, clear button, and item count display.
- Settings persona: new sidebar entry accessible to all scopes. `SettingsPage` provides tag profile CRUD. `*:write` scopes can create, edit, and delete profiles; `*:read` scopes can only view. Tag value inputs enforce a 128-character maximum length.
- 29 backend tests covering tag policy CRUD, tag designation, tag resolution, validation, and agent tag storage.

### Phase 8 — Frontend Visual Polish *(Complete)*
- Theme system: `ThemeContext` with 10 themes — 5 light (Ayu Light, Catppuccin Latte, Everforest Light, Rosé Pine Dawn, Solarized Light) and 5 dark (Ayu Dark, Catppuccin Mocha, Dracula, Nord, Tokyo Night). Theme selector on Settings page with Light/Dark grouping. CSS variables per theme in `index.css`. Latte is the default (no class); other themes use class selectors. `localStorage` persistence.
- Theme accessibility: darkened `foreground`/`muted-foreground`/`border` for all light themes for better readability. Brightened `foreground`/`muted-foreground`/`border` for all dark themes. Badge `border-border` added to default and secondary badge variants for visibility.
- Settings page: moved theme and timezone selectors from sidebar to Settings preferences section. Description updated to "Manage settings and tag profiles."
- Drag-to-reorder cards: `@dnd-kit` for card reordering in grid sections (`SortableCardGrid` component), order persisted to `localStorage`.
- Admin role view switching: sidebar dropdown (Eye icon) to test other role experiences while retaining admin access. `effectiveHasScope` overrides `hasScope` for UI rendering.
- Deploy flow: fire-and-forget pattern — form collapses immediately, shows agent card with creating status. Background API call with error toast on failure. No 45-second blocking.
- Agent card two-phase creation: shows deploying → completing deployment → finalizing endpoint status with spinner and timer. Timer format: spinner (Ns) message. Timer uses `registered_at` to avoid reset on phase transition. Two-row header layout.
- Memory card: matching two-row header layout with spinner/timer for creating/deleting states.
- Polling stability: `initialLoadDone` ref prevents skeleton flash on refetches. `watchIds`-based polling effect dependency to prevent interval teardown on state updates. Removed redundant polling from `AgentListPage`.
- JSON paste: handles `model`, `role`, `authorizer`, and `network_mode` fields in addition to `name`/`description`/`persona`/`instructions`/`behavior`.
- Credential suggestion on errors: `friendlyInvokeError` accepts optional `authorizerName`, suggests correct authorizer on 401/403 errors.
- Catalog page: removed unnecessary refresh button from Memory Resources section.
- Documentation: `frontend/.env.example` template, README title updated.

### Phase 9 — Tagging Page and Custom Tags *(Complete)*
- Dedicated Tagging page: tag profile management extracted from Settings into a new `TaggingPage` component with its own sidebar entry (Tags icon, visible to all scopes). Drag-to-reorder via `SortableCardGrid` for both tag policies and tag profiles.
- Custom tag policy management: `platform:required` tags shown as read-only cards with lock icon (top-right) and designation badge; `custom:optional` tags are editable (pencil icon) and deletable (Trash2 icon, top-right) with designation badge. "Add Custom Tag" form with key, default value, and show-on-card toggle. Custom tags are always `required=false`.
- Tag profile form with two sections: **Platform (Required)** with mandatory input fields for all `platform:required` tags, and **Custom (Optional)** with checkbox-to-enable pattern per custom tag (checking reveals a value input, unchecking removes from profile).
- Simplified tag model: removed `source` (build-time/deploy-time) distinction. Tag resolution: for each policy, use user-supplied value → fall back to `default_value` (only for required policies) → error if required and missing. Custom/optional tags only appear when the profile explicitly sets them.
- Progressive disclosure tag filtering: on Catalog, Agents, and Memory pages, required tag filters are always shown; custom tag filters are hidden until added via a custom `AddFilterDropdown` component. Filter bar layout: required filters → eyeball toggle → activated custom filters → "custom filters" Add dropdown → Clear filters → count. All label rows use fixed `h-4` height for visual alignment. Filter state (`tagFilters` and `activeCustomFilterKeys`) persisted to `localStorage` per page and survives navigation.
- Custom tag show/hide toggle: Eye/EyeOff button on filter bars (positioned left of custom filter dropdown) toggles visibility of custom tags on agent and memory cards. Preference persisted to `localStorage` (`loom:showCustomTags`).
- Card layout consistency: Trash2 icon for delete across all cards (agents, memory, roles, authorizers, tags). Edit/delete icons positioned top-right as lightweight `<button>` elements. Delete confirmation right-aligned at card bottom.
- Table consistency: all tables use `table-fixed` with matching percentage-based column widths (30%/12%/14%/14%/14%/16%). Action columns removed from all tables — delete/refresh operations are card-view only.
- Security card consistency: RoleManagementPanel and AuthorizerManagementPanel cards use the same top-right icon pattern (pencil + trash for authorizers, trash for roles). Tags aligned with content via `ml-6` offset.
- Backend: `tags` column added to `managed_roles` and `authorizer_configs` tables. IAM role import fetches tags via `list_role_tags`. `environment.sh.example` files added for backend and security directories.
- Pydantic error handling: `apiFetch` handles array-style `detail` responses (Pydantic validation errors) by joining `msg` fields.
- Settings page simplified to display preferences only (theme + timezone).

### Phase 10 — Fine-Grained Permissions Scoping *(Complete)*
- Two-dimensional group architecture: Type groups (`t-admin`, `t-user`) define UI view; Group membership (`g-admins-*`, `g-users-*`) grants scopes. Users belong to both a type group and one or more resource groups.
- Expanded scope model from 15 to 19 scopes: added `tagging:read/write` for tag policy/profile management, `costs:read/write` for cost dashboard access. Scopes at this phase: `invoke`, `catalog:read/write`, `agent:read/write`, `memory:read/write`, `security:read/write`, `settings:read/write`, `tagging:read/write`, `costs:read/write`, `mcp:read/write`, `a2a:read/write`. (Later expanded to 21 in Phase 22 with `registry:read/write`.)
- Updated Cognito group structure:
  - Type groups: `t-admin` (admin UI), `t-user` (user UI)
  - Admin groups: `g-admins-super` (all scopes), `g-admins-demo` (read/write to most pages including MCP/A2A + demo group resources), `g-admins-security`, `g-admins-memory`, `g-admins-mcp`, `g-admins-a2a`
  - User groups: `g-users-demo`, `g-users-test`, `g-users-strategics` (each grants catalog:read, agent:read, memory:read, costs:read, costs:write, invoke)
- Updated user assignments: `admin` → t-admin + g-admins-super, `demo-admin` → t-admin + g-admins-demo, `security-admin` → t-admin + g-admins-security, `integration-admin` → t-admin + g-admins-memory + g-admins-mcp + g-admins-a2a, `demo-user` → t-user + g-users-demo
- Backend OAuth2 enforcement: every router endpoint guarded by `require_scopes()` dependency with OpenAPI scope annotations via `Security()`. `get_current_user` validates JWT, extracts `cognito:groups`, and derives scopes via `GROUP_SCOPES` mapping. Returns 401 for missing/invalid tokens, 403 for insufficient scopes.
- Group-based invoke restriction: `g-admins-super` can invoke any agent; other admins and users can only invoke agents whose `loom:group` tag matches their group (strips `g-admins-` or `g-users-` prefix for comparison).
- Resource filtering: Admins (t-admin) see all resources including untagged. Users (t-user) see only resources matching their group tags (union semantics for multiple groups).
- Demo-admin write restrictions: `g-admins-demo` users can only create/delete agents, memory resources, MCP servers, and A2A agents tagged with `loom:group=demo`. Delete buttons hidden on cards for resources outside their group.
- Tag policy management: `list_tag_policies()` and `list_tag_profiles()` require authentication but no specific scope (needed for card display). Only `g-admins-super` can edit/delete custom tag policies. Demo-admins can edit/delete tag profiles only with `loom:group=demo`.
- Token forwarding for agent invocation: user's login token is forwarded to OAuth-protected agents (shared Cognito pool). Token priority: manual bearer token > M2M credential > user login token > agent config M2M > SigV4 (no token).
- Auto-include user app client ID (`LOOM_COGNITO_USER_CLIENT_ID`) in agent authorizer `allowedClients` on deploy, so user login tokens are accepted by the agent runtime.
- Credential dropdown shows context-aware options: OAuth agents show user's token (default), M2M credentials, and manual token; non-OAuth agents show "No credentials (SigV4)" only.
- Auto-select newly created session in the session dropdown after an invocation.
- Automatic 401 token refresh: `apiFetch` intercepts 401 responses, refreshes the Cognito access token, and retries the request transparently.
- Re-fetch agent list after authentication to prevent empty state on hard refresh.
- Frontend `AuthContext` and `App.tsx` updated with matching `GROUP_SCOPES` mapping. View As selector changed from group-based to user-based (admin, demo-admin, security-admin, etc.) for more realistic role simulation.
- Default page on login: users are routed to their first accessible page based on available scopes (e.g., security-admin → Security page, demo-user → Catalog page).
- Group restriction on `ResourceTagFields`: demo-admins only see tag profiles matching their group, and `loom:group` tag is forced to their group value. Tag profile selector: "None" option removed, users must select a profile.
- Sidebar overflow fix: sidebar and main content use proper scroll containment.
- Bypass mode preserved: when `LOOM_COGNITO_USER_POOL_ID` is not set, all scopes are granted (local development).
- Comprehensive test updates for new group structure in `test_scopes.py` and `test_costs.py`.

### Phase 11 — JSON Import/Export and Agent Deletion Polling *(Complete)*
- Shared `JsonConfigSection` component for collapsible JSON import/export on forms. Encapsulates toggle, textarea, and Apply/Export/Cancel buttons.
- Agent deploy form (`AgentRegistrationForm`): refactored to use `JsonConfigSection`. Export serializes form state to JSON with human-readable names (model ID, role name, authorizer name, tag profile name). Import maps `name`, `description`, `persona`, `instructions`, `behavior`, `model`, `role`, `network_mode`, `authorizer`, `tags`.
- Memory create form (`MemoryManagementPanel`): added `JsonConfigSection` with import/export. Import maps `name`, `description`, `event_expiry_duration` (validated 3-364), `tags` (tag profile name lookup), `strategies` (array with strategy_type validation against semantic/summary/user_preference/episodic/custom). Export serializes current form state; empty/default fields omitted. Memory namespace changed from array with TagInput to singular string textbox for simpler UX and import compatibility.
- Round-trip capable: exported JSON is valid input for import, reproducing the same form state.
- Consistent visual behavior across both forms: same collapse/expand toggle, textarea styling, and button layout.
- Agent async deletion polling: agent DELETE endpoint returns `AgentResponse` with DELETING status (instead of 204) when `cleanup_aws=true` and agent has a runtime. Frontend `useAgents` hook polls DELETING agents at 5-second intervals; on 404, calls the new purge endpoint (`DELETE /api/agents/{id}/purge`) to clean up locally. Agent cards show spinner and elapsed timer during deletion, matching the memory deletion pattern. New `deleteStartTimes` state tracks deletion initiation timestamps for accurate timer display.

### Phase 12 — Card Sorting and Sort Controls *(Complete)*
- Default alphabetical sorting (case-insensitive, A-Z) for all card grids on initial load when no persisted custom order exists.
- Standalone `SortButton` component (A-Z / Z-A toggle) placed inline with section headers, next to "Add" buttons. Sort preference persisted to localStorage per grid (`loom-sort-${storageKey}`).
- After drag-to-reorder, custom order takes precedence and sort direction is cleared.
- New items not in persisted order are sorted alphabetically among themselves and appended after persisted items.
- `SortableCardGrid` uses controlled `sortDirection` prop with `onSortDirectionChange` callback. Exported helpers: `loadSortDirection()`, `saveSortDirection()`, `toggleSortDirection()`, `SortButton`, `SortDirection`.
- `SortableTableHead` component for clickable sortable table column headers with arrow indicators (ArrowUp/ArrowDown). `sortRows()` helper for generic multi-column sorting (string and numeric).
- Table view column sorting: pages with table views (CatalogPage, AgentListPage, MemoryManagementPanel) support click-to-sort on any column header.
- Security admin panels (RoleManagementPanel, AuthorizerManagementPanel, PermissionRequestsPanel) converted from stacked `<div className="space-y-2">` layouts to `SortableCardGrid` with drag-to-reorder and alphabetical sort controls. AuthorizerManagementPanel and PermissionRequestsPanel use responsive grid (`md:grid-cols-2 lg:grid-cols-3`); RoleManagementPanel uses full-width single-column layout since role cards contain long ARNs and expandable policy documents.
- All existing card grid consumers updated: CatalogPage (agents, memories), AgentListPage (agents), MemoryManagementPanel (memories), TaggingPage (policies, profiles).

### Phase 13 — MCP Server Integration *(Complete)*
- Backend: `McpServer`, `McpTool`, `McpServerAccess` ORM models with full CRUD API under `/api/mcp/servers`. MCP server registration with name, endpoint URL, and transport type (SSE or Streamable HTTP). OAuth2 authentication configuration with well-known URL, client ID, client secret (write-only), and scopes. Conditional validation: OAuth2 fields required when auth_type is `oauth2`. Client secrets never returned in GET responses (`has_oauth2_secret` flag instead).
- Tool discovery: `GET /api/mcp/servers/{id}/tools` returns cached tools, `POST /api/mcp/servers/{id}/tools/refresh` fetches from server (stub implementation). Each tool stores name, description, and input schema (JSON).
- Access control: `GET/PUT /api/mcp/servers/{id}/access` manages per-persona access rules. Access levels: `all_tools` (any tool including future ones) or `selected_tools` (specific tool names). Disabled by default — no rules means all agents have access. When rules exist, only listed agents have access. Auto-grant: when deploying an agent with MCP/A2A associations, if access rules already exist, the new agent is automatically added with `all_tools`/`all_skills` access.
- Connection test: `POST /api/mcp/servers/{id}/test-connection` validates OAuth2 configuration (stub for actual MCP connectivity).
- Frontend: `McpServersPage` with card/table view toggle, sortable columns, server detail view with Tools/Access tabs. `McpServerForm` with progressive OAuth2 field disclosure. `McpToolList` with refresh, collapsible input schema display. `McpAccessControl` with per-agent toggle, all_tools/selected_tools radio, individual tool checkboxes.
- MCP Servers sidebar item activated (no longer disabled/coming soon). Scope-gated by `mcp:read`/`mcp:write`.
- Agent deployment with MCP server selection: multi-select dropdown on deploy form allows selecting MCP servers from catalog. Selected servers attached to agent during deployment.
- OAuth2 credential provider creation: for OAuth2-enabled MCP servers, backend calls AgentCore `create_oauth2_credential_provider` API using `CustomOauth2` vendor with `discoveryUrl` from server configuration. Credential providers auto-named `{agent_name}-mcp-{server_name}`. Credential provider creation uses exponential backoff retry (4 retries, delays 2s/4s/8s/16s). Deployment fails with credential_creation_failed status if all retries are exhausted.
- Background deployment with progressive status updates: deploy endpoint returns immediately with `creating_credentials` status. Background task progresses through `creating_role`, `building_artifact`, `deploying` phases with DB updates. Frontend polls at 2-second intervals.
- Frontend progressive deployment status display: agent cards show human-readable status messages (Creating credential provider, Creating IAM role, Building artifact, Deploying runtime, Completing deployment, Finalizing endpoint) with spinner and elapsed timer.
- Smart polling optimization: frontend skips AWS API calls during `creating_credentials`, `creating_role`, and `building_artifact` phases (local operations only), reducing unnecessary backend load.
- Credential provider cascade delete: when agents are deleted, associated OAuth2 credential providers are automatically cleaned up via AgentCore API.
- Agent runtime deferred MCP client initialization: OAuth2 MCP clients are initialized at invocation time (not handler startup) since workload tokens are only available during active requests.
- Agent runtime `_OAuth2Auth` httpx handler: exchanges ephemeral workload token for downstream OAuth2 access token via AgentCore Identity service M2M flow. Workload token retrieved from `AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE` environment variable.
- Agent deletion with background polling: delete endpoint returns `DELETING` status. Background task polls AgentCore until runtime deletion completes, then purges local DB record. Endpoint status badge hidden during deletion.
- 25 backend tests covering all CRUD operations, validation, secret exclusion, OAuth2 conditional fields, tools, access rules, and cascade delete.

### Phase 14 — A2A Agent Integration *(Complete)*
- Backend: `A2aAgent`, `A2aAgentSkill`, `A2aAgentAccess` ORM models with full CRUD API under `/api/a2a/agents`. A2A agent registration by base URL with automatic Agent Card fetching from `<base_url>/.well-known/agent.json`. Agent Card data cached locally: name, description, version, provider, capabilities, authentication schemes, input/output modes, and raw JSON. Skills parsed and stored in a separate table for queryability.
- OAuth2 authentication configuration: well-known URL, client ID, client secret (write-only), and scopes. Conditional validation: OAuth2 fields required when auth_type is `oauth2`. Client secrets never returned in GET responses (`has_oauth2_secret` flag instead).
- Agent Card endpoints: `GET /api/a2a/agents/{id}/card` returns cached raw Agent Card JSON. `POST /api/a2a/agents/{id}/card/refresh` re-fetches from remote agent, updates all cached fields and syncs skills. Failed refresh preserves existing cached data.
- Skills endpoint: `GET /api/a2a/agents/{id}/skills` returns skills parsed from the Agent Card. Skills synced on registration and on card refresh (add new, remove stale).
- Access control: `GET/PUT /api/a2a/agents/{id}/access` manages per-persona access rules. Access levels: `all_skills` (any skill including future ones) or `selected_skills` (specific skill IDs). Deny by default.
- Connection test: `POST /api/a2a/agents/{id}/test-connection` acquires OAuth2 token if configured and fetches the Agent Card.
- Agent deployment with A2A integration: multi-select dropdown on deploy form allows selecting A2A agents from catalog. Selected agents attached to agent during deployment. OAuth2-enabled A2A agents get credential providers created with exponential backoff retry. Credential provider names follow pattern `loom-{agent_name}-a2a-{a2a_name}`. Deployment fails with `credential_creation_failed` status if credential provider creation exhausts retries.
- Agent deployment with memory integration: multi-select dropdown on deploy form allows selecting memory resources from catalog. Selected memory IDs and names passed in `AGENT_CONFIG_JSON` under `integrations.memory.resources`.
- A2A runtime client (`agents/strands_agent/src/integrations/a2a_client.py`): `_AuthenticatedA2AAgent` subclass of the Strands SDK `A2AAgent` for OAuth2-protected A2A endpoints. Injects OAuth2 Bearer tokens via AgentCore Identity service into both agent card fetches and message sending. Handles both SSE (`text/event-stream`) and plain JSON responses. Falls back from `message/stream` to `message/send` on "Method not found". Buffers `Message` events and yields them after `Task` events so `stream_async` picks the content-bearing `Message` as `last_complete_event`. Each enabled A2A agent in the configuration is wrapped as a `@tool` function that the orchestrating agent can invoke during conversation.
- Agent deletion cascade: credential providers for both MCP and A2A integrations are cleaned up. Explicit session/invocation deletion in all delete paths (immediate, background, purge) as safety net alongside ORM cascades.
- Frontend: `A2aAgentsPage` with card/table view toggle, sortable columns, agent detail view with Agent Card/Access tabs. `A2aAgentForm` with base URL input and progressive OAuth2 field disclosure. `A2aAgentCardView` with structured display of capabilities (enabled/disabled badges), authentication schemes, input/output modes, and skills list. `A2aSkillList` with expandable skill cards showing tags, examples, and mode overrides. `A2aAccessControl` with per-persona toggle, all_skills/selected_skills radio, individual skill checkboxes with descriptions.
- A2A Agents sidebar item activated (no longer disabled/coming soon). Scope-gated by `a2a:read`/`a2a:write`.
- Frontend state management: clearing stale session/invocation state on agent selection and deletion. `useSessions` hook clears sessions immediately when agent changes before fetching new data.
- Frontend status display: `credential_creation_failed` deployment status mapped to destructive badge variant.
- JSON import/export: agent deploy form supports `a2a_agents` and `memories` arrays (names) in JSON configuration alongside `mcp_servers`.
- 26 backend tests covering CRUD operations, Agent Card fetching, skill sync, card refresh, secret exclusion, OAuth2 validation, access rules, and cascade delete.

### Phase 15 — Token Usage Tracking and Cost Dashboard *(Complete)*
- Backend schema: `input_tokens`, `output_tokens`, `estimated_cost`, `compute_cost`, `compute_cpu_cost`, `compute_memory_cost`, `idle_timeout_cost`, `idle_cpu_cost`, `idle_memory_cost`, `memory_retrievals`, `memory_events_sent`, `memory_estimated_cost`, `stm_cost`, `ltm_cost`, `cost_source` columns on the `invocations` table via SQLAlchemy migration (`_migrate_add_columns`).
- Token estimation: 4 characters per token heuristic used since AgentCore doesn't expose token counts directly. Applied to both prompt and response text.
- Cost calculation: `(input_tokens / 1000 * input_price_per_1k_tokens) + (output_tokens / 1000 * output_price_per_1k_tokens)` using per-model pricing data.
- Model pricing metadata: `SUPPORTED_MODELS` extended with `input_price_per_1k_tokens`, `output_price_per_1k_tokens`, and `pricing_as_of` fields for all models (Anthropic and Amazon).
- AgentCore Runtime pricing constant: `AGENTCORE_RUNTIME_PRICING` tracks CPU ($0.0895/vCPU-hour), Memory ($0.00945/GB-hour), default vCPU (1), default memory (0.5 GB), and default idle timeout (900 seconds).
- View-time cost recomputation: Runtime CPU and memory costs are recomputed from `client_duration_ms` at view time using current pricing defaults (1 vCPU, 0.5 GB), so changing defaults retroactively affects all historical data. `_apply_view_time_costs()` applies the I/O wait discount to CPU costs. `_backfill_idle_costs()` always recomputes idle costs from session gaps to correct stale values.
- CPU I/O Wait Discount: Single configurable site setting (`cpu_io_wait_discount`, default 75%) applied universally to runtime CPU costs across both estimates and actuals. Configurable on the Settings page. Stored as integer percentage (0-99).
- Cost estimation formulas: `Runtime CPU = hours × 1 vCPU × $0.0895 × (1 − I/O wait%)`, `Runtime Mem = hours × 0.5 GB × $0.00945`, `Idle Mem = idle_seconds × 0.5 GB × $0.00945 / 3600`.
- New endpoints: `GET /api/agents/models/pricing` returns models with pricing metadata; `GET /api/dashboard/costs` provides estimated cost aggregation with group filtering, time-range filtering (7d/30d/90d/all), and per-agent breakdown; `POST /api/dashboard/costs/actuals` pulls actual runtime and memory costs from CloudWatch logs.
- CloudWatch log retrieval strategies: (1) stream-name matching for session-specific streams (fetches all events), (2) filterPattern fallback for shared streams. Both use nextToken pagination for complete data retrieval.
- Vended log sources: log viewer dropdown includes runtime APPLICATION_LOGS, runtime USAGE_LOGS, and memory APPLICATION_LOGS as selectable vended log sources with display labels and last event timestamps. Stream timestamps respect the user's timezone preference.
- Cost dashboard sections: **Estimated Costs** table with per-agent breakdown (Model Tokens, AgentCore Runtime CPU+Mem, AgentCore Memory STM+LTM, Per Invoke, Total) with inline sub-details. **Actual Costs** split into Runtime and Memory sub-sections. Runtime: collapsible agent groups with per-session detail rows, subtotals per agent, sortable at agent level. Memory: consolidated per-resource table with columns Log Events, Extractions, Consolidations, LTM Retrievals, Records Stored, Total. Actuals are cached in module-level state to persist across page navigation.
- Runtime actuals session filtering: Only sessions tracked in Loom's `invocation_sessions` table are shown, filtering out external invocations against the same runtime.
- Runtime actuals aggregation: CloudWatch usage log events (1-second granularity) are aggregated by `(agent_name, session_id)` tuple from `attributes.agent.name` and `attributes.session.id`. Timestamps normalized from epoch milliseconds or ISO strings to UTC ISO 8601. Delivery of usage logs can be delayed up to 15 minutes.
- Memory actuals: Parsed from `BedrockAgentCoreMemory_ApplicationLogs` vended log group. Memory pipeline session IDs are internal to AgentCore and do NOT correlate with runtime session IDs — they represent asynchronous extraction/consolidation/storage pipeline runs. `parse_memory_log_events()` maps `body.log` messages to pricing operations.
- Cost summary in responses: `AgentResponse` includes `cost_summary` field with `total_input_tokens`, `total_output_tokens`, `total_model_cost`, `total_runtime_cost`, `total_memory_cost`, `total_cost`, and `total_invocations`.
- SSE streaming: `session_end` event includes token counts and estimated cost for immediate display after invocation completes.
- Settings page: CPU I/O Wait Discount input with description and save-on-blur behavior.
- Database integrity: `PRAGMA foreign_keys=ON` added to all test engines for proper SQLite FK enforcement. Explicit cascade delete for invocations before sessions to prevent FK constraint violations.
- Frontend invocation metrics: InvocationTable expanded to 7 columns — Client Invoke, Agent Start, Cold Start, Duration, Input Tokens, Output Tokens, Est. Cost — all displayed in a single row.
- Frontend agent cards: cost badge displayed when `total_estimated_cost > 0`. READY status badge hidden to reduce clutter. Memory cards hide ACTIVE status badge.
- Frontend cost dashboard: new `CostDashboardPage` with time-range selector (7d/30d/90d/All), summary cards (Total Cost, Model Tokens, Runtime, Memory), estimated costs table with sortable columns and methodology formulas, actual costs section with separate Runtime (collapsible agent groups) and Memory (consolidated per-resource) sub-sections, Pull Actuals button with loading timer. Platform catalog page includes estimates disclaimer.
- Costs sidebar item: new navigation entry (above Settings) visible to users with `catalog:read` scope.

### Phase 16 — Trace Visualization *(Complete)*
- Backend OTEL log parsing service (`services/otel.py`): fetches OTEL log records from the CloudWatch `otel-rt-logs` stream via `filter_log_events`. Parses JSON log bodies containing `traceId`, `spanId`, `observedTimeUnixNano`, `body` (string or dict with input/output), `attributes` (with `session.id`), and `scope.name`. Bodies with both `input` and `output` keys are split into two separate events for accurate event counting. Groups events by trace ID for list view and by span ID for detail view.
- Backend traces router (`routers/traces.py`): `GET /api/agents/{id}/sessions/{sid}/traces` fetches all OTEL events from the log stream (single fetch, no filter), then filters by `session.id` in Python. Returns trace summaries with trace ID, start/end time, duration, span count, and event count. `GET /api/agents/{id}/traces/{tid}` fetches events filtered by trace ID and returns full trace detail with per-span event lists, scopes, and timing.
- Frontend Logs/Traces tabbed layout on `SessionDetailPage` using shadcn Tabs. Logs tab preserves existing log viewer unchanged. Traces tab shows trace list (Trace ID, Start Time, End Time, Duration, Spans, Events) with lazy loading on first tab activation. Description text prompts users to click a trace ID for detail.
- Interactive `TraceGraph` component: CSS-based waterfall timeline with colored horizontal bars showing span durations relative to trace start. 8-color palette for span differentiation. Hover over spans reveals a persistent detail panel (Span ID, Scope, Duration, Events, Start/End times). Click-to-select spans with event detail expansion. Left panel shows span list with divide styling; right panel shows events with expand/collapse all toggle. Event detail lines show timestamp, span ID link, and scope/source.
- `InvocationDetailPage` extended with Traces tab showing traces scoped to that session.
- 12 backend tests covering trace router endpoints (7) and OTEL log parsing (5), including string body handling and input/output splitting.

### Phase 17 — Admin Dashboard and UX Enhancements *(Complete)*
- **Admin Dashboard global user filter:** Multi-select dropdown in the dashboard header allowing super-admins to selectively include/exclude specific users from all reporting. When a filter is active, summary cards (Total Logins, Total Page Views, Total Actions, Total Duration, Most Active Page), charts (Logins Over Time, Actions Over Time, Page Views), and all tab tables (Sessions, Actions, Page Views) are recomputed client-side from the filtered data. When no users are selected, all data is shown as before.
- **Table column consistency:** Agent and memory tables updated to reduce Status column to 10% and add an Estimated Cost column at 12%. MCP Server and A2A Agent tables aligned to a consistent 5-column structure: Name (18%), Endpoint/URL (46%), Transport/Version (10%), Auth (10%), Created (16%). A2A tables removed the Provider and Status columns to match the MCP structure. All column widths sum to 100% across Catalog, standalone MCP Servers, and A2A Agents pages.
- **Tag visibility at CREATING status:** Agent tags are now applied to the DB record immediately after initial record creation (before the background deployment task begins). This ensures tag-based resource filtering (e.g., demo users filtered by `loom:group`) can see agents from the moment they appear in CREATING status.
- **Logout sessionStorage cleanup:** On logout, all `loom:invokePrompt:*` keys are cleared from `sessionStorage` so per-agent prompt drafts do not persist across sessions.
- **Deploy flow:** Reverted to fire-and-forget pattern where the form collapses immediately and the real agent card appears once the DB record is created. Removed the ephemeral pending-card approach in favor of the direct DB-record polling flow.

### Phase 18 — End-User Chat Interface *(Complete)*
- **End-user routing:** `App.tsx` detects the type group of the authenticated user (or admin in "View as" mode). Users in `t-user` (without `t-admin`) are routed to `ChatPage` instead of the admin layout. Admins can preview the end-user experience by selecting any `demo-user-*` or `test-user` in the "View as" dropdown.
- **ChatPage layout:** Two-column layout — narrow left sidebar and main chat area, with an optional right memory panel. The sidebar contains: logo, agent picker (shown when multiple agents exist), "New Conversation" button, conversation history list, "My Memory" button (when agent has memory), and user info/logout.
- **Agent filtering:** Agents are filtered by `loom:group` tag vs. the user's `g-users-*` group names. Agents with no group tag are visible to all users. A single accessible agent is auto-selected.
- **Chat interface:** Alternating user (right, primary) and assistant (left, muted) message bubbles. In-flight messages (user prompt + streaming assistant response) displayed during streaming. Animated cursor while streaming. Markdown rendering with `react-markdown` + `remark-gfm`: paragraphs, headings, lists, tables, blockquotes, inline code, fenced code blocks, bold, and links. JSON code blocks rendered as collapsible `CollapsibleJsonBlock` components. Error display inline in the chat area. Enter to send, Shift+Enter for newline. Max-width content centering on wide screens.
- **Streaming:** Reuses `useInvoke` hook with `qualifier: "DEFAULT"` and no credential selection. Streaming indicator (`isCurrentlyStreaming`) is scoped to the active session — it is `false` when viewing a different conversation while a stream is in progress, preventing the thinking/spinner from appearing in unrelated conversations.
- **Session tab created immediately:** The conversation sidebar entry is created as soon as the `session_start` SSE event fires (not after `session_end`). The new session is also auto-selected and highlighted in the sidebar at that point. This means the conversation tab appears the moment the agent acknowledges the invocation, rather than waiting for the full response.
- **Session management:** New conversations start without a session ID; the first invocation creates a new `InvocationSession`. Subsequent messages reuse the session ID from `sessionEnd`. Resuming a past session rebuilds message history from `invocation.prompt_text` / `invocation.response_text` pairs. On `sessionEnd`, messages are loaded authoritatively from `getSession()` rather than assembled from in-memory streaming state, preventing content loss on finalization. `setPendingPrompt(null)` is deferred until after `setMessages()` completes so the in-flight bubbles remain visible during the backend fetch.
- **Conversation removal:** Removing a conversation calls `hideSession()` then records a `remove_conversation` audit action via `trackAction`. If the removed session is currently active, the chat area is cleared.
- **User isolation:** Session list filtered to the authenticated user's sessions (`user_id` match). Admin details (session IDs, qualifiers, credentials, bearer tokens) are not exposed in the end-user interface.
- **Memory panel:** Accessible via "My Memory" button when the agent has memory resources. Displays Session Memory (current exchange count + custom strategy names/descriptions) and "What I Remember About You" (long-term strategies: semantic, summary, user_preference, episodic). No memory IDs, ARNs, namespaces, strategy types, or configuration objects shown.
- **View-as banner:** When an admin is previewing the end-user experience via "View as", a non-destructive banner indicates the preview mode with an "Exit preview" button.
- **`useInvoke` subscription stability:** `clearInvokeState()` resets the module-level store to `EMPTY` and notifies all subscribers, but deliberately does NOT remove the subscriber set for the agent. This keeps the React component subscribed across "New Conversation" resets so that subsequent invocations correctly propagate streaming state updates to the UI.

### Phase 19 — Cloud Infrastructure and Operations *(Complete)*
- **RDS PostgreSQL support:** SAM template (`iac/rds.yaml`) for RDS PostgreSQL with optional RDS Proxy, multi-AZ, IAM database authentication, and Secrets Manager integration (secrets encrypted with a dedicated KMS CMK managed in the same stack). Dialect-aware engine configuration in `db.py` (SQLite vs PostgreSQL). `_migrate_add_columns` helper handles both dialects. Migration script (`scripts/migrate_sqlite_to_postgres.py`) with topological sort for foreign-key dependency order. Sequence auto-repair script (`scripts/fix_sequences.py`) for PostgreSQL after migration. Database reset script (`scripts/reset_db.py`).
- **Shared infrastructure stack:** SAM template (`iac/infra.yaml`) for long-lived resources: S3 artifact bucket (versioning, AES256 encryption, public access block, access logging to a pre-existing logging bucket), ECR repositories (frontend + backend, KMS CMK-encrypted, with lifecycle policies), ACM certificate (DNS validation via Route 53), ALB (internet-facing, HTTPS-only with TLS 1.3, path-based routing), security groups (ALB + ECS), target groups (frontend port 80, backend port 8000), and Route 53 A-record alias for the ALB.
- **EC2 SSM tunnel:** SAM template (`iac/ec2.yaml`) for an EC2 bastion instance in a private subnet with no public IP, using SSM Session Manager (via VPC endpoints) for tunneling to RDS. Makefile `tunnel` target configures port forwarding via `aws ssm start-session`.
- **Multi-account environment configuration:** `backend/etc/environment.sh` sources account-specific files (e.g., `environment_9582.sh`, `environment_1527.sh`) containing AWS profile, account ID, VPC/subnet IDs, RDS parameters, and stack names. Enables managing multiple AWS accounts from the same codebase.
- **CountTokens API integration:** `services/tokens.py` uses the Bedrock `count_tokens` API for accurate token counting. Provider guard restricts API calls to supported providers (Anthropic, Meta); all other models fall back to the 4 chars/token heuristic.
- **Background usage poller:** `services/usage_poller.py` runs every 10 minutes, finds invocations with `cost_source="estimated"`, polls USAGE_LOGS from CloudWatch, matches events to invocations by timestamp (within 5 seconds), and updates costs from estimated to actual (`cost_source="usage_logs"`).
- **Observability service:** `services/observability.py` enables USAGE_LOGS and APPLICATION_LOGS delivery for agent runtimes via CloudWatch vended log delivery APIs (`put_delivery_source`, `put_delivery_destination`, `create_delivery`).
- **AgentCore credential management:** Makefile targets for listing and bulk-deleting AgentCore OAuth2 credential providers.
- **Infrastructure makefile targets:** Shared makefile (`shared/makefile`): `infra`, `ecs`, `docker.*`, `deploy` targets for cross-cutting infrastructure and container deployment. Backend makefile: `rds`, `ec2`, `tunnel` targets for database infrastructure. `migrate-db`, `fix-sequences`, `reset-db` targets for database operations.
- **Pull Actuals session ID fix:** Removed `tracked_session_ids` filter from `pull_cost_actuals` in `costs.py`. USAGE_LOGS use internal AgentCore session IDs that do not match Loom's `runtimeSessionId`, so session-based filtering dropped all events. Events are now scoped by time window and runtime ID only.
- **Tagging UX improvements:** Collapsible tag profile groups in `TaggingPage` (platform required vs custom optional sections). Form-fill import from tag policies (auto-populates profile form with policy defaults). Tag policy and profile sorting. Sidebar entry renamed from "Tagging" to "Tags".
- **Admin dashboard fixes:** Fixed `page_views_by_page` type mismatch that caused dashboard crash. Custom tooltips on all recharts charts for consistent styling. Theme picker moved from Settings page to admin sidebar for easier access.

### Phase 20 — Container Deployment to AWS *(Complete)*
- **Containerization:** `backend/Dockerfile` (Python 3.13-slim, non-root user, uvicorn on port 8000) and `frontend/Dockerfile` (multi-stage: Node 20 build + nginx Alpine serving on port 80). `frontend/nginx.conf` with SPA fallback routing, gzip compression, and immutable asset caching. `.dockerignore` files exclude `.env`, `node_modules`, `dist`, and development artifacts.
- **Dynamic API base URL:** `frontend/src/api/client.ts` reads `VITE_API_BASE_URL` from Vite build-time env using nullish coalescing (`??`) so empty string (same-origin) works in production while falling back to `http://localhost:8000` for local dev. Injected via `ARG`/`ENV` in the frontend Dockerfile.
- **Cognito client ID injection:** `VITE_COGNITO_USER_CLIENT_ID` is passed as a Docker build arg during `podman.build.frontend` (sourced from `O_COGNITO_USER_CLIENT_ID` in the outputs file). Required because `.dockerignore` excludes `.env`.
- **FastAPI docs under /api:** `docs_url="/api/docs"`, `redoc_url="/api/redoc"`, `openapi_url="/api/openapi.json"` so API documentation is accessible through the ALB's `/api/*` path-based routing rule.
- **Multi-stack deployment architecture:** 10 CloudFormation stacks across 3 directories:
  - `shared/iac/dns.yaml` — Route 53 hosted zone for subdomain delegation
  - `shared/iac/infra.yaml` — S3, ECR, ACM, ALB, security groups, target groups, Route 53 A-record
  - `shared/iac/cognito.yaml` — Cognito User Pool, groups, scopes, users
  - `shared/iac/role.yaml` — IAM execution roles for agents
  - `shared/iac/ecs.yaml` — ECS Fargate cluster (shared by frontend and backend)
  - `frontend/iac/ecs.yaml` — Frontend ECS service (task def, service, public subnets, port 80)
  - `backend/iac/ecs.yaml` — Backend ECS service (task def, task role, service, auto-scaling, private subnets, port 8000)
  - `backend/iac/rds.yaml` — RDS PostgreSQL with optional RDS Proxy
  - `backend/iac/ec2.yaml` — EC2 bastion for SSM tunneling
- **Centralized stack outputs:** `shared/scripts/capture_outputs.py` queries all stacks and writes `O_*` variables to `shared/etc/outputs_<profile>.sh`. This single file is included by all environment files across shared, frontend, and backend directories. Also writes `VITE_COGNITO_USER_CLIENT_ID` to `frontend/.env`.
- **Git SHA image tagging:** `IMAGE_TAG := $(shell git rev-parse --short HEAD)` used in all podman build, tag, and push commands. ECR URIs stored without tags in outputs (`O_ECR_FRONTEND_URI`, `O_ECR_BACKEND_URI`); tags appended dynamically at deploy time as `$(O_ECR_*_URI):$(IMAGE_TAG)`.
- **Cross-platform container builds:** `--platform linux/amd64` on all podman build commands to ensure ECS Fargate compatibility when building on ARM64 Macs (M-series).
- **Split ECS services:** Cluster is shared (`shared/iac/ecs.yaml`); frontend and backend have independent ECS service stacks in their respective `iac/` directories. Each has its own environment config in `etc/`, including `ecs.*` makefile targets.
- **4-phase deployment:** Phase 0 (DNS + delegation + ECS and AgentCore service-linked roles) → Phase 1 (foundation stacks in parallel) → Phase 2 (capture outputs) → Phase 3 (container build + push + ECS deploy).
- **Granular deployment targets:** `shared/makefile` supports `deploy` (full), `deploy.frontend`, and `deploy.backend` for independent container build+push+deploy. Podman targets: `podman.build.*`, `podman.push.*`, `podman.login`.
- **ALB with HTTPS:** HTTPS-only listener (port 443) with ACM certificate (DNS-validated via Route 53), TLS 1.3 policy. Port 80 is not exposed. Path-based routing: `/api/*` and `/health` to backend target group, default to frontend. Route 53 A-record alias for the ALB domain. Health check interval: 60 seconds.
- **ECR repositories:** CloudFormation-managed ECR repos (frontend + backend) encrypted with a dedicated KMS CMK (`EcrKmsKey` in `infra.yaml`, with auto-rotation enabled), scan-on-push, and lifecycle policies (keep last 10 images).
- **ECS Fargate configuration:** Fargate and Fargate Spot capacity providers on the cluster. Configurable task sizes via environment variables. Backend service includes auto-scaling (CPU target tracking at 70%).
- **Security groups:** ALB allows inbound HTTPS (443) from anywhere (suppressed intentionally — internet-facing ALB); ECS tasks allow inbound only from ALB security group on ports 80 (frontend) and 8000 (backend).
- **IAM roles:** Frontend: execution role (ECR pull + KMS decrypt for ECR CMK, CloudWatch Logs). Backend: execution role (ECR pull + KMS decrypt for ECR CMK, CloudWatch Logs, Secrets Manager + KMS decrypt for secrets CMK) + task role (Bedrock, Bedrock AgentCore, S3, CloudWatch Logs, IAM PassRole, Secrets Manager + KMS, Cognito, CloudFormation).
- **RDS IAM authentication:** `EnableIAMDatabaseAuthentication: true` on the RDS instance. Password-based authentication (via Secrets Manager) remains fully functional alongside IAM auth.
- **Dynamic CORS:** `LOOM_ALLOWED_ORIGINS` env var (comma-separated) adds origins to the default localhost entries. Backend reads this for CORSMiddleware configuration.
- **Database URL injection:** `LOOM_DATABASE_URL` injected via ECS Secrets (ValueFrom) referencing the RDS stack's Secrets Manager ARN with JSON key extraction.
- **Cross-account DNS delegation:** DNS stack creates a Route 53 hosted zone; if the parent domain is in a different account, NS delegation records must be added in the parent account before deploying the infra stack.

### Phase 22 — AWS Agent Registry Integration *(Complete)*
- **Scope expansion from 19 to 21:** Added `registry:read` and `registry:write` scopes for Agent Registry governance. Registry endpoints use `mcp:read` for GET and `mcp:write` for POST/PUT/DELETE as the underlying scope enforcement.
- **New Cognito group:** `g-admins-registry` with scopes `mcp:read`, `a2a:read`, `registry:read`, `registry:write`, `settings:read`, `settings:write`, `tagging:read`. Enables dedicated registry governance administrators.
- **Registry sidebar visibility gating:** The Registry sidebar entry is visible only when the user has `registry:read` or `registry:write` scope, ensuring non-registry users do not see the governance UI.
- **`registryEnabled` prop pattern:** All frontend pages that display registry UI elements (RegistryStatusBadge, RegistryActions) fetch `getRegistryConfig()` on mount and thread a `registryEnabled` boolean through their components. When registry is disabled, all registry badges and action buttons are hidden — RegistryStatusBadge returns null when `registryEnabled=false`, and RegistryActions rendering is gated by `registryEnabled &&` at all render sites.
- **Registry status badges across all pages:** RegistryStatusBadge added to CatalogPage (agents, MCP servers, A2A agents sections), AgentListPage, McpServersPage, and A2aAgentsPage in both card and table views. All instances pass `registryEnabled={registryEnabled}` to hide when disabled.
- **AgentCard `registryEnabled` prop:** AgentCard accepts `registryEnabled` (default true) and passes it to its embedded RegistryStatusBadge, allowing the catalog and agent list pages to control badge visibility.
- **Collapsible catalog sections:** CatalogPage sections (Agents, Memory Resources, MCP Servers, A2A Agents) are collapsible via ChevronRight/ChevronDown toggles. Collapse state persisted to `localStorage` under `loom:collapsedSections:catalog`.
- **Backend registry status sync:** When registry is re-enabled via the Settings page, `_sync_registry_statuses()` validates all stored `registry_record_id` values across Agent, McpServer, and A2aAgent models against the live registry. Records that no longer exist are cleared; status mismatches are updated. This prevents stale governance data after a disable/re-enable cycle.

### Phase 23 — Runtime Model Selection *(Complete)*
- **Model catalog externalization:** `SUPPORTED_MODELS` and `AGENTCORE_RUNTIME_PRICING` extracted from inline Python constants to JSON configuration files (`backend/etc/models.json`, `backend/etc/runtime_pricing.json`), loaded at startup. Model catalog expanded from 10 to 22 models across 7 vendor groups (Anthropic, Amazon, DeepSeek, Google, Meta, MiniMax, Moonshot AI).
- **Admin-enabled models:** `enabled_model_ids` site setting (default `[]` = all models). `GET /api/settings/models` returns the enabled list and full catalog. `PUT /api/settings/models` updates the enabled set (validates against `SUPPORTED_MODELS`). `GET /api/agents/models` filters by the enabled set. Settings page "Enabled Models" section with per-vendor grouped checkboxes and Save button.
- **Per-agent allowed models:** `allowed_model_ids` TEXT column on the `agents` table (JSON array). `Agent` ORM model with `get_allowed_model_ids()` / `set_allowed_model_ids()` helpers. Deploy and register flows store the allowed list (defaults to `[model_id]`). `AgentResponse` includes `allowed_model_ids` field.
- **Runtime model override on invoke:** `POST /api/agents/{id}/invoke` accepts optional `model_id` parameter. Validated against the agent's `allowed_model_ids` (HTTP 400 on mismatch). Passed through to `invoke_agent_stream()` which overrides `agent_model_id` for that invocation.
- **Agent PATCH endpoint extended:** `PATCH /api/agents/{id}` accepts `model_id` (updates `AGENT_CONFIG_JSON`) and `allowed_model_ids` (validates against `SUPPORTED_MODELS`). Description changes propagated to AgentCore via `update_runtime(description=...)`.
- **Group-based invoke fix:** Agents with no `loom:group` tag are now accessible to any authenticated user with invoke scope (previously blocked by empty-string comparison).
- **Streaming tool-call events:** Strands agent handler detects `contentBlockStart` events with `toolUse` data and yields `{"tool_use": {"name": ..., "id": ...}}` structured events. Backend `invoke_agent_stream` forwards these as `event: tool_use` SSE events. Frontend `StreamSegment` type models interleaved text and tool_use segments. `useInvoke` hook tracks `segments`, `currentToolName`, and `toolNames` arrays.
- **Inline tool-call indicators:** `ToolUseBlock` component renders tool calls with Wrench icon, counter (N/M), elapsed timer, and tool names. `formatToolName()` strips MCP server prefixes (`server___tool` → `tool`). Tool names persist in `ChatMessage.toolNames` and are displayed in finalized `MessageBubble` components after stream ends.
- **401 retry for SSE invoke:** `invokeAgentStream()` in `invocations.ts` intercepts 401 responses, calls `tryRefreshToken()` (exported from `client.ts`), and retries the SSE request with the refreshed token. Mirrors the existing `apiFetch` 401 retry pattern.
- **Frontend model selection UI:**
  - Deploy form: "Default Model" label, "Allowed Models (runtime selection)" checkbox section grouped by vendor via `groupModels()`.
  - `InvokePanel`: model dropdown (`Select`) filtered by `allowedModelIds`, disabled when single model, passes `model_id` override to `onInvoke`.
  - `DeploymentPanel`: "Allowed Models" section with inline edit mode (grouped checkboxes, default model toggle, Save/Cancel buttons).
  - `AgentDetailPage`: Overview card consolidates description + deployment + model config. `RegisteredAgentModelConfig` component for non-deployed agents.
  - `ChatPage`: model picker button in input area footer with click-outside-to-close dropdown, auto-reset on agent switch.
  - `groupModels()` utility in `frontend/src/lib/models.ts`: groups `ModelOption[]` by vendor, sorts groups alphabetically.
- **AgentCard display updates:** Endpoint qualifiers shown as comma-separated text (removed individual badges). Authorizer shown as a single outline badge with name/type fallback.
- **Agent detail response pane refactor:** Markdown rendering extracted to standalone `MarkdownBlock` component. Response pane renders `segments` array with `ToolUseBlock` and `MarkdownBlock` blocks. Thinking indicator shown when streaming with no segments. `StreamingBubble` component in ChatPage for segment-based rendering during active streams.
- 12 backend tests in `test_model_selection.py` covering Agent model helpers, registration with `allowed_model_ids`, response inclusion, PATCH validation, and invoke model validation.

### Phase 24 — Third-Party Connectors *(Complete)*
- **API key authentication for MCP servers:** New `api_key` auth type alongside `none` and `oauth2`. Admin API keys stored in Loom-managed AWS Secrets Manager (`loom/mcp/{name}/admin-api-key`), never in the database. Per-user API keys stored at `loom/mcp/{name}/api-key/{user_sub}`. Backend resolves keys from Secrets Manager with 5-minute in-memory cache. `_ApiKeyAuth` httpx handler in agent runtime resolves key once at session init (not per-request) to avoid throttling.
- **Dynamic MCP connectors in ChatPage:** "Connectors" button in the input area footer (left of model picker). Dropdown lists MCP servers available to the user with per-server toggle switches. Enabled connector state persisted to `localStorage` per agent (`loom:enabledConnectors:{agentId}`). API key connectors prompt for key entry on first enable; disconnect action deletes the stored key. Connector IDs passed through invoke request to agent runtime as `dynamic_mcp_servers`.
- **Agent runtime model override:** `AGENT_MODEL_ID` environment variable and `model_id` field in invoke payload. Agent handler caches `BedrockModel` instances per model ID and swaps `agent.model` per invocation. Default model restored when no override specified.
- **Agent runtime dynamic MCP attachment:** Handler accepts `dynamic_mcp_servers` in invoke payload. Maintains connection pool keyed by `(server_name, actor_id)`. Previously-connected servers are reused across invocations. Supports `api_key`, `oauth2`, and unauthenticated transports.
- **Salesforce Agentforce A2A integration:** Salesforce uses `/v1/card` instead of `/.well-known/agent.json` for Agent Card endpoint. `_AuthenticatedA2AAgent` detects Salesforce URLs and trusts the card's declared RPC URL (does not override with endpoint). Agent card `capabilities.streaming` check — skip `message/stream` and go directly to `message/send` for agents that don't advertise streaming support.
- **A2A agent card UX improvements:** Skill list restyled from Card-based layout to compact expandable rows matching MCP tool list style. Capabilities (streaming, push notifications, state history) and default I/O modes displayed inline with label prefixes. Empty default modes show "none" indicator.
- **Registry lifecycle improvements:** MCP server deletion cleans up associated registry records. Tool refresh propagates updated descriptors to the registry. Registry status badges shown across catalog and list views.
- **Catalog navigation improvements:** Clicking an item in the CatalogPage navigates to the corresponding admin page with the item pre-selected.
- **AgentCard overflow fix:** `overflow-hidden` on flex container prevents long agent names from overflowing card boundaries.
- **ChatPage model picker grouped by vendor:** Model dropdown uses `groupModels()` utility for alphabetical vendor grouping with section headers, matching the admin deploy form pattern.
- **SQLite absolute path default:** `DATABASE_URL` defaults to an absolute path based on the backend directory to avoid data loss when CWD differs between invocations.

### Phase 25 — AgentCore Harness Deployment *(Complete)*
- **New deployment type:** `source="harness"` alongside existing `register` and `deploy` types. Harness is a fully managed agent loop — no user-authored code, artifact build, or credential provider creation required. Agents are configured entirely through API parameters (model, system prompt, tools, iteration limits, timeouts).
- **Backend model:** `harness_id` column added to the `agents` table (VARCHAR, nullable). Stores the harness ID for managed agent deployments. Included in `Agent.to_dict()` serialization and `AgentResponse`.
- **Backend service module:** `backend/app/services/harness.py` with `create_harness()`, `get_harness()`, `delete_harness()`, and `invoke_harness_stream()` functions. Control plane operations use the `bedrock-agentcore-control` client; data plane invocation uses the `bedrock-agentcore` client. `invoke_harness_stream()` translates Converse API streaming events (`messageStart`, `contentBlockStart`, `contentBlockDelta`, `contentBlockStop`, `messageStop`, `metadata`) into the existing SSE format (`text`, `structured/tool_use`, `metadata`) so the frontend works without modification.
- **Harness tools:** Three tool types supported — `remote_mcp` (from MCP server catalog), `agentcore_code_interpreter` (built-in toggle), and `agentcore_browser` (built-in toggle). Custom tools can also be passed via `harness_tools` parameter.
- **Deploy-time vs invoke-time tool split:** OAuth2-authenticated MCP tools are excluded from `create_harness` (they fail to initialize without auth headers at deploy time). All MCP tools are stored in the config JSON under `harness_config.tools` for invocation-time injection; only non-OAuth2 tools go to `harness_config.deploy_tools` (what `create_harness` receives). At invocation time, OAuth2 tools are injected with fresh M2M tokens as `Authorization: Bearer` headers in the `remoteMcp` tool config.
- **OAuth2 credential provider creation:** For harness agents with OAuth2 MCP servers, the backend creates AgentCore credential providers during deployment (same pattern as custom agents). Credential providers are cleaned up on agent deletion.
- **M2M token injection:** At invocation time, the backend looks up each OAuth2 MCP server's `client_id`, `client_secret`, and `well_known_url` from the database, calls `_get_oauth2_token()` to obtain an M2M access token, and injects `Authorization: Bearer <token>` into the `remoteMcp` tool's `headers` map. This uses the MCP server's own OAuth2 credentials, not the Loom user's token.
- **JWT authorizer support:** Harness invocations support JWT authorization. When a user access token is available, the data plane client is configured with `UNSIGNED` SigV4 and an `Authorization: Bearer <token>` header injected via a boto3 `before-send` event hook.
- **Observability:** Harness agents automatically get USAGE_LOGS and APPLICATION_LOGS delivery enabled on their auto-provisioned runtime (same as custom agents). Observability is cleaned up on deletion.
- **ARN field handling:** The Harness API returns the ARN in the `"arn"` field (not `"harnessArn"`). All code paths (deploy, status poll, manual refresh) use `response.get("arn") or response.get("harnessArn", "")`.
- **Deployment flow:** `_deploy_harness()` validates name, model_id, and role_arn. Creates Agent record with `source="harness"`, `status="CREATING"`, `deployment_status="initializing"`. Background task `_deploy_harness_background()` creates OAuth2 credential providers for MCP servers, calls `create_harness` with non-OAuth2 tools only, sets harness_id, extracts auto-provisioned runtime, enables observability, and updates status to `deployed`. On failure, status is set to `FAILED`.
- **Status polling:** `get_agent_status()` detects `source="harness"` agents and polls via `get_harness_api()` instead of the runtime API. Extracts runtime from the harness environment and updates status.
- **Refresh:** `refresh_agent()` routes harness agents to `get_harness_api()` for status refresh.
- **Deletion:** `delete_agent()` routes harness agents to `delete_harness_api()` instead of `delete_runtime()`. Cleans up observability and credential providers.
- **Invocation:** `invoke_agent_endpoint()` dispatches to `invoke_harness_agent_stream()` when `agent.source == "harness"`. Reads `harness_config.tools` and MCP server auth types from stored config, resolves OAuth2 M2M tokens per server, and passes tools with auth headers as `dynamic_tools`. Token counts come from harness metadata events (falls back to CountTokens API if zero).
- **Frontend types:** `AgentHarnessDeployRequest` interface with harness-specific fields (max_iterations, timeout_seconds, max_tokens, temperature, top_p, code_interpreter, browser). `AgentResponse.source` union extended to include `"harness"`. `AgentResponse.harness_id` field added.
- **Frontend form:** `AgentRegistrationForm` adds a Deployment Type selector (Custom Agent vs Managed Agent radio buttons). Managed mode shows model parameters (max tokens, temperature, top_p), built-in tools (code interpreter, browser toggles), and iteration/timeout configuration. Harness Parameters section positioned between Authorizer and Lifecycle. Custom-only sections (protocol, authorizer, A2A agents, memory) are hidden in managed mode.
- **Frontend AgentCard:** Deployment type label (`MANAGED` / `CUSTOM`) and cost badge moved below the info box as outline badges, decluttering the card header row. Header row contains only: agent name, registry status, status badge, session count, refresh/trash buttons.
- **Frontend wiring:** `useAgents` hook includes `deployHarnessAgent` function with harness-specific polling support. `AgentListPage` and `App.tsx` wire `onDeployHarness` prop through to the registration form.
- **21 backend tests** in `test_harness.py` covering deployment CRUD, validation, MCP server integration, built-in tools, model parameters, status polling, refresh, deletion, config storage, and service module functions (create, get, delete, invoke stream with text and tool_use events).

### Phase 26 — External Integration Info *(Complete)*
- **Backend endpoint:** `GET /api/agents/{id}/integration` returns assembled integration details for READY agents: invocation URLs (per qualifier), protocol, network mode, authentication requirements, and example code snippets.
- **URL construction:** Invocation URLs follow the `bedrock-agentcore.{region}.amazonaws.com/runtimes/{runtime_id}/endpoints/{qualifier}/invoke` pattern. Protocol-specific URLs for MCP (`/mcp`) and A2A (`/.well-known/agent.json`) are included.
- **Auth info (SigV4):** For agents without an authorizer, displays required IAM action (`InvokeAgentRuntime` for custom, `InvokeHarness` for managed), resource ARN, example IAM policy, boto3 snippet, and AWS CLI snippet.
- **Auth info (OAuth2):** For agents with an authorizer, displays authorizer type, OIDC discovery URL, token endpoint (derived from Cognito pool ID or custom discovery URL), allowed client IDs and scopes, example token request and invocation curl snippets. Client secrets are never returned.
- **Frontend component:** `ExternalIntegrationSection` displays endpoint info with copy-to-clipboard buttons, protocol badges, network mode indicators, and syntax-highlighted code blocks. Only shown for agents with status READY.
- **10 backend tests** in `test_integration_info.py` covering SigV4 custom/harness agents, OAuth2 Cognito/custom OIDC, MCP/A2A protocol URLs, multiple qualifiers, VPC network mode, and error cases.

### Phase 27 — 3rd-Party Identity Provider Support *(Complete)*
- **Backend `IdentityProvider` model** (`backend/app/models/identity_provider.py`): stores OIDC configuration (issuer, client ID, discovery URL, authorization/token/JWKS endpoints), group claim mapping (external IdP groups to Loom groups via configurable JSON mapping), and cached discovery metadata with TTL-based refresh.
- **CRUD endpoints** at `/api/settings/identity-providers` for managing identity provider configurations, plus `POST .../discover` for OIDC discovery and `POST .../test-discovery` for validating provider connectivity.
- **OIDC discovery service** (`backend/app/services/oidc.py`): fetches `.well-known/openid-configuration` from any OIDC-compliant provider, extracts authorization, token, JWKS, and userinfo endpoints.
- **Generic JWT validation** (`backend/app/services/jwt_validator.py`): validates tokens against any JWKS endpoint (not just Cognito). Supports key rotation via cached JWKS with automatic refresh on key-not-found.
- **Group claim mapping**: maps external IdP group claims (e.g., Microsoft Entra ID `groups`, Okta `groups`) to Loom's internal group model (`g-admins-*`, `g-users-*`) via a configurable per-provider mapping table.
- **`GET /api/auth/config`** extended to return the active identity provider configuration when an external IdP is active, backward-compatible with the existing Cognito-only response format.
- **Generic token service** (`backend/app/services/token.py`): client credentials grant against any OIDC-compliant token endpoint (not just Cognito).
- **Token endpoint** in the security router supports both Cognito and generic OIDC authorizers for agent invocation.
- **Supported providers**: Microsoft Entra ID, Okta, Auth0, Generic OIDC. Cognito remains the default when no external IdP is configured.
- **Frontend OIDC Authorization Code + PKCE flow**: `AuthContext` extended with `startOIDCLogin()` and `exchangeOIDCCode()` in `frontend/src/api/auth.ts` for standard browser-based OIDC login without client secrets.
- **LoginPage**: shows provider-specific button (e.g., "Sign in with Microsoft Entra ID") when an external IdP is active, alongside the existing Cognito login form.
- **Identity Provider management UI** (`frontend/src/components/IdentityProviderPanel.tsx`): CRUD for provider configurations, OIDC discovery test button, and group mapping table editor.
- **Security Admin page**: new "Identity Providers" tab for managing external IdP configurations.
- **API client** at `frontend/src/api/identity_providers.ts` for all identity provider CRUD operations.
- **22 backend tests** in `backend/tests/test_identity_providers.py` covering CRUD, discovery, group mapping, token validation, and backward compatibility.
- **Per-user authorizer linking** (`backend/app/services/authorizer_linking.py`): OAuth popup flow for cross-IdP scenarios where the user's login IdP differs from the agent's authorizer. Refresh tokens stored in Secrets Manager at `loom/authorizers/{auth_id}/user-tokens/{user_sub}`. Access tokens resolved at invocation time (Priority 1.5) with in-memory caching. Four linking endpoints under `/api/security/authorizers/{auth_id}/link`. Frontend `OAuthLinkCallbackPage` handles popup callback with `window.opener.postMessage`.
- **Same-IdP detection**: When the user's login IdP matches the agent's authorizer (e.g., same Entra ID tenant), the frontend auto-detects this by comparing tenant IDs extracted from login issuer URL and agent authorizer discovery URL. Shows a green dot indicator and automatically selects the user's login token — no account linking required.
- **`allowed_audience` field**: Added to the `AuthorizerConfig` model, DB migration, CRUD endpoints, deploy requests, and frontend forms. Maps to AgentCore's `allowedAudience` parameter (validates the `aud` JWT claim, separate from `allowedClients` which validates `azp`).
- **Entra ID `allowedClients` fix**: Microsoft Entra ID v1.0 access tokens lack the standard `azp` claim (they use `appid` instead). AgentCore validates `allowedClients` against `azp`, causing `UnrecognizedClientException` (401). Deploy paths now omit `allowedClients` for `entra_id` authorizer type, relying on `allowedAudience` alone.
- **Entra ID v1.0/v2.0 issuer handling**: Backend auth dependency detects v2.0 issuer URLs and constructs the expected v1.0 issuer (`https://sts.windows.net/{tenant}/`) for token validation, since Entra ID v2.0 token endpoints issue access tokens with v1.0 format issuers.
- **Credential filtering per authorizer**: Frontend invoke panel filters M2M credentials to only show those from the agent's matching authorizer, preventing cross-authorizer credential selection.
- **Harness IAM prefix fix**: IAM role policy and CloudFormation role template updated to include `harness_` prefix for workload identity resources and CloudWatch Logs permissions, supporting harness-deployed agents.

### Phase 28 — On-Behalf-Of Token Exchange *(Complete)*
- **OBO delegation mode:** `delegation_mode` field added to `McpServer` and `A2aAgent` models (`m2m` or `obo`). When set to `obo`, AgentCore credential providers are configured for on-behalf-of token exchange (RFC 8693) instead of machine-to-machine client credentials. Configurable `obo_grant_type` field supports `TOKEN_EXCHANGE` (RFC 8693, for Okta and others) and `JWT_AUTHORIZATION_GRANT` (RFC 7523, for Microsoft Entra ID).
- **Credential provider OBO configuration:** `create_oauth2_credential_provider` accepts `delegation_mode` and `obo_grant_type` parameters. When `obo`, the provider is configured with `onBehalfOfTokenExchangeConfig` containing the appropriate grant type. `TOKEN_EXCHANGE` uses `actorTokenContent: NONE` with `CLIENT_SECRET_BASIC` auth method; `JWT_AUTHORIZATION_GRANT` uses `CLIENT_SECRET_POST`.
- **User token forwarding:** The invoke endpoint extracts the user's access token from the `Authorization` header and passes it as `user_access_token` in the invocation payload. The harness service injects it as an `X-Loom-User-Access-Token` HTTP header via a boto3 `before-send` event hook. Custom agents receive it in the invoke payload.
- **Agent runtime OBO exchange:** The `_OAuth2Auth` httpx handler in `mcp_client.py` supports both M2M and OBO flows. OBO uses `oauth2Flow: ON_BEHALF_OF_TOKEN_EXCHANGE` with the user's access token. Workload tokens are captured eagerly at construction time to avoid ContextVar propagation issues in background threads. Token caching is keyed by `(credential_provider_name, oauth2_flow, workload_token_prefix)` with expiry-skew handling.
- **Token info inspection:** `TokenInfoHook` (Strands `HookProvider`) extracts `__TOKEN_INFO__` markers from MCP tool results (server-initiated notifications cannot traverse the AgentCore proxy). Decoded JWT claims are emitted as `token_info` SSE events. The frontend renders a `TokenInfoCard` on the invoke page showing user token claims, OBO token claims with group mapping resolution, credential provider attribution, and claim annotations (issuer, audience, scopes, roles, expiry).
- **`client_type` field on identity providers:** `IdentityProvider` model gains a `client_type` column (`public` or `confidential`). The frontend `IdentityProviderPanel` shows a toggle for selecting client type, which controls whether the client secret is required.
- **Harness update endpoint:** `PUT /api/agents/{id}/redeploy-harness` uses the `UpdateHarness` API to modify existing harness agents in-place without recreation. Background task handles credential provider lifecycle (create new, delete removed) and config JSON updates.
- **Session table pagination:** `SessionTable` component adds pagination with page size controls and page navigation, improving usability for agents with many sessions.
- **Session ownership filtering:** Admin invoke panel filters sessions to those owned by the current user via `user_id` match, resolved authoritatively from a backend `/api/auth/me` endpoint.
- **Resource export/edit system:** `AgentCard` and `MemoryCard` replace the refresh button with a pencil-to-edit button. Clicking edit on an agent navigates to the deploy form pre-filled with the agent's exported configuration. Memory cards open the create form pre-filled with the memory's exported configuration (via `GET /api/memories/{id}/export`). JSON export from the form serializes the current state including `memory_strategies`.
- **Sidebar tooltip component:** New `Tooltip` shadcn component (`frontend/src/components/ui/tooltip.tsx`) using Radix Tooltip primitives with zero-delay appearance and animated content. Used for instant username display on sidebar hover.
- **HITL improvements:** Approval dialog race condition fix — prevents duplicate decision submissions. Elicitation dialog improvements. `ToolProviderException` handling in agent runtime yields user-friendly error messages instead of crashing the stream.
- **Graceful MCP failures:** `attach_mcp_tools` skips servers that fail to connect (e.g., 401 Unauthorized) rather than failing the entire agent initialization. Retry on next invocation when attachment fails. Strands internal loggers suppressed to CRITICAL during MCP attachment to avoid noisy stack traces.
- **`oauth2_audience` field on MCP servers:** Supports token exchange audience parameter required by Okta custom authorization servers.
- **`WORKLOAD_IDENTITY_NAME` env var:** Automatically set to `loom-{agent_name}` at deploy time for credential provider discovery.
- **Agent list registry filtering:** When registry is enabled, `t-user` users see only `APPROVED` agents (previously saw both approved and unregistered). When registry is disabled, the original behavior (show all non-draft) is preserved.

### Phase 29 — Code Interpreter for Custom Agents
- **Config:** `CodeInterpreterConfig` dataclass added to `agents/strands_agent/src/config.py` under `IntegrationsConfig` — fields: `enabled` (bool), `region` (string), `identifier` (string, optional custom interpreter ID).
- **Agent wiring:** `build_agent()` in `agents/strands_agent/src/agent.py` instantiates `AgentCoreCodeInterpreter` from `strands-agents-tools` when `config.integrations.code_interpreter.enabled` is `True`. The `.code_interpreter` tool is appended to the agent's tool list.
- **SDK dependency:** Uses `strands-agents-tools` (already in `requirements.txt`) which provides `AgentCoreCodeInterpreter` — a Strands `@tool`-decorated class backed by `bedrock_agentcore.tools.code_interpreter_client.CodeInterpreter`.
- **Sandbox isolation:** Code executes in an AWS-managed sandbox with no access to the host filesystem or network.
- **Configuration parsing:** `_parse_integrations()` reads `code_interpreter` from the JSON config and populates `CodeInterpreterConfig`.
- **Custom CI resource:** When a Code Interpreter execution role is configured, the backend creates a custom `bedrock-agentcore-control` Code Interpreter resource in parallel with the runtime artifact build. The resource ID is stored in `agents.code_interpreter_id` and its identifier is injected into `AGENT_CONFIG_JSON` before deployment.
- **IAM roles — two-role pattern:** Two distinct IAM roles are used. The agent execution role (deployed via `shared/iac/role.yaml`) requires `bedrock-agentcore` actions covering `code-interpreter/*` (system) and `code-interpreter-custom/*` (customer-owned) resource ARNs. A separate CI execution role (deployed via `shared/iac/code_interpreter_role.yaml`, named `loom-ci-role-{sanitized-name}`) is the sandbox identity used by the custom interpreter.
- **Deployment form:** Registration form exposes Code Interpreter as a peer integration section alongside Memory, MCP, and A2A. Fields: enable toggle, network mode (SANDBOX/PUBLIC), region dropdown, and CI execution role selector (filtered to `role_type="code_interpreter"` managed roles).
- **JSON manifest:** CI config exported/imported under nested `code_interpreter` key: `{"enabled": true, "region": "us-east-1", "network_mode": "SANDBOX", "role": "loom-ci-role-demo"}`.
- **CI observability:** `enable_code_interpreter_observability()` wires USAGE_LOGS and APPLICATION_LOGS vended log delivery for the custom CI resource, mirroring the runtime observability pattern. Account ID is extracted from the CI ARN to ensure the log group ARN is always valid.
- **X-Ray tracing:** Runtime deployments now include `OTEL_TRACES_EXPORTER=awsxray` and `OTEL_PROPAGATORS=xray` environment variables, activating the ADOT auto-instrumentation pipeline already present in the agent package.
- **Lifecycle:** Deleting an agent also deletes its associated CI resource. If active sessions are present, sessions are terminated first via `StopCodeInterpreterSession` before retrying the delete.
- **Role management:** `ManagedRole` model extended with `role_type` column (`"agent"` or `"code_interpreter"`). The Role Management panel groups roles by type with collapsible sections.
- **Status polling:** CI status is surfaced via `code_interpreter_status` on `AgentResponse`. CI polling is skipped when the agent is in `DELETING` state. `ResourceNotFoundException` during CI poll is logged at DEBUG (expected post-deletion).
- **Deployment phase label:** `creating_ci_resource` displays as "Building artifact & creating Code Interpreter" to reflect the parallel nature of the two operations.

### Phase 31 — VPC-Enabled Agents *(Complete)*
- **VPC configuration model:** `VpcConfig` ORM model with `name`, `vpc_id`, `subnet_ids` (JSON array), and `security_group_ids` (JSON array). Full CRUD API under `/api/vpc-configs`. Stored in the `vpc_configs` table; referenced by agents via `vpc_config_id` (INTEGER FK).
- **VPC egress for deploy-type agents:** `AgentDeployRequest` accepts `network_mode` (`PUBLIC` or `VPC`) and `vpc_config_id`. When `network_mode=VPC`, the runtime is created with `networkConfiguration.networkMode=VPC` and the resolved subnet/SG IDs. `vpc_config_id` is persisted on the `Agent` record and included in `AgentResponse` for export/edit round-trips.
- **VPC egress for harness agents:** `AgentHarnessDeployRequest` accepts `network_mode` and `vpc_config_id`. `create_harness` / `update_harness` accept optional `vpc_subnet_ids` and `vpc_security_group_ids` parameters passed through to the AgentCore Harness API when `network_mode=VPC`. `vpc_config_id` is persisted on the `Agent` record at harness creation time.
- **PrivateLink ingress IaC:** `shared/iac/privatelink.yaml` SAM template creates the NLB, VPC Endpoint Service, and required security groups for PrivateLink-based agent invocation. Makefile targets: `privatelink`, `privatelink.delete`, `privatelink.describe`.
- **Frontend VPC selector:** Network mode radio (PUBLIC/VPC) in the deploy form expands to show a VPC Config dropdown when VPC is selected. On agent edit, the previously-selected VPC config is pre-populated using a `useRef`-deferred effect that resolves the config name after the `vpcConfigs` list loads.
- **Harness refinements (same branch):**
  - All MCP tools (including OAuth2-authenticated) are included in the harness tool list; OAuth2 tokens are injected at invocation time via `remoteMcp.headers`.
  - `actor_id` sanitized with regex `[^a-zA-Z0-9:_/\-] → _` to handle Okta email-format subs that contain `@` and `.`.
  - Code Interpreter `ConflictException` handled by reusing existing CI resource by name (`list_code_interpreters` scan); orphaned CI resource deleted when harness is deleted.
  - Memory `retrievalConfig` built from active strategies (`strategy.status == "ACTIVE"`) using `strategyId` as key; `get_memory` response unwrapped from nested `"memory"` key.
  - `bedrock-agentcore:ListEvents` added to the memory policy in `shared/iac/role.yaml`.
  - Harness `ConflictException` on create resolved by pre-deleting the existing harness with the same name before calling `create_harness`.
  - Registry auto-registration for harness agents: harness status polling now includes the same auto-registration block as custom deploy-type agents — when deployment reaches READY and no `registry_record_id` exists, a DRAFT registry record is created.

### Phase 32 — Alternate LLM Providers (LiteLLM Proxy) *(Complete)*
- **Provider registry:** `backend/etc/providers.json` is the static provider registry (currently `bedrock` and `litellm`, each with `requires_api_key`, `requires_base_url`, `harness_supported` flags). Loaded at startup into `SUPPORTED_PROVIDERS`/`SUPPORTED_PROVIDER_IDS` in `routers/agents.py`. `GET /api/agents/providers` returns the registry merged with a live `available` flag per provider (LiteLLM is `available` only when a proxy connection is configured and enabled).
- **Per-agent provider selection:** `AgentDeployRequest`, `AgentHarnessDeployRequest`, and the register/PATCH request models accept `provider` (`"bedrock"` default or `"litellm"`), `base_url`, and `api_key`. Non-Bedrock providers are validated against `SUPPORTED_PROVIDER_IDS`; for `litellm`, the effective base URL comes from the configured proxy connection rather than a per-agent field.
- **LiteLLM proxy connection service (`backend/app/services/litellm.py`):** resolves the proxy's master key and base URLs with a two-tier fallback — a Settings-page override (Secrets Manager + `SiteSetting` rows, gated by a `litellm_enabled` toggle) always wins once saved; otherwise falls back to CFN-seeded env vars (`LOOM_LITELLM_PROXY_BASE_URL`, `LOOM_LITELLM_DISCOVERY_BASE_URL`, `LOOM_LITELLM_PROXY_API_KEY`) so a fresh deploy works without a Settings visit. Two base URLs are tracked because the caller differs: `agent_base_url` is what deployed agents/harnesses reach at runtime (e.g. an internal ALB); `discovery_base_url` is what the Loom backend itself uses for `/model/info`, `/key/generate`, `/key/delete` calls, falling back to `agent_base_url` when unset (useful when the backend reaches the proxy via a local SSM tunnel during dev while agents reach it through the real ALB).
- **Per-agent virtual key vending:** the master key is never handed to an agent. `vend_virtual_key()` mints a scoped LiteLLM virtual key via `/key/generate` (aliased `loom-agent-{agent_id}`, restricted to the agent's `allowed_model_ids`) and `revoke_virtual_key()` deletes it via `/key/delete` on redeploy/delete. Vending is idempotent — a deterministic key alias means a retried deploy revokes any stale key under the same alias before minting a new one. For custom (deploy-type) agents, the vended key is stored as a Secrets Manager secret (`loom/agents/{name}-{id}/llm-provider-api-key`) and referenced via the `LLM_PROVIDER_API_KEY_SECRET_ARN` config entry, resolved by the agent runtime at build time (see below). For harness agents, the key is instead registered as an AgentCore **API key credential provider** (`create_api_key_credential_provider`/`delete_api_key_credential_provider` in `services/credential.py`) — the Harness API's `liteLlmModelConfig.apiKeyArn` resolves it directly via `bedrock-agentcore:GetResourceApiKey` at invocation time, a distinct mechanism from Secrets Manager.
- **Harness model config (`services/harness.py`):** `_build_model_config()` builds either `bedrockModelConfig` (default) or `liteLlmModelConfig` (`modelId`, optional `apiKeyArn`, `apiBase`, `maxTokens`) for `CreateHarness`/`UpdateHarness`/`InvokeHarness`, selected by a new `provider` parameter threaded through `create_harness()`, `update_harness()`, and `invoke_harness_stream()`.
- **Strands agent runtime provider support:** `agents/strands_agent/src/config.py`'s `AgentConfig` gains `provider` (default `"bedrock"`), `base_url`, and `api_key_secret_arn` fields, parsed from the deploy-time JSON config. `agents/strands_agent/src/agent.py`'s `_build_model()` instantiates `BedrockModel` (IAM-authenticated, unchanged default), or for `openai`/`anthropic`/`litellm` resolves the API key once via `agents/strands_agent/src/integrations/secrets.py::resolve_secret()` and constructs `AnthropicModel`/`OpenAIModel`/`LiteLLMModel` respectively, with a bounded request timeout (`LOOM_MODEL_REQUEST_TIMEOUT_SECONDS`, default 30s) so an unreachable proxy fails fast with a loggable exception instead of hanging until the caller's own read timeout. For `litellm`, `client_args["use_litellm_proxy"] = True` is set so a bare model ID is routed through the proxy's `base_url` with the vended virtual key, rather than being handed unprefixed to LiteLLM's own provider auto-detection (which would otherwise route straight at the real upstream provider using the virtual key as if it were a real provider key).
- **Dynamic model catalog (`backend/app/services/model_catalog.py`):** merges four sources — the curated static `models.json`, live Bedrock availability/catalog discovery (`list_foundation_models`/`list_inference_profiles`, restricted to allow-listed labs), the live LiteLLM proxy's own catalog (`/model/info`, only when a proxy is configured), and LiteLLM's public `model_prices_and_context_window.json` as a pricing fallback for curated/dynamic Bedrock entries. `get_bedrock_models()` (Bedrock-only, never touches the proxy — used for the model picker's eager page-load fetch) and `get_litellm_models_live()` (proxy-only, no public-catalog or placeholder fallback — returns models actually deployed on the proxy, or empty if unreachable) are cached independently with a shared TTL (default 900s, `LOOM_MODEL_CATALOG_TTL_SECONDS`) so selecting one provider never waits on the other. `get_merged_models()` concatenates both for callers needing the full valid-ID universe (settings validation, PATCH, pricing). `clear_litellm_cache()` and `POST /api/settings/litellm-proxy/refresh` force a live re-fetch bypassing the TTL, recovering from a stale/empty cache (e.g. cached while the proxy was unreachable) without a backend restart.
- **Settings page LiteLLM proxy endpoints:** `GET/PUT /api/settings/litellm-proxy` manage `enabled`, `base_url` (agent base URL), `discovery_base_url`, and a write-only `master_key` (omitting it on PUT leaves the stored key untouched; responses include `has_master_key` instead of the key itself). `PUT` persists the URLs/toggle as `SiteSetting` rows and the master key to Secrets Manager, then clears the LiteLLM model-catalog cache so the next fetch reflects the new connection.
- **IAM/IaC (`backend/iac/ecs.yaml`):** new parameters `pLitellmProxyBaseUrl`, `pLitellmDiscoveryBaseUrl`, `pLitellmProxyApiKeySecretArn`, `pLitellmProxyApiKeySecretKmsKeyArn` seed the CFN-level env-var fallback; when the secret ARN is set, it's injected as the `LOOM_LITELLM_PROXY_API_KEY` ECS task Secret and the task execution role is granted `secretsmanager:GetSecretValue` on it (plus `kms:Decrypt` on its KMS key, if a customer-managed key is specified) — both conditioned on the parameter being non-empty so a deployment without LiteLLM configured grants nothing extra. Reaching this feature also required closing several unrelated AgentCore IAM gaps on the backend task role: full `CreateAgentRuntime`/`UpdateAgentRuntime`/`DeleteAgentRuntime`-family actions (previously only invoke-time actions were granted), `iam:CreateServiceLinkedRole` scoped to `AWSServiceRoleForBedrockAgentCoreNetwork` (VPC-mode runtimes trigger AWS to lazily create this role on first use per account), and CloudWatch Logs delivery-pipeline permissions (`PutDeliveryDestination`/`PutDeliverySource`/`CreateDelivery`/`DescribeDeliveries` and matching `Delete*`) for vended runtime/Code Interpreter log routing. A dedicated `LogsKmsKey` now encrypts the backend's own ECS log group. `bedrock:ListFoundationModels`/`ListInferenceProfiles` (list-only, no resource-level scoping) were added for `model_catalog.py`'s live Bedrock discovery.
- **Frontend provider selection:** `AgentRegistrationForm` adds a provider selector (fetched via `fetchProviders()`); switching providers resets model/credential fields. Selecting `litellm` lazily fetches its catalog on demand (`fetchLitellmModels()`, called only when the provider is selected or an imported/edited manifest references it) rather than eagerly alongside Bedrock's list, since it reflects exactly what the deployed proxy reports. A provider without `harness_supported` forces the deployment type back to Custom Agent. JSON import/export accepts both a flat `provider` string (legacy) and a nested `{id, base_url, api_key}` object. `InvokePanel` and `ChatPage` merge `fetchModels()` (Bedrock) with `fetchLitellmModels()` so an agent's `allowed_model_ids` resolve correctly regardless of which provider they come from; `groupModelsByProvider()` in `lib/models.ts` groups the merged picker options by provider (Bedrock first, then LiteLLM, then alphabetical) before the existing vendor grouping. Settings page gains a full LiteLLM panel (enabled toggle, Agent Base URL, Discovery Base URL, master key write-only field, live model list split by provider with per-provider enable/disable and a search filter, and a Refresh button wired to `POST /api/settings/litellm-proxy/refresh`).
- **API key credential provider service:** `create_api_key_credential_provider()`/`delete_api_key_credential_provider()` added to `services/credential.py`, distinct from the existing OAuth2 credential provider functions — creates/deletes AgentCore API key credential providers via `bedrock-agentcore-control`, with the same create-or-update-on-conflict handling as the OAuth2 path.

---

## 7. Open Questions / Future Decisions

| # | Question | Notes |
|---|----------|-------|
| 1 | What Strands Agents templates will be supported beyond the initial blueprint? | To be defined as new agent patterns emerge. |
| 2 | Should the Operate tab aggregate metrics via a separate analytics store or compute on-the-fly from SQLite? | SQLite is sufficient for MVP; revisit at scale. |
| 3 | What is the CloudWatch log format for agents that do NOT emit the "Start time:" structured log? | **Resolved.** `parse_agent_start_time` first looks for the "Agent invoked - Start time:" pattern; if not found, it falls back to the earliest CloudWatch event timestamp as an approximation. |
| 4 | Will multi-region support be needed? | Region is extracted per-agent from the ARN. The backend can manage agents across multiple regions simultaneously. |
| 5 | Should the Agent PK be changed from integer to a natural key? | **Decision: keep integer PK.** Integer PKs provide the best ergonomics for CLI usage and fastest SQLite joins. |
| 6 | Can we query AWS for live session status? | **No.** The Bedrock AgentCore SDK does not expose session listing/querying APIs. Session liveness is computed locally using an idle timeout heuristic (`LOOM_SESSION_IDLE_TIMEOUT_SECONDS`, default 300). |
| 7 | How should Cognito client secrets be stored? | **Resolved.** AWS Secrets Manager with in-memory caching (5-minute TTL). Never stored in the local database. |
| 8 | Should agent deletion also clean up AWS resources? | **Resolved.** Optional checkbox "Also delete in AgentCore" shown when agent has a runtime_id. IAM roles are preserved. |
| 9 | Should session filtering be done client-side or server-side? | **Resolved.** Server-side via `user_id` query parameter on `GET /api/agents/{id}/sessions`. Client-side filtering caused a race condition with Cognito auth timing in AWS deployments — sessions would briefly appear then vanish when `currentUserId` resolved and triggered effect re-runs. The ALB idle timeout is set to 300s to support long-lived SSE connections. |
