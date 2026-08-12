# Google ADK Agent for AgentCore Runtime

Pre-built agent code for deployment on Amazon Bedrock AgentCore Runtime, powered by Google's Agent Development Kit (ADK). This is an alternate custom-code framework to [`strands_agent`](../strands_agent/README.md) — selectable per agent via `agent_framework="adk"` at deploy time.

## Overview

This agent is configured entirely via environment variables and/or a JSON configuration file — no user-authored code is generated. The configuration schema, AgentCore Runtime entrypoint contract (streaming SSE event shapes), and telemetry span structure are kept identical to `strands_agent` so that the rest of Loom (backend, frontend, traces UI) behaves the same regardless of which framework an agent uses.

## Directory Structure

```
adk_agent/
├── etc/
│   ├── config.json         # Local development configuration
│   └── environment.sh      # Local env vars (gitignored)
├── src/
│   ├── __init__.py
│   ├── handler.py          # AgentCore Runtime entry point (BedrockAgentCoreApp)
│   ├── agent.py            # LlmAgent/Runner construction and model selection
│   ├── config.py           # Configuration loading and validation (identical schema to strands_agent)
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── mcp_client.py         # MCP tool client vending (McpToolset, OAuth2/OBO header providers)
│   │   ├── a2a_client.py         # A2A agent client vending (RemoteA2aAgent)
│   │   ├── memory.py             # AgentCore Memory plugin (MemoryPlugin)
│   │   ├── approval.py           # HITL/approval policy translation layer
│   │   └── code_interpreter.py   # AgentCore Code Interpreter tool wrapper
│   └── telemetry.py        # OTEL instrumentation (TelemetryPlugin)
├── tests/
├── makefile
├── requirements.txt
└── README.md
```

## Configuration

Configuration is identical to `strands_agent` — see [`agents/strands_agent/README.md`](../strands_agent/README.md#configuration) for the full schema and environment variable reference. The agent reads configuration from `AGENT_CONFIG_JSON` (inline) or `AGENT_CONFIG_PATH` (file), and the system prompt resolves from `AGENT_SYSTEM_PROMPT` (highest priority) or the config file's `system_prompt` field.

## Development

### Setup

```bash
make install
```

### Run Locally

```bash
source etc/environment.sh
make run
```

### Run Tests

```bash
make test
```

### Build Deployment Artifact

```bash
make build
```

Produces `build/agent.zip` — a self-contained zip deployable to AgentCore Runtime.

## Integrations

### Model Providers

`build_model()` in `src/agent.py` dispatches on `provider`. Bedrock (default) uses `LiteLlm(model="bedrock/{model_id}")` with IAM credentials (no API key). `openai`, `anthropic`, and `litellm` resolve an API key once via `src/integrations/secrets.py::resolve_secret()` and construct the corresponding LiteLLM model string (`anthropic/{model_id}`, `openai/{model_id}`, or `litellm_proxy/{model_id}` with `use_litellm_proxy=True`). ADK has no native Bedrock model class, so all providers route through LiteLLM.

### MCP Tool Servers

MCP servers are loaded via `McpToolset` (`src/integrations/mcp_client.py`), resolved eagerly to concrete tools at agent build time (rather than passed as a lazy toolset) so that approval policies can be attached per tool. OAuth2/OBO and API-key auth are injected via a `header_provider` callable (ADK's per-request auth hook), reusing the same token-exchange logic as `strands_agent`.

**Known parity gap:** `strands_agent`'s MCP `logging/message` notification-based token info extraction has no ADK equivalent (`McpToolset` does not expose the underlying `ClientSession`). Only the result-embedded `__TOKEN_INFO__` marker path works for ADK agents.

### A2A Agent Clients

A2A agents are wrapped using ADK's native `RemoteA2aAgent` + `AgentTool` (`src/integrations/a2a_client.py`), rather than porting `strands_agent`'s raw JSON-RPC/SSE client. This avoids a hard version conflict between the a2a-sdk release Strands pins and the one `google-adk[a2a]` resolves. OAuth2-protected endpoints use an `httpx.Auth` bearer-token handler; Agent Cards are pre-fetched and their URLs corrected (AgentCore-hosted agents report unreachable internal URLs) before being handed to `RemoteA2aAgent`.

### AgentCore Memory

`MemoryPlugin` (`src/integrations/memory.py`) is a `BasePlugin` registered on the `Runner` (ADK plugins are Runner-level, not agent-level). It preserves the same `LOOM_MEMORY_TELEMETRY: retrievals=N, events_sent=M` structured log line used by the backend for cost tracking.

### Code Interpreter

`src/integrations/code_interpreter.py` is a lean, ADK-native wrapper built directly on `bedrock_agentcore.tools.code_interpreter_client.CodeInterpreter`, avoiding a dependency on the Strands-coupled `strands-agents-tools` package. Exposes the same six tools as `strands_agent` (execute_code, execute_command, write_files, read_files, list_files, remove_files).

### Human-in-the-Loop / Approval Policies

ADK's HITL primitive (`ToolContext.request_confirmation()` + a `require_confirmation` predicate) is structurally different from Strands' dynamic `event.interrupt()`. `src/integrations/approval.py` translates Loom's existing approval-policy configuration into ADK's model:

- For tools built by this package, a per-tool-name predicate closure is attached via `FunctionTool(func, require_confirmation=predicate)`.
- For framework-generated tools (MCP), `apply_confirmation_to_tools()` monkey-patches `check_require_confirmation` directly onto each resolved tool instance, since MCP tool names aren't known until the remote server is queried.

Approval decisions resume via a synthetic `adk_request_confirmation` FunctionCall in session history, translated in `handler.py` to/from Loom's existing `interruptResponse` wire contract — callers see no difference from `strands_agent`.

**Known parity gap:** MCP elicitation (Strands' `ctx.elicit()` / `{"elicitation": ...}` event) and the `{"token_info": ...}` OBO-token-metadata event are not wired for the WebSocket (`ws_invoke`) path — a tool requiring approval over WebSocket surfaces an error directing the client to fall back to the HTTP `interruptResponse` flow.

### Observability (OTEL)

`TelemetryPlugin` (`src/telemetry.py`) is a `BasePlugin` producing the same span hierarchy as `strands_agent`'s `TelemetryHook`: `agent.invocation` (root, per request) with `tool.call` and `model.call` child spans. ADK splits success/error into separate callback pairs (`after_*_callback` / `on_*_error_callback`), both of which close the same pending span so the resulting span shape matches Strands' output exactly.
