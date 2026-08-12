"""A2A (Agent-to-Agent) client vending from agent configuration.

Ports the OAuth2 auth handling and AgentCore-hosted-agent quirks from
``agents/strands_agent/src/integrations/a2a_client.py``, but builds on ADK's
native ``RemoteA2aAgent`` (wrapped as an ``AgentTool``) rather than hand-
rolling JSON-RPC/SSE parsing against the remote agent's A2A endpoint.

This differs from the Strands port strategy used elsewhere in this package:
Strands' ``_AuthenticatedA2AAgent`` implements its own message-send/SSE
parsing directly against ``a2a-sdk``. The version of ``a2a-sdk`` pulled in by
``google-adk[a2a]`` (1.x) changed several of the types that logic depends on
from Pydantic models to protobuf-generated messages (e.g. ``AgentCard`` and
its ``url`` field moved to a repeated ``supported_interfaces[].url``), so a
line-for-line port would be reimplementing wire-protocol handling against an
unfamiliar SDK generation. ``RemoteA2aAgent`` already implements this against
the same a2a-sdk version, so it's used directly; this module's job is only to
resolve and fix up the ``AgentCard`` the same way Strands does before handing
it to ``RemoteA2aAgent``, and to provide the authenticated ``httpx.AsyncClient``
it uses for both the card fetch and message sends.
"""

import json as _json
import logging
import os
import re
from typing import Any, Optional

import httpx
from a2a.client.card_resolver import parse_agent_card
from a2a.types import AgentCard
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.base_tool import BaseTool

from src.config import A2AAgentConfig
from src.integrations.mcp_client import _OAuth2TokenFetcher

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 300


def _sanitize_agent_name(raw: str) -> str:
    """Sanitize a configured agent name into a valid Python identifier.

    Unlike Strands (which accepts arbitrary tool names), ADK requires every
    ``BaseAgent.name`` to be a valid Python identifier — Loom's own
    ``A2AAgentConfig.name`` has no such restriction (users can name an
    integration ``"my-agent"``), so names are sanitized here rather than at
    the config layer, keeping the config schema identical to Strands'.
    """
    sanitized = re.sub(r"[^0-9a-zA-Z_]", "_", raw)
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"a2a_{sanitized}"
    return sanitized


class _BearerAuth(httpx.Auth):
    """httpx.Auth that injects a Bearer token fetched via ``_OAuth2TokenFetcher``.

    Used as the ``auth`` on the shared ``httpx.AsyncClient`` passed to
    ``RemoteA2aAgent``, so both the agent-card fetch and every message-send
    request carry the same token — matching Strands' single authenticated
    client used for both purposes.
    """

    def __init__(self, fetcher: _OAuth2TokenFetcher) -> None:
        self._fetcher = fetcher

    def auth_flow(self, request: httpx.Request):
        token = self._fetcher.fetch_bearer_token()
        if token:
            request.headers["Authorization"] = f"Bearer {token}"
        yield request


async def _fetch_agent_card(
    endpoint_url: str, http_client: httpx.AsyncClient
) -> AgentCard:
    """Fetch and fix up a remote agent's card, matching Strands'
    ``_AuthenticatedA2AAgent.get_agent_card`` quirk handling:

    - Salesforce Einstein AI Agent endpoints expose their card at ``/v1/card``
      rather than the standard well-known path.
    - Older cards may omit ``defaultInputModes``/``defaultOutputModes`` or
      per-skill ``tags``, which current validation requires — backfilled here.
    - AgentCore-hosted agents report an internal URL (e.g.
      ``http://localhost:8081``) in their card that isn't reachable
      externally; the configured endpoint is substituted in for every
      transport binding. Non-AgentCore agents (e.g. Salesforce) keep their
      own advertised URL, since their RPC endpoint may differ from the base
      URL used to fetch the card.
    """
    base_url = endpoint_url.rstrip("/")
    is_salesforce = "salesforce.com/einstein/ai-agent" in base_url
    if is_salesforce:
        card_url = f"{base_url}/v1/card"
    else:
        card_url = f"{base_url}/{AGENT_CARD_WELL_KNOWN_PATH.lstrip('/')}"

    response = await http_client.get(card_url)
    response.raise_for_status()
    card_data: dict[str, Any] = response.json()

    logger.info("Fetched agent card JSON from %s: %s", card_url, _json.dumps(card_data, indent=2, default=str))

    card_data.setdefault("defaultInputModes", ["application/json"])
    card_data.setdefault("defaultOutputModes", ["application/json"])
    for skill in card_data.get("skills", []):
        skill.setdefault("tags", [])

    card = parse_agent_card(card_data)

    if not is_salesforce:
        external_url = endpoint_url.rstrip("/") + "/"
        for iface in card.supported_interfaces:
            logger.info(
                "Overriding agent card interface url '%s' -> '%s' (endpoint='%s')",
                iface.url, external_url, endpoint_url,
            )
            iface.url = external_url
    else:
        logger.info("Using agent card url(s) as-is (endpoint='%s')", endpoint_url)

    return card


async def _build_a2a_tool(config: A2AAgentConfig) -> BaseTool:
    """Build an ``AgentTool`` wrapping a ``RemoteA2aAgent`` for the given
    A2A agent configuration.

    Async because resolving the agent card requires an HTTP round trip
    (``_fetch_agent_card``); the result is a real, fixed-up ``AgentCard``
    object handed to ``RemoteA2aAgent`` directly, so it never performs its
    own (unauthenticated, unfixed) URL-based resolution — the same
    authenticated ``httpx.AsyncClient`` is then reused for message sends.
    """
    http_client: httpx.AsyncClient
    if config.auth and config.auth.type == "oauth2" and config.auth.credential_provider_name:
        scope_list = config.auth.scopes.split() if config.auth.scopes else []
        delegation_mode = (config.auth.delegation_mode or "m2m").lower()
        fetcher = _OAuth2TokenFetcher(
            credential_provider_name=config.auth.credential_provider_name,
            scopes=scope_list,
            delegation_mode=delegation_mode,
            obo_grant_type=config.auth.obo_grant_type or None,
            audience=config.auth.audience or "",
        )
        logger.info(
            "A2A agent '%s' configured with OAuth2 auth (credential_provider=%s, scopes=%s, delegation_mode=%s)",
            config.name, config.auth.credential_provider_name, scope_list, delegation_mode,
        )
        http_client = httpx.AsyncClient(auth=_BearerAuth(fetcher), timeout=_DEFAULT_TIMEOUT)
    else:
        http_client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)

    card = await _fetch_agent_card(config.endpoint_url, http_client)

    remote_agent = RemoteA2aAgent(
        name=_sanitize_agent_name(config.name),
        agent_card=card,
        httpx_client=http_client,
        timeout=_DEFAULT_TIMEOUT,
        description=card.description or f"Send a message to the '{config.name}' A2A agent.",
    )
    logger.info("Created A2A AgentTool for agent '%s' at %s", config.name, config.endpoint_url)
    return AgentTool(agent=remote_agent)


async def create_a2a_tools(agents: list[A2AAgentConfig]) -> list[BaseTool]:
    """Create AgentTool wrappers for all enabled agent configurations.

    Agents whose card can't be resolved (unreachable endpoint, auth
    failure) are skipped gracefully so the rest of the agent's tools still
    load, matching Strands' soft-fail behavior for unreachable integrations.

    Args:
        agents: List of A2A agent configurations.

    Returns:
        List of AgentTool instances, one per enabled, reachable agent.
    """
    tools: list[BaseTool] = []
    for agent_cfg in agents:
        if not agent_cfg.enabled:
            logger.debug("Skipping disabled A2A agent '%s'", agent_cfg.name)
            continue
        try:
            tools.append(await _build_a2a_tool(agent_cfg))
        except Exception as e:
            logger.warning(
                "Failed to build A2A tool for agent '%s': %s. Skipping this agent.",
                agent_cfg.name, e,
            )
    logger.info("Initialised %d A2A tool(s)", len(tools))
    return tools
