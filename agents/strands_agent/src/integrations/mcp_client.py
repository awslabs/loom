"""Dynamic MCP tool client creation from agent configuration."""

import base64
import json as _json
import logging
import os
import threading
import time
from functools import partial
from typing import Any, Generator, Optional

import boto3
import httpx
from mcp.client.streamable_http import streamablehttp_client
from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterToolCallEvent
from strands.tools.mcp import MCPClient

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


class TokenInfoHook(HookProvider):
    """Strands hook that extracts __TOKEN_INFO__ markers from MCP tool results.

    When an MCP server embeds token info in tool result content blocks
    (because server-initiated notifications can't traverse the AgentCore proxy),
    this hook strips those blocks from the result before the model sees them
    and pushes the data into the token_info event queue.
    """

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self._extract_token_info)

    def _extract_token_info(self, event: AfterToolCallEvent) -> None:
        result = event.result
        if not result or "content" not in result:
            return

        clean_content = []
        for block in result["content"]:
            text = block.get("text", "")
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
            event.result = {**result, "content": clean_content}


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


class _OAuth2Auth(httpx.Auth):
    """httpx Auth that injects a Bearer token from the AgentCore Identity service.

    On each outbound HTTP request the auth handler:
      1. Uses the workload access token (captured at construction time from
         ``BedrockAgentCoreContext`` or resolved lazily from the env/context).
      2. Exchanges it for a downstream OAuth2 access token via the
         AgentCore ``get_resource_oauth2_token`` API.
      3. Sets the ``Authorization: Bearer <token>`` header.

    The delegation_mode determines the oauth2Flow parameter:
      - "m2m" → M2M (machine-to-machine)
      - "obo" → USER_FEDERATION (on-behalf-of user)
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
        # Capture the workload token eagerly — auth_flow runs in the MCP
        # client's background thread where ContextVar is not propagated.
        self._workload_token = BedrockAgentCoreContext.get_workload_access_token()


    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        workload_token = self._workload_token or BedrockAgentCoreContext.get_workload_access_token()
        if not workload_token:
            logger.warning(
                "No workload access token available for '%s'; sending unauthenticated",
                self._credential_provider_name,
            )
            yield request
            return
        logger.info(
            "Workload token for '%s': prefix=%s len=%d",
            self._credential_provider_name, workload_token[:50], len(workload_token),
        )

        token = self._fetch_resource_token(workload_token)
        if token:
            request.headers["Authorization"] = f"Bearer {token}"
            logger.debug(
                "Injected OAuth2 token for credential provider '%s' (flow=%s)",
                self._credential_provider_name, self._oauth2_flow,
            )
        else:
            logger.warning(
                "No accessToken available for credential provider '%s' (flow=%s); sending unauthenticated",
                self._credential_provider_name, self._oauth2_flow,
            )

        yield request

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

            # Runtime automatically calls GetWorkloadAccessTokenForJWT when the
            # invocation includes a user Bearer token. The workload token we
            # receive already contains the user's identity — no need to call
            # get_workload_access_token_for_jwt ourselves.

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


class _ApiKeyAuth(httpx.Auth):
    """httpx Auth that injects an API key header on each request.

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

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        if self._api_key:
            if self._header_name.lower() == "authorization":
                request.headers["Authorization"] = f"Bearer {self._api_key}"
            else:
                request.headers[self._header_name] = self._api_key
        else:
            logger.warning("No API key resolved; sending unauthenticated request")
        yield request



def _build_transport_callable(config: MCPServerConfig) -> Any:
    """Build a transport callable for the given MCP server configuration.

    For OAuth2-authenticated servers, attaches an ``_OAuth2Auth`` handler
    that dynamically fetches tokens from the AgentCore Identity service
    on each request using the per-invocation workload access token.

    Args:
        config: MCP server configuration with endpoint and optional auth.

    Returns:
        A callable that returns an async context manager providing the MCP transport.
    """
    if config.auth and config.auth.type == "oauth2" and config.auth.credential_provider_name:
        scope_list = config.auth.scopes.split() if config.auth.scopes else []
        delegation_mode = (config.auth.delegation_mode or "m2m").lower()
        auth = _OAuth2Auth(
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
        return partial(streamablehttp_client, url=config.endpoint_url, auth=auth)

    if config.auth and config.auth.type == "api_key" and config.auth.credentials_secret_arn:
        try:
            auth = _ApiKeyAuth(
                secret_name=config.auth.credentials_secret_arn,
                header_name=config.auth.api_key_header_name or "x-api-key",
            )
            logger.info(
                "MCP server '%s' configured with API key auth (secret=%s, header=%s)",
                config.name,
                config.auth.credentials_secret_arn,
                config.auth.api_key_header_name,
            )
            return partial(streamablehttp_client, url=config.endpoint_url, auth=auth)
        except Exception as e:
            logger.warning(
                "Failed to resolve API key for server '%s': %s. Falling back to unauthenticated.",
                config.name,
                e,
            )

    return partial(streamablehttp_client, url=config.endpoint_url)


def _make_logging_callback():
    """Create an async logging callback that captures token_info notifications."""
    async def _logging_callback(params) -> None:
        logger.info(
            "MCP logging notification received: logger=%s level=%s data_type=%s",
            getattr(params, "logger", None),
            getattr(params, "level", None),
            type(getattr(params, "data", None)).__name__,
        )
        if getattr(params, "logger", None) == "token_info" and params.data:
            data = params.data
            if isinstance(data, dict) and "token_info" in data:
                with _token_info_lock:
                    _token_info_events.append(data["token_info"])
                logger.info(
                    "Captured token_info from MCP server: type=%s provider=%s",
                    data["token_info"].get("token_type"),
                    data["token_info"].get("credential_provider"),
                )
            else:
                logger.warning("token_info logger but unexpected data structure: %s", data)
    return _logging_callback


def _install_logging_callback(client: MCPClient) -> None:
    """Monkey-patch the MCP client session to capture logging notifications."""
    session = getattr(client, "_background_thread_session", None)
    if session is not None:
        session._logging_callback = _make_logging_callback()
        logger.info("Installed token_info logging callback on MCP session")
    else:
        logger.warning("Cannot install logging callback: no _background_thread_session found")


def _try_create_client(server: MCPServerConfig) -> MCPClient | None:
    """Attempt to create and validate an MCP client for a server.

    Returns the client if successful, or None if the server is unreachable
    or returns an auth error (e.g. 401/403).  Catches BaseException to
    handle ExceptionGroup raised by the MCP SDK background thread.
    """
    transport_callable = _build_transport_callable(server)
    client = MCPClient(transport_callable)

    # Temporarily suppress the strands MCP client logger during start()
    # to avoid noisy ERROR tracebacks for expected auth failures.
    strands_mcp_logger = logging.getLogger("strands.tools.mcp.mcp_client")
    prev_level = strands_mcp_logger.level
    strands_mcp_logger.setLevel(logging.CRITICAL)
    try:
        client.start()
        _install_logging_callback(client)
        logger.info("MCP client for server '%s' started successfully", server.name)
        return client
    except BaseException as e:
        logger.warning(
            "Failed to start MCP client for server '%s': %s. "
            "The agent will continue without this server's tools.",
            server.name,
            e,
        )
        try:
            client.stop()
        except BaseException:
            pass
        return None
    finally:
        strands_mcp_logger.setLevel(prev_level)


def create_mcp_clients(servers: list[MCPServerConfig]) -> list[MCPClient]:
    """Create MCP clients for all enabled server configurations.

    Must be called within an invocation context so that the workload
    access token is available for OAuth2-authenticated servers.

    Only servers with ``enabled=True`` are instantiated. Currently supports
    the ``streamable_http`` transport; other transports log a warning and
    are skipped. Servers that fail to connect (e.g. 401 Unauthorized) are
    skipped gracefully so the agent can still operate with its remaining tools.

    Args:
        servers: List of MCP server configurations.

    Returns:
        List of successfully initialised MCPClient instances.
    """
    clients: list[MCPClient] = []

    for server in servers:
        if not server.enabled:
            logger.debug("Skipping disabled MCP server '%s'", server.name)
            continue

        if server.transport == "streamable_http":
            client = _try_create_client(server)
            if client is not None:
                clients.append(client)
        else:
            logger.warning(
                "Unsupported transport '%s' for MCP server '%s'; skipping",
                server.transport,
                server.name,
            )

    logger.info("Initialised %d MCP client(s)", len(clients))
    return clients


def build_mcp_clients(servers: list[MCPServerConfig]) -> list[MCPClient]:
    """Build MCP clients without starting them.

    Used when clients will be registered via ``agent.tool_registry.process_tools``
    which handles starting internally.

    Args:
        servers: List of MCP server configurations.

    Returns:
        List of MCPClient instances (not yet started).
    """
    clients: list[MCPClient] = []

    for server in servers:
        if not server.enabled:
            logger.debug("Skipping disabled MCP server '%s'", server.name)
            continue

        if server.transport == "streamable_http":
            transport_callable = _build_transport_callable(server)
            client = MCPClient(transport_callable)
            clients.append(client)
            logger.info("Built MCP client for server '%s' (not yet started)", server.name)
        else:
            logger.warning(
                "Unsupported transport '%s' for MCP server '%s'; skipping",
                server.transport,
                server.name,
            )

    return clients


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
