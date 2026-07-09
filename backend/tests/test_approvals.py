"""Tests for approval policy CRUD and approval coordination endpoints."""
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import UserInfo, get_current_user
from app.models.approval_policy import ApprovalPolicy
from app.models.approval_log import ApprovalLog


def _admin_user():
    return UserInfo(
        sub="admin",
        username="admin",
        groups=["g-admins-super"],
        scopes={
            "security:read", "security:write", "invoke",
            "agent:read", "agent:write",
        },
    )


class TestApprovalPolicyCRUD(unittest.TestCase):
    """Test cases for approval policy CRUD endpoints."""

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
        app.dependency_overrides[get_current_user] = _admin_user
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        app.dependency_overrides.clear()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)

    def test_create_approval_policy(self) -> None:
        response = self.client.post("/api/settings/approval-policies", json={
            "name": "Test Policy",
            "policy_type": "loop_hook",
            "tool_match_rules": ["db_*", "file_write"],
            "approval_mode": "require_approval",
            "timeout_seconds": 120,
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["name"], "Test Policy")
        self.assertEqual(data["policy_type"], "loop_hook")
        self.assertEqual(data["tool_match_rules"], ["db_*", "file_write"])
        self.assertEqual(data["timeout_seconds"], 120)
        self.assertTrue(data["enabled"])

    def test_create_duplicate_policy_returns_409(self) -> None:
        self.client.post("/api/settings/approval-policies", json={
            "name": "Unique Policy",
            "policy_type": "loop_hook",
        })
        response = self.client.post("/api/settings/approval-policies", json={
            "name": "Unique Policy",
            "policy_type": "loop_hook",
        })
        self.assertEqual(response.status_code, 409)

    def test_create_invalid_policy_type_returns_400(self) -> None:
        response = self.client.post("/api/settings/approval-policies", json={
            "name": "Bad Type",
            "policy_type": "invalid",
        })
        self.assertEqual(response.status_code, 400)

    def test_list_approval_policies(self) -> None:
        self.client.post("/api/settings/approval-policies", json={
            "name": "Policy A",
            "policy_type": "loop_hook",
        })
        response = self.client.get("/api/settings/approval-policies")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)

    def test_get_approval_policy(self) -> None:
        create_resp = self.client.post("/api/settings/approval-policies", json={
            "name": "Policy B",
            "policy_type": "tool_context",
        })
        policy_id = create_resp.json()["id"]
        response = self.client.get(f"/api/settings/approval-policies/{policy_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Policy B")

    def test_update_approval_policy(self) -> None:
        create_resp = self.client.post("/api/settings/approval-policies", json={
            "name": "Policy C",
            "policy_type": "loop_hook",
            "timeout_seconds": 300,
        })
        policy_id = create_resp.json()["id"]
        response = self.client.put(f"/api/settings/approval-policies/{policy_id}", json={
            "timeout_seconds": 60,
            "enabled": False,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["timeout_seconds"], 60)
        self.assertFalse(response.json()["enabled"])

    def test_delete_approval_policy(self) -> None:
        create_resp = self.client.post("/api/settings/approval-policies", json={
            "name": "Policy D",
            "policy_type": "mcp_elicitation",
        })
        policy_id = create_resp.json()["id"]
        response = self.client.delete(f"/api/settings/approval-policies/{policy_id}")
        self.assertEqual(response.status_code, 204)
        get_resp = self.client.get(f"/api/settings/approval-policies/{policy_id}")
        self.assertEqual(get_resp.status_code, 404)

    def test_get_nonexistent_policy_returns_404(self) -> None:
        response = self.client.get("/api/settings/approval-policies/99999")
        self.assertEqual(response.status_code, 404)


class TestApprovalDecision(unittest.TestCase):
    """Test cases for approval decision endpoint."""

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
        app.dependency_overrides[get_current_user] = _admin_user
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        app.dependency_overrides.clear()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)

    def test_decide_nonexistent_request_returns_404(self) -> None:
        response = self.client.post("/api/settings/approvals/nonexistent-id/decide", json={
            "decision": "approved",
        })
        self.assertEqual(response.status_code, 404)


class TestApprovalLogs(unittest.TestCase):
    """Test cases for approval log query endpoint."""

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
        app.dependency_overrides[get_current_user] = _admin_user
        self.client = TestClient(app)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        app.dependency_overrides.clear()

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)

    def test_list_approval_logs_empty(self) -> None:
        response = self.client.get("/api/settings/approvals/logs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_approval_logs_with_data(self) -> None:
        self.session.query(ApprovalLog).delete()
        self.session.commit()
        log = ApprovalLog(
            request_id="req-123",
            session_id="sess-456",
            agent_id=1,
            tool_name="db_write",
            pattern_type="loop_hook",
            status="approved",
        )
        self.session.add(log)
        self.session.commit()

        response = self.client.get("/api/settings/approvals/logs")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["request_id"], "req-123")
        self.assertEqual(data[0]["tool_name"], "db_write")

    def test_list_approval_logs_filter_by_status(self) -> None:
        self.session.add(ApprovalLog(request_id="a", tool_name="t1", pattern_type="loop_hook", status="approved"))
        self.session.add(ApprovalLog(request_id="b", tool_name="t2", pattern_type="loop_hook", status="rejected"))
        self.session.commit()

        response = self.client.get("/api/settings/approvals/logs?status=approved")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["request_id"], "a")


class TestApprovalPolicyModel(unittest.TestCase):
    """Unit tests for ApprovalPolicy model methods."""

    def test_to_dict_serialization(self) -> None:
        policy = ApprovalPolicy(
            id=1,
            name="Test",
            policy_type="loop_hook",
            tool_match_rules='["db_*", "write_*"]',
            approval_mode="require_approval",
            timeout_seconds=120,
            agent_scope='{"type": "all"}',
            approval_cache_ttl=60,
            enabled=True,
        )
        d = policy.to_dict()
        self.assertEqual(d["name"], "Test")
        self.assertEqual(d["tool_match_rules"], ["db_*", "write_*"])
        self.assertEqual(d["agent_scope"], {"type": "all"})

    def test_get_tool_match_rules_empty(self) -> None:
        policy = ApprovalPolicy(tool_match_rules="[]")
        self.assertEqual(policy.get_tool_match_rules(), [])

    def test_get_agent_scope_default(self) -> None:
        policy = ApprovalPolicy(agent_scope=None)
        self.assertEqual(policy.get_agent_scope(), {"type": "all"})


class TestApprovalLogModel(unittest.TestCase):
    """Unit tests for ApprovalLog model methods."""

    def test_to_dict_serialization(self) -> None:
        log = ApprovalLog(
            id=1,
            request_id="req-1",
            session_id="sess-1",
            agent_id=5,
            tool_name="deploy",
            pattern_type="loop_hook",
            status="pending",
        )
        d = log.to_dict()
        self.assertEqual(d["request_id"], "req-1")
        self.assertEqual(d["agent_id"], 5)
        self.assertEqual(d["status"], "pending")


if __name__ == "__main__":
    unittest.main()
