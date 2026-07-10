# Loom Backend

FastAPI backend for the Loom Agent Builder Playground. Provides endpoints for agent registration, deployment, SSE streaming invocation, paginated CloudWatch log retrieval, cold-start latency measurement, session liveness tracking, memory resource management, MCP server management, A2A agent management, AWS Agent Registry integration (governance and discovery), alternate LLM provider support (self-hosted LiteLLM proxy with per-agent virtual key vending and a dynamic model catalog), security administration, 3rd-party identity provider management (Microsoft Entra ID, Okta, Auth0, Generic OIDC), per-user authorizer linking (cross-IdP OAuth popup flow with Secrets Manager token storage), on-behalf-of (OBO) token exchange (RFC 8693) for user-scoped delegation to downstream MCP servers and A2A agents, tag policy management, tag profile management, cost estimation dashboard, actual runtime cost retrieval from CloudWatch usage logs, and admin audit tracking (login events, user actions, page views, per-session aggregation). Agent deploy applies resolved tags to the DB record immediately on creation so tag-based resource filtering (e.g., demo user group restrictions) is effective from CREATING status.

## Technology Stack

| Concern | Choice |
|---------|--------|
| Framework | FastAPI |
| Server | Uvicorn |
| ORM | SQLAlchemy (SQLite / PostgreSQL) |
| AWS SDK | boto3 |
| Python | 3.11+ |
| Dependency manager | uv |
| Streaming | SSE via `StreamingResponse` |

## Setup

```bash
# Create and activate virtual environment
uv venv .venv
source .venv/bin/activate

# Install dependencies
make install

# Run tests
make test

# Start the development server
make run
```

### Local Development

By default the backend uses **SQLite** (`sqlite:///./loom.db`) — no database setup required. Tables are auto-created on startup.

To develop against a deployed **RDS PostgreSQL** instance via SSM tunnel (requires `loom-rds` + `loom-ec2` stacks):

```bash
make tunnel              # Port forwards localhost:5432 → RDS via EC2 bastion
uv pip install ".[postgres]"
make run
```

See the [root README](../README.md) for the full local development guide, deployment workflow, and environment configuration.

## Configuration

Runtime configuration is sourced from `etc/environment.sh`:

| Variable | Description | Default |
|----------|-------------|---------|
| `BACKEND_PORT` | Port for uvicorn | `8000` |
| `FRONTEND_PORT` | Port for Vite dev server (CORS) | `5173` |
| `DATABASE_URL` | SQLite file path | `sqlite:///./loom.db` |
| `LOG_LEVEL` | Backend log level | `info` |
| `LOOM_SESSION_IDLE_TIMEOUT_SECONDS` | Session idle timeout for liveness detection | `300` |
| `LOOM_SESSION_MAX_LIFETIME_SECONDS` | Maximum session lifetime | `3600` |
| `AWS_REGION` | AWS region for deployments | `us-east-1` |
| `LOOM_ARTIFACT_BUCKET` | S3 bucket for agent deployment artifacts | — |
| `LOOM_COGNITO_USER_POOL_ID` | Cognito User Pool ID for user authentication | — |
| `LOOM_COGNITO_REGION` | Region of the Cognito pool | `AWS_REGION` |
| `LOOM_COGNITO_USER_CLIENT_ID` | Cognito user app client ID (auto-included in agent `allowedClients` on deploy) | — |
| `LOOM_ALLOWED_ORIGINS` | Comma-separated additional CORS origins for deployed environments | — |
| `LOOM_REGISTRY_ID` | AWS Agent Registry ID (bootstrap fallback; prefer Settings page configuration) | — |
| `LOOM_LITELLM_PROXY_BASE_URL` | Default Agent Base URL for a self-hosted LiteLLM proxy (bootstrap fallback; prefer Settings → Models → LiteLLM). Leave unset to disable the LiteLLM provider. | — |
| `LOOM_LITELLM_DISCOVERY_BASE_URL` | Default Discovery Base URL the backend itself uses for model discovery, if different from `LOOM_LITELLM_PROXY_BASE_URL` (e.g. a local SSM tunnel during dev) | — |
| `LOOM_LITELLM_PROXY_API_KEY` | Default LiteLLM proxy master key (bootstrap fallback; a Settings-page save always overrides this) | — |

AWS credentials use the standard boto3 credential chain (environment variables, AWS profile, instance metadata).

When `LOOM_COGNITO_USER_POOL_ID` is set, the backend validates user JWTs, derives scopes from `cognito:groups` via the `GROUP_SCOPES` mapping, and enforces per-endpoint scope requirements using `require_scopes()`. Returns 401 for missing/invalid tokens, 403 for insufficient scopes. When not set (bypass mode), all scopes are granted for local development. The user client ID is configured on the frontend side (via `VITE_COGNITO_USER_CLIENT_ID` in the frontend `.env` file), not the backend.

## Authentication and Authorization

### Scope Model

The backend uses a fine-grained scope model for access control:

| Scope | Description |
|-------|-------------|
| `catalog:read` | View agent and memory catalogs |
| `catalog:write` | Modify catalog metadata |
| `agent:read` | View agents, sessions, and invocations |
| `agent:write` | Create, update, and delete agents |
| `memory:read` | View memory resources |
| `memory:write` | Create, update, and delete memory resources |
| `security:read` | View roles, authorizers, and credentials |
| `security:write` | Manage roles, authorizers, and credentials |
| `settings:read` | View site settings |
| `settings:write` | Manage site settings |
| `tagging:read` | View tag policies and profiles |
| `tagging:write` | Manage tag policies and profiles |
| `costs:read` | View cost dashboard and estimates |
| `costs:write` | Manage cost settings and pull actuals |
| `mcp:read` | View MCP servers and tools |
| `mcp:write` | Manage MCP servers and access rules |
| `a2a:read` | View A2A agents and skills |
| `a2a:write` | Manage A2A agents and access rules |
| `registry:read` | View registry records (uses mcp:read) |
| `registry:write` | Manage registry records (uses mcp:write) |
| `invoke` | Invoke agents |

### Group-to-Scope Mapping (Two-Dimensional Architecture)

Scopes are derived from Cognito group membership via `GROUP_SCOPES`. The system uses two dimensions:

**Type Groups** (UI view):
- `t-admin` — No scopes directly, but determines UI layout
- `t-user` — No scopes directly, but determines UI layout

**Resource Groups** (access control):
- `g-admins-super` — All 21 scopes (catalog:r/w, agent:r/w, memory:r/w, security:r/w, settings:r/w, tagging:r/w, costs:r/w, mcp:r/w, a2a:r/w, registry:r/w, invoke)
- `g-admins-demo` — Read/write to most pages (`catalog:read`, `agent:read/write`, `memory:read/write`, `security:read`, `settings:read/write`, `tagging:read`, `costs:read/write`, `mcp:read/write`, `a2a:read/write`) + `invoke`. Write operations restricted to `loom:group=demo` resources.
- `g-admins-security` — `security:read`, `security:write`, `settings:read`
- `g-admins-memory` — `memory:read`, `memory:write`, `settings:read`
- `g-admins-mcp` — `mcp:read`, `mcp:write`, `settings:read`
- `g-admins-a2a` — `a2a:read`, `a2a:write`, `settings:read`
- `g-admins-registry` — `mcp:read`, `a2a:read`, `registry:read`, `registry:write`, `settings:read`, `settings:write`, `tagging:read`
- `g-users-demo`, `g-users-test`, `g-users-strategics` — `invoke` + read access to resources tagged with matching group

### Resource Filtering by Group Tag

Resources (agents and memories) are tagged with `loom:group` at creation time. The backend filters resources based on resource group membership:

- **g-admins-super**: See all resources including untagged (no filtering)
- **Other g-admins-* groups**: See all resources including untagged (admins have visibility across groups)
- **g-users-* groups**: Only see resources where `loom:group` matches their group (e.g., `g-users-demo` sees only `loom:group=demo`)
- **Multi-group users**: See resources tagged with ANY of their groups (union filter)

Demo-admin write restrictions: `g-admins-demo` can only create/delete resources with `loom:group=demo`

### Demo User Architecture

The system includes demo user personas with different access levels:

1. **demo-admin** (Type: `t-admin`, Groups: `g-admins-demo`): Can create and manage agents, memories, MCP servers, and A2A agents within the demo group. Has read access to all pages and write access to demo resources. Restricted by backend validation to `loom:group=demo` on create/delete operations.
2. **demo-user** (Type: `t-user`, Groups: `g-users-demo`): Read-only access to demo resources. Can only invoke agents. Filtered to see only `loom:group=demo` resources.

Demo users cannot see or interact with resources tagged for other groups (e.g., test, strategics).

### View As Mode

Super-admins can use "View As" mode to see the system from another user's perspective. The frontend passes a `group` query parameter to backend endpoints (e.g., `GET /api/agents?group=demo`, `GET /api/dashboard/costs?group=demo`). The backend applies group-based filtering as if the super-admin belonged to that group. This enables permission model validation without switching accounts.

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── db.py                # SQLAlchemy engine, session factory, init_db
│   ├── models/
│   │   ├── agent.py         # Agent ORM model
│   │   ├── config_entry.py  # AgentConfigEntry ORM model (per-agent key-value config)
│   │   ├── session.py       # InvocationSession ORM model (session_id string PK)
│   │   ├── invocation.py    # Invocation ORM model (timing + latency data)
│   │   ├── managed_role.py  # ManagedRole ORM model (IAM roles)
│   │   ├── authorizer_config.py    # AuthorizerConfig ORM model
│   │   ├── authorizer_credential.py # AuthorizerCredential ORM model
│   │   ├── permission_request.py   # PermissionRequest ORM model
│   │   ├── memory.py        # Memory ORM model (AgentCore Memory resources)
│   │   ├── mcp.py           # McpServer, McpTool, McpServerAccess ORM models
│   │   ├── a2a.py           # A2aAgent, A2aAgentSkill, A2aAgentAccess
│   │   ├── identity_provider.py # IdentityProvider ORM model (3rd-party OIDC providers)
│   │   ├── tag_policy.py    # TagPolicy ORM model (configurable tag policies)
│   │   ├── tag_profile.py   # TagProfile ORM model (named tag presets)
│   │   ├── site_setting.py    # SiteSetting ORM model (site-wide settings)
│   │   └── audit.py           # AuditLogin, AuditAction, AuditPageView ORM models
│   ├── dependencies/
│   │   └── auth.py          # Auth dependencies (get_current_user, require_scopes, UserInfo)
│   ├── routers/
│   │   ├── auth.py          # Auth config endpoint (GET /api/auth/config)
│   │   ├── agents.py        # Agent CRUD + ARN parsing + log group derivation
│   │   ├── invocations.py   # SSE streaming invoke + session/invocation queries
│   │   ├── logs.py          # CloudWatch log browsing with pagination + session log retrieval + vended log sources (runtime/memory)
│   │   ├── memories.py      # Memory resource CRUD + strategy mapping
│   │   ├── a2a.py           # A2A agent CRUD, Agent Card, skills, access control
│   │   ├── mcp.py           # MCP server CRUD, tool discovery, access control
│   │   ├── security.py      # Security admin: roles, authorizers, credentials, permissions
│   │   ├── settings.py      # Tag policy + tag profile CRUD (/api/settings/tags, /api/settings/tag-profiles)
│   │   ├── costs.py          # Cost dashboard: estimates + runtime/memory actuals from CloudWatch
│   │   ├── traces.py         # Trace retrieval: OTEL log parsing for trace summaries and span detail
│   │   ├── admin.py          # Admin audit API: login/action/pageview tracking, sessions, summary
│   │   ├── registry.py      # Agent Registry: record CRUD, lifecycle management, search
│   │   └── utils.py         # Shared router utilities
│   └── services/
│       ├── agentcore.py     # boto3 wrapper: describe, list endpoints, invoke
│       ├── cloudwatch.py    # CloudWatch log retrieval with pagination, session filtering, usage log parsing, memory log parsing
│       ├── otel.py          # OTEL log parsing: fetch events from otel-rt-logs stream, parse traces and spans
│       ├── observability.py # CloudWatch vended log delivery configuration
│       ├── cognito.py       # Cognito OAuth2 token retrieval
│       ├── credential.py    # AgentCore credential provider management
│       ├── deployment.py    # Agent artifact build + runtime CRUD
│       ├── harness.py       # AgentCore Harness API: create, update, get, delete, invoke stream
│       ├── iam.py           # IAM role management + Cognito pool listing
│       ├── jwt_validator.py # JWT validation against any JWKS endpoint (Cognito + external IdPs)
│       ├── oidc.py          # OIDC discovery: fetch .well-known/openid-configuration
│       ├── token.py         # Generic token service: client credentials grant against any OIDC token endpoint
│       ├── latency.py       # Pure computation: cold_start_latency_ms, client_duration_ms
│       ├── a2a.py           # A2A Agent Card fetching, parsing, connection test
│       ├── mcp.py           # MCP connection test + tool fetch stubs
│       ├── memory.py        # boto3 wrapper: AgentCore Memory CRUD + LTM record queries
│       ├── secrets.py       # Secrets Manager wrapper with caching
│       ├── tokens.py        # Bedrock CountTokens API with provider guard
│       ├── authorizer_linking.py # Per-user authorizer linking: token storage/resolution via Secrets Manager
│       ├── registry.py      # AWS Agent Registry: control/data plane wrapper, descriptor builders
│       └── usage_poller.py  # Background poller: estimated → actual costs
├── scripts/
│   ├── stream.py            # CLI streaming client (httpx-based)
│   ├── migrate_sqlite_to_postgres.py  # SQLite → PostgreSQL migration
│   ├── fix_sequences.py     # PostgreSQL sequence auto-repair
│   ├── reset_db.py          # Database reset utility
│   ├── debug_session_correlation.py  # Debug script to correlate session IDs
│   ├── query_memory_records.py  # Query LTM records by actor ID (resolves strategy namespaces)
│   └── list_memory_records.py   # List LTM records by memory ID and namespace
├── tests/
│   ├── test_agents_deploy.py
│   ├── test_a2a.py          # A2A agent CRUD, Agent Card, skills, access
│   ├── test_registry.py     # Registry record CRUD, lifecycle, search, visibility
├── Dockerfile               # Backend container image (Python 3.13 slim + uvicorn + agent source)
├── makefile                 # Build, test, and manual testing targets
├── pyproject.toml
└── requirements.txt
```

## Database Schema

### `agents`

Stores registered and deployed AgentCore Runtime agents. Uses an auto-incrementing integer PK for internal references; `arn` and `runtime_id` are stored as indexed columns for AWS lookups. Includes columns for: `source` (`register`, `deploy`, or `harness`), `deployment_status`, `execution_role_arn`, `endpoint_name`, `endpoint_arn`, `endpoint_status`, `protocol`, `network_mode`, `authorizer_config`, `credential_providers`, `deployed_at`, `tags` (JSON dict of resolved tag key-value pairs), `harness_id` (harness ID for managed agent deployments), `registry_record_id` (AWS Agent Registry record ID), and `registry_status` (registry lifecycle status). Agents are auto-registered in DRAFT status on deployment when registry is configured.

### `agent_config_entries`

Stores key-value configuration per agent. Used for environment variables, secret ARN references, and agent metadata (e.g., `AGENT_CONFIG_JSON` for model_id).

### `managed_roles`

Stores IAM roles managed through the Security Admin workflow. Includes role name, ARN, description, and policy document.

### `authorizer_configs`

Stores authorizer configurations (e.g., Cognito pools) with pool ID, discovery URL, allowed clients, and allowed scopes.

### `authorizer_credentials`

Stores OAuth credentials per authorizer config. Each credential has a label, client_id, and a reference to the client_secret stored in AWS Secrets Manager (`client_secret_arn`). Client secrets are never stored in the local database.

### `permission_requests`

Stores permission escalation requests against managed roles. Includes requested actions, resources, justification, and review status (pending/approved/denied).

### `tag_policies`

Stores configurable tag policies for AWS resource tagging. Each policy defines a tag key, optional default value, source (`deploy-time` for auto-applied tags, `build-time` for user-supplied tags), whether the tag is required, and whether it should display on cards (`show_on_card`). Seeded with default policies (`loom:deployed-by`, `loom:application`, `loom:group`, `loom:owner`) on database initialization.

### `tag_profiles`

Stores named presets of tag key-value pairs. Each profile has a unique name and a JSON dict of tags. When a profile is selected during deployment, its tag values are merged with deploy-time policy defaults and applied to all created AWS resources. Tag values are limited to 128 characters.

### `mcp_servers`

Stores registered MCP servers. Columns include `name`, `url`, `transport` (sse or streamable_http), `description`, `auth_type` (none or oauth2), OAuth2 fields (`oauth2_client_id`, `oauth2_client_secret`, `oauth2_token_url`, `oauth2_scopes`, `oauth2_well_known_url`), `status` (active/inactive), and timestamps. The `oauth2_client_secret` is write-only — it is never returned in GET responses; a boolean `has_oauth2_secret` is returned instead.

### `mcp_tools`

Stores discovered tools for each MCP server. Columns include `server_id` (FK to mcp_servers), `name`, `description`, and `input_schema` (JSON). Tools are refreshed via the tool discovery endpoint. Cascade-deletes when the parent server is removed.

### `mcp_server_access`

Stores per-persona access rules for MCP server tools. Columns include `server_id` (FK to mcp_servers), `persona` (unique per server), `allowed` (boolean), `access_mode` (all_tools or selected_tools), and `allowed_tool_names` (JSON list). Defaults to deny (no access) until explicitly granted. Cascade-deletes when the parent server is removed.

### `a2a_agents`

Stores registered A2A (Agent-to-Agent) protocol agents. Columns include `base_url`, `name`, `description`, `agent_version`, `documentation_url`, `provider_organization`, `provider_url`, `capabilities` (JSON), `authentication_schemes` (JSON), `default_input_modes` (JSON), `default_output_modes` (JSON), `agent_card_raw` (JSON), `status` (active/inactive/error), `auth_type` (none or oauth2), OAuth2 fields (`oauth2_client_id`, `oauth2_client_secret`, `oauth2_well_known_url`, `oauth2_scopes`), `last_fetched_at`, and timestamps. The `oauth2_client_secret` is write-only — it is never returned in GET responses.

### `a2a_agent_skills`

Stores skills parsed from A2A Agent Cards. Columns include `agent_id` (FK to a2a_agents), `skill_id`, `name`, `description`, `tags` (JSON), `examples` (JSON), `input_modes` (JSON), `output_modes` (JSON), and `last_refreshed_at`. Skills are synced on registration and on card refresh. Cascade-deletes when the parent agent is removed.

### `a2a_agent_access`

Stores per-persona access rules for A2A agent skills. Columns include `agent_id` (FK to a2a_agents), `persona_id`, `access_level` (all_skills or selected_skills), and `allowed_skill_ids` (JSON list). Defaults to deny (no access) until explicitly granted. Cascade-deletes when the parent agent is removed.

### `memories`

Stores AgentCore Memory resource metadata. Columns include `name`, `arn`, `memory_id`, `region`, `account_id`, `status` (CREATING/ACTIVE/FAILED/DELETING), `event_expiry_duration`, `memory_execution_role_arn`, `encryption_key_arn`, `strategies_config` (JSON), `strategies_response` (JSON), `tags` (JSON dict of resolved tags), and `failure_reason`.

### `invocation_sessions`

Groups related invocations. Uses `session_id` (UUID string) as the primary key — this is the natural key passed to AWS as `runtimeSessionId`.

### `invocations`

Stores per-invocation timing measurements, token usage, cost breakdowns, and status. Fields include `client_invoke_time`, `client_done_time`, `agent_start_time`, `cold_start_latency_ms`, `client_duration_ms`, `input_tokens`, `output_tokens`, `estimated_cost`, `compute_cpu_cost`, `compute_memory_cost`, `idle_cpu_cost`, `idle_memory_cost`, `stm_cost`, `ltm_cost`, `cost_source`, and `status`. Runtime costs are recomputed from `client_duration_ms` at view time using current pricing defaults. Token counts use a 4-character-per-token heuristic; model cost is computed from per-model pricing data.

### `site_settings`

Stores configurable site-wide settings. Currently includes `cpu_io_wait_discount` (default 75%) which is applied universally to runtime CPU cost calculations.

### `audit_login`, `audit_action`, `audit_page_view`

Write-only audit tables populated by the frontend. `audit_login` records user login events with a `browser_session_id` (client-generated UUID) to distinguish concurrent sessions for shared accounts. `audit_action` records explicit user interactions (deploys, creates, deletes, etc.) with category, type, and optional resource name. `audit_page_view` records persona navigation with entry time and duration. Only the Admin Dashboard reads from these tables.

## API Endpoints

### Agent Registration and Deployment

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/agents` | Register an agent by ARN or deploy a new agent |
| `GET` | `/api/agents` | List all registered agents (includes `model_id` and `active_session_count`) |
| `GET` | `/api/agents/{agent_id}` | Get agent metadata |
| `GET` | `/api/agents/{agent_id}/status` | Poll AWS for runtime/endpoint status during deployment |
| `DELETE` | `/api/agents/{agent_id}?cleanup_aws=true` | Remove agent; optionally initiate async AWS deletion (returns DELETING status) |
| `DELETE` | `/api/agents/{agent_id}/purge` | Remove agent from local DB only (after AWS deletion confirmed) |
| `POST` | `/api/agents/{agent_id}/refresh` | Re-fetch metadata from AWS |
| `POST` | `/api/agents/{agent_id}/redeploy` | Redeploy with current config |
| `GET` | `/api/agents/roles` | List IAM roles for AgentCore |
| `GET` | `/api/agents/cognito-pools` | List Cognito user pools |
| `GET` | `/api/agents/models` | List supported Bedrock models (with display name and group) |
| `GET` | `/api/agents/models/litellm` | List models reported live by the connected LiteLLM proxy, if any (fetched on demand, not part of `/models`) |
| `GET` | `/api/agents/providers` | List supported LLM providers (`bedrock`, `litellm`), each with a live `available` flag |
| `GET` | `/api/agents/models/pricing` | List models with pricing metadata |
| `GET` | `/api/agents/defaults` | Get configurable defaults (idle timeout, max lifetime) |
| `GET` | `/api/agents/{agent_id}/integration` | Get external integration info (endpoints, auth, code snippets) |

### Security Administration

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/security/roles` | Create a managed role |
| `GET` | `/api/security/roles` | List managed roles |
| `GET` | `/api/security/roles/{role_id}` | Get a managed role |
| `PUT` | `/api/security/roles/{role_id}` | Update a managed role |
| `DELETE` | `/api/security/roles/{role_id}` | Delete a managed role |
| `GET` | `/api/security/cognito-pools` | List Cognito pools with discovery URLs |
| `POST` | `/api/security/authorizers` | Create an authorizer config |
| `GET` | `/api/security/authorizers` | List authorizer configs |
| `DELETE` | `/api/security/authorizers/{auth_id}` | Delete an authorizer config |
| `POST` | `/api/security/authorizers/{auth_id}/credentials` | Add a credential |
| `GET` | `/api/security/authorizers/{auth_id}/credentials` | List credentials |
| `DELETE` | `/api/security/authorizers/{auth_id}/credentials/{cred_id}` | Delete a credential |
| `POST` | `/api/security/authorizers/{auth_id}/credentials/{cred_id}/token` | Generate OAuth token |
| `POST` | `/api/security/permission-requests` | Create a permission request |
| `GET` | `/api/security/permission-requests` | List permission requests |
| `PUT` | `/api/security/permission-requests/{req_id}/review` | Review a permission request |

### Tag Policy Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings/tags` | List all tag policies |
| `POST` | `/api/settings/tags` | Create a tag policy (409 if key exists) |
| `PUT` | `/api/settings/tags/{tag_id}` | Update a tag policy |
| `DELETE` | `/api/settings/tags/{tag_id}` | Delete a tag policy |

### Tag Profile Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings/tag-profiles` | List all tag profiles |
| `POST` | `/api/settings/tag-profiles` | Create a tag profile |
| `PUT` | `/api/settings/tag-profiles/{profile_id}` | Update a tag profile |
| `DELETE` | `/api/settings/tag-profiles/{profile_id}` | Delete a tag profile |

### Cost Dashboard

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/dashboard/costs` | Aggregate estimated costs (group filter, time-range filter, per-agent breakdown) |
| `POST` | `/api/dashboard/costs/actuals` | Pull actual costs from CloudWatch usage logs (runtime per-session breakdown) and APPLICATION_LOGS (memory per-resource breakdown) |

Runtime costs are recomputed from `client_duration_ms` at view time using current pricing defaults (1 vCPU, 0.5 GB memory, $0.0895/vCPU-hour, $0.00945/GB-hour). The CPU I/O Wait Discount (configurable in Settings, default 75%) is applied universally to CPU costs across both estimates and actuals. Runtime actuals include all events within the time window for a given runtime — USAGE_LOGS session IDs are internal to AgentCore and do not match Loom's `runtimeSessionId`. Memory actuals are parsed from vended `BedrockAgentCoreMemory_ApplicationLogs` — memory pipeline session IDs are also internal to AgentCore.

### Site Settings

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings/site` | List all site settings (includes defaults for unset keys) |
| `PUT` | `/api/settings/site/{key}` | Create or update a site setting |
| `GET`/`PUT` | `/api/settings/litellm-proxy` | Get/update the LiteLLM proxy connection (`enabled`, `base_url`, `discovery_base_url`, write-only `master_key`) |
| `POST` | `/api/settings/litellm-proxy/refresh` | Force a live re-fetch of the LiteLLM proxy's model catalog, bypassing the cache |

### Authentication

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/auth/config` | Return auth config (Cognito or active external IdP) for frontend |

### Identity Provider Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/settings/identity-providers` | Create an identity provider configuration |
| `GET` | `/api/settings/identity-providers` | List all identity provider configurations |
| `GET` | `/api/settings/identity-providers/{id}` | Get a specific identity provider |
| `PUT` | `/api/settings/identity-providers/{id}` | Update an identity provider configuration |
| `DELETE` | `/api/settings/identity-providers/{id}` | Delete an identity provider configuration |
| `POST` | `/api/settings/identity-providers/discover` | Run OIDC discovery against a well-known URL |
| `POST` | `/api/settings/identity-providers/{id}/test-discovery` | Test discovery for an existing provider |

Supports Microsoft Entra ID, Okta, Auth0, and Generic OIDC providers. Includes OIDC discovery for auto-populating endpoints, configurable group claim mapping (external IdP groups to Loom groups), and generic JWT validation against any JWKS endpoint. Cognito remains the default when no external IdP is active. Scope enforcement: `settings:read` for GET, `settings:write` for POST/PUT/DELETE.

### Memory Resources

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/memories` | Create a memory resource |
| `POST` | `/api/memories/import` | Import an existing memory by AWS memory ID |
| `GET` | `/api/memories` | List all memory resources |
| `GET` | `/api/memories/{memory_id}` | Get a specific memory resource |
| `POST` | `/api/memories/{memory_id}/refresh` | Refresh memory status from AWS |
| `DELETE` | `/api/memories/{memory_id}?cleanup_aws=true` | Delete a memory resource; optionally delete from AWS |
| `DELETE` | `/api/memories/{memory_id}/purge` | Remove from local DB only (no AWS call) |
| `GET` | `/api/memories/{memory_id}/records` | Retrieve stored LTM records for the authenticated user |

Supports five memory strategy types: semantic, summary, user_preference, episodic, and custom. Strategies are mapped to AWS tagged union format on creation. The delete endpoint supports async deletion: when `cleanup_aws=true`, it initiates deletion in AWS and marks the resource as DELETING. The frontend polls via refresh and uses purge to clean up locally after AWS confirms deletion (404).

The records endpoint uses the **data plane** client (`bedrock-agentcore`) — not the control plane — and queries by namespace, substituting the actor ID and strategy IDs from the memory's strategy configuration. The service unwraps the AWS tagged union strategy format (e.g. `{"userPreferenceMemoryStrategy": {"strategyId": "...", "namespaces": [...]}}`) to extract namespace templates. Records are scoped to the authenticated user's identity (`username or sub or "loom-agent"` fallback chain). Content field mapping handles dict, string, and fallback structures. Records with empty text are filtered out. INFO-level debug logging is emitted at each stage.

### MCP Server Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/mcp/servers` | Register an MCP server |
| `GET` | `/api/mcp/servers` | List all MCP servers |
| `GET` | `/api/mcp/servers/{server_id}` | Get a specific MCP server |
| `PUT` | `/api/mcp/servers/{server_id}` | Update an MCP server |
| `DELETE` | `/api/mcp/servers/{server_id}` | Delete an MCP server (cascades to tools and access) |
| `POST` | `/api/mcp/servers/{server_id}/test-connection` | Test connectivity to an MCP server |
| `GET` | `/api/mcp/servers/{server_id}/tools` | List discovered tools for a server |
| `POST` | `/api/mcp/servers/{server_id}/tools/refresh` | Refresh tools via discovery |
| `GET` | `/api/mcp/servers/{server_id}/access` | Get access rules for a server |
| `PUT` | `/api/mcp/servers/{server_id}/access` | Update access rules for a server |

OAuth2 authentication supports well-known URL discovery for auto-populating token URLs and scopes. The `oauth2_client_secret` field is write-only — never included in GET responses; a `has_oauth2_secret` boolean is returned instead. Conditional validation ensures all required OAuth2 fields are present when `auth_type` is `oauth2`. Scope enforcement: `mcp:read` for GET, `mcp:write` for POST/PUT/DELETE.

### A2A Agent Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/a2a/agents` | Register an A2A agent (fetches Agent Card from base URL) |
| `GET` | `/api/a2a/agents` | List all A2A agents |
| `GET` | `/api/a2a/agents/{agent_id}` | Get a specific A2A agent |
| `PUT` | `/api/a2a/agents/{agent_id}` | Update an A2A agent |
| `DELETE` | `/api/a2a/agents/{agent_id}` | Delete an A2A agent (cascades to skills and access) |
| `POST` | `/api/a2a/agents/{agent_id}/test-connection` | Test connectivity (OAuth2 token + Agent Card fetch) |
| `GET` | `/api/a2a/agents/{agent_id}/card` | Get cached raw Agent Card JSON |
| `POST` | `/api/a2a/agents/{agent_id}/card/refresh` | Re-fetch Agent Card and sync skills |
| `GET` | `/api/a2a/agents/{agent_id}/skills` | List cached skills for an agent |
| `GET` | `/api/a2a/agents/{agent_id}/access` | Get access rules for an agent |
| `PUT` | `/api/a2a/agents/{agent_id}/access` | Update access rules for an agent |

A2A agents are registered by base URL. On registration, the backend fetches `<base_url>/.well-known/agent.json` and populates all agent metadata from the Agent Card. Skills are parsed and stored in a separate table for queryability and fine-grained access control. OAuth2 authentication follows the same pattern as MCP servers — `oauth2_client_secret` is write-only with `has_oauth2_secret` flag. Scope enforcement: `a2a:read` for GET, `a2a:write` for POST/PUT/DELETE.

### Agent Invocation (SSE Streaming)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/agents/{agent_id}/invoke` | Invoke agent, stream response via SSE |
| `GET` | `/api/agents/{agent_id}/sessions` | List sessions with invocations (optional `user_id` query param for server-side filtering) |
| `GET` | `/api/agents/{agent_id}/sessions/{session_id}` | Get a specific session |

The invoke endpoint uses a priority-based token selection: (0) `bearer_token` from request body, (1) `credential_id` for M2M token, (2) user access token (forwarded when agent has authorizer), (3) agent config M2M flow, (4) SigV4. The `session_start` SSE event includes `has_token` and `token_source` fields when a token is used.

Agent list responses include a computed `active_session_count` field based on `LOOM_SESSION_IDLE_TIMEOUT_SECONDS`, and an `authorizer_config` field extracted from the AgentCore runtime's `customJWTAuthorizer` configuration. Session responses include computed `live_status` (`"pending"`, `"streaming"`, `"active"`, or `"expired"`).

### CloudWatch Logs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agents/{agent_id}/logs/streams` | List available log streams |
| `GET` | `/api/agents/{agent_id}/logs` | Get logs from latest (or specified) stream with pagination |
| `GET` | `/api/agents/{agent_id}/sessions/{session_id}/logs` | Get all logs for a session (stream-name matching + filterPattern fallback, paginated) |
| `GET` | `/api/agents/{agent_id}/logs/vended` | Get logs from a vended log source (runtime or memory APPLICATION_LOGS, runtime USAGE_LOGS) |

### Traces (OTEL Logs)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agents/{agent_id}/sessions/{session_id}/traces` | List traces for a session (parsed from OTEL log records in CloudWatch) |
| `GET` | `/api/agents/{agent_id}/traces/{trace_id}` | Get full trace detail with per-span events |

### Admin Audit

Requires `security:read` scope (super-admins and demo-admins).

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/audit/login` | Record a user login event |
| `GET` | `/api/admin/audit/logins` | List login events (filterable by user_id, date range) |
| `POST` | `/api/admin/audit/action` | Record a user action event |
| `GET` | `/api/admin/audit/actions` | List action events (filterable by user_id, session, category, type, date range) |
| `POST` | `/api/admin/audit/pageview` | Record a page view event |
| `GET` | `/api/admin/audit/pageviews` | List page view events (filterable by user_id, session, page name, date range) |
| `GET` | `/api/admin/audit/sessions` | List browser sessions with aggregated action and page view counts |
| `GET` | `/api/admin/audit/sessions/{browser_session_id}/timeline` | Interleaved event timeline for a browser session |
| `GET` | `/api/admin/audit/summary` | Aggregated metrics: totals, by-category counts, by-page stats, daily series |

## Streaming Architecture

The boto3 `invoke_agent_runtime` call returns a synchronous `StreamingBody`. To prevent blocking the uvicorn async event loop:

1. Each `next()` call on the chunk generator runs via `asyncio.to_thread()`.
2. SSE events are flushed to the client in real-time as chunks arrive.
3. After streaming completes, CloudWatch log retrieval also runs via `asyncio.to_thread()`. Log retrieval now paginates via nextToken.

## Latency Measurement

Cold-start latency is computed automatically during the invoke flow:

1. `client_invoke_time` is recorded before the AWS API call.
2. After streaming completes, `client_done_time` is recorded and `client_duration_ms` is computed.
3. CloudWatch logs are queried for the "Agent invoked - Start time:" pattern.
4. `agent_start_time` is parsed and `cold_start_latency_ms` is computed. Falls back to the earliest CloudWatch event timestamp when the pattern is not found.
5. All metrics are persisted to SQLite and included in the `session_end` SSE event.

## Agent Deployment

Deploy creates a Strands Agent runtime on AgentCore with background deployment and progressive status updates. The deployment flow includes:

1. **OAuth2 credential provider creation** — MCP server and A2A agent integrations with OAuth2 are provisioned as AgentCore credential providers with exponential backoff retry (4 retries, delays 2s/4s/8s/16s). If a provider already exists (e.g., redeployment), it is automatically updated with the latest configuration. Deployment fails with `credential_creation_failed` status if all retries are exhausted.
2. **IAM role creation** — Execution role provisioning (if creating new role)
3. **Artifact build** — Cross-compiles ARM64 artifact (pip install into target directory, zips, uploads to S3)
4. **Runtime deployment** — Creates AgentCore runtime and endpoint

The `deployment_status` field tracks progression through phases: `creating_credentials`, `creating_iam_role`, `building_artifact`, `deploying_runtime`, `completing_deployment`, `finalizing_endpoint`, `deployed`, `failed`, `deleting`.

Smart status polling: during local build phases (credential provider, IAM role, artifact build), the frontend polls the local database only. Once the runtime deployment begins, the `/api/agents/{agent_id}/status` endpoint queries AWS for runtime and endpoint status.

Model and IAM role are required fields. The deployment supports configurable protocol (HTTP), network mode (PUBLIC), authorizer, and lifecycle settings. Cognito client secrets are stored in Secrets Manager and never persisted in the local database. The deployment automatically sets `OTEL_SERVICE_NAME` to the agent name for AgentCore Observability integration.

Tags are resolved from the tag policy system at deploy time. Deploy-time tags are auto-applied from their default values; build-time tags are resolved from the selected tag profile. Required tags that are missing cause deployment to fail with a 400 error. Resolved tags are applied to all created AWS resources (AgentCore runtimes, endpoints, IAM execution roles, memory resources) and stored locally on Agent and Memory records. For registered agents and imported memories, tags are fetched from AWS via `list_tags_for_resource`; missing required tags are filled with `"missing"`.

Deletion with `cleanup_aws=true` immediately deletes all sessions and invocations for the agent (preventing stale data on admin pages), then initiates background async AWS deletion (endpoint + runtime + MCP and A2A credential providers + Secrets Manager cleanup), marks the agent as DELETING, and returns the updated agent. The frontend polls the status endpoint until AWS confirms deletion (404), then calls the purge endpoint to remove the local record. Credential providers cascade delete when the agent is deleted.

## Alternate LLM Providers

By default, agent model calls go straight to Amazon Bedrock. Agents can instead be deployed with `provider="litellm"` to route model calls through a self-hosted [LiteLLM](https://www.litellm.ai/) proxy. Configure the connection once (Settings page → Models → LiteLLM, or the `LOOM_LITELLM_PROXY_BASE_URL`/`LOOM_LITELLM_DISCOVERY_BASE_URL`/`LOOM_LITELLM_PROXY_API_KEY` env vars as a bootstrap fallback), then each LiteLLM-provider agent gets its own scoped virtual key vended automatically via the proxy's `/key/generate` API — no shared credential is ever stored on an individual agent. Custom agents receive the key via a Secrets Manager secret; harness agents receive it via an AgentCore API key credential provider. See [`backend/SPECIFICATIONS.md` § 16](SPECIFICATIONS.md#16-alternate-llm-providers-litellm-proxy) for the full design (master-key resolution order, virtual key vending, dynamic model catalog merging).

## Authenticated Invocation

Invocations support multiple token sources with priority ordering:

1. **Manual bearer token**: If the invoke request includes a `bearer_token` field, it is used directly.
2. **Credential-based token**: If the invoke request includes a `credential_id`, the backend resolves the credential, fetches the client secret from Secrets Manager (5-minute cache), and exchanges it for an M2M OAuth token.
3. **User login token**: If the agent has an authorizer configured, the user's access token from the `Authorization` header is forwarded directly to AgentCore. This works because the frontend and agent share the same Cognito user pool.
4. **Agent config token**: Falls back to the agent's stored authorizer config for M2M token retrieval.
5. **SigV4 (no token)**: If no token is resolved, the request uses IAM SigV4 authentication.

Group-based invoke restriction: `super-admins` can invoke any agent. Other users can only invoke agents whose `loom:group` tag matches one of their groups. For example, demo users can only invoke agents tagged `loom:group=demo`. The backend checks group-tag permission BEFORE creating the invocation session to prevent orphaned pending sessions. Returns 403 if the user's groups don't match the agent's tag. The backend automatically includes `LOOM_COGNITO_USER_CLIENT_ID` in agent authorizer `allowedClients` on deploy so user tokens are accepted.

## Infrastructure

Backend-specific SAM templates:

| Stack | Template | Description |
|-------|----------|-------------|
| `loom-rds` | `iac/rds.yaml` | RDS PostgreSQL with optional RDS Proxy, multi-AZ, and Secrets Manager |
| `loom-ec2` | `iac/ec2.yaml` | EC2 bastion instance with SSM access for tunneling to RDS |
| `loom-ecs-backend` | `iac/ecs.yaml` | Backend ECS Fargate service (task def, task role, service, auto-scaling) |

The ECS task role includes policies for Bedrock, AgentCore, S3, CloudWatch Logs, IAM PassRole, Secrets Manager, Cognito, and CloudFormation. Notably, the Secrets Manager policy covers both the RDS database secret and `bedrock-agentcore-identity!*` secrets used by OAuth2 credential providers (created/deleted during agent deployment). The CloudWatch Logs policy covers both `/aws/bedrock-agentcore/*` and `/aws/vendedlogs/bedrock-agentcore/*` prefixes. Default task resources are 1 vCPU / 2 GB RAM.

Optional `pLitellmProxyBaseUrl`/`pLitellmDiscoveryBaseUrl`/`pLitellmProxyApiKeySecretArn`/`pLitellmProxyApiKeySecretKmsKeyArn` parameters on the `loom-ecs-backend` stack seed the LiteLLM proxy connection's env-var fallback tier (see Alternate LLM Providers above); when a secret ARN is supplied, the task execution role is granted `secretsmanager:GetSecretValue` on it (and `kms:Decrypt` on its KMS key, if customer-managed). The stack also grants the task role the AgentCore runtime lifecycle actions (`Create`/`Update`/`DeleteAgentRuntime(Endpoint)`), `iam:CreateServiceLinkedRole` for VPC-mode runtimes, and CloudWatch Logs delivery-pipeline permissions needed by `services/observability.py` for vended log routing.

The backend Docker image is built with the repository root as the build context (via `-f backend/Dockerfile ..` from `shared/makefile`) so it can include both `backend/app/` and `agents/strands_agent/` source. The agent source is required by `build_agent_artifact` to package and upload agent code to S3 during deployment.

Deploy with `make rds`, `make ec2`, and `make ecs` from the backend directory. Use `make tunnel` to start an SSM port-forwarding session to the RDS instance.

Cross-cutting infrastructure (S3, ECR, ACM, ALB, ECS cluster) is managed from `shared/makefile` — see root README for deployment commands.

## Makefile Targets

```bash
# Development
make install              # Install dependencies
make test                 # Run test suite
make run                  # Start dev server

# Database operations
make migrate-db           # Migrate SQLite → PostgreSQL
make fix-sequences        # Repair PostgreSQL sequences after migration
make reset-db             # Reset database

# Backend infrastructure (RDS, EC2, ECS)
make rds                  # Deploy RDS PostgreSQL stack
make ec2                  # Deploy EC2 bastion stack
make ecs                  # Deploy backend ECS service (uses git SHA image tag)
make tunnel               # Start SSM tunnel to RDS

# AgentCore credentials
make agentcore.credentials.list       # List OAuth2 credential providers
make agentcore.credentials.delete-all # Delete all credential providers

# AgentCore memory queries
make agentcore.memory.list                  # List all memory resources
make agentcore.memory.get                   # Get a specific memory resource by P_MEMORY_ID
make agentcore.memory.records               # Query LTM records by P_MEMORY_ID and P_MEMORY_ACTOR_ID
make agentcore.memory.records-by-namespace  # List LTM records by P_MEMORY_ID and P_MEMORY_NAMESPACE
make agentcore.memory.extraction-jobs       # List extraction jobs for P_MEMORY_ID
```

## Tests

Unit tests covering all routers, services, and models:

```bash
make test
```

Tests use in-memory SQLite and mock all AWS API calls via `unittest.mock.patch`.
