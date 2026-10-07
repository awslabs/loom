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
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/no-tag-role",
        })

        self.assertEqual(response.status_code, 201)
        data = response.json()
        # A failed AWS tag fetch is non-fatal: the import still succeeds and the
        # caller's profile tags are kept. (Tags are required now, so the old
        # expectation of an empty dict is no longer reachable.)
        self.assertEqual(data["tags"], {"loom:group": "demo"})

    def test_register_role_missing_arn(self):
        """role_arn is a required field now that there is no create mode, so
        this is schema validation (422) rather than a handler check (400)."""
        response = self.client.post("/api/security/roles", json={})
        self.assertEqual(response.status_code, 422)

    @patch("app.routers.security.get_role_policy_details")
    def test_import_role_duplicate(self, mock_policy):
        """Test importing the same role twice."""
        mock_policy.return_value = {"statements": []}
        arn = "arn:aws:iam::123456789012:role/dup-role"

        self.client.post("/api/security/roles", json={"mode": "import", "role_arn": arn, "tags": {"loom:group": "demo"}})
        response = self.client.post("/api/security/roles", json={"mode": "import", "role_arn": arn, "tags": {"loom:group": "demo"}})
        self.assertEqual(response.status_code, 409)


    def test_mode_field_is_gone(self):
        """`mode` selected between import and wizard. Wizard created an IAM
        role, which Loom can no longer do, so the field was removed — an
        unknown key is ignored and role_arn is what matters."""
        response = self.client.post("/api/security/roles", json={"mode": "wizard"})
        self.assertEqual(response.status_code, 422)

    @patch("app.routers.security.get_role_policy_details")
    def test_list_roles(self, mock_policy):
        """Test listing managed roles."""
        mock_policy.return_value = {"statements": []}

        self.client.post("/api/security/roles", json={
            "tags": {"loom:group": "demo"},
            "mode": "import",
            "role_arn": "arn:aws:iam::123456789012:role/role-a",
        })
        self.client.post("/api/security/roles", json={
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
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


    def test_update_role_not_found(self):
        """Test updating a non-existent role."""
        response = self.client.put("/api/security/roles/999", json={"description": "x"})
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.security.get_role_policy_details")
    def test_delete_role(self, mock_policy):
        """Test deleting a role."""
        mock_policy.return_value = {"statements": []}

        create_resp = self.client.post("/api/security/roles", json={
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
            "name": "tagged-cognito",
            "authorizer_type": "cognito",
            "pool_id": "us-east-1_tagged",
        })
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["tags"]["loom:application"], "myapp")
        self.assertEqual(data["tags"]["loom:owner"], "alice")

    def test_create_non_cognito_authorizer_merges_no_aws_tags(self):
        """A non-Cognito authorizer has no user pool to read tags from, so the
        stored tags are exactly the caller's profile — nothing is merged in.
        (Tags themselves are now required, so "empty" is no longer reachable.)"""
        response = self.client.post("/api/security/authorizers", json={
            "tags": {"loom:group": "demo"},
            "name": "other-auth",
            "authorizer_type": "other",
            "discovery_url": "https://example.com/.well-known/openid-configuration",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["tags"], {"loom:group": "demo"})

    @patch("app.routers.security.store_secret")
    def test_create_authorizer_with_secret(self, mock_store):
        """Test creating an authorizer with a client secret."""
        mock_store.return_value = "arn:aws:secretsmanager:us-east-1:123:secret:test-abc"

        response = self.client.post("/api/security/authorizers", json={
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
            "name": "dup-auth",
            "authorizer_type": "cognito",
        })
        response = self.client.post("/api/security/authorizers", json={
            "tags": {"loom:group": "demo"},
            "name": "dup-auth",
            "authorizer_type": "other",
        })
        self.assertEqual(response.status_code, 409)

    def test_list_authorizers(self):
        """Test listing authorizers."""
        self.client.post("/api/security/authorizers", json={"name": "auth-a", "authorizer_type": "cognito", "tags": {"loom:group": "demo"}})
        self.client.post("/api/security/authorizers", json={"name": "auth-b", "authorizer_type": "other", "tags": {"loom:group": "demo"}})

        response = self.client.get("/api/security/authorizers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_get_authorizer(self):
        """Test getting a single authorizer."""
        create_resp = self.client.post("/api/security/authorizers", json={
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
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
            "tags": {"loom:group": "demo"},
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


if __name__ == "__main__":
    unittest.main()
