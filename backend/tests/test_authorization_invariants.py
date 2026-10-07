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
    # KNOWN GAP, deliberately open — see SPECIFICATIONS.md. These two filter by
    # loom:group only when the caller is not a t-admin, so a scoped admin
    # group still lists every group's rows. Fetch-by-id is 403, so this
    # discloses existence and metadata rather than contents. Narrowing it is a
    # product decision because reading across all groups is intended for
    # g-admins-demo.
    "routers/agents.py": "list_agents t-user filter (known gap, tracked)",
    "routers/memories.py": "list_memories t-user filter (known gap, tracked)",
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
