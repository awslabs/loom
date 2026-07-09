"""Tests for admin audit endpoints."""
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db


class TestAuditLogin(unittest.TestCase):
    """Test cases for /api/admin/audit/login endpoints."""

    @classmethod
    def setUpClass(cls):
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

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def test_create_login(self):
        """Test recording a login event."""
        response = self.client.post("/api/admin/audit/login", json={
            "user_id": "user-1",
            "browser_session_id": "sess-abc",
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["user_id"], "user-1")
        self.assertEqual(data["browser_session_id"], "sess-abc")
        self.assertIn("logged_in_at", data)

    def test_create_login_with_timestamp(self):
        """Test recording a login with explicit timestamp."""
        response = self.client.post("/api/admin/audit/login", json={
            "user_id": "user-1",
            "browser_session_id": "sess-abc",
            "logged_in_at": "2026-03-20T10:00:00Z",
        })
        self.assertEqual(response.status_code, 201)

    def test_list_logins(self):
        """Test listing login records."""
        self.client.post("/api/admin/audit/login", json={
            "user_id": "user-1",
            "browser_session_id": "sess-1",
        })
        self.client.post("/api/admin/audit/login", json={
            "user_id": "user-2",
            "browser_session_id": "sess-2",
        })

        response = self.client.get("/api/admin/audit/logins")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)


class TestAuditAction(unittest.TestCase):
    """Test cases for /api/admin/audit/action endpoints."""

    @classmethod
    def setUpClass(cls):
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

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def test_create_action(self):
        """Test recording an action event."""
        response = self.client.post("/api/admin/audit/action", json={
            "user_id": "user-1",
            "browser_session_id": "sess-abc",
            "action_category": "agent",
            "action_type": "create",
            "resource_name": "my-agent",
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["action_category"], "agent")
        self.assertEqual(data["action_type"], "create")
        self.assertEqual(data["resource_name"], "my-agent")

    def test_create_action_no_resource(self):
        """Test recording an action without resource_name."""
        response = self.client.post("/api/admin/audit/action", json={
            "user_id": "user-1",
            "browser_session_id": "sess-abc",
            "action_category": "navigation",
            "action_type": "click",
        })
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["resource_name"])

    def test_list_actions(self):
        """Test listing action records."""
        self.client.post("/api/admin/audit/action", json={
            "user_id": "user-1",
            "browser_session_id": "sess-1",
            "action_category": "agent",
            "action_type": "create",
        })
        self.client.post("/api/admin/audit/action", json={
            "user_id": "user-1",
            "browser_session_id": "sess-1",
            "action_category": "memory",
            "action_type": "read",
        })

        response = self.client.get("/api/admin/audit/actions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)


class TestAuditPageView(unittest.TestCase):
    """Test cases for /api/admin/audit/pageview endpoints."""

    @classmethod
    def setUpClass(cls):
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

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def test_create_pageview(self):
        """Test recording a page view event."""
        response = self.client.post("/api/admin/audit/pageview", json={
            "user_id": "user-1",
            "browser_session_id": "sess-abc",
            "page_name": "AgentCatalog",
            "entered_at": "2026-03-20T10:00:00Z",
            "duration_seconds": 45,
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["page_name"], "AgentCatalog")
        self.assertEqual(data["duration_seconds"], 45)

    def test_create_pageview_no_duration(self):
        """Test recording a page view without duration."""
        response = self.client.post("/api/admin/audit/pageview", json={
            "user_id": "user-1",
            "browser_session_id": "sess-abc",
            "page_name": "Dashboard",
            "entered_at": "2026-03-20T10:00:00Z",
        })
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["duration_seconds"])

    def test_list_pageviews(self):
        """Test listing page view records."""
        self.client.post("/api/admin/audit/pageview", json={
            "user_id": "user-1",
            "browser_session_id": "sess-1",
            "page_name": "AgentCatalog",
            "entered_at": "2026-03-20T10:00:00Z",
        })
        self.client.post("/api/admin/audit/pageview", json={
            "user_id": "user-1",
            "browser_session_id": "sess-1",
            "page_name": "CostDashboard",
            "entered_at": "2026-03-20T10:05:00Z",
        })

        response = self.client.get("/api/admin/audit/pageviews")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)


class TestAuditSessions(unittest.TestCase):
    """Test cases for /api/admin/audit/sessions endpoints."""

    @classmethod
    def setUpClass(cls):
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

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _seed_session_data(self):
        """Seed login, action, and page view data for a session."""
        self.client.post("/api/admin/audit/login", json={
            "user_id": "user-1",
            "browser_session_id": "sess-xyz",
            "logged_in_at": "2026-03-20T09:00:00Z",
        })
        self.client.post("/api/admin/audit/action", json={
            "user_id": "user-1",
            "browser_session_id": "sess-xyz",
            "action_category": "agent",
            "action_type": "invoke",
            "performed_at": "2026-03-20T09:05:00Z",
        })
        self.client.post("/api/admin/audit/pageview", json={
            "user_id": "user-1",
            "browser_session_id": "sess-xyz",
            "page_name": "AgentDetail",
            "entered_at": "2026-03-20T09:02:00Z",
            "duration_seconds": 120,
        })

    def test_list_sessions(self):
        """Test listing browser sessions with activity counts."""
        self._seed_session_data()

        response = self.client.get("/api/admin/audit/sessions")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        session = data[0]
        self.assertEqual(session["browser_session_id"], "sess-xyz")
        self.assertEqual(session["user_id"], "user-1")
        self.assertEqual(session["action_count"], 1)
        self.assertEqual(session["page_view_count"], 1)

    def test_session_timeline(self):
        """Test getting chronological timeline for a session."""
        self._seed_session_data()

        response = self.client.get("/api/admin/audit/sessions/sess-xyz/timeline")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 3)
        # Should be sorted chronologically
        self.assertEqual(data[0]["type"], "login")
        self.assertEqual(data[1]["type"], "page_view")
        self.assertEqual(data[2]["type"], "action")

    def test_session_timeline_empty(self):
        """Test timeline for non-existent session returns empty list."""
        response = self.client.get("/api/admin/audit/sessions/nonexistent/timeline")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


class TestAuditSummary(unittest.TestCase):
    """Test cases for /api/admin/audit/summary endpoint."""

    @classmethod
    def setUpClass(cls):
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

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def test_summary_empty(self):
        """Test summary with no data."""
        response = self.client.get("/api/admin/audit/summary")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_logins"], 0)
        self.assertEqual(data["active_users"], 0)
        self.assertEqual(data["total_actions"], 0)
        self.assertEqual(data["actions_by_category"], {})
        self.assertEqual(data["page_views_by_page"], {})
        self.assertEqual(data["logins_by_day"], [])
        self.assertEqual(data["actions_by_day"], [])

    def test_summary_with_data(self):
        """Test summary with seeded data."""
        # Logins
        self.client.post("/api/admin/audit/login", json={
            "user_id": "user-1",
            "browser_session_id": "sess-1",
            "logged_in_at": "2026-03-20T10:00:00Z",
        })
        self.client.post("/api/admin/audit/login", json={
            "user_id": "user-2",
            "browser_session_id": "sess-2",
            "logged_in_at": "2026-03-20T11:00:00Z",
        })

        # Actions
        self.client.post("/api/admin/audit/action", json={
            "user_id": "user-1",
            "browser_session_id": "sess-1",
            "action_category": "agent",
            "action_type": "create",
            "performed_at": "2026-03-20T10:05:00Z",
        })
        self.client.post("/api/admin/audit/action", json={
            "user_id": "user-1",
            "browser_session_id": "sess-1",
            "action_category": "agent",
            "action_type": "invoke",
            "performed_at": "2026-03-20T10:10:00Z",
        })
        self.client.post("/api/admin/audit/action", json={
            "user_id": "user-2",
            "browser_session_id": "sess-2",
            "action_category": "memory",
            "action_type": "read",
            "performed_at": "2026-03-20T11:05:00Z",
        })

        # Page views
        self.client.post("/api/admin/audit/pageview", json={
            "user_id": "user-1",
            "browser_session_id": "sess-1",
            "page_name": "AgentCatalog",
            "entered_at": "2026-03-20T10:00:00Z",
            "duration_seconds": 60,
        })

        response = self.client.get("/api/admin/audit/summary")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_logins"], 2)
        self.assertEqual(data["active_users"], 2)
        self.assertEqual(data["total_actions"], 3)
        self.assertEqual(data["actions_by_category"]["agent"], 2)
        self.assertEqual(data["actions_by_category"]["memory"], 1)
        self.assertIn("AgentCatalog", data["page_views_by_page"])
        self.assertEqual(data["page_views_by_page"]["AgentCatalog"]["count"], 1)
        self.assertEqual(data["page_views_by_page"]["AgentCatalog"]["total_duration_seconds"], 60)


if __name__ == "__main__":
    unittest.main()
