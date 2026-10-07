# Loom Backend — Specifications

## 1. Technology Stack

| Concern | Choice |
|---------|--------|
| Framework | FastAPI |
| Server | Uvicorn (local dev) |
| ORM | SQLAlchemy (SQLite for local dev, PostgreSQL for cloud) |
| AWS SDK | boto3 |
| Python version | 3.11+ (3.13 for ARM64 runtime deployment) |
| Dependency manager | uv |
| Streaming | SSE via `StreamingResponse` |

---

## 2. Configuration

All runtime configuration is injected via environment variables sourced from `etc/environment.sh`:

| Variable | Description | Default |
|----------|-------------|---------|
| `LOOM_DATABASE_URL` | SQLAlchemy database URL (SQLite or PostgreSQL) | `sqlite:///./loom.db` |
| `BACKEND_PORT` | Port for uvicorn | `8000` |
| `FRONTEND_PORT` | Port for Vite dev server (CORS) | `5173` |
| `LOG_LEVEL` | Backend log level | `info` |
| `LOOM_SESSION_IDLE_TIMEOUT_SECONDS` | Idle timeout for session liveness detection | `300` |
| `LOOM_SESSION_MAX_LIFETIME_SECONDS` | Maximum session lifetime | `3600` |
| `AWS_REGION` | AWS region for deployments | `us-east-1` |
| `LOOM_ARTIFACT_BUCKET` | S3 bucket for agent deployment artifacts | — |
| `MEMORY_NAME` | Default memory resource name | `loom_memory` |
| `MEMORY_EVENT_EXPIRY_DURATION` | Default memory event expiry in days | `30` |
| `LOOM_COGNITO_USER_POOL_ID` | Cognito User Pool ID for user authentication | — |
| `LOOM_COGNITO_REGION` | Region of the Cognito pool | `AWS_REGION` |
| `LOOM_COGNITO_USER_CLIENT_ID` | Cognito user app client ID (auto-included in agent authorizer `allowedClients` on deploy) | — |
| `LOOM_ALLOWED_ORIGINS` | Comma-separated additional CORS origins for deployed environments | — |
| `LOOM_LITELLM_PROXY_BASE_URL` | Default Agent Base URL for the LiteLLM proxy (what deployed agents/harnesses call at runtime); seeds the Settings page on first load, empty disables the LiteLLM provider | — |
| `LOOM_LITELLM_DISCOVERY_BASE_URL` | Default Discovery Base URL the backend itself uses for `/model/info`, `/key/generate`, `/key/delete`; falls back to `LOOM_LITELLM_PROXY_BASE_URL` when unset | — |
| `LOOM_LITELLM_PROXY_API_KEY` | Default LiteLLM proxy master key; a Settings-page save always overrides this | — |

AWS credentials use the standard boto3 credential chain (environment variables, AWS profile, instance metadata).

---

## 3. Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── db.py                # SQLAlchemy engine, session factory, init_db
│   ├── models/
│   │   ├── __init__.py      # Re-exports all models
│   │   ├── agent.py         # Agent ORM model
│   │   ├── config_entry.py  # ConfigEntry ORM model (agent key-value configuration)
│   │   ├── session.py       # InvocationSession ORM model
│   │   ├── invocation.py    # Invocation ORM model
│   │   ├── managed_role.py  # ManagedRole ORM model (IAM roles)
│   │   ├── authorizer_config.py    # AuthorizerConfig ORM model
│   │   ├── authorizer_credential.py # AuthorizerCredential ORM model
│   │   ├── permission_request.py   # PermissionRequest ORM model
│   │   ├── memory.py        # Memory ORM model (AgentCore Memory resources)
│   │   ├── mcp.py           # MCP models: McpServer, McpTool, McpServerAccess
│   │   ├── a2a.py           # A2A models: A2aAgent, A2aAgentSkill, A2aAgentAccess
│   │   ├── tag_policy.py    # TagPolicy ORM model (configurable resource tagging)
│   │   ├── tag_profile.py   # TagProfile ORM model (named tag presets)
│   │   ├── site_setting.py    # SiteSetting ORM model (configurable site-wide settings)
│   │   └── audit.py         # Audit ORM models: AuditLogin, AuditAction, AuditPageView
│   ├── dependencies/
│   │   ├── __init__.py
│   │   └── auth.py          # Auth dependencies (get_current_user, require_scopes, UserInfo)
│   ├── routers/
│   │   ├── auth.py          # Authentication config endpoint (GET /api/auth/config)
│   │   ├── agents.py        # Agent CRUD + ARN parsing + log group derivation + tag resolution
│   │   ├── a2a.py           # A2A agent CRUD, Agent Card, skills, access control
│   │   ├── settings.py      # Settings endpoints (tag policy CRUD, tag profile CRUD)
│   │   ├── costs.py          # Cost dashboard: estimated costs + actuals from CloudWatch usage logs
│   │   ├── traces.py        # Trace retrieval: OTEL log parsing for trace summaries and span detail
│   │   ├── evaluations.py   # Evaluations: test case CRUD, on-demand scoring runs, plus read-only AgentCore sources/per-trace scores
│   │   ├── invocations.py   # SSE streaming invoke + session/invocation queries
│   │   ├── logs.py          # CloudWatch log browsing with pagination + session log retrieval via stream-name matching
│   │   ├── memories.py      # Memory resource CRUD + strategy mapping
│   │   ├── mcp.py           # MCP server CRUD, tools, access control
│   │   ├── security.py      # Security admin: roles, authorizers, credentials, permissions
│   │   ├── admin.py         # Admin audit API: login/action/pageview tracking, session aggregation, summary
│   │   └── utils.py         # Shared router utilities (get_agent_or_404)
│   └── services/
│       ├── agentcore.py     # Bedrock AgentCore API wrapper
│       ├── a2a.py           # A2A Agent Card fetching, parsing, connection test
│       ├── cloudwatch.py    # CloudWatch log retrieval and parsing
│       ├── otel.py          # OTEL log parsing: fetch events from otel-rt-logs, parse traces and spans
│       ├── observability.py # CloudWatch vended log delivery configuration (USAGE_LOGS, APPLICATION_LOGS)
│       ├── cognito.py       # Cognito OAuth2 token retrieval (client credentials grant)
│       ├── credential.py    # AgentCore credential provider management
│       ├── deployment.py    # Agent artifact build, runtime CRUD, secret detection
│       ├── harness.py       # AgentCore Harness API: create, get, delete, invoke stream
│       ├── iam.py           # IAM role creation/deletion, Cognito pool listing
│       ├── jwt_validator.py # JWT validation against Cognito JWKS (with caching)
│       ├── latency.py       # Latency calculation helpers
│       ├── mcp.py           # MCP server connection test and tool discovery stubs
│       ├── memory.py        # Bedrock AgentCore Memory API wrapper
│       ├── secrets.py       # AWS Secrets Manager wrapper with in-memory caching
│       ├── tokens.py        # Bedrock CountTokens API with provider guard (Anthropic/Meta)
│       └── usage_poller.py  # Background poller: updates estimated costs with actual USAGE_LOGS data
├── scripts/
│   ├── stream.py            # SSE streaming client for CLI invocations (httpx)
│   ├── migrate_sqlite_to_postgres.py  # CLI utility to migrate SQLite data to PostgreSQL
│   ├── fix_sequences.py     # PostgreSQL sequence auto-repair after migration
│   ├── reset_db.py          # Database reset utility
│   ├── query_memory_records.py  # Query LTM records by actor ID (resolves strategy namespaces)
│   └── list_memory_records.py   # List LTM records by memory ID and namespace
├── tests/
│   ├── test_agentcore.py    # AgentCore service tests
│   ├── test_agents.py       # Agent router tests
│   ├── test_agents_deploy.py # Deployment-specific tests
│   ├── test_a2a.py          # A2A agent CRUD, Agent Card, skills, access tests
│   ├── test_cloudwatch.py   # CloudWatch service tests
│   ├── test_iam.py          # IAM service tests
│   ├── test_invocations.py  # Invocation router tests
│   ├── test_latency.py      # Latency computation tests
│   ├── test_logs.py         # Logs router tests
│   ├── test_memories.py     # Memory resource tests
│   ├── test_security.py     # Security router tests (roles, authorizers)
│   ├── test_mcp.py          # MCP server CRUD, tools, access control tests
│   ├── test_scopes.py       # Scope enforcement and GROUP_SCOPES mapping tests
│   ├── test_tags.py         # Tag policy, tag profile, and tag enforcement tests
│   ├── test_traces.py       # Trace router + OTEL parsing tests (12 tests)
│   ├── test_harness.py      # AgentCore Harness tests (21 tests: deploy CRUD, MCP integration, built-in tools, model params, status, config, service module)
│   ├── test_model_selection.py  # Runtime model selection tests (12 tests: allowed_model_ids, invoke validation, PATCH)
│   ├── test_admin_audit.py  # Admin audit router tests (14 tests: login, action, pageview, sessions, summary)
│   └── test_integration_info.py  # External integration info tests (10 tests: SigV4, OAuth2, protocols, qualifiers, network modes)
├── etc/
│   ├── environment.sh           # Sources account-specific file + shared outputs
│   ├── environment.sh.example   # Example environment configuration template
│   ├── models.json              # Supported model catalog (model_id, display_name, group, pricing, endpoints, apis) — generated, see scripts/refresh_models_json.py
│   ├── bedrock_model_catalog.json # Curated superset of known Bedrock models (adds launch_date; source of truth for models.json)
│   └── runtime_pricing.json     # AgentCore Runtime pricing constants (CPU, memory, defaults)
├── iac/
│   ├── rds.yaml                 # RDS PostgreSQL with optional RDS Proxy
│   ├── ec2.yaml                 # EC2 bastion for SSM tunnel to RDS
│   └── ecs.yaml                 # Backend ECS Fargate service (task def, task role, service, auto-scaling)
├── .dockerignore                # Excludes .env, .venv, __pycache__, tests, etc.
├── Dockerfile                   # Backend container image (Python 3.13 slim + uvicorn + agent source)
├── makefile
├── pyproject.toml
└── requirements.txt
```

---

## 4. Database Backend

### Supported Backends

Loom supports two database backends selected via `LOOM_DATABASE_URL`:

| Backend | URL Format | Use Case |
|---------|-----------|----------|
| SQLite | `sqlite:///./loom.db` | Local development and single-instance deployments |
| PostgreSQL | `postgresql+psycopg2://user:pass@host:5432/loom` | Cloud deployments with load balancing across multiple containers |

The backend is designed for transparent compatibility — no changes to application code or the frontend are required when switching backends. SQLAlchemy abstracts all database interactions.

### Dialect-Aware Engine Configuration

`backend/app/db.py` detects the dialect from `LOOM_DATABASE_URL` at startup:

- **SQLite**: sets `connect_args={"check_same_thread": False}` and registers a `PRAGMA foreign_keys=ON` connection hook.
- **PostgreSQL**: omits both (handled natively by PostgreSQL).

### Schema Migrations (`_migrate_add_columns`)

The `_migrate_add_columns` helper adds missing columns to existing tables at startup (SQLAlchemy's `create_all` does not alter existing tables). It is dialect-aware:

- **SQLite**: `ALTER TABLE {table} ADD COLUMN {column} {type}`
- **PostgreSQL**: `ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {pg_type}`
  - `DATETIME` → `TIMESTAMP`
  - `REAL` → `DOUBLE PRECISION`

### SQLite-to-PostgreSQL Migration

`backend/scripts/migrate_sqlite_to_postgres.py` migrates all data from a source database to a destination database:

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --source sqlite:///./loom.db \
  --dest postgresql+psycopg2://user:pass@host:5432/loom [--skip-existing]
```

- Discovers all tables at runtime via SQLAlchemy reflection (no hardcoded table names).
- Copies tables in foreign-key dependency order using Kahn's topological sort.
- `--skip-existing`: skips tables in the destination that already contain data.
- Per-table error handling: logs failures and continues with remaining tables.
- Also available as `make migrate-db` (uses `$LOOM_DATABASE_URL` as destination).

### PostgreSQL Dependency

`psycopg2-binary` is required for PostgreSQL connections. Install it with:

```bash
uv pip install ".[postgres]"
```

---

## 5. Database Schema

### `agents` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `arn` | TEXT UNIQUE NOT NULL | AgentCore Runtime ARN |
| `runtime_id` | TEXT NOT NULL | Extracted from ARN |
| `name` | TEXT | Human-readable name (from AgentCore describe response) |
| `status` | TEXT | Runtime status (e.g., `READY`, `CREATING`) |
| `region` | TEXT NOT NULL | Extracted from ARN |
| `account_id` | TEXT NOT NULL | Extracted from ARN |
| `log_group` | TEXT | Derived: `/aws/bedrock-agentcore/runtimes/{runtime_id}-{qualifier}` |
| `available_qualifiers` | TEXT | JSON array of endpoint names (e.g., `["DEFAULT"]`) |
| `raw_metadata` | TEXT | Full JSON from AgentCore describe API |
| `source` | TEXT | `register`, `deploy`, or `harness` |
| `deployment_status` | TEXT | `initializing`, `creating_credentials`, `creating_role`, `building_artifact`, `creating_ci_resource`, `deploying`, `deployed`, `failed`, `removing`, `READY` |
| `execution_role_arn` | TEXT | IAM execution role ARN |
| `config_hash` | TEXT | Configuration hash |
| `endpoint_name` | TEXT | Runtime endpoint name |
| `endpoint_arn` | TEXT | Runtime endpoint ARN |
| `endpoint_status` | TEXT | Endpoint status |
| `protocol` | TEXT | `HTTP`, `MCP`, or `A2A` |
| `network_mode` | TEXT | `PUBLIC` or `VPC` |
| `authorizer_config` | TEXT | JSON: `{type, pool_id, discovery_url, allowed_clients, allowed_scopes}` |
| `tags` | TEXT | JSON dict of resolved tags applied to this agent's AWS resources |
| `allowed_model_ids` | TEXT | JSON array of model IDs the agent is allowed to use at invoke time (defaults to `[model_id]`) |
| `harness_id` | VARCHAR | Harness ID for managed agent deployments (nullable, set when `source="harness"`) |
| `code_interpreter_id` | TEXT | Custom Code Interpreter resource ID (nullable, set when a custom CI resource is created on deploy) |
| `agent_framework` | VARCHAR | Custom-code agent framework: `strands` (default) or `adk`. Only meaningful when `source="deploy"`. |
| `registered_at` | DATETIME | Timestamp of local registration |
| `deployed_at` | DATETIME | Deployment timestamp |
| `last_refreshed_at` | DATETIME | Last time metadata was fetched from AWS |

**Relationships:**
- `credential_providers` — One-to-many relationship with credential providers created for MCP OAuth2 integrations. Cascade-deleted when agent is deleted.

### `agent_config_entries` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `agent_id` | INTEGER FK → agents.id (CASCADE delete) | Associated agent |
| `key` | TEXT NOT NULL | Configuration key |
| `value` | TEXT | Plaintext for non-secrets, ARN for secrets |
| `is_secret` | BOOLEAN | Whether value references a secret |
| `source` | TEXT | `env_var`, `secrets_manager`, `s3` |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

**Constraints:** UNIQUE on (`agent_id`, `key`).

### `managed_roles` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `role_name` | TEXT NOT NULL | IAM role name |
| `role_arn` | TEXT UNIQUE NOT NULL | IAM role ARN |
| `description` | TEXT | Role description |
| `policy_document` | TEXT | JSON policy document |
| `tags` | TEXT | JSON dict of tags fetched from AWS IAM on import |
| `role_type` | TEXT DEFAULT 'agent' | Role type: `"agent"` or `"code_interpreter"` |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

### `authorizer_configs` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `name` | TEXT UNIQUE NOT NULL | Authorizer config name |
| `authorizer_type` | TEXT NOT NULL | e.g., `cognito` |
| `pool_id` | TEXT | Cognito user pool ID |
| `discovery_url` | TEXT | OIDC discovery URL |
| `allowed_clients` | TEXT | JSON array of allowed client IDs |
| `allowed_scopes` | TEXT | JSON array of allowed OAuth scopes |
| `client_id` | TEXT | Default client ID |
| `client_secret_arn` | TEXT | Secrets Manager ARN for default client secret |
| `tags` | TEXT | JSON dict of tags |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

### `authorizer_credentials` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `authorizer_config_id` | INTEGER FK → authorizer_configs.id (CASCADE delete) | Associated authorizer |
| `label` | TEXT NOT NULL | Human-readable credential label |
| `client_id` | TEXT NOT NULL | OAuth client ID |
| `client_secret_arn` | TEXT NOT NULL | Secrets Manager ARN for client secret |
| `created_at` | DATETIME | Creation timestamp |

### `permission_requests` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `managed_role_id` | INTEGER FK → managed_roles.id | Target role |
| `requested_actions` | TEXT | JSON array of IAM actions |
| `requested_resources` | TEXT | JSON array of IAM resources |
| `justification` | TEXT | Request justification |
| `status` | TEXT NOT NULL | `pending`, `approved`, `denied` |
| `reviewer_notes` | TEXT | Reviewer notes |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

### `tag_policies` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `key` | TEXT UNIQUE NOT NULL | Tag key name (e.g., `loom:application`, `cost-center`) |
| `default_value` | TEXT | Optional default value |
| `source` | TEXT (deprecated) | Legacy column, kept for DB compatibility. Not used in API or UI. |
| `required` | BOOLEAN NOT NULL | Whether this tag must be present on all resources |
| `show_on_card` | BOOLEAN NOT NULL | Whether to display on agent cards in the catalog |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

**Computed designation** (not stored, derived from key):
- `platform:required` — keys starting with `loom:`. Required, read-only in UI.
- `custom:optional` — all other keys. Optional, editable/deletable in UI.

**Default seed data** (created on first startup):

| Key | Designation | Default Value | Required | Show on Card |
|-----|-------------|---------------|----------|--------------|
| `loom:application` | platform:required | — | Yes | Yes |
| `loom:group` | platform:required | — | Yes | Yes |
| `loom:owner` | platform:required | — | Yes | Yes |

### `tag_profiles` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `name` | TEXT UNIQUE NOT NULL | Profile name (e.g., "Team Alpha - Production") |
| `tags` | TEXT NOT NULL | JSON dict of tag key-value pairs |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

Tag profiles are named presets of tag values that satisfy required tag policies. When a profile is selected during deployment, its tag values are merged with policy defaults and applied to all created AWS resources. Tag values are limited to 128 characters.

### `mcp_servers` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `name` | TEXT NOT NULL | Display name for the MCP server |
| `description` | TEXT | Human-readable description |
| `endpoint_url` | TEXT NOT NULL | MCP server SSE or Streamable HTTP endpoint URL |
| `transport_type` | TEXT NOT NULL | `sse` or `streamable_http` |
| `status` | TEXT NOT NULL | `active`, `inactive`, `error` |
| `auth_type` | TEXT NOT NULL | `none` or `oauth2` |
| `oauth2_well_known_url` | TEXT | OAuth2 `.well-known` URL (required when auth_type is `oauth2`) |
| `oauth2_client_id` | TEXT | OAuth2 client ID (required when auth_type is `oauth2`) |
| `oauth2_client_secret` | TEXT | OAuth2 client secret (write-only, never returned in GET responses) |
| `oauth2_scopes` | TEXT | Space-separated OAuth2 scopes |
| `delegation_mode` | TEXT NOT NULL | `m2m` (machine-to-machine) or `obo` (on-behalf-of token exchange). Default `m2m`. |
| `obo_grant_type` | TEXT | `JWT_AUTHORIZATION_GRANT` or `TOKEN_EXCHANGE`. Required when delegation_mode is `obo`. |
| `oauth2_audience` | TEXT | Token exchange audience (required for Okta custom authorization servers) |
| `api_key_header_name` | TEXT | HTTP header name for API key auth (e.g. `x-api-key`, `Authorization`) (nullable) |
| `has_admin_api_key` | TEXT | `"true"` or `"false"` — whether an admin API key is stored in Secrets Manager (nullable) |
| `created_at` | DATETIME | Creation timestamp |
| `registry_record_id` | TEXT | AWS Agent Registry record ID (nullable) |
| `registry_status` | TEXT | Registry lifecycle status: DRAFT, PENDING_APPROVAL, APPROVED, REJECTED, DEPRECATED (nullable) |
| `updated_at` | DATETIME | Last update timestamp |

### `mcp_tools` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `server_id` | INTEGER FK → mcp_servers.id (CASCADE delete) | Associated MCP server |
| `tool_name` | TEXT NOT NULL | Tool name as reported by the MCP server |
| `description` | TEXT | Tool description |
| `input_schema` | TEXT | JSON Schema for tool input parameters |
| `last_refreshed_at` | DATETIME | When this tool was last synced from the server |

### `mcp_server_access` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `server_id` | INTEGER FK → mcp_servers.id (CASCADE delete) | Associated MCP server |
| `persona_id` | INTEGER | Reference to agent (persona) ID |
| `access_level` | TEXT NOT NULL | `all_tools` or `selected_tools` |
| `allowed_tool_names` | TEXT | JSON list of allowed tool names (when access_level is `selected_tools`) |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

A persona with no access rule for a given MCP server has no access (deny by default).

### `memories` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `name` | TEXT NOT NULL | Memory resource name |
| `description` | TEXT | Optional description |
| `arn` | TEXT | ARN returned after creation |
| `memory_id` | TEXT | AWS memory resource ID |
| `region` | TEXT NOT NULL | AWS region |
| `account_id` | TEXT NOT NULL | AWS account ID |
| `status` | TEXT NOT NULL | Resource status (`CREATING`, `ACTIVE`, `FAILED`, `DELETING`) |
| `event_expiry_duration` | INTEGER NOT NULL | Duration in days before memory events expire |
| `memory_execution_role_arn` | TEXT | IAM role ARN for the memory resource |
| `encryption_key_arn` | TEXT | KMS key ARN for encryption |
| `strategies_config` | TEXT | JSON: memory strategies as submitted |
| `strategies_response` | TEXT | JSON: strategies with IDs and statuses from AWS |
| `tags` | TEXT | JSON dict of resolved tags applied to this memory's AWS resources |
| `failure_reason` | TEXT | Failure reason if status is `FAILED` |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

### `invocation_sessions` table

| Column | Type | Description |
|--------|------|-------------|
| `agent_id` | INTEGER FK → agents.id | Associated agent |
| `session_id` | TEXT PK | UUID used as `runtimeSessionId` in the invoke call (primary key) |
| `qualifier` | TEXT NOT NULL | Endpoint qualifier used (e.g., `DEFAULT`) |
| `status` | TEXT NOT NULL | `pending`, `streaming`, `complete`, `error` |
| `created_at` | DATETIME NOT NULL | Session creation timestamp |

### `invocations` table

Each session contains one or more invocations. Timing measurements and latency data are stored per-invocation.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `session_id` | TEXT FK → invocation_sessions.session_id | Parent session |
| `invocation_id` | TEXT UNIQUE NOT NULL | UUID identifying this specific invocation |
| `client_invoke_time` | REAL | Unix timestamp (seconds) recorded immediately before the invoke call |
| `client_done_time` | REAL | Unix timestamp when the stream completes |
| `agent_start_time` | REAL | Unix timestamp parsed from "Start time:" in CloudWatch logs |
| `cold_start_latency_ms` | REAL | `(agent_start_time - client_invoke_time) * 1000` |
| `client_duration_ms` | REAL | `(client_done_time - client_invoke_time) * 1000` |
| `input_tokens` | INTEGER | Estimated input token count (4 chars/token heuristic) |
| `output_tokens` | INTEGER | Estimated output token count (4 chars/token heuristic) |
| `estimated_cost` | REAL | Estimated cost based on model pricing |
| `compute_cost` | REAL | Deprecated; use compute_cpu_cost + compute_memory_cost |
| `compute_cpu_cost` | REAL | Runtime CPU cost (recomputed at view time from client_duration_ms) |
| `compute_memory_cost` | REAL | Runtime memory cost (recomputed at view time from client_duration_ms) |
| `idle_timeout_cost` | REAL | Total idle timeout cost (memory only) |
| `idle_cpu_cost` | REAL | Idle CPU cost (always 0; kept for schema compatibility) |
| `idle_memory_cost` | REAL | Idle memory cost (recomputed from session gaps using current pricing) |
| `memory_retrievals` | INTEGER | Number of memory retrievals |
| `memory_events_sent` | INTEGER | Number of memory events sent |
| `memory_estimated_cost` | REAL | Memory feature estimated cost |
| `stm_cost` | REAL | Short-term memory cost |
| `ltm_cost` | REAL | Long-term memory cost |
| `cost_source` | TEXT | "estimated" (from invoke duration) or "usage_logs" (from CloudWatch) |
| `status` | TEXT NOT NULL | `pending`, `streaming`, `complete`, `error` |
| `error_message` | TEXT | Error detail if status is `error` |
| `created_at` | DATETIME NOT NULL | Invocation creation timestamp |

**Computed fields (not stored in the database):**
- `active_session_count` — returned on agent responses. Counts sessions with at least one invocation whose last activity is within `LOOM_SESSION_IDLE_TIMEOUT_SECONDS` of the current time.
- `live_status` — returned on session responses. Computed from the session's stored `status` and the timestamp of its most recent invocation:
  - `"pending"` / `"streaming"` → returned as-is
  - `"complete"` / `"error"` → `"active"` if last activity is within the idle timeout, otherwise `"expired"`

**Design decisions:**
- Prompt text, thinking text, and response text are stored per invocation (`prompt_text`, `thinking_text`, `response_text` columns on the `invocations` table).
- The `Agent` model retains an integer auto-incrementing PK. The `arn` and `runtime_id` columns serve as natural identifiers when interacting with AWS.

### `site_settings` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `key` | TEXT UNIQUE NOT NULL | Setting key (e.g., `cpu_io_wait_discount`) |
| `value` | TEXT NOT NULL | Setting value |
| `updated_at` | DATETIME | Last update timestamp |

### `audit_login` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `user_id` | TEXT NOT NULL | Cognito username (e.g. `admin`, `demo-user`) |
| `browser_session_id` | TEXT NOT NULL | Client-generated UUID identifying a unique browser session |
| `logged_in_at` | DATETIME NOT NULL | UTC timestamp of login (server default) |

### `audit_action` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `user_id` | TEXT NOT NULL | Cognito username |
| `browser_session_id` | TEXT NOT NULL | Browser session UUID |
| `action_category` | TEXT NOT NULL | Resource category: `agent`, `memory`, `security`, `tagging`, `mcp`, `a2a` |
| `action_type` | TEXT NOT NULL | Action name: `deploy`, `invoke`, `import`, `create`, `edit`, `delete`, `add_role`, `approve_request`, `deny_request`, `test_connection`, `invoke_tool`, `update_permissions`, etc. |
| `resource_name` | TEXT | Name or identifier of the affected resource (nullable) |
| `performed_at` | DATETIME NOT NULL | UTC timestamp of the action (server default) |

### `audit_page_view` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal ID |
| `user_id` | TEXT NOT NULL | Cognito username |
| `browser_session_id` | TEXT NOT NULL | Browser session UUID |
| `page_name` | TEXT NOT NULL | Persona/page visited: `catalog`, `agents`, `memory`, `security`, `tagging`, `mcp`, `a2a`, `costs`, `settings`, `admin` |
| `entered_at` | DATETIME NOT NULL | UTC timestamp when the user navigated to this page |
| `duration_seconds` | INTEGER | Time spent on the page in seconds (nullable; null if tab was closed without navigating away) |

---

## 5. ARN Parsing

Runtime ARN format: `arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{runtime_id}`

From the ARN, the backend automatically derives:
- `region` → extracted from ARN segment 3
- `account_id` → extracted from ARN segment 4
- `runtime_id` → extracted from ARN resource path

Log group format (per qualifier): `/aws/bedrock-agentcore/runtimes/{runtime_id}-{qualifier}`

---

## 6. API Endpoints

All endpoints are prefixed `/api`.

### Authentication

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/auth/config` | Return Cognito pool ID and region for frontend auth flow. |
| `GET` | `/api/auth/me` | Return the authenticated user's identity (username, sub, groups). Used for session ownership resolution. |

The `/api/auth/config` endpoint returns only the pool ID and region. The user client ID is configured on the frontend via the `VITE_COGNITO_USER_CLIENT_ID` environment variable. No client secrets are exposed.

### Agent Registration and Deployment

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/agents` | Create agent (register by ARN or deploy new runtime). |
| `GET` | `/api/agents` | List all registered agents. |
| `GET` | `/api/agents/{agent_id}` | Get metadata for a specific registered agent. |
| `DELETE` | `/api/agents/{agent_id}?cleanup_aws=true` | Remove agent; optionally initiate async AWS deletion (returns DELETING status). |
| `DELETE` | `/api/agents/{agent_id}/purge` | Remove agent from local DB only (no AWS call). Used after confirming AWS deletion is complete. |
| `POST` | `/api/agents/{agent_id}/refresh` | Re-fetch metadata from AgentCore and update the local record. |
| `POST` | `/api/agents/{agent_id}/redeploy` | Redeploy an agent with current config. |
| `PUT` | `/api/agents/{agent_id}/redeploy-harness` | Update and redeploy a harness agent with new configuration (UpdateHarness API). |
| `GET` | `/api/agents/roles` | List IAM roles suitable for AgentCore. |
| `GET` | `/api/agents/cognito-pools` | List Cognito user pools. |
| `GET` | `/api/agents/models` | List supported foundation models (with display name and group). Bedrock-only — the merged static/live Bedrock catalog from `model_catalog.get_bedrock_models()`, filtered by `enabled_model_ids`. |
| `GET` | `/api/agents/models/litellm` | List models reported by the configured LiteLLM proxy's live catalog (`model_catalog.get_litellm_models_live()`). Fetched on demand by the frontend when the LiteLLM provider is selected, not eagerly alongside `/models`. Returns an empty list if no proxy is configured/reachable. |
| `GET` | `/api/agents/providers` | List the supported LLM provider registry (`backend/etc/providers.json`), each entry annotated with a live `available: bool` (LiteLLM is available only when a proxy connection is configured and enabled). |
| `GET` | `/api/agents/models/pricing` | List models with pricing metadata (input/output price per 1K tokens). |
| `POST` | `/api/agents/models/invoke-test` | Run a one-off serverless inference call against any catalog `model_id`, on whichever endpoint (`bedrock-runtime` or `bedrock-mantle`) it supports (`bedrock_invocation.invoke_model()`) — validates a model works before wiring it into an agent or harness (#64 R1). |
| `GET` | `/api/agents/defaults` | Get configurable defaults (idle timeout, max lifetime). |
| `PATCH` | `/api/agents/{agent_id}` | Update editable agent fields (description, model_id, allowed_model_ids). Description changes propagated to AgentCore. |
| `PUT` | `/api/agents/{agent_id}/config` | Update agent configuration entries. |
| `GET` | `/api/agents/{agent_id}/config` | Get agent configuration entries. |
| `GET` | `/api/agents/{agent_id}/integration` | Get external integration info (endpoints, auth, code snippets). Only for READY agents. |

**`DELETE /api/agents/{agent_id}` behavior:**
- When `cleanup_aws=false` or agent has no `runtime_id`: immediately deletes from local DB, returns the `AgentResponse` with HTTP 200.
- When `cleanup_aws=true` and agent has a `runtime_id`: immediately deletes all sessions and invocations for the agent from the local database (preventing stale session data from appearing on admin pages), then initiates async deletion via `BackgroundTasks`. The background task:
  1. Deletes non-DEFAULT runtime endpoints (AWS automatically handles DEFAULT endpoints).
  2. Deletes the runtime.
  3. Cleans up Secrets Manager secrets.
  4. Parses `AGENT_CONFIG_JSON` to extract credential provider names from both `integrations.mcp_servers[].auth.credential_provider_name` and `integrations.a2a_agents[].auth.credential_provider_name`.
  5. Deletes each credential provider via `delete_credential_provider`.
  6. Polls runtime deletion status (5-second intervals, 30 max attempts).
  7. Purges the agent DB record using `db.flush()` before `db.commit()` for reliable SQLite writes.
- Returns the `AgentResponse` with `status="DELETING"`, `deployment_status="removing"`, HTTP 200. The frontend polls via the status endpoint and uses purge to clean up locally after AWS confirms deletion (404).

**`DELETE /api/agents/{agent_id}/purge`:**
Removes the agent record from the local database without any AWS API call. Used by the frontend after confirming that AWS deletion is complete (404 on status poll). Returns 204 No Content.

**`GET /api/agents/{agent_id}` status polling behavior:**
- **Smart polling during local phases**: When `deployment_status` is `initializing`, `creating_credentials`, `creating_role`, or `building_artifact`, the endpoint returns DB state immediately without making AWS API calls.
- **AWS polling after deployment**: Once `deployment_status` reaches `deployed`, the endpoint queries AWS for current runtime state via `get_agent_runtime`.
- **Permanent error detection**: If AWS returns `AccessDeniedException` or `UnauthorizedException`, the backend marks the agent as `deployment_status="failed"` to stop frontend polling.

**`POST /api/agents` register request body:**
```json
{
  "arn": "arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{runtime_id}",
  "model_id": "us.anthropic.claude-sonnet-4-6"
}
```

The `model_id` field is optional on registration and stored as an `AGENT_CONFIG_JSON` config entry.

**`POST /api/agents` deploy request body:**

| Field | Description |
|-------|-------------|
| `source` | `register`, `deploy`, or `harness` |
| `name` | Agent name |
| `description` | Agent description |
| `agent_description` | Description passed to the agent prompt |
| `behavioral_guidelines` | Behavioral guidelines for the agent |
| `output_expectations` | Expected output format/behavior |
| `model_id` | Foundation model identifier (required) |
| `allowed_model_ids` | Optional subset of model IDs the user may select at invoke time (defaults to `[model_id]`) |
| `provider` | LLM provider: `"bedrock"` (default) or `"litellm"`. Non-bedrock providers are only supported for `source="deploy"` and `source="harness"`, validated against `SUPPORTED_PROVIDER_IDS` from `backend/etc/providers.json`. |
| `agent_framework` | Custom-code agent framework: `"strands"` (default) or `"adk"`. Only used when `source="deploy"`; selects the agent blueprint (`agents/strands_agent/` or `agents/adk_agent/`) used to build the deployment artifact. |
| `base_url` | Custom/private endpoint base URL for OpenAI-compatible providers (unused for `litellm`, which resolves its base URL from the configured proxy connection instead). |
| `api_key` | Provider API key. Required for non-bedrock, non-litellm providers; ignored for `litellm`, which vends a scoped virtual key automatically (see `services/litellm.py`). |
| `role_arn` | IAM execution role ARN (required) |
| `protocol` | `HTTP`, `MCP`, or `A2A` |
| `network_mode` | `PUBLIC` or `VPC` |
| `idle_timeout` | Idle timeout in seconds |
| `max_lifetime` | Maximum lifetime in seconds |
| `authorizer_type` | Authorizer type (e.g., Cognito) |
| `authorizer_pool_id` | Cognito user pool ID |
| `authorizer_discovery_url` | OIDC discovery URL |
| `authorizer_allowed_clients` | Allowed client IDs |
| `authorizer_allowed_scopes` | Allowed OAuth scopes |
| `authorizer_client_id` | Client ID for token retrieval |
| `authorizer_client_secret` | Client secret for token retrieval |
| `memory_enabled` | Whether memory is enabled |
| `memory_ids` | Memory resource IDs to integrate (from Memory catalog) |
| `mcp_servers` | MCP server configuration (stored in `AGENT_CONFIG_JSON` as `integrations.mcp_servers`) |
| `a2a_agents` | A2A agent IDs to integrate (from A2A catalog) |
| `tags` | Build-time tag values (e.g., `{"team": "aws", "owner": "heeki"}`) |
| `harness_tools` | Custom tool definitions for harness deployment (optional) |
| `harness_max_iterations` | Maximum iterations for harness agent loop (optional) |
| `harness_timeout_seconds` | Timeout in seconds for harness invocations (optional) |
| `harness_max_tokens` | Maximum tokens for harness model output (optional) |
| `harness_temperature` | Temperature for harness model sampling (optional) |
| `harness_top_p` | Top-p for harness model sampling (optional) |
| `harness_code_interpreter` | Enable built-in code interpreter tool (boolean, default false) |
| `harness_browser` | Enable built-in browser tool (boolean, default false) |

When `source="harness"`, the agent is deployed as a fully managed AgentCore Harness — no artifact build, no credential provider creation. Requires `name`, `model_id`, and `role_arn`. The backend calls `CreateHarness` API, sets `harness_id` on the agent record, and extracts the auto-provisioned runtime from the harness environment. Harness agents are invoked via `InvokeHarness` API (Converse API streaming format translated to existing SSE events) and deleted via `DeleteHarness` API.

The `mcp_servers` configuration is stored in the `AGENT_CONFIG_JSON` config entry under `integrations.mcp_servers` as an array. Each MCP server with OAuth2 authentication includes:
- `auth.credential_provider_name` — Name of the AgentCore credential provider created during deployment, from `credential_provider_name()` (`loom-{agent name}-{agent id}-mcp|a2a-{resource name}`)
- `auth.well_known_endpoint` — OAuth2 discovery URL
- `auth.scopes` — Array of OAuth2 scopes
- `auth.delegation_mode` — `m2m` or `obo` (on-behalf-of token exchange)
- `auth.obo_grant_type` — `TOKEN_EXCHANGE` or `JWT_AUTHORIZATION_GRANT` (when delegation_mode is `obo`)
- `auth.audience` — Token exchange audience (when required by the authorization server)

The `a2a_agents` configuration is stored in the `AGENT_CONFIG_JSON` config entry under `integrations.a2a_agents` as an array. Each A2A agent with OAuth2 authentication includes:
- `auth.credential_provider_name` — Name of the AgentCore credential provider created during deployment, from `credential_provider_name()` (`loom-{agent name}-{agent id}-mcp|a2a-{resource name}`)
- `auth.well_known_endpoint` — OAuth2 discovery URL
- `auth.scopes` — OAuth2 scopes string
- `auth.delegation_mode` — `m2m` or `obo` (on-behalf-of token exchange)
- `auth.obo_grant_type` — `TOKEN_EXCHANGE` or `JWT_AUTHORIZATION_GRANT` (when delegation_mode is `obo`)

Memory resources are stored in `AGENT_CONFIG_JSON` under `integrations.memory.resources` as an array of `{name, memory_id, arn}` objects. `integrations.memory.enabled` is set to `true` when any memory resources are selected.

**`GET /api/agents` response includes:**
- `tags` — resolved tags (profile values + policy defaults) stored on the agent record
- `model_id` — extracted from the agent's `AGENT_CONFIG_JSON` config entry
- `allowed_model_ids` — list of model IDs the agent may use at invoke time. Derived from the `allowed_model_ids` column; defaults to `[model_id]` when not explicitly set.
- `active_session_count` — computed at query time based on `LOOM_SESSION_IDLE_TIMEOUT_SECONDS`
- `authorizer_config` — JSON object with `type`, `name`, `pool_id`, `discovery_url` fields (extracted from AgentCore `customJWTAuthorizer` on register/refresh); `null` when no authorizer is configured

**`GET /api/agents/models` response:**

Returns models filtered by the `enabled_model_ids` site setting. When no models are explicitly enabled, returns the full catalog. Models are loaded from `backend/etc/models.json`.

```json
[
  {"model_id": "us.anthropic.claude-opus-4-6-v1", "display_name": "Claude Opus 4.6", "group": "Anthropic"},
  {"model_id": "us.amazon.nova-pro-v1:0", "display_name": "Nova Pro", "group": "Amazon"}
]
```

**`GET /api/agents/defaults` response:**
```json
{
  "idle_timeout_seconds": 300,
  "max_lifetime_seconds": 3600
}
```

### Tag Policy Management (Settings)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings/tags` | List all tag policies. |
| `POST` | `/api/settings/tags` | Create a new tag policy. |
| `PUT` | `/api/settings/tags/{tag_id}` | Update an existing tag policy. |
| `DELETE` | `/api/settings/tags/{tag_id}` | Delete a tag policy. |

**Tag resolution during deployment:**
- For each tag policy: use user-supplied value (from profile) → fall back to `default_value` → error if required and missing (HTTP 400).
- The deploy request includes a `tags: dict[str, str]` field with values from the selected tag profile.
- Resolved tags are stored on Agent and Memory records and included in API responses.
- For registered agents and imported memories, tags are fetched from AWS via `list_tags_for_resource` and stored locally. Missing required tags are filled with `"missing"`.

### Tag Profile Management (Settings)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings/tag-profiles` | List all tag profiles. |
| `POST` | `/api/settings/tag-profiles` | Create a new tag profile. |
| `PUT` | `/api/settings/tag-profiles/{profile_id}` | Update an existing tag profile. |
| `DELETE` | `/api/settings/tag-profiles/{profile_id}` | Delete a tag profile. |

Tag profiles are named presets of tag key-value pairs. When creating or updating a profile, all required tag policies must have values in the profile's tags.

### Security Administration

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/security/roles` | Create a managed role (import or wizard mode). |
| `GET` | `/api/security/roles` | List managed roles. |
| `GET` | `/api/security/roles/{role_id}` | Get a specific managed role. |
| `PUT` | `/api/security/roles/{role_id}` | Update a managed role. |
| `DELETE` | `/api/security/roles/{role_id}` | Delete a managed role. |
| `GET` | `/api/security/cognito-pools` | List Cognito pools with discovery URLs. |
| `POST` | `/api/security/authorizers` | Create an authorizer config. |
| `GET` | `/api/security/authorizers` | List authorizer configs. |
| `GET` | `/api/security/authorizers/{auth_id}` | Get a specific authorizer config. |
| `PUT` | `/api/security/authorizers/{auth_id}` | Update an authorizer config. |
| `DELETE` | `/api/security/authorizers/{auth_id}` | Delete an authorizer config. |
| `POST` | `/api/security/authorizers/{auth_id}/credentials` | Add a credential to an authorizer. |
| `GET` | `/api/security/authorizers/{auth_id}/credentials` | List credentials for an authorizer. |
| `DELETE` | `/api/security/authorizers/{auth_id}/credentials/{cred_id}` | Delete a credential. |
| `POST` | `/api/security/authorizers/{auth_id}/credentials/{cred_id}/token` | Generate OAuth token from credential. |
| `POST` | `/api/security/permission-requests` | Create a permission request. |
| `GET` | `/api/security/permission-requests` | List permission requests. |
| `PUT` | `/api/security/permission-requests/{req_id}/review` | Approve or deny a permission request. |

**Role import behavior:** When importing a role by ARN, the backend fetches the IAM policy document via `get_role_policy` and IAM tags via `list_role_tags`, storing both on the managed role record. Tags are included in the role response as a JSON dict.

### Memory Resources

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/memories` | Create a new memory resource. |
| `POST` | `/api/memories/import` | Import an existing memory resource by AWS memory ID. |
| `GET` | `/api/memories` | List all memory resources. |
| `GET` | `/api/memories/{memory_id}` | Get a specific memory resource. |
| `POST` | `/api/memories/{memory_id}/refresh` | Refresh memory status from AWS. |
| `DELETE` | `/api/memories/{memory_id}?cleanup_aws=true` | Delete a memory resource; optionally delete from AWS. |
| `DELETE` | `/api/memories/{memory_id}/purge` | Remove from local DB only (no AWS call). |
| `GET` | `/api/memories/{memory_id}/records` | Retrieve stored LTM records for the authenticated user. |
| `GET` | `/api/memories/{memory_id}/export` | Export memory configuration as JSON (name, description, strategies, tags). |

**Naming convention:** Memory names and strategy names must match `[a-zA-Z][a-zA-Z0-9_]{0,47}` — start with a letter, letters/digits/underscores only, max 48 characters. Hyphens are not allowed.

**`POST /api/memories` request body:**
```json
{
  "name": "my_memory",
  "event_expiry_duration": 30,
  "description": "Optional description",
  "memory_execution_role_arn": "arn:aws:iam::...:role/...",
  "encryption_key_arn": "arn:aws:kms:...",
  "memory_strategies": [
    {
      "strategy_type": "semantic",
      "name": "default-semantic",
      "description": "Optional",
      "namespaces": ["ns1"],
      "configuration": {}
    }
  ],
  "tags": {"loom:application": "my-app", "loom:group": "my-team", "loom:owner": "owner@example.com"}
}
```

**`POST /api/memories/import` request body:**
```json
{
  "memory_id": "my_memory-zYcvlyGXsK"
}
```

Fetches the memory details from AWS via `get_memory` and stores them locally. Returns 409 if the memory is already imported.

**`DELETE /api/memories/{memory_id}?cleanup_aws=true`:**
When `cleanup_aws=true` (default), initiates async deletion in AWS and marks status as DELETING. When `cleanup_aws=false`, removes from local DB only. For FAILED memories, always removes locally without AWS call.

**`DELETE /api/memories/{memory_id}/purge`:**
Removes the memory record from the local database without any AWS API call. Used by the frontend after confirming that AWS deletion is complete (404 on refresh). Returns 204 No Content.

**`GET /api/memories/{memory_id}/records`:**
Retrieves stored long-term memory records for the authenticated user within a memory resource. Records are scoped to the requesting user's identity — users cannot access records belonging to other actors.

- **Data plane vs control plane:** `list_memory_records` is a data plane operation on `bedrock-agentcore`, not the control plane `bedrock-agentcore-control` used by other memory CRUD operations.
- **Namespace-based querying:** The data plane API requires a `namespace` parameter (not `actorId`). Each LTM strategy defines a namespace template (e.g. `/strategy/{memoryStrategyId}/actor/{actorId}/`). The service substitutes the strategy ID and actor ID into each template, then queries each namespace. For summary strategies with `{sessionId}` placeholders, the query is truncated at the unresolved placeholder to match all sessions.
- **Tagged union unwrapping:** The `strategies_response` stored from the AWS `get_memory` API uses a tagged union format where each strategy is wrapped in a type key (e.g. `{"userPreferenceMemoryStrategy": {"strategyId": "...", "namespaces": [...]}}`). The service unwraps this format to extract `strategyId` and `namespaces` from the inner dict, falling back to top-level access for pre-unwrapped formats.
- **Actor ID resolution:** Uses `user.username or user.sub or "loom-agent"` — the same fallback chain used on the write side when the agent sends memory events during chat.
- **Content field mapping:** The AWS response contains `memoryRecords[].content` which may be a dict with a `text` key, a plain string, or another structure. The service handles all three cases. Records with empty text are filtered out.
- **Debug logging:** INFO-level logs are emitted at each stage: before the API call (memory_id, actor_id, strategy count), after receiving raw records (count), and after filtering (kept vs filtered counts).
- **Error handling:** On AWS API failure, returns an empty records list with a warning log. The frontend error state is reserved for HTTP errors from the backend.

**Strategy type mapping:**

| `strategy_type` | AWS Parameter Key |
|-----------------|-------------------|
| `semantic` | `semanticMemoryStrategy` |
| `summary` | `summaryMemoryStrategy` |
| `user_preference` | `userPreferenceMemoryStrategy` |
| `episodic` | `episodicMemoryStrategy` |
| `custom` | `customMemoryStrategy` |

**Error mapping:**

| AWS Exception | HTTP Status |
|---------------|-------------|
| `ValidationException` | 400 |
| `ConflictException` | 409 |
| `ResourceNotFoundException` | 404 |
| `ServiceQuotaExceededException` | 429 |
| `AccessDeniedException` | 403 |
| `ThrottledException` | 429 |

### MCP Server Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/mcp/servers` | Register a new MCP server. |
| `GET` | `/api/mcp/servers` | List all registered MCP servers. |
| `GET` | `/api/mcp/servers/{server_id}` | Get details of a specific MCP server. |
| `PUT` | `/api/mcp/servers/{server_id}` | Update an MCP server configuration. |
| `DELETE` | `/api/mcp/servers/{server_id}` | Remove an MCP server (cascades to tools and access rules). |
| `POST` | `/api/mcp/servers/{server_id}/test-connection` | Test MCP server connectivity and OAuth2 token acquisition. |
| `GET` | `/api/mcp/servers/{server_id}/tools` | Get cached tool list for a server. |
| `POST` | `/api/mcp/servers/{server_id}/tools/refresh` | Refresh tool list from the MCP server. |
| `GET` | `/api/mcp/servers/{server_id}/access` | Get access control rules for a server. |
| `PUT` | `/api/mcp/servers/{server_id}/access` | Replace all access control rules for a server. |
| `GET` | `/api/mcp/connectors` | List MCP servers available as connectors with per-user API key status. |
| `PUT` | `/api/mcp/servers/{server_id}/api-key` | Store the user's personal API key in Secrets Manager. |
| `GET` | `/api/mcp/servers/{server_id}/api-key/status` | Check whether the user has a personal API key set. |
| `DELETE` | `/api/mcp/servers/{server_id}/api-key` | Remove the user's personal API key from Secrets Manager. |

**`POST /api/mcp/servers` request body:**
```json
{
  "name": "My MCP Server",
  "description": "Optional description",
  "endpoint_url": "https://example.com/mcp",
  "transport_type": "sse",
  "auth_type": "oauth2",
  "oauth2_well_known_url": "https://auth.example.com/.well-known/openid-configuration",
  "oauth2_client_id": "client-id",
  "oauth2_client_secret": "client-secret",
  "oauth2_scopes": "openid profile"
}
```

When `auth_type` is `oauth2`, `oauth2_well_known_url` and `oauth2_client_id` are required (validated via Pydantic model validator). When `auth_type` is `api_key`, `api_key_header_name` is required.

**Security:** `oauth2_client_secret` is write-only — it is never included in GET responses. The response includes `has_oauth2_secret: bool` instead. API keys are stored in Loom-managed AWS Secrets Manager — admin keys at `loom/mcp/{name}/admin-api-key`, per-user keys at `loom/mcp/{name}/api-key/{user_sub}`. The response includes `has_admin_api_key: bool` instead of the key value.

**API key authentication model:**
- **Admin key:** Used by the Loom backend for test connection, refresh tools, and invoke from admin console. Stored in Secrets Manager on create/update.
- **Per-user key:** Each user supplies their own key via the ChatPage connector UI or API. Required for runtime invocations. Admin key is for admin console operations only — no fallback between them.
- **Header injection:** When `api_key_header_name` is `Authorization`, the key is sent as `Bearer {key}`. For all other headers (e.g. `x-api-key`), the raw key is set directly.

**`GET /api/mcp/connectors` response:**
Returns MCP servers available as connectors with per-user API key status. End-users (`t-user`) see only APPROVED or unregistered servers. Each entry includes `id`, `name`, `description`, `auth_type`, and `has_user_api_key` (whether the current user has a stored API key).

**`PUT /api/mcp/servers/{server_id}/access` request body:**
```json
{
  "rules": [
    {"persona_id": 1, "access_level": "all_tools"},
    {"persona_id": 2, "access_level": "selected_tools", "allowed_tool_names": ["tool_a", "tool_b"]}
  ]
}
```

Replaces all existing access rules for the server. Personas not listed have no access (deny by default).

### A2A Agent Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/a2a/agents` | Register a new A2A agent by base URL (fetches Agent Card). |
| `GET` | `/api/a2a/agents` | List all registered A2A agents. |
| `GET` | `/api/a2a/agents/{agent_id}` | Get details of a specific A2A agent. |
| `PUT` | `/api/a2a/agents/{agent_id}` | Update an A2A agent configuration. |
| `DELETE` | `/api/a2a/agents/{agent_id}` | Remove an A2A agent (cascades to skills and access rules). |
| `POST` | `/api/a2a/agents/{agent_id}/test-connection` | Test A2A agent connectivity (fetches Agent Card with optional OAuth2). |
| `GET` | `/api/a2a/agents/{agent_id}/card` | Get cached raw Agent Card JSON. |
| `POST` | `/api/a2a/agents/{agent_id}/card/refresh` | Re-fetch Agent Card and sync skills. |
| `GET` | `/api/a2a/agents/{agent_id}/skills` | Get cached skill list for an agent. |
| `GET` | `/api/a2a/agents/{agent_id}/access` | Get access control rules for an agent. |
| `PUT` | `/api/a2a/agents/{agent_id}/access` | Replace all access control rules for an agent. |

**`POST /api/a2a/agents` request body:**
```json
{
  "base_url": "https://recipe-agent.example.com",
  "auth_type": "oauth2",
  "oauth2_well_known_url": "https://auth.example.com/.well-known/openid-configuration",
  "oauth2_client_id": "client-id",
  "oauth2_client_secret": "client-secret",
  "oauth2_scopes": "openid profile"
}
```

On registration, the backend fetches the Agent Card from the well-known endpoint. Standard A2A agents use `/.well-known/agent.json`; AgentCore agents try `/.well-known/agent-card.json` first; Salesforce Agentforce agents use `/v1/card`. All agent metadata (name, description, version, capabilities, skills) is populated from the card. If the fetch fails, registration is rejected with a descriptive error.

When `auth_type` is `oauth2`, `oauth2_well_known_url` and `oauth2_client_id` are required (validated via Pydantic model validator).

**Security:** `oauth2_client_secret` is write-only — it is never included in GET responses. The response includes `has_oauth2_secret: bool` instead.

**`PUT /api/a2a/agents/{agent_id}/access` request body:**
```json
{
  "rules": [
    {"persona_id": 1, "access_level": "all_skills"},
    {"persona_id": 2, "access_level": "selected_skills", "allowed_skill_ids": ["find-recipe"]}
  ]
}
```

Replaces all existing access rules for the agent. Personas not listed have no access (deny by default).

### Agent Registry Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/registry/records` | List all registry records. Optional query params: `status` (filter by record status), `descriptor_type` (filter by MCP or A2A). |
| `GET` | `/api/registry/records/{record_id}` | Get full detail for a registry record including descriptors. |
| `POST` | `/api/registry/records` | Create a registry record. Body: `{resource_type: "mcp"|"a2a"|"agent", resource_id: int}` derives the record from a Loom MCP server/A2A agent/agent; `{resource_type: "skill", skill_name, skill_description, skill_license, skill_version, skill_md}` authors a SKILL record directly (no linked Loom resource — see "Skill authoring" below). |
| `PUT` | `/api/registry/records/{record_id}` | Update a registry record by re-building descriptors from the linked Loom resource, or (for a SKILL record, which has none) from re-submitted `skill_name`/`skill_description`/`skill_license`/`skill_version`/`skill_md` fields. |
| `POST` | `/api/registry/records/{record_id}/submit` | Submit a registry record for approval. Updates linked resource status to PENDING_APPROVAL. |
| `POST` | `/api/registry/records/{record_id}/approve` | Approve a registry record. Updates linked resource status to APPROVED. |
| `POST` | `/api/registry/records/{record_id}/reject` | Reject a registry record. Body: `{reason: str}`. Updates linked resource status to REJECTED. |
| `DELETE` | `/api/registry/records/{record_id}` | Delete a registry record and clear the linked resource's registry fields (already worked for SKILL records unmodified, since they have no linked resource to clear). |
| `GET` | `/api/registry/search` | Semantic search over registry records. Query params: `q` (search query), `max_results` (default 10). |

**Record lifecycle:** CREATING → DRAFT → PENDING_APPROVAL → APPROVED | REJECTED (also DEPRECATED)

**Skill authoring (issue #61):** Unlike `mcp`/`a2a`/`agent`, a SKILL record isn't derived from a Loom-owned/deployed resource — its content (name/description/license/metadata/SKILL.md body) is authored directly through `SkillsPage.tsx`'s create/edit form and built via `RegistryClient.build_skill_descriptors()`. AWS validates the `agentSkillsDefinition.data` field server-side against an undocumented, closed schema — confirmed by direct trial against a live registry (see `tmp/issues/061-add-skill-management-capabilities.md`): `data` must be *exactly* `{name, description, license, metadata: {author, version}}` with no other top-level keys, and `dataSchemaVersion` must be omitted entirely (AWS auto-assigns it) rather than set to any explicit value. The full SKILL.md markdown body lives separately in `additionalData.skillMd.data`. `metadata.author` is always the current Loom user on create, and is preserved from the existing record (not reassigned to the editor) on update — the create/update request models have no author field for exactly this reason. The existing submit/approve/reject/deprecate governance actions (`RegistryActions.tsx`, `/api/registry/records/{record_id}/submit|approve|reject`) already worked for SKILL records unmodified — they operate purely on `registryRecordId`/`registryStatus` and (via `_find_resource_by_record_id`) silently skip the "sync a linked Loom resource's status" step for skills, which have none — so wiring `RegistryActions` into `SkillsPage.tsx`'s detail view required no backend changes, confirmed by exercising the full submit→approve flow against a live registry.

`create_record`/`update_record` pass the skill's own `skill_version` (the SKILL.md `metadata.version` semver, e.g. `1.2.3`) as AWS's `recordVersion` field for `resource_type == "skill"` — a fix for an earlier bug where both calls hardcoded `record_version="1.0"` regardless of what the author set, so the version tag Loom displayed never actually matched what was submitted.

**Registry is opt-in:** The registry is configured via the Settings page by entering a registry ARN (validated format: `arn:aws:agent-registry:<region>:<account>:registry/<id>`). The ARN is stored in `site_settings` and loaded into memory on startup. When enabled, it provides additional governance mechanisms: agents, MCP servers, and A2A agents must be approved in the registry before they can be used. When not configured, all resources are available without registry approval. The `LOOM_REGISTRY_ID` env var is supported as a bootstrap fallback.

**Supported resource types:** `mcp` (MCP servers), `a2a` (A2A agents), `agent` (deployed agents). Agents are auto-registered in DRAFT status when deployment completes (if registry is configured).

**Visibility filtering:** When listing agents, MCP servers, or A2A agents, users in the `t-user` role only see resources with `registry_status` of APPROVED or NULL (unregistered). Admin users see all resources regardless of registry status.

**Integration gating:** When registry is configured, only APPROVED MCP servers and A2A agents can be selected for agent deployment. Non-approved integrations are rejected with a descriptive error.

**Scope enforcement:** `registry:read` for GET endpoints, `registry:write` for POST/PUT/DELETE endpoints.

**Registry status sync on re-enable:** When the registry ARN is updated via `PUT /api/settings/registry` and the new ARN is non-empty, the backend calls `_sync_registry_statuses()` to validate all stored `registry_record_id` values across Agent, McpServer, and A2aAgent models against the live registry. Records that no longer exist in the registry have their `registry_record_id` and `registry_status` cleared. Status mismatches are updated to match the live registry state. This prevents stale governance data after a disable/re-enable cycle.

**Data model:**
- `A2aAgent`: stores base URL, Agent Card fields (name, description, version, provider, capabilities, auth schemes, I/O modes), raw card JSON, OAuth2 config, status, and timestamps.
- `A2aAgentSkill`: stores skill ID, name, description, tags, examples, and I/O mode overrides. Foreign key to `A2aAgent` with cascade delete.
- `A2aAgentAccess`: stores persona_id, access_level (`all_skills`/`selected_skills`), and allowed_skill_ids (JSON). Foreign key to `A2aAgent` with cascade delete.

**Attaching Agent Registry skills to an agent (issue #61):** `Integration` (`models/integration.py`, previously used only for AWS-service integrations like S3/DynamoDB) is reused with `integration_type="skill"` and `integration_config={"record_id": "<SKILL record id>"}` to record which SKILL registry records an agent should use — managed through the existing `/api/agents/{agent_id}/integrations` CRUD (`routers/integrations.py`), surfaced in `AttachedSkillsSection.tsx` on `AgentDetailPage.tsx`, scoped in the picker to `APPROVED`-status SKILL records only (`GET /api/registry/records?status=APPROVED&descriptor_type=SKILL`). An unrecognized `integration_type` like `"skill"` is silently ignored by `build_integration_policy_statements()` (`services/iam.py`), so attaching a skill grants no IAM permissions — it's purely content, not an AWS-service integration.

At agent create/update/redeploy time, `_get_attached_skill_prompt_text(agent_id, db)` (`routers/agents.py`) fetches each enabled skill integration's registry record **live** (never cached) and folds `additionalData.skillMd.data` into the system prompt built by `_build_system_prompt()`, right alongside `agent_description`/`behavioral_guidelines`/`output_expectations`. Any attached skill that isn't currently `APPROVED` (later un-approved, deleted, or a registry lookup error) is silently skipped rather than failing the redeploy — the same "re-check live, fail open on the individual item" pattern used for MCP tool refreshes elsewhere. This is only wired into the two full-redeploy paths (`PUT /{agent_id}/redeploy-deploy`, `PUT /{agent_id}/redeploy-harness`), which already rebuild the system prompt from a fresh `AgentCreateRequest` — **not** the quick `POST /{agent_id}/redeploy`, which just resends the agent's existing env vars unchanged and never rebuilds the prompt at all. Attaching or detaching a skill therefore takes effect on the next full redeploy, not the quick one — the same "attach, then redeploy to apply" operational pattern already used for every other integration type in this codebase.

`AgentCreateRequest.skill_ids` (list of registry record IDs) lets skills be attached at initial deploy/harness-create time too, not just afterward via `AttachedSkillsSection.tsx` — validated against `APPROVED` status the same way as MCP/A2A, then reconciled onto `Integration` rows by `_sync_attached_skills()` (add missing, remove deselected) immediately after the agent row exists but before the system prompt is built, so a skill picked at creation time is included in that agent's very first deployed system prompt. `_sync_attached_skills()` is also called from both full-redeploy paths, so the "Update Agent" form's skill checklist and `AttachedSkillsSection.tsx`'s attach/detach both converge on the same rows.

**CreateAgentRuntime/UpdateAgentRuntime's `environmentVariables` has two caps that matter here**: a per-value max of 5000 characters (the API shape's declared limit, any platform version), and — the binding one in practice — AgentCore Runtime V2 (the default platform version for every agent, see `platformVersion="V2"` in `create_runtime`/`update_runtime`) enforces a much smaller **aggregate payload cap of 1536 bytes across every key+value combined**, confirmed from a live error ("The environment variable payload is 2835 bytes, exceeding the 1536-byte maximum supported for V2 agents"). `AGENT_CONFIG_JSON` (system prompt + integrations) blows past that total on almost any real system prompt, let alone one with a skill folded in. `_config_json_env_var()` guards this: it sums the UTF-8 byte length of every other env var plus the candidate `AGENT_CONFIG_JSON` value (`env_vars_total_bytes()`, `services/deployment.py`) and sends it inline only if the total fits under `MAX_ENV_VARS_TOTAL_BYTES` (1200, leaving headroom below AWS's 1536); otherwise `bake_config_into_artifact()` injects it as `agent_config.json` into the already-built artifact zip in S3, and `AGENT_CONFIG_PATH=agent_config.json` is sent instead of the inline JSON — the runtime's `config.py` (`load_config()`) already supported this file-path fallback (relative to the artifact root, which is the process's CWD since `entryPoint` runs `src/handler.py` relative to it), so no runtime code changes were needed, and no new IAM permissions either. Loom's own `ConfigEntry` bookkeeping always keeps the full inline JSON regardless of what was actually sent to AWS. The lightweight `POST /{agent_id}/redeploy` (which normally reuses the existing artifact untouched) rebuilds the artifact only when the stored env vars' total now exceeds the cap, purely to bake the file in.

### Agent Invocation (SSE Streaming)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/agents/{agent_id}/invoke` | Invoke the agent and stream the response via SSE. |
| `GET` | `/api/agents/{agent_id}/sessions` | List invocation sessions with their invocations. Accepts optional `user_id` query parameter for server-side filtering. |
| `GET` | `/api/agents/{agent_id}/sessions/{session_id}` | Get a specific session with its invocations. |
| `GET` | `/api/agents/{agent_id}/sessions/{session_id}/invocations/{invocation_id}` | Get a specific invocation. |

**`POST /api/agents/{agent_id}/invoke` request body:**
```json
{
  "prompt": "Hello, agent!",
  "qualifier": "DEFAULT",
  "credential_id": 1,
  "bearer_token": "eyJraWQ...",
  "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}
```

The optional `credential_id` references an authorizer credential. When provided, the backend fetches the client secret from Secrets Manager and generates an OAuth token for authenticated invocation. The optional `bearer_token` allows passing a raw bearer token directly — it takes highest priority (Priority 0) in the token selection chain, above user tokens and credential-based tokens.

The optional `model_id` specifies a runtime model override. When provided, it is validated against the agent's `allowed_model_ids`. If the model is not in the allowed list, the endpoint returns HTTP 400. If valid, the override is passed to `invoke_agent_stream()` which uses it instead of the agent's default model for that invocation. At the agent runtime level, model override uses a cached `BedrockModel` pool — models are created once and reused across invocations.

The optional `connector_ids` field is a list of MCP server IDs to dynamically attach for this invocation. The backend resolves each connector's configuration (endpoint URL, transport type, auth settings) and passes them to the agent runtime as `dynamic_mcp_servers` in the invocation payload. The agent runtime maintains a connection pool keyed by `(server_name, actor_id)` to reuse MCP clients across invocations. For API key connectors, the user's personal API key is resolved from Secrets Manager at `loom/mcp/{name}/api-key/{user_sub}`.

The invoke endpoint uses a priority-based token selection: (0) `bearer_token` from request body, (1) `credential_id` for M2M token, (2) user access token (forwarded when agent has authorizer), (3) agent config M2M flow, (4) SigV4 (no token).

**Group-based invoke restriction:** Super-admins (`g-admins-super`) can invoke any agent. For other users, agents with a `loom:group` tag are restricted to users whose group matches. Agents with no `loom:group` tag are accessible to any authenticated user with invoke scope.

**SSE event stream format:**

```
event: session_start
data: {"session_id": "uuid-...", "invocation_id": "uuid-...", "client_invoke_time": 1708000000.123, "has_token": true, "token_source": "credential:my-cred"}

event: chunk
data: {"text": "Hello! I am your agent."}

event: tool_use
data: {"name": "mcp_server___tool_name"}

event: session_end
data: {"session_id": "uuid-...", "invocation_id": "uuid-...", "qualifier": "DEFAULT", "client_invoke_time": 1708000000.123, "client_done_time": 1708000002.456, "client_duration_ms": 2333.0, "cold_start_latency_ms": 500.0, "agent_start_time": 1708000000.623, "input_tokens": 25, "output_tokens": 150, "estimated_cost": 0.001125}

event: error
data: {"message": "Invocation failed: ..."}
```

The `tool_use` event is emitted when the agent invokes a tool during streaming. The `name` field contains the tool name as reported by the Strands SDK (may include MCP server prefix in `server___tool` format).

The `has_token` and `token_source` fields in `session_start` indicate whether an OAuth token was used for the invocation.

### Cost Dashboard

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/dashboard/costs` | Aggregate estimated cost data across agents. Supports `group` (loom:group tag filter) and `days` (time range: 7, 30, 90, or 0 for all) query parameters. Non-super-admins are restricted to their own group. Returns per-agent cost breakdown with totals. Recomputes runtime costs from `client_duration_ms` at view time. |
| `POST` | `/api/dashboard/costs/actuals` | Pull actual costs from CloudWatch usage logs (runtime) and APPLICATION_LOGS (memory). Returns per-agent, per-session runtime cost breakdown and per-memory-resource cost breakdown. Runtime actuals only include sessions tracked in Loom. Memory actuals are unfiltered (memory pipeline session IDs do not correlate with runtime session IDs). |

**Token estimation:** AgentCore does not expose token counts. A heuristic of 4 characters per token is applied to both prompt and response text. Cost is computed as `(input_tokens / 1000 * input_price) + (output_tokens / 1000 * output_price)` using per-model pricing data from `SUPPORTED_MODELS`.

**Model pricing:** `SUPPORTED_MODELS` is loaded from `backend/etc/models.json` at startup. Each entry includes `model_id`, `display_name`, `group`, `max_tokens`, `input_price_per_1k_tokens`, `output_price_per_1k_tokens`, and `pricing_as_of` fields. `AGENTCORE_RUNTIME_PRICING` is loaded from `backend/etc/runtime_pricing.json` and tracks CPU ($0.0895/vCPU-hour), Memory ($0.00945/GB-hour), default vCPU allocation (1), default memory allocation (0.5 GB), and default idle timeout (900 seconds).

**View-time cost recomputation:** Runtime CPU and memory costs are recomputed from `client_duration_ms` at view time using current pricing defaults, so changing defaults retroactively affects all historical data. The `_apply_view_time_costs()` function recalculates both CPU and memory from duration, applying the I/O wait discount to CPU only. `_backfill_idle_costs()` always recomputes idle costs from session gaps to correct stale values from old defaults.

**Cost estimation formulas:**
- `Runtime CPU = invocation_duration_hours × 1 vCPU × $0.0895/vCPU·h × (1 − I/O wait%)`
- `Runtime Memory = invocation_duration_hours × 0.5 GB × $0.00945/GB·h`
- `Idle Memory = idle_seconds × 0.5 GB × $0.00945/GB·h ÷ 3600`

**CPU I/O Wait Discount:** A single configurable site setting (`cpu_io_wait_discount`, default 75%) applied universally to runtime CPU costs across both estimates and actuals. Stored as integer percentage (0–99).

**Actuals from CloudWatch usage logs:** The `POST /api/dashboard/costs/actuals` endpoint queries CloudWatch `BedrockAgentCoreRuntime_UsageLogs` streams for each runtime. Usage events (1-second granularity) are aggregated by `(agent_name, session_id)` from `attributes.agent.name` and `attributes.session.id`. All events within the time window for a given runtime are included — USAGE_LOGS session IDs are internal to AgentCore and do NOT match Loom's `runtimeSessionId`, so session-based filtering is not applied. Timestamps are normalized from epoch milliseconds or ISO strings to UTC ISO 8601. Delivery of usage logs can be delayed up to 15 minutes.

**Memory actuals from CloudWatch APPLICATION_LOGS:** For each memory resource, the endpoint queries the vended log group `/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/{memory_id}` stream `BedrockAgentCoreMemory_ApplicationLogs`. Memory pipeline session IDs are internal to AgentCore and do NOT correlate with runtime session IDs — they represent asynchronous extraction/consolidation/storage pipeline runs. The `parse_memory_log_events()` function maps `body.log` messages to pricing operations: "Retrieving memories." → LTM retrievals ($0.50/1K), "Succeeded to upsert N records." → LTM records stored ($0.75/1K/month), extraction and consolidation events are tracked as counts. Per-session breakdowns include `log_events`, `retrieve_records`, `records_stored`, `extractions`, `consolidations`, and `errors`.

**Agent cost summary:** `AgentResponse` includes a computed `cost_summary` field aggregating `total_input_tokens`, `total_output_tokens`, `total_model_cost`, `total_runtime_cost`, `total_memory_cost`, `total_cost`, and `total_invocations` across all invocations for the agent.

### Site Settings

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings/site` | List all site settings (includes defaults for unset keys). |
| `PUT` | `/api/settings/site/{key}` | Create or update a site setting. |
| `GET` | `/api/settings/models` | Get admin-enabled model IDs and the full merged model catalog (`model_catalog.get_merged_models()` — static + live Bedrock + live LiteLLM). |
| `PUT` | `/api/settings/models` | Update the set of admin-enabled models. Validates model IDs against the merged catalog (`get_merged_models()`), so dynamically-discovered Bedrock and LiteLLM models can be enabled too, not just the curated static list. |
| `POST` | `/api/settings/models/refresh` | Regenerate `etc/models.json` from `etc/bedrock_model_catalog.json` on demand (`model_catalog_refresh.refresh_models_json()`), then reload `SUPPORTED_MODELS` in-process (#64 R2). Uses the `models_json_lookback_months` site setting (default 6) unless an override is given in the request body. Returns the cutoff date and the included/excluded model IDs. |
| `GET` | `/api/settings/registry` | Get current registry configuration (ARN, ID, enabled status). |
| `PUT` | `/api/settings/registry` | Update registry configuration. Validates ARN format before saving. Empty ARN disables. |
| `GET` | `/api/settings/litellm-proxy` | Get the current LiteLLM proxy configuration (`enabled`, `base_url`, `discovery_base_url`, `has_master_key`). Reflects env-seeded defaults when no Settings-page override has been saved. Never returns the master key. |
| `PUT` | `/api/settings/litellm-proxy` | Update the LiteLLM proxy configuration. `master_key` is write-only — omit it to leave the stored key untouched. Persists to `SiteSetting` rows + Secrets Manager, then clears the LiteLLM model-catalog cache. |
| `POST` | `/api/settings/litellm-proxy/refresh` | Force a live re-fetch of the LiteLLM proxy's model catalog, bypassing the cache TTL — recovers from a stale/empty result (e.g. cached while the proxy was unreachable) without a backend restart. Returns the same shape as `GET/PUT /api/settings/models`. |

Current site settings:
- `cpu_io_wait_discount` (default: `75`) — CPU I/O wait discount percentage (0–99). Applied universally to runtime CPU costs.
- `enabled_model_ids` (default: `[]`) — JSON array of admin-enabled model IDs. When empty, all models are available. Filters the response of `GET /api/agents/models`. May include LiteLLM model IDs.
- `litellm_enabled`, `litellm_proxy_base_url`, `litellm_discovery_base_url` — LiteLLM proxy connection settings managed via `GET/PUT /api/settings/litellm-proxy` (see [16. Alternate LLM Providers](#16-alternate-llm-providers-litellm-proxy)). The master key is stored separately in Secrets Manager, not as a site setting.
- `loom_registry_id` (default: `""`) — AWS Agent Registry ARN. Stored in `site_settings`, loaded into memory on startup. Validated format: `arn:aws:agent-registry:<region>:<account>:registry/<id>`.

### CloudWatch Logs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agents/{agent_id}/logs/streams` | List available CloudWatch log streams. Also returns vended log sources (runtime APPLICATION_LOGS, runtime USAGE_LOGS, memory APPLICATION_LOGS) with display labels and last event timestamps. |
| `GET` | `/api/agents/{agent_id}/logs` | Retrieve logs from the latest (or specified) log stream. Paginates via `nextToken` (limit 10000). |
| `GET` | `/api/agents/{agent_id}/sessions/{session_id}/logs` | Retrieve all logs for a session using stream-name matching with `nextToken` pagination (limit 10000). Falls back to `filterPattern` for shared streams. |
| `GET` | `/api/agents/{agent_id}/logs/vended` | Retrieve logs from a vended log source (runtime or memory). Accepts `log_group` and `stream` query parameters. |

### Traces (OTEL Logs)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agents/{agent_id}/sessions/{session_id}/traces` | List traces for a session. Fetches all OTEL log records from the `otel-rt-logs` CloudWatch stream (single fetch, no filter), then filters by `session.id` attribute in Python. Returns trace summaries with trace ID, start/end time ISO, duration, span count, and event count. |
| `GET` | `/api/agents/{agent_id}/traces/{trace_id}` | Get full trace detail. Fetches OTEL log records filtered by trace ID. Returns the trace ID and a list of spans, each with span ID, scopes, start/end times, duration, and a list of events (observed time, severity, scope, body). Bodies with both `input` and `output` keys are split into separate events. |

### Admin Audit

All endpoints require `security:read` scope (super-admins and demo-admins only).

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/audit/login` | Record a user login event. Body: `{user_id, browser_session_id}`. |
| `GET` | `/api/admin/audit/logins` | List login events. Query params: `user_id`, `start_date`, `end_date`, `limit` (default 100), `offset` (default 0). |
| `POST` | `/api/admin/audit/action` | Record a user action event. Body: `{user_id, browser_session_id, action_category, action_type, resource_name?}`. |
| `GET` | `/api/admin/audit/actions` | List action events. Query params: `user_id`, `browser_session_id`, `action_category`, `action_type`, `start_date`, `end_date`, `limit`, `offset`. |
| `POST` | `/api/admin/audit/pageview` | Record a page view event. Body: `{user_id, browser_session_id, page_name, entered_at, duration_seconds?}`. |
| `GET` | `/api/admin/audit/pageviews` | List page view events. Query params: `user_id`, `browser_session_id`, `page_name`, `start_date`, `end_date`, `limit`, `offset`. |
| `GET` | `/api/admin/audit/sessions` | List browser sessions with aggregated counts. Returns `{browser_session_id, user_id, logged_in_at, action_count, page_view_count, last_activity_at}`. Query params: `user_id`, `start_date`, `end_date`. |
| `GET` | `/api/admin/audit/sessions/{browser_session_id}/timeline` | Interleaved chronological event feed for a single browser session (logins, actions, and page views). |
| `GET` | `/api/admin/audit/summary` | Aggregated metrics. Query params: `start_date`, `end_date`. Returns `{total_logins, active_users, total_actions, actions_by_category, page_views_by_page, logins_by_day, actions_by_day}`. |

---

## 7. Service Modules

### `services/agentcore.py`

Wraps `boto3.client('bedrock-agentcore')` and `boto3.client('bedrock-agentcore-control')`:

- `describe_runtime(arn: str, region: str) -> dict` — calls `get_agent_runtime` and returns runtime metadata.
- `list_runtime_endpoints(runtime_id: str, region: str) -> list[str]` — returns available qualifier names.
- `invoke_agent(arn: str, qualifier: str, session_id: str, prompt: str, region: str) -> Generator` — calls `invoke_agent_runtime`, yields decoded text chunks. Supports OAuth-authorized agents via Bearer token header.

### `services/cloudwatch.py`

Wraps `boto3.client('logs')`:

- `list_log_streams(log_group: str, region: str) -> list[dict]` — lists streams ordered by last event time.
- `get_stream_log_events(log_group: str, stream_name: str, region: str, ...) -> list[dict]` — retrieves all events from a single log stream with `nextToken` pagination. Default limit 10000.
- `get_log_events(log_group: str, session_id: str, region: str, ...) -> list[dict]` — two-strategy session log retrieval: (1) matches log streams whose name contains the session ID (e.g. `[runtime-logs-<session_id>]`) and fetches all events with pagination, (2) falls back to `filterPattern` search across all streams for shared streams like `ApplicationLogs`. Both strategies paginate via `nextToken` with limit 10000.
- `parse_agent_start_time(log_events: list[dict]) -> float | None` — parses "Agent invoked - Start time:" pattern; falls back to earliest CloudWatch event timestamp.
- `parse_memory_telemetry(log_events: list[dict]) -> dict[str, int]` — parses `LOOM_MEMORY_TELEMETRY` structured log line for memory cost tracking. Returns `retrievals` and `events_sent` counts.
- `get_usage_log_events_by_time(runtime_id, region, start_time_ms, end_time_ms)` — queries CloudWatch `BedrockAgentCoreRuntime_UsageLogs` stream for usage events within a time range. Paginates via `nextToken`.
- `parse_usage_events(raw_events)` — parses raw CloudWatch log events into structured usage records with vCPU hours, memory GB hours, agent name, session ID, and normalized timestamps.
- `get_memory_log_events(memory_id, region, start_time_ms, end_time_ms)` — queries CloudWatch `BedrockAgentCoreMemory_ApplicationLogs` stream in the vended log group `/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/{memory_id}`. Paginates via `nextToken`.
- `parse_memory_log_events(raw_events)` — parses memory APPLICATION_LOG events by mapping `body.log` messages to operations: "Retrieving memories." → LTM retrievals, "Succeeded to upsert N records." → records stored, extraction/consolidation tracking. Returns total counts, per-session breakdowns, and computed costs.

### `services/otel.py`

Parses OTEL (OpenTelemetry) log records from CloudWatch:

- `fetch_otel_events(log_group, region, filter_pattern, limit)` — fetches log events from the `otel-rt-logs` CloudWatch stream via `filter_log_events`. Always scopes to `logStreamNames: ["otel-rt-logs"]`. Supports optional `filterPattern` for trace ID filtering. Paginates via `nextToken`. Default limit 10000.
- `parse_otel_traces(raw_events)` — groups raw OTEL log events by `traceId`. Computes per-trace summaries: start/end time, duration, unique span count, and event count (with input/output body splitting for accurate counts). Filters by `session.id` attribute when present.
- `parse_otel_trace_detail(raw_events)` — groups events by `spanId` within a single trace. For each span: collects scopes, computes start/end times and duration, builds event list with observed time, severity, scope, and body. Bodies containing both `input` and `output` keys are split into two separate events via `_split_body()`.

### `services/deployment.py`

Handles agent artifact build and runtime lifecycle:

- Builds agent artifacts by cross-compiling pip dependencies for ARM64 (`manylinux2014_aarch64`).
- Creates, updates, and deletes AgentCore runtimes and endpoints.
- `create_runtime()` and `update_runtime()` always set `platformVersion="V2"` in the boto3 call params, so every runtime Loom creates or updates lands on AgentCore Runtime v2 (snapshot-restore cold starts, paged memory) with no caller-supplied flag. Requires `boto3>=1.43.95` — earlier versions' `bedrock-agentcore-control` service model doesn't expose `platformVersion` on `CreateAgentRuntime`/`UpdateAgentRuntime`.
- `update_runtime()` accepts optional `description`, `env_vars`, `role_arn`, `authorizer_config`, and `region` parameters. Description updates are propagated from the `PATCH /api/agents/{id}` endpoint.
- Updates agent runtime authorizer configuration (e.g., adding client IDs to `allowedClients`).
- Validates configuration values for secrets, stores/updates/deletes secrets in AWS Secrets Manager.

### `services/cognito.py`

- `get_cognito_token(pool_id: str, client_id: str, client_secret: str, scopes: list[str]) -> str` — exchanges client credentials for an access token via the Cognito OAuth2 token endpoint.

### `services/harness.py`

AgentCore Harness API wrapper for managed agent deployments:

- `create_harness(name, execution_role_arn, model_id, system_prompt, tools, allowed_tools, max_iterations, max_tokens, authorizer_config, network_mode, idle_timeout, max_lifetime, tags, region, provider="bedrock", litellm_api_key_arn=None, litellm_api_base=None) -> dict` — creates a new AgentCore Harness via the `bedrock-agentcore-control` client. Builds the `model` field via `_build_model_config()` — `bedrockModelConfig` (default) or, when `provider="litellm"`, `liteLlmModelConfig` (`modelId`, optional `apiKeyArn` pointing at an AgentCore API key credential provider, `apiBase`, `maxTokens`). Supports tool types: `remote_mcp`, `agentcore_code_interpreter`, `agentcore_browser`. Sets `allowedTools: ["*"]` by default. Returns the harness response with ARN in the `"arn"` field.
- `get_harness(harness_id, region) -> dict` — retrieves current harness state from the control plane.
- `delete_harness(harness_id, region) -> dict` — deletes a harness.
- `update_harness(harness_id, execution_role_arn, model_id, system_prompt, tools, allowed_tools, max_iterations, max_tokens, authorizer_config, network_mode, idle_timeout, max_lifetime, region, provider="bedrock", litellm_api_key_arn=None, litellm_api_base=None) -> dict` — updates an existing harness via the `bedrock-agentcore-control` client. Only sends parameters that are explicitly provided (non-None). Uses the same `_build_model_config()` provider dispatch as `create_harness`. Used by the `redeploy-harness` endpoint.
- `invoke_harness_stream(harness_arn, session_id, prompt, region, model_id, system_prompt, tools, allowed_tools, max_iterations, timeout_seconds, max_tokens, actor_id, access_token, user_access_token, provider="bedrock", litellm_api_key_arn=None, litellm_api_base=None) -> Generator[dict]` — invokes a harness and yields translated events. When `access_token` is provided, configures the `bedrock-agentcore` client with `UNSIGNED` SigV4 and injects `Authorization: Bearer <token>` via a boto3 `before-send` event hook for JWT auth. When `user_access_token` is provided, injects it as `X-Loom-User-Access-Token` header for OBO token exchange flows. Translates Converse API streaming format (`messageStart`, `contentBlockStart`, `contentBlockDelta`, `contentBlockStop`, `messageStop`, `metadata`) into `{"type": "text", "content": str}`, `{"type": "structured", "content": {"tool_use": {"name": str}}}`, and `{"type": "metadata", "content": dict}` events. Accumulates token counts from metadata events.
- `resume_harness_stream(harness_arn, session_id, tool_result, region, ..., user_access_token) -> Generator[dict]` — re-invokes a harness with a `toolResult` to resume after an inline function call. Supports the same `user_access_token` header injection for OBO flows.
- `_build_model_config(provider, model_id, max_tokens=None, litellm_api_key_arn=None, litellm_api_base=None) -> dict` — internal helper selecting the `model` payload shape for `CreateHarness`/`UpdateHarness`/`InvokeHarness` based on `provider`.

AgentCore Harness only reaches models via the `bedrock-runtime` endpoint. `app.routers.agents._deploy_harness()` and `redeploy_harness_agent()` call `bedrock_invocation.assert_model_supports_endpoint(model_id, SUPPORTED_MODELS, BEDROCK_RUNTIME)` before `create_harness`/`update_harness` and reject `bedrock-mantle`-only models (e.g. Gemma 4) with a 400 rather than letting `CreateHarness`/`UpdateHarness` fail opaquely (#64 R1). Models missing from the curated catalog (dynamically-discovered LiteLLM/live-Bedrock models) are not validated — nothing to check against.

### `services/bedrock_invocation.py`

Resolves and performs serverless inference against Bedrock models on either the `bedrock-runtime` or `bedrock-mantle` endpoint (#64 R1). Each `models.json`/`bedrock_model_catalog.json` entry declares which endpoint(s) and API(s) its `model_id` supports via `endpoints` (list of `"bedrock-runtime"`/`"bedrock-mantle"`) and `apis` (dict of endpoint → list of `"converse"`/`"invoke"`/`"messages"`/`"chat_completions"`/`"responses"`), plus an optional `endpoint_model_ids` override for models whose ID differs per endpoint (e.g. `openai.gpt-oss-120b-1:0` on `bedrock-runtime` vs. `openai.gpt-oss-120b` on `bedrock-mantle`).

- `resolve_model_target(model_id, catalog, region, preferred_endpoint=None, preferred_api=None) -> ModelInvocationTarget` — picks the endpoint/API/model-ID to invoke with. Catalog entries predating this metadata fall back to `bedrock-runtime` + `converse`.
- `assert_model_supports_endpoint(model_id, catalog, endpoint="bedrock-runtime")` — raises `UnsupportedModelEndpointError` unless `model_id` supports `endpoint`; used by the harness deploy/redeploy validation above.
- `invoke_model(model_id, catalog, messages, region, max_tokens=None, system_prompt=None, preferred_endpoint=None, preferred_api=None) -> dict` — runs a single-turn inference call and returns `{"content", "endpoint", "api", "model_id", "raw"}`. On `bedrock-runtime` this uses the standard `boto3.client("bedrock-runtime")` (Converse API, or `InvokeModel` with the Anthropic Messages body for the `messages`/`invoke` APIs). `bedrock-mantle` isn't a registered boto3 service model, so the request is built and SigV4-signed directly (`botocore.auth.SigV4Auth` against service `"bedrock"`) and sent via `urllib.request` to `https://bedrock-mantle.{region}.api.aws{path}` — `/anthropic/v1/messages` for the native Messages API, `/openai/v1/chat/completions` or `/openai/v1/responses` for the OpenAI-compatible APIs.
- Exposed via `POST /api/agents/models/invoke-test` (see API Endpoints below) so a user can validate any catalog model works, on whichever endpoint it requires, before wiring it into an agent or harness.

### `services/model_catalog_refresh.py`

Regenerates `etc/models.json` from the curated `etc/bedrock_model_catalog.json` superset (#64 R2). `bedrock_model_catalog.json` carries every known model — including ones too old, or too new/unpriced, to serve by default — plus a `launch_date` field that `models.json` (which lacks it) doesn't need at runtime. Filtering rules:

1. **Recency** — a model is included only if `launch_date` falls within `lookback_months` (default 6) of today. A `null` `launch_date` (unknown) is always included rather than guessed away.
2. **Completeness** — a model is included only if it has non-null `max_tokens` and both per-1k-token prices. Bedrock publishes no pricing API, so this is manually curated; incomplete entries are excluded, not zero-filled, until an engineer fills them in.
3. Optionally cross-checked against live `ListFoundationModels`/`ListInferenceProfiles` availability in a target region — best-effort, any failure (missing credentials, network) is logged and skipped rather than failing the run.

- `refresh_models_json(catalog_path, output_path, lookback_months=6, region="us-east-1", skip_live_check=False, reference_date=None, dry_run=False) -> dict` — does the filtering; returns `{"included", "excluded_stale", "excluded_incomplete", "excluded_unavailable", "cutoff"}` (each a list of `model_id`s except `cutoff`, an ISO date string).
- `reload_supported_models()` — re-reads `etc/models.json` and pushes it into `app.routers.agents.SUPPORTED_MODELS`, since that module-level list is otherwise only loaded once at import.
- Used by `scripts/refresh_models_json.py` (CLI — run via `make refresh-models` at each major release; accepts `LOOKBACK_MONTHS`/`REGION` env overrides) and `POST /api/settings/models/refresh` (on-demand admin trigger, reads the `models_json_lookback_months` site setting unless overridden in the request body).

### `services/credential.py`

AgentCore credential provider management:

- `credential_provider_name(agent_id: int, agent_name: str, kind: str, resource_name: str | None = None) -> str` — the single place provider names are derived: `loom-{agent name}-{agent id}-{kind}[-{resource name}]`, with every component sanitized to `[a-zA-Z0-9.-]`. `kind` is `mcp`, `a2a`, `litellm-key` or `custom`. The agent id is the security-relevant part — see "Credential provider names are keyed on the agent id" above.
- `create_oauth2_credential_provider(name: str, client_id: str, client_secret: str, auth_server_url: str, region: str, tags: dict | None, delegation_mode: str = "m2m", obo_grant_type: str | None = None, allow_update: bool = False) -> dict` — creates an OAuth2 credential provider using the `CustomOauth2` vendor type. When `delegation_mode` is `"obo"`, configures `onBehalfOfTokenExchangeConfig` with the specified grant type (`TOKEN_EXCHANGE` for RFC 8693 or `JWT_AUTHORIZATION_GRANT` for RFC 7523). TOKEN_EXCHANGE uses `actorTokenContent: NONE` with `CLIENT_SECRET_BASIC` auth method; JWT_AUTHORIZATION_GRANT uses `CLIENT_SECRET_POST`. If creation fails with a `ValidationException` indicating the provider already exists, raises `CredentialProviderNameInUse` unless `allow_update=True`, in which case it falls back to `update_oauth2_credential_provider` (without tags, which the update API does not accept). Retries other transient failures with exponential backoff (4 retries, delays 2s/4s/8s/16s). Raises on exhaustion.
- `delete_credential_provider(provider_name: str, region: str)` — deletes an OAuth2 credential provider by name.
- `create_api_key_credential_provider(name: str, api_key: str, region: str, allow_update: bool = False) -> dict` — creates an AgentCore **API key** credential provider — a distinct provider type from the OAuth2 ones above. Used for harness agents' `liteLlmModelConfig.apiKeyArn`, which the Harness resolves itself via `bedrock-agentcore:GetResourceApiKey` at invocation time (not Secrets Manager). Same `allow_update` semantics as the OAuth2 function. Returns the response dict including `credentialProviderArn`.
- `CredentialProviderNameInUse(Exception)` — raised when the name is already taken and the caller did not opt into overwriting it.
- `delete_api_key_credential_provider(provider_name: str, region: str)` — deletes an API key credential provider by name.

**IAM permissions required:** The ECS task role needs both `bedrock-agentcore:*` actions (for the control plane API) and Secrets Manager permissions scoped to `bedrock-agentcore-identity!*` secrets. Credential providers internally store OAuth2 client credentials in Secrets Manager under this prefix. The task role requires `secretsmanager:GetSecretValue`, `CreateSecret`, `DeleteSecret`, and `PutSecretValue` on `arn:aws:secretsmanager:*:${AccountId}:secret:bedrock-agentcore-identity!*`. The CloudWatch Logs policy covers both `/aws/bedrock-agentcore/*` and `/aws/vendedlogs/bedrock-agentcore/*` log group prefixes (the latter is used for agent observability vended logs).

### `services/jwt_validator.py`

- `validate_cognito_token(token: str, user_pool_id: str, region: str, client_id: str | None) -> dict` — validates a JWT against the Cognito JWKS endpoint. Caches JWKS keys for 1 hour.

### `dependencies/auth.py`

Core authentication and authorization module. Provides:

- `GROUP_SCOPES: dict[str, list[str]]` — maps Cognito group names to scope lists. Must match the frontend `GROUP_SCOPES` exactly. Uses two-dimensional group architecture:
  - **Type groups** (UI view): `t-admin`, `t-user` — no scopes, determine layout
  - **Resource groups** (access control):
    - `g-admins-super`: all 22 scopes (catalog:r/w, agent:r/w, session:read, memory:r/w, security:r/w, tagging:r/w, costs:r/w, mcp:r/w, a2a:r/w, registry:r/w, admin:r/w, invoke)
    - `g-admins-demo`: `catalog:read`, `agent:read`, `agent:write`, `session:read`, `memory:read`, `memory:write`, `security:read`, `tagging:read`, `costs:read`, `costs:write`, `mcp:read`, `mcp:write`, `a2a:read`, `a2a:write`, `invoke` (can create/delete demo resources only)
    - `g-admins-security`: `security:read`, `security:write`, `tagging:read`
    - `g-admins-memory`: `memory:read`, `memory:write`, `tagging:read`
    - `g-admins-mcp`: `mcp:read`, `mcp:write`, `tagging:read`
    - `g-admins-a2a`: `a2a:read`, `a2a:write`, `tagging:read`
    - `g-admins-registry`: `mcp:read`, `a2a:read`, `registry:read`, `registry:write`, `tagging:read`
    - `g-users-demo`, `g-users-test`, `g-users-strategics`: `invoke` + read access to resources tagged with matching group
  - **`admin:read`/`admin:write`** (global deployment configuration — site settings, registry config, LiteLLM proxy config, enabled models, VPC configs): held only by `g-admins-super`. No domain-scoped admin group holds these, since none of the actions they gate are scoped to a `loom:group` — a write by any domain admin would apply to the whole deployment.
- `UserInfo` dataclass — `sub`, `username`, `groups`, `scopes` (derived from groups).
- `get_current_user(request: Request) -> UserInfo` — FastAPI dependency; pulls the Bearer token from the header and delegates to `authenticate_bearer_token`. Raises 401 on missing/invalid token.
- `authenticate_bearer_token(token: str, connection: Request | WebSocket) -> UserInfo` — the single token-to-identity implementation, shared by the HTTP dependency and the invoke WebSocket. Validates against an active external IdP first, then Cognito; in bypass mode (no `LOOM_COGNITO_USER_POOL_ID` and no active IdP) returns a super-admin, but only with the explicit opt-in and a loopback client. `connection` is only read for `.headers`/`.client`, which both Request and WebSocket provide.

**WebSocket invoke authentication (CWE-306).** `WS /api/agents/{id}/ws` (`routers/invocations.py`) used to call `accept()` and then serve invocations with *no* authentication: no identity, no `invoke` scope, and no `loom:group` check, while `POST /api/agents/{id}/invoke` beside it required all three. Anyone able to reach the socket received a `session_start`, could enumerate agent IDs from the "Agent N not found" reply, and — supplying a runtime bearer of their own as `bearer_token` — could drive a JWT/OAuth-authorized agent with no Loom session and no group check. SigV4-authorized runtimes were unreachable only incidentally, because nothing on this path signs.

The handler now authenticates from the first frame, which is where the SPA has always sent the Loom JWT as `token` (`api/invocations.ts`) — the field simply was never read. Order matters and is asserted by tests: authenticate, check the `invoke` scope, *then* look up the agent and apply `check_resource_group_access`, so the not-found reply can no longer be used as an unauthenticated existence oracle. Any failure sends one error frame and closes with 1008. Because the first frame is consumed for authentication, the read loop fetches subsequent frames at the end of the prompt branch rather than at the top.

This route queried `Agent` directly, which is why it was missed when fetch-by-ID was routed through `check_resource_group_access` for H1-3954919 — the same shape of gap as the IdP empty-mapping bypass: a remediation that fixed the reported path rather than every path.

**Local-dev bypass: defence in depth around an open-admin-panel risk.** The bypass returns every scope with no authentication, and its precondition — neither Cognito nor an active external IdP configured — is also the state of a *fresh deployment that intends to use an external IdP but has not registered it yet*. The two remaining gates are therefore all that separate such a deployment from an open admin panel, and neither was robust alone:

- `LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV` is a boolean that can be left behind in a task definition.
- `_is_loopback_request()` reads `request.client`, which is only as trustworthy as the proxy config in front of the app. uvicorn ships with `proxy_headers=True` and `forwarded_allow_ips` defaulting to `FORWARDED_ALLOW_IPS` or `127.0.0.1`; widening that past loopback — a common change behind a load balancer, made to recover real client IPs, and one that looks unrelated to auth — lets a remote caller send `X-Forwarded-For: 127.0.0.1` and have `request.client.host` read back as loopback.

Two defences, both verified by mutation testing in `tests/test_auth_bypass_hardening.py`:

- `assert_local_dev_bypass_not_deployed()` is called as the **first** step of the application lifespan and raises, refusing to serve any request, when the opt-in is set alongside a container-runtime signal (`ECS_CONTAINER_METADATA_URI_V4`, `ECS_CONTAINER_METADATA_URI`, `AWS_EXECUTION_ENV` — injected by ECS into every task, absent on a developer machine) or a `FORWARDED_ALLOW_IPS` value that trusts non-loopback peers. Misconfiguration is a config-time event, so it fails at config time, in front of whoever deployed it.
- `_bypass_allowed_for_request()` additionally refuses the bypass for any request carrying a proxy forwarding header (`X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Real-IP`, `Forwarded`). The spoof above cannot work *without* one of those headers, and uvicorn leaves them readable after rewriting `request.client`, while a genuine direct-to-loopback dev request never carries one.

Note `get_current_user_token()` has the same no-IdP precondition and returns the caller's token *unvalidated* in that state. It grants no scopes, so it does not escalate privilege, but it is the remaining instance of this pattern — tracked for removal alongside the bypass itself.
- `require_scopes(*required: str)` — factory returning a FastAPI dependency that checks the user has ALL required scopes. Raises 403 on missing scope. Used as `Depends(require_scopes("scope:name"))` on all guarded endpoints.
- `oauth2_scheme` — `OAuth2AuthorizationCodeBearer` for OpenAPI docs with all 22 scopes.
- `get_current_user_token(request: Request) -> str | None` — legacy helper for token forwarding to AgentCore invocations.
- `get_token_claims(request: Request) -> dict | None` — legacy helper for decoded claims extraction.

**Scope enforcement per router:**

| Router | GET scopes | POST/PUT/DELETE scopes |
|--------|-----------|----------------------|
| `agents.py` | `agent:read` | `agent:write` |
| `invocations.py` | `agent:read` (sessions), `invoke` (invoke/token) | — |
| `logs.py` | `agent:read` | — |
| `credentials.py` | `agent:read` | `agent:write` |
| `integrations.py` | `agent:read` | `agent:write` |
| `memories.py` | `memory:read` | `memory:write` |
| `security.py` | `security:read` | `security:write` |
| `settings.py` (tag policies/profiles) | `tagging:read` | `tagging:write` |
| `settings.py` (site settings, registry config, LiteLLM proxy config, enabled models) | `admin:read` | `admin:write` |
| `settings.py` (VPC configs list/detail) | any `t-admin` group | — |
| `settings.py` (VPC configs create/update/delete) | — | `admin:write` |
| `costs.py` | `costs:read` | `costs:write` (actuals endpoint) |
| `mcp.py` | `mcp:read` | `mcp:write` |
| `a2a.py` | `a2a:read` | `a2a:write` |
| `registry.py` | `registry:read` | `registry:write` |
| `auth.py` | Public (no guard) | — |

**Tag-based resource isolation:** Resources are filtered by the `loom:group` tag. The two-dimensional group architecture determines filtering:
- **Admins** (`t-admin` + any `g-admins-*`): See all resources including untagged (no filtering)
- **Users** (`t-user` + `g-users-*`): Only see resources where `loom:group` matches one of their `g-users-*` groups
- **Multi-group users**: See resources tagged with ANY of their groups (union semantics)
- **Demo-admin write restrictions**: `g-admins-demo` can only create/delete resources with `loom:group=demo` (enforced in agents.py and memories.py)

**Multi-group filtering:** When a user belongs to multiple groups (excluding `super-admins`), the backend applies a union filter: a resource is visible if its `loom:group` tag matches any of the user's groups. This allows cross-team visibility when users have multiple group memberships.

**`session:read` is separate from `agent:read`.** Conversation content — `prompt_text`, `thinking_text`, `response_text`, and approval logs' `tool_input_summary` — is far more sensitive than "this agent exists", so the session/invocation/approval-log readers are gated on `session:read` rather than `agent:read`. Every group that holds `agent:read` today also holds `session:read`, so the split is not a privilege change; the point is that agent visibility can now be granted without handing over every transcript, and the domain admins (`g-admins-security`/`memory`/`mcp`/`a2a`/`registry`) hold neither.

**Conversation reads enforce group *and* ownership.** `GET /api/agents/{id}` returned 403 for an agent outside the caller's group, but the readers beside it never got the same check: `list_sessions` loaded the Agent by ID with no check and returned every conversation on it to any `t-admin`, while `get_session` and `get_invocation` resolved by session UUID with no group check *and* no owner filter. `GET /api/settings/approvals/logs` was worse — declared with `dependencies=[...]` and no `user` parameter, so it had no identity in scope and structurally could not check anything, filtering only on a caller-supplied sequential `agent_id`. `routers/utils.py` now provides `get_session_or_404()` (group check via `get_agent_or_404`, then `assert_session_readable`: owner, or an admin for the agent's group) and `visible_agent_ids()` (for list routes, so an unfiltered query returns the caller's own agents rather than everyone's).

**loom:group is mandatory at creation.** `routers/utils.py`'s `require_group_tag()` rejects any create whose tags carry no `loom:group`, wired into every resource-creating path: both agent deploy paths, memory create, MCP server create/update, A2A agent create/update, managed-role import and authorizer create. MCP servers and A2A agents previously had tag *columns* (`tags` and `resource_tags`) that no API exposed, which is why every one of them was untagged — both now accept `tags` on create and update. The frontend disables submit until a tag profile is chosen, on the agent wizard, memory, MCP and A2A forms.

Enforced at the API boundary rather than in the models' `set_tags()`: internal paths and the fail-closed tests still need to be able to construct an untagged resource, not least to prove the fail-closed behaviour. The guarantee is "the API cannot create one", not "the type cannot exist". The authorizer create path additionally gained a `tags` field — it previously read tags only from the Cognito user pool and silently ignored the caller's, which is how two of three authorizers ended up untagged.

**Untagged resources fail closed.** `check_resource_group_access()` used to return early for a resource with no `loom:group` tag, making it readable by anyone — the same shape as an empty IdP mapping table meaning "trust the provider": absence of policy read as absence of restriction. An untagged resource is now visible to super-admins only. **This is a breaking change for existing data**: any resource without a `loom:group` tag becomes inaccessible to non-super users until tagged.

**Resources bound to an agent by primary key are group-checked.** `GET /api/mcp/servers/{id}` and `GET /api/memories/{id}` returned 403 across groups, but the agent deploy paths resolved `mcp_servers`, `memory_ids` and `a2a_agents` straight from primary keys in the request body and only ever validated existence and registry-approval status. The IDs were therefore a second way in: a caller holding `agent:write` in one group could attach another group's MCP server — whose deploy snapshot carries `oauth2_client_secret` into a credential provider created under the caller's own agent — or another group's `memory_id` into their own `AGENT_CONFIG_JSON`. The single-object helpers never ran on this path.

`routers/utils.py`'s `assert_bindable()` now runs at all ten bind sites across the four entry points (`_deploy_agent`, `_deploy_harness`, `redeploy_deploy_agent`, `redeploy_harness_agent`). Unlike `filter_visible_resources` it raises rather than filtering: a list silently omitting an unreachable row is right, but a deploy silently dropping an integration the caller asked for would hand them a working agent quietly missing its tools.

Keyed on what the **caller** can reach rather than on matching the agent's own `loom:group`. That is the reporter's own "do not snapshot secrets the caller cannot GET", it matches the semantics every other check uses, and it leaves a super-admin able to compose across groups deliberately rather than breaking deployments that share one integration between several groups' agents. The existence check still runs first, so an unknown ID remains a 400 rather than becoming a 403 — otherwise every bad ID would look like someone else's resource.

`code_interpreter_role_id` had the same shape and was **not in the report**. It is worse than the reported binds: `ci_role.role_arn` becomes the code interpreter's `execution_role_arn`, so an unchecked bind hands another group's IAM role to the caller's agent — privilege escalation rather than disclosure. `ManagedRole` carries `loom:group` tags, so the same check applies. It is validated at request time in all four entry points because the two deploy paths that consume it run in background tasks, where there is no caller to check against. `VpcConfig` is bound the same way and deliberately left alone: it has no tag column, being global deployment-wide configuration behind `admin:write` rather than a group-scoped resource.

**Loom cannot create, modify or delete IAM roles or policies.** The capability was removed outright rather than restricted. Loom used to create the agent execution role during deploy, PutRolePolicy-replace its inline policy whenever an integration changed, apply extra statements when a permission request was approved, and delete the role on teardown. All of it is gone, including the policy *document builders* (`build_base_policy`, `build_trust_policy`, `build_integration_policy_statements`) — those only returned dicts, but they are the machinery for writing a policy, and the requirement was no capability whether latent or not.

The execution role is now provisioned outside Loom by a platform engineer from `shared/iac/role.yaml`, which is retained for exactly that purpose, and registered through Security > Roles so agents can reference it and group entitlement can be checked. `app/services/iam.py` is read-only by construction and exports only `list_agentcore_roles` and `list_cognito_pools`. `app/services/security.py` keeps only `get_role_policy_details`, which reads a role's policy so the registered record can display what the permissions actually are; Loom never writes it back.

Worth recording because it reframes the IAM-takeover report: the deployed ECS task role has never been granted `iam:CreateRole`, `iam:PutRolePolicy` or `iam:DeleteRole` — only `PassRole`, `GetRole` and read/list actions. So those code paths already failed with AccessDenied on any standard deployment and only worked when Loom was run locally against an over-privileged AWS profile. Removing them deletes code that was dead in production.

Consequences, all deliberate:

- **`role_arn` is required on deploy and redeploy.** There is nothing to fall back to. Rejected with 400 and a message naming `shared/iac/role.yaml`, at the request boundary rather than in the background task, so the caller is not left waiting on a deployment that cannot succeed.
- **Only a registered role is usable.** `bindable_role_arns()` lost its clause accepting any ARN already attached to a reachable agent — that clause existed only because Loom-created roles had no `ManagedRole` row. Registration is now the single way a role enters Loom. **An agent whose role Loom auto-created will fail to redeploy until that role is registered under Security > Roles**, which is the intended outcome: an unregistered role has no `loom:group`, so it has no owner and no one can be entitled to it.
- **Integrations no longer grant permissions.** Adding an S3 or Lambda integration records the configuration and nothing more; the operator grants the matching permission on the role themselves. `test_integrations.py` asserts the inverse of what it used to — that creating an integration does not construct an IAM client at all.
- **Role registration is import-only.** `CreateRoleRequest` lost `mode`, `role_name` and `policy_document`; `role_arn` is required. `UpdateRoleRequest` lost `policy_document`, because accepting a policy Loom cannot apply would misrepresent the role's real permissions.
- **Permission requests are removed entirely** — model, routes, UI and table. The feature existed only to have Loom apply statements to a role. `backend/scripts/drop_permission_requests.py` drops the table; it is dry-run by default and `--apply` destroys the request history.

`TestLoomCannotWriteIam` in `tests/test_authorization_invariants.py` enforces all of this structurally: no call to any IAM write action anywhere under `app/`, none of the removed helper names reappearing (which also catches a re-add of the builders), `services/iam.py` exporting only the two discovery functions, and no `PermissionRequest` reference surviving.

**Registry status transitions are group-checked.** `registry:write` was enough to drive another group's agent, MCP server or A2A agent through submit → approve. Create was fixed earlier; `submit_for_approval`, `approve_record`, `reject_record`, `delete_record` and `update_record` all resolved the Loom row via `_find_resource_by_record_id` and stamped `registry_status` with no `loom:group` check. That matters because approval is both the deploy gate and the `t-user` catalog gate, and the descriptors published to the site-wide AWS Agent Registry carry the victim's invoke URL, MCP `endpoint_url` or A2A card URL. `_owned_resource_or_403()` now runs in all five — and runs *before* the registry API call, since the remote transition is the side effect that cannot be rolled back. Records with no linked Loom row (skills) stay governed by `registry:write` alone. The primary-key bind guard did not catch these because they resolve by `registry_record_id` rather than `.id`.

**Execution-role ARNs are authorized before they are attached.** `agent:write` was enough to take over any IAM role in the account that trusts `bedrock-agentcore`, with no `security:write`: `GET /api/agents/roles` listed every such role via `iam.list_roles`, deploy accepted any ARN as `role_arn`, and `_sync_role_policy` then derived the role name from it and PutRolePolicy-**replaced** `loom-agent-base-policy` on it, discarding the original statements. The agent was group-checked; the role never was.

`routers/utils.py`'s `bindable_role_arns()` defines entitlement as either (a) the ARN has a `ManagedRole` row the caller can reach, or (b) the ARN is already the execution role of an agent the caller can reach. Clause (b) is load bearing: the roles Loom creates for itself during deploy get no `ManagedRole` row, so requiring (a) alone would break redeploys. `assert_role_arn_bindable()` runs at all four deploy entry points, the discovery listing is filtered through the same set — it was also an inventory of the account's IAM to any `agent:read` holder — and `_sync_role_policy()` now takes the caller and re-checks, which is what stops an agent that had a foreign role attached *before* this fix from still reaching the IAM write.

**Discovery endpoints must be absolute https URLs.** `fetch_discovery()` copied `authorization_endpoint` out of the OIDC document verbatim. `routers/security.py` concatenates it into `authorize_url`, and the SPA assigns that to `window.location.href` — so a `javascript:` URL in a discovery document executed in Loom's own origin, where the session tokens live in `sessionStorage`. Registering the authorizer takes `security:write` and clicking Link Account takes `agent:read`, so the plant and the trigger are different roles. `require_https_endpoint()` is applied to `jwks_uri`, `authorization_endpoint` and `token_endpoint` at discovery time, again in `security.py` before the URL is handed to the SPA (rows written before the check existed are still in the database), and a third time in the frontend's shared `getAuthorizerLinkAuthorizeUrl()` — placed in the fetcher rather than in each caller so a new navigation site cannot miss it, since the browser is where the consequence lands.

**Secret paths are not logged either.** None of these paths *is* a secret — `loom/mcp/42/oauth2-client-secret` is a deterministic function of the row id and the secret kind. But it carries no information an operator does not already get from "the OAuth2 client secret for MCP server 42", and a log line that looks like a credential locator costs a scanner finding and a security review every time someone reads it. So the paths are out of the logs and the resource is named instead.

`services/secrets.py` logs the secret *kind* (`admin-api-key`, `oauth2-client-secret`) rather than the path, which keeps the only operationally useful part — confirmation that a write or delete actually happened. `_kind()` matches against a vocabulary rather than taking the trailing path segment, because the per-user paths end in the user's subject identifier (`loom/authorizers/3/user-tokens/{sub}`) and "last segment" would have swapped a credential locator for a user identifier; an unrecognised shape degrades to `"secret"` rather than echoing whatever it ends with. `SecretWriteError` no longer embeds the path for the same reason — the AWS error code is the diagnostic, and every caller has better context than a path.

Callers name the resource: `services/mcp.py` logs via `_resource_label()` ("MCP server 42"), the two delete loops in `routers/mcp.py` label *which* location failed (`current` / `legacy`) instead of printing both paths, and `scripts/migrate_oauth2_secrets.py` already had the row id so the path was pure redundancy. `services/authorizer_linking.py` was logging a full per-user token path at INFO on every lookup, including the user's subject identifier, while the failure branch two lines below already reported both — that is now a DEBUG line naming only the authorizer.

`TestLogsDoNotContainSecretPaths` holds it: no `logger.*` call anywhere in `app/` or `scripts/` may take a secret-name builder as an argument, and `_kind()` is asserted never to echo an identifier.

**An AWS error cannot carry a secret into the logs.** AWS validation errors commonly echo the offending parameter back — `Value 'xxx' at 'clientSecret' failed to satisfy constraint` is a shape that appears across services. So an exception raised by a call whose *request body* held a secret can itself contain that secret, and any caller that logs the exception writes it to CloudWatch.

An AST sweep found 20 such sites: `logger.*(..., e)` inside an `except` whose `try` had just passed a secret to `store_secret`, `create_oauth2_credential_provider`, `create_api_key_credential_provider` or similar — mostly on the agent deploy path in `agents.py`. Fixing them individually would have meant threading the secret value into 20 log statements and getting it right again for the twenty-first.

So the scrub happens where the secret is *sent*, which is the only layer that knows what to remove. `services/secrets.py`'s `store_secret` and `services/credential.py`'s provider creators catch the AWS exception and re-raise `SecretWriteError` / `CredentialProviderError` with the value replaced by `<redacted>` via `services/redaction.py`. Everything downstream is then safe whatever it logs. Two details matter: the re-raise uses `from None`, because `from e` would leave the unscrubbed message reachable through `__cause__` and rendered by any `exc_info=True`; and the credential provider's retry loop scrubs before its *first* log rather than only at the final raise, since it logs once per attempt. The secret's name and the AWS error code are kept, so the diagnostic survives.

Three categories were checked and found safe rather than fixed: `services/secrets.py` logs only secret *names* (`loom/mcp/{id}/oauth2-client-secret`), never values — which is what the endpoint-change and deletion warnings emit; `get_cognito_token` raises `httpx.HTTPStatusError`, whose string is the status and URL with no response body, so the three sites logging it cannot leak the client secret in its POST form body; and `services/litellm.py`'s `exc_info=True` does not render frame locals, so the master key in the request header does not reach the log.

Whether AWS echoes these particular values is unverified. It is not something to establish from a production log.

**No secret is stored in the database.** `McpServer.oauth2_client_secret` and `A2aAgent.oauth2_client_secret` were plaintext columns — the only secrets in Loom not in Secrets Manager. Every other secret already went there with just a flag or an ARN persisted: authorizer and identity-provider client secrets, the LiteLLM master key, MCP admin and per-user API keys. The two exceptions made a database dump or RDS snapshot directly credential-bearing, left secret reads with no CloudTrail trail, and made the `admin:write` export routes a plaintext database read rather than an audited Secrets Manager call.

Both now live at `loom/mcp/{id}/oauth2-client-secret` and `loom/a2a/{id}/oauth2-client-secret`, keyed on the row id for the same reason the admin API key is: the id is server-assigned and immutable, so renaming or repointing a row cannot retarget the lookup. `resolve_oauth2_client_secret()` is the single read path, used by the M2M and OBO token exchanges, the A2A token exchange, the six agent-deploy snapshot sites and both export routes. `has_oauth2_secret` became a real column, since the response flag used to be derived from the column's own presence.

Existing deployments upgrade without anyone re-entering anything: the resolver falls back to the legacy column and migrates the value across on first use, so the plaintext copy stops existing the moment it is used. Lazy migration only moves what gets used, so `backend/scripts/migrate_oauth2_secrets.py` does every row at once — dry-run by default, and it writes to Secrets Manager and reads back before clearing a column, so an interrupted run cannot lose the only copy of a credential. The columns are retained read-only; `TestLoomCannotWriteIam` asserts no *new* secret-bearing column appears and that nothing assigns anything but `None` to these two.

The column guard is narrowed two ways so it is a rule rather than a keyword guess: only textual columns can hold a secret, which excludes `invocations.input_tokens` (an INTEGER count) and `agent_config_entries.is_secret` (a BOOLEAN flag); and names denoting a *reference* rather than a value are allowed, covering `client_secret_arn`, `api_key_header_name` and `token_endpoint`.

**Two latent model-registration bugs fixed alongside.** `app/models/__init__.py` never imported `a2a.py` or `identity_provider.py`, so `import app.models` left `a2a_agents` and `identity_providers` out of the SQLAlchemy metadata. It worked in the running app only because a router imports them, but any standalone script relying on `app.models` saw no such table — which is how the new migration script first failed. This is the same latent bug that was fixed for `evaluation.py` in v1.8.1 and left in place for these two.

**Two smaller fixes from the same review.** `POST /api/security/authorizers/{a}/credentials/{c}/token` moved from `security:read` to `security:write`: it does not read configuration, it mints a usable bearer token for a machine identity, and `g-admins-demo` holds `security:read` without `security:write` — so under the read scope the group documented as "read-only to all pages" could mint a credential another admin had configured. And the Okta logout URL now sends `id_token_hint` only when the token's own `iss` claim names the same host as the logout endpoint. That is the non-circular form of the check: allowlisting `issuer_url` against the deployment's trusted hosts would be meaningless, because `get_trusted_oauth_hosts()` is built from `issuer_url`. If an administrator repoints it after tokens were issued, the hosts stop matching and the token is withheld; sign-out still proceeds without the hint, as the Entra branch already did.

**A stored credential does not follow a moved endpoint.** The admin API key is keyed on `server.id`, so it survived a change of `endpoint_url` — and `mcp:write` is enough to make that change. `test-connection`, `tools/refresh` and `tools/invoke` each resolve the key and send it as an `Authorization: Bearer` header to whatever host the URL now names, so repointing a server re-aimed a credential another admin had configured. On an OBO invocation the same endpoint also receives every invoking user's downstream access token.

Repointing a server is a legitimate admin action; silently re-aiming its stored credential at the new host is not. `update_mcp_server` now clears the admin API key and the OAuth2 client secret when `endpoint_url` changes, and `update_a2a_agent` does the same for `base_url`. Supplying a new secret in the same request wins, so moving a server and giving it the new host's credential is still one call, and an idempotent PUT that rewrites the same URL changes nothing.

Note what this does **not** claim to fix: an MCP server is supposed to receive the token, and there is no allowlist on the data-plane `endpoint_url` the way `is_trusted_oauth_host()` constrains the OAuth token endpoint. The asymmetry is deliberate — a token endpoint has a knowable set of legitimate hosts and an MCP endpoint does not — but it means the protection here is "the credential must be re-entered against the new host", not "the credential cannot leave".

**Smaller leak paths closed in the same pass.** `services/mcp.py` logged the *entire* OBO claim set at INFO on every exchange, putting the invoking user's `email`/`upn`/`oid`/`groups` into the backend log on a hot path; it now logs the same named subset as the adjacent subject-token line. The SSE `token_info` event was relayed verbatim from the agent, and two of that queue's producers accept arbitrary content from a remote MCP server (a `__TOKEN_INFO__`-prefixed tool result, and an MCP `logging` notification named `token_info`), so a third-party server could put whatever it liked into a privileged-looking UI panel — `_safe_token_info()` re-applies the harness's own allowlist on receipt. `POST /api/auth/token` is unauthenticated by necessity and relayed the identity provider's raw response body to an anonymous caller; it now returns a generic message and keeps the body in the log. `POST /api/agents/{id}/credential-providers` returned the raw boto3 exception from a call whose kwargs carry the client secret — unverified whether AgentCore echoes it, and cheap to make safe either way.

**Verified not to be leaks**, recorded so they are not re-investigated: every model's `to_dict()` exposes `has_*_secret` booleans or ARNs rather than values; `/config` masks `is_secret` entries with `********`; the agent harness logs a truncated SHA-256 fingerprint instead of a token and redacts `token_info` stream lines; `is_trusted_oauth_host()` gates every client-credentials, OBO, refresh and code-exchange call; no token ever enters a URL except the RFC-sanctioned `id_token_hint` on Okta logout; there is no `EventSource`, so SSE uses `fetch` with an `Authorization` header rather than a query parameter; the WebSocket token travels in the first frame body, not the URL; all tokens live in `sessionStorage` and nothing sensitive is in `localStorage`; and there is no `document.cookie` use at all.

**Open design questions, deliberately not changed here.** The `id_token` in the Okta logout query string goes to a host taken from `IdentityProvider.issuer_url`, which is scheme-checked but not host-allowlisted. `McpServer.oauth2_client_secret` and `A2aAgent.oauth2_client_secret` are plaintext database columns, unlike every other secret in the system, which makes a database dump directly credential-bearing and makes the `admin:write` export routes a plaintext read. And `POST /api/security/authorizers/{a}/credentials/{c}/token` mints a usable bearer token under `security:read` — a read scope that produces a credential.

**Every server-supplied navigation target is scheme-checked, not just the reported one.** The report named Link Account's `authorize_url`. Fixing that and then sweeping for other sinks found three more fed by the same IdP-derived values, and the most exposed of them was not the reported one: `/api/auth/config` is **unauthenticated** and serves `authorization_endpoint` (assigned to `window.location.href` to begin the login redirect) and `issuer_url` (used to build the IdP logout URL), so that sink needs no scope at all, where the reported one needed `agent:read`.

All four now go through one guard on each side. `routers/auth.py`'s `_navigable_endpoints_are_safe()` validates both fields before the active provider is served, and returns False rather than raising so a bad row costs only the external login path and falls through to the Cognito default, instead of 500ing the endpoint the whole UI boots from. On the client, `lib/navigation.ts` provides `assertHttpsUrl()` / `navigateToExternal()`, used by the login redirect, both logout redirects and the Link Account fetcher — placed in a shared helper rather than per caller so a new redirect site cannot miss it.

`sessionStorage`-sourced redirect targets (`loom_link_return_url`) are deliberately not covered: the app sets them itself and they are same-origin paths, so a check there would guard against an attacker who already has script execution.

**The SSRF guard covers local aliases, not just loopback.** `_is_always_disallowed_ip()` checked `is_loopback`, `is_link_local`, `is_multicast`, `is_reserved` and `is_unspecified`. Only `0.0.0.0` itself is `is_unspecified`, so the rest of `0.0.0.0/8` passed — and Linux treats `connect()` to any address in that block as local, making `http://0.0.0.1:<port>/` a working alias for a listener the same guard refused on `127.0.0.1`. The IPv6 metadata address `fd00:ec2::254` passed for the same reason: it is a unique-local address, so it is only `is_private`. Both are named explicitly now. Deliberately **not** by adding `is_private`: RFC 1918 and ULA addresses are legitimate targets at the permissive guard level, because the backend runs in private subnets specifically to reach VPC-internal MCP servers and A2A agents, so each locally-routable range that is not a valid target has to be enumerated.

**ADK honours HITL approval policies.** `require_approval` policies were enforced for Strands agents and silently ignored for `agent_framework=adk`. Two bugs compounded: `ApprovalPolicyMatcher()` seeded itself from `LOOM_APPROVAL_POLICIES`, an env var deploy never sets, and `build_agent` attached the per-tool confirmation predicate only `if approval_matcher.policies:` — so with an empty env the predicate was never attached at all; and `handler.invoke` never read `payload["approval_policies"]`, which is where Loom actually ships the enabled policies (`services/agentcore.py`), and which Strands' handler assigns onto its loop hook on every call. A policy an operator enabled in the UI therefore did not pause ADK tools, and because no `approval_request` was ever raised, the owner check on approve/deny never ran either.

The predicate is now attached unconditionally — it is a no-op while the matcher holds no policies, so attaching it always costs nothing and leaves the gate able to turn on later — `build_agent` returns the matcher, and `handler.invoke` assigns the payload's policies onto it per invocation, clearing them when a payload carries none so one caller's policies cannot linger in the warm singleton into the next caller's invocation.

**Why fixes kept being partial, and what now prevents it.** Five reports from one researcher landed on Loom in sequence, and they were not five unrelated bugs. They were one bug class — a caller-supplied key reaching a resource the caller is not entitled to — plus four distinct ways a fix for it failed to be complete. Each failure mode now has a mechanical guard in `tests/test_authorization_invariants.py`, because the thing being guarded is *believing a rule holds everywhere it should*, which prose cannot check.

1. **Duplicated policy.** `invoke_agent_endpoint` carried an inlined copy of `check_resource_group_access`. Making the shared helper fail closed on untagged resources left the copy failing open, so untagged agents stayed invokable for two releases *after* the release that announced untagged resources were locked down. → `TestGroupRuleIsNotReimplemented` fails if any module outside a justified allowlist derives a caller's permitted `loom:group` values by hand.
2. **Fixed at the reported site, not across the class.** Credential provider names were re-keyed off a mutable display name; the structurally identical MCP admin API key was not, and returned as its own report two releases later. → `TestSecretPathsAreBuiltInReviewedPlaces` confines Secrets Manager path construction to a small allowlisted set of modules, each entry stating why its keying is safe, so "is this keyed on something the caller can change?" is answered in review.
3. **Unverified claims.** A docstring asserted "list routes already filter by `loom:group`" and the guard-test allowlist cited that as its justification. Neither was true of the MCP, connector or A2A listings — so the test written to catch the class exempted the class. → Every allowlist in both guard files is now asserted to contain no **stale** entries (a renamed function cannot leave a silent exemption) and no **unnecessary** ones (adding the check forces the entry's removal, so an exemption cannot outlive its justification). Writing those assertions immediately found three entries naming functions that do not exist and three more that were not needed.
4. **A guarantee stated more broadly than the code delivered.** The release notes promised untagged resources were super-admin-only. On the read paths they were; on invoke they were not. → `TestUntaggedResourcesFailClosedEverywhere` asserts the guarantee per route across every resource family, with the caller holding *every scope* but no super-admin group — so a 403 can only come from the group rule — plus a positive control proving the same request succeeds for a resource in the caller's own group. Without that control the test would pass for the wrong reason, which is a mistake made earlier in this series.

Two further instances of the class were found by these guards rather than by a report. `pull_cost_actuals` filtered **memories** with `if group: ... elif not t-admin: ...`, so passing `?group=` skipped the caller's own restriction and returned another group's memory spend — the agents half of that same route had been fixed earlier, the memories half had not. And the per-user MCP secret path was being built in three places; all three now come from `services/mcp.py`'s `user_api_key_secret_name`, since independent copies of a path are how keying decisions drift apart.

Checked and found **not** vulnerable, recorded so the question is not reopened: authorizer and identity-provider client secrets are also stored under a name-derived path, but both `AuthorizerConfig.name` and `IdentityProvider.name` are `unique=True`, so no cross-group collision is possible, and every read goes through the stored `client_secret_arn` rather than re-deriving the path from the mutable name.

**The primary-key bind guard, and the four gaps it found.** `TestPrimaryKeyBindsAreAuthorized` in `tests/test_router_authorization_guard.py` parses every router with `ast`, resolves model import aliases (so `A2aAgent as A2aAgentModel` is caught), and finds every function that uses a group-owned model's `.id` inside a `filter()`. Each such function must perform at least as many group checks as the number of distinct group-owned models it binds, or appear in `ALLOWED_PK_BIND` with a reason.

The pre-existing module-level guard asked only "does this file query a scoped model at all", which is coarse enough that one exemption covers a whole router — that is precisely how the agent deploy binds inherited `agents.py`'s existing pass for four releases. Three properties make this one harder to fool: checks are **counted per distinct bound model**, because a single check used to satisfy a function binding three of them (removing one branch's check from `registry.create_record` left the old form green); the allowlist is asserted to contain **no stale** entries (a renamed function cannot leave a silent exemption) and **no unnecessary** ones (adding a check to an exempt function forces its entry to be removed, so an exemption cannot outlive its justification); and the detector **self-tests** against a function shaped like the bug, since a guard that silently matches nothing is worse than none. `TagProfile` is deliberately outside `GROUP_OWNED_MODELS` despite having `get_tags()`: a profile's tags are its payload, not a record of who owns it, so an ownership check against those values would be coincidence rather than authorization.

Running it surfaced four instances of the reported bug class that no report named:

1. **`invoke_agent_endpoint` carried an inlined copy of `check_resource_group_access`** whose `if agent_group:` skipped the entire check for an untagged agent. When the shared helper was changed to fail closed on untagged resources, the copy kept failing open — so an untagged agent remained invokable by anyone holding `invoke`, contradicting the documented fail-closed behaviour. Replaced with a call to the helper, so the rule lives in one place.
2. **`connector_ids` on both the HTTP and WebSocket invoke paths** resolved MCP servers from the request body with no group check — the same bind as the deploy paths, on the hot path, and the resolved server's OAuth secret or admin API key is handed to the runtime for that invocation. Both now call `assert_bindable`.
3. **`registry.create_record`** resolved a caller-supplied `resource_id` to an MCP server, A2A agent or agent with no group check, letting a `registry:write` holder submit another group's resource into the registry. All three branches now check. `get_skill_dependents` reverse-looks-up agents by skill record and named every one regardless of caller; it now passes through `filter_visible_resources`.
4. **`credential_id` on the invoke path** resolved an `AuthorizerCredential` by primary key and used its `client_secret_arn` to mint an M2M token that is then handed to the agent. An `AuthorizerCredential` carries no `loom:group` of its own, so the owning `AuthorizerConfig` is what gets checked. Note the consequence: a deployment whose authorizer configs are still untagged will find `credential_id` invokes refused until those configs are tagged, since untagged resources fail closed.

**MCP admin API keys are keyed on the server id, and cross-group name collisions are refused.** An MCP server's admin API key was stored at `loom/mcp/{name}/admin-api-key` and resolved by `server.name` — a mutable display string with no uniqueness constraint. `update_mcp_server` `setattr`s `name` and `endpoint_url` freely, and a rename does not move the secret, so a caller holding `mcp:write` could create a server, rename it onto another group's display name, point `endpoint_url` at a host they controlled, and call `POST /{id}/tools/invoke`: `resolve_api_key` resolved the *victim's* secret and `svc_invoke_tool` sent it to the attacker's endpoint as a Bearer header. Writing an `api_key` onto the colliding row overwrote the victim's secret instead, giving the same bug an integrity direction.

Mandatory `loom:group` tags and the fail-closed untagged check reduced the original report's prerequisites but did not close this: the attacker does not need an untagged row, because a row legitimately tagged with their *own* group passes `check_resource_group_access` and the name collision does all the work. Those checks gate the row; the vulnerability was in the secret's name. This is the same structural class as the credential-provider bug below — a secret in a flat namespace keyed on a caller-controlled mutable string — and takes the same fix.

`services/mcp.py` now derives the location from `admin_api_key_secret_name(server_id)` (`loom/mcp/{id}/admin-api-key`), which a rename cannot retarget. `_assert_name_available()` in `routers/mcp.py` refuses a create or rename whose name is held by a server in a *different* `loom:group`, comparing group tags directly so the rule binds super-admins too — a super-admin colliding would not escalate their own access, but would make another group's name ambiguous. The check is scoped to the security boundary rather than enforced as global uniqueness, since two servers in one group share an owner.

Pre-migration secrets stay readable through `_resolve_legacy_admin_api_key()`, which requires a `db` session, refuses when more than one row shares the name (an ambiguous name is how the attack aimed this lookup, so it denies rather than guesses), and migrates the value onto the id-keyed path before returning it. `resolve_api_key()` consults the legacy location only when passed a session, so a caller that cannot prove the name is unambiguous gets nothing.

Per-user keys (`loom/mcp/{name}/api-key/{sub}`) are deliberately left name-keyed: that path is written into `AGENT_CONFIG_JSON` at deploy time and read by the deployed agent itself, so re-keying it would strip per-user keys from every already-deployed agent until redeployed. It is safe name-keyed now that cross-group collisions are refused, and the trailing `user_sub` already confines each entry to its owner.

**List routes filter by `loom:group`.** `list_mcp_servers`, `list_connectors` and `list_a2a_agents` filtered only on `registry_status`, so every group's rows were listed to any holder of `mcp:read`/`a2a:read` — which is where the attack above got the victim's display name. All three now pass through `filter_visible_resources()` in `routers/utils.py`, which drops rows the caller's group does not reach rather than failing the whole response. `check_resource_group_access`'s docstring asserted that list routes already filtered by `loom:group`; that was false for exactly these three, and the guard test's `ALLOWED_RAW_QUERY` entries repeated the claim as their justification — which is how a test written to catch this class exempted it. Both now describe what the code does.

`list_agents` and `list_memories` were the last two routes applying their `loom:group` filter only `if "t-admin" not in user.groups`, and both now go through `filter_visible_resources()` like every other listing. Two things were wrong with the old form:

- **Cross-group listing.** Every `t-admin` got the unfiltered query. An earlier note here claimed this meant "a scoped admin group still lists every group's rows", which overstated it: the scope gate already stops most domain admins, since only `g-admins-demo` and `g-admins-super` hold `agent:read`, and only they plus `g-admins-memory` hold `memory:read`. So the real exposure was `g-admins-demo` on both listings — arguably within its documented "read-only to all pages" role — and `g-admins-memory` on memories, which is not documented as reading across groups and was the genuinely unintended case. Both are narrowed now: every non-super caller sees only its own groups, which makes the listing agree with fetch-by-ID, where the same row already returned 403.
- **Untagged rows.** The old comment said `t-admin` "see[s] ALL resources including untagged", which directly contradicted the published guarantee that an untagged resource is visible to super-admins alone. That one was not a product decision — nobody chose it, and `check_resource_group_access` had enforced the opposite on fetch-by-ID since the fail-closed change.

`TestUntaggedResourcesFailClosedEverywhere` now covers **list routes as well as single-object ones**, for agents, memories, MCP servers and A2A agents: an untagged row must be absent from every listing, another group's row must be absent, the caller's own row must be present (so the filter cannot pass by emptying the page), and a super-admin must still see untagged rows. The original version of that class only exercised fetch-by-ID and invoke, which is exactly why it never saw this — a guarantee has to be asserted on every route shape that can expose the resource, or the untested shape is where it drifts.

Note that the existing suite did not react to narrowing these two routes, because almost every test authenticates through the local-dev bypass as `g-admins-super`, which still sees everything. The behaviour change is only visible to the tests that deliberately act as a non-super admin.

**Breaking change for operators:** `g-admins-demo` and `g-admins-memory` now see only their own group's agents and memory resources in listings, and untagged resources disappear from every non-super-admin listing. Nothing was deleted; tag the resources or use a super-admin account.

**Credential provider names are keyed on the agent id, and collisions fail closed.** Credential provider names live in one flat namespace per AWS account, shared by every `loom:group`, but they were derived entirely from caller-controlled strings — `loom-{agent name}-mcp-{server name}`, `loom-{agent name}-a2a-{a2a name}`, `loom-{agent name}-litellm-key`, or, from `POST /api/agents/{id}/credential-providers`, the caller's raw `request.name`. Where the name then collided with an existing provider, `create_oauth2_credential_provider`/`create_api_key_credential_provider` caught the `ValidationException`, logged "already exists, updating instead", and called `update_*_credential_provider` with the caller's own `clientSecret`/`apiKey`. An operator in one group could therefore name an agent and MCP server to match another group's derived name and silently replace the client secret that group's agents authenticate downstream with — a cross-group credential overwrite from `agent:write` alone.

Both halves are fixed. `services/credential.py`'s new `credential_provider_name(agent_id, agent_name, kind, resource_name=None)` builds every name as `loom-{agent name}-{agent id}-{kind}[-{resource name}]`, sanitized to `[a-zA-Z0-9.-]` (which the harness's `apiKeyArn` regex requires anyway). The agent id is what makes this safe: it is server-assigned and an agent belongs to exactly one group, so no caller can derive a name that lands on another group's provider. And `allow_update` now defaults to `False`, raising `CredentialProviderNameInUse` instead of overwriting. Only the deploy/redeploy paths pass `allow_update=True`, and they may do so precisely because the id in the name means a collision can only be their own leftover from an earlier failed deploy (`AGENT_CONFIG_JSON` is written on success, so a deploy that fails after provider creation leaves one behind with no record of it — failing closed there would wedge the agent permanently). `POST /api/agents/{id}/credential-providers`, whose name is caller-supplied, keeps the default and returns `409` on collision; the caller's `name` becomes a label inside `loom-{name}-{agent id}-custom`.

Two latent bugs in the same paths were fixed alongside, deliberately together: that endpoint passed `scopes=` to `create_oauth2_credential_provider`, which has no such parameter, so it raised `TypeError` and returned `502` on every call (`scopes` is stored on the local `CredentialProvider` row only and was never sent to AgentCore) — fixing that without namespacing first would have armed it as a direct overwrite gadget. And `_update_harness_background` imported `create_oauth2_credential_provider` from `app.services.deployment`, which does not define it, so adding an OAuth2 MCP server to an existing harness agent always failed with `credential_creation_failed`; the module-level import from `app.services.credential` is used now.

Existing agents are unaffected: deletion and redeploy read the provider name from `AGENT_CONFIG_JSON`, which still holds the old un-namespaced form, and the reconciliation in `_update_deploy_agent_background` creates the new name and deletes the old one as a `removed_cps` entry on the next redeploy.

**Single-object fetch-by-ID also enforces `loom:group` (H1-3954919):** the tag filtering above was applied consistently on list routes, but every single-object fetch-by-ID helper — `routers/utils.py`'s `get_agent_or_404()` and the inline `Memory` lookups in `memories.py` — resolved by ID alone with no group check, so any authenticated user could read/update/delete/export another group's agent or memory resource (and mint a live Cognito token for any agent via `POST /api/agents/{id}/token`) simply by guessing/enumerating IDs. `routers/utils.py`'s new `check_resource_group_access(resource, user, resource_label)` — the same logic the agent invoke route (`invocations.py`) already applied — is now called from `get_agent_or_404()` (fixing all 21 call sites across `agents.py`/`credentials.py`/`integrations.py` in one place, since `CredentialProvider`/`Integration` records are scoped to their parent agent), `memories.py`'s new `_get_memory_or_404()` (6 call sites), and directly in the `/api/agents/{id}/token` handler. Semantics match the existing invoke-route reference exactly: `g-admins-super` bypasses; an untagged resource is accessible to anyone (consistent with list-route behavior for untagged resources); every other admin group is confined to its own `g-admins-*` group; users are confined to the union of their `g-users-*` groups. The pre-existing demo-admin-specific delete restriction in `memories.py`/`agents.py` (`g-admins-demo` confined to `loom:group=demo`, including untagged resources) is unaffected and still runs as an additional, stricter check afterward.

Not covered by this fix, flagged as separate follow-ups rather than folded in mechanically: `security.py`'s `ManagedRole` single-object routes (`get_role`/`update_role`/`delete_role`) share the same shape but are gated by `security:read`/`security:write`, which every persona holding `agent:write` also holds today — not currently exploitable, but worth the same fix if a future persona breaks that pairing. `AuthorizerConfig`/`AuthorizerCredential`/`PermissionRequest` are globally scoped by design (no `loom:group` concept), so applying a group check there would be a behavior change needing a product decision, not a bug fix. `McpServer`/`A2aAgent` have no `loom:group` tag concept at all today — `POST /mcp/{id}/tools/invoke` resolving a server's admin API key regardless of caller is a real gap, but closing it requires deciding whether MCP servers/A2A agents should get a group-ownership model in the first place, which is a larger, separate change.

**View As mode:** Super-admins can switch to view the system as a different user persona (e.g., `demo-admin`, `demo-user`). The frontend sends a `group` parameter to backend endpoints, which filters resources as if the admin belonged to that group. This enables super-admins to validate permission models without switching accounts.

### `services/net_guard.py`

SSRF-safe HTTP fetchers for outbound calls to user-supplied URLs, at two guard levels reflecting different trust models:

- `safe_get(url, headers=None, timeout=10) -> Response`, `safe_post(url, data=None, headers=None, timeout=10) -> Response` — strict, public-addresses-only. Forces HTTPS, resolves the hostname via DNS, and rejects private/loopback/link-local (including the `169.254.169.254` cloud metadata address)/multicast/reserved/unspecified addresses. Used for OAuth2/OIDC discovery ("well-known") documents and the token endpoints they advertise (`mcp.py`/`a2a.py`'s `_get_oauth2_token`/`_get_obo_token`), since both are attacker-influenced (the well-known URL comes from an MCP server/A2A agent registration, and the discovery document supplies the token endpoint) and legitimate identity providers are always public internet-facing services.
- `guarded_get(url, headers=None, timeout=10, follow_redirects=True) -> Response`, `guarded_post(url, json=None, headers=None, timeout=10, follow_redirects=True) -> Response` — permissive, allows both `http`/`https` and private (RFC 1918/RFC 4193) addresses, but still always blocks cloud metadata, loopback, link-local, multicast, reserved, and unspecified addresses. Used for the actual MCP server `endpoint_url` / A2A agent `base_url` connection targets — unlike OAuth infrastructure, reaching a private/VPC-internal address is a legitimate, supported use case here (the backend ECS service runs in private subnets specifically to support VPC-internal MCP servers and A2A agents).
- Both levels resolve the hostname once via `socket.getaddrinfo` and pin the outbound connection to that validated IP (rather than letting the HTTP client re-resolve at connect time), preventing DNS-rebinding between the check and the actual connection. `guarded_get`/`guarded_post` additionally re-validate every redirect hop before following it (up to 5 hops, `SSRFBlockedError` beyond that) — an initial target passing validation does not grant a later cross-host redirect target a pass.
- `SSRFBlockedError(ValueError)` — raised by both levels when a URL is blocked; callers catch it separately from generic connection errors to log/return a distinct "blocked" outcome without ever surfacing the disallowed target's response body.
- **`get_trusted_oauth_hosts() -> set[str]`, `is_trusted_oauth_host(url, trusted_hosts) -> bool`** — closes the residual gap `safe_get`/`safe_post` leave on their own: both still permit *any* public HTTPS host, so a well-known URL/discovery document (attacker-influenced input at `mcp:write`/`a2a:write`, not the platform's top trust level) could still redirect a client-credentials exchange or an on-behalf-of token exchange to a public server the caller controls — handing over the resource's own `client_secret` (M2M) or, more seriously, another user's real access token (OBO). `get_trusted_oauth_hosts()` builds the set of hostnames from `IdentityProvider.issuer_url` and `AuthorizerConfig.discovery_url` — both populated only via admin flows gated by a higher-trust scope than `mcp:write`/`a2a:write` — via its own short-lived `SessionLocal()` session (module-level pattern, matching `model_catalog.py`/background tasks elsewhere in this codebase); a DB failure fails closed to an empty set rather than raising. `mcp.py`'s `_get_oauth2_token`/`_get_obo_token` and `a2a.py`'s `_get_oauth2_token` call this immediately after resolving `token_endpoint` from the discovery document and refuse to proceed (logging a warning, returning `None`) if the resolved host isn't in the trusted set — before any secret or user token is sent. One operational consequence: a brand-new downstream OAuth2 provider for a single MCP server/A2A agent must first be registered as an Authorizer config (Security tab) or Identity Provider (Settings) before OBO/M2M to it will work — a deliberate one-time step, not a bug.
- **Coverage beyond MCP/A2A:** the same two guard levels were retrofitted onto every other place the backend makes an outbound OAuth2/OIDC call that was still using raw `urllib.request`/`httpx` with, at most, a scheme check (`oidc.require_https_url`, now removed as dead code once every caller moved to `safe_get`/`safe_post`). `services/oidc.py`'s `fetch_discovery()` (well-known documents for `AuthorizerConfig.discovery_url`/`IdentityProvider.issuer_url`) and `services/jwt_validator.py`'s `_get_jwks()` (JWKS endpoints — `jwks_uri` comes from the discovery document itself, so it's attacker-influenced whenever the issuer is) now call `safe_get`. `services/token.py`'s `get_oauth2_token()` (generic OIDC client-credentials), `services/authorizer_linking.py`'s `resolve_access_token()`/`exchange_code_for_tokens()` (per-user refresh-token/auth-code exchange), and `services/cognito.py`'s `get_cognito_token()` now call `safe_post`, and the two functions whose `token_endpoint` comes from a discovery document they resolved themselves (`token.py`, `authorizer_linking.py`) also gate on `is_trusted_oauth_host()`/`get_trusted_oauth_hosts()`, identical to the `mcp.py`/`a2a.py` fix, since a compromised or malicious discovery response is the same attack regardless of which caller triggered the fetch. `routers/auth.py`'s `/api/auth/token` handler posts to `idp.token_endpoint` (a value already vetted at IdP-registration time, not re-resolved per request) via `safe_post` for the DNS-pinning/IP-validation defense-in-depth, without an additional trust-host check. Deliberately left unguarded: `services/litellm.py`/`model_catalog.py`'s calls to the LiteLLM proxy `base_url` — that value is `admin:write`-gated (as of the settings-scope tightening below, a strictly higher trust tier than `security:write`, held only by `g-admins-super`), a single global deployment setting rather than a per-resource attacker-influenced field, and is documented to legitimately point at `http://localhost:<port>` during local development (an SSM tunnel to the proxy) — `net_guard`'s guards unconditionally block loopback, so applying them here would break that supported flow without closing a real gap.

### `services/mcp.py`

MCP server connection, tool discovery, and invocation:

- `test_mcp_connection(server, api_key=None) -> dict` — Sends an `initialize` JSON-RPC request to verify the server is reachable. Supports OAuth2, API key, and unauthenticated connections.
- `fetch_mcp_tools(server, api_key=None) -> list[dict]` — Calls `tools/list` JSON-RPC method and returns tool metadata (name, description, input_schema).
- `invoke_mcp_tool(server, tool_name, arguments, api_key=None) -> dict` — Calls `tools/call` JSON-RPC method to invoke a specific tool with arguments.
- `resolve_api_key(server, user_sub=None) -> str | None` — Resolves API key from Secrets Manager. Admin key for admin context (`loom/mcp/{name}/admin-api-key`), user key for user context (`loom/mcp/{name}/api-key/{user_sub}`).
- `_build_headers(server, api_key=None, user_token=None) -> dict` — Builds request headers with auth injection. For API key auth, uses `api_key_header_name` to set the correct header; `Authorization` headers are prefixed with `Bearer`. For OAuth2 auth with `delegation_mode="obo"` and a caller-supplied `user_token` (the raw bearer token from the inbound request's `Authorization` header — extracted by the router only when `delegation_mode` is `"obo"`), calls `_get_obo_token()`; otherwise (M2M) calls `_get_oauth2_token()`. Both resolve `token_endpoint` from `oauth2_well_known_url` via `safe_get`/`safe_post` and then require `net_guard.is_trusted_oauth_host()` before sending anything to it — see `services/net_guard.py` above.
- `_call_streamable_http()`, `_initialize_session()`, `_call_sse()`, `_call_mcp()` — Transport methods accepting optional `api_key` parameter. All POST to `server.endpoint_url` via `net_guard.guarded_post` (SSRF-guarded, private/VPC addresses allowed) rather than a raw `httpx.post`, since `endpoint_url` is user-supplied at MCP server registration; `SSRFBlockedError` is caught and logged as a blocked connection (returns `None`, same as any other connection failure).

### `services/a2a.py`

A2A Agent Card fetching and connection testing:

- `fetch_agent_card(base_url: str, auth_headers: dict | None) -> dict` — fetches the Agent Card from the well-known endpoint via `net_guard.guarded_get` (SSRF-guarded, private/VPC addresses allowed, since `base_url` is user-supplied at A2A agent registration). Standard A2A agents use `/.well-known/agent.json`; AgentCore agents try `/.well-known/agent-card.json` first; Salesforce Agentforce agents use `/v1/card` via `_fetch_salesforce_agent_card`, also guarded. Raises `ValueError` on HTTP errors, invalid JSON, or an `SSRFBlockedError` (mapped to a `ValueError` without echoing any part of the blocked target's response). Error messages for non-2xx statuses use a fixed friendly string rather than the response body, since the connection target is attacker-influenced and echoing response content back to the caller would make the endpoint usable as a blind-SSRF response oracle.
- `parse_agent_card(card_json: dict) -> dict` — extracts structured fields (name, description, version, provider, capabilities, authentication, skills, etc.) from raw Agent Card JSON.
- `sync_skills(db: Session, agent_id: int, skills: list[dict])` — synchronizes skills from Agent Card to the database. Adds new skills, removes stale ones.
- `test_a2a_connection(agent) -> dict` — acquires OAuth2 token if configured and fetches the Agent Card, returning success/failure with details.

### `services/secrets.py`

- `store_secret(name: str, secret_value: str, region: str)` — creates or updates a secret.
- `get_secret(name: str, region: str) -> str` — retrieves a secret value with a 5-minute in-memory cache.
- `delete_secret(name: str, region: str)` — deletes a secret.

### `services/litellm.py`

LiteLLM proxy master-key resolution and per-agent virtual key vending — see [16. Alternate LLM Providers (LiteLLM Proxy)](#16-alternate-llm-providers-litellm-proxy) for the full design.

- `is_enabled(db) -> bool`, `get_agent_base_url(db) -> str`, `get_effective_config(db) -> dict` — resolve whether the connection is active and which base URL deployed agents use, applying the Settings-override-then-env-var-fallback order.
- `get_litellm_proxy_config(db) -> tuple[str, str] | None` — resolves `(base_url, master_key)` for calls the Loom *backend itself* makes to the proxy (uses `discovery_base_url`). Returns `None` if no proxy is configured, the Settings-page toggle is off, or the master key can't be read from Secrets Manager.
- `has_master_key(db) -> bool` — whether a master key is currently resolvable.
- `vend_virtual_key(agent_id, agent_name, allowed_model_ids, db, timeout=10.0) -> str | None` — mints a scoped virtual key via `POST /key/generate` on the proxy, aliased `loom-agent-{agent_id}`. Revokes any stale key under the same alias first (idempotent under redeploy retries). Returns `None` (rather than raising) if the proxy isn't configured or the request fails — deploy degrades gracefully since the LiteLLM integration is optional.
- `revoke_virtual_key(key_alias, db, timeout=10.0) -> None` — best-effort `POST /key/delete` by alias; logs and returns on any failure (including 404, expected on first deploy) rather than raising, so an unreachable proxy never blocks agent deletion.

### `services/model_catalog.py`

Dynamic model catalog merging the static list with live Bedrock and LiteLLM sources — see [16. Alternate LLM Providers (LiteLLM Proxy)](#16-alternate-llm-providers-litellm-proxy).

- `get_bedrock_models(region) -> list[dict]` — static `models.json` (Bedrock-lab entries only) enriched with live availability (`list_foundation_models`/`list_inference_profiles`) and live pricing (LiteLLM's public pricing JSON), plus any live-discovered Bedrock model not yet curated in `models.json`. Never contacts the LiteLLM proxy. Cached with a TTL (`LOOM_MODEL_CATALOG_TTL_SECONDS`, default 900s), thread-safe via a lock with re-check-after-acquire.
- `get_litellm_models_live() -> list[dict]` — models actually configured on the deployed LiteLLM proxy (`/model/info`), resolved via `services/litellm.get_litellm_proxy_config()`. No public-catalog or placeholder fallback — returns `[]` if the proxy isn't configured/enabled/reachable. Cached independently of `get_bedrock_models` with the same TTL.
- `get_merged_models(region) -> list[dict]` — `get_bedrock_models() + get_litellm_models_live()`, for callers needing the full valid-model-ID universe (settings validation, `PATCH /api/agents/{id}`, pricing).
- `get_providers_merged() -> list[dict]` — thin passthrough returning `SUPPORTED_PROVIDERS` (a hook for future live provider discovery).
- `clear_litellm_cache() -> None` — drops the cached LiteLLM proxy catalog so the next call re-fetches live, bypassing the TTL. Called by `PUT /api/settings/litellm-proxy` and `POST /api/settings/litellm-proxy/refresh`.
- `_normalize_model_id(model_id) -> str` — strips region (`us.`/`eu.`/`apac.`) and `bedrock/` prefixes and lowercases, for cross-source matching between `models.json` IDs, Bedrock's IDs, and LiteLLM's pricing JSON keys.

### `services/iam.py`

- `create_execution_role() -> str` — creates an IAM execution role suitable for AgentCore.
- `delete_execution_role(role_arn: str)` — deletes an IAM execution role.
- `list_agentcore_roles() -> list[dict]` — lists IAM roles suitable for AgentCore.
- `list_cognito_pools() -> list[dict]` — lists Cognito user pools.
- `build_base_policy(region, account_id, agent_name, ...) -> dict` — the inline policy attached to an agent's execution role. **Every statement is scoped per agent by `agent_name`**, which may be one agent's exact name or, for a shared managed role, the common name prefix of a family of agents:
  - Workload identity — `workload-identity-directory/default/workload-identity/{agent_name}-*` plus a `harness_{agent_name}-*` variant.
  - Credential providers — `token-vault/default/oauth2credentialprovider/loom-{agent_name}-*` and `.../apikeycredentialprovider/loom-{agent_name}-*`.
  - CloudWatch Logs — the agent's own runtime log groups, plus `harness_` variants.
  - Secrets Manager — `secret:loom/agents/{agent_name}*`, plus a `harness_` variant.

**Credential-provider scoping (H1-3956464).** The two credential-provider statements previously used a bare `.../{oauth2,apikey}credentialprovider/*`, so any agent's execution role could read *every* credential provider in the account's token vault — other agents' OAuth tokens and API keys — while the workload-identity and Secrets Manager statements beside them were already per-agent. Both are now scoped, in `build_base_policy()` and in the equivalent `bedrock-agentcore` policy in `shared/iac/role.yaml` (where the single mixed statement was split in two so credential providers could be scoped without touching workload-identity grants).

The `loom-` prefix is load-bearing: Loom names providers `loom-{agent_name}-mcp-{server}`, `loom-{agent_name}-a2a-{agent}` and `loom-{agent_name}-litellm-key` (`routers/agents.py`), so scoping to a bare `{agent_name}-*` would look correct and match nothing, breaking every OAuth integration at runtime rather than at deploy time. There is deliberately **no** `harness_` variant for providers, unlike log groups and workload identities: that prefix is applied by AgentCore to the runtime name it auto-provisions for a harness, whereas provider names are built by Loom from the agent record's own name, so a harness agent's providers are `loom-{agent_name}-*` as well.

### `services/memory.py`

Wraps `boto3.client('bedrock-agentcore-control')` for memory CRUD and `boto3.client('bedrock-agentcore')` for memory record queries:

- `create_memory(name, event_expiry_duration, ..., region) -> dict` — calls `create_memory` and returns the full response including ARN, ID, and status.
- `get_memory(memory_id, region) -> dict` — calls `get_memory(memoryId=...)` and returns current memory state.
- `list_memories(region) -> dict` — calls `list_memories()` and returns all memory resources.
- `list_memory_records(memory_id, actor_id, strategies, max_records, region) -> list[dict]` — data plane operation that queries LTM records by resolving strategy namespace templates with the actor ID. Unwraps the AWS tagged union strategy format (e.g. `{"userPreferenceMemoryStrategy": {...}}`) to extract `strategyId` and `namespaces`. Truncates unresolved placeholders (e.g. `{sessionId}`) to query all matching records.
- `delete_memory(memory_id, region) -> dict` — calls `delete_memory(memoryId=...)`.

### `services/latency.py`

- `compute_cold_start(client_invoke_time: float, agent_start_time: float) -> float` — returns millisecond delta.
- `compute_client_duration(client_invoke_time: float, client_done_time: float) -> float` — returns millisecond delta.

### `services/tokens.py`

Bedrock token counting via the CountTokens API:

- `count_input_tokens(model_id, prompt, region) -> int` — counts input tokens using the Bedrock `count_tokens` API. Provider guard restricts API calls to supported providers (`anthropic`, `meta`); other models fall back to `len(prompt) // 4` heuristic.
- `count_output_tokens(model_id, output_text, region) -> int` — counts output tokens by passing text through `count_tokens` (returns `inputTokens` for any content). Same provider guard and fallback.

### `services/usage_poller.py`

Background poller that updates estimated compute costs with actual USAGE_LOGS data:

- `start_usage_poller() -> None` — async task that runs every 10 minutes (`POLL_INTERVAL_SECONDS = 600`). Finds invocations with `cost_source="estimated"` and `status="complete"`, groups them by runtime, polls CloudWatch USAGE_LOGS, matches events by timestamp (within 5 seconds of `client_invoke_time`), and updates `compute_cpu_cost`, `compute_memory_cost`, `compute_cost`, and `cost_source` from `"estimated"` to `"usage_logs"`.

### `services/registry.py`

Wraps `boto3.client('agent-registry-control')` (control plane) and `boto3.client('agent-registry')` (data plane) for AWS Agent Registry operations. AWS Agent Registry moved from the `bedrock-agentcore`/`bedrock-agentcore-control` namespace to its own dedicated `agent-registry`/`agent-registry-control` namespace at GA (2026-08-06), which also restructured the registry record schema — descriptors are now a flat, keyed structure (one primary descriptor per `recordType`, e.g. `mcpServer`/`a2aAgentCard`/`custom`, with supplementary content nested under `additionalData`) instead of a discriminated union, and records carry two new required top-level fields (`name` as a registry-unique dedup key, `recordType` as the semantic type — `AGENT`/`MCP`/`SKILL`/`CUSTOM`). The router (`routers/registry.py`) translates between this AWS shape and Loom's stable frontend-facing contract (`descriptor_type` values `MCP`/`A2A`), so `RegistryPage.tsx` and the rest of the frontend are unaffected by the AWS-side rename.

- `RegistryClient(registry_id, region)` — lazy singleton via `get_registry_client()`. Gracefully returns empty results when `LOOM_REGISTRY_ID` is not set.
- `list_records() -> dict` — lists all records in the registry.
- `get_record(record_id) -> dict` — gets full record detail including descriptors.
- `create_record(name, display_name, record_type, descriptors, record_version, description) -> dict` — creates a new registry record. `name` is the required registry-unique dedup key; Loom passes the resource's own display name (agent/server/A2A agent name) as both `name` and `display_name` — a collision (two resources sharing a name) surfaces as an AWS `ConflictException`, mapped to HTTP 409 by the router, rather than silently succeeding under an unreadable synthetic key.
- `wait_for_record(record_id) -> dict` — polls until the record leaves the CREATING state. Blocking (`time.sleep` loop), so callers on a request thread must not call this inline from a frequently-polled endpoint — see the auto-registration note below.
- `submit_for_approval(record_id) -> dict` — submits a record for approval review.
- `approve_record(record_id) -> dict` — approves a record (sets status to APPROVED).
- `reject_record(record_id, reason) -> dict` — rejects a record with a reason.
- `update_record(record_id, display_name, descriptors, record_version, description) -> dict` — updates a record's mutable fields (`recordType` and `name` are immutable after creation).
- `delete_record(record_id) -> dict` — deletes a registry record.
- `search_records(query, max_results) -> dict` — semantic search over registry records via `SearchDiscoverableRegistryRecords` (data plane).
- `build_mcp_descriptors(server, tools) -> dict` — builds a flattened `mcpServer` descriptor from a Loom McpServer and its tools (server manifest as `data`, tool definitions nested under `additionalData.tools`).
- `build_a2a_descriptors(agent) -> dict` — builds a flattened `a2aAgentCard` descriptor from a Loom A2aAgent (agent card as `data`).
- `build_agent_descriptors(agent) -> dict` — builds a flattened `a2aAgentCard` descriptor from a Loom Agent (agent manifest with name, HTTP invocation `url`, region, protocol, network mode). Maps to `recordType: "AGENT"` — AWS has no distinct A2A record type. The card's `url` is the callable `https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{url-encoded-arn}/invocations` endpoint (or `/harnesses/invoke` for harness-sourced agents) via `_agent_invoke_url()` — never the runtime ARN itself, which AWS's A2A AgentCard schema validation rejects as an invalid `url`.

**Error mapping:** `routers/registry.py` wraps every `RegistryClient` call through `_call_registry()`, which catches `botocore.exceptions.ClientError`/`BotoCoreError` and translates named AWS error codes into the corresponding HTTP status (`ValidationException`→400, `ResourceNotFoundException`→404, `ConflictException`→409, `AccessDeniedException`→403, `ThrottlingException`/`ServiceQuotaExceededException`→429, anything else→502) with the AWS error message as the response detail. Without this, any AWS-side rejection (schema validation, dedup-key conflict, throttling) surfaced as an unhandled exception and a generic 500.

**Auto-registration concurrency:** Agents are auto-registered once `deployment_status` reaches `READY`, checked on every `GET /api/agents/{id}/status` poll (the frontend polls this endpoint every ~2s while an agent deploys). Because `create_record()` + `wait_for_record()` can block for several seconds, the actual AWS call runs in a `BackgroundTasks`-scheduled function (`_register_agent_in_registry_background` in `routers/agents.py`), and only the request that wins an atomic DB claim (`_claim_registry_registration`: `UPDATE agents SET registry_status='REGISTERING' WHERE id=? AND registry_record_id IS NULL AND registry_status IS NULL`) schedules it. This prevents overlapping polls from each independently calling `create_record()` for the same agent and producing duplicate orphaned registry records.

### `services/observability.py`

CloudWatch vended log delivery configuration for agent runtimes and memory resources:

- `enable_runtime_observability(runtime_arn, runtime_id, account_id, region) -> dict` — configures USAGE_LOGS and APPLICATION_LOGS delivery for an agent runtime using the CloudWatch `put_delivery_source`, `put_delivery_destination`, and `create_delivery` APIs. Called during agent deployment to enable cost tracking via vended logs.
- `enable_code_interpreter_observability(ci_arn, ci_id, account_id, region) -> dict` — configures USAGE_LOGS and APPLICATION_LOGS delivery for a custom Code Interpreter resource. Account ID is parsed from `ci_arn` directly to ensure the log group ARN is valid. Delivery source/destination names use the last 8 characters of the CI ID to stay within CloudWatch's 64-character limit.

---

## 8. Agent Deployment Flow

Deployment runs asynchronously via FastAPI `BackgroundTasks` with progressive `deployment_status` updates:

1. User submits a deploy form with agent configuration (model and IAM role are required).
2. Backend creates the agent record with `deployment_status="initializing"`, immediately applies resolved tags to the DB record (so tag-based resource filtering is active from the first poll), and returns immediately with HTTP 202.
   - **Auto-grant access control:** After creating the agent record, for each associated MCP server and A2A agent, if access control rules already exist for that integration, the new agent is automatically added with `all_tools` (MCP) or `all_skills` (A2A) access. If no rules exist (access control disabled), no action is taken — the agent already has access by default. Existing rules are never modified, only new entries are added.
3. Background task progresses through deployment phases:
   - **`creating_credentials`**: For each MCP server or A2A agent with OAuth2 auth, calls `create_oauth2_credential_provider` (vendor=`CustomOauth2`, using `discoveryUrl` from config) with exponential backoff retry, under a name from `credential_provider_name()` and with `allow_update=True`. If the provider already exists (e.g., redeployment, or a leftover from a deploy that failed after this step), applies the latest configuration via `update_oauth2_credential_provider`; because the name embeds the agent id, that existing provider can only be this agent's own. Stores credential provider names in `AGENT_CONFIG_JSON` under `integrations.mcp_servers[].auth.credential_provider_name` or `integrations.a2a_agents[].auth.credential_provider_name`. If credential provider creation fails after all retries, sets `deployment_status="credential_creation_failed"` and returns without deploying.
   - **`creating_role`**: Creates or validates the IAM execution role (if needed).
   - **`building_artifact`**: Builds the deployment artifact by copying source from `agents/strands_agent/src/` (or `agents/adk_agent/src/` when `agent_framework="adk"` — selected via `build_agent_artifact(region, agent_framework=...)` in `services/deployment.py`), running `pip install` against `requirements.txt` targeting `linux/arm64` (`manylinux2014_aarch64`), fixing console script shebangs (e.g. `opentelemetry-instrument`) to use `#!/usr/bin/env python3` for Linux compatibility, zipping the package and uploading it to S3. Both frameworks' `handler.py` share the same `entryPoint`/`runtime` values passed to `create_runtime`/`update_runtime`, so no framework parameter is needed there. When `code_interpreter_enabled` is true and a CI execution role is configured, a custom Code Interpreter resource is created in parallel via `ThreadPoolExecutor`. The resulting resource ID is stored in `agents.code_interpreter_id` and injected into `AGENT_CONFIG_JSON` as `integrations.code_interpreter.identifier`.
   - **`deploying`**: Calls `create_agent_runtime` with the artifact location, environment variables (including `OTEL_SERVICE_NAME` set to the agent name, `AGENT_OBSERVABILITY_ENABLED=true` to activate the `aws-opentelemetry-distro` export pipeline, `OTEL_TRACES_EXPORTER=awsxray`, and `OTEL_PROPAGATORS=xray` to activate X-Ray tracing), network/protocol/lifecycle/authorizer configuration.
   - **`deployed`**: Stores authorizer config on the agent record. Stores the Cognito `client_id` as a config entry. Stores the `client_secret` in AWS Secrets Manager and saves the resulting ARN as a config entry. Updates `deployment_status="deployed"` and `status="READY"`.
4. On error during any phase: sets `deployment_status="failed"` (or `"credential_creation_failed"` specifically for credential failures).
5. Frontend polls the status endpoint to track progress. Smart polling returns DB state immediately during local build phases (`creating_credentials`, `creating_role`, `building_artifact`) without AWS API calls. Only when `deployment_status="deployed"` does the status endpoint query AWS for runtime state.
6. Permanent errors (e.g., `AccessDeniedException`, `UnauthorizedException`) mark the agent as FAILED to stop polling.

---

## 9. Authenticated Invocation Flow

Invocations are authenticated with a priority-based token selection:

0. **Bearer token (highest priority):** If the invoke request includes a `bearer_token` field, it is used directly as the Authorization header. The `token_source` is set to `"manual"`. This supports agents with external authorizers where credentials are not managed within Loom.
1. **Credential-based token:** If the invoke request includes a `credential_id`, the backend looks up the `AuthorizerCredential`, fetches the client secret from Secrets Manager (5-minute cache), and exchanges credentials for an M2M access token. The `token_source` is set to the credential label.
1.5. **Linked-user token (cross-IdP):** If the agent has an authorizer with a configured user client, the backend attempts to resolve a linked access token for the current user from Secrets Manager (`loom/authorizers/{auth_id}/user-tokens/{user.sub}`). The refresh token is exchanged for a fresh access token via the authorizer's token endpoint. The `token_source` is set to `"linked-user"`. This enables cross-IdP scenarios where the user's login IdP differs from the agent's authorizer.
2. **User login token:** If the agent has an authorizer configured and the request includes an `Authorization: Bearer` header, the user's access token is forwarded directly to AgentCore. The `token_source` is set to `"user"`. This works when the user's login IdP matches the agent's authorizer (same-IdP scenario).
3. **Agent config token (lowest priority):** Falls back to the agent's stored authorizer config for M2M token retrieval. The `token_source` is set to `"agent-config"`.
4. **No token (SigV4):** If no token is resolved, the request uses IAM SigV4 authentication (the default boto3 credential chain).

The selected Bearer token is passed to `invoke_agent_runtime` (unsigned SigV4 + `Authorization` header). The `session_start` SSE event includes `has_token: true` and `token_source` indicating which token source was used.

**Group-based invoke restriction:** `super-admins` can invoke any agent. `demo-admins` and `users` can only invoke agents whose `loom:group` tag matches their own group. Returns 403 if the user's group doesn't match the agent's tag.

**User client auto-inclusion:** When deploying an agent with a Cognito authorizer, the backend automatically adds `LOOM_COGNITO_USER_CLIENT_ID` to the agent's `allowedClients` list. This ensures user login tokens are accepted by the agent runtime without manual configuration.

---

## 10. Latency Measurement Flow

Latency measurement is integrated into the invoke flow — no separate endpoint is needed.

```
Client                  Backend                 AWS
   │                       │                     │
   │── POST /invoke ──────►│                     │
   │                       │── record client_invoke_time
   │                       │── create session + invocation records
   │                       │── invoke_agent_runtime ────────────────►│
   │                       │◄── SSE stream chunks (asyncio.to_thread)│
   │◄── SSE: session_start─│                     │
   │◄── SSE: chunk... ─────│  (real-time flush)  │
   │                       │── record client_done_time               │
   │                       │── compute client_duration_ms            │
   │                       │── filter_log_events (asyncio.to_thread)►│
   │                       │◄── log events ──────────────────────────│
   │                       │── parse "Start time:" from logs         │
   │                       │── compute cold_start_latency_ms         │
   │                       │── persist all metrics to SQLite         │
   │◄── SSE: session_end ──│  (includes latency data)                │
```

---

## 11. Session Liveness Tracking

Session liveness is computed locally — no AWS API calls are made.

### Configuration

- `LOOM_SESSION_IDLE_TIMEOUT_SECONDS` (default: `300`) — how long after the last invocation activity a session is considered still warm.
- `LOOM_SESSION_MAX_LIFETIME_SECONDS` (default: `3600`) — maximum session lifetime regardless of activity.

Both values are exposed via `GET /api/agents/defaults` for the frontend to display as placeholder hints.

### `live_status` Computation

| Stored Status | Last Activity | `live_status` |
|---------------|---------------|---------------|
| `pending` | any | `"pending"` |
| `streaming` | any | `"streaming"` |
| `complete` / `error` | within timeout | `"active"` |
| `complete` / `error` | beyond timeout | `"expired"` |

### `active_session_count` Computation

Counts sessions whose `live_status` would be `"pending"`, `"streaming"`, or `"active"`. Computed based on the end time (`client_done_time`) of the last invocation.

---

## 12. 3rd-Party Identity Provider Support

### Overview

The backend supports federated authentication via 3rd-party OIDC identity providers (Microsoft Entra ID, Okta, Auth0, Generic OIDC) alongside the existing Cognito-based authentication. Cognito remains the default; external IdPs are opt-in via the Identity Provider management API.

### `identity_providers` Table

Stores OIDC identity provider configurations. Columns include `name`, `provider_type` (entra_id, okta, auth0, generic_oidc), `issuer`, `client_id`, `client_type` (`public` or `confidential`, default `public`), `discovery_url`, `authorization_endpoint`, `token_endpoint`, `jwks_uri`, `userinfo_endpoint`, `group_claim` (the JWT claim containing group membership), `group_mapping` (JSON dict mapping external groups to Loom groups), `scopes` (space-separated OIDC scopes), `is_active` (boolean, at most one active at a time), `discovery_metadata` (cached `.well-known/openid-configuration` response), and timestamps. Client secrets are never stored in the database.

### Identity Provider Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/settings/identity-providers` | Create an identity provider configuration |
| `GET` | `/api/settings/identity-providers` | List all identity provider configurations |
| `GET` | `/api/settings/identity-providers/{id}` | Get a specific identity provider |
| `PUT` | `/api/settings/identity-providers/{id}` | Update an identity provider configuration |
| `DELETE` | `/api/settings/identity-providers/{id}` | Delete an identity provider configuration |
| `POST` | `/api/settings/identity-providers/discover` | Run OIDC discovery against a well-known URL |
| `POST` | `/api/settings/identity-providers/{id}/test-discovery` | Test discovery for an existing provider |

Scope enforcement: `security:read` for GET, `security:write` for POST/PUT/DELETE.

### OIDC Discovery Service (`services/oidc.py`)

Fetches `.well-known/openid-configuration` from any OIDC-compliant provider. Extracts `authorization_endpoint`, `token_endpoint`, `jwks_uri`, `userinfo_endpoint`, and `issuer` from the discovery document. Used both at provider creation (to auto-populate endpoints) and at runtime (to refresh cached metadata).

### Generic JWT Validation (`services/jwt_validator.py`)

Extended to validate tokens against any JWKS endpoint, not just Cognito. On token validation:
1. Extracts the `kid` from the JWT header.
2. Looks up the signing key from the cached JWKS keyset for the provider's `jwks_uri`.
3. On key-not-found, refreshes the JWKS cache and retries (handles key rotation).
4. Validates `iss`, `aud`, and `exp` claims against the provider configuration.

### Group Claim Mapping

External IdPs use different claim names and group identifiers. The `group_mapping` field on `IdentityProvider` maps external group values to Loom groups:
- The `group_claim` field specifies which JWT claim contains group membership (e.g., `groups` for Entra ID, `groups` for Okta).
- The `group_mapping` JSON dict maps external group names/IDs to Loom group names (e.g., `{"EntraAdmins": "g-admins-super", "EntraUsers": "g-users-demo"}`).
- Unmapped groups are ignored. Users with no mapped groups receive no scopes (same as an unrecognized Cognito group).

**Self-escalation guard on `group_mappings` writes:** `security:write` alone is enough to create/update an identity provider, and the mapping table names arbitrary Loom groups with no restriction on which ones — so without a check, a security-scoped admin (`g-admins-security`: `security:read/write`, `tagging:read` only) could map an external group they control to `g-admins-super` and, by authenticating through that IdP, obtain every scope in the system including `admin:write`. `routers/identity_providers.py`'s `_assert_group_mappings_within_caller_scopes()` closes this: on `create`/`update`, every Loom group named anywhere in `group_mappings`' values is resolved via `derive_scopes()`, and the request is rejected (403) if that union grants any scope the calling admin doesn't already hold — the general "no delegation beyond what you hold" rule, not a hardcoded reserved-group denylist, so it also blocks mapping to e.g. `g-admins-mcp` (which a security admin doesn't hold `mcp:write` for either). A genuine super-admin (holding every scope) is unaffected. Type groups (`t-admin`/`t-user`, which grant no scopes) and mapping to one's own group are always allowed.

**Empty mapping tables fail closed.** The guard above covers the mapping *table*, and was bypassable by never putting the group name in the table at all. `_build_user_from_external_claims()` used to read an empty or missing table as "no restrictions configured, trust the IdP" and copy the raw `groups` claim straight through as Loom group names. Because that token is signed by whoever controls the IdP, the claim is attacker-controlled — so a caller holding only `security:write` could create a provider with mappings omitted (or `PUT {"group_mappings": {}}`, which skipped the guard's truthiness check while the persist ran on `is not None`), mint a JWT claiming `g-admins-super`, and authenticate with every scope including `admin:write`.

External claims are now *always* resolved through the mapping table, with no fallback: an empty table yields no groups, so the user authenticates and holds no scopes, and every guarded route returns 403. An IdP configured without mappings is therefore a visible misconfiguration rather than a silent grant of everything — the login path logs a warning naming the unmapped groups. Both the create and update guards are gated on `is not None` to match their persist conditions, so no settable value can skip the check.

This is deliberately a behaviour change: any deployment that was relying on claim pass-through will find its users hold no scopes until `group_mappings` is populated.

### Generic Token Service (`services/token.py`)

Performs client credentials grants against any OIDC-compliant token endpoint for M2M flows. Used when agents are configured with non-Cognito OIDC authorizers.

### Auth Config Endpoint

`GET /api/auth/config` returns the active identity provider configuration when an external IdP is active. The response includes `provider_type`, `issuer`, `authorization_endpoint`, `client_id`, and `scopes` — sufficient for the frontend to initiate an Authorization Code + PKCE flow. When no external IdP is active, the response falls back to the existing Cognito-only format for backward compatibility.

### Per-User Authorizer Linking (`services/authorizer_linking.py`)

When a user's login IdP differs from an agent's authorizer (cross-IdP scenario), the user must link their identity to the agent's authorizer via an OAuth popup flow. The linking service provides:

- `check_link_status(auth_id, user_sub, region)` — checks if a user has linked credentials in Secrets Manager.
- `store_user_tokens(auth_id, user_sub, refresh_token, region)` — stores the refresh token at `loom/authorizers/{auth_id}/user-tokens/{user_sub}`.
- `resolve_access_token(auth_id, user_sub, region, discovery_url, client_id, client_secret)` — exchanges the stored refresh token for a fresh access token with in-memory caching keyed by `(auth_id, user_sub)`.
- `exchange_code_for_tokens(auth_id, code, code_verifier, redirect_uri, region, discovery_url, client_id, client_secret)` — completes the OAuth code exchange for the popup callback.
- `delete_user_tokens(auth_id, user_sub, region)` — removes linked credentials from Secrets Manager.

Linking endpoints under `/api/security/authorizers/{auth_id}/link`: `GET .../status`, `GET .../authorize`, `POST .../callback`, `DELETE .../`.

### Authorizer `allowed_audience` Field

The `AuthorizerConfig` model includes an `allowed_audience` field (JSON array) for configuring the `allowedAudience` parameter on AgentCore runtimes. This is distinct from `allowedClients` — audience validates the `aud` claim, while clients validates the `azp` claim.

**Entra ID and Okta compatibility:** Microsoft Entra ID v1.0 access tokens use a proprietary `appid` claim instead of the standard OAuth2 `azp` claim, and Okta access tokens use `cid` instead of `azp`. AgentCore's `allowedClients` validates against `azp`, causing `UnrecognizedClientException` (401) for both providers. The deploy paths for both custom and harness agents omit `allowedClients` when `authorizer_type` is `"entra_id"` or `"okta"`, relying on `allowedAudience` alone for token validation.

### Entra ID v1.0/v2.0 Issuer Handling

Entra ID v2.0 token endpoints issue access tokens with a v1.0 issuer (`https://sts.windows.net/{tenant}/`). The backend auth dependency handles this by extracting the tenant ID from a v2.0 issuer URL and constructing the expected v1.0 issuer format for token validation. Agent authorizers should use the v1.0 discovery URL (`https://login.microsoftonline.com/{tenant}/.well-known/openid-configuration`) for consistency.

---

## 13. Human-in-the-Loop (HITL) Approvals

Loom supports three HITL patterns for pausing agent execution at sensitive tool calls and requiring human approval:

### 13.1 Agentic Loop Hook (Custom Agents — Method 1)

The Strands Agent framework `before_tool_call` hook intercepts tool calls. When a matching approval policy exists:
1. The hook emits an `approval_request` SSE event via the streaming queue.
2. The backend (`invocations.py`) detects the interrupt, calls `create_approval_request()` and `wait_for_approval()`.
3. The user's decision is submitted via `POST /api/approvals/{request_id}/decision`.
4. The agent is resumed with `interruptResponse` containing the decision.

### 13.2 Tool Context Interrupt (Custom Agents — Method 2)

Individual tools embed approval logic using `agents/strands_agent/src/integrations/approval.py`. Tools call `require_approval()` to pause and wait for human input. Approval decisions can be cached per session via `approval_cache_ttl`.

### 13.3 MCP Elicitation (Custom Agents — Method 3)

MCP servers use `ctx.elicit()` to request structured input. The handler (`handler.py`) uses a `threading.Event` for cross-thread synchronization:
1. The elicitation request is put on the streaming queue as an `elicitation_request` SSE event.
2. The backend waits on the event until the user submits a response via `POST /api/approvals/{request_id}/decision`.
3. The response content is passed back to the MCP server's elicitation callback.

### 13.4 Harness Inline Function (Managed Agents — Method 4)

Managed harness agents use an `inline_function` tool (`user_confirmation`) defined at deploy time. When the agent calls this tool:
1. The harness stream stops with `stopReason: "tool_use"`.
2. `invoke_harness_agent_stream` detects the `tool_use_stop` event and emits `approval_request` SSE.
3. After user decision, the backend calls `resume_harness_stream()` with both the assistant `toolUse` turn and user `toolResult` turn.
4. Multiple consecutive HITL rounds are supported via a loop.

### 13.5 Approval Policies

Stored in `approval_policies` table. Fields: `name`, `policy_type` (loop_hook/tool_context/mcp_elicitation), `tool_pattern` (glob), `approval_mode` (require_approval/notify_only), `timeout_seconds`, `agent_filter`. CRUD via `/api/settings/approval-policies`.

### 13.6 Approval Audit Log

All approval events are recorded in `approval_logs` table: `request_id`, `session_id`, `agent_id`, `tool_name`, `policy_name`, `pattern_type`, `status`, timestamps, `decided_by`, `reason`. Queryable via `GET /api/agents/{agent_id}/approvals`.

### 13.7 SSE Event Types

| Event | Description |
|-------|-------------|
| `approval_request` | Agent paused — awaiting user decision. Contains `request_id`, `tool_name`, `tool_input_summary`, `timeout_seconds`. |
| `approval_resolved` | Decision made. Contains `request_id`, `status` (approved/rejected/timeout), `decided_by`, `reason`. |
| `elicitation_request` | MCP server requesting structured input. Contains `elicitation_id`, `server_name`, `schema`, `message`. |

---

## 14. On-Behalf-Of (OBO) Token Exchange

Loom supports RFC 8693 on-behalf-of token exchange, enabling agents to access downstream OAuth2-protected resources with the invoking user's scoped permissions rather than a shared M2M identity.

### 14.1 Delegation Mode

MCP servers and A2A agents have a `delegation_mode` field (`m2m` or `obo`, default `m2m`):
- **m2m**: Existing client_credentials flow — agent identity used for all downstream calls.
- **obo**: RFC 8693 token exchange — user's access token is exchanged for a downstream token carrying the user's permissions.

### 14.2 Credential Provider Creation

`create_oauth2_credential_provider()` in `app/services/credential.py` accepts `delegation_mode`. When `"obo"`, it adds `oauth2Flow="ON_BEHALF_OF_TOKEN_EXCHANGE"` to the ACPS `create-oauth2-credential-provider` request. M2M path unchanged.

### 14.3 Subject Token Forwarding

The invocation endpoint scans `AGENT_CONFIG_JSON` integrations for `delegation_mode=="obo"`. When OBO is active:
- Extracts the user's Bearer token from the incoming request `Authorization` header.
- Passes `user_access_token` to `invoke_agent_stream` / `invoke_harness_agent_stream`.
- Custom agents receive it in the invoke payload; harness agents receive it via `X-Loom-User-Access-Token` header.
- If the token is missing, the invocation aborts with SSE error `code: "obo_missing_user_token"`.

### 14.4 Runtime Token Exchange (Agent)

The `_OAuth2Auth` handler in `agents/strands_agent/src/integrations/mcp_client.py`:
1. Calls `acps.get_workload_access_token_for_jwt(workloadName, userToken)` to get an OBO workload token.
2. Calls `acps.get_resource_oauth2_token(..., oauth2Flow="ON_BEHALF_OF_TOKEN_EXCHANGE")` to get the downstream token.
3. Caches by `(credential_provider_name, user_sub)` with TTL from `expiresIn`.

### 14.5 Validation Endpoint

`POST /api/agents/{id}/test-obo` performs a dry-run token exchange using the caller's Bearer token. Returns decoded JWT claims for admin inspection.

### 14.6 Observability

- `session_start` SSE includes `delegation_mode` and `has_user_access_token` (when OBO).
- Agent runtime logs OBO exchange attempts at INFO level (provider name, user sub, success/failure).
- OBO failures surface as user-friendly SSE errors, not 500s.

---

## 14b. Authorization Guard Tests

`tests/test_router_authorization_guard.py` makes instance-level authorization
mechanical rather than remembered. Four reported findings had the same shape —
a route resolving a resource from a caller-supplied ID without checking
entitlement — and each was fixed where it was reported while the next turned up
elsewhere (the H1-3954919 fetch-by-ID sweep missed the session and invocation
readers, which became their own report).

Scope-level authorization does not have this problem because it rides
dependency injection: a route cannot silently lack `require_scopes`. Two tests
give instance-level checks the same property:

- **Every route is scope-guarded.** Each `@router.*` handler must carry a
  `require_scopes` dependency or an authenticated `UserInfo` parameter.
  `auth.py`'s `/config` and `/token` are the only allowlisted exceptions.
- **Scoped models are not queried directly.** A router may not call
  `db.query(<ScopedModel>)` for `Agent`, `InvocationSession`, `Invocation`,
  `ApprovalLog`, `Memory`, `McpServer` or `A2aAgent` unless its module is in
  `ALLOWED_RAW_QUERY` with a stated reason. `db.query(Agent).filter(Agent.id ==
  agent_id).first()` answers "does this row exist" when the question is "may
  this caller have this row"; the helpers answer the second. A third test fails
  when the allowlist names a module that no longer exists, so the exemptions
  keep meaning something.

The allowlist is deliberately coarse and must be extended consciously — the
failure mode being guarded is forgetting.

## 14a. Test Isolation Boundary

`tests/conftest.py` keeps the suite independent of the machine it runs on. The
suite previously ran green for months and then 335 of 893 tests failed at once
— not from a regression, but because an external IdP had been registered in
the developer's local `loom.db`. Each boundary below closes one way that
dependency got in (issue #77).

- **Database.** `LOOM_DATABASE_URL` is pointed at a throwaway SQLite file at
  conftest *import* time, followed by `init_db()`. It has to be import time,
  not a fixture: `app/db.py` resolves the URL and builds its engine as a side
  effect of being imported. Overriding the `get_db` dependency is not
  sufficient on its own — 18 call sites across `app/` construct a
  `SessionLocal()` directly rather than taking the dependency, so
  `dependency_overrides[get_db]` never reaches them.
  `app/dependencies/auth.py` is one of those sites, which is why a local IdP
  made every un-overridden router request fail closed with 401.
- **Auth bypass.** `_default_auth_bypass` supplies the
  `LOOM_ALLOW_UNAUTHENTICATED_LOCAL_DEV` opt-in plus a loopback client, since
  most tests don't care about auth semantics. `test_auth.py` and
  `test_scopes.py` override it with a no-op to control auth state themselves.
  `_reset_idp_cache` clears auth's module-level active-IdP cache around every
  test — shared mutable state that otherwise outlives the test that populated
  it. It deliberately does *not* force the lookup to return `None`: the
  database isolation is the single mechanism, and a second fixture papering
  over it is how the original problem stayed invisible.
- **Clock.** `_no_real_sleeping` replaces the `time` reference in the modules
  with polling/backoff loops (`routers/agents`, `services/registry`,
  `services/cloudwatch`, `services/credential`, `services/evaluations`) with a
  shim whose `sleep` is a no-op and every other attribute delegates to the
  real module. Only the sleeping is removed, so the loops keep the
  break/purge semantics their tests assert against. `_delete_agent_background`
  alone slept up to 150 seconds per `DELETE /api/agents/{id}`, inside the
  TestClient request, because FastAPI runs `BackgroundTasks` there — which
  went unnoticed because auth was rejecting those requests first. Removing the
  sleeps cut suite runtime roughly in half.
- **Network.** `_no_outbound_network` denies `socket.getaddrinfo` for
  hostnames and `socket.create_connection` outright, so a new test cannot
  silently add egress. Resolving a *numeric* literal is still allowed: the
  SSRF tests exercise their guard with addresses like `169.254.169.254` and
  `127.0.0.1`, which `getaddrinfo` parses without touching DNS.
  `socket.socket` itself is left alone — asyncio's selector event loop builds
  its self-pipe with `socketpair()`, so denying it breaks every TestClient
  request rather than catching real egress.

Note that `boto3` is mocked throughout the suite; the leaks were to the local
filesystem and the clock, not to AWS.

---

## 15. Makefile Targets

The backend `makefile` sources `etc/environment.sh` and provides:

```makefile
install              # uv pip install -r requirements.txt
test                 # python -m pytest tests/ -v
run                  # uvicorn app.main:app --reload --port $BACKEND_PORT

# Database operations
migrate-db           # Migrate SQLite → PostgreSQL (uses $LOOM_DATABASE_URL)
fix-sequences        # Repair PostgreSQL sequences after migration
reset-db             # Reset database (drop all tables)

# RDS infrastructure (PostgreSQL + optional RDS Proxy)
rds                  # Package and deploy RDS stack
rds.package          # SAM package for RDS stack
rds.deploy           # SAM deploy for RDS stack
rds.outputs          # Query RDS stack outputs
rds.get-url          # Get database URL from Secrets Manager
rds.delete           # Delete RDS stack

# EC2 infrastructure (SSM tunnel bastion)
ec2                  # Package and deploy EC2 stack
ec2.package          # SAM package for EC2 stack
ec2.deploy           # SAM deploy for EC2 stack
ec2.outputs          # Query EC2 stack outputs
ec2.delete           # Delete EC2 stack

# ECS backend service
ecs                  # Package and deploy backend ECS service
ecs.package          # SAM package for backend ECS stack
ecs.deploy           # SAM deploy for backend ECS stack (pImageUri includes git SHA tag)
ecs.outputs          # Query backend ECS stack outputs
ecs.delete           # Delete backend ECS stack

# SSM tunnel (port forwarding to RDS)
tunnel               # Start SSM port forwarding session to RDS

# AgentCore credential providers
agentcore.credentials.list       # List OAuth2 credential providers
agentcore.credentials.delete-all # Delete all credential providers

# AgentCore memory queries (requires P_MEMORY_ID, P_MEMORY_ACTOR_ID, P_MEMORY_NAMESPACE in env)
agentcore.memory.list                  # List all memory resources
agentcore.memory.get                   # Get a specific memory resource
agentcore.memory.records               # Query LTM records by actor ID (resolves strategy namespaces)
agentcore.memory.records-by-namespace  # List LTM records by memory ID and namespace
agentcore.memory.extraction-jobs       # List memory extraction jobs
```

---

## 16. Alternate LLM Providers (LiteLLM Proxy)

### Overview

Agent model calls default to Amazon Bedrock (IAM-authenticated, no additional configuration). Loom also supports routing an agent's model calls through a self-hosted [LiteLLM](https://www.litellm.ai/) proxy, giving access to any model the proxy exposes (including non-Bedrock providers) without Loom needing per-provider integration code. The provider registry is static and file-based (`backend/etc/providers.json`), loaded into `SUPPORTED_PROVIDERS`/`SUPPORTED_PROVIDER_IDS` in `routers/agents.py`:

```json
[
  {"id": "bedrock", "display_name": "Amazon Bedrock", "requires_api_key": false, "requires_base_url": false, "harness_supported": true},
  {"id": "litellm", "display_name": "LiteLLM", "requires_api_key": false, "requires_base_url": false, "harness_supported": true}
]
```

`GET /api/agents/providers` returns this registry merged with a live `available: bool` per provider — LiteLLM is `available` only when a proxy connection is configured and enabled (`services.litellm.is_enabled()`).

### Proxy Connection Resolution (`services/litellm.py`)

The LiteLLM master key is the one credential Loom holds for the proxy; it is never handed to an individual agent (see virtual key vending below). Resolution order for the master key and base URLs, applied uniformly by `get_litellm_proxy_config()`/`get_agent_base_url()`/`get_effective_config()`:

1. **Settings-page override** — `SiteSetting` rows (`litellm_enabled`, `litellm_proxy_base_url`, `litellm_discovery_base_url`) plus the master key in Secrets Manager (`loom/settings/litellm-master-key`), set via Settings → Models → LiteLLM. Wins once an agent base URL has been saved there, gated by the `litellm_enabled` toggle.
2. **CFN-seeded env vars** — `LOOM_LITELLM_PROXY_BASE_URL`, `LOOM_LITELLM_DISCOVERY_BASE_URL`, `LOOM_LITELLM_PROXY_API_KEY` — used only when no agent base URL has ever been saved via Settings. Considered "enabled" automatically once `LOOM_LITELLM_PROXY_BASE_URL` is set (there's no separate toggle at this tier), so a fresh deploy works without a Settings-page visit.

Two distinct base URLs are tracked because the machine calling the proxy differs:
- **`agent_base_url`** — what deployed agents/harnesses use at runtime to reach the proxy directly. Must be reachable from wherever the agent runs (e.g. an internal ALB).
- **`discovery_base_url`** — what the Loom *backend itself* uses for calls it makes directly to the proxy (`/model/info` discovery, `/key/generate`, `/key/delete`). Falls back to `agent_base_url` when not separately set — they're identical in a deployed environment, but during local dev the backend typically reaches the proxy through an SSM tunnel (e.g. `http://localhost:4000`) while agents reach it through the real ALB.

### Per-Agent Virtual Key Vending

Each LiteLLM-provider agent gets a scoped *virtual key* minted via the proxy's key-management API rather than sharing the master key:

- `vend_virtual_key()` calls `POST /key/generate` with `models: allowed_model_ids` and a deterministic `key_alias` of `loom-agent-{agent_id}`, so a retried/redeployed agent doesn't collide with a stale key from a prior attempt (LiteLLM rejects duplicate aliases with 400) — the alias is revoked first, making vending idempotent.
- `revoke_virtual_key()` calls `POST /key/delete` by alias on agent redeploy/delete. Both functions are best-effort: any failure (unreachable proxy, 404 on delete) is logged and swallowed rather than raised, so the LiteLLM integration being optional never blocks a deploy or delete.
- **Custom (deploy-type) agents:** the vended virtual key is stored as a Secrets Manager secret at `loom/agents/{name}-{id}/llm-provider-api-key` and referenced via the `LLM_PROVIDER_API_KEY_SECRET_ARN` agent config entry. The agent runtime resolves it at model-build time via `agents/strands_agent/src/integrations/secrets.py::resolve_secret()`.
- **Harness agents:** the vended key is instead registered as an AgentCore **API key credential provider** (`create_api_key_credential_provider()` in `services/credential.py`, distinct from the OAuth2 credential providers used for MCP/A2A auth). The Harness API's `liteLlmModelConfig.apiKeyArn` resolves it directly via `bedrock-agentcore:GetResourceApiKey` at invocation time — Secrets Manager is not involved for this path. The credential provider name and ARN are stored in `AGENT_CONFIG_JSON` (`litellm_api_key_credential_provider_name`/`_arn`) for cleanup on redeploy/delete.

### Agent Runtime Model Construction

`agents/strands_agent/src/config.py`'s `AgentConfig` carries `provider` (default `"bedrock"`), `base_url`, and `api_key_secret_arn`, parsed from the deploy-time JSON config. `agents/strands_agent/src/agent.py::_build_model()` dispatches on `provider`:

- **`bedrock`** (default) — unchanged `BedrockModel`, IAM-authenticated via the execution role.
- **`openai` / `anthropic` / `litellm`** — resolves the API key once via `resolve_secret(config.api_key_secret_arn)` and constructs `OpenAIModel` / `AnthropicModel` / `LiteLLMModel` respectively, with `client_args["timeout"]` bounded by `LOOM_MODEL_REQUEST_TIMEOUT_SECONDS` (default 30s). Without this bound, a network path that accepts the TCP connection but never responds (misconfigured security group, unreachable ALB target) hangs the underlying httpx client indefinitely — the failure would otherwise only ever surface as the invoke caller's own read timeout, minutes later, with no detail.
- For `litellm` specifically, `client_args["use_litellm_proxy"] = True` is set. Without it, a bare model ID (e.g. `"claude-sonnet-5"`) is handed to LiteLLM's SDK unprefixed, and LiteLLM's own provider auto-detection routes the call straight at the real upstream provider (e.g. Anthropic) instead of through the configured proxy's `base_url` — using the proxy's virtual key as if it were a real provider key. Setting this flag makes `LiteLLMModel._apply_proxy_prefix` add a `litellm_proxy/` prefix, forcing the proxy route.

### Dynamic Model Catalog (`services/model_catalog.py`)

The model picker merges four sources, none of which block on each other:

1. **Static `models.json`** — curated `display_name`/`group`/`max_tokens` defaults, source of truth for known models.
2. **Live Bedrock availability/catalog** — `list_foundation_models`/`list_inference_profiles`, restricted to an allow-listed set of labs (Anthropic, OpenAI, Amazon, DeepSeek, Qwen, Z.AI). Fills in models not yet curated in `models.json`.
3. **Live LiteLLM proxy catalog** — `/model/info` on the configured proxy, reshaped into the same flat shape as the public pricing catalog. Only queried when a proxy is configured.
4. **LiteLLM's public pricing JSON** (`model_prices_and_context_window.json` on GitHub, overridable via `LOOM_LITELLM_PRICING_URL`) — pricing fallback/enrichment for curated and dynamically-discovered Bedrock entries.

`get_bedrock_models(region)` (sources 1+2, enriched by 4; never touches the proxy) and `get_litellm_models_live()` (source 3 only, no placeholder fallback) are cached independently with a shared TTL (`LOOM_MODEL_CATALOG_TTL_SECONDS`, default 900s), each behind its own lock with re-check-after-acquire for thread safety under concurrent sync FastAPI handlers. This split means the frontend's eager page-load fetch of Bedrock models never waits on a LiteLLM proxy round-trip, and selecting the LiteLLM provider fetches its catalog on demand rather than eagerly. `get_merged_models(region)` concatenates both for callers needing the complete valid-model-ID universe (`PUT /api/settings/models` validation, `PATCH /api/agents/{id}`, pricing lookups).

`clear_litellm_cache()` drops the cached LiteLLM catalog, exposed via `POST /api/settings/litellm-proxy/refresh` for recovering from a stale/empty cache (e.g. cached while the proxy was momentarily unreachable) without waiting out the TTL or restarting the backend.

### Settings Page Endpoints

`GET/PUT /api/settings/litellm-proxy` manage the connection (`enabled`, `base_url`, `discovery_base_url`, write-only `master_key`). `PUT` persists the toggle/URLs as `SiteSetting` rows, writes the master key to Secrets Manager only if provided (omitting it leaves the stored key untouched), and clears the LiteLLM model-catalog cache so the change takes effect immediately. `POST /api/settings/litellm-proxy/refresh` forces a live re-fetch without changing the connection settings.

### IAM / IaC (`backend/iac/ecs.yaml`)

New parameters `pLitellmProxyBaseUrl`, `pLitellmDiscoveryBaseUrl`, `pLitellmProxyApiKeySecretArn`, `pLitellmProxyApiKeySecretKmsKeyArn` seed the env-var fallback tier described above. When `pLitellmProxyApiKeySecretArn` is set: it's injected as the `LOOM_LITELLM_PROXY_API_KEY` ECS task **Secret** (not a plain environment variable), and the backend task execution role is granted `secretsmanager:GetSecretValue` on it (plus `kms:Decrypt` on `pLitellmProxyApiKeySecretKmsKeyArn`, if the secret uses a customer-managed KMS key rather than the default `aws/secretsmanager` key). Both grants are conditioned on the parameter being non-empty (`HasLitellmProxyApiKey`/`HasLitellmProxyApiKeySecretKmsKey` CFN conditions), so a deployment without LiteLLM configured grants nothing extra.

Deploying and exercising this feature end-to-end also surfaced (and required fixing) several pre-existing IAM gaps on the backend task role, tracked here since they were necessary to actually deploy an agent:
- **AgentCore runtime lifecycle:** `CreateAgentRuntime`, `CreateAgentRuntimeEndpoint`, `UpdateAgentRuntime`, `UpdateAgentRuntimeEndpoint`, `DeleteAgentRuntime`, `DeleteAgentRuntimeEndpoint` (previously only invoke-time actions were granted, since the original role was built around `register`-source agents).
- **VPC-mode service-linked role:** `iam:CreateServiceLinkedRole` scoped to `arn:aws:iam::${AccountId}:role/aws-service-role/network.bedrock-agentcore.amazonaws.com/AWSServiceRoleForBedrockAgentCoreNetwork` (condition: `iam:AWSServiceName == network.bedrock-agentcore.amazonaws.com`). VPC-mode runtimes trigger AWS to lazily create this role on first use per account — without the grant, `CreateAgentRuntime` fails with "Failed creating service linked role" before AWS ever evaluates the action's own IAM permissions.
- **CloudWatch Logs delivery pipeline:** `logs:PutDeliveryDestination`/`PutDeliverySource`/`CreateDelivery` (+ matching `Delete*`) and `logs:DescribeDeliveries` (list-only, no resource-level scoping), used by `services/observability.py` to route AgentCore Runtime and Code Interpreter vended logs into `/aws/vendedlogs/bedrock-agentcore/*`.
- **Live Bedrock discovery:** `bedrock:ListFoundationModels`/`ListInferenceProfiles` (list-only), used by `model_catalog.py`'s live Bedrock availability/catalog fetch.
- A dedicated `LogsKmsKey` (customer-managed, rotation enabled) now encrypts the backend's own ECS CloudWatch log group.
