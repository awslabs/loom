"""A2A agent service layer for Agent Card fetching and connection testing."""
import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

A2A_REQUEST_TIMEOUT = 30

# Standard A2A well-known path
AGENT_JSON_PATH = "/.well-known/agent.json"
# AgentCore Runtime uses a different well-known path
AGENT_CARD_JSON_PATH = "/.well-known/agent-card.json"


def _is_agentcore_url(base_url: str) -> bool:
    """Detect if the base URL points to an AgentCore Runtime endpoint."""
    return "bedrock-agentcore" in base_url


def _is_salesforce_url(base_url: str) -> bool:
    """Detect if the base URL points to a Salesforce Agentforce endpoint."""
    return "salesforce.com/einstein/ai-agent" in base_url


def _get_oauth2_token(agent: Any) -> str | None:
    """Exchange OAuth2 client credentials for an access token."""
    if agent.auth_type != "oauth2" or not agent.oauth2_client_id or not agent.oauth2_client_secret:
        return None

    token_url = None

    if agent.oauth2_well_known_url:
        try:
            resp = httpx.get(agent.oauth2_well_known_url, timeout=10)
            resp.raise_for_status()
            token_url = resp.json().get("token_endpoint")
        except Exception as e:
            logger.warning("Failed to discover token endpoint from %s: %s", agent.oauth2_well_known_url, e)

    if not token_url:
        return None

    try:
        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": agent.oauth2_client_id,
            "client_secret": agent.oauth2_client_secret,
        }
        if agent.oauth2_scopes:
            data["scope"] = agent.oauth2_scopes
        resp = httpx.post(token_url, data=data, timeout=10)
        if resp.status_code == 400 and agent.oauth2_scopes:
            logger.info("Token request with scopes failed, retrying without scopes")
            data.pop("scope", None)
            resp = httpx.post(token_url, data=data, timeout=10)
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as e:
        logger.warning("Failed to obtain OAuth2 token: %s", e)
        return None


def _build_headers(agent: Any) -> dict[str, str]:
    """Build request headers, including auth if configured.

    For AgentCore URLs, uses the stored agentcore_session_id if available,
    otherwise generates a new UUID.
    """
    base_url = getattr(agent, "base_url", "")
    headers: dict[str, str] = {"Accept": "*/*"}
    if agent.auth_type == "oauth2":
        token = _get_oauth2_token(agent)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    if _is_agentcore_url(base_url):
        session_id = getattr(agent, "agentcore_session_id", None) or str(uuid.uuid4())
        headers["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] = session_id
    return headers


def _fetch_salesforce_agent_card(base_url: str, headers: dict[str, str]) -> dict:
    """Fetch the Agent Card from a Salesforce Agentforce A2A endpoint.

    Salesforce uses /v1/card instead of /.well-known/agent.json and returns
    401 for unknown paths rather than 404.
    """
    url = base_url + "/v1/card"
    try:
        resp = httpx.get(url, headers=headers, timeout=A2A_REQUEST_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        friendly = {
            401: "authentication required — check OAuth2 credentials",
            403: "access denied — check OAuth2 credentials and scopes",
        }
        detail = friendly.get(status_code, e.response.text[:200])
        raise ValueError(f"Salesforce Agent Card fetch failed (HTTP {status_code}): {detail}") from e
    except httpx.ConnectError as e:
        raise ValueError(f"Cannot connect to {base_url} — verify the URL is correct") from e
    except httpx.TimeoutException as e:
        raise ValueError(f"Connection to {base_url} timed out after {A2A_REQUEST_TIMEOUT}s") from e
    except Exception as e:
        raise ValueError(f"Failed to fetch Salesforce Agent Card from {url}: {e}") from e


def fetch_agent_card(base_url: str, auth_headers: dict[str, str] | None = None) -> dict:
    """Fetch the Agent Card from the well-known endpoint.

    Args:
        base_url: The base URL of the A2A agent.
        auth_headers: Optional headers for authenticated requests.

    Returns:
        The parsed Agent Card JSON.

    Raises:
        ValueError: If the Agent Card cannot be fetched or is invalid.
    """
    stripped = base_url.rstrip("/")
    headers = auth_headers or {"Accept": "*/*"}

    # Salesforce Agentforce: card is at /v1/card, not .well-known
    if _is_salesforce_url(base_url):
        return _fetch_salesforce_agent_card(stripped, headers)

    # Try AgentCore path first for AgentCore URLs, then standard; reverse for others
    if _is_agentcore_url(base_url):
        paths = [AGENT_CARD_JSON_PATH, AGENT_JSON_PATH]
    else:
        paths = [AGENT_JSON_PATH, AGENT_CARD_JSON_PATH]

    last_error: Exception | None = None
    for path in paths:
        url = stripped + path
        try:
            resp = httpx.get(url, headers=headers, timeout=A2A_REQUEST_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            break
        except httpx.HTTPStatusError as e:
            last_error = e
            status = e.response.status_code
            # 404 = direct not found; 424 = AgentCore proxy received 404 from underlying agent
            if status in (404, 424):
                logger.debug("Agent Card not found at %s (HTTP %d), trying next path", url, status)
                continue
            friendly = {
                401: "authentication required — check OAuth2 credentials",
                403: "access denied — check OAuth2 credentials and scopes",
                500: "the remote server returned an internal error",
                502: "bad gateway — the remote server may be down",
                503: "the remote server is unavailable",
            }
            detail = friendly.get(status, e.response.text[:200])
            raise ValueError(f"Agent Card fetch failed (HTTP {status}): {detail}") from e
        except httpx.ConnectError as e:
            raise ValueError(f"Cannot connect to {base_url} — verify the URL is correct and the server is running") from e
        except httpx.TimeoutException as e:
            raise ValueError(f"Connection to {base_url} timed out after {A2A_REQUEST_TIMEOUT}s") from e
        except Exception as e:
            raise ValueError(f"Failed to fetch Agent Card from {url}: {e}") from e
    else:
        raise ValueError(
            "No Agent Card found — tried both /.well-known/agent.json and "
            "/.well-known/agent-card.json. The underlying agent may not implement "
            "the A2A protocol. Verify the agent exposes an Agent Card endpoint."
        )

    try:
        card = resp.json()
    except Exception as e:
        raise ValueError(f"Agent Card response is not valid JSON: {e}") from e

    # Validate required fields
    for field in ("name", "description", "url", "version"):
        if not card.get(field):
            raise ValueError(f"Agent Card missing required field: {field}")

    return card


def parse_agent_card(card: dict) -> dict:
    """Extract structured data from a raw Agent Card.

    Returns a dict with fields matching the A2aAgent model columns.
    """
    provider = card.get("provider") or {}
    capabilities = card.get("capabilities") or {}
    authentication = card.get("authentication") or {}

    return {
        "name": card["name"],
        "description": card["description"],
        "agent_version": card["version"],
        "documentation_url": card.get("documentationUrl"),
        "provider_organization": provider.get("organization"),
        "provider_url": provider.get("url"),
        "capabilities": capabilities,
        "authentication_schemes": authentication.get("schemes", []),
        "default_input_modes": card.get("defaultInputModes", []),
        "default_output_modes": card.get("defaultOutputModes", []),
    }


def parse_skills(card: dict) -> list[dict]:
    """Extract skills from an Agent Card.

    Returns a list of dicts with fields matching the A2aAgentSkill model columns.
    """
    skills_data = card.get("skills", [])
    skills: list[dict] = []
    for s in skills_data:
        skill: dict[str, Any] = {
            "skill_id": s.get("id", ""),
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "tags": s.get("tags", []),
        }
        if s.get("examples"):
            skill["examples"] = s["examples"]
        if s.get("inputModes"):
            skill["input_modes"] = s["inputModes"]
        if s.get("outputModes"):
            skill["output_modes"] = s["outputModes"]
        skills.append(skill)
    return skills


def test_a2a_connection(agent: Any) -> dict:
    """Test connectivity to an A2A agent by fetching its Agent Card.

    If the agent has OAuth2 configured, acquires a token first.
    """
    try:
        headers = _build_headers(agent)
        card = fetch_agent_card(agent.base_url, auth_headers=headers)
        name = card.get("name", "Unknown")
        version = card.get("version", "")
        version_str = f" v{version}" if version else ""
        return {"success": True, "message": f"Connected to {name}{version_str}"}
    except ValueError as e:
        return {"success": False, "message": str(e)}
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {e}"}
