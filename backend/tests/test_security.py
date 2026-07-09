"""Tests for security management endpoints."""
import json
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.managed_role import ManagedRole
from app.models.authorizer_config import AuthorizerConfig
from app.models.permission_request import PermissionRequest


class TestSecurityRoles(unittest.TestCase):
    """Test cases for /api/security/roles endpoints."""

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

    @patch("app.routers.security.get_role_policy_details")
    def test_import_role(self, mock_policy):
        """Test importing an existing IAM role."""
        mock_policy.return_value = {"statements": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}

        response = self.client.post("/api/security/roles", json={
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "description": "Test role",
        })

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["role_name"], "test-role")
        self.assertEqual(data["role_arn"], "arn:aws:iam::123456789012:role/test-role")
        self.assertEqual(data["description"], "Test role")
        self.assertIsInstance(data["policy_document"], dict)

    @patch("app.routers.security.boto3")
    @patch("app.routers.security.get_role_policy_details")
    def test_import_role_fetches_tags(self, mock_policy, mock_boto3):
        """Test that importing a role fetches and stores IAM tags."""
        mock_policy.return_value = {"statements": []}
        mock_iam = MagicMock()
        mock_boto3.client.return_value = mock_iam
        mock_iam.list_role_tags.return_value = {
            "Tags": [
                {"Key": "loom:application", "Value": "myapp"},
                {"Key": "loom:owner", "Value": "alice"},
                {"Key": "Environment", "Value": "prod"},
            ]
        }

        response = self.client.post("/api/security/roles", json={
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/tagged-role",
        })

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["tags"]["loom:application"], "myapp")
        self.assertEqual(data["tags"]["loom:owner"], "alice")
        self.assertEqual(data["tags"]["Environment"], "prod")
        mock_iam.list_role_tags.assert_called_once_with(RoleName="tagged-role")

    @patch("app.routers.security.boto3")
    @patch("app.routers.security.get_role_policy_details")
    def test_import_role_tag_fetch_failure_non_fatal(self, mock_policy, mock_boto3):
        """Test that tag fetch failure does not block role import."""
        mock_policy.return_value = {"statements": []}
        mock_iam = MagicMock()
        mock_boto3.client.return_value = mock_iam
        mock_iam.list_role_tags.side_effect = Exception("Access denied")

        response = self.client.post("/api/security/roles", json={
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/no-tag-role",
        })

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["tags"], {})

    def test_import_role_missing_arn(self):
        """Test import mode without role_arn."""
        response = self.client.post("/api/security/roles", json={"mode": "import"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("role_arn is required", response.json()["detail"])

    @patch("app.routers.security.get_role_policy_details")
    def test_import_role_duplicate(self, mock_policy):
        """Test importing the same role twice."""
        mock_policy.return_value = {"statements": []}
        arn = "arn:aws:iam::123456789012:role/dup-role"

        self.client.post("/api/security/roles", json={"mode": "import", "role_arn": arn})
        response = self.client.post("/api/security/roles", json={"mode": "import", "role_arn": arn})
        self.assertEqual(response.status_code, 409)

    @patch("app.routers.security.create_iam_role_with_policy")
    def test_wizard_create_role(self, mock_create):
        """Test creating a role via wizard mode."""
        mock_create.return_value = "arn:aws:iam::123456789012:role/new-role"

        policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}]}
        response = self.client.post("/api/security/roles", json={
            "mode": "wizard",
            "role_name": "new-role",
            "description": "Wizard role",
            "policy_document": policy,
        })

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["role_name"], "new-role")
        self.assertEqual(data["role_arn"], "arn:aws:iam::123456789012:role/new-role")
        mock_create.assert_called_once()

    def test_wizard_create_role_missing_name(self):
        """Test wizard mode without role_name."""
        response = self.client.post("/api/security/roles", json={"mode": "wizard"})
        self.assertEqual(response.status_code, 400)

    def test_invalid_mode(self):
        """Test invalid mode."""
        response = self.client.post("/api/security/roles", json={"mode": "bad"})
        self.assertEqual(response.status_code, 400)

    @patch("app.routers.security.get_role_policy_details")
    def test_list_roles(self, mock_policy):
        """Test listing managed roles."""
        mock_policy.return_value = {"statements": []}

        self.client.post("/api/security/roles", json={
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/role-a",
        })
        self.client.post("/api/security/roles", json={
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/role-b",
        })

        response = self.client.get("/api/security/roles")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    @patch("app.routers.security.get_role_policy_details")
    def test_get_role(self, mock_policy):
        """Test getting a single role."""
        mock_policy.return_value = {"statements": []}

        create_resp = self.client.post("/api/security/roles", json={
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/get-test",
        })
        role_id = create_resp.json()["id"]

        response = self.client.get(f"/api/security/roles/{role_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role_name"], "get-test")

    def test_get_role_not_found(self):
        """Test getting a non-existent role."""
        response = self.client.get("/api/security/roles/999")
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.security.get_role_policy_details")
    @patch("app.routers.security.update_iam_role_policy")
    def test_update_role(self, mock_update, mock_policy):
        """Test updating a role."""
        mock_policy.return_value = {"statements": []}

        create_resp = self.client.post("/api/security/roles", json={
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/upd-test",
        })
        role_id = create_resp.json()["id"]

        new_policy = {"Version": "2012-10-17", "Statement": []}
        response = self.client.put(f"/api/security/roles/{role_id}", json={
            "description": "Updated",
            "policy_document": new_policy,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["description"], "Updated")
        mock_update.assert_called_once()

    def test_update_role_not_found(self):
        """Test updating a non-existent role."""
        response = self.client.put("/api/security/roles/999", json={"description": "x"})
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.security.get_role_policy_details")
    def test_delete_role(self, mock_policy):
        """Test deleting a role."""
        mock_policy.return_value = {"statements": []}

        create_resp = self.client.post("/api/security/roles", json={
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/del-test",
        })
        role_id = create_resp.json()["id"]

        response = self.client.delete(f"/api/security/roles/{role_id}")
        self.assertEqual(response.status_code, 204)

        # Verify gone
        response = self.client.get(f"/api/security/roles/{role_id}")
        self.assertEqual(response.status_code, 404)

    def test_delete_role_not_found(self):
        """Test deleting a non-existent role."""
        response = self.client.delete("/api/security/roles/999")
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.security.get_role_policy_details")
    def test_delete_role_in_use(self, mock_policy):
        """Test deleting a role that is in use by an agent."""
        mock_policy.return_value = {"statements": []}

        role_arn = "arn:aws:iam::123456789012:role/in-use-role"
        create_resp = self.client.post("/api/security/roles", json={
            "mode": "import",
            "role_arn": role_arn,
        })
        role_id = create_resp.json()["id"]

        # Create an agent that uses this role
        from app.models.agent import Agent
        agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent",
            runtime_id="test-agent",
            name="Test Agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            execution_role_arn=role_arn,
        )
        self.session.add(agent)
        self.session.commit()

        response = self.client.delete(f"/api/security/roles/{role_id}")
        self.assertEqual(response.status_code, 409)
        self.assertIn("in use", response.json()["detail"])


class TestSecurityAuthorizers(unittest.TestCase):
    """Test cases for /api/security/authorizers endpoints."""

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

    def test_create_authorizer_basic(self):
        """Test creating a basic authorizer without secret."""
        response = self.client.post("/api/security/authorizers", json={
            "name": "my-cognito",
            "authorizer_type": "cognito",
            "pool_id": "us-east-1_abc123",
            "allowed_clients": ["client1"],
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["name"], "my-cognito")
        self.assertEqual(data["authorizer_type"], "cognito")
        self.assertEqual(data["pool_id"], "us-east-1_abc123")
        self.assertEqual(data["allowed_clients"], ["client1"])
        self.assertFalse(data["has_client_secret"])

    @patch("app.routers.security.boto3")
    def test_create_cognito_authorizer_fetches_tags(self, mock_boto3):
        """Test that creating a Cognito authorizer fetches pool tags."""
        mock_cognito = MagicMock()
        mock_boto3.client.return_value = mock_cognito
        mock_cognito.describe_user_pool.return_value = {
            "UserPool": {
                "UserPoolTags": {
                    "loom:application": "myapp",
                    "loom:owner": "alice",
                }
            }
        }

        response = self.client.post("/api/security/authorizers", json={
            "name": "tagged-cognito",
            "authorizer_type": "cognito",
            "pool_id": "us-east-1_tagged",
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["tags"]["loom:application"], "myapp")
        self.assertEqual(data["tags"]["loom:owner"], "alice")

    def test_create_non_cognito_authorizer_no_tags(self):
        """Test that non-Cognito authorizers get empty tags."""
        response = self.client.post("/api/security/authorizers", json={
            "name": "other-auth",
            "authorizer_type": "other",
            "discovery_url": "https://example.com/.well-known/openid-configuration",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["tags"], {})

    @patch("app.routers.security.store_secret")
    def test_create_authorizer_with_secret(self, mock_store):
        """Test creating an authorizer with a client secret."""
        mock_store.return_value = "arn:aws:secretsmanager:us-east-1:123:secret:test-abc"

        response = self.client.post("/api/security/authorizers", json={
            "name": "secret-auth",
            "authorizer_type": "cognito",
            "client_id": "my-client",
            "client_secret": "super-secret",
        })
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["has_client_secret"])
        mock_store.assert_called_once()

    def test_create_authorizer_duplicate_name(self):
        """Test creating authorizer with duplicate name."""
        self.client.post("/api/security/authorizers", json={
            "name": "dup-auth",
            "authorizer_type": "cognito",
        })
        response = self.client.post("/api/security/authorizers", json={
            "name": "dup-auth",
            "authorizer_type": "other",
        })
        self.assertEqual(response.status_code, 409)

    def test_list_authorizers(self):
        """Test listing authorizers."""
        self.client.post("/api/security/authorizers", json={"name": "auth-a", "authorizer_type": "cognito"})
        self.client.post("/api/security/authorizers", json={"name": "auth-b", "authorizer_type": "other"})

        response = self.client.get("/api/security/authorizers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_get_authorizer(self):
        """Test getting a single authorizer."""
        create_resp = self.client.post("/api/security/authorizers", json={
            "name": "get-auth",
            "authorizer_type": "cognito",
        })
        auth_id = create_resp.json()["id"]

        response = self.client.get(f"/api/security/authorizers/{auth_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "get-auth")

    def test_get_authorizer_not_found(self):
        """Test getting a non-existent authorizer."""
        response = self.client.get("/api/security/authorizers/999")
        self.assertEqual(response.status_code, 404)

    def test_update_authorizer(self):
        """Test updating an authorizer."""
        create_resp = self.client.post("/api/security/authorizers", json={
            "name": "upd-auth",
            "authorizer_type": "cognito",
        })
        auth_id = create_resp.json()["id"]

        response = self.client.put(f"/api/security/authorizers/{auth_id}", json={
            "pool_id": "us-east-1_xyz",
            "allowed_scopes": ["openid"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pool_id"], "us-east-1_xyz")
        self.assertEqual(response.json()["allowed_scopes"], ["openid"])

    def test_update_authorizer_not_found(self):
        """Test updating a non-existent authorizer."""
        response = self.client.put("/api/security/authorizers/999", json={"pool_id": "x"})
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.security.delete_secret")
    @patch("app.routers.security.store_secret")
    def test_delete_authorizer_with_secret(self, mock_store, mock_delete):
        """Test deleting an authorizer cleans up its secret."""
        mock_store.return_value = "arn:aws:secretsmanager:us-east-1:123:secret:test"

        create_resp = self.client.post("/api/security/authorizers", json={
            "name": "del-auth",
            "authorizer_type": "cognito",
            "client_secret": "secret-value",
        })
        auth_id = create_resp.json()["id"]

        response = self.client.delete(f"/api/security/authorizers/{auth_id}")
        self.assertEqual(response.status_code, 204)
        mock_delete.assert_called_once()

    @patch("app.routers.security.delete_secret")
    @patch("app.routers.security.store_secret")
    def test_delete_authorizer_with_credentials(self, mock_store, mock_delete):
        """Test deleting an authorizer also deletes its credentials."""
        mock_store.return_value = "arn:aws:secretsmanager:us-east-1:123:secret:cred"

        create_resp = self.client.post("/api/security/authorizers", json={
            "name": "auth-with-creds",
            "authorizer_type": "cognito",
        })
        auth_id = create_resp.json()["id"]

        # Add a credential with a secret
        self.client.post(f"/api/security/authorizers/{auth_id}/credentials", json={
            "label": "test-cred",
            "client_id": "cid",
            "client_secret": "csecret",
        })

        response = self.client.delete(f"/api/security/authorizers/{auth_id}")
        self.assertEqual(response.status_code, 204)
        mock_delete.assert_called()

    def test_delete_authorizer_not_found(self):
        """Test deleting a non-existent authorizer."""
        response = self.client.delete("/api/security/authorizers/999")
        self.assertEqual(response.status_code, 404)


class TestPermissionRequests(unittest.TestCase):
    """Test cases for /api/security/permission-requests endpoints."""

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

    def _create_role(self) -> int:
        """Helper to create a managed role directly in DB."""
        role = ManagedRole(
            role_name="test-role",
            role_arn="arn:aws:iam::123456789012:role/test-role",
            description="Test role",
            policy_document="{}",
        )
        self.session.add(role)
        self.session.commit()
        self.session.refresh(role)
        return role.id

    def test_create_permission_request(self):
        """Test creating a permission request."""
        role_id = self._create_role()

        response = self.client.post("/api/security/permission-requests", json={
            "managed_role_id": role_id,
            "requested_actions": ["s3:GetObject", "s3:PutObject"],
            "requested_resources": ["arn:aws:s3:::my-bucket/*"],
            "justification": "Need S3 access for data pipeline",
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["managed_role_id"], role_id)
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["requested_actions"], ["s3:GetObject", "s3:PutObject"])
        self.assertEqual(data["justification"], "Need S3 access for data pipeline")

    def test_create_permission_request_invalid_role(self):
        """Test creating a permission request for non-existent role."""
        response = self.client.post("/api/security/permission-requests", json={
            "managed_role_id": 999,
            "requested_actions": ["s3:GetObject"],
            "requested_resources": ["*"],
            "justification": "Test",
        })
        self.assertEqual(response.status_code, 404)

    def test_list_permission_requests(self):
        """Test listing all permission requests."""
        role_id = self._create_role()

        self.client.post("/api/security/permission-requests", json={
            "managed_role_id": role_id,
            "requested_actions": ["s3:GetObject"],
            "requested_resources": ["*"],
            "justification": "Req 1",
        })
        self.client.post("/api/security/permission-requests", json={
            "managed_role_id": role_id,
            "requested_actions": ["dynamodb:Query"],
            "requested_resources": ["*"],
            "justification": "Req 2",
        })

        response = self.client.get("/api/security/permission-requests")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_list_permission_requests_filter_by_status(self):
        """Test listing permission requests filtered by status."""
        role_id = self._create_role()

        self.client.post("/api/security/permission-requests", json={
            "managed_role_id": role_id,
            "requested_actions": ["s3:GetObject"],
            "requested_resources": ["*"],
            "justification": "Pending one",
        })

        response = self.client.get("/api/security/permission-requests?status=pending")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

        response = self.client.get("/api/security/permission-requests?status=approved")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 0)

    @patch("app.routers.security.apply_permissions_to_role")
    def test_approve_permission_request(self, mock_apply):
        """Test approving a permission request."""
        updated_doc = {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": ["*"]}
        ]}
        mock_apply.return_value = updated_doc

        role_id = self._create_role()

        create_resp = self.client.post("/api/security/permission-requests", json={
            "managed_role_id": role_id,
            "requested_actions": ["s3:GetObject"],
            "requested_resources": ["*"],
            "justification": "Need it",
        })
        req_id = create_resp.json()["id"]

        response = self.client.put(f"/api/security/permission-requests/{req_id}", json={
            "status": "approved",
            "reviewer_notes": "LGTM",
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "approved")
        self.assertEqual(data["reviewer_notes"], "LGTM")
        mock_apply.assert_called_once()

    def test_deny_permission_request(self):
        """Test denying a permission request."""
        role_id = self._create_role()

        create_resp = self.client.post("/api/security/permission-requests", json={
            "managed_role_id": role_id,
            "requested_actions": ["iam:*"],
            "requested_resources": ["*"],
            "justification": "Full IAM access",
        })
        req_id = create_resp.json()["id"]

        response = self.client.put(f"/api/security/permission-requests/{req_id}", json={
            "status": "denied",
            "reviewer_notes": "Too broad",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "denied")

    @patch("app.routers.security.apply_permissions_to_role")
    def test_review_already_reviewed(self, mock_apply):
        """Test reviewing a non-pending request fails."""
        mock_apply.return_value = {"Version": "2012-10-17", "Statement": []}
        role_id = self._create_role()

        create_resp = self.client.post("/api/security/permission-requests", json={
            "managed_role_id": role_id,
            "requested_actions": ["s3:GetObject"],
            "requested_resources": ["*"],
            "justification": "Test",
        })
        req_id = create_resp.json()["id"]

        # Approve first
        self.client.put(f"/api/security/permission-requests/{req_id}", json={"status": "approved"})

        # Try to review again
        response = self.client.put(f"/api/security/permission-requests/{req_id}", json={"status": "denied"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("not pending", response.json()["detail"])

    def test_review_not_found(self):
        """Test reviewing a non-existent request."""
        response = self.client.put("/api/security/permission-requests/999", json={"status": "approved"})
        self.assertEqual(response.status_code, 404)

    def test_review_invalid_status(self):
        """Test reviewing with invalid status value."""
        role_id = self._create_role()

        create_resp = self.client.post("/api/security/permission-requests", json={
            "managed_role_id": role_id,
            "requested_actions": ["s3:GetObject"],
            "requested_resources": ["*"],
            "justification": "Test",
        })
        req_id = create_resp.json()["id"]

        response = self.client.put(f"/api/security/permission-requests/{req_id}", json={"status": "maybe"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be 'approved' or 'denied'", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
