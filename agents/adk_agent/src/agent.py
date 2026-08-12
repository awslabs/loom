"""ADK Agent initialization and configuration.

Ports ``agents/strands_agent/src/agent.py``'s ``_build_model``/``build_agent``
onto ADK's ``LlmAgent``/``Runner`` model. The biggest structural difference
from Strands: ADK's telemetry/memory/approval integrations are ``BasePlugin``
instances attached to the ``Runner`` (not the agent itself — ADK has no
per-agent hooks list), so ``build_agent`` returns the plugin list alongside
the agent rather than baking hooks into construction.
"""

import logging
import os
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.models.lite_llm import LiteLlm
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool

from src.config import AgentConfig
from src.integrations.a2a_client import create_a2a_tools
from src.integrations.approval import ApprovalPolicyMatcher, apply_confirmation_to_tools
from src.integrations.code_interpreter import AgentCoreCodeInterpreterTools, build_code_interpreter_tools
from src.integrations.mcp_client import build_toolsets
from src.integrations.memory import MemoryPlugin
from src.integrations.secrets import resolve_secret
from src.telemetry import TelemetryPlugin

logger = logging.getLogger(__name__)


def build_model(config: AgentConfig) -> str | BaseLlm:
    """Instantiate the ADK model selected by ``config.provider``.

    Supports ``bedrock`` (default, IAM-authenticated via LiteLLM's own
    boto3-based credential resolution — no API key needed, same as Strands'
    IAM-native ``BedrockModel``), ``openai``, ``anthropic``, and ``litellm``.
    The latter three require an API key, resolved once from Secrets Manager
    via ``config.api_key_secret_arn``. ADK has no native non-Gemini model
    classes, so every non-Gemini provider (including the ``bedrock`` default)
    routes through ``LiteLlm``.
    """
    provider = config.provider or "bedrock"

    if provider == "bedrock":
        region = os.environ.get("AWS_REGION", "us-east-1")
        return LiteLlm(model=f"bedrock/{config.model_id}", aws_region_name=region)

    if provider not in ("openai", "anthropic", "litellm"):
        raise ValueError(f"Unsupported model provider: '{provider}'")

    if not config.api_key_secret_arn:
        raise ValueError(f"Provider '{provider}' requires 'api_key_secret_arn' to be configured")
    api_key = resolve_secret(config.api_key_secret_arn)

    # Without an explicit timeout, a network path that accepts the TCP
    # connection but never responds (misconfigured security group/NACL,
    # unreachable ALB target, wrong port) hangs indefinitely instead of
    # raising. Bound it so a bad connection fails fast with a loggable
    # exception — same rationale as Strands' LOOM_MODEL_REQUEST_TIMEOUT_SECONDS.
    request_timeout = float(os.environ.get("LOOM_MODEL_REQUEST_TIMEOUT_SECONDS", "30"))

    client_args: dict[str, Any] = {"api_key": api_key, "timeout": request_timeout}
    if config.base_url:
        client_args["base_url"] = config.base_url

    if provider == "anthropic":
        return LiteLlm(model=f"anthropic/{config.model_id}", **client_args)

    model_prefix = provider  # "openai" or "litellm"
    if provider == "litellm":
        # Without this, a bare model_id is routed by litellm's own provider
        # auto-detection straight at the real upstream provider instead of
        # through our proxy's base_url — using the proxy's virtual key as if
        # it were a real provider key. Forces the "litellm_proxy/" prefix so
        # the call actually goes through the configured proxy.
        # See https://github.com/BerriAI/litellm/issues/13454.
        model_prefix = "litellm_proxy"
        client_args["use_litellm_proxy"] = True
        logger.info(
            "LiteLLM client configured: base_url=%s use_litellm_proxy=%s timeout=%s api_key_len=%d",
            config.base_url or "<unset>",
            client_args["use_litellm_proxy"],
            request_timeout,
            len(api_key or ""),
        )

    return LiteLlm(model=f"{model_prefix}/{config.model_id}", **client_args)


async def build_agent(
    config: AgentConfig,
) -> tuple[LlmAgent, list[BasePlugin], Optional[AgentCoreCodeInterpreterTools]]:
    """Build an ADK LlmAgent from the provided configuration.

    Async because MCP toolset and A2A agent-card resolution require network
    I/O at build time (unlike Strands, where ``MCPClient``/``A2AAgent``
    construction is itself synchronous and connection happens lazily).

    Returns:
        A tuple of (agent, plugins, code_interpreter_tools). ``plugins``
        must be passed to the ``Runner`` that executes this agent — ADK has
        no per-agent hooks list, so telemetry/memory/approval integrations
        live at the Runner level rather than baked into the agent itself.
        ``code_interpreter_tools`` is returned separately (rather than only
        living inside the tool closures) so the caller can trigger a
        background pre-warm of the sandbox session.
    """
    model = build_model(config)
    logger.info("Initialized model for provider=%s model_id=%s", config.provider, config.model_id)

    tools: list[BaseTool] = []
    ci_tools: Optional[AgentCoreCodeInterpreterTools] = None

    # MCP toolsets — resolved to concrete tools at build time (rather than
    # passed as lazy BaseToolset instances) so approval predicates can be
    # attached per-tool below; this mirrors Strands' own eager
    # build_mcp_clients, which likewise returns concrete client/tool objects
    # rather than a lazy toolset abstraction.
    enabled_mcp_servers = [s for s in config.integrations.mcp_servers if s.enabled]
    if enabled_mcp_servers:
        toolsets = build_toolsets(enabled_mcp_servers)
        mcp_tool_count = 0
        for toolset in toolsets:
            try:
                mcp_tools = await toolset.get_tools()
                tools.extend(mcp_tools)
                mcp_tool_count += len(mcp_tools)
            except Exception as e:
                logger.warning("Failed to load tools from an MCP toolset: %s. Skipping this server.", e)
        logger.info("Loaded %d MCP tool(s) from %d server(s)", mcp_tool_count, len(toolsets))

    # A2A agent tools
    enabled_a2a_agents = [a for a in config.integrations.a2a_agents if a.enabled]
    if enabled_a2a_agents:
        a2a_tools = await create_a2a_tools(enabled_a2a_agents)
        if a2a_tools:
            tools.extend(a2a_tools)
            logger.info("Loaded %d A2A tool(s)", len(a2a_tools))

    # Code Interpreter tools
    if config.integrations.code_interpreter.enabled:
        ci_function_tools, ci_tools = build_code_interpreter_tools(config.integrations.code_interpreter)
        tools.extend(ci_function_tools)
        logger.info(
            "Loaded %d Code Interpreter tool(s) (region=%s)",
            len(ci_function_tools), config.integrations.code_interpreter.region or "default",
        )

    # Approval predicates — applied per-tool after construction since
    # McpToolset-generated tools' names aren't known until the server is
    # queried. FunctionTool-based tools (code interpreter) could take a
    # require_confirmation callable at construction time instead, but
    # patching uniformly after the fact keeps one code path for all tool
    # kinds and matches how MCP-sourced tools must be handled anyway.
    approval_matcher = ApprovalPolicyMatcher()
    if approval_matcher.policies:
        apply_confirmation_to_tools(tools, approval_matcher)
        logger.info("Enabled approval predicates for %d tool(s) with %d static policy(ies)", len(tools), len(approval_matcher.policies))

    plugins: list[BasePlugin] = [TelemetryPlugin()]
    logger.info("Enabled telemetry plugin")

    if config.integrations.memory.enabled:
        memory_store_id = None
        if config.integrations.memory.resources:
            memory_store_id = config.integrations.memory.resources[0].memory_id
        plugins.append(MemoryPlugin(memory_store_id=memory_store_id))
        logger.info("Enabled AgentCore Memory plugin (store_id=%s)", memory_store_id)

    agent = LlmAgent(
        name="loom_agent",
        model=model,
        instruction=config.system_prompt,
        tools=tools,
    )
    logger.info("Agent initialized with %d tool(s) and %d plugin(s)", len(tools), len(plugins))
    return agent, plugins, ci_tools
