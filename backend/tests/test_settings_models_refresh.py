"""Tests for POST /api/settings/models/refresh and the
models_json_lookback_months site setting (#64 R2)."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.dependencies.auth import get_current_user
from app.models.site_setting import SiteSetting


def _admin_user():
    return type("UserInfo", (), {
        "sub": "test", "username": "admin", "groups": ["t-admin", "g-admins-super"],
        "scopes": ["admin:read", "admin:write"],
    })()


class TestModelsJsonRefreshEndpoint(unittest.TestCase):
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

    def _mock_summary(self):
        return {
            "included": ["a", "b"],
            "excluded_stale": ["c"],
            "excluded_incomplete": [],
            "excluded_unavailable": [],
            "cutoff": "2026-03-29",
        }

    def test_default_lookback_is_six_months(self):
        response = self.client.get("/api/settings/site")
        self.assertEqual(response.status_code, 200)
        settings_by_key = {s["key"]: s["value"] for s in response.json()}
        self.assertEqual(settings_by_key["models_json_lookback_months"], "6")

    @patch("app.services.model_catalog_refresh.reload_supported_models")
    @patch("app.services.model_catalog_refresh.refresh_models_json")
    def test_refresh_uses_site_setting_by_default(self, mock_refresh, mock_reload):
        mock_refresh.return_value = self._mock_summary()

        response = self.client.post("/api/settings/models/refresh", json={})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["lookback_months"], 6)
        self.assertEqual(data["included"], ["a", "b"])
        mock_refresh.assert_called_once()
        self.assertEqual(mock_refresh.call_args.kwargs["lookback_months"], 6)
        mock_reload.assert_called_once()

    @patch("app.services.model_catalog_refresh.reload_supported_models")
    @patch("app.services.model_catalog_refresh.refresh_models_json")
    def test_refresh_request_override_beats_site_setting(self, mock_refresh, mock_reload):
        self.session.add(SiteSetting(key="models_json_lookback_months", value="6"))
        self.session.commit()
        mock_refresh.return_value = self._mock_summary()

        response = self.client.post("/api/settings/models/refresh", json={"lookback_months": 24})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lookback_months"], 24)
        self.assertEqual(mock_refresh.call_args.kwargs["lookback_months"], 24)

    def test_configured_lookback_is_respected(self):
        self.session.add(SiteSetting(key="models_json_lookback_months", value="12"))
        self.session.commit()

        with patch("app.services.model_catalog_refresh.reload_supported_models"), \
             patch("app.services.model_catalog_refresh.refresh_models_json") as mock_refresh:
            mock_refresh.return_value = self._mock_summary()
            response = self.client.post("/api/settings/models/refresh", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lookback_months"], 12)
        self.assertEqual(mock_refresh.call_args.kwargs["lookback_months"], 12)


if __name__ == "__main__":
    unittest.main()
