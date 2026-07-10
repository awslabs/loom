# Loom Frontend — Specifications

## 1. Technology Stack

| Concern | Choice |
|---------|--------|
| Framework | React 18 with TypeScript |
| Build tool | Vite 6 |
| UI components | shadcn/ui (Radix primitives) |
| Styling | Tailwind CSS v4 (Vite plugin, no PostCSS) |
| Theme | 10 themes: 5 light + 5 dark (Ayu Light, Catppuccin Latte, Everforest, Rosé Pine Dawn, Solarized, Ayu Dark, Catppuccin Mocha, Dracula, Nord, Tokyo Night) |
| HTTP client | Native `fetch` (typed wrappers in `src/api/client.ts`, dynamic `VITE_API_BASE_URL` with nullish coalescing fallback) |
| SSE streaming | `fetch` + `ReadableStream` (POST-based SSE) |
| Notifications | Sonner (toast) |
| Module system | ESM |

---

## 2. Project Structure

```
frontend/
├── src/
│   ├── api/
│   │   ├── types.ts            # TypeScript interfaces mirroring backend models (A2aAgent, A2aAgentSkill, A2aAgentAccess, A2aAgentCard, CostDashboardResponse, CostActualsResponse, CostActualAgent, CostActualSession, AgentCostSummary, ModelPricing, SSEToolUse, SSETokenInfo, StreamSegment)
│   │   ├── client.ts           # apiFetch<T>() wrapper + ApiError class, dynamic BASE_URL via VITE_API_BASE_URL, automatic auth token injection, 401 auto-refresh via `setOnUnauthorized` callback, and `tryRefreshToken()` export for SSE retry
│   │   ├── auth.ts             # Cognito auth API (initiateAuth, respondToChallenge, refreshTokens)
│   │   ├── agents.ts           # Agent CRUD + deployHarnessAgent(), fetchRoles(), fetchCognitoPools(), fetchModels(), fetchDefaults()
│   │   ├── invocations.ts      # Session queries + SSE stream consumer (with auth header)
│   │   ├── logs.ts             # CloudWatch log queries: `getSessionLogs`, `getAgentLogs`, `listLogStreams`, `listVendedLogSources`, `getVendedLogs`
│   │   ├── mcp.ts              # MCP server CRUD, tools, access, test connection
│   │   ├── a2a.ts              # A2A agent CRUD, test connection, card refresh, access
│   │   ├── memories.ts         # Memory resource CRUD + refresh
│   │   ├── security.ts         # Security admin: roles, authorizers, credentials, permissions
│   │   ├── settings.ts        # Settings API: tag policy + tag profile CRUD + enabled models (getEnabledModels, updateEnabledModels)
│   │   ├── costs.ts           # Cost dashboard (estimated + actuals) + model pricing API
│   │   ├── traces.ts          # Trace API: `getSessionTraces`, `getTraceDetail`
│   │   └── audit.ts           # Admin audit API: recordLogin, recordAction, recordPageView, fetchLogins, fetchActions, fetchPageViews, fetchSessions, fetchSessionTimeline, fetchAuditSummary, trackAction (fire-and-forget)
│   ├── contexts/
│   │   ├── AuthContext.tsx      # Cognito auth provider (login, logout, token refresh, browserSessionId generation and login audit)
│   │   ├── TimezoneContext.tsx  # Timezone preference provider + hook
│   │   └── ThemeContext.tsx     # Theme provider with 10 themes, localStorage persistence, WCAG-compliant contrast
│   ├── hooks/
│   │   ├── useAgents.ts        # Agent list state + CRUD actions
│   │   ├── useSessions.ts      # Session list state per agent
│   │   ├── useInvoke.ts        # Streaming invocation state + AbortController + StreamSegment tracking + tool_use events
│   │   ├── useLogs.ts          # On-demand session and stream log fetching with optional cache-busting (`noCache` parameter appends `_t` timestamp)
│   │   ├── useDeployment.ts    # Agent config, credential providers, integrations hooks
│   │   ├── useMcpServers.ts   # MCP server list state + CRUD actions
│   │   ├── useA2aAgents.ts  # A2A agent list with auto-fetch, CRUD callbacks
│   │   └── useTraces.ts    # Trace list + detail state management
│   ├── components/
│   │   ├── ui/                 # shadcn primitives + searchable-select.tsx + multi-select.tsx + add-filter-dropdown.tsx + tooltip.tsx
│   │   ├── SortableCardGrid.tsx — Drag-to-reorder card grid using @dnd-kit, default alphabetical sort, SortButton, localStorage persistence
│   │   ├── SortableTableHead.tsx — Clickable sortable table column headers with arrow indicators
│   │   ├── AgentCard.tsx       # Agent summary card with refresh + Trash2 icon deletion
│   │   ├── AgentRegistrationForm.tsx  # Tabbed form: ARN registration + agent deployment
│   │   ├── JsonConfigSection.tsx     # Shared collapsible JSON import/export section
│   │   ├── AuthorizerManagementPanel.tsx # Authorizer config + credential management
│   │   ├── McpAccessControl.tsx        # Persona access control for MCP servers and tools
│   │   ├── McpServerForm.tsx          # Form for adding/editing MCP servers with OAuth2 config
│   │   ├── McpToolList.tsx            # Tool list display with schema details
│   │   ├── A2aAgentForm.tsx          # A2A agent create/edit form with OAuth2 disclosure
│   │   ├── A2aAgentCardView.tsx      # Structured Agent Card display with skills
│   │   ├── A2aSkillList.tsx          # Expandable skill cards with tags, examples, modes
│   │   ├── A2aAccessControl.tsx      # Per-persona access control for A2A agent skills
│   │   ├── MemoryCard.tsx              # Memory resource summary card
│   │   ├── MemoryManagementPanel.tsx    # Memory resource create form + list table
│   │   ├── ResourceTagFields.tsx       # Shared tag profile selector + tag resolution
│   │   ├── DeploymentPanel.tsx # Deployment details panel
│   │   ├── ExternalIntegrationSection.tsx # External integration info (endpoints, auth, code snippets)
│   │   ├── InvokePanel.tsx     # Qualifier select, credential select, model select, prompt input, invoke/cancel
│   │   ├── LatencySummary.tsx  # Invocation metrics (timing + token usage + cost)
│   │   ├── SessionTable.tsx    # Clickable session list
│   │   ├── InvocationTable.tsx # Invocation timing data + token/cost columns
│   │   ├── LogViewer.tsx       # Paginated log viewer with toggleable line numbers and timestamps
│   │   ├── TraceList.tsx      # Trace summary table (Trace ID, Start/End Time, Duration, Spans, Events) with clickable rows
│   │   └── TraceGraph.tsx     # Interactive waterfall timeline with colored span bars, hover detail panel, click-to-select events, expand/collapse all
│   ├── pages/
│   │   ├── AgentListPage.tsx   # Agents persona: registration form + agent grid
│   │   ├── AgentDetailPage.tsx # Sessions, latency, invoke, response
│   │   ├── CatalogPage.tsx     # Platform Catalog: agents, memory, MCP, A2A agents sections
│   │   ├── SecurityAdminPage.tsx  # Security persona: roles, authorizers, credentials, permissions
│   │   ├── LoginPage.tsx        # Cognito login + NEW_PASSWORD_REQUIRED challenge
│   │   ├── McpServersPage.tsx  # MCP server management: list, detail, tools, access
│   │   ├── A2aAgentsPage.tsx       # A2A agent management with card/access tabs
│   │   ├── MemoryManagementPage.tsx # Memory persona: memory resource management
│   │   ├── TaggingPage.tsx         # Tagging persona: tag policy + tag profile CRUD
│   │   ├── SettingsPage.tsx        # Settings persona: display preferences + cost estimation settings
│   │   ├── CostDashboardPage.tsx  # Cost dashboard with time-range selector and per-agent breakdown
│   │   ├── AdminDashboardPage.tsx # Admin-only dashboard: summary cards, charts, Sessions/Logins/Actions/Page Views tabs
│   │   ├── SessionDetailPage.tsx  # Session metadata, invocations, tabbed Logs/Traces view
│   │   └── InvocationDetailPage.tsx  # Invocation details, cost breakdown, Traces tab
│   ├── lib/
│   │   ├── utils.ts            # shadcn cn() utility
│   │   ├── format.ts           # Timezone-aware timestamp + metric formatters
│   │   ├── models.ts           # groupModels() utility — groups ModelOption[] by vendor, sorted alphabetically
│   │   ├── status.ts           # Status badge variant mapping
│   │   └── errors.ts           # Friendly invoke error message mapping
│   ├── App.tsx                 # Auth gate + persona-based navigation + sidebar
│   ├── main.tsx                # Entry point
│   └── index.css               # Tailwind v4 imports + Catppuccin CSS variables
├── index.html
├── package.json
├── tsconfig.json
├── tsconfig.app.json
├── vite.config.ts
├── etc/
│   ├── environment.sh           # Sources account-specific file + shared outputs
│   └── environment.sh.example   # Example environment configuration template
├── iac/
│   └── ecs.yaml                 # Frontend ECS Fargate service (task def, service)
├── .dockerignore                # Excludes .env, node_modules, dist
├── Dockerfile                   # Multi-stage container image (Node build + nginx serve)
├── nginx.conf                   # nginx SPA config with gzip and immutable asset caching
├── components.json              # shadcn configuration
├── makefile                     # dev, build, ecs.* targets
└── SPECIFICATIONS.md            # This file
```

---

## 3. Application Shell

The app uses a persona-based single-page architecture with a sidebar for workflow selection:

### Persona Navigation (Sidebar)

| Persona | Icon | Description | Required Scope | Default |
|---------|------|-------------|----------------|---------|
| Platform Catalog | BookOpen | Browse agents, memory resources, MCP servers, A2A agents | Always visible | Yes |
| Agents | Bot | Deploy new agents or import existing ones | `agent:read` or `agent:write` | |
| Memory | Brain | Create and manage AgentCore Memory resources | `memory:read` or `memory:write` | |
| Security Admin | Shield | Manage roles, authorizers, credentials, permissions | `security:read` or `security:write` | |
| Tags | Tags | Manage tag policies and tag profiles | Always visible | |
| Settings | Settings | Manage display preferences | Always visible | |
| MCP Servers | Network | Register and manage MCP servers, tools, and access control | `mcp:read` or `mcp:write` | |
| A2A Agents | Users | Register and manage A2A agents, view Agent Cards, and control access | `a2a:read` or `a2a:write` | |
| Registry | Library | Browse and manage AWS Agent Registry records for governance and discovery | `registry:read` or `registry:write` | |
| Costs | DollarSign | Cost dashboard with estimated costs, actual runtime costs from CloudWatch, and cost estimation settings | `catalog:read` | |
| Admin Dashboard | BarChart3 | Platform usage analytics: login tracking, action tracking, page navigation, per-session drill-down, summary cards and charts | `isAdmin` (super-admins only) | |

Sidebar items are conditionally rendered based on the user's scopes derived from their Cognito group membership. When auth is not configured, all items are visible.

The sidebar also contains:
- User indicator with username display and logout button (when authenticated)
- Live clock display
- Version badge

### Admin View Switching
Admin users see an Eye icon dropdown in the sidebar that lets them simulate specific users (admin, demo-admin-1, demo-admin-2, security-admin, integration-admin, demo-user-1, demo-user-2). Each user maps to their Cognito groups, and `effectiveHasScope` resolves scopes from those groups. This lets admins see what each user's experience looks like — including group-restricted resource visibility — without losing admin access. The dropdown resets when the page is refreshed.

### Drill-Down Navigation (Catalog)

Within the Catalog persona, state-driven drill-down navigation:

```
Catalog  >  [Agent Name]  >  [Session ID]
```

- **No router library** — navigation is managed via lifted state in `App.tsx` (`selectedAgentId`, `selectedSessionId`)
- Breadcrumb navigation in the header allows clicking back to any level
- Sonner `<Toaster>` provides toast notifications for all user actions

---

## 4. Platform Catalog (Home View)

**Purpose:** Browse and manage registered agents, memory resources, and other platform resources.

**Content:**
- Page description: "Browse and manage registered agents and resources." with estimates disclaimer: "Costs for agents and memory resources are *estimates*."
- Page header: "Platform Catalog" with card/table view toggle (top-right)
- Organized into collapsible sections: Agents, Memory Resources, MCP Servers, A2A Agents. Each section header has a ChevronRight/ChevronDown toggle. Collapse state persisted to `localStorage` under `loom:collapsedSections:catalog`.
- Tag-based filter bar above the agents grid, with multi-select dropdowns (checkbox-based) for each tag policy with `show_on_card=true`. Client-side AND filtering with "Clear filters" button and agent count display (e.g., "Showing 3 of 12 agents")
- Card/table view toggle applies to all sections on the page
- Agents section: responsive grid of `AgentCard` components (3 columns on large screens) or table view
- Memory Resources section: responsive grid of `MemoryCard` components with delete and refresh wired to API, manual RefreshCw button next to section header; or table view
- Transitional-state polling: if any memory is in CREATING or DELETING state, polls at 3-second intervals; stops when all resources are stable. Memories returning 404 on refresh are automatically purged.
- Loading skeleton placeholders during data fetch
- Empty state with instructions when no agents/memories exist

### AgentCard

Each card displays:
- Agent name (or runtime ID fallback)
- Protocol badge (e.g., `HTTP`) — inline with name
- Status badge (color-coded: READY=default, CREATING=secondary, FAILED=destructive) — inline with name
- Deployment type badge (`MANAGED` or `CUSTOM`) and cost badge displayed below the info box as outline badges (not in the header row)
- Progressive deployment status phases: `initializing`, `creating_credentials` (Creating credential provider), `creating_role` (Creating IAM role), `building_artifact` (Building artifact), `creating_ci_resource` (Building artifact & creating Code Interpreter), `deploying` (Deploying runtime / Creating harness), then "Completing deployment" / "Creating harness", "Finalizing endpoint"
- Spinner animation when agent is in a creating/deploying state
- Spinner animation and elapsed timer when agent is in DELETING state, using `deleteStartTime` prop for accurate timer display
- Endpoint status badge hidden during DELETING state
- `DEPLOY_IN_PROGRESS` set for determining transitional states
- Active session count badge (when > 0)
- Region, Account ID, Network mode, Available qualifiers, Authorizer (name, "Cognito", "external", or "None"), Registered timestamp
- Tag badges (secondary variant) for tags marked `show_on_card` in tag policies, formatted as `key: value`
- Refresh button (RefreshCw icon) and Trash2 icon (top-right) for refresh/deletion

### Delete Confirmation

Clicking the Trash2 icon triggers an overlay confirmation panel:
- Absolutely positioned at the bottom of the card (`absolute inset-x-0 bottom-0`) to prevent other cards in the grid from changing height
- "Also delete in AgentCore" checkbox (right-aligned, shown only when agent has a runtime_id)
- Cancel and Confirm buttons (right-aligned)
- Clicks within the overlay are stopped from propagating to the card's `onClick`

When deletion is confirmed with "Also delete in AgentCore" checked, the agent transitions to DELETING status with a spinner and timer on the card. The `useAgents` hook polls the agent status at 5-second intervals. When the poll returns 404, the hook calls the purge endpoint to remove the agent from the local database and shows a success toast. On deletion, persisted connector preferences (`loom:enabledConnectors:{agentId}:*`) are also cleaned up from `localStorage`.

---

## 5. Agents View (Agent Administration)

**Purpose:** Deploy new agents or import existing ones to AgentCore Runtime.

**Content:**
- Page header: "Agent Administration" with card/table view toggle (top-right)
- Sub-header: "Agents" with description and "Add Agent" button (right-aligned)
- "Add Agent" toggles a Card containing Deploy/Import tab switcher and `AgentRegistrationForm`
- When deploy succeeds, the form collapses and an ephemeral `AgentCard` appears at the top of the grid with CREATING status and spinner/timer. Once the real agent appears in the agents list, the ephemeral card is removed.
- Below the form: responsive grid of `AgentCard` components (cards default) or table view

### Import Tab

- ARN text input and Model selector on the same line (ARN fills remaining space, model is fixed width)
- Labels: "AgentCore Runtime ARN" and "Model Used"
- Model selector uses `SearchableSelect` with grouped options (Anthropic / Amazon), no default selection
- Import button with `min-w-[120px]` to prevent layout shift during loading spinner

### Deploy Tab

Full deployment form with sections:
- **Deployment Type Selector**: Radio buttons for "Custom Agent" (code-based, full configuration) or "Managed Agent" (AgentCore Harness, no code required). Defaults to Custom. Controls which form sections are visible.
- **JSON Import/Export**: Collapsible section (ChevronDown/ChevronRight toggle) via the shared `JsonConfigSection` component. Import maps `name`, `description`, `persona` (→ agent description), `instructions` (→ behavioral guidelines), `behavior` (→ output expectations), `model`, `role`, `network_mode`, `authorizer`, `tags` (tag profile name). Export serializes the current form state to JSON using human-readable identifiers (model ID, role name, authorizer name, tag profile name); empty/default fields are omitted. Apply/Export/Cancel buttons. Invalid JSON shows inline error without clearing existing fields.
- **Agent Identity**: name (1/3 width) and description (2/3 width)
- **System Prompt**: agent description, behavioral guidelines, output expectations — each with placeholder examples
- **Provider / Default Model / Protocol / Network / IAM Role**: Provider selector (Bedrock default, or LiteLLM when a proxy connection is configured — see [17. Alternate LLM Providers](#17-alternate-llm-providers-litellm-proxy)) precedes Default Model, which uses `SearchableSelect` with grouped options and no default selection; switching provider resets the model selection. Protocol offers HTTP as selectable; MCP and A2A shown as disabled (custom only). Network offers PUBLIC; VPC shown as disabled. IAM Role uses a `SearchableSelect` with searchable dropdown. Model, provider, and IAM role are required — deploy button is disabled until all are selected.
- **Allowed Models (runtime selection)**: shown after a default model is selected. Per-vendor grouped checkboxes via `groupModels()`. The default model is always checked and disabled. Additional models can be checked to allow runtime selection at invoke time. If no additional models are selected, only the default model is allowed. JSON import/export supports `allowed_models` array field.
- **Model Parameters** (managed only): max tokens, temperature, top_p — numeric inputs for controlling harness model behavior.
- **Built-in Tools** (managed only): toggle switches for Code Interpreter and Browser tools. When enabled, the corresponding `agentcore_code_interpreter` or `agentcore_browser` tool is added to the harness configuration.
- **Role Permissions (read-only)**: collapsible section shown after IAM role selection, displays policy document. Clicking the header toggles visibility.
- **Authorizer** (custom only): radio selection of None, Cognito, or Other. Authorizer dropdown is 25% width, shows just the authorizer config name. Fields show "Allowed Clients" and "Allowed Scopes".
  - Cognito: searchable Cognito pool select (30% width), auto-populated discovery URL, tag inputs for allowed clients and scopes, app client ID and client secret fields
  - Other: textbox for discovery URL, tag inputs for allowed clients and scopes
- **Harness Parameters** (managed only): max iterations and timeout seconds — positioned between Authorizer and Lifecycle.
- **Lifecycle**: idle timeout and max lifetime fields with dynamic placeholders fetched from `/api/agents/defaults` (e.g., "300" and "3600")
- **Resource Tags**: `ResourceTagFields` component with tag profile dropdown (persisted in `sessionStorage`). Deploy-time tags are auto-applied; build-time tags are resolved from the selected tag profile.
- **Integrations**: Memory (enabled, with multi-select dropdown for memory resources, custom only), MCP Servers (enabled with multi-select dropdown), A2A Agents (enabled with multi-select dropdown, custom only), Code Interpreter (custom only — peer integration section with enable toggle, network mode select (SANDBOX/PUBLIC), region labeled dropdown, and CI execution role selector filtered to `role_type="code_interpreter"` managed roles). JSON import/export uses nested `code_interpreter` key: `{"enabled": true, "region": "us-east-1", "network_mode": "SANDBOX", "role": "loom-ci-role-demo"}`.

---

## 6. Agent Detail View

**Purpose:** Invoke agents with streaming, view latency metrics, inspect session history, and view deployment details.

**Layout:** Single-column, full-width stacked layout:

### Sessions (top)
- Full-width table of all sessions for this agent, filtered to sessions owned by the current user
- Columns: Session ID (truncated), Qualifier, Live Status, Invocation count, Created timestamp
- Live status badges: active (green), expired (muted), streaming/pending (yellow), error (red)
- Pagination with configurable page size and page navigation controls
- Clicking a row navigates to Session Detail

### Invoke Form
- `InvokePanel` component: qualifier selector, credential selector, model selector, multi-line prompt textarea, invoke/cancel buttons
- Model dropdown (`Select`) shown when the agent has allowed models. Filters to `allowedModelIds` when available, otherwise shows only the agent's default model. Disabled when only one model is available. Default model marked with "(default)" suffix. Selected non-default model passed as `model_id` override in the invoke request.
- Credential dropdown is context-aware:
  - **OAuth agents** (agent has authorizer): shows user's token (default), M2M credentials filtered to the agent's matching authorizer only, linked token option (when cross-IdP linking is available), and manual token (always last)
  - **Non-OAuth agents** (no authorizer): shows "No credentials (SigV4)" only
- **Same-IdP detection**: `issuerMatchesDiscovery()` compares the user's login issuer URL against the agent's authorizer discovery URL. For Entra ID, tenant IDs are extracted from both URLs for comparison (handles v1.0/v2.0 URL differences). When matched, the credential dropdown auto-selects the user's login token and shows a green dot indicator. No account linking UI is shown.
- **Cross-IdP account linking**: When the user's login IdP differs from the agent's authorizer, a "Link Account" button appears. Clicking opens an OAuth popup flow. After successful linking, a green dot with "Unlink" option is shown. Linked tokens are used at invocation time (Priority 1.5 in the backend).
- When a credential is selected, the `credential_id` is passed with the invoke request
- When "Manual token" is selected, a password input field appears for entering a raw bearer token
- Session dropdown auto-selects the newly created session after an invocation
- Token indicator (Key icon + badge) shown when `session_start` includes `has_token: true`

### Latency Summary
- 4-metric placeholder (shows "—" before invocation), fills in after `session_end` SSE event

### Token Info Card
- Shown below the latency summary when the invocation includes user token claims or OBO token claims
- Displays decoded JWT claims for the user token (issuer, subject with annotation, audience, scopes, roles with group mapping resolution, expiry)
- Displays OBO tokens acquired from downstream MCP servers during tool execution (credential provider attribution, flow type, claims)
- Role claims are resolved against the active IdP's group mappings to show the Loom group assignment

### Error Display
- Invocation errors show user-friendly messages mapped from raw error patterns via `friendlyInvokeError()` in `lib/errors.ts`
- Pattern matching: 401/unauthorized → auth required, 403/forbidden → access denied, token errors → expired/invalid, credential errors → credential required
- Collapsible "Show details" toggle reveals the raw error for debugging
- Error card styled with `border-destructive`

### Response Pane
- Segment-based rendering: the response pane renders an array of `StreamSegment` objects (text or tool_use) rather than raw text. Text segments are rendered as `MarkdownBlock` components; tool_use segments are rendered as `ToolUseBlock` components.
- `ToolUseBlock`: displays tool calls with Wrench icon, counter (N/M format), `ElapsedTimer` with live seconds count, and animated bounce dots while active. Tool names listed below the counter with `formatToolName()` stripping MCP server prefixes (`server___tool` becomes `tool`).
- Thinking indicator (bouncing dots + "Thinking...") shown when streaming has started but no segments have arrived yet.
- Session ID badge and animated "streaming" indicator in header
- Blinking cursor while streaming
- Markdown rendering extracted to standalone `MarkdownBlock` component (shared `mdComponents` object) for reuse across response pane segments

### Deployment Section (deployed agents only)
- `DeploymentPanel` component restructured: "Allowed Models" section at top with inline edit mode (pencil icon triggers grouped checkbox editor with "set default" toggle per model, Save/Cancel buttons). "Deployed Configuration" section below with runtime status, protocol, network mode, execution role, deployed timestamp.
- `RegisteredAgentModelConfig` card shown for non-deployed agents with model configuration. Same edit flow as `DeploymentPanel` allowed models.

### External Integration (READY deployed agents only)
- `ExternalIntegrationSection` component fetches integration info from `GET /api/agents/{id}/integration` and displays endpoint URLs, auth requirements, and copy-ready code snippets.
- **Endpoint info:** Runtime ARN, protocol badge (HTTP/MCP/A2A), network mode badge (PUBLIC/VPC with icon), per-qualifier invocation URLs and protocol-specific URLs (MCP streamable HTTP, A2A agent card). All URL/ARN fields have copy-to-clipboard buttons.
- **Auth info (SigV4):** IAM action, resource ARN, execution role, example IAM policy (JSON), boto3 snippet, and AWS CLI snippet in syntax-highlighted copyable code blocks.
- **Auth info (OAuth2):** Authorizer type badge, OIDC discovery URL, token endpoint, allowed client IDs and scopes as badges, example token request and invocation curl snippets. Client secrets are never displayed — a note directs users to their identity provider administrator.

---

## 7. Security Admin View

**Purpose:** Manage IAM roles, authorizer configurations, authorizer credentials, and permission requests.

**Content:**
- `SecurityAdminPage` with sections for:
  - **Managed Roles**: list, create (import existing / wizard), view policy document, delete. Uses `SortableCardGrid` with drag-to-reorder (storage key `security-roles`), full-width single-column layout (role cards contain long ARNs and expandable policy documents), default alphabetical sort by role name, and A-Z/Z-A sort toggle. Roles are grouped by `role_type` into collapsible sections ("Agent Roles" for `"agent"`, "Code Interpreter Roles" for `"code_interpreter"`). The import form includes a role type selector to set this field on import. `AgentResponse` includes `code_interpreter_id?: string | null` and `code_interpreter_status?: string | null` to surface CI resource status. `ManagedRole` interface includes `role_type: "agent" | "code_interpreter"`.
  - **Authorizer Configs**: list, create (Amazon Cognito, Microsoft Entra ID, Okta, or Other type with auto-populated discovery URL for Cognito), update, delete. Uses `SortableCardGrid` with drag-to-reorder (storage key `security-authorizers`), default alphabetical sort by config name, and A-Z/Z-A sort toggle.
  - **Authorizer Credentials**: per-config credential management (add label + client_id + client_secret, list, delete). Credential form uses 1/4 / 1/4 / 1/2 field widths. Authorizer type displayed as "Amazon Cognito", "Microsoft Entra ID", or "Okta" for known types.
  - **Permission Requests**: create requests for additional IAM permissions, review (approve/deny) with role application. Uses `SortableCardGrid` with drag-to-reorder (storage key `security-permissions`), default alphabetical sort by role name, and A-Z/Z-A sort toggle.

---

## 8. Memory Management View (Memory Administration)

**Purpose:** Create new AgentCore Memory resources with configurable strategies or import existing ones.

**Layout:** Page header "Memory Administration" with card/table view toggle (top-right), followed by "Add Memory" button, create form (toggle), and memory list (cards default or table).

### Create Form

Toggled via the "Add Memory" button. Contained in a `Card` with the following fields:

- **JSON Import/Export**: Collapsible section via the shared `JsonConfigSection` component. Import maps `name`, `description`, `event_expiry_duration` (validated 3-364), `tags` (tag profile name lookup), `strategies` (array with strategy_type validation). Export serializes the current form state; empty/default fields are omitted. Apply/Export/Cancel buttons.
- **Name** (required, flex-1) and **Event Expiry** (days, fixed 140px width) — same row
- **Description** — full width, optional
- **Memory Execution Role ARN** and **Encryption Key ARN** — 2-column grid, optional
- **Strategies** — dynamic list, each strategy in a dashed-border card:
  - **Type** (Select: Semantic, Summary, User Preference, Episodic, Custom) and **Name** — same row
  - **Description** — full width, optional
  - **Namespace** — single text input field
  - Trash icon to remove individual strategies
  - "Add Strategy" ghost button to add more
- **Resource Tags**: `ResourceTagFields` component (same as agent deploy form) — tag profile dropdown with `sessionStorage` persistence
- **Create** button (disabled until name provided) and **Cancel** button

### Memory List (Card View / Table View)

**Card view** (default): Responsive grid of `MemoryCard` components (3 columns on large screens). Each card displays name, status badge, spinner+timer for transitional states, region, account, event expiry, strategies count, registered timestamp, tag badges (for tags with `show_on_card=true`), refresh and delete buttons. Multi-select tag filter bar above the grid with AND logic.

**Table view**: Table with columns (using `table-fixed` layout with percentage-based widths matching agent tables):

| Column | Width | Description |
|--------|-------|-------------|
| Name | 26% | Memory resource name (font-medium) |
| Status | 10% | Badge with status variant + spinner for transitional states |
| Cost | 12% | Estimated total memory cost (`~N.NNNN` or `—`) |
| Strategies | 12% | Count of configured strategies |
| Event Expiry | 12% | Duration in days (computed from seconds) |
| Region | 12% | AWS region |
| Registered | 16% | Timezone-aware timestamp |

### Status Badges

Status badges use `statusVariant()` mapping:
- **ACTIVE** — default variant
- **CREATING** — secondary variant + spinning `Loader2` icon
- **FAILED** — destructive variant
- **DELETING** — secondary variant + spinning `Loader2` icon
- **initializing** — secondary variant
- **creating_credentials** — secondary variant
- **creating_role** — secondary variant
- **building_artifact** — secondary variant
- **deploying** — secondary variant
- **ENDPOINT_CREATING** — secondary variant

### Timer Accuracy

Elapsed timers for transitional states use per-resource timestamps:
- **CREATING**: Timer uses the creation initiation timestamp (tracked in component state) rather than `created_at` from the server.
- **DELETING**: Timer uses the delete initiation timestamp (tracked in component state) rather than `created_at`.
- A 10-minute creation timeout shows an error toast rather than spinning indefinitely.

### Delete Confirmation

Inline overlay on the card or table row (absolute positioned at bottom):
- "Also delete in AgentCore" checkbox (shown when memory has a memory_id)
- Cancel button (ghost) and Confirm button (destructive)
- Clicks within overlay are stopped from propagating

### Notifications

All operations show Sonner toast notifications:
- Success: "Memory resource created", "Memory resource refreshed", "Memory resource deleted"
- Error: Mapped from HTTP status codes (400→invalid request, 403→access denied, 404→not found, 409→conflict, 429→rate limited, 502→AWS service error)

### Empty State

When no memory resources exist: centered muted text "No memory resources yet. Add one above."

---

## 8a. MCP Servers View (MCP Server Administration)

**Purpose:** Register and manage MCP (Model Context Protocol) servers, view available tools, and control persona access. MCP servers can be selected during agent deployment for runtime integration.

**Layout:** Page header "MCP Server Administration" with card/table view toggle (top-right), followed by "Add MCP Server" button, create form (toggle), and server list (cards default or table).

### Server List

**Card view** (default): `SortableCardGrid` with drag-to-reorder (storage key `mcp-servers`), default alphabetical sort by name, and A-Z/Z-A sort toggle. Each card displays server name, status badge (`active`=default, `inactive`=secondary, `error`=destructive), endpoint URL, transport type badge, auth type badge, created timestamp. Delete with inline confirmation overlay (same pattern as AgentCard).

**Table view**: Sortable columns — Name (18%), Endpoint (46%), Transport (10%), Auth (10%), Created (16%).

### Server Detail View

Accessed by clicking a server card/row. Shows:
- Header with server name, endpoint URL, status/transport/auth badges
- "Edit Server" button (opens inline McpServerForm with pre-filled data)
- Tab bar: Tools | Access

**Tools tab** (`McpToolList`):
- Tool count and last-refreshed timestamp
- "Refresh Tools" button to fetch from the MCP server
- Each tool displayed as a card: tool name (bold), description, collapsible input schema (formatted JSON in monospace `pre` block)
- Empty state: "No tools discovered. Click 'Refresh Tools' to fetch from the MCP server."

**Access tab** (`McpAccessControl`):
- Lists all registered agents (personas) with checkbox to grant/revoke access
- When access granted: radio for "All Tools" / "Selected Tools"
- When "Selected Tools": checkboxes for individual tools (from cached tool list)
- "Save" button to persist changes
- Deny by default — personas without an explicit rule cannot use the server

### McpServerForm

Create/edit form with:
- Name (required, 1/3 width) and Endpoint URL (required, flex-1) and Transport Type (select: SSE/Streamable HTTP, 180px)
- Description (textarea)
- Authentication section: radio toggle for None / OAuth2 / API Key
- When OAuth2: well-known URL, client ID, client secret (password input with "(unchanged)" placeholder in edit mode), scopes (space-separated), delegation mode radio toggle (M2M / OBO), OBO grant type selector (TOKEN_EXCHANGE / JWT_AUTHORIZATION_GRANT, shown when OBO selected), audience field (shown when OBO selected, required for Okta custom authorization servers)
- When API Key: Header Name dropdown (`x-api-key` or `Authorization`), API Key password input (with "(unchanged)" placeholder in edit mode when admin key exists)
- "Test Connection" button (only shown in edit mode) with success/failure badge result
- Create/Update and Cancel buttons

---

## 8b. A2A Agents View (A2A Agent Administration)

**Purpose:** Register and manage A2A (Agent-to-Agent) protocol integrations, view structured Agent Card information, and control persona access to agent skills.

**Layout:** Page header "A2A Agent Administration" with card/table view toggle (top-right), followed by "Add A2A Agent" button, create form (toggle), and agent list (cards default or table).

### Agent List

**Card view** (default): `SortableCardGrid` with drag-to-reorder (storage key `a2a-agents`), default alphabetical sort by name, and A-Z/Z-A sort toggle. Each card displays agent name, version badge, base URL, provider, auth type, created timestamp. Edit/Delete buttons with inline confirmation overlay.

**Table view**: Sortable columns — Name (18%), URL (46%), Version (10%), Auth (10%), Created (16%). No Provider or Status column; structure matches the MCP Servers table.

### Agent Detail View

Accessed by clicking an agent card/row. Shows:
- Header with agent name, edit button, and description
- "Edit Agent" opens inline A2aAgentForm with pre-filled data
- Tab bar: Agent Card | Access

**Agent Card tab** (`A2aAgentCardView`):
- Header section: agent name, version badge, status badge, provider info, documentation link, "Refresh Card" button with last-fetched timestamp
- Capabilities section: enabled/disabled badges for Streaming, Push Notifications, State History
- Authentication Schemes section: badges for each scheme (e.g., Bearer, Basic)
- Input/Output Modes section: MIME type badges
- Skills section (`A2aSkillList`): expandable skill cards with name, skill ID, description, tag badges, examples (bulleted list), and input/output mode overrides

**Access tab** (`A2aAccessControl`):
- Lists all registered agents (personas) with checkbox to grant/revoke access
- When access granted: radio for "All Skills" / "Selected Skills"
- When "Selected Skills": checkboxes for individual skills with name and description
- "Save" button to persist changes
- Deny by default — personas without an explicit rule cannot use the agent

### A2aAgentForm

Create/edit form with:
- Base URL (required) with helper text about Agent Card endpoint
- Authentication section: radio toggle for None / OAuth2
- When OAuth2: well-known URL, client ID, client secret (password input with "(unchanged)" placeholder in edit mode), scopes (space-separated), delegation mode radio toggle (M2M / OBO), OBO grant type selector (shown when OBO selected)
- "Test Connection" button (only shown in edit mode) with success/failure badge result
- Register/Update and Cancel buttons

---

## 9. Settings View

**Purpose:** Manage display preferences and platform configuration.

**Content:**
- Page header: "Settings" with description "Manage display preferences."
- **Preferences** section: Theme selector (grouped by Light/Dark using SelectGroup/SelectLabel, always drops down via `position="popper"`) and Timezone selector (local/UTC)
- **Enabled Models** section (requires `settings:read`/`settings:write`): Split into a Bedrock block and an optional LiteLLM block (connection toggle, base URLs, write-only master key, Refresh button) — see [17. Alternate LLM Providers](#17-alternate-llm-providers-litellm-proxy). Per-vendor grouped checkboxes within each provider block for selecting which models are available platform-wide, plus a text filter. When none are selected for a provider, all of that provider's models are available. Save button with confirmation indicator. Status text shows count (e.g., "8 of 22 models enabled"). Uses `groupModels()` utility for alphabetical vendor grouping. Configuration is saved via `PUT /api/settings/models`.
- Always visible in the sidebar (no scope guard for visibility)

---

## 9a. Tagging View

**Purpose:** Manage tag policies (platform + custom) and tag profiles.

**Tag Designations:**
- `platform:required` — tags with `loom:` prefix. Required for all resources. Read-only in the policy list (Lock icon). Always shown as input fields in the profile form.
- `custom:optional` — user-defined tags without `loom:` prefix. Optional, editable, deletable. In the profile form, each appears as a checkbox; checking it reveals a value input.
- Designation is computed from the key (not stored). The legacy `source` column is retained in the DB for backward compatibility but is not exposed in the API or UI.

**Content:**
- Page header: "Tagging" with description "Manage tag policies and tag profiles."
- **Tag Policies** section (top): displays `platform:required` tags as read-only rows with a Lock icon and designation badge, followed by `custom:optional` tags (editable/deletable with designation badge). "Add Custom Tag" button shows a form with: key (text, required), default value (optional text), show on card (checkbox, default true). Custom tags are always created as `required=false`. Sort toggle (A-Z/Z-A) available for policies and profiles.
- **Tag Profiles** section (below policies): list, create, edit, delete named tag presets
  - Each profile card shows: name, timestamps, and tag value badges
  - Collapsible profile groups: platform required tags and custom optional tags are in collapsible sections (ChevronDown/ChevronRight toggle)
  - Create/edit form has two sections:
    1. **Platform (Required)** — input fields for each `platform:required` tag (mandatory, marked with `*`)
    2. **Custom (Optional)** — checkbox per custom tag; checking reveals a value input. Unchecking removes the tag from the profile.
  - Form-fill import: JSON import via `JsonConfigSection` auto-populates profile form with tag key-value pairs from the imported JSON
  - Accessible to all scopes; `*:write` can create, edit, and delete; `*:read` can only view
  - Delete with inline confirmation (Confirm/Cancel)
- Always visible in the sidebar (no scope guard for visibility)

---

## 10. Session Detail View

**Purpose:** Inspect a single session's invocations and CloudWatch logs.

**Content:**
- Session metadata card — session_id, qualifier, live status badge, created timestamp
- Invocation table — all invocations with timing data
- Tabbed layout (shadcn Tabs) with **Logs** and **Traces** tabs, defaulting to Logs
- **Logs tab**: Log source selector — dropdown to switch between session-filtered logs (service-level), individual log streams (with simplified stream name display and timezone-aware timestamps), and vended log sources (runtime APPLICATION_LOGS, runtime USAGE_LOGS, memory APPLICATION_LOGS)
- **Traces tab**: Trace list table (Trace ID, Start Time, End Time, Duration, Spans, Events). Description text indicates clicking a trace ID for detail. Clicking a trace shows the interactive `TraceGraph` waterfall timeline with per-span event inspection. Traces are lazy-loaded on first tab activation.
- Log controls — toggle buttons for line numbers (`#` icon, enabled by default) and timestamps (clock icon, enabled by default), plus a Refresh button that cache-busts by appending a `_t` timestamp parameter
- Log viewer — paginated display (200 lines per page) with first/prev/next/last navigation, global line numbering across pages, and "Showing N–M of T log lines" indicator. Pagination controls appear at top and bottom when content exceeds one page.

---

## 11. Design Decisions

### Persona-Based Navigation
Chose a sidebar with persona-based workflows over traditional tab navigation. Each persona represents a distinct user role (catalog browser, agent builder, security admin, memory manager) with its own page and feature set. The sidebar provides persistent access to all personas and includes theme/timezone controls.

### Navigation: Lifted State vs. Router
Chose lifted state in `App.tsx` over React Router. Persona selection and drill-down navigation (within Catalog) are managed via state variables. A router would add unnecessary complexity for this use case.

### Layout: Stacked Single-Column for Agent Detail
Full-width stacked layout gives each section appropriate breathing room. Sessions are shown first as primary context, followed by invoke form, latency summary, response pane, and deployment details.

### Dynamic Expansion: Response Pane and Log Viewer
Both use plain `div` containers with no `max-height` or `ScrollArea` constraint, letting content grow naturally. The log viewer paginates at 200 lines per page with navigation controls to avoid rendering performance issues with large log sets.

### AgentCard Grid Stability
The delete confirmation uses absolute positioning (`absolute inset-x-0 bottom-0`) to overlay the card rather than expanding it, preventing layout shifts in the responsive grid.

### Grouped Searchable Model Selector
Model selection uses `SearchableSelect` with group headers sorted alphabetically by vendor (Anthropic, Amazon, DeepSeek, Google, Meta, MiniMax, Moonshot AI). The `groupModels()` utility in `src/lib/models.ts` groups `ModelOption[]` by `group` field and returns sorted `[string, ModelOption[]][]` tuples. Search matches both display name and model ID value, allowing power users to search by inference profile ID. No default is pre-selected — the user must explicitly choose a model on both register and deploy forms.

### Theme System
10 themes organized into Light and Dark groups:
- **Light:** Ayu Light (white + blue), Catppuccin Latte (cool blue-gray, default), Everforest Light (warm green), Rosé Pine Dawn (warm rose), Solarized Light (warm yellow-blue)
- **Dark:** Ayu Dark (dark blue), Catppuccin Mocha (deep purple-blue), Dracula (vibrant purple), Nord (arctic blue), Tokyo Night (indigo blue)

ThemeContext manages theme state with localStorage persistence. Latte uses `:root` variables (no class); all other themes use CSS class selectors on `<html>`. The `@custom-variant dark` includes all dark theme classes (`dark`, `dracula`, `ayudark`, `nord`, `tokyonight`). Badge `default` and `secondary` variants include `border-border` for visibility across all themes.

**WCAG Accessibility Compliance:**
All themes target WCAG 2.1 AA or better:
- Text contrast (`--foreground`, `--muted-foreground`): ≥ 4.5:1 against their background surface
- Border contrast (`--border`): ≥ 3:1 against adjacent surfaces

Light theme card backgrounds are set to significantly darker surface values (e.g., Latte uses Catppuccin `surface0 #ccd0da` as card, vs. the `base #eff1f5` background) so cards are visually distinct from the page. Dark theme `--muted-foreground` and `--border` values are lightened relative to prior values to satisfy contrast thresholds on dark surfaces.

### Drag-to-Reorder Card Grid with Alphabetical Sorting
`SortableCardGrid` uses @dnd-kit/core + @dnd-kit/sortable for drag-and-drop reordering of cards within grid sections. Order is persisted to localStorage keyed by `storageKey`. Uses `PointerSensor` with 8px activation distance, `rectSortingStrategy`, and `closestCenter` collision detection.

**Default alphabetical sorting:** All cards are sorted alphabetically (case-insensitive, A-Z) on initial load when no persisted custom order exists. The `getName` prop extracts the display name from each item for sorting. New items not in a persisted order are sorted alphabetically among themselves and appended after persisted items.

**Sort toggle control:** A standalone `SortButton` component (ArrowDownAZ/ArrowUpAZ icons) is placed inline with each section header, next to "Add" buttons. Sort direction is controlled by the parent component and persisted to localStorage per grid (keyed as `loom-sort-${storageKey}`). `SortableCardGrid` accepts `sortDirection` as a controlled prop. After applying a sort option, drag-to-reorder still works — once the user drags a card, the new order becomes the custom order, the sort direction is cleared via the `onSortDirectionChange(null)` callback, and the custom order is persisted. Exported helpers: `loadSortDirection()`, `saveSortDirection()`, `toggleSortDirection()`.

**Table view column sorting:** Pages with table views (CatalogPage, AgentListPage, MemoryManagementPanel, McpServersPage, A2aAgentsPage) use `SortableTableHead` for clickable column headers. Clicking a column header sorts by that column (ascending); clicking again reverses to descending. An arrow indicator (ArrowUp/ArrowDown) shows the active sort column and direction. The `sortRows()` helper provides generic multi-column sorting with support for both string and numeric values.

**Table column layout standards:**
- **Agent tables** (AgentListPage, CatalogPage): Name 26%, Status 10%, Cost 12%, Protocol 12%, Network 12%, Region 12%, Registered 16%.
- **Memory tables** (MemoryManagementPanel, CatalogPage): Name 26%, Status 10%, Cost 12%, Strategies 12%, Event Expiry 12%, Region 12%, Registered 16%.
- **MCP Server tables** (McpServersPage, CatalogPage): Name 18%, Endpoint 46%, Transport 10%, Auth 10%, Created 16%.
- **A2A Agent tables** (A2aAgentsPage, CatalogPage): Name 18%, URL 46%, Version 10%, Auth 10%, Created 16%. Matches MCP structure — no Provider or Status column.
- All tables use `table-fixed` with the above widths summing to 100%. Delete/refresh operations are card-view only; no action columns in tables.

**Applied to all card grids:** CatalogPage (agents, memories), AgentListPage (agents), MemoryManagementPanel (memories), TaggingPage (policies, profiles), RoleManagementPanel (roles, full-width single-column), AuthorizerManagementPanel (authorizers), PermissionRequestsPanel (permissions).

### Registry `registryEnabled` Pattern
All pages displaying registry UI elements (RegistryStatusBadge, RegistryActions) fetch `getRegistryConfig()` on mount and maintain a `registryEnabled` boolean state. When registry is disabled (no ARN configured in Settings), all registry badges and action buttons are hidden:
- `RegistryStatusBadge` accepts a `registryEnabled` prop (default `true`). When `false`, returns `null` regardless of status.
- `RegistryActions` rendering is gated at each render site via `{registryEnabled && <RegistryActions ... />}`.
- `AgentCard` accepts `registryEnabled` (default `true`) and passes it to its embedded `RegistryStatusBadge`.
- Applied consistently across CatalogPage, AgentListPage, McpServersPage, and A2aAgentsPage in both card and table views.

### Tailwind CSS v4 (Vite Plugin)
Using the `@tailwindcss/vite` plugin instead of PostCSS. Configuration is handled via CSS `@theme` blocks in `index.css`.

### Timezone-Aware Timestamps
All timestamps use shared utilities in `src/lib/format.ts`. A `TimezoneContext` stores the user's preference ("local" or "UTC"), applied globally.

### SearchableSelect Component
Custom combobox with click-outside detection, filtered option list, check mark for selected item, and optional group headers. Accepts a `className` prop for width control. Filter matches both `label` and `value` fields.

### JsonConfigSection Component
Shared collapsible component for JSON import/export on forms. Encapsulates the collapse/expand toggle (ChevronRight/ChevronDown), monospace textarea, and Apply/Export/Cancel button row. Props: `onApply(json) => string | null` (returns error or null on success), `onExport() => string`, optional `label` and `placeholder`. On successful apply, the input clears and the section auto-collapses. On export, the serialized JSON is written to the textarea and the section expands if collapsed. Used by both `AgentRegistrationForm` and `MemoryManagementPanel` to ensure consistent behavior. Export produces human-readable JSON (model ID for agents, role names, profile names rather than internal IDs) that is valid input for import (round-trip capable).

### TagInput Pattern
Inline component for adding/removing tag-style values (clients, scopes). Single textbox with Enter to add, badge with X to remove.

### Secrets Handling
Cognito client secrets are password-masked in forms. Secrets are sent to the backend which stores them in AWS Secrets Manager — they never persist in the frontend or local database.

### User Authentication
- `AuthContext` provides login, logout, logoutIdP, token refresh, user state, and scope-based authorization to the entire app.
- `logout()` clears local state only (tokens, user, session storage). `logoutIdP()` calls `logout()` then redirects to the external IdP's logout endpoint (Okta or Entra ID) so the browser session is also cleared. Regular logout uses `logout()`; "Sign in as a different user" on the login page uses `logoutIdP()`.
- Tokens (id, access, refresh) are stored in React state only — never in localStorage or cookies.
- On logout, all `loom:invokePrompt:*` keys are cleared from `sessionStorage` so per-agent prompt drafts do not persist across user sessions.
- The `AuthProvider` wraps the app at the top level (outside `TimezoneProvider`). If Cognito is not configured (empty pool ID from backend or missing `VITE_COGNITO_USER_CLIENT_ID`), authentication is bypassed and all scopes are granted.
- The user client ID is configured via the `VITE_COGNITO_USER_CLIENT_ID` Vite environment variable (in `frontend/.env`), not fetched from the backend. The backend only provides the pool ID and region via `GET /api/auth/config`.
- `LoginPage` renders when the user is not authenticated. It handles the `NEW_PASSWORD_REQUIRED` challenge for admin-created Cognito users.
- Access tokens are automatically refreshed 60 seconds before expiry using the refresh token.
- The user indicator (username + logout button) is shown in the sidebar footer, above the theme selector.
- `apiFetch` and `invokeAgentStream` automatically include the `Authorization: Bearer` header when a token is available, via a module-level token setter (`setAuthToken`/`getAuthToken`).
- On 401 responses, `apiFetch` calls a registered `onUnauthorized` callback that refreshes the Cognito access token via `REFRESH_TOKEN_AUTH` and retries the failed request. This prevents expired token errors during long sessions.

### Scope-Based Authorization
- `AuthContext` extracts `cognito:groups` from the decoded ID token and maps them to scopes using a `GROUP_SCOPES` lookup table (must match the backend `GROUP_SCOPES` exactly). The `hasScope(scope)` function is exposed to the entire app.
- Scopes (21 total): `invoke`, `catalog:read`, `catalog:write`, `agent:read`, `agent:write`, `memory:read`, `memory:write`, `security:read`, `security:write`, `settings:read`, `settings:write`, `tagging:read`, `tagging:write`, `costs:read`, `costs:write`, `mcp:read`, `mcp:write`, `a2a:read`, `a2a:write`, `registry:read`, `registry:write`.
- Two-dimensional group architecture:
  - **Type groups**: `t-admin` (admin UI), `t-user` (user UI) — determine layout and default navigation
  - **Resource groups**:
    - `g-admins-super`: All 21 scopes (full access)
    - `g-admins-demo`: Read/write to most pages including MCP and A2A + demo group resources
    - `g-admins-security`, `g-admins-memory`, `g-admins-mcp`, `g-admins-a2a`: Domain-specific admin scopes
    - `g-admins-registry`: `mcp:read`, `a2a:read`, `registry:read`, `registry:write`, `settings:read`, `settings:write`, `tagging:read`
    - `g-users-demo`, `g-users-test`, `g-users-strategics`: invoke + group-filtered read access
- Sidebar visibility is controlled by scopes — each persona item is rendered only when the user has the corresponding `*:read` or `*:write` scope. Platform Catalog, Tagging, and Settings are always visible.
- Write operations are gated by a `readOnly` prop propagated from `App.tsx` through page components to individual UI elements. When `readOnly` is true, add/edit/delete buttons are disabled or hidden.
- Pages and their `readOnly` mapping: `AgentListPage` and `CatalogPage` use `!hasScope("agent:write")`, `SecurityAdminPage` uses `!hasScope("security:write")`, `MemoryManagementPage` uses `!hasScope("memory:write")`, `TaggingPage` uses `!hasScope("tagging:write")`.
- Components that respect `readOnly` and `userGroups`: `AgentCard`, `AgentListPage`, `CatalogPage`, `SecurityAdminPage`, `RoleManagementPanel`, `AuthorizerManagementPanel`, `PermissionRequestsPanel`, `MemoryManagementPage`, `MemoryManagementPanel`, `MemoryCard`, `TaggingPage`.
- Demo-admin restrictions: Delete buttons hidden for resources not in demo group via `userGroups` prop. Tag policy edit restricted to super-admins only. Tag profile edit restricted by group ownership.

### Resource Tagging
- Tag policies use a two-tier designation system: `platform:required` (keys starting with `loom:`) and `custom:optional` (all others). Designation is computed from the key, not stored. Filter categorization uses the `required` flag, not key prefix.
- Tag policies are fetched from `/api/settings/tags` and used to derive `showOnCardKeys` for tag badge display and filter dropdowns.
- Tag profiles are named presets managed via the Tagging page. The `ResourceTagFields` shared component renders a profile dropdown (persisted in `sessionStorage` as `loom:selectedTagProfileId`), resolves tags from the selected profile + policy defaults, displays all profile tags as badges, and calls `onChange(tags)`. Used by both agent deploy and memory create forms.
- `ResourceTagFields` accepts an optional `groupRestriction` prop. When set (for demo-admins), only profiles whose `loom:group` matches the restriction are shown, and the resolved `loom:group` tag is forced to the restriction value. `MemoryManagementPanel` also receives `groupRestriction` for the same purpose.
- Tag resolution: for each policy, use user-supplied value → fall back to `default_value` (only for required policies) → error if required and missing. Custom/optional tags only appear when the profile explicitly sets them. The previous `source` (build-time/deploy-time) distinction has been removed.
- `showOnCardKeys` (derived from tag policies with `show_on_card=true`) is filtered by the eyeball toggle to produce `effectiveShowOnCardKeys`, which is passed as a prop to `AgentCard` and `MemoryCard` components from all listing pages.
- Tag badges use `variant="secondary"` to visually distinguish them from status and protocol badges.
- **Progressive disclosure filtering:** All listing pages (CatalogPage, AgentListPage, MemoryManagementPanel) split show-on-card policies into required and custom using the `required` flag. The filter bar renders in order: required filters → eyeball toggle → activated custom filters → "custom filters" Add dropdown → Clear filters → item count. All label rows use fixed `h-4 flex items-center` wrappers for consistent visual alignment. Custom `AddFilterDropdown` component (not Radix Select) provides the "Add filter" dropdown with click-outside-to-close behavior.
- **Custom tag show/hide toggle:** An Eye/EyeOff button in the filter bar (positioned left of custom filter dropdowns) toggles visibility of custom tags on agent and memory cards. The preference is persisted to `localStorage` as `loom:showCustomTags`. When hidden, only required tags appear on cards; filtering still works independently.
- **Filter persistence:** Both `tagFilters` and `activeCustomFilterKeys` are persisted to `localStorage` per page (e.g., `loom:tagFilters:agents`, `loom:customFilterKeys:catalog`) so filter state survives page navigation.
- Filter state uses `Record<string, string[]>` to support multiple selected values per tag key with AND logic.

### MultiSelect Component
Custom dropdown with checkboxes for multi-value selection. Uses `min-w-[140px]` with auto-expanding width to fit content (no truncation). Closes on outside click via `mousedown` event listener. Shows "All" when no values selected, the value when one is selected, or "N selected" for multiple. Uses `bg-input-bg` to match the existing `Select` component styling.

### AddFilterDropdown Component
Custom dropdown for adding custom tag filters to the filter bar. Uses a plain `<button>` with an absolute-positioned option list (not Radix Select, which has issues with empty controlled values). Shows a Plus icon and "Add filter" label, with a ChevronDown indicator. Closes on outside click via `mousedown` event listener. Each option triggers `onSelect` and closes the dropdown. Matches `MultiSelect` styling (`h-7`, `min-w-[140px]`, `bg-input-bg`).

### Pydantic Error Handling
`apiFetch` in `client.ts` handles Pydantic validation errors where `detail` is an array of objects (not a string). Array entries are mapped to their `msg` fields and joined with `"; "` for display. This prevents `[object Object]` from appearing in error toasts.

### API Layer Design
- `apiFetch<T>()` is a thin wrapper around `fetch` with JSON parsing, `ApiError` class, automatic auth token injection, and 401 auto-refresh (intercepts unauthorized responses, refreshes the token, and retries once)
- `tryRefreshToken()` is exported from `client.ts` for use by `invokeAgentStream()` to retry SSE connections on 401, since SSE streaming bypasses `apiFetch`
- Each API domain (agents, auth, invocations, logs, security) is a separate module with typed functions
- `api/a2a.ts` — A2A agent operations: CRUD, test connection, card retrieval/refresh, skills, access rules

### Session Liveness Display
Computed server-side using `LOOM_SESSION_IDLE_TIMEOUT_SECONDS`. The frontend displays `live_status` with color-coded badges and `active_session_count` on agent cards.

### View Mode Persistence
Card/table view mode state is lifted to `App.tsx` with separate state variables per page (`catalogViewMode`, `agentsViewMode`, `memoryViewMode`). Each page receives its mode and setter as props. This ensures the selection persists when switching between personas — the page components unmount but the state lives in the parent.

### Deploy Flow
Agent deployment uses a fire-and-forget pattern. The form collapses immediately on deploy, the backend creates a DB record before starting the AWS call, and `fetchAgents()` picks up the new record. The `useAgents` hook polls transitional agents (deploying/CREATING/endpoint CREATING) at 2-second intervals using a `watchIds` effect dependency. Smart polling: during local build phases (`creating_credentials`, `creating_role`, `building_artifact`, `deploying`), the backend returns DB state without AWS API calls. An `initialLoadDone` ref prevents skeleton flash on subsequent fetches. Agent cards show two-phase creation status: deploying → completing deployment → finalizing endpoint, with a timer using `registered_at` to avoid resets on phase transitions. Agent deletion with AWS cleanup follows a matching async pattern: the DELETE endpoint marks the agent as DELETING, the hook polls at 2-second intervals, detects 404 when the runtime is fully deleted, uses a background task for DB purge after runtime is confirmed deleted, and shows a success toast.

### SSE Stream Consumer
`invokeAgentStream()` uses `ReadableStream` to consume POST-based SSE responses with buffer-based line parsing, typed callback dispatch, and `AbortSignal` for cancellation. Supports `onToolUse` callback for `event: tool_use` SSE events. On 401 response, calls `tryRefreshToken()` (exported from `client.ts`) to refresh the auth token and retries the SSE request once, mirroring the `apiFetch` 401 retry pattern.

### StreamSegment Architecture
The `useInvoke` hook tracks streaming responses as an array of `StreamSegment` objects rather than a flat text string. Segments are either `{ type: "text", content: string }` or `{ type: "tool_use", name: string, index: number, total: number, timestamp: number }`. Text chunks are appended to the last text segment; tool_use events create new segments. The `segments` array, `currentToolName`, and `toolNames` are exposed alongside `streamedText` for backward compatibility. `StreamingBubble` (ChatPage) and the response pane (AgentDetailPage) render segments inline, interleaving `MarkdownBlock` and `ToolUseBlock` components. Tool names from the completed stream are persisted on `ChatMessage.toolNames` and displayed in finalized `MessageBubble` components.

### Queued Prompt (ChatPage)
The input textarea remains enabled during streaming. Sending a message while a response is streaming enqueues it (single slot, last-write-wins). The queued message appears as a dimmed bubble (`bg-primary/50`) with a cancel (X) button and full markdown rendering. It auto-sends when streaming completes (skipped on error). Switching agents or starting a new conversation discards the queued message. Send and cancel-stream buttons are independent (both visible during streaming).

### Deploy Card
When a deploy starts, `AgentListPage` records the deploying agent name and triggers an immediate `fetchAgents()` to pick up the DB record (created before the AWS API call). The `useAgents` hook handles ongoing polling for transitional agents. This replaced the earlier ephemeral card approach which caused position glitches when the real agent appeared.

### Resource Export/Edit System
`AgentCard` and `MemoryCard` replace the refresh button with a pencil-to-edit button (Pencil icon). Clicking edit on an agent navigates to the agent deploy form pre-filled with the agent's exported configuration. Memory cards open the create form pre-filled with the memory's configuration fetched via `GET /api/memories/{id}/export`. JSON export from the form serializes the current state including `memory_strategies` with strategy types and namespaces. This enables round-trip editing of existing resources.

### Tooltip Component
`frontend/src/components/ui/tooltip.tsx` — Radix Tooltip primitives with zero-delay appearance (`delayDuration=0`), animated content (fade-in/zoom-in), directional slide animations, and an arrow indicator. Used for instant username display on sidebar hover.

### Friendly Error Messages
`lib/errors.ts` provides `friendlyInvokeError(raw: string, authorizerName?: string): string` that maps raw error strings to user-friendly messages using pattern matching. When an `authorizerName` is provided (from the agent's `authorizer_config`), 401/403 errors include a hint about which authorizer to use. The `useInvoke` hook stores both the friendly error (for display) and the raw error (for the 'Show details' toggle). This keeps error UX readable while preserving debugging information.

### Credential Suggestion on Errors
`friendlyInvokeError()` accepts an optional `authorizerName` parameter (from the agent's `authorizer_config`). On 401/403 errors, if the agent has a configured authorizer, the error message includes a hint like: 'This agent uses the "authorizer-name" authorizer — make sure you select a credential from that authorizer.' This helps users identify the correct credential without trial and error.

### Authorizer Display on Agent Cards
Agent cards show the configured authorizer in the metadata section as a single outline badge. The backend extracts `customJWTAuthorizer` configuration from the AgentCore `describe_runtime` response on import and refresh, stores it as JSON in the `authorizer_config` column, and returns it in the agent response. The frontend renders the authorizer name (falling back to type, then "external") as a badge, or muted "None" when absent. Endpoint qualifiers are shown as comma-separated text (individual badges removed for cleaner display).

### Manual Bearer Token Input
The invoke panel's credential dropdown includes a "Manual token" sentinel value. Selecting it reveals a password input for pasting a raw bearer token. The token is passed in the invoke request body as `bearer_token` and takes highest priority (Priority 0) in the backend's token selection chain — above user tokens, credential-based tokens, and agent config tokens.

### Hooks
- `useA2aAgents()` — A2A agent list with auto-fetch, CRUD callbacks, toast notifications

### Key Components
- **A2aAgentForm** — Create/edit form for A2A agents with base URL input and progressive OAuth2 disclosure (auth_type toggle reveals well-known URL, client ID, secret, scopes). Test connection button in edit mode.
- **A2aAgentCardView** — Structured display of the full Agent Card: header (name, version, status, provider, documentation, refresh button with last-fetched timestamp), capabilities and default modes displayed inline (streaming yes/no, push notifications, state history as badges, input/output modes with "none" fallback for empty arrays), authentication schemes, and skills list.
- **A2aSkillList** — Compact expandable skill rows matching MCP tool list style. Each row shows name and description with chevron toggle. Expanded view shows skill ID, tag badges, examples (bulleted list), and input/output mode overrides. Single-column grid layout.
- **A2aAccessControl** — Per-persona access control for A2A agent skills. Checkbox to grant/revoke access, all_skills/selected_skills radio, individual skill checkboxes with descriptions. Deny by default.

### Views

| View | Persona | Description |
|------|---------|-------------|
| A2aAgentsPage | A2A Agents | A2A agent CRUD, agent detail with Agent Card and Access tabs, card/table views |
| CostDashboardPage | Costs | Cost dashboard with time-range selector (7d/30d/90d/All), summary cards (Total Cost, Model Tokens, Runtime, Memory), Estimated Costs table with per-agent breakdown and methodology formulas, Actual Costs with separate Runtime and Memory sub-sections, collapsible agent groups for Runtime, consolidated per-resource rows for Memory, sortable columns |

### Token Usage and Cost Display

- **LatencySummary** renamed to "Invocation Metrics": single-row layout with 7 metrics — Client Invoke, Agent Start, Cold Start, Duration, Input Tokens, Output Tokens, Est. Cost.
- **InvocationTable**: 3 additional columns — Input Tokens, Output Tokens, Est. Cost with formatting helpers.
- **AgentCard**: READY status badge hidden; cost badge shown when `total_estimated_cost > 0`.
- **Agent table view**: Includes an Estimated Cost column (12%) showing the agent's total estimated cost from `cost_summary.total_cost`. Formatted as `~N.NNNNNN` for costs below $0.01 or `~N.NNNN` otherwise. Shows `—` (U+2014) when no cost data is available.
- **Memory table view**: Includes an Estimated Cost column (12%) showing `cost_summary.total_memory_estimated_cost`. Same formatting as agent cost column.
- **MemoryCard**: ACTIVE status badge hidden for visual cleanliness.
- **CostDashboardPage**: Three-section cost dashboard:
  - **Summary cards**: Total Cost (Model + Runtime + Memory), Model Tokens (with invocation count), Runtime (CPU + Mem breakdown), Memory (STM + LTM breakdown).
  - **Estimated Costs table**: Per-agent breakdown with columns Agent, Model, Invocations, Model Tokens, AgentCore Runtime, AgentCore Memory, Per Invoke, Total. Single-row per agent with sub-details as `text-[10px]` inline divs (token in/out, CPU+Mem split, STM+LTM split). Methodology formulas displayed below header. Sortable columns via `SortableTableHead`. Estimates disclaimer: costs are estimates based on token heuristics and pricing defaults.
  - **Actual Costs** with separate Runtime and Memory sub-cards:
    - **Runtime**: Collapsible agent groups — each agent row shows agent name, session count, total CPU cost, total memory cost, and subtotal. Expand to see individual session rows with event counts, time range, resource hours (vCPU·h, GB·h), and per-session costs. Sortable at the agent level. Description: "Costs from runtime USAGE_LOGS for the runtime within the time window. CPU I/O wait discount: N%, configurable in Settings." Note: USAGE_LOGS session IDs are internal to AgentCore and do not match Loom's runtimeSessionId.
    - **Memory**: Consolidated per-resource table with columns Memory, Log Events, Extractions, Consolidations, LTM Retrievals, Records Stored, Total. One row per memory resource. Sortable columns. Description: "Costs from memory APPLICATION_LOGS. Memory pipeline session IDs are internal to AgentCore and do not correlate with runtime session IDs."
    - NOTE: "Delivery of usage logs for calculating actual costs can be delayed. If costs are not showing up, try again in 15 minutes."
  - Pull Actuals button with loading timer. Module-level cache preserves actuals across page navigation.
  - Time-range selector: 7d, 30d, 90d, All buttons. Changing time range clears cached actuals.
- **SettingsPage**: CPU I/O Wait Discount input (0–99%) with save-on-blur and Enter key support. Description: "Assumed % of CPU time spent waiting on I/O. Applied as a discount to runtime CPU cost across estimates and actuals."

---

## 12. Admin Dashboard

**Purpose:** Platform usage analytics for super-admins. Accessible only via `isAdmin` check — the sidebar item is hidden for non-admin users.

**Auth context additions:**
- `browserSessionId: string | null` — UUID generated at login via `crypto.randomUUID()`, stored in React state (not localStorage). Resets on page refresh or re-login to distinguish usage sessions.
- On login: `recordLogin(username, browserSessionId)` is called fire-and-forget via `audit.ts`.
- On logout: `browserSessionId` is cleared to `null`.

**Page view tracking (`App.tsx`):**
- A `pageEntryRef` records `{persona, enteredAt}` for the currently active persona.
- When `activePersona` changes, the previous page's duration is computed and `recordPageView` is called fire-and-forget.
- A `beforeunload` listener uses `navigator.sendBeacon` to POST the final page view when the tab is closed.

**Action tracking (`audit.ts` → `trackAction`):**
- `trackAction(userId, browserSessionId, category, type, resourceName?)` — fire-and-forget wrapper around `recordAction`.
- Called at the point of submission (before the API call, not on success) in all page and component handlers.
- Categories and actions instrumented:

| Category | Actions |
|----------|---------|
| `agent` | `deploy`, `import`, `invoke`, `redeploy`, `delete`, `remove_conversation` |
| `memory` | `create`, `import`, `delete` |
| `security` | `add_role`, `delete_role`, `add_authorizer`, `add_credential`, `delete_authorizer`, `approve_request`, `deny_request` |
| `tagging` | `add_tag`, `edit_tag`, `delete_tag`, `add_profile`, `edit_profile`, `delete_profile` |
| `mcp` | `add_server`, `delete_server`, `test_connection`, `invoke_tool`, `update_permissions` |
| `a2a` | `add_agent`, `delete_agent`, `test_connection`, `update_permissions` |

`remove_conversation` is emitted from `ChatPage` when a user removes a conversation from the sidebar (calls `hideSession` then records the action with the agent name as the resource name).

**Dashboard layout (`AdminDashboardPage.tsx`):**
- **Global user filter:** Multi-select dropdown in the header (labeled "Users:") listing all unique user IDs from the loaded data. Selecting users filters all summary cards, charts, and tab tables to only that subset. When no users are selected ("All users"), the full unfiltered data is shown. When a filter is active, summary stats are recomputed client-side from the filtered sessions, actions, and page views (rather than relying on the API summary, which is unfiltered). Pagination page counters reset when the filter changes.
- Time range selector: Today / Last 7 days / Last 30 days / All time.
- Summary cards (5): Total Logins, Total Page Views, Total Actions, Total Duration, Most Active Page. Stats reflect the active user filter when set.
- Charts (recharts, 3): Logins Over Time (bar chart, daily), Actions Over Time (bar chart, daily), Page Views by page name (horizontal bar chart). All charts use custom tooltip components for consistent theme-aware styling. Chart data reflects the active user filter.
- Tabs (3): Sessions, Actions, Page Views.
  - **Sessions:** Table of aggregated browser sessions (session ID, user, login time, last activity, page view count, action count, duration). Clicking a row shows the full interleaved event timeline (logins, actions, page views). Filtered by the global user filter.
  - **Actions:** Table with category and action type filters. Filtered by the global user filter.
  - **Page Views:** Table with page name filter. Filtered by the global user filter.

---

## 13. End-User Chat Interface

**Purpose:** A consumer-oriented chat experience for end-users (`t-user` group). Hides all admin functionality and presents a clean, focused interface for interacting with agents.

### Routing

After authentication, `App.tsx` checks whether the effective user (real or "view as") belongs to the `t-user` type group and not `t-admin`. If so, `ChatPage` is rendered instead of the admin layout. Admins can switch to end-user mode via the "View as" dropdown by selecting any `demo-user-*` or `test-user` account.

A "Previewing end-user experience as [user]" banner is shown to admins when in view-as mode, with an "Exit preview" button that returns to the admin layout.

### ChatPage (`frontend/src/pages/ChatPage.tsx`)

**Layout:** Two-column with a narrow left sidebar and a main chat area. An optional right panel shows memory information. Content is centered with a max-width on wide screens.

**Sidebar contents:**
- Logo
- Agent picker — shown only when multiple agents are accessible; auto-selected when only one exists
- "New Conversation" button
- Conversation history list (past sessions for the current user, showing date/time and message count)
- "My Memory" button (shown only when the selected agent has memory resources attached)
- User indicator and logout button

**Agent filtering:** Agents are filtered client-side by comparing the agent's `loom:group` tag against the user's `g-users-*` group names. An agent with no `loom:group` tag is visible to all users. Agents with `deployment_status === "removing"` (DELETING) are excluded from the list.

**Chat area:**
- Header with agent name and "responding..." indicator while streaming (scoped to the active conversation)
- Scrollable message history with alternating user (right-aligned, primary color) and assistant (left-aligned, muted) bubbles
- In-flight messages displayed during streaming: user prompt bubble immediately, `StreamingBubble` with segment-based rendering (interleaved `MarkdownBlock` and `ChatToolUseBlock` components) and animated cursor
- Thinking indicator (bouncing dots + "thinking...") shown while streaming with no segments
- Inline tool-call indicators in `ChatToolUseBlock`: Wrench icon, counter (N/M), `ChatElapsedTimer` with live seconds, bounce animation while active. Tool names displayed with `formatToolName()` stripping MCP server prefixes. Tool names from completed streams persist on `ChatMessage.toolNames` and are shown in finalized `MessageBubble` components.
- Markdown rendering for all message bubbles (user, assistant, and queued) via `react-markdown` + `remark-gfm`: paragraphs, headings (h1–h3), ordered/unordered lists, tables, blockquotes, inline code, fenced code blocks, bold, links. Assistant responses additionally render JSON code blocks as collapsible `CollapsibleJsonBlock` components (click to expand/collapse).
- Error display as styled text in the chat area
- Input area with rounded border container: Textarea at top (borderless), footer row with model picker (left of Send) and Send/Cancel buttons (right)

**Model selection:**
- Model picker button in the input area footer (right side, left of Send), shown when the agent has multiple allowed models. Displays the current model's display name (or agent default). Click to open a dropdown grouped by vendor via `groupModels()` with section headers; click-outside-to-close behavior via `mousedown` listener. Default model marked with "(default)" suffix. Selecting a model sets `selectedModelId`; selecting the default clears it to `null`. Model selection resets when switching agents. The selected non-default model ID is passed as `model_id` in the invoke request.

**Session management:**
- New conversations start with no session ID; a new `InvocationSession` is created automatically on first invocation
- **Immediate session tab creation:** On `session_start` SSE event, the new session is immediately added to the sidebar conversation list and auto-selected (highlighted). The conversation tab appears as soon as the agent acknowledges the invocation — before the response finishes streaming.
- After each invocation, `sessionEnd.session_id` is captured and used for subsequent messages in the same conversation
- On `sessionEnd`, messages are loaded from the backend via `getSession()` as the authoritative source. `setPendingPrompt(null)` is deferred until after `setMessages()` completes, preventing the streaming bubbles from disappearing before persisted messages are ready.
- Resuming a past session calls `getSession()` and reconstructs the message history from `invocation.prompt_text` / `invocation.response_text` pairs
- Removing a conversation calls `hideSession()`, records a `remove_conversation` audit action via `trackAction`, and clears the chat area if the removed session was active. The remove button is shown on all owned sessions except the one currently streaming — sessions with an active AgentCore Runtime session (but not actively streaming a response) are removable.

**Streaming state scoping:**
- `isCurrentlyStreaming` is derived as `isStreaming && (!sessionStart || sessionStart.session_id === currentSessionId)`. The thinking spinner, streaming bubble, and "responding..." header text are all conditioned on `isCurrentlyStreaming`, not `isStreaming`. This prevents streaming UI from leaking into unrelated conversations when the user switches sessions mid-stream.

**`useInvoke` subscription stability:**
- `clearInvokeState(agentId)` resets the module-level store to `EMPTY` and notifies subscribers, but does NOT remove the listener set for the agent. This keeps the component's subscription alive after "New Conversation" so that subsequent invocations correctly propagate to the UI. Deleting the listener entry (the prior behavior) caused a silent state-update drop where streams ran to completion without any React re-renders.

**MCP Connectors:**
- "Connectors" button in the input area footer (left of model picker), shown when MCP connectors are available
- Dropdown lists MCP servers with per-server toggle switches (green when enabled)
- API key connectors (`auth_type === "api_key"`) show a KeyRound icon when key is not set; toggling on prompts a modal dialog for key entry. Disconnect (Unplug icon) deletes the stored key from Secrets Manager.
- OAuth2 connectors show "OAuth2" label when disabled (currently no user-side auth flow — admin-configured credentials are used)
- Enabled connector state persisted to `localStorage` per agent (`loom:enabledConnectors:{agentId}`) and reset when switching agents
- Active connector count shown as a green badge on the Connectors button
- Connector IDs are passed through the invoke request as `connector_ids`

**Abstractions (admin details hidden):**
- No qualifier picker (always uses `DEFAULT`)
- No credential selector (uses default)
- No session ID display
- No bearer token input

### Memory Panel

Accessible via the "My Memory" sidebar button when the selected agent has memory resources.

**Session Memory section:**
- Shows the current conversation's exchange count
- Lists any custom-strategy names/descriptions from attached memory resources

**"What I Remember About You" section (long-term):**
- Shown only when at least one long-term strategy exists (`semantic`, `summary`, `user_preference`, `episodic`)
- Displays each strategy's admin-configured `name` and `description` as user-facing labels
- No memory IDs, ARNs, namespaces, strategy types, or configuration objects exposed

**User isolation:**
- Session list filtered server-side via the `user_id` query parameter passed to the `list_sessions` API; the frontend passes `currentUserId` from Cognito auth to scope sessions per user
- Session list refresh is suppressed while an invocation is actively streaming (`isStreaming` guard) to prevent race conditions between auth resolution and session state
- Memory content is managed by the agent; the panel shows strategy metadata only

---

## 14. 3rd-Party Identity Provider Support

### Overview

The frontend supports federated login via 3rd-party OIDC identity providers (Microsoft Entra ID, Okta, Auth0, Generic OIDC) alongside the existing Cognito `USER_PASSWORD_AUTH` flow. The active provider is determined by the `GET /api/auth/config` response at startup.

### OIDC Authorization Code + PKCE Flow

When an external IdP is active, `AuthContext` uses the standard Authorization Code flow with PKCE (Proof Key for Code Exchange):

1. `startOIDCLogin()` generates a cryptographic code verifier and challenge, stores state in `sessionStorage`, and redirects to the provider's authorization endpoint.
2. On callback, `exchangeOIDCCode()` exchanges the authorization code for tokens at the provider's token endpoint using the stored code verifier.
3. Group claims are extracted from the ID token using the provider's configured `group_claim` and mapped to Loom groups via the `group_mapping` from the auth config. Empty group mappings (`{}`) are treated as "no mappings" — raw groups are passed through unchanged. This prevents the JavaScript truthiness of `{}` from discarding all groups.

Functions are implemented in `frontend/src/api/auth.ts`.

### LoginPage

When an external IdP is active:
- A provider-branded button is shown (e.g., "Sign in with Microsoft Entra ID", "Sign in with Okta").
- Clicking the button initiates the OIDC redirect flow.
- Below the button, the last OIDC username is displayed if available (persisted in `localStorage` as `loom_last_oidc_user`): "Currently logged in as [username]".
- A "Sign in as a different user" link triggers `logoutIdP()` which redirects to the IdP's logout endpoint (Okta `/v1/logout` or Entra ID `/oauth2/v2.0/logout`) with `post_logout_redirect_uri` back to the app.
- When both an external IdP and Cognito are configured, a tab bar allows switching between providers. The existing Cognito username/password form is shown on the Cognito tab.

When no external IdP is active, the login page behaves identically to the existing Cognito flow.

### Identity Provider Management UI

`IdentityProviderPanel.tsx` on the Security Admin page provides:
- **Identity Providers tab**: CRUD for provider configurations with fields for name, provider type (dropdown: Microsoft Entra ID, Okta, Auth0, Generic OIDC), discovery URL, client ID, client type toggle (public/confidential), group claim, and scopes.
- **OIDC Discovery button**: fetches `.well-known/openid-configuration` and auto-populates authorization, token, JWKS, and userinfo endpoints.
- **Test Discovery button**: validates that the provider's discovery endpoint is reachable and returns valid metadata.
- **Group Mapping table**: editable table for mapping external IdP group names/IDs to Loom groups. Each row has external group (text input) and Loom group (dropdown of known groups).
- **Status indicators**: each provider card shows a green/gray status dot (green for active, gray for inactive) and an "Active" badge when active.
- **Activate/Deactivate button**: each provider card has an "Activate" or "Deactivate" button. At most one external provider can be active; deactivating all falls back to Cognito.

### API Client

`frontend/src/api/identity_providers.ts` provides typed functions for all identity provider CRUD operations: `listIdentityProviders`, `getIdentityProvider`, `createIdentityProvider`, `updateIdentityProvider`, `deleteIdentityProvider`, `discoverOIDC`, and `testDiscovery`.

### Per-User Authorizer Linking

When a user's login IdP differs from an agent's authorizer (cross-IdP), the user can link their identity via an OAuth popup flow:

- **InvokePanel**: checks link status on mount when the agent has an authorizer. Shows "Link Account" button when not linked and not same-IdP. After linking, shows a green dot with "Unlink" option.
- **ChatPage**: same-IdP detection with tenant ID comparison. Same-IdP status skips all linking UI.
- **OAuthLinkCallbackPage** (`/oauth/link-callback`): minimal popup callback page that extracts the authorization code from URL params, exchanges it via the backend callback endpoint, and sends `window.opener.postMessage({type: "authorizer-linked", authId})` before closing.
- **API functions** in `frontend/src/api/security.ts`: `checkAuthorizerLinkStatus`, `getAuthorizerLinkAuthorizeUrl`, `submitAuthorizerLinkCallback`, `deleteAuthorizerLink`.

### Authorizer Allowed Audience

The `AuthorizerManagementPanel` includes an "Allowed Audience" field for configuring the `allowedAudience` parameter on AgentCore runtimes. This is separate from "Allowed Clients" — audience validates the JWT `aud` claim while clients validates the `azp` claim. The field is included in create, edit, JSON paste, and export flows.

### Backward Compatibility

When no external IdP is configured, the entire authentication flow remains unchanged — Cognito `USER_PASSWORD_AUTH` with `NEW_PASSWORD_REQUIRED` challenge handling, token refresh, and scope derivation from `cognito:groups`. The external IdP feature is purely additive.

---

## 15. Human-in-the-Loop (HITL) Approvals

### 15.1 SSE Event Handling

The `useInvoke` hook handles three HITL-related SSE event types:
- `approval_request` — Adds an `ApprovalRequestBubble` segment to the stream.
- `approval_resolved` — Triggers `flushTools()` (no separate bubble — status shown inline).
- `elicitation_request` — Adds an `ElicitationRequestBubble` segment to the stream.

The `StreamSegment` union type includes these variants with typed data payloads. Elicitation segments also carry an optional `resolvedSummary` field persisted when the user responds.

### 15.2 Approval Dialog (`ApprovalDialog.tsx`)

- `ApprovalRequestBubble`: Displays tool name, input summary, policy name, countdown timer, Approve/Reject buttons. Supports `resolved` prop for post-stream re-rendering.
- `notify_only` mode renders as an informational blue bubble without action buttons.
- Buttons are disabled after interaction to prevent double-submission.

### 15.3 Elicitation Dialog (`ElicitationDialog.tsx`)

- `ElicitationRequestBubble`: Renders dynamic forms from JSON Schema (text inputs, enum selectors, boolean yes/no).
- After submission, displays the actual response value (not generic "Response submitted").
- Accepts `resolvedSummary` prop for consistent display after stream completion.

### 15.4 HITL Segment Persistence

HITL segments are persisted in a `hitlSegmentsMap` ref (keyed by invocation ID) so they survive message re-fetches after stream completion. When messages are rendered from history, `hitlSegments` are passed to `MessageBubble` and displayed with `resolved={true}`.

### 15.5 Approval Policy Administration

The Security Admin page includes an "Approval Policies" section (`ApprovalPolicyPanel.tsx`) with:
- Card-based list of configured policies.
- Create/edit form with fields: name, type, tool pattern (glob), mode, timeout, agent filter.

### 15.6 Harness Human Confirmation

The Agent Registration Form includes a "Enable human confirmation (inline function HITL)" checkbox under Harness Parameters. When enabled:
- A customizable "Confirmation Policy" textarea defines when the agent should seek confirmation.
- The policy text becomes the `description` of the `user_confirmation` inline function tool deployed with the harness.
- The JSON config export/import includes `human_confirmation` and `confirmation_policy` fields.

---

## 16. On-Behalf-Of (OBO) Delegation UI

### 16.1 Delegation Mode Selector

MCP server and A2A agent forms include a "Delegation Mode" select within the OAuth2 authentication section:
- Options: **M2M** (client credentials, default) or **On-Behalf-Of** (RFC 8693 token exchange).
- Only visible when `auth_type` is "oauth2".
- Stored as `delegation_mode` field on the server/agent model.

### 16.2 Deploy Form Integration Badges

The agent registration form shows M2M/OBO badges next to each OAuth2 MCP server and A2A agent in the integration selection lists, so admins can see which delegation mode each integration uses at deploy time.

### 16.3 Invoke/Chat OBO Indicators

- **InvokePanel**: When the agent has OBO-configured integrations and a user token is available, displays a blue "User identity delegated" indicator. If the user is not authenticated, shows an amber "OBO requires authentication" warning.
- **ChatPage**: Same indicators rendered near the model/connector row above the message input.

### 16.4 Types

`delegation_mode?: "m2m" | "obo"` added to: `McpServer`, `McpServerCreateRequest`, `McpServerUpdateRequest`, `A2aAgent`, `A2aAgentCreateRequest`, `A2aAgentUpdateRequest`, and `ConnectorInfo`.

---

## 17. Alternate LLM Providers (LiteLLM Proxy)

Backend design (provider registry, virtual key vending, dynamic model catalog, IAM/IaC) is documented in [`backend/SPECIFICATIONS.md` § 16](../backend/SPECIFICATIONS.md#16-alternate-llm-providers-litellm-proxy); this section covers only the frontend surface.

### 17.1 Provider-Aware Deploy Form

`AgentRegistrationForm` adds a provider selector (fetched via `fetchProviders()` → `GET /api/agents/providers`), positioned alongside the Default Model field. Switching providers resets the model selection and any provider-specific credential fields.

- **Bedrock** (default): unchanged — model list from `fetchModels()`, no additional fields.
- **LiteLLM**: selecting it triggers a lazy, on-demand fetch of `fetchLitellmModels()` (`GET /api/agents/models/litellm`) rather than loading it eagerly alongside Bedrock's list on page mount, since the LiteLLM catalog reflects exactly what's deployed on the connected proxy and may not be configured at all. The same lazy fetch is triggered when importing/editing a manifest whose `provider` is `litellm`, so the model dropdown has options to match against.
- A provider whose registry entry has `harness_supported: false` forces the Deployment Type radio back to "Custom Agent" if "Managed Agent" was selected — failing fast in the UI rather than letting the backend reject an unsupported combination after deploy.
- **JSON import/export**: accepts both a flat `provider` string (legacy manifests / backend `GET /api/agents/{id}/integration`-style export) and a nested `{id, base_url, api_key}` object, since the manifest format evolved during this feature. Exported manifests always use the flat string form going forward.

### 17.2 Provider-Aware Model Pickers (Invoke, Chat)

Because `GET /api/agents/models` only ever returns Bedrock models, any surface that resolves an agent's `allowed_model_ids` to display names must also merge in `fetchLitellmModels()` — otherwise a LiteLLM agent's allowed models fail to match and the picker either hides or falls back to showing raw IDs:

- **`InvokePanel`**: merges `fetchModels()` and `fetchLitellmModels()` (both fetched in parallel, each tolerant of failure) into a single `ModelOption[]` before filtering to the agent's `allowedModelIds`.
- **`ChatPage`**: same merge for the model picker in the input area footer. `availableModels` additionally synthesizes a fallback `{model_id, display_name: model_id}` entry for any `allowed_model_ids` value missing from the merged catalog — the invoke endpoint only ever validates against the agent's own `allowed_model_ids` (not the admin's global enabled-models allowlist), so a model that's invocable but temporarily absent from the catalog is still shown rather than silently hidden.
- **`groupModelsByProvider()`** (`lib/models.ts`): groups a `ModelOption[]` by `provider` field (Bedrock first, then LiteLLM, then alphabetically for any others), then applies the existing `groupModels()` vendor grouping within each provider group.

### 17.3 Settings Page LiteLLM Panel

The Settings page's "Enabled Models" section (§ 9) is split into a Bedrock block (always available, no connection toggle) and a LiteLLM block:

- **Enabled toggle**: mirrors the backend's `litellm_enabled` setting. Fields below are only shown when checked.
- **Agent Base URL** and **Discovery Base URL** inputs, each with inline helper text explaining the distinction (agent/harness runtime reachability vs. backend-only model discovery) — mirroring the backend's two-base-URL design.
- **Master key**: password-style input, write-only — never pre-filled from the server. A `has_master_key` boolean from `GET /api/settings/litellm-proxy` is used to show whether a key is already stored, without ever displaying it.
- **Model list**: the merged catalog (`allModels`) is split by `provider` into a Bedrock section and a LiteLLM section, each with its own per-vendor grouped checkboxes, an "All"/"None" quick-toggle per section, and a shared text filter (matches display name or model ID) that narrows both sections simultaneously.
- **Refresh button**: calls `POST /api/settings/litellm-proxy/refresh` and replaces `allModels`/`enabledModelIds` with the response — used to recover from a stale/empty LiteLLM catalog (e.g. fetched while the proxy was briefly unreachable) without waiting out the cache TTL.
- Saving the connection (`updateLitellmProxyConfig`) re-triggers the enabled-models fetch so the model list reflects the new connection immediately.

### 17.4 Types

`Provider` (`id`, `display_name`, `requires_api_key`, `requires_base_url`, `harness_supported`, `available`) added to `api/types.ts`. `ModelOption` gains an optional `provider` field. `AgentDeployRequest` and `AgentHarnessDeployRequest` gain optional `provider`, `base_url`, and `api_key` fields. `patchAgent()` accepts the same three fields for editing an existing agent's provider configuration.

---

## 18. Future Work

- **VPC network mode** support
- **Operate Tab** — aggregate dashboard with summary cards, per-agent latency charts
- **Real-time auto-refresh** of sessions and metrics
- **Log stream selection** and agent-level log viewer
- **Latency charts** using Recharts
- **OAuth2 user-side connector auth flow** for MCP connectors requiring OAuth2 in the ChatPage
