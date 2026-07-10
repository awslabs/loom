"""Tests for /api/settings/litellm-proxy endpoints."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import get_current_user


def _admin_user():
    return type("UserInfo", (), {
        "sub": "test", "username": "admin", "groups": ["t-admin", "g-admins-super"],
        "scopes": ["settings:read", "settings:write"],
    })()


class TestLitellmProxySettingsEndpoints(unittest.TestCase):
    """Test cases for /api/settings/litellm-proxy endpoints."""

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
        app.dependency_overrides.pop(get_current_user, None)
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def test_get_default_config(self):
        with patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": ""}):
            response = self.client.get("/api/settings/litellm-proxy")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["enabled"])
        self.assertEqual(data["base_url"], "")
        self.assertEqual(data["discovery_base_url"], "")
        self.assertFalse(data["has_master_key"])

    @patch("app.services.secrets.store_secret")
    def test_update_sets_base_url_and_master_key(self, mock_store_secret):
        mock_store_secret.return_value = "arn:aws:secretsmanager:us-east-1:123:secret:loom/settings/litellm-master-key"

        with patch("app.services.secrets.get_secret", return_value="sk-master"):
            response = self.client.put(
                "/api/settings/litellm-proxy",
                json={
                    "enabled": True,
                    "base_url": "https://proxy.example.com",
                    "discovery_base_url": "http://localhost:4000",
                    "master_key": "sk-master",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["base_url"], "https://proxy.example.com")
        self.assertEqual(data["discovery_base_url"], "http://localhost:4000")
        self.assertTrue(data["has_master_key"])
        mock_store_secret.assert_called_once()
        call_kwargs = mock_store_secret.call_args.kwargs
        self.assertEqual(call_kwargs["name"], "loom/settings/litellm-master-key")
        self.assertEqual(call_kwargs["secret_value"], "sk-master")

        from app.models.site_setting import SiteSetting
        row = self.session.query(SiteSetting).filter(SiteSetting.key == "litellm_proxy_base_url").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.value, "https://proxy.example.com")
        enabled_row = self.session.query(SiteSetting).filter(SiteSetting.key == "litellm_enabled").first()
        self.assertEqual(enabled_row.value, "true")
        discovery_row = self.session.query(SiteSetting).filter(SiteSetting.key == "litellm_discovery_base_url").first()
        self.assertEqual(discovery_row.value, "http://localhost:4000")

    @patch("app.services.secrets.store_secret")
    def test_update_without_master_key_does_not_write_secret(self, mock_store_secret):
        with patch("app.services.secrets.get_secret", side_effect=Exception("not found")):
            response = self.client.put(
                "/api/settings/litellm-proxy",
                json={"enabled": True, "base_url": "https://proxy.example.com"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["base_url"], "https://proxy.example.com")
        self.assertFalse(data["has_master_key"])
        mock_store_secret.assert_not_called()

    @patch("app.services.secrets.store_secret")
    def test_disabling_gates_config_resolution(self, mock_store_secret):
        with patch("app.services.secrets.get_secret", return_value="sk-master"):
            self.client.put(
                "/api/settings/litellm-proxy",
                json={"enabled": True, "base_url": "https://proxy.example.com", "master_key": "sk-master"},
            )
            response = self.client.put(
                "/api/settings/litellm-proxy",
                json={"enabled": False, "base_url": "https://proxy.example.com"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])

        from app.services.litellm import get_litellm_proxy_config
        with patch.dict("os.environ", {"LOOM_LITELLM_PROXY_BASE_URL": ""}):
            self.assertIsNone(get_litellm_proxy_config(self.session))


if __name__ == "__main__":
    unittest.main()
