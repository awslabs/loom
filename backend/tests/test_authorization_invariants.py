"""Invariants that stop a fix from being a partial fix.

Five reports from the same researcher have now landed on Loom, and the pattern
across them was not five unrelated bugs — it was one bug class, plus four ways
a fix for it failed to be complete:

1. **Duplicated policy.** `invoke_agent_endpoint` carried an inlined copy of
   `check_resource_group_access`. Making the shared helper fail closed on
   untagged resources left the copy failing open, so untagged agents stayed
   invokable for two releases after the "untagged fails closed" release.
2. **Fixed at the reported site, not across the class.** Credential provider
   names were re-keyed off a mutable display name; the structurally identical
   MCP admin API key was not, and came back as its own report.
3. **Unverified claims.** A docstring asserted "list routes already filter by
   loom:group" and the guard-test allowlist cited that as its justification.
   Neither was true of the MCP, connector or A2A listings — so the test
   written to catch the class exempted the class.
4. **A guarantee stated more broadly than the code delivered.** The release
   notes promised untagged resources were super-admin-only. On the read paths
   they were. On invoke they were not.

Each test here turns one of those into something mechanical. They are
deliberately structural: the failure being guarded is *believing a rule holds
everywhere it should*, and prose cannot check that.
"""
import ast
import pathlib
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import GROUP_SCOPES, UserInfo, get_current_user
from app.models.a2a import A2aAgent
from app.models.agent import Agent
from app.models.mcp import McpServer
from app.models.memory import Memory

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


# ---------------------------------------------------------------------------
# 1. The group rule lives in exactly one place
# ---------------------------------------------------------------------------
# Tokens that mean "someone is deriving a caller's permitted loom:group values
# by hand" — i.e. reimplementing check_resource_group_access rather than
# calling it. That is what let the invoke path drift away from the shared rule.
INLINE_RULE_TOKENS = (
    'startswith("g-admins-")',
    'startswith("g-users-")',
    'replace("g-admins-"',
    'replace("g-users-"',
)

# Files allowed to derive group values directly, each with a verified reason.
# Reasons here were checked against the code, not written from intent — that
# mistake is item 3 in this module's docstring.
INLINE_RULE_ALLOWED = {
    "routers/utils.py": "defines check_resource_group_access; is the rule",
    "routers/security.py": "_get_user_group extracts the caller's own group for tagging defaults, not an access decision",
}


class TestGroupRuleIsNotReimplemented(unittest.TestCase):
    def test_no_inline_group_derivation_outside_allowlist(self) -> None:
        offenders = []
        for path in sorted(APP_DIR.rglob("*.py")):
            rel = path.relative_to(APP_DIR).as_posix()
            if rel in INLINE_RULE_ALLOWED:
                continue
            text = path.read_text()
            hits = [tok for tok in INLINE_RULE_TOKENS if tok in text]
            if hits:
                offenders.append(f"{rel}: {', '.join(hits)}")
        self.assertEqual(
            [], offenders,
            "This derives a caller's permitted loom:group values by hand "
            "instead of calling check_resource_group_access. An inlined copy "
            "is how the invoke path kept failing open for two releases after "
            "the shared helper was fixed. Call the helper, or add the file to "
            "INLINE_RULE_ALLOWED with a reason you have verified:\n  "
            + "\n  ".join(offenders),
        )

    def test_inline_rule_allowlist_has_no_stale_entries(self) -> None:
        stale = [
            rel for rel in INLINE_RULE_ALLOWED
            if not (APP_DIR / rel).exists()
        ]
        self.assertEqual([], stale, f"INLINE_RULE_ALLOWED names missing files: {stale}")

    def test_inline_rule_allowlist_has_no_unnecessary_entries(self) -> None:
        """An exemption whose file no longer derives groups by hand is a
        standing permission to start doing it again."""
        unnecessary = []
        for rel in INLINE_RULE_ALLOWED:
            path = APP_DIR / rel
            if path.exists() and not any(t in path.read_text() for t in INLINE_RULE_TOKENS):
                unnecessary.append(rel)
        self.assertEqual(
            [], unnecessary,
            f"These INLINE_RULE_ALLOWED entries are no longer needed: {unnecessary}",
        )


# ---------------------------------------------------------------------------
# 2. Secret names are built in one place
# ---------------------------------------------------------------------------
# Two reports were the same bug: a secret or provider name interpolated a
# mutable, caller-controlled display name, so renaming a row the caller owned
# retargeted the lookup at another group's credential. Both fixes keyed the
# name on a server-assigned id instead. The durable version of that fix is to
# stop building these names ad hoc, so the keying decision is made in one
# reviewable place rather than in an f-string in a router.
# Only Secrets Manager paths. `loom-` names (IAM roles, log groups, dashboards,
# S3 prefixes) are deliberately out of scope: they are not credential lookups,
# and sweeping them in would make the allowlist below meaningless.
SECRET_PATH_PREFIX = "loom/"

# Modules allowed to construct a Secrets Manager path, each with the reason its
# keying is safe. Every reason here was checked against the code — asserting an
# unverified one is item 3 in this module's docstring.
SECRET_PATH_BUILDERS_ALLOWED = {
    "services/mcp.py": (
        "admin key keyed on the immutable server id; the per-user path is "
        "name-keyed but confined by the trailing user_sub, and cross-group "
        "name collisions are refused at the API boundary"
    ),
    "services/authorizer_linking.py": "keyed on the immutable authorizer id plus user_sub",
    "routers/security.py": (
        "authorizer client secrets are name-keyed at creation only; "
        "AuthorizerConfig.name is unique=True so no cross-group collision is "
        "possible, and every read goes through the stored client_secret_arn "
        "rather than re-deriving the path"
    ),
    "routers/identity_providers.py": (
        "same shape as routers/security.py: IdentityProvider.name is "
        "unique=True and reads go through the stored client_secret_arn"
    ),
    "routers/agents.py": (
        "per-agent paths keyed on the agent id (cognito-client-secret) or "
        "name plus id (llm-provider-api-key); the MCP per-user path now comes "
        "from services/mcp.py's helper"
    ),
    "services/litellm.py": "a single module-level constant, loom/settings/litellm-master-key",
}


def _builds_a_secret_path(path: pathlib.Path) -> list[str]:
    """String literals and f-strings that start a Secrets Manager path."""
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        head = None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            head = node.value
        elif isinstance(node, ast.JoinedStr):
            head = next(
                (v.value for v in node.values
                 if isinstance(v, ast.Constant) and isinstance(v.value, str)),
                "",
            )
        if head and head.startswith(SECRET_PATH_PREFIX):
            found.append(f"line {node.lineno}: {head[:48]!r}")
    return sorted(set(found))


class TestSecretPathsAreBuiltInReviewedPlaces(unittest.TestCase):
    """Two reports were the same bug: a credential looked up by a path built
    from a mutable, caller-controlled display name, so renaming a row the
    caller owned retargeted the lookup at another group's secret. Both fixes
    re-keyed onto a server-assigned id.

    The durable form of that fix is to keep the set of modules that can mint a
    secret path small and explicitly justified, so "is this keyed on something
    the caller can change?" is answered in review rather than discovered in a
    report.
    """

    def test_secret_paths_are_only_built_in_allowlisted_modules(self) -> None:
        offenders = []
        for path in sorted(APP_DIR.rglob("*.py")):
            rel = path.relative_to(APP_DIR).as_posix()
            if rel in SECRET_PATH_BUILDERS_ALLOWED:
                continue
            for hit in _builds_a_secret_path(path):
                offenders.append(f"{rel} {hit}")
        self.assertEqual(
            [], offenders,
            "A Secrets Manager path is being built outside the reviewed set. "
            "Whether it is keyed on something immutable is the security "
            "question — two reports were exactly this bug. Build it in a named "
            "helper in services/, or add the module to "
            "SECRET_PATH_BUILDERS_ALLOWED with a reason you have verified:\n  "
            + "\n  ".join(offenders),
        )

    def test_secret_path_allowlist_has_no_stale_entries(self) -> None:
        stale = [r for r in SECRET_PATH_BUILDERS_ALLOWED if not (APP_DIR / r).exists()]
        self.assertEqual([], stale, f"stale entries: {stale}")

    def test_secret_path_allowlist_has_no_unnecessary_entries(self) -> None:
        unnecessary = [
            r for r in SECRET_PATH_BUILDERS_ALLOWED
            if (APP_DIR / r).exists() and not _builds_a_secret_path(APP_DIR / r)
        ]
        self.assertEqual(
            [], unnecessary,
            f"These entries no longer build a secret path; remove them: {unnecessary}",
        )

    def test_no_secret_store_call_takes_an_inline_fstring(self) -> None:
        """The name handed to Secrets Manager must come from a helper, a
        column, or at least a named local — never an f-string written at the
        call site, where nobody reviews what it is keyed on."""
        offenders = []
        for path in sorted(APP_DIR.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                fn = (node.func.id if isinstance(node.func, ast.Name)
                      else getattr(node.func, "attr", None))
                if fn not in {"get_secret", "store_secret", "delete_secret"}:
                    continue
                if node.args and isinstance(node.args[0], ast.JoinedStr):
                    offenders.append(
                        f"{path.relative_to(APP_DIR).as_posix()}:{node.lineno} {fn}(f\"...\")"
                    )
        self.assertEqual([], offenders, "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# 3. The fail-closed guarantee holds on every route, not just the read ones
# ---------------------------------------------------------------------------
class TestUntaggedResourcesFailClosedEverywhere(unittest.TestCase):
    """Pins the guarantee the release notes made.

    "A resource with no loom:group tag is reachable only by a super-admin" was
    true of fetch-by-id and listings and false of invoke, because invoke had
    its own copy of the check. A guarantee that only holds on the paths
    somebody remembered is not a guarantee, so it is asserted here per route.

    The caller is given *every* scope while holding no super-admin group. That
    matters: an earlier test in this series looked like it proved a group check
    when the scope gate was actually doing the rejecting, so the group check it
    claimed to cover was never exercised. With all scopes present, a 403 can
    only have come from the group rule.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        cls.all_scopes = sorted({s for v in GROUP_SCOPES.values() for s in v})

    def setUp(self) -> None:
        self.db = self.Session()
        # Each factory call needs its own identifiers: the subTest loops build
        # one resource per route, and Agent.arn / McpServer name collide
        # otherwise.
        self._seq = 0

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        app.dependency_overrides.clear()

    def _as_non_super(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            sub="u", username="caller@example.com",
            groups=["t-admin", "g-admins-demo"], scopes=self.all_scopes,
        )

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    def _add(self, row, group: str | None):
        if group is not None:
            row.set_tags({"loom:group": group})
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _agent(self, group: str | None):
        n = self._next()
        return self._add(Agent(
            arn=f"arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/a-{n}",
            runtime_id=f"rt-{n}", name=f"agent_{n}", status="READY",
            region="us-east-1", account_id="123456789012", source="deploy",
        ), group)

    def _memory(self, group: str | None):
        return self._add(Memory(
            name=f"mem_{self._next()}", region="us-east-1", account_id="123456789012",
            status="ACTIVE", event_expiry_duration=90,
        ), group)

    def _mcp(self, group: str | None):
        return self._add(McpServer(
            name=f"mcp_{self._next()}", description="d", endpoint_url="https://x.internal/mcp",
            transport_type="streamable_http", auth_type="none",
        ), group)

    def _a2a(self, group: str | None):
        return self._add(A2aAgent(
            base_url="https://x.internal/a2a", name=f"a2a_{self._next()}", description="d",
            agent_version="1.0.0", status="active", auth_type="none",
        ), group)

    # (label, factory, method, path template, json body)
    def _cases(self):
        return [
            ("agent fetch", self._agent, "GET", "/api/agents/{id}", None),
            ("agent invoke", self._agent, "POST", "/api/agents/{id}/invoke",
             {"prompt": "hi", "qualifier": "DEFAULT"}),
            ("agent sessions", self._agent, "GET", "/api/agents/{id}/sessions", None),
            ("agent trace detail", self._agent, "GET", "/api/agents/{id}/traces/t-1", None),
            ("agent session traces", self._agent, "GET", "/api/agents/{id}/sessions/s-1/traces", None),
            ("agent token", self._agent, "POST", "/api/agents/{id}/token", None),
            ("memory fetch", self._memory, "GET", "/api/memories/{id}", None),
            ("mcp fetch", self._mcp, "GET", "/api/mcp/servers/{id}", None),
            ("mcp tool invoke", self._mcp, "POST", "/api/mcp/servers/{id}/tools/invoke",
             {"tool_name": "t", "arguments": {}}),
            ("a2a fetch", self._a2a, "GET", "/api/a2a/agents/{id}", None),
        ]

    def test_untagged_resource_is_refused_on_every_route(self) -> None:
        self._as_non_super()
        for label, factory, method, template, body in self._cases():
            with self.subTest(route=label):
                row = factory(None)
                url = template.format(id=row.id)
                resp = self.client.request(method, url, json=body)
                self.assertEqual(
                    403, resp.status_code,
                    f"{label} ({method} {url}) returned {resp.status_code} for an "
                    "UNTAGGED resource; the fail-closed guarantee says 403",
                )

    # (label, factory, listing path, json key holding the rows)
    LIST_CASES = (
        ("agents", "_agent", "/api/agents"),
        ("memories", "_memory", "/api/memories"),
        ("mcp servers", "_mcp", "/api/mcp/servers"),
        ("a2a agents", "_a2a", "/api/a2a/agents"),
    )

    def test_untagged_resource_is_absent_from_every_listing(self) -> None:
        """The guarantee covers listings, not just fetch-by-id.

        It did not, originally: list_agents and list_memories applied their
        group filter only `if "t-admin" not in user.groups`, so an untagged
        row was listed to any admin while GET /{id} on it returned 403. The
        earlier version of this class only exercised single-object routes, so
        it never saw that — a guarantee has to be checked on every route shape
        that can expose the resource, or the untested shape is where it drifts.
        """
        self._as_non_super()
        for label, factory_name, path in self.LIST_CASES:
            with self.subTest(listing=label):
                row = getattr(self, factory_name)(None)
                resp = self.client.get(path)
                self.assertEqual(200, resp.status_code, f"{label} listing failed")
                ids = [item.get("id") for item in resp.json()]
                self.assertNotIn(
                    row.id, ids,
                    f"{label} listing exposed UNTAGGED id {row.id}; the "
                    "fail-closed guarantee says super-admins only",
                )

    def test_other_groups_resource_is_absent_from_every_listing(self) -> None:
        """A listing must not expose a row the caller could not open."""
        self._as_non_super()
        for label, factory_name, path in self.LIST_CASES:
            with self.subTest(listing=label):
                row = getattr(self, factory_name)("mcp")  # caller is g-admins-demo
                resp = self.client.get(path)
                self.assertEqual(200, resp.status_code)
                ids = [item.get("id") for item in resp.json()]
                self.assertNotIn(row.id, ids, f"{label} listing exposed another group's row")

    def test_own_group_resource_is_present_in_every_listing(self) -> None:
        """Positive control: the filter must not simply empty the page."""
        self._as_non_super()
        for label, factory_name, path in self.LIST_CASES:
            with self.subTest(listing=label):
                row = getattr(self, factory_name)("demo")
                resp = self.client.get(path)
                self.assertEqual(200, resp.status_code)
                ids = [item.get("id") for item in resp.json()]
                self.assertIn(row.id, ids, f"{label} listing hid the caller's own row")

    def test_super_admin_still_sees_untagged_in_listings(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            sub="s", username="super@example.com",
            groups=["t-admin", "g-admins-super"], scopes=self.all_scopes,
        )
        for label, factory_name, path in self.LIST_CASES:
            with self.subTest(listing=label):
                row = getattr(self, factory_name)(None)
                ids = [item.get("id") for item in self.client.get(path).json()]
                self.assertIn(row.id, ids, f"{label} listing hid an untagged row from a super-admin")

    def test_positive_control_same_group_is_not_refused(self) -> None:
        """Proves the 403s above come from the missing tag and not from the
        route being broken, unreachable, or rejecting for some other reason."""
        self._as_non_super()
        for label, factory, method, template, body in self._cases():
            with self.subTest(route=label):
                row = factory("demo")
                url = template.format(id=row.id)
                resp = self.client.request(method, url, json=body)
                self.assertNotEqual(
                    403, resp.status_code,
                    f"{label} ({method} {url}) returned 403 for a resource in the "
                    "caller's OWN group, so the untagged test above proves nothing",
                )


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# 4. Loom cannot write IAM
# ---------------------------------------------------------------------------
# Loom used to create the agent execution role during deploy, replace its
# inline policy whenever an integration changed, apply extra statements when a
# permission request was approved, and delete the role on teardown. All of it
# is gone: roles are provisioned outside Loom by a platform engineer (see
# `shared/iac/role.yaml`) and registered through Security > Roles.
#
# The requirement is "no capability, whether latent or not", so this asserts
# the absence of the machinery rather than that it happens to be unreachable.
# Policy-document *builders* count as machinery and were removed too — the
# deployed task role has never been granted these actions, so any such code
# would be a dormant privilege waiting for someone to widen the policy.
IAM_WRITE_ACTIONS = (
    "create_role",
    "put_role_policy",
    "delete_role",
    "delete_role_policy",
    "attach_role_policy",
    "detach_role_policy",
    "tag_role",
    "untag_role",
    "update_assume_role_policy",
    "create_policy",
    "put_user_policy",
)

# Names that may not reappear anywhere under app/.
REMOVED_IAM_SYMBOLS = (
    "create_execution_role",
    "delete_execution_role",
    "update_role_policy",
    "build_base_policy",
    "build_trust_policy",
    "build_integration_policy_statements",
    "create_iam_role_with_policy",
    "update_iam_role_policy",
    "delete_iam_role",
    "apply_permissions_to_role",
    "_sync_role_policy",
)


class TestLoomCannotWriteIam(unittest.TestCase):
    def test_no_iam_write_calls_anywhere_in_app(self) -> None:
        offenders = []
        for path in sorted(APP_DIR.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None)
                if name in IAM_WRITE_ACTIONS:
                    offenders.append(
                        f"{path.relative_to(APP_DIR).as_posix()}:{node.lineno} .{name}()"
                    )
        self.assertEqual(
            [], offenders,
            "Loom must not create, modify or delete IAM roles or policies. "
            "The execution role is provisioned outside Loom (shared/iac/role.yaml) "
            "and registered under Security > Roles:\n  " + "\n  ".join(offenders),
        )

    def test_removed_iam_helpers_have_not_come_back(self) -> None:
        """Catches a reintroduction under the old name, including a re-add of
        the policy builders — which are latent write capability even though
        they only return a dict."""
        offenders = []
        for path in sorted(APP_DIR.rglob("*.py")):
            text = path.read_text()
            for symbol in REMOVED_IAM_SYMBOLS:
                if symbol in text:
                    offenders.append(f"{path.relative_to(APP_DIR).as_posix()}: {symbol}")
        self.assertEqual([], offenders, "\n  ".join(offenders))

    def test_iam_service_exports_only_discovery(self) -> None:
        """app/services/iam.py is read-only by construction."""
        from app.services import iam

        public = {n for n in dir(iam) if not n.startswith("_") and callable(getattr(iam, n))}
        public -= {"logging", "Any"}
        self.assertEqual({"list_agentcore_roles", "list_cognito_pools"}, public)

    def test_permission_requests_are_gone(self) -> None:
        """The feature existed only to have Loom apply statements to a role."""
        import app.models as models

        self.assertFalse(hasattr(models, "PermissionRequest"))
        offenders = [
            p.relative_to(APP_DIR).as_posix()
            for p in APP_DIR.rglob("*.py")
            if "PermissionRequest" in p.read_text()
        ]
        self.assertEqual([], offenders, f"PermissionRequest still referenced in {offenders}")


# ---------------------------------------------------------------------------
# 5. Server-supplied URLs reach the browser only through the guard
# ---------------------------------------------------------------------------
# Scanning TypeScript from a Python test is not elegant, but the frontend has
# no test runner of its own (no vitest, no jest, no test files), and pytest is
# the only suite CI can run. The alternative is no check at all, which is how
# three navigation sinks beyond the reported one went unnoticed: the reported
# bug was Link Account's authorize_url, while the login redirect and both
# logout redirects were fed the same IdP-derived values through the
# *unauthenticated* /api/auth/config.
FRONTEND_SRC = APP_DIR.parent.parent / "frontend" / "src"

NAV_SINK_PATTERNS = (
    "window.location.href =",
    "window.location.href=",
    "location.assign(",
    "location.replace(",
    "window.open(",
)

# file -> why this sink does not need the https guard. Every reason here was
# traced to the value's origin, not assumed.
NAV_SINK_ALLOWED = {
    "lib/navigation.ts": "defines assertHttpsUrl / navigateToExternal; is the guard",
    "App.tsx": "location.replace of loom_link_return_url, written only as window.location.pathname",
    "contexts/AuthContext.tsx": "same loom_link_return_url same-origin path; its two IdP redirects use navigateToExternal",
    "pages/OAuthLinkCallbackPage.tsx": "same loom_link_return_url same-origin path",
}

# Files that build an href in JSX from a non-literal. Markdown anchors are
# safe because react-markdown's defaultUrlTransform blanks unsafe schemes and
# rehype-raw is not installed, so raw HTML never renders.
JSX_HREF_ALLOWED = {
    "pages/SkillsPage.tsx": "registry-supplied repository/website URL, gated on isSafeExternalUrl",
    "components/MarkdownRenderer.tsx": "react-markdown anchor override; defaultUrlTransform already blanked the href",
    "pages/ChatPage.tsx": "react-markdown anchor overrides; defaultUrlTransform applies",
    "components/EvaluationRail.tsx": "hard-coded https console URL; region is encodeURIComponent'd",
    "components/EvaluationTestCases.tsx": "hard-coded https console URL from lib/evaluations.ts",
    "components/AgentRegistrationForm.tsx": "blob: object URL for a local download",
    "pages/AdminDashboardPage.tsx": "blob: object URL for a local download",
    "pages/SessionDetailPage.tsx": "blob: object URL for a local download",
}


def _frontend_files():
    if not FRONTEND_SRC.is_dir():
        return []
    return sorted(
        p for p in FRONTEND_SRC.rglob("*")
        if p.suffix in {".ts", ".tsx"} and "node_modules" not in p.parts
    )


class TestServerSuppliedUrlsAreGuarded(unittest.TestCase):
    def test_frontend_source_is_present(self) -> None:
        """A scan that silently finds no files is not a check."""
        self.assertTrue(_frontend_files(), f"no frontend sources under {FRONTEND_SRC}")

    def test_navigation_sinks_are_allowlisted(self) -> None:
        offenders = []
        for path in _frontend_files():
            rel = path.relative_to(FRONTEND_SRC).as_posix()
            if rel in NAV_SINK_ALLOWED:
                continue
            text = path.read_text()
            for pattern in NAV_SINK_PATTERNS:
                if pattern in text:
                    offenders.append(f"{rel}: {pattern}")
        self.assertEqual(
            [], offenders,
            "This navigates to a URL without the https guard. If the target "
            "comes from the server it can be a javascript: URL, which runs in "
            "Loom's origin where the session tokens live. Use "
            "navigateToExternal() from lib/navigation.ts, or add the file to "
            "NAV_SINK_ALLOWED with a reason you have traced:\n  "
            + "\n  ".join(offenders),
        )

    def test_jsx_hrefs_are_allowlisted(self) -> None:
        """A clickable href is a navigation sink too — that is what the
        registry-supplied skill repository URL was."""
        offenders = []
        for path in _frontend_files():
            rel = path.relative_to(FRONTEND_SRC).as_posix()
            if rel in JSX_HREF_ALLOWED:
                continue
            if "href={" in path.read_text():
                offenders.append(rel)
        self.assertEqual(
            [], offenders,
            "This builds an href from a non-literal. If the value comes from "
            "the server, gate it on isSafeExternalUrl() and render plain text "
            "when it fails, or add the file to JSX_HREF_ALLOWED with a "
            f"reason: {offenders}",
        )

    # Where an allowlist entry's reason is "it is gated on X", the entry is
    # only true while X is still called in that file. A file-level allowlist
    # catches a NEW sink but not a regression inside a file already reviewed —
    # neutering the SkillsPage check kept the suite green until this was
    # added. Same weakness that let the MCP listing exemption stand.
    REQUIRED_MARKERS = {
        "pages/SkillsPage.tsx": "isSafeExternalUrl",
        "components/EvaluationRail.tsx": "encodeURIComponent",
        "components/InvokePanel.tsx": "navigateToExternal",
        "pages/ChatPage.tsx": "navigateToExternal",
        "api/auth.ts": "navigateToExternal",
        "api/security.ts": "assertHttpsUrl",
        "contexts/AuthContext.tsx": "navigateToExternal",
    }

    def test_allowlisted_files_still_call_their_guard(self) -> None:
        offenders = []
        for rel, marker in self.REQUIRED_MARKERS.items():
            path = FRONTEND_SRC / rel
            if not path.exists():
                offenders.append(f"{rel}: file is gone")
            elif marker not in path.read_text():
                offenders.append(f"{rel}: no longer calls {marker}()")
        self.assertEqual(
            [], offenders,
            "A file is exempt, or safe, only because it calls this guard. It "
            "no longer does:\n  " + "\n  ".join(offenders),
        )

    def test_allowlists_have_no_stale_entries(self) -> None:
        missing = [
            rel for rel in (*NAV_SINK_ALLOWED, *JSX_HREF_ALLOWED)
            if not (FRONTEND_SRC / rel).exists()
        ]
        self.assertEqual([], missing, f"allowlists name missing files: {missing}")

    def test_raw_html_rendering_stays_unavailable(self) -> None:
        """react-markdown drops HTML nodes unless rehype-raw is added, which is
        what keeps agent and tool output from injecting script. Adding that
        dependency, or overriding urlTransform, would undo it silently."""
        pkg = (FRONTEND_SRC.parent / "package.json").read_text()
        for dangerous in ("rehype-raw", "dangerously-set", "marked"):
            self.assertNotIn(dangerous, pkg, f"{dangerous} would re-enable raw HTML rendering")
        for path in _frontend_files():
            text = path.read_text()
            self.assertNotIn("urlTransform", text, f"{path.name} overrides react-markdown's URL sanitiser")
            self.assertNotIn("dangerouslySetInnerHTML", text, f"{path.name} injects raw HTML")
