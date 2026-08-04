"""SSRF-safe HTTP fetcher for outbound calls to user-supplied URLs.

Used for OAuth2/OIDC discovery ("well-known") documents and the token
endpoints they advertise, since both are attacker-influenced (an MCP server
or A2A agent registration supplies the well-known URL, and the discovery
document supplies the token endpoint). Every call is forced to HTTPS,
resolved via DNS, and validated against private/loopback/link-local
(including the 169.254.169.254 cloud metadata address) and other
non-public ranges. The connection is then pinned to the resolved IP so a
second DNS lookup at connect time can't rebind the hostname to a different,
disallowed address after the check has passed.
"""
import ipaddress
import logging
import socket
import urllib.parse

import httpx

logger = logging.getLogger(__name__)


class SSRFBlockedError(ValueError):
    """Raised when a URL is blocked by outbound SSRF protections."""


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if ip is not a routable public address."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_and_validate(hostname: str) -> str:
    """Resolve hostname and return a single validated public IP to connect to.

    Raises SSRFBlockedError if resolution fails or any resolved address is
    non-public. Returning one pinned address (rather than letting the HTTP
    client re-resolve at connect time) prevents DNS-rebinding between the
    check and the actual connection.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise SSRFBlockedError(f"DNS resolution failed for {hostname!r}: {e}") from e

    resolved_ips = {info[4][0] for info in infos}
    if not resolved_ips:
        raise SSRFBlockedError(f"No addresses resolved for {hostname!r}")

    for ip_str in resolved_ips:
        ip = ipaddress.ip_address(ip_str)
        if _is_disallowed_ip(ip):
            raise SSRFBlockedError(f"{hostname!r} resolves to disallowed address {ip_str}")

    return next(iter(resolved_ips))


def _safe_request(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> httpx.Response:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise SSRFBlockedError(f"Disallowed URL scheme {parsed.scheme!r}; only https is permitted")
    if not parsed.hostname:
        raise SSRFBlockedError(f"URL has no hostname: {url!r}")

    validated_ip = _resolve_and_validate(parsed.hostname)

    port = parsed.port or 443
    is_ipv6 = ":" in validated_ip
    pinned_host = f"[{validated_ip}]" if is_ipv6 else validated_ip
    pinned_netloc = f"{pinned_host}:{port}"
    pinned_url = parsed._replace(netloc=pinned_netloc).geturl()

    request_headers = dict(headers or {})
    request_headers.setdefault("Host", parsed.hostname)

    request = httpx.Request(
        method,
        pinned_url,
        data=data,
        headers=request_headers,
        extensions={"sni_hostname": parsed.hostname},
    )
    with httpx.Client(timeout=timeout) as client:
        return client.send(request)


def safe_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 10) -> httpx.Response:
    """SSRF-guarded GET. Use for well-known/OIDC discovery documents."""
    return _safe_request("GET", url, headers=headers, timeout=timeout)


def safe_post(
    url: str,
    *,
    data: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> httpx.Response:
    """SSRF-guarded POST. Use for token endpoints discovered from a well-known document."""
    return _safe_request("POST", url, data=data, headers=headers, timeout=timeout)
