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
    # Resource owners: CRUD plus list routes. A create has no row to authorize
    # yet; a list filters rather than resolves.
    #
    # These reasons were previously all written as "group-filtered list
    # routes", which was not true of mcp.py or a2a.py — their listings had no
    # loom:group filter at all, and that exemption is how this test gave a
    # pass to the very gap it exists to catch. State what each one actually
    # does, and nothing more.
    "mcp.py": "MCP server CRUD; listings filtered via filter_visible_resources",
    "a2a.py": "A2A agent CRUD; listings filtered via filter_visible_resources",
    # KNOWN GAP, tracked separately: these two filter by loom:group only when
    # the caller is not a t-admin, so any scoped admin group (g-admins-mcp,
    # g-admins-memory, ...) still lists every group's rows. Fetch-by-ID is
    # 403, so this leaks existence and metadata rather than contents. Not
    # changed here because the read-everything behaviour is documented and
    # deliberate for g-admins-demo, so narrowing it is a product decision.
    "agents.py": "agent CRUD; list filters by loom:group for t-user only",
    "memories.py": "memory CRUD; list filters by loom:group for t-user only",
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


# ---------------------------------------------------------------------------
# Primary-key binds of group-owned rows
# ---------------------------------------------------------------------------
# The module-level guard above asks "does this file query a scoped model at
# all", which is coarse enough that a whole router gets one exemption. That is
# what let the agent deploy paths bind mcp_servers/memory_ids/a2a_agents by
# primary key with no group check for four releases: agents.py was already
# allowlisted for its own CRUD, so the binds inherited the pass.
#
# This guard is narrower. It asks, per *function*, whether a lookup keyed on a
# group-owned model's `id` is accompanied by an authorization check, so a new
# `*_id` field in a request body cannot quietly become a second way to reach
# another group's row.

# Rows that belong to a loom:group. Narrower than SCOPED_MODELS: these are the
# ones an authorization decision is made *about*, so resolving one by ID has to
# be accompanied by a check.
#
# TagProfile is deliberately absent even though it has get_tags(): a profile's
# tags are its payload — the preset applied to other resources — not a record
# of who owns the profile. Running an ownership check against those values
# would be coincidence, not authorization. A2aAgentSkill likewise has a `tags`
# column holding skill keywords, and no get_tags() at all.
GROUP_OWNED_MODELS = {
    "Agent",
    "Memory",
    "McpServer",
    "A2aAgent",
    "ManagedRole",
    "AuthorizerConfig",
}

# Calling any of these in the same function counts as having authorized the
# lookup. Coarse on purpose — proving the check covers the specific rows would
# need real dataflow analysis, and the failure being guarded is a check that is
# absent entirely, not one applied to the wrong variable.
GROUP_CHECK_CALLS = {
    "check_resource_group_access",
    "assert_bindable",
    "filter_visible_resources",
    "visible_agent_ids",
    "get_agent_or_404",
    "get_session_or_404",
    "_get_agent_or_404",
    "_get_server_or_404",
    "_get_memory_or_404",
}

# (module, function) -> reason. Each entry says why resolving a group-owned row
# by ID in that function needs no check.
ALLOWED_PK_BIND = {
    # Background tasks. Each is reachable only via background_tasks.add_task
    # from a route that has already resolved the agent through
    # get_agent_or_404, so the id they receive is authorized before they run.
    # They have no caller to check against: by the time they execute the
    # request is over and there is no UserInfo.
    ("agents.py", "_deploy_agent_background"): "queued by create_agent after its binds are authorized",
    ("agents.py", "_update_deploy_agent_background"): "queued by redeploy_deploy_agent after get_agent_or_404",
    ("agents.py", "_deploy_harness_background"): "queued by create_agent after its binds are authorized",
    ("agents.py", "_update_harness_background"): "queued by redeploy_harness_agent after get_agent_or_404",
    ("agents.py", "_delete_agent_background"): "queued by delete_agent after get_agent_or_404",
    ("agents.py", "_register_agent_in_registry_background"): "queued post-deploy with the agent's own id",
    ("evaluations.py", "_execute_run"): "queued by run_test_case/rescore_test_case after get_agent_or_404",
    # Not a caller-supplied lookup: queries by name and uses `id !=` only to
    # exclude the row being updated. It compares loom:group tags directly,
    # which is the check, but deliberately not through
    # check_resource_group_access — the rule has to bind super-admins too.
    ("mcp.py", "_assert_name_available"): "excludes self by id; compares group tags directly",
}


def _model_aliases(tree: ast.Module) -> dict[str, str]:
    """Local name -> model name, so `A2aAgent as A2aAgentModel` is resolved."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.models"):
            for alias in node.names:
                if alias.name in GROUP_OWNED_MODELS:
                    aliases[alias.asname or alias.name] = alias.name
    return aliases


def _functions(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _binds_group_owned_id(func, aliases: dict[str, str]) -> set[str]:
    """Model names whose `.id` this function uses inside a filter()."""
    found: set[str] = set()
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in {"filter", "filter_by", "get"}:
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Attribute)
                and sub.attr == "id"
                and isinstance(sub.value, ast.Name)
                and sub.value.id in aliases
            ):
                found.add(aliases[sub.value.id])
    return found


def _group_check_count(func) -> int:
    """How many group checks this function performs.

    Counted rather than merely detected. A single check used to satisfy the
    whole function, which meant a function binding three different models
    passed on the strength of checking one of them — removing the McpServer
    check from registry.create_record left the guard green because the a2a and
    agent branches still had theirs. Requiring one check per distinct
    group-owned model bound is still a proxy for dataflow analysis, but it
    closes that gap at no cost in false positives.
    """
    n = 0
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in GROUP_CHECK_CALLS:
                n += 1
    return n


def _calls_a_group_check(func) -> bool:
    return _group_check_count(func) > 0


class TestPrimaryKeyBindsAreAuthorized(unittest.TestCase):
    """A function resolving a group-owned row by ID must also authorize it."""

    def _offenders(self) -> list[str]:
        offenders: list[str] = []
        for path in sorted(ROUTERS.glob("*.py")):
            tree = ast.parse(path.read_text())
            aliases = _model_aliases(tree)
            if not aliases:
                continue
            for func in _functions(tree):
                models = _binds_group_owned_id(func, aliases)
                if not models:
                    continue
                if (path.name, func.name) in ALLOWED_PK_BIND:
                    continue
                checks = _group_check_count(func)
                if checks >= len(models):
                    continue
                offenders.append(
                    f"{path.name}:{func.lineno} {func.name}() binds "
                    f"{len(models)} group-owned model(s) "
                    f"({', '.join(sorted(models))}) by id but performs only "
                    f"{checks} group check(s)"
                )
        return offenders

    def test_every_primary_key_bind_is_authorized(self) -> None:
        offenders = self._offenders()
        self.assertEqual(
            [], offenders,
            "A caller-supplied ID reached a group-owned row without an "
            "authorization check. Call one of "
            f"{sorted(GROUP_CHECK_CALLS)} in the same function, or add the "
            "function to ALLOWED_PK_BIND with a reason:\n  "
            + "\n  ".join(offenders),
        )

    def test_pk_bind_allowlist_has_no_stale_entries(self) -> None:
        """A renamed or deleted function must not leave a silent exemption."""
        existing = set()
        for path in sorted(ROUTERS.glob("*.py")):
            tree = ast.parse(path.read_text())
            for func in _functions(tree):
                existing.add((path.name, func.name))
        stale = sorted(set(ALLOWED_PK_BIND) - existing)
        self.assertEqual(
            [], stale, f"ALLOWED_PK_BIND names functions that no longer exist: {stale}",
        )

    def test_pk_bind_allowlist_has_no_unnecessary_entries(self) -> None:
        """An exemption for a function that does not need one is a silent
        over-grant: the function could later start resolving a caller-supplied
        ID and the allowlist would already be waving it through. Entries must
        earn their place, so adding the group check to an exempt function is
        required to also remove its entry.
        """
        needed = set()
        for path in sorted(ROUTERS.glob("*.py")):
            tree = ast.parse(path.read_text())
            aliases = _model_aliases(tree)
            if not aliases:
                continue
            for func in _functions(tree):
                models = _binds_group_owned_id(func, aliases)
                if models and _group_check_count(func) < len(models):
                    needed.add((path.name, func.name))
        unnecessary = sorted(set(ALLOWED_PK_BIND) - needed)
        self.assertEqual(
            [], unnecessary,
            "These ALLOWED_PK_BIND entries are no longer needed — the function "
            "either authorizes its lookup now or no longer resolves a "
            f"group-owned row by id. Remove them: {unnecessary}",
        )

    def test_the_guard_actually_detects_a_missing_check(self) -> None:
        """Self-test. A guard that silently matches nothing is worse than no
        guard, so prove the detector fires on a function shaped like the bug.

        This is the mistake the MCP listing exemption made: the reason sounded
        right and nothing was verifying it.
        """
        src = (
            "from app.models.mcp import McpServer\n"
            "def bind(request, db, user):\n"
            "    return db.query(McpServer).filter(McpServer.id.in_(request.ids)).all()\n"
        )
        tree = ast.parse(src)
        aliases = _model_aliases(tree)
        self.assertEqual({"McpServer": "McpServer"}, aliases)
        func = next(_functions(tree))
        self.assertEqual({"McpServer"}, _binds_group_owned_id(func, aliases))
        self.assertFalse(_calls_a_group_check(func))

    def test_the_guard_accepts_a_checked_bind(self) -> None:
        """The negative control: adding the check must clear the finding."""
        src = (
            "from app.models.mcp import McpServer\n"
            "def bind(request, db, user):\n"
            "    rows = db.query(McpServer).filter(McpServer.id.in_(request.ids)).all()\n"
            "    assert_bindable(rows, user)\n"
            "    return rows\n"
        )
        func = next(_functions(ast.parse(src)))
        self.assertTrue(_calls_a_group_check(func))
