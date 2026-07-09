"""Tests for cost dashboard endpoints."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine

client = TestClient(app)


class TestCostDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def test_get_cost_dashboard_returns_expected_fields(self):
        """Cost dashboard returns expected fields including memory cost."""
        with patch("app.dependencies.auth.get_current_user") as mock_user:
            mock_user.return_value = type("UserInfo", (), {
                "sub": "test", "username": "admin", "groups": ["t-admin", "g-admins-super"],
                "scopes": ["catalog:read"],
            })()
            response = client.get("/api/dashboard/costs?days=30")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("total_invocations", data)
            self.assertIn("total_estimated_cost", data)
            self.assertIn("total_compute_cpu_cost", data)
            self.assertIn("total_compute_memory_cost", data)
            self.assertIn("total_idle_cpu_cost", data)
            self.assertIn("total_idle_memory_cost", data)
            self.assertIn("total_stm_cost", data)
            self.assertIn("total_ltm_cost", data)
            self.assertIn("agents", data)
            self.assertIsInstance(data["total_stm_cost"], (int, float))
            self.assertIsInstance(data["total_ltm_cost"], (int, float))

    def test_model_pricing_endpoint(self):
        """Models pricing endpoint returns pricing data."""
        with patch("app.dependencies.auth.get_current_user") as mock_user:
            mock_user.return_value = type("UserInfo", (), {
                "sub": "test", "username": "admin", "groups": ["t-admin", "g-admins-super"],
                "scopes": ["agent:read"],
            })()
            response = client.get("/api/agents/models/pricing")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertGreater(len(data), 0)
            self.assertIn("input_price_per_1k_tokens", data[0])
            self.assertIn("output_price_per_1k_tokens", data[0])
            self.assertIn("pricing_as_of", data[0])


if __name__ == "__main__":
    unittest.main()
