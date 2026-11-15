"""Configuration loading and validation for the ADK agent.

Shares the exact ``AGENT_CONFIG_JSON``/``AGENT_CONFIG_PATH`` schema used by
``agents/strands_agent/src/config.py`` so the backend deploy pipeline needs
no framework-specific config-assembly logic.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuthConfig:
    """Authentication configuration for an integration."""

    type: str
    well_known_endpoint: str = ""
    credentials_secret_arn: str = ""
    credential_provider_name: str = ""
    scopes: str = ""
    api_key_header_name: str = "x-api-key"
    delegation_mode: str = "m2m"
    obo_grant_type: str = ""
    audience: str = ""


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server integration."""

    name: str
    enabled: bool = False
    transport: str = "streamable_http"
    endpoint_url: str = ""
    auth: Optional[AuthConfig] = None
    dynamic_only: bool = False


@dataclass
class A2AAgentConfig:
    """Configuration for an A2A agent integration."""

    name: str
    enabled: bool = False
    endpoint_url: str = ""
    auth: Optional[AuthConfig] = None


@dataclass
class MemoryResourceConfig:
    """Configuration for a single memory resource."""

    name: str
    memory_id: str
    arn: str = ""


@dataclass
class MemoryConfig:
    """Configuration for AgentCore Memory integration."""

    enabled: bool = False
    resources: list[MemoryResourceConfig] = field(default_factory=list)


@dataclass
class CodeInterpreterConfig:
    """Configuration for the Code Interpreter integration."""

    enabled: bool = False
    region: str = ""
    identifier: str = ""


@dataclass
class IntegrationsConfig:
    """Configuration for all integrations."""

    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
    a2a_agents: list[A2AAgentConfig] = field(default_factory=list)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    code_interpreter: CodeInterpreterConfig = field(default_factory=CodeInterpreterConfig)


@dataclass
class GuardrailRef:
    """A Bedrock guardrail an invocation may select (an ``allowed`` entry)."""

    guardrail_id: str
    guardrail_version: str
    guardrail_arn: str = ""


@dataclass
class GuardrailConfig:
    """Bedrock Guardrails configuration (the ``guardrail`` config key).

    ``mode`` is ``enforce`` (guardrail attached to every Bedrock model call)
    or ``monitor`` (``ApplyGuardrail`` on input and final output, log-only).
    ``stream_processing_mode`` and ``redact_history`` only apply to enforce.
    ``allowed`` lists alternate guardrails a single invocation may pick; the
    mode and other settings always come from this (primary) entry.
    """

    guardrail_id: str
    guardrail_version: str
    guardrail_arn: str = ""
    mode: str = "enforce"
    stream_processing_mode: str = "sync"
    redact_history: bool = True
    source: str = ""
    allowed: list[GuardrailRef] = field(default_factory=list)

    @property
    def identifier(self) -> str:
        """Identifier to send to Bedrock: the ARN when known, else the ID."""
        return self.guardrail_arn or self.guardrail_id


@dataclass
class AgentConfig:
    """Top-level agent configuration."""

    system_prompt: str
    model_id: str
    max_tokens: int = 4096
    provider: str = "bedrock"
    base_url: str = ""
    api_key_secret_arn: str = ""
    integrations: IntegrationsConfig = field(default_factory=IntegrationsConfig)
    guardrail: Optional[GuardrailConfig] = None


_GUARDRAIL_MODES = ("enforce", "monitor")
_GUARDRAIL_STREAM_MODES = ("sync", "async")


def _parse_guardrail(data: Optional[dict]) -> Optional[GuardrailConfig]:
    """Parse the optional ``guardrail`` block. Absent or null means no guardrail.

    A present-but-invalid block raises ``ValueError`` rather than being
    dropped, so a malformed config fails closed instead of silently running
    the agent without its guardrail.
    """
    if not data:
        return None
    if not isinstance(data, dict):
        raise ValueError("'guardrail' must be an object")
    guardrail_id = str(data.get("guardrail_id") or "").strip()
    if not guardrail_id:
        raise ValueError("'guardrail' must include 'guardrail_id'")
    mode = str(data.get("mode") or "enforce").lower()
    if mode not in _GUARDRAIL_MODES:
        raise ValueError(f"Unsupported guardrail mode: '{mode}'")
    stream_mode = str(data.get("stream_processing_mode") or "sync").lower()
    if stream_mode not in _GUARDRAIL_STREAM_MODES:
        raise ValueError(f"Unsupported guardrail stream_processing_mode: '{stream_mode}'")
    redact_history = data.get("redact_history")
    allowed = [
        GuardrailRef(
            guardrail_id=str(entry["guardrail_id"]),
            guardrail_version=str(entry.get("guardrail_version") or "DRAFT"),
            guardrail_arn=str(entry.get("guardrail_arn") or ""),
        )
        for entry in (data.get("allowed") or [])
        if isinstance(entry, dict) and entry.get("guardrail_id")
    ]
    return GuardrailConfig(
        guardrail_id=guardrail_id,
        guardrail_version=str(data.get("guardrail_version") or "DRAFT"),
        guardrail_arn=str(data.get("guardrail_arn") or ""),
        mode=mode,
        stream_processing_mode=stream_mode,
        redact_history=True if redact_history is None else bool(redact_history),
        source=str(data.get("source") or ""),
        allowed=allowed,
    )


def _parse_auth(data: Optional[dict]) -> Optional[AuthConfig]:
    """Parse auth configuration from a dictionary."""
    if data is None:
        return None
    return AuthConfig(
        type=data.get("type", ""),
        well_known_endpoint=data.get("well_known_endpoint", ""),
        credentials_secret_arn=data.get("credentials_secret_arn", ""),
        credential_provider_name=data.get("credential_provider_name", ""),
        scopes=data.get("scopes", ""),
        api_key_header_name=data.get("api_key_header_name", "x-api-key"),
        delegation_mode=(data.get("delegation_mode") or "m2m").lower(),
        obo_grant_type=data.get("obo_grant_type", ""),
        audience=data.get("audience", ""),
    )


def _parse_mcp_servers(data: list[dict]) -> list[MCPServerConfig]:
    """Parse MCP server configurations from a list of dictionaries."""
    servers = []
    for entry in data:
        servers.append(MCPServerConfig(
            name=entry["name"],
            enabled=entry.get("enabled", False),
            transport=entry.get("transport", "streamable_http"),
            endpoint_url=entry.get("endpoint_url", ""),
            auth=_parse_auth(entry.get("auth")),
            dynamic_only=entry.get("dynamic_only", False),
        ))
    return servers


def _parse_a2a_agents(data: list[dict]) -> list[A2AAgentConfig]:
    """Parse A2A agent configurations from a list of dictionaries."""
    agents = []
    for entry in data:
        agents.append(A2AAgentConfig(
            name=entry["name"],
            enabled=entry.get("enabled", False),
            endpoint_url=entry.get("endpoint_url", ""),
            auth=_parse_auth(entry.get("auth")),
        ))
    return agents


def _parse_integrations(data: Optional[dict]) -> IntegrationsConfig:
    """Parse integrations configuration from a dictionary."""
    if data is None:
        return IntegrationsConfig()
    ci_data = data.get("code_interpreter", {})
    return IntegrationsConfig(
        mcp_servers=_parse_mcp_servers(data.get("mcp_servers", [])),
        a2a_agents=_parse_a2a_agents(data.get("a2a_agents", [])),
        memory=MemoryConfig(
            enabled=data.get("memory", {}).get("enabled", False),
            resources=[
                MemoryResourceConfig(
                    name=r.get("name", ""),
                    memory_id=r.get("memory_id", ""),
                    arn=r.get("arn", ""),
                )
                for r in data.get("memory", {}).get("resources", [])
            ],
        ),
        code_interpreter=CodeInterpreterConfig(
            enabled=ci_data.get("enabled", False),
            region=ci_data.get("region", ""),
            identifier=ci_data.get("identifier", ""),
        ),
    )


def _parse_config(data: dict) -> AgentConfig:
    """Parse and validate a configuration dictionary into an AgentConfig.

    The system_prompt is resolved with the following precedence:
      1. AGENT_SYSTEM_PROMPT environment variable (highest — injected at deploy time)
      2. system_prompt field in the configuration data
    This allows the frontend to pass the user-configured prompt as a
    parameter at deployment without modifying the static config file.
    """
    system_prompt = os.environ.get("AGENT_SYSTEM_PROMPT") or data.get("system_prompt")
    if not system_prompt:
        raise ValueError(
            "No system prompt configured. Set AGENT_SYSTEM_PROMPT env var "
            "or include 'system_prompt' in the configuration."
        )
    if "model_id" not in data:
        raise ValueError("Configuration must include 'model_id'")
    return AgentConfig(
        system_prompt=system_prompt,
        model_id=data["model_id"],
        max_tokens=data.get("max_tokens", 4096),
        provider=(data.get("provider") or "bedrock").lower(),
        base_url=data.get("base_url", ""),
        api_key_secret_arn=data.get("api_key_secret_arn", ""),
        integrations=_parse_integrations(data.get("integrations")),
        guardrail=_parse_guardrail(data.get("guardrail")),
    )


def load_config() -> AgentConfig:
    """Load agent configuration from environment variable or file.

    Checks AGENT_CONFIG_JSON first (inline JSON string), then
    AGENT_CONFIG_PATH (path to a JSON file). Raises ValueError
    if neither is set or if the configuration is invalid.
    """
    config_json = os.environ.get("AGENT_CONFIG_JSON")
    if config_json:
        data = json.loads(config_json)
        return _parse_config(data)

    config_path = os.environ.get("AGENT_CONFIG_PATH")
    if config_path:
        with open(config_path) as f:
            data = json.load(f)
        return _parse_config(data)

    raise ValueError(
        "No configuration found. Set AGENT_CONFIG_JSON or AGENT_CONFIG_PATH."
    )
