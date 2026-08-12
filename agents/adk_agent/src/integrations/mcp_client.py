"""Dynamic MCP tool client creation from agent configuration.

Ports the OAuth2/OBO token-exchange and API-key auth logic from
``agents/strands_agent/src/integrations/mcp_client.py`` verbatim (same token
cache, same JWT-claims decode, same AgentCore Identity API calls) but
reshapes the auth-injection point: Strands attaches an ``httpx.Auth``
subclass to a raw ``streamablehttp_client`` transport; ADK's ``McpToolset``
takes a ``header_provider`` callable (``ReadonlyContext -> dict[str, str]``)
that is invoked on every tool call and at session-creation time, which is
ADK's own first-class per-request dynamic-header mechanism.

Known parity gap: Strands' ``_install_logging_callback`` monkeypatches the
MCP client's background-thread session to capture out-of-band MCP
``logging/message`` notifications (used by some servers to push
``token_info`` when a result-embedded ``__TOKEN_INFO__`` marker isn't
suitable). ADK's ``MCPSessionManager`` doesn't expose the underlying
``ClientSession`` or a logging-callback hook, so that specific channel is not
wired here — only the result-embedded ``__TOKEN_INFO__`` marker path
(``extract_token_info_from_tool_result``) works for ADK-built agents. Servers
that only push token_info via MCP logging notifications (rather than
embedding it in the tool result) will not surface that data for ADK agents.
"""

import base64
import json as _json
import logging
import os
import threading
import time
from typing import Any, Awaitable, Optional

import boto3

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

from bedrock_agentcore.runtime.context import BedrockAgentCoreContext
from bedrock_agentcore.services.identity import IdentityClient

from src.config import MCPServerConfig

logger = logging.getLogger(__name__)


# Process-wide cache for downstream tokens, keyed by
# (credential_provider_name, oauth2_flow, workload_token_prefix).
_TOKEN_CACHE: dict[tuple[str, str, str], tuple[str, float]] = {}
_TOKEN_CACHE_LOCK = threading.Lock()
_TOKEN_EXPIRY_SKEW_SECS = 30

# User access token for OBO flows — set per invocation from the Lambda payload
_user_access_token: str | None = None
_user_access_token_lock = threading.Lock()


def set_user_access_token(token: str | None) -> None:
    """Set the user access token for OBO token exchange flows."""
    global _user_access_token
    with _user_access_token_lock:
        _user_access_token = token


def get_user_access_token() -> str | None:
    """Get the current user access token."""
    with _user_access_token_lock:
        return _user_access_token


# Token info events emitted when OBO tokens are acquired.
# The handler drains this list and yields events to the stream.
_token_info_events: list[dict[str, Any]] = []
_token_info_emitted: set[str] = set()
_token_info_lock = threading.Lock()


def drain_token_info_events() -> list[dict[str, Any]]:
    """Drain and return all pending token info events."""
    with _token_info_lock:
        events = _token_info_events.copy()
        _token_info_events.clear()
    return events


def reset_token_info_state() -> None:
    """Reset emission tracking for a new invocation."""
    with _token_info_lock:
        _token_info_emitted.clear()


_TOKEN_INFO_PREFIX = "__TOKEN_INFO__:"  # nosec B105 — protocol prefix string, not a password


def extract_token_info_from_tool_result(tool: BaseTool, result: dict[str, Any]) -> dict[str, Any]:
    """Strip ``__TOKEN_INFO__`` markers from an MCP tool result's content blocks.

    Ports Strands' ``TokenInfoHook._extract_token_info``; called from a
    ``BasePlugin.after_tool_callback`` in ``agent.py`` (ADK has no equivalent
    of Strands' ``AfterToolCallEvent`` hook registered per-tool, so this is a
    plain function the plugin calls for every tool result rather than a
    dedicated hook class).
    """
    if not result or "content" not in result:
        return result

    clean_content = []
    for block in result["content"]:
        text = block.get("text", "") if isinstance(block, dict) else ""
        if text.startswith(_TOKEN_INFO_PREFIX):
            try:
                payload = _json.loads(text[len(_TOKEN_INFO_PREFIX):])
                with _token_info_lock:
                    _token_info_events.append(payload)
                logger.info(
                    "Extracted token_info from tool result: type=%s provider=%s",
                    payload.get("token_type"),
                    payload.get("credential_provider"),
                )
            except Exception as e:
                logger.warning("Failed to parse __TOKEN_INFO__ block: %s", e)
        else:
            clean_content.append(block)

    if len(clean_content) != len(result["content"]):
        return {**result, "content": clean_content}
    return result


def _decode_jwt_claims(token: str) -> dict[str, Any] | None:
    """Decode JWT payload without verification (for inspection only)."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return _json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None


class _OAuth2TokenFetcher:
    """Fetches downstream OAuth2 access tokens via the AgentCore Identity
    service, shared by the MCP ``header_provider`` (this module) and the A2A
    ``httpx.Auth`` handler (``a2a_client.py``) — the token-fetch mechanics are
    identical for both; only the injection point (HTTP header vs httpx auth
    flow) differs by transport.

    On each call the fetcher:
      1. Uses the workload access token (resolved from
         ``BedrockAgentCoreContext``, a ContextVar set by the AgentCore
         Runtime request handler independent of any agent framework).
      2. Exchanges it for a downstream OAuth2 access token via the
         AgentCore ``get_resource_oauth2_token`` API.

    The delegation_mode determines the oauth2Flow parameter:
      - "m2m" → M2M (machine-to-machine)
      - "obo" → ON_BEHALF_OF_TOKEN_EXCHANGE (on-behalf-of user)
    """

    def __init__(
        self,
        credential_provider_name: str,
        scopes: list[str],
        delegation_mode: str = "m2m",
        obo_grant_type: str | None = None,
        audience: str = "",
    ) -> None:
        self._credential_provider_name = credential_provider_name
        self._scopes = scopes
        self._region = os.environ.get("AWS_REGION", "us-east-1")
        self._delegation_mode = (delegation_mode or "m2m").lower()
        self._oauth2_flow = "ON_BEHALF_OF_TOKEN_EXCHANGE" if self._delegation_mode == "obo" else "M2M"
        self._obo_grant_type = obo_grant_type
        self._audience = audience

    def fetch_bearer_token(self) -> Optional[str]:
        """Return a bearer token string for the current request, or None."""
        workload_token = BedrockAgentCoreContext.get_workload_access_token()
        if not workload_token:
            logger.warning(
                "No workload access token available for '%s'; sending unauthenticated",
                self._credential_provider_name,
            )
            return None
        logger.info(
            "Workload token for '%s': prefix=%s len=%d",
            self._credential_provider_name, workload_token[:50], len(workload_token),
        )

        token = self._fetch_resource_token(workload_token)
        if token:
            logger.debug(
                "Fetched OAuth2 token for credential provider '%s' (flow=%s)",
                self._credential_provider_name, self._oauth2_flow,
            )
            return token

        logger.warning(
            "No accessToken available for credential provider '%s' (flow=%s); sending unauthenticated",
            self._credential_provider_name, self._oauth2_flow,
        )
        return None

    def _emit_token_info(self, token: str) -> None:
        """Decode token claims and emit a token_info event (once per drain cycle)."""
        emit_key = self._credential_provider_name
        with _token_info_lock:
            if emit_key in _token_info_emitted:
                return
            _token_info_emitted.add(emit_key)

        claims = _decode_jwt_claims(token)
        if claims:
            event = {
                "token_type": "obo",
                "credential_provider": self._credential_provider_name,
                "flow": self._oauth2_flow,
                "claims": {
                    "iss": claims.get("iss"),
                    "sub": claims.get("sub"),
                    "aud": claims.get("aud"),
                    "azp": claims.get("azp"),
                    "appid": claims.get("appid"),
                    "cid": claims.get("cid"),
                    "scp": claims.get("scp"),
                    "roles": claims.get("roles"),
                    "act": claims.get("act"),
                    "exp": claims.get("exp"),
                    "iat": claims.get("iat"),
                },
            }
            with _token_info_lock:
                _token_info_events.append(event)

    def _fetch_resource_token(self, workload_token: str) -> Optional[str]:
        cache_key = (self._credential_provider_name, self._oauth2_flow, workload_token[:32])
        now = time.time()
        with _TOKEN_CACHE_LOCK:
            cached = _TOKEN_CACHE.get(cache_key)
            if cached and cached[1] > now + _TOKEN_EXPIRY_SKEW_SECS:
                self._emit_token_info(cached[0])
                return cached[0]

        try:
            identity_client = IdentityClient(self._region)

            token_kwargs: dict[str, Any] = {
                'workloadIdentityToken': workload_token,
                'resourceCredentialProviderName': self._credential_provider_name,
                'scopes': self._scopes,
                'oauth2Flow': self._oauth2_flow,
            }
            if self._obo_grant_type == "JWT_AUTHORIZATION_GRANT":
                token_kwargs['customParameters'] = {'requested_token_use': 'on_behalf_of'}
            if self._obo_grant_type == "TOKEN_EXCHANGE":
                if self._audience:
                    token_kwargs['audiences'] = [self._audience]
                token_kwargs['customParameters'] = {
                    'subject_token_type': 'urn:ietf:params:oauth:token-type:access_token',
                }
            resp = identity_client.dp_client.get_resource_oauth2_token(**token_kwargs)
            token = resp.get("accessToken")
            if not token:
                logger.warning(
                    "No accessToken returned for '%s' (flow=%s)",
                    self._credential_provider_name, self._oauth2_flow,
                )
                return None

            expires_in = int(resp.get("expiresIn") or 300)
            with _TOKEN_CACHE_LOCK:
                _TOKEN_CACHE[cache_key] = (token, now + expires_in)

            logger.info(
                "OAuth2 token acquired: credential_provider=%s flow=%s expires_in=%ds",
                self._credential_provider_name, self._oauth2_flow, expires_in,
            )

            self._emit_token_info(token)
            return token
        except Exception as e:
            logger.warning(
                "OAuth2 token exchange failed: credential_provider=%s flow=%s error=%s",
                self._credential_provider_name, self._oauth2_flow, e,
            )
            return None


class _OAuth2HeaderProvider(_OAuth2TokenFetcher):
    """``header_provider`` callable for ``McpToolset``/``McpTool`` that
    returns an ``Authorization: Bearer <token>`` header via
    ``_OAuth2TokenFetcher``.
    """

    def __call__(self, readonly_context: ReadonlyContext) -> dict[str, str]:
        token = self.fetch_bearer_token()
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}


class _ApiKeyHeaderProvider:
    """Injects an API key header on each request, for use as a
    ``McpToolset``/``McpTool`` ``header_provider``.

    The API key is resolved once from AWS Secrets Manager at initialization
    (not per-request) to avoid throttling.
    """

    def __init__(self, secret_name: str, header_name: str = "x-api-key") -> None:
        self._header_name = header_name
        self._api_key = self._resolve_key(secret_name)

    @staticmethod
    def _resolve_key(secret_name: str) -> str:
        region = os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("secretsmanager", region_name=region)
        resp = client.get_secret_value(SecretId=secret_name)
        return resp["SecretString"]

    def __call__(self, readonly_context: ReadonlyContext) -> dict[str, str]:
        if not self._api_key:
            logger.warning("No API key resolved; sending unauthenticated request")
            return {}
        if self._header_name.lower() == "authorization":
            return {"Authorization": f"Bearer {self._api_key}"}
        return {self._header_name: self._api_key}


def _build_header_provider(config: MCPServerConfig) -> Optional[Any]:
    """Build a ``header_provider`` callable for the given MCP server configuration.

    Returns None for unauthenticated servers (McpToolset accepts header_provider=None).
    """
    if config.auth and config.auth.type == "oauth2" and config.auth.credential_provider_name:
        scope_list = config.auth.scopes.split() if config.auth.scopes else []
        delegation_mode = (config.auth.delegation_mode or "m2m").lower()
        provider = _OAuth2HeaderProvider(
            credential_provider_name=config.auth.credential_provider_name,
            scopes=scope_list,
            delegation_mode=delegation_mode,
            obo_grant_type=config.auth.obo_grant_type or None,
            audience=config.auth.audience or "",
        )
        logger.info(
            "MCP server '%s' configured with OAuth2 auth (credential_provider=%s, scopes=%s, delegation_mode=%s, obo_grant_type=%s)",
            config.name,
            config.auth.credential_provider_name,
            scope_list,
            delegation_mode,
            config.auth.obo_grant_type,
        )
        return provider

    if config.auth and config.auth.type == "api_key" and config.auth.credentials_secret_arn:
        try:
            provider = _ApiKeyHeaderProvider(
                secret_name=config.auth.credentials_secret_arn,
                header_name=config.auth.api_key_header_name or "x-api-key",
            )
            logger.info(
                "MCP server '%s' configured with API key auth (secret=%s, header=%s)",
                config.name,
                config.auth.credentials_secret_arn,
                config.auth.api_key_header_name,
            )
            return provider
        except Exception as e:
            logger.warning(
                "Failed to resolve API key for server '%s': %s. Falling back to unauthenticated.",
                config.name,
                e,
            )

    return None


def build_toolset(server: MCPServerConfig) -> Optional[McpToolset]:
    """Build an ``McpToolset`` for a single enabled MCP server configuration.

    Only the ``streamable_http`` transport is supported (matching Strands);
    other transports log a warning and return None so the caller can skip
    this server gracefully.
    """
    if server.transport != "streamable_http":
        logger.warning(
            "Unsupported transport '%s' for MCP server '%s'; skipping",
            server.transport,
            server.name,
        )
        return None

    header_provider = _build_header_provider(server)
    connection_params = StreamableHTTPConnectionParams(url=server.endpoint_url)
    toolset = McpToolset(
        connection_params=connection_params,
        header_provider=header_provider,
    )
    logger.info("Built MCP toolset for server '%s'", server.name)
    return toolset


def build_toolsets(servers: list[MCPServerConfig]) -> list[McpToolset]:
    """Build toolsets for all enabled server configurations.

    Args:
        servers: List of MCP server configurations.

    Returns:
        List of McpToolset instances for enabled, supported-transport servers.
    """
    toolsets: list[McpToolset] = []
    for server in servers:
        if not server.enabled:
            logger.debug("Skipping disabled MCP server '%s'", server.name)
            continue
        toolset = build_toolset(server)
        if toolset is not None:
            toolsets.append(toolset)
    logger.info("Built %d MCP toolset(s)", len(toolsets))
    return toolsets


def has_oauth2_servers(servers: list[MCPServerConfig]) -> bool:
    """Check if any enabled MCP servers require OAuth2 authentication."""
    return any(
        s.enabled and s.auth and s.auth.type == "oauth2" and s.auth.credential_provider_name
        for s in servers
    )


def has_deferred_auth_servers(servers: list[MCPServerConfig]) -> bool:
    """Check if any enabled MCP servers require deferred auth (OAuth2 or API key)."""
    return any(
        s.enabled and s.auth and s.auth.type in ("oauth2", "api_key")
        for s in servers
    )
