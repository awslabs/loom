"""An MCP server's admin API key must not be reachable by naming collision.

The reported chain (v1.7.4): `POST /api/mcp/servers` never tagged the row,
`check_resource_group_access` allowed any untagged row, `GET /api/mcp/servers`
had no group filter, and the admin key lived at
`loom/mcp/{name}/admin-api-key` — resolved by `name`, a mutable display string
with no uniqueness constraint. So a caller with `mcp:write` could list another
group's server, create a row, rename it onto the victim's display name, point
`endpoint_url` at their own oracle, and `tools/invoke` to have the victim's
admin key sent there as a Bearer header.

v1.8.5 closed the untagged-create and fail-open legs, but *not this bug*: the
attacker no longer needs an untagged row, because a row legitimately tagged
with their own group passes the ownership check and the name collision does
all the work. The group check gates the row; the vulnerability was in the
secret's name.

Two fixes, both pinned here. The admin key is keyed on the server id, which is
server-assigned and immutable, so a rename cannot retarget it. And a name
already held by another group is refused outright, which is what keeps the
remaining name-keyed path (per-user keys, embedded in deployed agent config)
safe.
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.models.mcp import McpServer
from app.services.mcp import (
    admin_api_key_secret_name,
    legacy_admin_api_key_secret_name,
    resolve_api_key,
)

VICTIM_KEY = "LOOM-MCP-NAME-KEY-WITNESS"
VICTIM_NAME = "shared"


class _FakeVault:
    """Stands in for Secrets Manager, keyed by secret name."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.store: dict[str, str] = dict(initial or {})

    def get(self, name: str, region: str) -> str:
        if name not in self.store:
            raise KeyError(f"secret {name} not found")
        return self.store[name]

    def put(self, name: str, value: str, region: str, description: str = "") -> str:
        self.store[name] = value
        return f"arn:aws:secretsmanager:{region}:123456789012:secret:{name}"

    def delete(self, name: str, region: str) -> None:
        self.store.pop(name, None)


class McpSecretTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self) -> None:
        self.db = self.Session()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        self.vault = _FakeVault()
        # Each binding is patched where it is actually looked up: services/mcp
        # and routers/mcp bind at import time, while two routes import
        # get_secret inside the function body and so resolve through
        # services.secrets at call time.
        for target in (
            "app.services.mcp.get_secret",
            "app.services.mcp.store_secret",
            "app.services.mcp.delete_secret",
            "app.routers.mcp.store_secret",
            "app.routers.mcp.delete_secret",
            "app.services.secrets.get_secret",
        ):
            impl = {
                "get_secret": self.vault.get,
                "store_secret": self.vault.put,
                "delete_secret": self.vault.delete,
            }[target.rsplit(".", 1)[1]]
            p = patch(target, side_effect=impl)
            p.start()
            self.addCleanup(p.stop)

        # The victim: an MCP server owned by the "mcp" group, holding an admin
        # API key, stored the way a pre-migration deployment would have.
        self.victim = McpServer(
            name=VICTIM_NAME, description="victim", endpoint_url="https://victim.internal/mcp",
            transport_type="streamable_http", auth_type="api_key",
            api_key_header_name="Authorization", has_admin_api_key="true",
        )
        self.victim.set_tags({"loom:group": "mcp"})
        self.db.add(self.victim)
        self.db.commit()
        self.db.refresh(self.victim)
        self.vault.store[legacy_admin_api_key_secret_name(VICTIM_NAME)] = VICTIM_KEY

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        app.dependency_overrides.clear()

    def _as(self, groups: list[str]) -> None:
        user = UserInfo(sub="attacker-sub", username="attacker@example.com",
                        groups=groups, scopes=derive_scopes(groups))
        app.dependency_overrides[get_current_user] = lambda: user

    def _create(self, name: str, group: str, endpoint: str = "http://127.0.0.1:18410/oracle"):
        return self.client.post("/api/mcp/servers", json={
            "name": name, "description": "attacker", "endpoint_url": endpoint,
            "transport_type": "streamable_http", "auth_type": "api_key",
            "api_key": "attacker-own-key",  # nosec B106
            "api_key_header_name": "Authorization",
            "tags": {"loom:group": group},
        })


class TestRenameOntoAnotherGroupsName(McpSecretTestCase):
    def test_cannot_create_a_server_named_like_another_groups(self) -> None:
        """Leg 4, at the source: the collision itself is refused."""
        self._as(["t-admin", "g-admins-demo"])
        resp = self._create(VICTIM_NAME, "demo")
        self.assertEqual(resp.status_code, 409)

    def test_cannot_rename_onto_another_groups_name(self) -> None:
        """The reported chain: create legitimately, then rename onto the victim."""
        self._as(["t-admin", "g-admins-demo"])
        created = self._create("attacker-own", "demo")
        self.assertEqual(created.status_code, 201)
        resp = self.client.put(
            f"/api/mcp/servers/{created.json()['id']}", json={"name": VICTIM_NAME},
        )
        self.assertEqual(resp.status_code, 409)

    def test_admin_key_is_not_reachable_through_a_colliding_name(self) -> None:
        """Defence in depth: even with a colliding row forced into the database
        behind the API's back, the id-keyed lookup must not return the victim's
        key, and the ambiguous legacy name must refuse rather than guess."""
        attacker = McpServer(
            name=VICTIM_NAME, description="attacker", endpoint_url="http://127.0.0.1:18410/oracle",
            transport_type="streamable_http", auth_type="api_key",
            api_key_header_name="Authorization", has_admin_api_key="true",
        )
        attacker.set_tags({"loom:group": "demo"})
        self.db.add(attacker)
        self.db.commit()
        self.db.refresh(attacker)

        resolved = resolve_api_key(attacker, db=self.db)
        self.assertNotEqual(resolved, VICTIM_KEY)
        self.assertIsNone(resolved)

    def test_super_admin_also_cannot_make_a_name_ambiguous(self) -> None:
        """A super-admin gains nothing by colliding, but would break the
        victim's own lookup, so the rule holds for them too."""
        self._as(["t-admin", "g-admins-super"])
        self.assertEqual(self._create(VICTIM_NAME, "demo").status_code, 409)

    # -- positive controls --

    def test_same_group_may_reuse_a_name(self) -> None:
        """Scoped to the security boundary, not global uniqueness."""
        self._as(["t-admin", "g-admins-super"])
        self.assertEqual(self._create(VICTIM_NAME, "mcp").status_code, 201)

    def test_unrelated_name_still_creates(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        self.assertEqual(self._create("attacker-own", "demo").status_code, 201)

    def test_rename_within_the_same_group_still_works(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        created = self._create("attacker-own", "demo")
        resp = self.client.put(
            f"/api/mcp/servers/{created.json()['id']}", json={"name": "attacker-renamed"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "attacker-renamed")


class TestAdminKeyIsKeyedOnServerId(McpSecretTestCase):
    def test_secret_name_format_contains_the_id_and_not_the_name(self) -> None:
        """Pinned against a literal, deliberately. Asserting with
        admin_api_key_secret_name() on both sides would pass even if the
        function stopped keying on the id at all."""
        self.assertEqual(admin_api_key_secret_name(42), "loom/mcp/42/admin-api-key")
        self.assertNotEqual(
            admin_api_key_secret_name(1), admin_api_key_secret_name(2),
        )

    def test_create_stores_the_key_under_the_server_id(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        created = self._create("attacker-own", "demo")
        self.assertEqual(created.status_code, 201)
        server_id = created.json()["id"]
        self.assertIn(f"loom/mcp/{server_id}/admin-api-key", self.vault.store)
        self.assertNotIn("loom/mcp/attacker-own/admin-api-key", self.vault.store)

    def test_rename_does_not_move_the_key(self) -> None:
        """The id-keyed name is stable across a rename, which is the property
        that makes a rename useless as an attack."""
        self._as(["t-admin", "g-admins-demo"])
        created = self._create("attacker-own", "demo")
        server_id = created.json()["id"]
        path = f"loom/mcp/{server_id}/admin-api-key"
        before = self.vault.store[path]
        resp = self.client.put(
            f"/api/mcp/servers/{server_id}", json={"name": "attacker-renamed"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.vault.store[path], before)
        self.assertNotIn("loom/mcp/attacker-renamed/admin-api-key", self.vault.store)

    def test_legacy_key_is_read_and_migrated_when_the_name_is_unique(self) -> None:
        """Existing deployments keep working, and self-heal onto the id path."""
        legacy = legacy_admin_api_key_secret_name(VICTIM_NAME)
        self.assertIn(legacy, self.vault.store)

        resolved = resolve_api_key(self.victim, db=self.db)
        self.assertEqual(resolved, VICTIM_KEY)
        self.assertEqual(
            self.vault.store[f"loom/mcp/{self.victim.id}/admin-api-key"], VICTIM_KEY,
        )
        self.assertNotIn(legacy, self.vault.store)

    def test_legacy_fallback_is_off_without_a_session(self) -> None:
        """No db means no way to prove the name is unambiguous, so no read."""
        self.assertIsNone(resolve_api_key(self.victim))


class TestListRoutesFilterByGroup(McpSecretTestCase):
    def test_mcp_list_does_not_leak_another_groups_server(self) -> None:
        """Leg 2. The listing is where the victim's display name came from."""
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.get("/api/mcp/servers")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(VICTIM_NAME, [s["name"] for s in resp.json()])

    def test_connectors_list_does_not_leak_either(self) -> None:
        self._as(["t-admin", "g-admins-demo"])
        resp = self.client.get("/api/mcp/servers/connectors")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(VICTIM_NAME, [s["name"] for s in resp.json()])

    def test_owning_group_still_sees_its_own_server(self) -> None:
        self._as(["t-admin", "g-admins-mcp"])
        names = [s["name"] for s in self.client.get("/api/mcp/servers").json()]
        self.assertIn(VICTIM_NAME, names)

    def test_super_admin_still_sees_everything(self) -> None:
        self._as(["t-admin", "g-admins-super"])
        names = [s["name"] for s in self.client.get("/api/mcp/servers").json()]
        self.assertIn(VICTIM_NAME, names)


if __name__ == "__main__":
    unittest.main()
