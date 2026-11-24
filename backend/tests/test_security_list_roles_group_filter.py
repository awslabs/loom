"""GET /api/security/roles must not list other groups' roles to a group-scoped security:read admin."""
import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.main import app
from app.models.managed_role import ManagedRole


class TestListRolesGroupFilter(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        for name, group in (("demo-role", "demo"), ("other-role", "other"), ("untagged-role", None)):
            role = ManagedRole(
                role_name=name, role_arn=f"arn:aws:iam::123456789012:role/{name}", role_type="agent",
                description="", policy_document=json.dumps({"Statement": []}),
            )
            role.set_tags({"loom:group": group} if group else {})
            self.db.add(role)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        app.dependency_overrides.clear()

    def _list_as(self, groups: list[str]) -> list[str]:
        user = UserInfo(sub="s", username="alice@example.com", groups=groups, scopes=derive_scopes(groups))
        app.dependency_overrides[get_current_user] = lambda: user
        resp = self.client.get("/api/security/roles")
        self.assertEqual(resp.status_code, 200, resp.text)
        return sorted(r["role_name"] for r in resp.json())

    def test_security_read_admin_sees_only_own_group_roles(self) -> None:
        demo_admin = ["t-admin", "g-admins-demo"]
        self.assertIn("security:read", derive_scopes(demo_admin))
        self.assertEqual(self._list_as(demo_admin), ["demo-role"])
        # Positive control: super-admins remain unrestricted, including untagged roles.
        self.assertEqual(self._list_as(["t-admin", "g-admins-super"]), ["demo-role", "other-role", "untagged-role"])


if __name__ == "__main__":
    unittest.main()
