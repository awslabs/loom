"""MCP server connection and tool discovery service."""
import json
import logging
import os
from typing import Any

import httpx

from app.services.secrets import get_secret

logger = logging.getLogger(__name__)

# Timeout for MCP server requests (seconds)
MCP_REQUEST_TIMEOUT = 30


def _get_oauth2_token(server: Any) -> str | None:
    """Exchange OAuth2 client credentials for an access token."""
    if server.auth_type != "oauth2" or not server.oauth2_client_id or not server.oauth2_client_secret:
        return None

    token_url = None

    # Discover token endpoint from well-known URL
    if server.oauth2_well_known_url:
        try:
            resp = httpx.get(server.oauth2_well_known_url, timeout=10)
            resp.raise_for_status()
            token_url = resp.json().get("token_endpoint")
        except Exception as e:
            logger.warning("Failed to discover token endpoint from %s: %s", server.oauth2_well_known_url, e)

    if not token_url:
        return None

    try:
        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": server.oauth2_client_id,
            "client_secret": server.oauth2_client_secret,
        }
        if server.oauth2_scopes:
            data["scope"] = server.oauth2_scopes
        resp = httpx.post(token_url, data=data, timeout=10)
        if resp.status_code == 400 and server.oauth2_scopes:
            # Retry without scopes — some providers reject unknown scope values
            logger.info("Token request with scopes failed, retrying without scopes")
            data.pop("scope", None)
            resp = httpx.post(token_url, data=data, timeout=10)
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as e:
        logger.warning("Failed to obtain OAuth2 token: %s", e)
        return None


def resolve_api_key(server: Any, user_sub: str | None = None) -> str | None:
    """Resolve API key from Secrets Manager. Admin key for admin context, user key for user context."""
    if getattr(server, "auth_type", None) != "api_key":
        return None
    region = os.getenv("AWS_REGION", "us-east-1")
    name = getattr(server, "name", "")
    if user_sub:
        try:
            return get_secret(f"loom/mcp/{name}/api-key/{user_sub}", region)
        except Exception:
            return None
    if getattr(server, "has_admin_api_key", None) == "true":
        try:
            return get_secret(f"loom/mcp/{name}/admin-api-key", region)
        except Exception:
            return None
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
        resp = httpx.get(server.oauth2_well_known_url, timeout=10)
        resp.raise_for_status()
        discovery = resp.json()
        token_url = discovery.get("token_endpoint")
    except Exception as e:
        logger.warning("Failed to discover token endpoint from %s: %s", server.oauth2_well_known_url, e)

    if not token_url:
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
            resp = httpx.post(token_url, data=data, timeout=10)
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

            resp = httpx.post(token_url, data=data, headers=basic_headers, timeout=10)
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
        resp = httpx.post(
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
        resp = httpx.post(
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
        resp = httpx.post(
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
