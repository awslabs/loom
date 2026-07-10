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
│   ├── models.json              # Supported model catalog (model_id, display_name, group, pricing)
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
- `auth.credential_provider_name` — Name of the AgentCore credential provider created during deployment
- `auth.well_known_endpoint` — OAuth2 discovery URL
- `auth.scopes` — Array of OAuth2 scopes
- `auth.delegation_mode` — `m2m` or `obo` (on-behalf-of token exchange)
- `auth.obo_grant_type` — `TOKEN_EXCHANGE` or `JWT_AUTHORIZATION_GRANT` (when delegation_mode is `obo`)
- `auth.audience` — Token exchange audience (when required by the authorization server)

The `a2a_agents` configuration is stored in the `AGENT_CONFIG_JSON` config entry under `integrations.a2a_agents` as an array. Each A2A agent with OAuth2 authentication includes:
- `auth.credential_provider_name` — Name of the AgentCore credential provider created during deployment
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
| `POST` | `/api/registry/records` | Create a registry record from a Loom MCP server or A2A agent. Body: `{resource_type: "mcp"|"a2a", resource_id: int}`. |
| `POST` | `/api/registry/records/{record_id}/submit` | Submit a registry record for approval. Updates linked resource status to PENDING_APPROVAL. |
| `POST` | `/api/registry/records/{record_id}/approve` | Approve a registry record. Updates linked resource status to APPROVED. |
| `POST` | `/api/registry/records/{record_id}/reject` | Reject a registry record. Body: `{reason: str}`. Updates linked resource status to REJECTED. |
| `DELETE` | `/api/registry/records/{record_id}` | Delete a registry record and clear the linked resource's registry fields. |
| `GET` | `/api/registry/search` | Semantic search over registry records. Query params: `q` (search query), `max_results` (default 10). |

**Record lifecycle:** CREATING → DRAFT → PENDING_APPROVAL → APPROVED | REJECTED (also DEPRECATED)

**Registry is opt-in:** The registry is configured via the Settings page by entering a registry ARN (validated format: `arn:aws:bedrock-agentcore:<region>:<account>:registry/<id>`). The ARN is stored in `site_settings` and loaded into memory on startup. When enabled, it provides additional governance mechanisms: agents, MCP servers, and A2A agents must be approved in the registry before they can be used. When not configured, all resources are available without registry approval. The `LOOM_REGISTRY_ID` env var is supported as a bootstrap fallback.

**Supported resource types:** `mcp` (MCP servers), `a2a` (A2A agents), `agent` (deployed agents). Agents are auto-registered in DRAFT status when deployment completes (if registry is configured).

**Visibility filtering:** When listing agents, MCP servers, or A2A agents, users in the `t-user` role only see resources with `registry_status` of APPROVED or NULL (unregistered). Admin users see all resources regardless of registry status.

**Integration gating:** When registry is configured, only APPROVED MCP servers and A2A agents can be selected for agent deployment. Non-approved integrations are rejected with a descriptive error.

**Scope enforcement:** `registry:read` for GET endpoints, `registry:write` for POST/PUT/DELETE endpoints.

**Registry status sync on re-enable:** When the registry ARN is updated via `PUT /api/settings/registry` and the new ARN is non-empty, the backend calls `_sync_registry_statuses()` to validate all stored `registry_record_id` values across Agent, McpServer, and A2aAgent models against the live registry. Records that no longer exist in the registry have their `registry_record_id` and `registry_status` cleared. Status mismatches are updated to match the live registry state. This prevents stale governance data after a disable/re-enable cycle.

**Data model:**
- `A2aAgent`: stores base URL, Agent Card fields (name, description, version, provider, capabilities, auth schemes, I/O modes), raw card JSON, OAuth2 config, status, and timestamps.
- `A2aAgentSkill`: stores skill ID, name, description, tags, examples, and I/O mode overrides. Foreign key to `A2aAgent` with cascade delete.
- `A2aAgentAccess`: stores persona_id, access_level (`all_skills`/`selected_skills`), and allowed_skill_ids (JSON). Foreign key to `A2aAgent` with cascade delete.

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
| `GET` | `/api/settings/registry` | Get current registry configuration (ARN, ID, enabled status). |
| `PUT` | `/api/settings/registry` | Update registry configuration. Validates ARN format before saving. Empty ARN disables. |
| `GET` | `/api/settings/litellm-proxy` | Get the current LiteLLM proxy configuration (`enabled`, `base_url`, `discovery_base_url`, `has_master_key`). Reflects env-seeded defaults when no Settings-page override has been saved. Never returns the master key. |
| `PUT` | `/api/settings/litellm-proxy` | Update the LiteLLM proxy configuration. `master_key` is write-only — omit it to leave the stored key untouched. Persists to `SiteSetting` rows + Secrets Manager, then clears the LiteLLM model-catalog cache. |
| `POST` | `/api/settings/litellm-proxy/refresh` | Force a live re-fetch of the LiteLLM proxy's model catalog, bypassing the cache TTL — recovers from a stale/empty result (e.g. cached while the proxy was unreachable) without a backend restart. Returns the same shape as `GET/PUT /api/settings/models`. |

Current site settings:
- `cpu_io_wait_discount` (default: `75`) — CPU I/O wait discount percentage (0–99). Applied universally to runtime CPU costs.
- `enabled_model_ids` (default: `[]`) — JSON array of admin-enabled model IDs. When empty, all models are available. Filters the response of `GET /api/agents/models`. May include LiteLLM model IDs.
- `litellm_enabled`, `litellm_proxy_base_url`, `litellm_discovery_base_url` — LiteLLM proxy connection settings managed via `GET/PUT /api/settings/litellm-proxy` (see [16. Alternate LLM Providers](#16-alternate-llm-providers-litellm-proxy)). The master key is stored separately in Secrets Manager, not as a site setting.
- `loom_registry_id` (default: `""`) — AWS Agent Registry ARN. Stored in `site_settings`, loaded into memory on startup. Validated format: `arn:aws:bedrock-agentcore:<region>:<account>:registry/<id>`.

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

### `services/credential.py`

AgentCore credential provider management:

- `create_oauth2_credential_provider(name: str, client_id: str, client_secret: str, auth_server_url: str, region: str, tags: dict | None, delegation_mode: str = "m2m", obo_grant_type: str | None = None) -> dict` — creates or updates an OAuth2 credential provider using the `CustomOauth2` vendor type. When `delegation_mode` is `"obo"`, configures `onBehalfOfTokenExchangeConfig` with the specified grant type (`TOKEN_EXCHANGE` for RFC 8693 or `JWT_AUTHORIZATION_GRANT` for RFC 7523). TOKEN_EXCHANGE uses `actorTokenContent: NONE` with `CLIENT_SECRET_BASIC` auth method; JWT_AUTHORIZATION_GRANT uses `CLIENT_SECRET_POST`. If creation fails with a `ValidationException` indicating the provider already exists, automatically falls back to `update_oauth2_credential_provider` (without tags, which the update API does not accept). Retries other transient failures with exponential backoff (4 retries, delays 2s/4s/8s/16s). Raises on exhaustion.
- `delete_credential_provider(provider_name: str, region: str)` — deletes an OAuth2 credential provider by name.
- `create_api_key_credential_provider(name: str, api_key: str, region: str) -> dict` — creates (or, on `ValidationException` indicating the provider already exists, updates) an AgentCore **API key** credential provider — a distinct provider type from the OAuth2 ones above. Used for harness agents' `liteLlmModelConfig.apiKeyArn`, which the Harness resolves itself via `bedrock-agentcore:GetResourceApiKey` at invocation time (not Secrets Manager). Returns the response dict including `credentialProviderArn`.
- `delete_api_key_credential_provider(provider_name: str, region: str)` — deletes an API key credential provider by name.

**IAM permissions required:** The ECS task role needs both `bedrock-agentcore:*` actions (for the control plane API) and Secrets Manager permissions scoped to `bedrock-agentcore-identity!*` secrets. Credential providers internally store OAuth2 client credentials in Secrets Manager under this prefix. The task role requires `secretsmanager:GetSecretValue`, `CreateSecret`, `DeleteSecret`, and `PutSecretValue` on `arn:aws:secretsmanager:*:${AccountId}:secret:bedrock-agentcore-identity!*`. The CloudWatch Logs policy covers both `/aws/bedrock-agentcore/*` and `/aws/vendedlogs/bedrock-agentcore/*` log group prefixes (the latter is used for agent observability vended logs).

### `services/jwt_validator.py`

- `validate_cognito_token(token: str, user_pool_id: str, region: str, client_id: str | None) -> dict` — validates a JWT against the Cognito JWKS endpoint. Caches JWKS keys for 1 hour.

### `dependencies/auth.py`

Core authentication and authorization module. Provides:

- `GROUP_SCOPES: dict[str, list[str]]` — maps Cognito group names to scope lists. Must match the frontend `GROUP_SCOPES` exactly. Uses two-dimensional group architecture:
  - **Type groups** (UI view): `t-admin`, `t-user` — no scopes, determine layout
  - **Resource groups** (access control):
    - `g-admins-super`: all 21 scopes (catalog:r/w, agent:r/w, memory:r/w, security:r/w, settings:r/w, tagging:r/w, costs:r/w, mcp:r/w, a2a:r/w, registry:r/w, invoke)
    - `g-admins-demo`: `catalog:read`, `agent:read`, `agent:write`, `memory:read`, `memory:write`, `security:read`, `settings:read`, `tagging:read`, `costs:read`, `costs:write`, `mcp:read`, `mcp:write`, `a2a:read`, `a2a:write`, `invoke` (can create/delete demo resources only)
    - `g-admins-security`: `security:read`, `security:write`, `settings:read`
    - `g-admins-memory`: `memory:read`, `memory:write`, `settings:read`
    - `g-admins-mcp`: `mcp:read`, `mcp:write`, `settings:read`
    - `g-admins-a2a`: `a2a:read`, `a2a:write`, `settings:read`
    - `g-admins-registry`: `mcp:read`, `a2a:read`, `registry:read`, `registry:write`, `settings:read`, `settings:write`, `tagging:read`
    - `g-users-demo`, `g-users-test`, `g-users-strategics`: `invoke` + read access to resources tagged with matching group
- `UserInfo` dataclass — `sub`, `username`, `groups`, `scopes` (derived from groups).
- `get_current_user(request: Request) -> UserInfo` — validates JWT, extracts `cognito:groups`, derives scopes. In bypass mode (no `LOOM_COGNITO_USER_POOL_ID`), returns a super-admin with all scopes. Raises 401 on missing/invalid token.
- `require_scopes(*required: str)` — factory returning a FastAPI dependency that checks the user has ALL required scopes. Raises 403 on missing scope. Used as `Depends(require_scopes("scope:name"))` on all guarded endpoints.
- `oauth2_scheme` — `OAuth2AuthorizationCodeBearer` for OpenAPI docs with all 21 scopes.
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
| `settings.py` (site settings) | `settings:read` | `settings:write` |
| `settings.py` (enabled models) | `settings:read` | `settings:write` |
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

**View As mode:** Super-admins can switch to view the system as a different user persona (e.g., `demo-admin`, `demo-user`). The frontend sends a `group` parameter to backend endpoints, which filters resources as if the admin belonged to that group. This enables super-admins to validate permission models without switching accounts.

### `services/mcp.py`

MCP server connection, tool discovery, and invocation:

- `test_mcp_connection(server, api_key=None) -> dict` — Sends an `initialize` JSON-RPC request to verify the server is reachable. Supports OAuth2, API key, and unauthenticated connections.
- `fetch_mcp_tools(server, api_key=None) -> list[dict]` — Calls `tools/list` JSON-RPC method and returns tool metadata (name, description, input_schema).
- `invoke_mcp_tool(server, tool_name, arguments, api_key=None) -> dict` — Calls `tools/call` JSON-RPC method to invoke a specific tool with arguments.
- `resolve_api_key(server, user_sub=None) -> str | None` — Resolves API key from Secrets Manager. Admin key for admin context (`loom/mcp/{name}/admin-api-key`), user key for user context (`loom/mcp/{name}/api-key/{user_sub}`).
- `_build_headers(server, api_key=None) -> dict` — Builds request headers with auth injection. For API key auth, uses `api_key_header_name` to set the correct header; `Authorization` headers are prefixed with `Bearer`.
- `_call_streamable_http()`, `_call_sse()`, `_call_mcp()` — Transport methods accepting optional `api_key` parameter.

### `services/a2a.py`

A2A Agent Card fetching and connection testing:

- `fetch_agent_card(base_url: str, auth_headers: dict | None) -> dict` — fetches the Agent Card from the well-known endpoint. Standard A2A agents use `/.well-known/agent.json`; AgentCore agents try `/.well-known/agent-card.json` first; Salesforce Agentforce agents use `/v1/card`. Raises on HTTP errors or invalid JSON.
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

Wraps `boto3.client('bedrock-agentcore-control')` (control plane) and `boto3.client('bedrock-agentcore')` (data plane) for AWS Agent Registry operations:

- `RegistryClient(registry_id, region)` — lazy singleton via `get_registry_client()`. Gracefully returns empty results when `LOOM_REGISTRY_ID` is not set.
- `list_records() -> dict` — lists all records in the registry.
- `get_record(record_id) -> dict` — gets full record detail including descriptors.
- `create_record(name, descriptor_type, descriptors, record_version, description) -> dict` — creates a new registry record.
- `wait_for_record(record_id) -> dict` — polls until the record leaves the CREATING state.
- `submit_for_approval(record_id) -> dict` — submits a record for approval review.
- `approve_record(record_id) -> dict` — approves a record (sets status to APPROVED).
- `reject_record(record_id, reason) -> dict` — rejects a record with a reason.
- `delete_record(record_id) -> dict` — deletes a registry record.
- `search_records(query, max_results) -> dict` — semantic search over registry records (data plane).
- `build_mcp_descriptors(server, tools) -> list[dict]` — builds MCP-type descriptors from a Loom McpServer and its tools (server manifest + tool definitions).
- `build_a2a_descriptors(agent) -> list[dict]` — builds A2A-type descriptors from a Loom A2aAgent (agent card).
- `build_agent_descriptors(agent) -> list[dict]` — builds AGENT-type descriptors from a Loom Agent (agent manifest with name, ARN, runtime ID, region, protocol, network mode).

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
   - **`creating_credentials`**: For each MCP server or A2A agent with OAuth2 auth, calls `create_oauth2_credential_provider` (vendor=`CustomOauth2`, using `discoveryUrl` from config) with exponential backoff retry. If the provider already exists (e.g., redeployment), automatically falls back to `update_oauth2_credential_provider` to apply the latest configuration. Stores credential provider names in `AGENT_CONFIG_JSON` under `integrations.mcp_servers[].auth.credential_provider_name` or `integrations.a2a_agents[].auth.credential_provider_name`. If credential provider creation fails after all retries, sets `deployment_status="credential_creation_failed"` and returns without deploying.
   - **`creating_role`**: Creates or validates the IAM execution role (if needed).
   - **`building_artifact`**: Builds the deployment artifact by copying source from `agents/strands_agent/src/`, running `pip install` against `requirements.txt` targeting `linux/arm64` (`manylinux2014_aarch64`), fixing console script shebangs (e.g. `opentelemetry-instrument`) to use `#!/usr/bin/env python3` for Linux compatibility, zipping the package and uploading it to S3. When `code_interpreter_enabled` is true and a CI execution role is configured, a custom Code Interpreter resource is created in parallel via `ThreadPoolExecutor`. The resulting resource ID is stored in `agents.code_interpreter_id` and injected into `AGENT_CONFIG_JSON` as `integrations.code_interpreter.identifier`.
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

Scope enforcement: `settings:read` for GET, `settings:write` for POST/PUT/DELETE.

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
