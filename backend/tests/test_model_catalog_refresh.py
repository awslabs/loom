"""Tests for app.services.model_catalog_refresh (#64 R2: filtering the
curated Bedrock model catalog into etc/models.json by lookback window and
pricing completeness)."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.services.model_catalog_refresh import _months_ago, refresh_models_json

CATALOG = [
    {
        "model_id": "recent.priced.model",
        "display_name": "Recent Priced",
        "group": "Test",
        "max_tokens": 8192,
        "input_price_per_1k_tokens": 0.001,
        "output_price_per_1k_tokens": 0.002,
        "launch_date": "2026-08-01",
    },
    {
        "model_id": "stale.priced.model",
        "display_name": "Stale Priced",
        "group": "Test",
        "max_tokens": 8192,
        "input_price_per_1k_tokens": 0.001,
        "output_price_per_1k_tokens": 0.002,
        "launch_date": "2020-01-01",
    },
    {
        "model_id": "unknown.launch.date.model",
        "display_name": "Unknown Launch Date",
        "group": "Test",
        "max_tokens": 8192,
        "input_price_per_1k_tokens": 0.001,
        "output_price_per_1k_tokens": 0.002,
        "launch_date": None,
    },
    {
        "model_id": "recent.unpriced.model",
        "display_name": "Recent Unpriced",
        "group": "Test",
        "max_tokens": None,
        "input_price_per_1k_tokens": None,
        "output_price_per_1k_tokens": None,
        "launch_date": "2026-08-01",
    },
]


class TestMonthsAgo(unittest.TestCase):
    def test_simple_subtraction(self):
        self.assertEqual(_months_ago(date(2026, 9, 29), 6), date(2026, 3, 29))

    def test_year_rollover(self):
        self.assertEqual(_months_ago(date(2026, 2, 15), 6), date(2025, 8, 15))

    def test_clamps_shorter_month(self):
        # Aug 31 - 6 months = Feb 31, which doesn't exist -> Feb 28.
        self.assertEqual(_months_ago(date(2026, 8, 31), 6), date(2026, 2, 28))


class TestRefreshModelsJson(unittest.TestCase):
    def _run(self, lookback_months: int, reference_date: date) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "catalog.json"
            output_path = Path(tmp) / "models.json"
            catalog_path.write_text(json.dumps(CATALOG))

            summary = refresh_models_json(
                catalog_path=catalog_path,
                output_path=output_path,
                lookback_months=lookback_months,
                skip_live_check=True,
                reference_date=reference_date,
            )
            self.assertTrue(output_path.exists())
            written = json.loads(output_path.read_text())
            summary["written_ids"] = [e["model_id"] for e in written]
            return summary

    def test_excludes_models_launched_before_cutoff(self):
        summary = self._run(lookback_months=6, reference_date=date(2026, 9, 29))
        self.assertIn("recent.priced.model", summary["included"])
        self.assertIn("stale.priced.model", summary["excluded_stale"])
        self.assertEqual(summary["included"], summary["written_ids"])

    def test_unknown_launch_date_is_always_included(self):
        summary = self._run(lookback_months=1, reference_date=date(2026, 9, 29))
        self.assertIn("unknown.launch.date.model", summary["included"])

    def test_excludes_models_missing_verified_pricing_even_if_recent(self):
        summary = self._run(lookback_months=6, reference_date=date(2026, 9, 29))
        self.assertIn("recent.unpriced.model", summary["excluded_incomplete"])
        self.assertNotIn("recent.unpriced.model", summary["included"])

    def test_dry_run_does_not_write_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "catalog.json"
            output_path = Path(tmp) / "models.json"
            catalog_path.write_text(json.dumps(CATALOG))

            refresh_models_json(
                catalog_path=catalog_path,
                output_path=output_path,
                lookback_months=6,
                skip_live_check=True,
                reference_date=date(2026, 9, 29),
                dry_run=True,
            )
            self.assertFalse(output_path.exists())

    def test_live_availability_check_drops_unavailable_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "catalog.json"
            output_path = Path(tmp) / "models.json"
            catalog_path.write_text(json.dumps(CATALOG))

            from unittest.mock import patch

            with patch(
                "app.services.model_catalog_refresh._fetch_live_bedrock_model_ids",
                return_value={"recent.priced.model"},
            ):
                summary = refresh_models_json(
                    catalog_path=catalog_path,
                    output_path=output_path,
                    lookback_months=6,
                    skip_live_check=False,
                    reference_date=date(2026, 9, 29),
                )
            self.assertEqual(summary["included"], ["recent.priced.model"])
            self.assertIn("unknown.launch.date.model", summary["excluded_unavailable"])


if __name__ == "__main__":
    unittest.main()
