"""CLI wrapper for `app.services.model_catalog_refresh.refresh_models_json`.

Regenerates `etc/models.json` from the curated `etc/bedrock_model_catalog.json`
superset (#64 R2) — see that module's docstring for the filtering rules.
Intended to run as part of the release process (`make refresh-models`); the
admin-triggered on-demand path is `POST /api/settings/models/refresh`.

Usage:
    python scripts/refresh_models_json.py
    python scripts/refresh_models_json.py --lookback-months 12
    python scripts/refresh_models_json.py --skip-live-check --dry-run
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.model_catalog_refresh import (  # noqa: E402
    DEFAULT_CATALOG_PATH,
    DEFAULT_LOOKBACK_MONTHS,
    DEFAULT_OUTPUT_PATH,
    refresh_models_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--lookback-months", type=int, default=DEFAULT_LOOKBACK_MONTHS)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--skip-live-check", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print the summary without writing --output")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    summary = refresh_models_json(
        catalog_path=args.catalog,
        output_path=args.output,
        lookback_months=args.lookback_months,
        region=args.region,
        skip_live_check=args.skip_live_check,
        dry_run=args.dry_run,
    )

    print(f"Cutoff date: {summary['cutoff']} (lookback: {args.lookback_months} months)")
    print(f"Included ({len(summary['included'])}): {', '.join(summary['included'])}")
    if summary["excluded_stale"]:
        print(f"Excluded, launched before cutoff ({len(summary['excluded_stale'])}): {', '.join(summary['excluded_stale'])}")
    if summary["excluded_incomplete"]:
        print(f"Excluded, missing verified pricing/max_tokens ({len(summary['excluded_incomplete'])}): {', '.join(summary['excluded_incomplete'])}")
    if summary["excluded_unavailable"]:
        print(f"Excluded, not live in region {args.region} ({len(summary['excluded_unavailable'])}): {', '.join(summary['excluded_unavailable'])}")

    if not args.dry_run:
        print(f"Wrote {len(summary['included'])} models to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
