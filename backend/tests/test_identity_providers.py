"""Tests for identity provider management, OIDC discovery, JWT validation, and group mapping."""
import io
import json
import time
import unittest
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from jwt import algorithms as jwt_algorithms
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import jwt

from app.db import Base, get_db
from app.main import app
from app.models.identity_provider import IdentityProvider
from app.models.authorizer_config import AuthorizerConfig
from app.models.authorizer_credential import AuthorizerCredential
from app.dependencies.auth import _map_external_groups, derive_scopes
from app.services.oidc import fetch_discovery, OIDCDiscoveryError
from app.services.jwt_validator import validate_token, _jwks_cache


# ---------------------------------------------------------------------------
# Helpers: RSA key generation and JWT creation
# ---------------------------------------------------------------------------

def _generate_rsa_keypair():
    """Generate an RSA private key and return (private_key, public_key) objects."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _public_key_to_jwks(public_key, kid: str = "test-kid-1") -> dict:
    """Convert an RSA public key to a JWKS dict suitable for jwt_validator._get_jwks."""
    pub_numbers = public_key.public_numbers()
    # Use PyJWT's RSAAlgorithm to produce the JWK dict
    jwk_dict = json.loads(jwt_algorithms.RSAAlgorithm.to_jwk(public_key))
    jwk_dict["kid"] = kid
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "RS256"
    return {"keys": [jwk_dict]}


def _make_token(private_key, claims: dict, kid: str = "test-kid-1") -> str:
    """Create an RS256 JWT signed with the given private key."""
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


# ---------------------------------------------------------------------------
# Fake urllib response helper
# ---------------------------------------------------------------------------

def _fake_urlopen_response(body: dict):
    """Return a context-manager-compatible mock that mimics urllib.request.urlopen."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(body).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ===================================================================
# 1) OIDC Discovery tests
# ===================================================================

class TestOIDCDiscovery(unittest.TestCase):
    """Tests for app.services.oidc.fetch_discovery."""

    DISCOVERY_DOC = {
        "issuer": "https://idp.example.com",
        "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
        "authorization_endpoint": "https://idp.example.com/authorize",
        "token_endpoint": "https://idp.example.com/oauth2/token",
        "scopes_supported": ["openid", "profile", "email"],
    }

    @patch("app.services.oidc.urllib.request.urlopen")
    def test_fetch_discovery_success(self, mock_urlopen):
        mock_urlopen.return_value = _fake_urlopen_response(self.DISCOVERY_DOC)
        result = fetch_discovery("https://idp.example.com")
        self.assertEqual(result["jwks_uri"], self.DISCOVERY_DOC["jwks_uri"])
        self.assertEqual(result["authorization_endpoint"], self.DISCOVERY_DOC["authorization_endpoint"])
        self.assertEqual(result["token_endpoint"], self.DISCOVERY_DOC["token_endpoint"])
        self.assertEqual(result["scopes_supported"], ["openid", "profile", "email"])
        self.assertEqual(result["issuer"], "https://idp.example.com")

    @patch("app.services.oidc.urllib.request.urlopen")
    def test_fetch_discovery_unreachable(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionError("Connection refused")
        with self.assertRaises(OIDCDiscoveryError) as ctx:
            fetch_discovery("https://unreachable.example.com")
        self.assertIn("Failed to fetch discovery document", str(ctx.exception))

    @patch("app.services.oidc.urllib.request.urlopen")
    def test_fetch_discovery_missing_fields(self, mock_urlopen):
        incomplete_doc = {"issuer": "https://idp.example.com"}
        mock_urlopen.return_value = _fake_urlopen_response(incomplete_doc)
        with self.assertRaises(OIDCDiscoveryError) as ctx:
            fetch_discovery("https://idp.example.com")
        self.assertIn("missing required fields", str(ctx.exception))


# ===================================================================
# 2) Generic JWT Validation tests
# ===================================================================

class TestJWTValidation(unittest.TestCase):
    """Tests for app.services.jwt_validator.validate_token."""

    @classmethod
    def setUpClass(cls):
        cls.private_key, cls.public_key = _generate_rsa_keypair()
        cls.jwks = _public_key_to_jwks(cls.public_key)

    def setUp(self):
        # Clear JWKS cache between tests
        _jwks_cache.clear()

    @patch("app.services.jwt_validator._get_jwks")
    def test_validate_token_success(self, mock_get_jwks):
        mock_get_jwks.return_value = self.jwks
        claims = {
            "sub": "user-123",
            "iss": "https://idp.example.com",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "groups": ["Engineers"],
        }
        token = _make_token(self.private_key, claims)
        result = validate_token(token, "https://idp.example.com/.well-known/jwks.json", "https://idp.example.com")
        self.assertEqual(result["sub"], "user-123")
        self.assertEqual(result["groups"], ["Engineers"])

    @patch("app.services.jwt_validator._get_jwks")
    def test_validate_token_wrong_issuer(self, mock_get_jwks):
        mock_get_jwks.return_value = self.jwks
        claims = {
            "sub": "user-123",
            "iss": "https://wrong-issuer.com",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(self.private_key, claims)
        with self.assertRaises(Exception):
            validate_token(token, "https://idp.example.com/.well-known/jwks.json", "https://idp.example.com")

    @patch("app.services.jwt_validator._get_jwks")
    def test_validate_token_expired(self, mock_get_jwks):
        mock_get_jwks.return_value = self.jwks
        claims = {
            "sub": "user-123",
            "iss": "https://idp.example.com",
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,
        }
        token = _make_token(self.private_key, claims)
        with self.assertRaises(jwt.ExpiredSignatureError):
            validate_token(token, "https://idp.example.com/.well-known/jwks.json", "https://idp.example.com")


# ===================================================================
# 3) Group mapping tests
# ===================================================================

class TestGroupMapping(unittest.TestCase):
    """Tests for _map_external_groups and derive_scopes."""

    def test_map_external_groups_basic(self):
        mappings = {
            "EntraAdmins": ["t-admin", "g-admins-super"],
            "EntraUsers": ["t-user", "g-users-demo"],
        }
        result = _map_external_groups(["EntraAdmins"], mappings)
        self.assertEqual(result, ["t-admin", "g-admins-super"])

    def test_map_external_groups_multiple(self):
        mappings = {
            "EntraAdmins": ["t-admin", "g-admins-super"],
            "EntraUsers": ["t-user", "g-users-demo"],
        }
        result = _map_external_groups(["EntraAdmins", "EntraUsers"], mappings)
        self.assertIn("t-admin", result)
        self.assertIn("g-admins-super", result)
        self.assertIn("t-user", result)
        self.assertIn("g-users-demo", result)

    def test_map_external_groups_unknown_group(self):
        mappings = {"KnownGroup": ["t-admin"]}
        result = _map_external_groups(["UnknownGroup"], mappings)
        self.assertEqual(result, [])

    def test_map_external_groups_deduplicates(self):
        mappings = {
            "GroupA": ["t-admin", "g-admins-super"],
            "GroupB": ["t-admin", "g-admins-demo"],
        }
        result = _map_external_groups(["GroupA", "GroupB"], mappings)
        # t-admin should appear only once
        self.assertEqual(result.count("t-admin"), 1)

    def test_derive_scopes_admin_super(self):
        scopes = derive_scopes(["t-admin", "g-admins-super"])
        self.assertIn("agent:read", scopes)
        self.assertIn("agent:write", scopes)
        self.assertIn("admin:read", scopes)
        self.assertIn("invoke", scopes)

    def test_derive_scopes_user(self):
        scopes = derive_scopes(["t-user", "g-users-demo"])
        self.assertIn("agent:read", scopes)
        self.assertIn("invoke", scopes)
        self.assertNotIn("admin:read", scopes)
        self.assertNotIn("security:write", scopes)


# ===================================================================
# 4) Identity Provider CRUD tests (via TestClient)
# ===================================================================

MOCK_DISCOVERY = {
    "jwks_uri": "https://idp.example.com/.well-known/jwks.json",
    "authorization_endpoint": "https://idp.example.com/authorize",
    "token_endpoint": "https://idp.example.com/oauth2/token",
    "scopes_supported": ["openid", "profile"],
    "issuer": "https://idp.example.com",
}


@patch.dict("os.environ", {"LOOM_COGNITO_USER_POOL_ID": ""})
class TestIdentityProviderCRUD(unittest.TestCase):
    """CRUD tests for /api/settings/identity-providers."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

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
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)

    def _idp_payload(self, **overrides) -> dict:
        defaults = {
            "name": "test-azure-ad",
            "provider_type": "entra_id",
            "issuer_url": "https://login.microsoftonline.com/tenant-id/v2.0",
            "client_id": "app-client-id",
            "client_secret": "super-secret",
            "scopes": "openid profile",
            "group_claim_path": "groups",
            "group_mappings": {"EntraAdmins": ["t-admin", "g-admins-super"]},
            "status": "active",
        }
        defaults.update(overrides)
        return defaults

    @patch("app.routers.identity_providers.delete_secret")
    @patch("app.routers.identity_providers.store_secret", return_value="arn:aws:secretsmanager:us-east-1:123456789012:secret:test")
    @patch("app.routers.identity_providers.fetch_discovery", return_value=MOCK_DISCOVERY)
    def test_create_idp(self, mock_disc, mock_store, mock_del):
        resp = self.client.post("/api/settings/identity-providers", json=self._idp_payload())
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["name"], "test-azure-ad")
        self.assertEqual(data["provider_type"], "entra_id")
        self.assertEqual(data["jwks_uri"], MOCK_DISCOVERY["jwks_uri"])
        self.assertTrue(data["has_client_secret"])
        mock_disc.assert_called_once()
        mock_store.assert_called_once()

    @patch("app.routers.identity_providers.delete_secret")
    @patch("app.routers.identity_providers.store_secret", return_value="arn:aws:secretsmanager:us-east-1:123456789012:secret:test")
    @patch("app.routers.identity_providers.fetch_discovery", return_value=MOCK_DISCOVERY)
    def test_list_and_get_idp(self, mock_disc, mock_store, mock_del):
        self.client.post("/api/settings/identity-providers", json=self._idp_payload())

        # List
        resp = self.client.get("/api/settings/identity-providers")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "test-azure-ad")

        # Get by id
        idp_id = items[0]["id"]
        resp = self.client.get(f"/api/settings/identity-providers/{idp_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], idp_id)

    @patch("app.routers.identity_providers.delete_secret")
    @patch("app.routers.identity_providers.store_secret", return_value="arn:aws:secretsmanager:us-east-1:123456789012:secret:test")
    @patch("app.routers.identity_providers.fetch_discovery", return_value=MOCK_DISCOVERY)
    def test_update_idp(self, mock_disc, mock_store, mock_del):
        resp = self.client.post("/api/settings/identity-providers", json=self._idp_payload())
        idp_id = resp.json()["id"]

        resp = self.client.put(f"/api/settings/identity-providers/{idp_id}", json={"name": "renamed-idp"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "renamed-idp")

    @patch("app.routers.identity_providers.delete_secret")
    @patch("app.routers.identity_providers.store_secret", return_value="arn:aws:secretsmanager:us-east-1:123456789012:secret:test")
    @patch("app.routers.identity_providers.fetch_discovery", return_value=MOCK_DISCOVERY)
    def test_delete_idp(self, mock_disc, mock_store, mock_del):
        resp = self.client.post("/api/settings/identity-providers", json=self._idp_payload())
        idp_id = resp.json()["id"]

        resp = self.client.delete(f"/api/settings/identity-providers/{idp_id}")
        self.assertEqual(resp.status_code, 204)
        mock_del.assert_called_once()

        # Verify it is gone
        resp = self.client.get(f"/api/settings/identity-providers/{idp_id}")
        self.assertEqual(resp.status_code, 404)

    @patch("app.routers.identity_providers.delete_secret")
    @patch("app.routers.identity_providers.store_secret", return_value="arn:aws:secretsmanager:us-east-1:123456789012:secret:test")
    @patch("app.routers.identity_providers.fetch_discovery", return_value=MOCK_DISCOVERY)
    def test_only_one_active_idp(self, mock_disc, mock_store, mock_del):
        """Creating a second active IdP should deactivate the first."""
        self.client.post("/api/settings/identity-providers", json=self._idp_payload(name="idp-1", status="active"))
        self.client.post("/api/settings/identity-providers", json=self._idp_payload(name="idp-2", status="active"))

        resp = self.client.get("/api/settings/identity-providers")
        items = resp.json()
        active = [i for i in items if i["status"] == "active"]
        inactive = [i for i in items if i["status"] == "inactive"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["name"], "idp-2")
        self.assertEqual(len(inactive), 1)
        self.assertEqual(inactive[0]["name"], "idp-1")

    @patch("app.routers.identity_providers.fetch_discovery", side_effect=OIDCDiscoveryError("unreachable"))
    def test_create_idp_discovery_failure(self, mock_disc):
        resp = self.client.post("/api/settings/identity-providers", json=self._idp_payload(client_secret=None))
        self.assertEqual(resp.status_code, 422)
        self.assertIn("unreachable", resp.json()["detail"])


# ===================================================================
# 5) Auth Config endpoint tests
# ===================================================================

@patch.dict("os.environ", {"LOOM_COGNITO_USER_POOL_ID": "", "AWS_REGION": "us-west-2"})
class TestAuthConfigEndpoint(unittest.TestCase):
    """Tests for GET /api/auth/config."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

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
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)

    @patch("app.db.SessionLocal")
    def test_auth_config_fallback_to_cognito(self, mock_session_local):
        """When no active IdP exists, should return cognito fallback."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_session_local.return_value = mock_db
        resp = self.client.get("/api/auth/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["provider_type"], "cognito")
        self.assertEqual(data["region"], "us-west-2")

    @patch("app.db.SessionLocal")
    def test_auth_config_active_idp(self, mock_session_local):
        """When an active IdP exists, should return its config."""
        mock_idp = MagicMock()
        mock_idp.provider_type = "entra_id"
        mock_idp.authorization_endpoint = "https://login.microsoftonline.com/authorize"
        mock_idp.token_endpoint = "https://login.microsoftonline.com/token"  # nosec B105
        mock_idp.client_id = "my-client"
        mock_idp.scopes = "openid profile"
        mock_idp.issuer_url = "https://login.microsoftonline.com/tenant/v2.0"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_idp
        mock_session_local.return_value = mock_db

        resp = self.client.get("/api/auth/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["provider_type"], "entra_id")
        self.assertEqual(data["client_id"], "my-client")
        self.assertEqual(data["authorization_endpoint"], "https://login.microsoftonline.com/authorize")
        self.assertEqual(data["token_endpoint"], "https://login.microsoftonline.com/token")


# ===================================================================
# 6) Generic token endpoint tests
# ===================================================================

@patch.dict("os.environ", {"LOOM_COGNITO_USER_POOL_ID": ""})
class TestGenericTokenEndpoint(unittest.TestCase):
    """Tests for POST /api/security/authorizers/{id}/credentials/{id}/token with non-cognito authorizer."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

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
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.engine)

    def _create_authorizer_and_credential(self) -> tuple[int, int]:
        auth = AuthorizerConfig(
            name="oidc-auth",
            authorizer_type="custom",
            discovery_url="https://idp.example.com",
            allowed_scopes=json.dumps(["api"]),
        )
        self.session.add(auth)
        self.session.commit()
        self.session.refresh(auth)

        cred = AuthorizerCredential(
            authorizer_config_id=auth.id,
            label="test-cred",
            client_id="cred-client-id",
            client_secret_arn="arn:aws:secretsmanager:us-east-1:000000000000:secret:test-cred-secret",  # nosec B106
        )
        self.session.add(cred)
        self.session.commit()
        self.session.refresh(cred)
        return auth.id, cred.id

    @patch("app.routers.security.get_secret", return_value="the-client-secret")
    @patch("app.services.token.urllib.request.urlopen")
    @patch("app.services.token.fetch_discovery", return_value=MOCK_DISCOVERY)
    def test_generic_token_success(self, mock_disc, mock_urlopen, mock_get_secret):
        auth_id, cred_id = self._create_authorizer_and_credential()
        token_response_body = {
            "access_token": "eyJhbGciOi...",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_urlopen.return_value = _fake_urlopen_response(token_response_body)

        resp = self.client.post(f"/api/security/authorizers/{auth_id}/credentials/{cred_id}/token")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["access_token"], "eyJhbGciOi...")
        self.assertEqual(data["token_type"], "Bearer")
        self.assertEqual(data["expires_in"], 3600)
        mock_get_secret.assert_called_once()
        mock_disc.assert_called_once_with("https://idp.example.com")

    @patch("app.routers.security.get_secret", return_value="the-client-secret")
    @patch("app.services.token.urllib.request.urlopen", side_effect=ConnectionError("refused"))
    @patch("app.services.token.fetch_discovery", return_value=MOCK_DISCOVERY)
    def test_generic_token_provider_error(self, mock_disc, mock_urlopen, mock_get_secret):
        auth_id, cred_id = self._create_authorizer_and_credential()
        resp = self.client.post(f"/api/security/authorizers/{auth_id}/credentials/{cred_id}/token")
        self.assertEqual(resp.status_code, 502)
        self.assertIn("Failed to get token", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
