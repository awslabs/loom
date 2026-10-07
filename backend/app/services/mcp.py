"""MCP server connection and tool discovery service."""
import json
import logging
import os
from typing import Any

from app.services.net_guard import (
    SSRFBlockedError,
    get_trusted_oauth_hosts,
    guarded_post,
    is_trusted_oauth_host,
    safe_get,
    safe_post,
)
from app.services.secrets import delete_secret, get_secret, store_secret

logger = logging.getLogger(__name__)

# Timeout for MCP server requests (seconds)
MCP_REQUEST_TIMEOUT = 30


def admin_api_key_secret_name(server_id: int) -> str:
    """Secrets Manager name for a server's admin API key.

    Keyed on the server id, which is server-assigned and immutable. It used to
    be keyed on `server.name` — a mutable display string with no uniqueness
    constraint — so renaming any row the caller owned onto another group's
    display name pointed this lookup at that group's secret, and
    `tools/invoke` then sent it to the caller's own `endpoint_url`.
    """
    return f"loom/mcp/{server_id}/admin-api-key"


def legacy_admin_api_key_secret_name(name: str) -> str:
    """The pre-migration, name-keyed location. Read-only, and only ever read
    through `_resolve_legacy_admin_api_key`, which refuses an ambiguous name."""
    return f"loom/mcp/{name}/admin-api-key"


def user_api_key_secret_name(server_name: str, user_sub: str) -> str:
    """Secrets Manager name for one user's personal API key for a server.

    Still keyed on the server name, deliberately: this path is embedded in
    `AGENT_CONFIG_JSON` at deploy time and read by the deployed agent itself,
    so re-keying it would strip per-user keys from every already-deployed
    agent until it was redeployed. It is safe to leave name-keyed because
    cross-group name collisions are now refused at the API boundary (see
    `_assert_name_available`), and because the trailing `user_sub` confines
    each entry to the one caller who owns it.
    """
    return f"loom/mcp/{server_name}/api-key/{user_sub}"


def _resolve_legacy_admin_api_key(server: Any, region: str, db: Any) -> str | None:
    """Read a pre-migration name-keyed admin key, then migrate it.

    Only safe while the name is unambiguous. A second row sharing the name is
    exactly how the rename attack aimed this lookup at another group's secret,
    so an ambiguous name refuses rather than guesses — denying a read is the
    right failure here. New collisions are refused at the API boundary, so in
    practice this guard only covers duplicates that predate that check.
    """
    from app.models.mcp import McpServer

    same_name = db.query(McpServer).filter(McpServer.name == server.name).count()
    if same_name > 1:
        logger.warning(
            "Refusing to read the legacy admin API key for MCP server %s: "
            "%d servers share the name %r, so the name does not identify one secret",
            server.id, same_name, server.name,
        )
        return None
    try:
        value = get_secret(legacy_admin_api_key_secret_name(server.name), region)
    except Exception:
        return None
    try:
        store_secret(
            admin_api_key_secret_name(server.id), value, region,
            description=f"Admin API key for MCP server {server.name}",
        )
        delete_secret(legacy_admin_api_key_secret_name(server.name), region)
        logger.info(
            "Migrated the admin API key for MCP server %s from its name-keyed "
            "location to %s", server.id, admin_api_key_secret_name(server.id),
        )
    except Exception as e:
        # The read succeeded, so serve it; migration retries on the next call.
        logger.warning("Failed to migrate the admin API key for MCP server %s: %s", server.id, e)
    return value


def _get_oauth2_token(server: Any) -> str | None:
    """Exchange OAuth2 client credentials for an access token."""
    if server.auth_type != "oauth2" or not server.oauth2_client_id or not server.oauth2_client_secret:
        return None

    token_url = None

    # Discover token endpoint from well-known URL
    if server.oauth2_well_known_url:
        try:
            resp = safe_get(server.oauth2_well_known_url, timeout=10)
            resp.raise_for_status()
            token_url = resp.json().get("token_endpoint")
        except SSRFBlockedError as e:
            logger.warning("Blocked well-known URL %s: %s", server.oauth2_well_known_url, e)
            return None
        except Exception as e:
            logger.warning("Failed to discover token endpoint from %s: %s", server.oauth2_well_known_url, e)

    if not token_url:
        return None

    if not is_trusted_oauth_host(token_url, get_trusted_oauth_hosts()):
        logger.warning(
            "Refusing to send OAuth2 client credentials to untrusted token endpoint %s "
            "(host is not a configured identity provider or authorizer)", token_url,
        )
        return None

    try:
        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": server.oauth2_client_id,
            "client_secret": server.oauth2_client_secret,
        }
        if server.oauth2_scopes:
            data["scope"] = server.oauth2_scopes
        resp = safe_post(token_url, data=data, timeout=10)
        if resp.status_code == 400 and server.oauth2_scopes:
            # Retry without scopes — some providers reject unknown scope values
            logger.info("Token request with scopes failed, retrying without scopes")
            data.pop("scope", None)
            resp = safe_post(token_url, data=data, timeout=10)
        resp.raise_for_status()
        return resp.json().get("access_token")
    except SSRFBlockedError as e:
        logger.warning("Blocked token endpoint %s: %s", token_url, e)
        return None
    except Exception as e:
        logger.warning("Failed to obtain OAuth2 token: %s", e)
        return None


def resolve_api_key(server: Any, user_sub: str | None = None, db: Any = None) -> str | None:
    """Resolve API key from Secrets Manager. Admin key for admin context, user key for user context.

    Pass `db` to allow the one-time read of a pre-migration, name-keyed admin
    key. Without it the legacy location is not consulted at all, so a caller
    that cannot prove the name is unambiguous gets nothing rather than
    possibly another group's secret.
    """
    if getattr(server, "auth_type", None) != "api_key":
        return None
    region = os.getenv("AWS_REGION", "us-east-1")
    name = getattr(server, "name", "")
    if user_sub:
        try:
            return get_secret(user_api_key_secret_name(name, user_sub), region)
        except Exception:
            return None
    if getattr(server, "has_admin_api_key", None) == "true":
        try:
            return get_secret(admin_api_key_secret_name(server.id), region)
        except Exception:
            pass
        if db is not None:
            return _resolve_legacy_admin_api_key(server, region, db)
    return None


def _get_obo_token(server: Any, user_token: str) -> str | None:
    """Exchange a user token for a downstream token via OBO.

    Entra ID uses grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer with
    requested_token_use=on_behalf_of. Okta/others use the standard RFC 8693
    token-exchange grant.
    """
    if not server.oauth2_well_known_url or not server.oauth2_client_id or not server.oauth2_client_secret:
        return None

    token_url = None
    discovery: dict = {}
    try:
        resp = safe_get(server.oauth2_well_known_url, timeout=10)
        resp.raise_for_status()
        discovery = resp.json()
        token_url = discovery.get("token_endpoint")
    except SSRFBlockedError as e:
        logger.warning("Blocked well-known URL %s: %s", server.oauth2_well_known_url, e)
        return None
    except Exception as e:
        logger.warning("Failed to discover token endpoint from %s: %s", server.oauth2_well_known_url, e)

    if not token_url:
        return None

    if not is_trusted_oauth_host(token_url, get_trusted_oauth_hosts()):
        # This is the critical check: OBO forwards the *caller's own real
        # access token* as subject_token/assertion below. Without this,
        # anyone who can set oauth2_well_known_url (mcp:write) could point a
        # server's discovery response at infrastructure they control and
        # have every invoking user's token delivered to it.
        logger.warning(
            "Refusing OBO token exchange with untrusted token endpoint %s "
            "(host is not a configured identity provider or authorizer) — "
            "the caller's access token was NOT forwarded", token_url,
        )
        return None

    is_entra = "login.microsoftonline.com" in server.oauth2_well_known_url

    # Decode subject token claims for debugging and audience extraction
    import base64
    _claims: dict = {}
    try:
        _payload = user_token.split(".")[1]
        _payload += "=" * (4 - len(_payload) % 4)
        _claims = json.loads(base64.urlsafe_b64decode(_payload))
        logger.info("Subject token claims: iss=%s, aud=%s, cid/azp=%s", _claims.get("iss"), _claims.get("aud"), _claims.get("cid") or _claims.get("azp"))
    except Exception:
        pass

    try:
        if is_entra:
            data: dict[str, str] = {
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": user_token,
                "client_id": server.oauth2_client_id,
                "client_secret": server.oauth2_client_secret,
                "requested_token_use": "on_behalf_of",
            }
            if server.oauth2_scopes:
                data["scope"] = server.oauth2_scopes
            resp = safe_post(token_url, data=data, timeout=10)
        else:
            # Okta RFC 8693 token exchange — use Basic Auth per Okta docs
            import base64 as _b64
            audience = server.oauth2_audience or _claims.get("aud", "")
            logger.info("Okta token exchange audience: %s", audience)
            oidc_scopes = {"openid", "profile", "email", "address", "phone", "offline_access"}
            exchange_scopes = " ".join(
                s for s in (server.oauth2_scopes or "").split()
                if s not in oidc_scopes
            )

            # Okta: actor identified by Basic Auth credentials
            basic_creds = _b64.b64encode(
                f"{server.oauth2_client_id}:{server.oauth2_client_secret}".encode()
            ).decode()
            basic_headers = {
                "Authorization": f"Basic {basic_creds}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }

            data = {
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": user_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": audience,
            }
            if exchange_scopes:
                data["scope"] = exchange_scopes

            resp = safe_post(token_url, data=data, headers=basic_headers, timeout=10)
        if resp.status_code != 200:
            logger.warning("OBO token exchange failed (HTTP %d): %s", resp.status_code, resp.text)
            return None
        access_token = resp.json().get("access_token")
        if access_token:
            import base64
            try:
                payload = access_token.split(".")[1]
                payload += "=" * (4 - len(payload) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload))
                logger.info("OBO token claims: %s", json.dumps({k: v for k, v in claims.items() if k not in ("nonce", "x5t", "xms_cc")}, indent=2))
            except Exception:
                pass
        return access_token
    except Exception as e:
        logger.warning("OBO token exchange error: %s", e)
        return None


def _build_headers(server: Any, api_key: str | None = None, user_token: str | None = None) -> dict[str, str]:
    """Build request headers, including auth if configured."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if server.auth_type == "oauth2":
        if getattr(server, "delegation_mode", "m2m") == "obo" and user_token:
            token = _get_obo_token(server, user_token)
        else:
            token = _get_oauth2_token(server)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif server.auth_type == "api_key" and api_key:
        header_name = getattr(server, "api_key_header_name", "x-api-key") or "x-api-key"
        if header_name.lower() == "authorization":
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers[header_name] = api_key
    return headers


def _jsonrpc_request(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 request."""
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "id": req_id,
    }
    if params:
        msg["params"] = params
    return msg


def _call_streamable_http(server: Any, method: str, params: dict | None = None, api_key: str | None = None, user_token: str | None = None) -> dict | None:
    """Call an MCP server using Streamable HTTP (POST JSON-RPC).

    Always initializes a session first (works for both stateless and stateful
    servers). Stateless servers accept initialize but don't return a session ID.
    Stateful servers require it and return a Mcp-Session-Id header.
    """
    headers = _build_headers(server, api_key, user_token=user_token)
    headers["Accept"] = "application/json, text/event-stream"

    try:
        # Initialize session (no-op for stateless servers, required for stateful)
        if method != "initialize":
            session_id = _initialize_session(server, headers)
            if session_id:
                headers["Mcp-Session-Id"] = session_id

        body = _jsonrpc_request(method, params)
        resp = guarded_post(
            server.endpoint_url,
            json=body,
            headers=headers,
            timeout=MCP_REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.error("Streamable HTTP call to %s failed (HTTP %d): %s", server.endpoint_url, resp.status_code, resp.text[:500])
            return None
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return _parse_sse_response(resp.text)
        else:
            return resp.json()
    except SSRFBlockedError as e:
        logger.warning("Blocked MCP endpoint %s: %s", server.endpoint_url, e)
        return None
    except Exception as e:
        logger.error("Streamable HTTP call to %s failed: %s", server.endpoint_url, e)
        return None


def _initialize_session(server: Any, headers: dict[str, str]) -> str | None:
    """Send MCP initialize and return the session ID if the server is stateful."""
    init_body = _jsonrpc_request("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "loom", "version": "1.0.0"},
    })

    try:
        resp = guarded_post(
            server.endpoint_url,
            json=init_body,
            headers=headers,
            timeout=MCP_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        session_id = resp.headers.get("mcp-session-id")
        if session_id:
            logger.debug("MCP session established: %s", session_id)
        return session_id
    except Exception:
        return None


def _call_sse(server: Any, method: str, params: dict | None = None, api_key: str | None = None, user_token: str | None = None) -> dict | None:
    """Call an MCP server using SSE transport.

    SSE transport: POST JSON-RPC to the endpoint, receive SSE stream back.
    Some SSE servers accept POST directly; others require establishing an SSE
    connection first. We try the POST approach which is the MCP standard.
    """
    headers = _build_headers(server, api_key, user_token=user_token)
    headers["Accept"] = "text/event-stream"
    body = _jsonrpc_request(method, params)

    try:
        resp = guarded_post(
            server.endpoint_url,
            json=body,
            headers=headers,
            timeout=MCP_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return _parse_sse_response(resp.text)
        else:
            return resp.json()
    except SSRFBlockedError as e:
        logger.warning("Blocked MCP endpoint %s: %s", server.endpoint_url, e)
        return None
    except Exception as e:
        logger.error("SSE call to %s failed: %s", server.endpoint_url, e)
        return None


def _parse_sse_response(text: str) -> dict | None:
    """Parse an SSE stream text and extract the JSON-RPC result."""
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())

    # Try each data line — the result is typically the last one
    for data_str in reversed(data_lines):
        if not data_str or data_str == "[DONE]":
            continue
        try:
            parsed = json.loads(data_str)
            if "result" in parsed or "error" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _call_mcp(server: Any, method: str, params: dict | None = None, api_key: str | None = None, user_token: str | None = None) -> dict | None:
    """Call an MCP server using the configured transport."""
    if server.transport_type == "streamable_http":
        return _call_streamable_http(server, method, params, api_key, user_token=user_token)
    else:
        return _call_sse(server, method, params, api_key, user_token=user_token)


def test_mcp_connection(server: Any, api_key: str | None = None, user_token: str | None = None) -> dict:
    """Test connectivity to an MCP server.

    Sends an `initialize` JSON-RPC request to verify the server is reachable
    and responds to the MCP protocol.
    """
    init_params = {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "loom", "version": "1.0.0"},
    }

    result = _call_mcp(server, "initialize", init_params, api_key, user_token=user_token)

    if result is None:
        return {"success": False, "message": f"Failed to connect to {server.endpoint_url}"}

    if "error" in result:
        error = result["error"]
        msg = error.get("message", "Unknown error") if isinstance(error, dict) else str(error)
        return {"success": False, "message": f"Server error: {msg}"}

    server_info = result.get("result", {}).get("serverInfo", {})
    server_name = server_info.get("name", "Unknown")
    server_version = server_info.get("version", "")
    version_str = f" v{server_version}" if server_version else ""
    return {"success": True, "message": f"Connected to {server_name}{version_str}"}


def fetch_mcp_tools(server: Any, api_key: str | None = None, user_token: str | None = None) -> list[dict]:
    """Fetch available tools from an MCP server via the tools/list method."""
    result = _call_mcp(server, "tools/list", api_key=api_key, user_token=user_token)

    if result is None:
        logger.warning("No response from %s for tools/list", server.endpoint_url)
        return []

    if "error" in result:
        error = result["error"]
        msg = error.get("message", "Unknown error") if isinstance(error, dict) else str(error)
        logger.warning("tools/list error from %s: %s", server.endpoint_url, msg)
        return []

    tools_data = result.get("result", {}).get("tools", [])
    tools: list[dict] = []
    for t in tools_data:
        tool: dict[str, Any] = {
            "name": t.get("name", ""),
            "description": t.get("description"),
        }
        if "inputSchema" in t:
            tool["input_schema"] = t["inputSchema"]
        tools.append(tool)

    logger.info("Discovered %d tools from %s", len(tools), server.endpoint_url)
    return tools


def invoke_mcp_tool(server: Any, tool_name: str, arguments: dict, api_key: str | None = None) -> dict:
    """Invoke a tool on an MCP server via the tools/call method.

    Returns a dict with 'success', 'result' (on success), and 'error' (on failure).
    The 'request' field always contains the sent arguments for display purposes.
    """
    params = {"name": tool_name, "arguments": arguments}
    result = _call_mcp(server, "tools/call", params, api_key)

    if result is None:
        return {
            "success": False,
            "request": params,
            "error": f"No response from {server.endpoint_url}",
        }

    if "error" in result:
        error = result["error"]
        msg = error.get("message", "Unknown error") if isinstance(error, dict) else str(error)
        return {
            "success": False,
            "request": params,
            "error": msg,
        }

    return {
        "success": True,
        "request": params,
        "result": result.get("result", {}),
    }
