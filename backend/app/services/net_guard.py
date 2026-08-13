"""SSRF-safe HTTP fetchers for outbound calls to user-supplied URLs.

Two guard levels are provided, since Loom's outbound calls fall into two
different trust models:

- ``safe_get``/``safe_post`` (strict, public-only): used for OAuth2/OIDC
  discovery ("well-known") documents and the token endpoints they advertise,
  since both are attacker-influenced (an MCP server or A2A agent
  registration supplies the well-known URL, and the discovery document
  supplies the token endpoint) and legitimate identity providers are always
  public internet-facing services. Every call is forced to HTTPS, resolved
  via DNS, and validated against private/loopback/link-local (including the
  169.254.169.254 cloud metadata address) and other non-public ranges.

- ``guarded_get``/``guarded_post`` (permissive, connection sinks): used for
  the actual MCP server / A2A agent connection targets
  (``endpoint_url``/``base_url``). Unlike OAuth infrastructure, reaching a
  private/VPC-internal address is a legitimate, documented use case here —
  the backend runs in private subnets specifically to support VPC-internal
  MCP servers and A2A agents, and HTTP (not just HTTPS) is a supported
  scheme for local/internal deployments. These guards therefore allow
  private (RFC 1918/RFC 4193) addresses through, but still always block the
  cloud metadata address, loopback, link-local, multicast, reserved, and
  unspecified addresses, since none of those are legitimate MCP/A2A targets.

Both levels resolve the hostname once and pin the connection to the
validated IP so a second DNS lookup at connect time can't rebind the
hostname to a different, disallowed address after the check has passed
(DNS rebinding). ``guarded_get``/``guarded_post`` additionally re-validate
every redirect hop before following it, since an initial target can pass
validation and then redirect to a disallowed address.
"""
import ipaddress
import logging
import socket
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

# Maximum number of redirect hops guarded_get/guarded_post will follow,
# re-validating the target at each hop.
_MAX_REDIRECTS = 5


class SSRFBlockedError(ValueError):
    """Raised when a URL is blocked by outbound SSRF protections."""


def _is_always_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if ip must never be reachable, regardless of guard level.

    Covers the cloud metadata address (a link-local address), loopback,
    other link-local addresses, multicast, reserved, and unspecified — none
    of which are legitimate targets for either OAuth infrastructure or a
    user-configured MCP server / A2A agent.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if ip is not a routable public address (strict/public-only mode)."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_private or _is_always_disallowed_ip(ip)


def _resolve_and_validate(hostname: str, *, allow_private: bool = False) -> str:
    """Resolve hostname and return a single validated IP to connect to.

    Raises SSRFBlockedError if resolution fails, or if any resolved address
    is disallowed for the requested guard level (always-disallowed
    addresses are rejected regardless of ``allow_private``). Returning one
    pinned address (rather than letting the HTTP client re-resolve at
    connect time) prevents DNS-rebinding between the check and the actual
    connection.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise SSRFBlockedError(f"DNS resolution failed for {hostname!r}: {e}") from e

    resolved_ips = {info[4][0] for info in infos}
    if not resolved_ips:
        raise SSRFBlockedError(f"No addresses resolved for {hostname!r}")

    is_disallowed = _is_always_disallowed_ip if allow_private else _is_disallowed_ip
    for ip_str in resolved_ips:
        ip = ipaddress.ip_address(ip_str)
        if is_disallowed(ip):
            raise SSRFBlockedError(f"{hostname!r} resolves to disallowed address {ip_str}")

    return next(iter(resolved_ips))


def _validate_url(url: str, *, require_https: bool, allow_private: bool) -> tuple[urllib.parse.ParseResult, str]:
    """Validate a URL's scheme and resolved address; return (parsed, pinned_ip)."""
    parsed = urllib.parse.urlparse(url)
    allowed_schemes = ("https",) if require_https else ("http", "https")
    if parsed.scheme not in allowed_schemes:
        raise SSRFBlockedError(f"Disallowed URL scheme {parsed.scheme!r}")
    if not parsed.hostname:
        raise SSRFBlockedError(f"URL has no hostname: {url!r}")

    validated_ip = _resolve_and_validate(parsed.hostname, allow_private=allow_private)
    return parsed, validated_ip


def _build_pinned_request(
    method: str,
    parsed: urllib.parse.ParseResult,
    validated_ip: str,
    *,
    data: dict | None = None,
    json: dict | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Request:
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    is_ipv6 = ":" in validated_ip
    pinned_host = f"[{validated_ip}]" if is_ipv6 else validated_ip
    pinned_netloc = f"{pinned_host}:{port}"
    pinned_url = parsed._replace(netloc=pinned_netloc).geturl()

    request_headers = dict(headers or {})
    request_headers.setdefault("Host", parsed.hostname)

    extensions = {"sni_hostname": parsed.hostname} if parsed.scheme == "https" else {}
    return httpx.Request(
        method,
        pinned_url,
        data=data,
        json=json,
        headers=request_headers,
        extensions=extensions,
    )


def _safe_request(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> httpx.Response:
    """Strict, public-only guarded request. Used by safe_get/safe_post."""
    parsed, validated_ip = _validate_url(url, require_https=True, allow_private=False)
    request = _build_pinned_request(method, parsed, validated_ip, data=data, headers=headers)
    with httpx.Client(timeout=timeout) as client:
        return client.send(request)


def safe_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 10) -> httpx.Response:
    """SSRF-guarded GET, public addresses only. Use for well-known/OIDC discovery documents."""
    return _safe_request("GET", url, headers=headers, timeout=timeout)


def safe_post(
    url: str,
    *,
    data: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> httpx.Response:
    """SSRF-guarded POST, public addresses only. Use for token endpoints discovered from a well-known document."""
    return _safe_request("POST", url, data=data, headers=headers, timeout=timeout)


def _guarded_request(
    method: str,
    url: str,
    *,
    json: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
    follow_redirects: bool = True,
) -> httpx.Response:
    """Permissive guarded request for MCP/A2A connection targets.

    Allows private (RFC 1918/RFC 4193) addresses and both http/https, but
    always blocks cloud metadata, loopback, link-local, multicast, reserved,
    and unspecified addresses. Each redirect hop is independently validated
    before being followed — the initial target passing validation does not
    grant a later redirect target a pass.
    """
    current_url = url
    with httpx.Client(timeout=timeout) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            parsed, validated_ip = _validate_url(current_url, require_https=False, allow_private=True)
            request = _build_pinned_request(
                method, parsed, validated_ip,
                json=json,
                headers=headers,
            )
            resp = client.send(request)
            if not follow_redirects or not resp.is_redirect:
                return resp
            location = resp.headers.get("location")
            if not location:
                return resp
            current_url = str(httpx.URL(current_url).join(location))
        raise SSRFBlockedError(f"Exceeded maximum redirect count ({_MAX_REDIRECTS}) fetching {url!r}")


def guarded_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
    follow_redirects: bool = True,
) -> httpx.Response:
    """SSRF-guarded GET for MCP/A2A connection targets (private addresses allowed).

    Use for MCP server endpoint_url and A2A agent base_url calls — these
    legitimately reach VPC-internal addresses, unlike OAuth infrastructure.
    """
    return _guarded_request("GET", url, headers=headers, timeout=timeout, follow_redirects=follow_redirects)


def guarded_post(
    url: str,
    *,
    json: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
    follow_redirects: bool = True,
) -> httpx.Response:
    """SSRF-guarded POST for MCP/A2A connection targets (private addresses allowed)."""
    return _guarded_request("POST", url, json=json, headers=headers, timeout=timeout, follow_redirects=follow_redirects)
