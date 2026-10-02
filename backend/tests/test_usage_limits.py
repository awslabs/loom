"""Tests for usage limit CRUD endpoints."""
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import UserInfo, get_current_user
from app.models.usage_limit import UsageLimit


def _admin_user():
    # Stand-in for a real authenticated admin — bypasses Cognito entirely so
    # these tests don't need any identity provider running.
    return UserInfo(
        sub="admin",
        username="admin",
        groups=["g-admins-super"],
        scopes={"security:read", "security:write"},
    )


class TestUsageLimitCRUD(unittest.TestCase):
    """Test cases for usage limit CRUD endpoints."""

    @classmethod
    def setUpClass(cls):
        # One in-memory DB shared across the whole class; each test gets a
        # fresh session but the schema is only built once for speed.
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        self.session = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        # Swap out the real DB/auth dependencies for test doubles just for
        # the duration of this test.
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = _admin_user
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        app.dependency_overrides.clear()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)

    def test_create_usage_limit(self) -> None:
        # Happy path: a well-formed limit should come back with everything
        # we sent, plus the target default we didn't specify.
        response = self.client.post("/api/settings/usage-limits", json={
            "name": "User Token Cap",
            "scope": {"type": "user", "username": "alice"},
            "measure": "tokens",
            "threshold": 100000,
            "window": "daily",
            "enforcement": "block",
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["name"], "User Token Cap")
        self.assertEqual(data["scope"], {"type": "user", "username": "alice"})
        self.assertEqual(data["target"], {"type": "all"})  # default kicked in
        self.assertEqual(data["measure"], "tokens")
        self.assertEqual(data["enforcement"], "block")
        self.assertTrue(data["enabled"])

    def test_create_duplicate_returns_409(self) -> None:
        # name is unique=True on the model — make sure the API surfaces that
        # as a clean 409, not a raw DB IntegrityError.
        payload = {
            "name": "Dup Limit",
            "scope": {"type": "user", "username": "bob"},
            "measure": "tokens",
            "threshold": 1000,
        }
        self.client.post("/api/settings/usage-limits", json=payload)
        response = self.client.post("/api/settings/usage-limits", json=payload)
        self.assertEqual(response.status_code, 409)

    def test_create_invalid_measure_returns_400(self) -> None:
        response = self.client.post("/api/settings/usage-limits", json={
            "name": "Bad Measure",
            "scope": {"type": "user", "username": "carol"},
            "measure": "widgets",  # not tokens/budget
            "threshold": 10,
        })
        self.assertEqual(response.status_code, 400)

    def test_create_invalid_window_returns_400(self) -> None:
        response = self.client.post("/api/settings/usage-limits", json={
            "name": "Bad Window",
            "scope": {"type": "user", "username": "dave"},
            "measure": "tokens",
            "threshold": 10,
            "window": "hourly",  # not a supported window
        })
        self.assertEqual(response.status_code, 400)

    def test_create_missing_scope_target_fails_validation(self) -> None:
        # scope has no default on the model, and Field(...) makes it required
        # at the pydantic layer — this should never even reach our own
        # validation, FastAPI rejects it first with a 422.
        response = self.client.post("/api/settings/usage-limits", json={
            "name": "No Scope",
            "measure": "tokens",
            "threshold": 10,
        })
        self.assertEqual(response.status_code, 422)

    def test_create_group_scope_missing_group_returns_400(self) -> None:
        # scope.type is valid ("group") but the group name itself is missing —
        # this is the case our custom _validate_scope exists for, since
        # pydantic alone can't catch it.
        response = self.client.post("/api/settings/usage-limits", json={
            "name": "Bad Group Scope",
            "scope": {"type": "group"},
            "measure": "tokens",
            "threshold": 10,
        })
        self.assertEqual(response.status_code, 400)

    def test_create_model_target_missing_model_id_returns_400(self) -> None:
        # Same idea as above but for target — same-shaped bug, different field.
        response = self.client.post("/api/settings/usage-limits", json={
            "name": "Bad Model Target",
            "scope": {"type": "user", "username": "erin"},
            "target": {"type": "model"},
            "measure": "tokens",
            "threshold": 10,
        })
        self.assertEqual(response.status_code, 400)

    def test_list_usage_limits(self) -> None:
        self.client.post("/api/settings/usage-limits", json={
            "name": "Limit A",
            "scope": {"type": "user", "username": "frank"},
            "measure": "tokens",
            "threshold": 10,
        })
        response = self.client.get("/api/settings/usage-limits")
        self.assertEqual(response.status_code, 200)
        names = [l["name"] for l in response.json()]
        self.assertIn("Limit A", names)

    def test_get_usage_limit_not_found(self) -> None:
        # No limit will ever have this id in a fresh in-memory DB.
        response = self.client.get("/api/settings/usage-limits/99999")
        self.assertEqual(response.status_code, 404)

    def test_update_usage_limit(self) -> None:
        create = self.client.post("/api/settings/usage-limits", json={
            "name": "To Update",
            "scope": {"type": "user", "username": "grace"},
            "measure": "tokens",
            "threshold": 10,
        })
        limit_id = create.json()["id"]

        # Only sending two fields — confirms the partial-update logic doesn't
        # accidentally wipe out anything we didn't mention.
        response = self.client.put(f"/api/settings/usage-limits/{limit_id}", json={
            "threshold": 500,
            "enforcement": "throttle",
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["threshold"], 500)
        self.assertEqual(data["enforcement"], "throttle")

    def test_delete_usage_limit(self) -> None:
        create = self.client.post("/api/settings/usage-limits", json={
            "name": "To Delete",
            "scope": {"type": "user", "username": "heidi"},
            "measure": "tokens",
            "threshold": 10,
        })
        limit_id = create.json()["id"]

        response = self.client.delete(f"/api/settings/usage-limits/{limit_id}")
        self.assertEqual(response.status_code, 204)

        # And it should actually be gone, not just soft-hidden.
        get_response = self.client.get(f"/api/settings/usage-limits/{limit_id}")
        self.assertEqual(get_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
