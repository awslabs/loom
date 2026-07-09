"""Strands Agent initialization and configuration."""

import logging
from typing import Optional

from strands import Agent
from strands.models.bedrock import BedrockModel

from strands_tools.code_interpreter import AgentCoreCodeInterpreter

from src.config import AgentConfig, MCPServerConfig
from src.integrations.approval import ApprovalHook
from src.integrations.mcp_client import build_mcp_clients, create_mcp_clients, has_oauth2_servers, _install_logging_callback, TokenInfoHook
from src.integrations.a2a_client import create_a2a_clients
from src.integrations.memory import MemoryHook
from src.telemetry import TelemetryHook

logger = logging.getLogger(__name__)


def build_agent(config: AgentConfig, defer_mcp: bool = False) -> tuple[Agent, ApprovalHook, "AgentCoreCodeInterpreter | None"]:
    """Build a Strands Agent from the provided configuration.

    Initializes the Bedrock model, loads enabled integrations
    (MCP tools, memory hooks), and returns a configured Agent
    ready for invocation.

    Args:
        config: The agent configuration specifying model, system prompt,
                and integration settings.
        defer_mcp: If True, skip MCP client initialization.  Used when
                   OAuth2-authenticated MCP servers require a workload
                   access token that is only available during invocation.

    Returns:
        A configured Strands Agent instance.
    """
    model = BedrockModel(
        model_id=config.model_id,
        max_tokens=config.max_tokens,
        streaming=True,
    )
    logger.info("Initialized BedrockModel with model_id=%s", config.model_id)

    tools: list = []
    hooks: list = []
    ci: "AgentCoreCodeInterpreter | None" = None

    # MCP tool clients (R3) — may be deferred for authenticated servers
    if not defer_mcp and config.integrations.mcp_servers:
        enabled_servers = [s for s in config.integrations.mcp_servers if s.enabled]
        if enabled_servers:
            mcp_clients = build_mcp_clients(config.integrations.mcp_servers)
            tools.extend(mcp_clients)
            logger.info("Loaded %d MCP tool client(s)", len(mcp_clients))

    # A2A agent clients (R4 - scaffold)
    if config.integrations.a2a_agents:
        enabled_agents = [a for a in config.integrations.a2a_agents if a.enabled]
        if enabled_agents:
            a2a_clients = create_a2a_clients(config.integrations.a2a_agents)
            if a2a_clients:
                tools.extend(a2a_clients)
                logger.info("Loaded %d A2A client(s)", len(a2a_clients))

    # Code Interpreter tool
    if config.integrations.code_interpreter.enabled:
        ci_kwargs: dict = {}
        if config.integrations.code_interpreter.region:
            ci_kwargs["region"] = config.integrations.code_interpreter.region
        if config.integrations.code_interpreter.identifier:
            ci_kwargs["identifier"] = config.integrations.code_interpreter.identifier
        ci = AgentCoreCodeInterpreter(**ci_kwargs)
        tools.append(ci.code_interpreter)
        logger.info("Loaded Code Interpreter tool (region=%s)", ci_kwargs.get("region", "default"))

    # Approval hook (HITL Method 1) — policies injected at invocation time
    approval_hook = ApprovalHook(agent_tags=config.tags if hasattr(config, "tags") else None)
    hooks.append(approval_hook)
    if approval_hook.policies:
        logger.info("Enabled approval hook with %d static policy(ies)", len(approval_hook.policies))

    # Token info extraction hook — captures __TOKEN_INFO__ from MCP tool results
    hooks.append(TokenInfoHook())

    # Telemetry hook (R7)
    telemetry_hook = TelemetryHook()
    hooks.append(telemetry_hook)
    logger.info("Enabled telemetry hook")

    # Memory hooks (R8)
    if config.integrations.memory.enabled:
        memory_store_id = None
        if config.integrations.memory.resources:
            memory_store_id = config.integrations.memory.resources[0].memory_id
        memory_hook = MemoryHook(memory_store_id=memory_store_id)
        hooks.append(memory_hook)
        logger.info("Enabled AgentCore Memory hook (store_id=%s)", memory_store_id)

    try:
        agent = Agent(
            model=model,
            system_prompt=config.system_prompt,
            tools=tools,
            hooks=hooks,
        )
    except BaseException as e:
        if tools:
            logger.warning(
                "Agent init failed with %d tool(s): %s. Retrying without tools.",
                len(tools), e,
            )
            for tool in tools:
                if hasattr(tool, "stop"):
                    try:
                        tool.stop()
                    except BaseException:
                        pass
            agent = Agent(
                model=model,
                system_prompt=config.system_prompt,
                tools=[],
                hooks=hooks,
            )
        else:
            raise
    logger.info("Agent initialized with %d tool(s) and %d hook(s)", len(agent.tool_registry.registry), len(hooks))
    return agent, approval_hook, ci


def attach_mcp_tools(agent: Agent, servers: list[MCPServerConfig]) -> None:
    """Attach MCP tool clients to an already-initialized agent.

    Called during the first invocation when the workload access token
    is available in the request context. Servers that fail to connect
    (e.g. 401 Unauthorized) are skipped gracefully.

    Args:
        agent: The running Strands Agent instance.
        servers: MCP server configurations to connect.
    """
    mcp_clients = build_mcp_clients(servers)
    if not mcp_clients:
        logger.warning("build_mcp_clients returned 0 clients for %d server(s)", len(servers))
        return

    strands_mcp_logger = logging.getLogger("strands.tools.mcp.mcp_client")
    strands_registry_logger = logging.getLogger("strands.tools.registry")
    prev_mcp_level = strands_mcp_logger.level
    prev_registry_level = strands_registry_logger.level

    attached = 0
    for client in mcp_clients:
        strands_mcp_logger.setLevel(logging.CRITICAL)
        strands_registry_logger.setLevel(logging.CRITICAL)
        try:
            agent.tool_registry.process_tools([client])
            _install_logging_callback(client)
            attached += 1
        except BaseException as e:
            logger.warning(
                "Failed to attach MCP client: %s. The agent will continue without this server's tools.",
                e,
            )
            try:
                client.stop()
            except BaseException:
                pass
        finally:
            strands_mcp_logger.setLevel(prev_mcp_level)
            strands_registry_logger.setLevel(prev_registry_level)

    tool_names = list(agent.tool_registry.registry.keys())
    logger.info("Attached %d/%d MCP tool client(s) to agent. Registered tools: %s", attached, len(mcp_clients), tool_names)
