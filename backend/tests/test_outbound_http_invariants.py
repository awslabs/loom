"""Every outbound HTTP request from the backend goes through net_guard.

net_guard is where the SSRF policy lives: scheme checks, DNS resolution with
the connection pinned to the validated address, the always-disallowed ranges
(loopback, link-local, cloud metadata, 0.0.0.0/8, NAT64, ...), and per-hop
redirect validation. A raw httpx/urllib/requests call skips all of it. The
LiteLLM proxy calls were the last ones doing so. They sent the master key to an
unvalidated, admin-configured URL.

This test scans app/ for HTTP client calls and fails if one appears outside
net_guard.py, unless it is on the allowlist below with a stated reason. The
allowlist is itself checked: an entry that no longer matches a call fails the
test, so an exemption cannot outlive the code it was written for.
"""
import ast
import pathlib
import unittest

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"
NET_GUARD = APP_DIR / "services" / "net_guard.py"

# Call targets that send an HTTP request or open a client capable of one.
_HTTPX_CALLS = {"get", "post", "put", "patch", "delete", "head", "options", "request", "stream",
                "Client", "AsyncClient"}
_REQUESTS_CALLS = {"get", "post", "put", "patch", "delete", "head", "options", "request", "Session"}

# (module path relative to app/, dotted call) -> why it may bypass net_guard.
ALLOWED: dict[tuple[str, str], str] = {
    ("services/bedrock_invocation.py", "urllib.request.urlopen"): (
        "SigV4-signed POST to the fixed https://bedrock-mantle.<region>.api.aws endpoint. The region "
        "is the backend's own DEFAULT_REGION, never request input, and the URL prefix is asserted "
        "immediately before the call."
    ),
}


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _http_calls(path: pathlib.Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("httpx", "requests", "urllib.request", "aiohttp"):
            # `from httpx import get` would hide the call from the dotted-name check below.
            found.append((f"from {node.module} import", node.lineno))
            continue
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if not name:
            continue
        root, _, attr = name.rpartition(".")
        if (root == "httpx" and attr in _HTTPX_CALLS) \
                or (root == "requests" and attr in _REQUESTS_CALLS) \
                or name in ("urllib.request.urlopen", "aiohttp.ClientSession"):
            found.append((name, node.lineno))
    return found


def _all_calls() -> dict[tuple[str, str], list[int]]:
    calls: dict[tuple[str, str], list[int]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        if path == NET_GUARD:
            continue
        rel = path.relative_to(APP_DIR).as_posix()
        for name, line in _http_calls(path):
            calls.setdefault((rel, name), []).append(line)
    return calls


class TestOutboundHttpGoesThroughNetGuard(unittest.TestCase):
    def test_no_http_call_bypasses_net_guard(self) -> None:
        unguarded = {
            key: lines for key, lines in _all_calls().items() if key not in ALLOWED
        }
        self.assertEqual(
            unguarded, {},
            "Outbound HTTP must go through app.services.net_guard (guarded_get/guarded_post for "
            "connection targets that may be VPC-internal, safe_get/safe_post for public-only ones). "
            "Found direct calls: " + ", ".join(f"{f}:{lines} {n}" for (f, n), lines in unguarded.items()),
        )

    def test_allowlist_has_no_stale_entries(self) -> None:
        calls = _all_calls()
        stale = [key for key in ALLOWED if key not in calls]
        self.assertEqual(stale, [], "Allowlisted calls no longer present; remove them from ALLOWED")

    def test_scanner_detects_the_forms_it_guards(self) -> None:
        """Positive control: without this the test above could pass by detecting nothing."""
        import tempfile
        source = (
            "import httpx, requests, urllib.request\n"
            "from httpx import post\n"
            "httpx.get('http://x')\n"
            "httpx.Client()\n"
            "requests.post('http://x')\n"
            "urllib.request.urlopen('http://x')\n"
            "httpx.Response(200)\n"  # not a request: must not be reported
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(source)
        found = sorted(name for name, _ in _http_calls(pathlib.Path(f.name)))
        pathlib.Path(f.name).unlink()
        self.assertEqual(found, sorted([
            "from httpx import", "httpx.get", "httpx.Client", "requests.post", "urllib.request.urlopen",
        ]))


if __name__ == "__main__":
    unittest.main()
