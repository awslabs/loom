"""Structural guards against the authorization gaps that keep recurring.

Four reported findings have had the same shape: a route resolved a resource
from a caller-supplied ID without checking the caller was entitled to it. Each
was fixed where it was reported, and the next one turned up somewhere else —
H1-3954919's fetch-by-ID sweep missed the session and invocation readers, which
then became their own report.

Scope-level authorization does not have this problem because it rides
dependency injection: you cannot write a route without a `require_scopes`
dependency and have it silently grant access. Instance-level authorization is
remembered rather than structural, so these tests make it mechanical. They are
deliberately coarse: an allowlist that someone must consciously extend is the
point, because the failure mode being guarded is *forgetting*.
"""
import ast
import pathlib
import re
import unittest

ROUTERS = pathlib.Path(__file__).resolve().parent.parent / "app" / "routers"

# Models whose rows belong to a loom:group (or to a user) and so must not be
# resolved from a caller-supplied ID without an authorization check.
SCOPED_MODELS = {
    "Agent",
    "InvocationSession",
    "Invocation",
    "ApprovalLog",
    "Memory",
    "McpServer",
    "A2aAgent",
}

# Modules allowed to query a scoped model directly, with the reason. Adding to
# this list is a deliberate act: it means you have reasoned about why the query
# is safe without the shared helper.
ALLOWED_RAW_QUERY = {
    # The helpers themselves must query in order to check.
    "utils.py": "defines get_agent_or_404 / get_session_or_404 / visible_agent_ids",
    # Resource owners: CRUD plus list routes that filter by loom:group inline.
    # A create has no row to authorize yet; a list filters rather than resolves.
    "agents.py": "agent CRUD and group-filtered list routes",
    "memories.py": "memory CRUD and group-filtered list routes",
    "mcp.py": "MCP server CRUD and group-filtered list routes",
    "a2a.py": "A2A agent CRUD and group-filtered list routes",
    # Scoped reads that resolve the agent through get_agent_or_404 first, then
    # query child rows under it.
    "invocations.py": "session/invocation routes group-check the agent first",
    "evaluations.py": "evaluation routes resolve the agent first",
    # logs.py still queries Memory for vended log sources; Agent now goes
    # through get_agent_or_404 in its two shared resolvers.
    "logs.py": "vended-log source lookup queries Memory",
    "approvals.py": "approval logs scoped via visible_agent_ids",
    # Cross-resource aggregates behind their own scopes rather than per-row
    # authorization. Worth revisiting: costs:read currently spans every group.
    "costs.py": "cost aggregation across agents (costs:read)",
    "admin.py": "admin dashboards aggregate across resources (admin:read)",
    "registry.py": "registry records joined to resources by ID (registry:read)",
    "security.py": "roles/authorizers, checked via check_resource_group_access",
}


def _router_files() -> list[pathlib.Path]:
    return sorted(p for p in ROUTERS.glob("*.py") if p.name != "__init__.py")


class TestEveryRouteIsScopeGuarded(unittest.TestCase):
    """Every API route must carry a scope dependency or an authenticated user.

    This is the layer that already works; the test pins it so it keeps working.
    """

    PUBLIC = {
        ("auth.py", "get"),   # /config — auth configuration for the login page
        ("auth.py", "post"),  # /token — the token exchange itself
    }

    def test_all_routes_require_scopes_or_a_user(self) -> None:
        decorator = re.compile(r"@router\.(get|post|put|patch|delete|websocket)\(")
        unguarded = []
        for path in _router_files():
            lines = path.read_text().split("\n")
            for i, line in enumerate(lines):
                m = decorator.search(line)
                if not m:
                    continue
                block = "\n".join(lines[i:i + 40])
                guarded = (
                    "require_scopes" in block
                    or "UserInfo" in block
                    or (m.group(1) == "websocket" and "authenticate_bearer_token" in path.read_text())
                )
                if not guarded and (path.name, m.group(1)) not in self.PUBLIC:
                    unguarded.append(f"{path.name}:{i + 1} @router.{m.group(1)}")

        self.assertEqual(
            [], unguarded,
            "Route(s) with neither a require_scopes dependency nor an authenticated "
            "user parameter. Add one, or add to PUBLIC with a comment saying why "
            f"it is safe to expose:\n  " + "\n  ".join(unguarded),
        )


class TestScopedModelsAreNotQueriedDirectly(unittest.TestCase):
    """Router modules should resolve scoped resources through the helpers.

    `db.query(Agent).filter(Agent.id == agent_id).first()` is the exact shape of
    every one of these findings: it answers "does this row exist" when the
    question is "may this caller have this row". `get_agent_or_404` and
    `get_session_or_404` answer the second.
    """

    def test_raw_queries_of_scoped_models_are_allowlisted(self) -> None:
        offenders = []
        for path in _router_files():
            if path.name in ALLOWED_RAW_QUERY:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute) and func.attr == "query"):
                    continue
                for arg in node.args:
                    name = arg.id if isinstance(arg, ast.Name) else None
                    if name in SCOPED_MODELS:
                        offenders.append(f"{path.name}:{node.lineno} query({name})")

        self.assertEqual(
            [], offenders,
            "Router(s) resolving a group-scoped model directly. Use "
            "get_agent_or_404 / get_session_or_404 / visible_agent_ids, or add the "
            f"module to ALLOWED_RAW_QUERY with a reason:\n  " + "\n  ".join(offenders),
        )

    def test_allowlist_has_no_stale_entries(self) -> None:
        """A module that no longer needs the exemption should lose it, so the
        allowlist keeps meaning something."""
        existing = {p.name for p in _router_files()}
        stale = sorted(set(ALLOWED_RAW_QUERY) - existing)
        self.assertEqual([], stale, f"ALLOWED_RAW_QUERY names modules that no longer exist: {stale}")


if __name__ == "__main__":
    unittest.main()
