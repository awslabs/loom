# Loom Onboarding Guide

## Table of Contents

1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
   - [Accessing Loom](#accessing-loom)
   - [First-Time Login](#first-time-login)
   - [Understanding the Interface](#understanding-the-interface)
3. [Part 1: Admin Guide](#part-1-admin-guide)
   - [Super-Admin Setup](#super-admin-setup)
     - [Step 1: Set Up Tag Policies and Profiles](#step-1-set-up-tag-policies-and-profiles)
     - [Step 2: Configure Security](#step-2-configure-security)
   - [Demo-Admin Setup](#demo-admin-setup)
     - [Step 3: Register MCP Servers](#step-3-register-mcp-servers)
     - [Step 4: Register A2A Agents](#step-4-register-a2a-agents)
     - [Step 5: Create Memory Resources](#step-5-create-memory-resources)
     - [Step 6: Deploy an Agent](#step-6-deploy-an-agent)
     - [Step 7: Test the Agent](#step-7-test-the-agent)
     - [Step 8: Review Invocation Results](#step-8-review-invocation-results)
     - [Step 9: Monitor Costs](#step-9-monitor-costs)
     - [Step 10: Review Audit Logs](#step-10-review-audit-logs)
     - [Step 11: Adjust Settings](#step-11-adjust-settings)
4. [Part 2: Demo-User Guide](#part-2-demo-user-guide)
   - [Step 1: Log In and Explore the Chat Interface](#step-1-log-in-and-explore-the-chat-interface)
   - [Step 2: Select an Agent](#step-2-select-an-agent)
   - [Step 3: Start a Conversation](#step-3-start-a-conversation)
   - [Step 4: Manage Sessions](#step-4-manage-sessions)
   - [Step 5: View Memory Records](#step-5-view-memory-records)
5. [Appendix A: Roles and Permissions](#appendix-a-roles-and-permissions)
6. [Appendix B: Cost Estimation Reference](#appendix-b-cost-estimation-reference)
7. [Appendix C: Glossary](#appendix-c-glossary)

---

## Introduction

Loom is a management platform for deploying, invoking, and monitoring AI agents powered by Amazon Bedrock AgentCore. It provides administrators with tools to deploy agents, configure security, manage memory resources, set up integrations, and track costs. End users interact with deployed agents through a conversational chat interface.

This guide is divided into two parts:

- **Part 1: Demo-Admin Guide** walks through the full administrative workflow for setting up the platform and deploying agents, presented in the sequential order that makes sense for building up a working agent from scratch.
- **Part 2: Demo-User Guide** covers the end-user experience of interacting with deployed agents through the chat interface.

> **Tip: PASTE JSON Shortcut.** Each resource creation form in Loom supports a **Paste JSON** shortcut. Administrators who want to copy/paste configurations can paste a JSON object to auto-fill the form fields, which is useful for replicating configurations across environments or bulk-provisioning resources.

---

## Getting Started

### Accessing Loom

Loom is accessed through a web browser. Your administrator will provide you with the URL for your Loom deployment. Loom supports both light and dark themes and works best in modern browsers (Chrome, Firefox, Safari, Edge).

### First-Time Login

1. Navigate to the Loom URL in your browser. You will see the **Login Page** with fields for username and password.
2. Enter the credentials provided by your administrator.
3. After successful authentication, you will be redirected to the main application interface.

Your session is maintained via JWT tokens that automatically refresh in the background. If your session expires, you will be redirected to the login page.

### Understanding the Interface

After logging in, the interface you see depends on your user type:

- **Admin users (t-admin)** see a left sidebar with navigation to multiple administrative personas (sections). Each persona provides a different set of management tools.
- **End users (t-user)** see a streamlined chat interface designed for conversational interaction with agents. Each user only see agents that are tagged with the same group label.

**Admin Sidebar Elements:**

The left sidebar includes the following elements:

- **Persona navigation** with icons for each section (described below)
- **User information** displaying your username at the bottom
- **Theme picker** to switch between light and dark visual themes with multiple variants (base, subtle, muted, cool, warm)
- **Logout button** to end your session
- **View As selector** to impersonate other users and see the application from their perspective (super admins only)
- **Clock display** showing the current time in your selected timezone
- **Version number** of the application

**Admin Personas (Navigation Sections):**

| Persona | Description |
|---------|-------------|
| Catalog | Browse all registered agents, memories, MCP servers, and A2A agents |
| Agents | Deploy new agents or import existing ones |
| Memory | Create and manage memory resources |
| Security | Configure IAM roles and authorizers |
| MCP Servers | Register and manage Model Context Protocol servers |
| A2A Agents | Register and manage Agent-to-Agent integrations |
| Tagging | Define tag policies and create tag profiles for resource organization |
| Costs | View cost analytics and dashboards |
| Admin | View audit logs, session analytics, and usage tracking (super-admin only) |
| Settings | Configure application preferences |

---

## Part 1: Admin Guide

This section walks through the complete administrative workflow in a logical sequence. It is divided into two subsections:

- **Super-Admin Setup** (Steps 1–2): Foundational configuration for tagging and security. Demo-admins can skip this section entirely.
- **Demo-Admin Setup** (Steps 3–11): Registering integrations, creating memory, deploying agents, testing, and monitoring. This is where demo-admins begin.

---

### Super-Admin Setup

Steps 1–2 configure the foundational elements that all other resources depend on. These steps are performed by super-admins only.

> **Demo-admins:** Skip ahead to [Demo-Admin Setup](#demo-admin-setup). Steps 1–2 have already been completed for you. Use the pre-configured **demo** tag profile when creating resources.

---

### Step 1: Set Up Tag Policies and Profiles

Navigate to the **Tagging** persona by clicking the tag icon in the sidebar. Tagging is a prerequisite to creating any resources in Loom, because all resources require platform tags to be set.

#### 1.1 Understand Platform Tags

Loom comes with three built-in **platform tags** that are required on all resources:

| Tag Key | Purpose |
|---------|---------|
| `loom:application` | Identifies which application or project the resource belongs to |
| `loom:group` | Controls access: users can only see resources tagged with their group |
| `loom:owner` | Identifies who created or owns the resource |

These platform tags are locked and cannot be edited or deleted. They appear on every resource creation form as required fields.

#### 1.2 Create Custom Tags (Optional)

If you need additional categorization beyond the platform tags, you can create custom tags:

1. In the **Tags** section, click **Add Tag**.
2. Enter a **key** (for example, "environment", "team", "cost-center").
3. Optionally set a **default value** that will be pre-filled in forms.
4. Toggle **Show on Card** to control whether this tag is visible on resource cards in the catalog view.
5. Click **Save**.

Custom tags are optional on resources and can be edited or deleted at any time.

#### 1.3 Create Tag Profiles

Tag profiles are named presets of tag values that can be quickly applied when creating resources. This ensures consistency and saves time.

1. In the **Tag Profiles** section, click **Add Profile**.
2. Enter a **profile name** (for example, "Demo Team Production").
3. Fill in values for the required platform tags:
   - **loom:application**: Enter the application name (for example, "loom-demo").
   - **loom:group**: Enter the group name (for example, "demo"). This is critical because it determines which users can access resources created with this profile.
   - **loom:owner**: Enter the owner identifier.
4. Optionally check and fill in any custom tags you want to include.
5. Click **Save**.

Tag profiles are grouped by their `loom:group` value in the display, making it easy to see which profiles belong to which user groups. You can also import and export profiles in JSON format for bulk operations.

---

### Step 2: Configure Security

Navigate to the **Security** persona by clicking the shield icon in the left sidebar. The Security page has two tabs: **IAM Roles** and **Authorizers**.

#### 2.1 Import an IAM Role

Agents need an IAM execution role to interact with AWS services. Only importing existing roles is supported, as it is assumed that security administrators create IAM roles via an external process.

**To import an existing role:**

1. Click the **Add Role** button.
2. Enter the ARN of an existing IAM role that has a trust policy allowing Amazon Bedrock AgentCore to assume it.
3. Select a **Tag Profile** to apply the appropriate platform tags to the imported role.
4. Click **Save**. Loom will fetch the role details from AWS and store them locally.

The role will appear in the IAM Roles list with its ARN, description, and creation time.

#### 2.2 Set Up an Authorizer

If your agents will use OAuth2 or Cognito-based authentication (for example, to validate end-user tokens or to obtain machine-to-machine tokens for integrations), you need to configure an authorizer.

1. Click the **Authorizers** tab.
2. Click **Add Authorizer**.
3. Fill in the following fields:
   - **Name**: A descriptive name for this authorizer (for example, "Cognito Production Pool").
   - **Type**: Select "Cognito" for AWS Cognito User Pools, or "Other" for generic OIDC providers.
   - **Pool ID** (Cognito): The User Pool ID from your Cognito configuration.
   - **Discovery URL** (Other): The OIDC discovery endpoint URL.
   - **Client ID**: The application client ID.
   - **Client Secret**: The client secret (stored securely in AWS Secrets Manager).
   - **Allowed Clients**: A list of client IDs that are permitted to authenticate. Press **Enter** after typing each value to add it to the list.
   - **Allowed Scopes**: A list of OAuth2 scopes that should be accepted. Press **Enter** after typing each value to add it to the list.
4. Click **Save**.

#### 2.3 Add Authorizer Credentials (Machine-to-Machine)

For agents that need to call external APIs or services using OAuth2 client credentials, you can add M2M credentials to an authorizer.

1. Select an existing authorizer from the list.
2. In the credentials section, click **Add Credential**.
3. Provide a **label** (for example, "Backend Service Account"), a **client ID**, and the **client secret** (stored in Secrets Manager).
4. Click **Save**.

These credentials can later be selected when invoking an agent, allowing the agent to authenticate to external services on behalf of the system.

---

### Demo-Admin Setup

Steps 3–11 cover registering integrations, creating memory, deploying agents, testing, reviewing results, and monitoring costs. Demo-admins start here using the pre-configured **demo** tag profile.

---

### Step 3: Register MCP Servers

Navigate to the **MCP Servers** persona. Model Context Protocol (MCP) servers provide agents with access to external tools and data sources through a standardized protocol.

#### 3.1 Test Connectivity First

Before registering a new MCP server, verify that the endpoint is reachable:

1. Use the **Test Connection** feature to confirm that Loom can reach the MCP server endpoint and authenticate successfully.
2. This helps catch configuration issues before committing the registration.

#### 3.2 Add an MCP Server

1. Click the **Add Server** button.
2. Fill in the form:
   - **Name**: A descriptive name (for example, "Internal Knowledge Base MCP").
   - **Description**: What tools this server provides.
   - **Endpoint URL**: The URL where the MCP server is accessible.
   - **Transport Type**: Choose between:
     - **Streamable HTTP**: Modern bidirectional streaming transport (recommended).
     - **SSE (Server-Sent Events)**: Older unidirectional streaming transport.
   - **Authentication**: Choose:
     - **None**: No authentication required (suitable for internal/VPC endpoints).
     - **OAuth2**: Requires OAuth2 credentials. Configure the token endpoint, client ID, client secret, and scopes.
3. Click **Save**.

#### 3.3 Refresh and Review Tools

After adding an MCP server:

1. Click the **Tools** tab on the server card.
2. Click **Refresh Tools** to fetch the current tool list from the server.
3. Review the available tools, their descriptions, and input schemas.

Each tool shows its name, description, and the JSON schema for its expected input parameters.

#### 3.4 Configure Access Control

Access control is **disabled by default**, meaning all MCP tools are available to all agents. To restrict access:

1. Click the **Access Control** tab on the server card.
2. For each agent, choose:
   - **All Tools**: The agent can use all tools from this server.
   - **Selected Tools**: Choose specific tools the agent can use.
3. Save the access rules.

> **Auto-grant behavior:** When a new agent is deployed with an MCP server association and access control rules already exist for that server, the new agent is automatically granted "All Tools" access. If access control is disabled (no rules configured), all agents already have access by default.

---

### Step 4: Register A2A Agents

Navigate to the **A2A Agents** persona. Agent-to-Agent (A2A) integration allows your agents to communicate with and delegate tasks to other agents that implement the A2A protocol.

#### 4.1 Test Connectivity First

Before registering a new A2A agent, verify that the endpoint is reachable:

1. Use the **Test Connection** feature to confirm that Loom can reach the A2A agent endpoint and authenticate successfully.
2. This helps catch configuration issues before committing the registration.

#### 4.2 Add an A2A Agent

1. Click the **Add Agent** button.
2. Fill in the form:
   - **Name**: A descriptive name (for example, "Research Assistant Agent").
   - **Description**: What this agent does.
   - **Base URL**: The URL where the A2A agent is accessible.
   - **Agent Version**: The version of the A2A agent.
   - **Authentication**: Choose None or OAuth2 (similar to MCP servers).
   - **Provider Organization**: The organization that maintains this agent.
3. Click **Save**.

Loom will fetch the agent's **Agent Card** (a JSON document describing the agent's capabilities, skills, and supported input/output modes) from the base URL.

#### 4.3 Review Skills

After registration, click the server card to view the agent's skills. Each skill includes:
- Skill name and description
- Supported input and output modes
- Example interactions
- Tags for categorization

#### 4.4 Configure Access Control

Access control is **disabled by default**, meaning all A2A skills are available to all agents. To restrict access:

1. Click the **Access Control** tab.
2. Choose **All Skills** or **Selected Skills** for each agent.
3. Save the access rules.

> **Auto-grant behavior:** When a new agent is deployed with an A2A agent association and access control rules already exist for that A2A agent, the new agent is automatically granted "All Skills" access. If access control is disabled (no rules configured), all agents already have access by default.

---

### Step 5: Create Memory Resources

Navigate to the **Memory** persona by clicking the brain icon in the sidebar. Memory resources give agents the ability to remember information across conversations, building up knowledge about users and topics over time.

#### 5.1 Create a New Memory Resource

1. Click the **Add Memory** button.
2. Select **Create** mode to create a new memory resource in AWS.
3. Fill in the form:

   **Basic Information:**
   - **Name**: A descriptive name (for example, "Demo Agent Memory").
   - **Description**: What this memory will be used for.
   - **Event Expiry Duration**: How long raw events are retained (in ISO 8601 duration format, for example "P30D" for 30 days).
   - **Tag Profile**: Select a tag profile to apply the appropriate platform tags.

   **Strategies** (configure at the end of the form):

   Strategies control how memory is processed after events are stored. Each strategy type creates a separate namespace for records. You can enable multiple strategies on the same memory resource.

   | Strategy | Description | Namespace |
   |----------|-------------|-----------|
   | **summary** | Periodically summarizes events into concise records. Good for agents that need to recall key facts from conversations. | `/strategy/{strategyId}/actor/{actorId}/session/{sessionId}/` |
   | **user_preference** | Extracts explicit user preferences (likes, dislikes, timezone, formatting preferences) from conversations. Requires users to state preferences directly. | `/strategy/{strategyId}/actor/{actorId}/` |
   | **semantic** | Indexes events semantically for retrieval-augmented generation (RAG). Best for agents that need to search and retrieve relevant past interactions. | `/strategy/{strategyId}/actor/{actorId}/` |
   | **episodic** | Stores episodic memories of specific events and interactions. Useful for agents that need to recall detailed past experiences. | `/strategy/{strategyId}/actor/{actorId}/` |

4. Click **Create**.

The memory resource will show a **CREATING** status while it is being provisioned in AWS. Creation typically takes about **3 minutes**. The status automatically refreshes every 3 seconds. Once the status changes to **READY**, the memory is available for use.

#### 5.2 Import an Existing Memory Resource

If you have a memory resource that was created outside of Loom:

1. Click the **Add Memory** button.
2. Select **Import** mode.
3. Enter the **Memory ID** of the existing resource.
4. Click **Import**.

Loom will fetch the memory's metadata from AWS and register it locally.

---

### Step 6: Deploy an Agent

Navigate to the **Agents (Builder)** persona by clicking the robot icon in the sidebar. This is where you deploy new agents or import existing ones.

#### 6.1 Deploy a New Agent

1. Click the **Add Agent** button.
2. Select the **Deploy** tab.
3. Fill in the deployment form:

   **Basic Information:**
   - **Agent Name**: A unique name for your agent (for example, "demo-assistant"). This will be used in the agent's ARN and must follow AWS naming conventions.
   - **Description**: A clear description of what the agent does. This is visible in the catalog and helps users understand the agent's purpose.

   **Runtime Configuration:**
   - **Protocol**: The communication protocol (typically "HTTP").
   - **Network Mode**: How the agent is networked (typically "PUBLIC" for internet-accessible endpoints).

   **Model Selection:**
   - **Model ID**: Select the foundation model that powers the agent. Available models include:
     - Claude Opus, Sonnet, and Haiku variants (Anthropic)
     - Amazon Nova Pro, Lite, and Micro variants
   - Each model shows its input and output token pricing to help you make cost-informed decisions.

   **Associations:**
   - **Memory**: Select one or more memory resources to associate with the agent. This gives the agent access to persistent memory across sessions.
   - **MCP Servers**: Select MCP servers to give the agent access to external tools.
   - **A2A Agents**: Select A2A agents to enable agent-to-agent delegation.

   **Tag Profile:**
   - Select a tag profile to apply the appropriate platform and custom tags. The `loom:group` tag in the profile determines which users can see and interact with this agent.

4. Click **Deploy**.

The deployment process runs asynchronously in the background. The agent will initially show a **CREATING** status. Creation typically takes about **1 minute**. During deployment, Loom performs the following operations:

- Creates OAuth2 credential providers for any MCP or A2A integrations that require authentication
- Creates or attaches the IAM execution role
- Builds the agent artifact (code, configuration, and environment variables)
- Creates the runtime in Amazon Bedrock AgentCore
- Enables observability (usage logs and application logs)
- Stores any Cognito client credentials securely in AWS Secrets Manager

You can monitor the deployment status by watching the agent card. When the status changes to **READY**, the agent is deployed and available for invocation. If the deployment fails, the status will show **FAILED** with a failure reason.

#### 6.2 Import an Existing Agent

If you have an agent that was deployed outside of Loom:

1. Click the **Add Agent** button.
2. Select the **Import** tab.
3. Enter the **ARN** of the existing AgentCore agent.
4. Click **Import**.

Loom will fetch the agent's metadata from AWS and register it locally, making it available in the catalog.

---

### Step 7: Test the Agent

Once an agent is in **READY** status, you can test it from the admin interface.

#### 7.1 Navigate to the Agent Detail Page

1. Go to the **Catalog** persona.
2. Click on the agent card for the agent you want to test.
3. You will see the Agent Detail Page with the agent's description, session table, and invoke panel.

#### 7.2 Invoke the Agent

The invoke panel is located at the bottom of the Agent Detail Page (visible if you have the `invoke` scope).

1. **Write a prompt**: Type your message in the prompt textarea. Your prompt text is automatically saved to your browser's session storage, so it persists if you navigate away and come back.

2. **Select a qualifier** (optional): If the agent has multiple model configurations (qualifiers), select the one you want to use from the dropdown.

3. **Select a session**:
   - **New Session**: Creates a fresh conversation context with no prior history.
   - **Existing Session**: Select a previous session to continue an existing conversation. The agent will have access to the full conversation history from that session.

4. **Configure authentication** (if the agent uses an authorizer):
   - **Current User Token**: The preferred option. Uses your current login session token to authenticate with the agent.
   - **Preconfigured M2M Credential**: Select a pre-configured machine-to-machine credential from the dropdown.
   - **Manual Bearer Token**: Paste a bearer token directly for testing purposes.

5. Click **Invoke**.

The response streams in real-time using Server-Sent Events (SSE). You will see:
- A **session_start** event confirming the session ID
- **chunk** events as the agent generates its response, displayed character by character
- A **session_end** event when the agent finishes responding

After the invocation completes, a **Latency Summary** panel appears showing:
- Cold start latency (if the agent runtime needed to initialize)
- Client duration (total time from request to completion)

---

### Step 8: Review Invocation Results

After testing, you can drill down into the detailed results of each invocation.

#### 8.1 View Sessions

On the Agent Detail Page, the **Sessions Table** shows all sessions for this agent:

| Column | Description |
|--------|-------------|
| Invoked By | The user who initiated the session |
| Qualifier | The model configuration used |
| Status | Active or completed |
| Invocations | Number of times the agent was invoked in this session |
| Created | When the session was started |

Click on a session row to navigate to the Session Detail Page.

#### 8.2 Session Detail Page

The Session Detail Page shows summary metrics at the top and the invocation table below.

**Session Summary:**

| Metric | Description |
|--------|-------------|
| Status | Active or completed |
| Cold Start | Cold start latency in milliseconds |
| Duration | Total client-side duration |
| Tokens | Total input + output tokens |
| Model Cost | Token-based cost |
| Runtime Cost | AgentCore Runtime compute cost |
| Memory Cost | STM + LTM operation cost |
| Total Cost | Sum of all cost categories |
| Created | When the session was started |

**Invocation Table:**

| Column | Description |
|--------|-------------|
| Invocation ID | Unique identifier for this specific invocation |
| Request ID | AWS request ID for tracing |
| Status | Pending, streaming, complete, or error |
| Cold Start | Cold start latency in milliseconds |
| Duration | Total client-side duration |
| Cost | Estimated cost for this invocation |

Click on an invocation row to see the full details.

#### 8.3 Invocation Detail Page

The Invocation Detail Page provides a complete breakdown:

**Request Details:**
- Request ID and status
- Cold start latency and client duration
- The full prompt text (rendered as Markdown)

**Response:**
- The full response text (rendered as Markdown with collapsible JSON blocks for structured data)

**Cost Breakdown:**

| Cost Category | Description |
|---------------|-------------|
| Model Cost | Token-based cost: (input tokens x input price) + (output tokens x output price) |
| Compute CPU | CPU time cost: duration x vCPU x price per vCPU-hour (with I/O wait discount applied) |
| Compute Memory | Memory cost: duration x GB x price per GB-hour |
| STM Cost | Short-term memory: event count x $0.25 per 1,000 events |
| LTM Cost | Long-term memory: retrieval count x $0.50 per 1,000 retrievals |
| Total | Sum of all cost categories |

#### 8.4 View Logs

On the Session Detail Page, click the **Logs** tab to access CloudWatch logs:

1. Select a **log stream** from the dropdown (runtime logs or OpenTelemetry logs).
2. Toggle **timestamps** on or off to show or hide log entry timestamps.
3. Toggle **line numbers** on or off.
4. Structured JSON log entries are displayed in **collapsible blocks** that you can expand to see the full JSON payload.

Logs are invaluable for debugging agent behavior, understanding tool use decisions, and tracing the flow of execution.

#### 8.5 View Traces

On the Session Detail Page, click the **Traces** tab to view OpenTelemetry distributed traces:

1. The **Trace List** shows all traces for the session with their duration and status.
2. Click on a trace to see the **Trace Graph**, a directed acyclic graph (DAG) visualization of spans showing the execution flow.
3. Click on individual spans in the graph to expand their details, including attributes, timing, and status.

Traces help you understand the sequence and timing of operations within an agent invocation, including model calls, tool executions, and memory operations.

---

### Step 9: Monitor Costs

Navigate to the **Costs** persona to view cost analytics across all agents.

#### 9.1 Cost Dashboard Overview

The Cost Dashboard provides three views of cost data:

**Time Range Filter:** Select a time window at the top:
- **7 days**: Last week of activity
- **30 days**: Last month of activity
- **Custom**: Specify a custom date range

**Summary Metrics** at the top show:
- Total estimated cost across all agents
- Total model tokens consumed
- Total AgentCore Runtime costs
- Total AgentCore Memory costs

#### 9.2 Estimated Costs Table

This table shows estimated costs aggregated by agent:

| Column | Description |
|--------|-------------|
| Agent Name | The agent's display name |
| Model | The foundation model used |
| Invocations | Total invocation count |
| Model Tokens | Total input + output tokens |
| AgentCore Runtime Costs | CPU + memory compute cost |
| AgentCore Memory Costs | STM + LTM operation cost |
| Per Invoke Costs | Average cost per invocation |
| Total Costs | Sum of all costs |

Click the expand arrow on any row to see a per-memory cost breakdown for that agent.

#### 9.3 Actual Costs Table

This table shows costs derived from AWS CloudWatch metrics. Click the **Pull Actuals** button to fetch the latest usage data from AWS.

| Column | Description |
|--------|-------------|
| Agent Name | The agent's display name |
| Sessions | Number of active sessions |
| CPU Cost | Actual CPU utilization cost |
| Memory Cost | Actual memory utilization cost |
| Total | Sum of actual costs |

#### 9.4 Memory Cost Breakdown

A dedicated table shows costs across all memory resources:

| Column | Description |
|--------|-------------|
| Memory Name | The memory resource name |
| Log Events | Number of events logged |
| Retrievals | Number of memory retrievals |
| Stored Records | Number of persistent records |
| Extractions | Number of extraction operations |
| Consolidations | Number of consolidation operations |
| Total | Total memory cost |

#### 9.5 Understanding Cost Adjustments

Loom applies a **CPU I/O Wait Discount** to compute costs. Since agents spend a significant portion of their CPU time waiting for I/O (model inference responses, API calls), the full CPU cost overstates actual utilization. The default discount is 75%, meaning only 25% of the raw CPU cost is counted. This discount is configurable in Settings.

---

### Step 10: Review Audit Logs

Navigate to the **Admin** persona (available to super admins only) to review system-wide audit logs and usage analytics.

#### 10.1 Audit Summary

The top of the Admin Dashboard shows a chart summarizing actions by user and day over the selected time range. Use the time range filter (Today, 7 days, 30 days, All) to adjust the view.

#### 10.2 Sessions Table

The Sessions table shows all user login sessions:

| Column | Description |
|--------|-------------|
| User | The username |
| Browser Session | Unique browser session identifier |
| Login Time | When the user logged in |
| Logout Time | When the session ended |
| Page Views | Number of pages visited during the session |

Click on a session row to expand the **Session Timeline**, which shows a chronological list of:
- **Page views**: Which personas the user visited, how long they spent on each, and when they left
- **Actions**: What operations the user performed (create, delete, invoke, etc.), on which resources, and when

#### 10.3 Actions Table

The Actions table provides a filterable, sortable list of all user actions:

| Column | Description |
|--------|-------------|
| Time | When the action was performed |
| User | Who performed the action |
| Category | The resource category (agent, memory, security, etc.) |
| Action | The specific action type (create, delete, invoke, refresh, etc.) |
| Resource | The name of the affected resource |

Use the dropdown filters for User, Category, and Action Type to narrow down results. This is useful for investigating who made changes, when, and to which resources.

#### 10.4 Page Views Table

The Page Views table tracks navigation patterns:

| Column | Description |
|--------|-------------|
| User | The username |
| Persona | Which section they visited |
| Entry Time | When they navigated to the page |
| Duration | How long they spent |
| Exit Time | When they left |

Filter by User or Persona to understand how different users engage with the platform.

---

### Step 11: Adjust Settings

Navigate to the **Settings** persona to configure application preferences.

#### 11.1 Timezone

Select your preferred timezone for all timestamp displays:
- **Local**: Uses your browser's local timezone
- **UTC**: Uses Coordinated Universal Time

This setting affects all timestamps throughout the application, including session times, invocation times, log timestamps, and audit entries.

#### 11.2 CPU I/O Wait Discount

Configure the percentage discount applied to CPU costs to account for I/O wait time:
- **Range**: 0% to 99%
- **Default**: 75%
- **Effect**: A 75% discount means only 25% of the raw CPU cost is counted in cost calculations

Adjust this value based on your agents' actual CPU utilization patterns. Agents that perform more computation (data processing, code generation) may warrant a lower discount, while agents that primarily wait for model responses may warrant a higher discount.

This setting is saved as a site-wide configuration and affects all cost displays for all users.

---

## Part 2: Demo-User Guide

This section covers the end-user experience. As an end user, you interact with deployed agents through a conversational chat interface. Your administrator has already set up the agents, memory, and security configuration described in Part 1.

---

### Step 1: Log In and Explore the Chat Interface

1. Navigate to the Loom URL and log in with your credentials (see [First-Time Login](#first-time-login) for details).
2. After logging in, you will see the **Chat Interface**. This interface is designed to be simple and intuitive, similar to other conversational AI applications.

The chat interface has three main areas:

- **Left Panel: Agent Navigation** - Lists the available agent names in the left navigation sidebar, filtered by your group membership. Click an agent name to select it.
- **Center Panel: Chat Window** - The main conversation area where you type messages and see agent responses. The selected agent's name and description are displayed at the top of the chat window.
- **Right Panel: Sessions and Memory** - Shows your conversation sessions and any memory records the agent has built about your interactions.

At the bottom of the sidebar, you will find:
- **Theme picker** to toggle between light and dark themes
- **Logout button** to end your session

---

### Step 2: Select an Agent

1. In the left panel, browse the list of available agent names. You will only see agents that have been tagged with your user group by the administrator.
2. Click on an agent name to select it. The chat window in the center panel will update to show the agent's **name and description** at the top, followed by the conversation interface.

If you do not see any agents, contact your administrator to verify that agents have been deployed and tagged with your user group.

---

### Step 3: Start a Conversation

1. With an agent selected, type your message in the **input textarea** at the bottom of the chat window.
2. Click the **Send** button (or press the appropriate keyboard shortcut) to send your message.
3. The agent will begin responding. Responses stream in real-time, so you will see text appearing as the agent generates it.
4. Once the response is complete, you can continue the conversation by typing another message. The agent maintains context from previous messages in the same session.

**Tips for effective conversations:**
- Be specific in your requests to get the most relevant responses.
- If the agent has memory enabled, it will remember key information from your conversations over time, so you do not need to repeat context in future sessions.
- Each conversation creates a **session**. You can start new sessions for different topics or continue existing ones.

---

### Step 4: Manage Sessions

Your conversation sessions are listed in the right panel under **Sessions**.

- **View previous sessions**: Click on any previous session to load its conversation history.
- **Start a new session**: Click the new session button to start a fresh conversation with no prior context.
- **Continue a session**: Click on an existing session and type a new message to continue where you left off.

Sessions are private to you. Other users cannot see your conversation history. You can hide sessions you no longer need by using the delete/hide option, which removes them from your list without permanently deleting the data (only completed sessions can be hidden).

---

### Step 5: View Memory Records

If the agent has memory enabled, you can view what the agent has learned about you:

1. In the right panel, click on the **Memory** section.
2. You will see a list of memory resources associated with the selected agent.
3. Expand a memory resource to view the **memory records** (facts and information) that the agent has extracted from your conversations.
4. Memory records are displayed as collapsible JSON blocks that you can expand to see the full content.

Memory records are **scoped to you** as a user. The agent builds a separate memory profile for each user, so information from your conversations is not shared with other users.

Memory helps the agent provide more personalized and contextually relevant responses over time. For example, if you tell the agent about your role or preferences in one session, it can recall that information in future sessions without you needing to repeat it.

---

## Appendix A: Roles and Permissions

Loom uses a group-based permission model managed through AWS Cognito. Users are assigned to groups that determine their access level.

### User Type Groups

| Group | Interface | Description |
|-------|-----------|-------------|
| t-admin | Admin UI | Full administrative interface with all personas |
| t-user | Chat UI | Streamlined conversational interface |

### Admin Groups

| Group | Access Level |
|-------|-------------|
| g-admins-super | Full access to all features and all resources |
| g-admins-demo | Admin access scoped to demo resources (includes MCP and A2A read/write) |
| g-admins-security | Security management only (IAM roles, authorizers) |
| g-admins-memory | Memory resource management only |
| g-admins-mcp | MCP server management only |
| g-admins-a2a | A2A agent management only |

### User Groups

| Group | Access Level |
|-------|-------------|
| g-users-demo | Can interact with agents tagged with loom:group=demo |
| g-users-test | Can interact with agents tagged with loom:group=test |
| g-users-strategics | Can interact with agents tagged with loom:group=strategics |

### Scope Reference

Scopes are automatically derived from group membership. Each scope has read and write variants:

| Scope | Grants Access To |
|-------|-----------------|
| catalog:read/write | Viewing and managing the resource catalog |
| agent:read/write | Viewing and deploying agents |
| memory:read/write | Viewing and managing memory resources |
| security:read/write | Viewing and managing IAM roles and authorizers |
| mcp:read/write | Viewing and managing MCP servers |
| a2a:read/write | Viewing and managing A2A agents |
| tagging:read/write | Viewing and managing tag policies and profiles |
| costs:read/write | Viewing cost dashboards |
| settings:read/write | Viewing and modifying application settings |
| admin:read/write | Viewing audit logs and analytics |
| invoke | Invoking agents (sending prompts and receiving responses) |

---

## Appendix B: Cost Estimation Reference

Loom tracks and estimates costs at multiple levels. All cost figures displayed in the UI are prefixed with "~" to indicate they are estimates.

### Model Costs

Model costs are based on token usage and vary by model:

| Model | Input Cost (per 1K tokens) | Output Cost (per 1K tokens) |
|-------|---------------------------|----------------------------|
| Claude Opus | Highest tier | Highest tier |
| Claude Sonnet | Mid tier | Mid tier |
| Claude Haiku | Lowest Anthropic tier | Lowest Anthropic tier |
| Amazon Nova Pro | Mid tier | Mid tier |
| Amazon Nova Lite | Low tier | Low tier |
| Amazon Nova Micro | Lowest tier | Lowest tier |

Exact pricing is displayed in the model selection dropdown when deploying an agent.

### Compute Costs

| Resource | Rate |
|----------|------|
| CPU | $0.0895 per vCPU-hour (before I/O wait discount) |
| Memory | $0.00945 per GB-hour |

Default allocation: 1 vCPU, 0.5 GB memory per agent runtime.

### Memory Operation Costs

| Operation | Rate |
|-----------|------|
| Short-Term Memory (STM) Events | $0.25 per 1,000 events |
| Long-Term Memory (LTM) Retrievals | $0.50 per 1,000 retrievals |

### Idle Costs

When an agent session is active but not processing invocations, memory costs continue to accrue at the standard memory rate. CPU costs do not accrue during idle time. Idle time is capped at the configured idle timeout (default: 900 seconds / 15 minutes).

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Agent** | An AI-powered runtime deployed on Amazon Bedrock AgentCore that can process natural language prompts and generate responses. Agents can use tools, access memory, and integrate with external services. |
| **AgentCore** | Amazon Bedrock AgentCore, the AWS service that hosts and manages agent runtimes. |
| **A2A (Agent-to-Agent)** | A protocol that allows agents to communicate with and delegate tasks to other agents. |
| **Authorizer** | A configuration that defines how authentication tokens are validated, typically using AWS Cognito or OIDC providers. |
| **Catalog** | The browsable collection of all registered agents, memory resources, MCP servers, and A2A agents. |
| **Cold Start** | The initial startup time when an agent runtime needs to initialize before processing its first request. Subsequent requests in the same session do not incur cold start latency. |
| **Credential Provider** | An OAuth2 credential configuration that allows an agent to obtain access tokens for external services. |
| **Invocation** | A single request-response cycle with an agent: one prompt in, one response out. |
| **M2M (Machine-to-Machine)** | Authentication between services (not involving a human user), typically using OAuth2 client credentials. |
| **MCP (Model Context Protocol)** | A standardized protocol for connecting AI models to external tools and data sources. MCP servers expose tools that agents can call. |
| **Memory** | A persistent storage resource that allows agents to remember information across conversation sessions. Memory can log events, summarize information, or consolidate knowledge over time. |
| **Persona** | A navigation section in the admin interface, each focused on a specific area of functionality (for example, Catalog, Agents, Memory, Security). |
| **Qualifier** | A named configuration variant for an agent, allowing different model or parameter settings under the same agent deployment. |
| **Session** | A conversation context between a user and an agent. Sessions maintain message history and can span multiple invocations. |
| **SSE (Server-Sent Events)** | A web technology for streaming data from server to client. Used by Loom to stream agent responses in real-time. |
| **Tag Policy** | A rule that defines a tag key, its default value, whether it is required, and whether it appears on resource cards. |
| **Tag Profile** | A named preset of tag key-value pairs that can be applied to resources during creation for consistent tagging. |
| **Token** | A unit of text processing for language models. Roughly corresponds to 3-4 characters of English text. Costs are calculated based on the number of input tokens (prompt) and output tokens (response). |
