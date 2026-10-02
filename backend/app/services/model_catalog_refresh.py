"""Regenerate `etc/models.json` from the curated `etc/bedrock_model_catalog.json`.

Part of GitHub issue #64 (R2). `etc/models.json` is the file
`app.routers.agents.SUPPORTED_MODELS` actually loads to populate model
pickers and pricing. `etc/bedrock_model_catalog.json` is the full curated
superset of known Bedrock models — including ones too old, or too new/
unpriced, to serve by default — maintained by engineers as new Bedrock
models ship (endpoint/API support has to be read off each model's AWS
documentation page; there is no API that returns it).

This filters that superset down to `models.json` by two rules:
  1. Recency: a model is included only if it launched within the lookback
     window (`lookback_months`, default 6 — admin-configurable via the
     `models_json_lookback_months` site setting, see `app.routers.settings`).
     A catalog entry with no `launch_date` (unknown) is always included
     rather than guessed away.
  2. Completeness: a model is included only if it has verified `max_tokens`
     and both per-1k-token prices. Bedrock doesn't publish per-token
     pricing via any API, so this data is manually curated — entries
     missing it are excluded (not zero-filled) until an engineer adds
     verified numbers to the catalog.

Optionally cross-checks each candidate against live Bedrock model/
inference-profile availability in the target region (`ListFoundationModels`
/ `ListInferenceProfiles`) and drops anything no longer actually offered
there. This check is best-effort: any failure (missing credentials, no
network, throttling) is logged and skipped rather than failing the run.

Used by both `scripts/refresh_models_json.py` (CLI / release step) and
`POST /api/settings/models/refresh` (on-demand admin trigger).
"""
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ETC_DIR = Path(__file__).resolve().parent.parent.parent / "etc"
DEFAULT_CATALOG_PATH = ETC_DIR / "bedrock_model_catalog.json"
DEFAULT_OUTPUT_PATH = ETC_DIR / "models.json"

DEFAULT_LOOKBACK_MONTHS = 6


def _months_ago(reference: date, months: int) -> date:
    """Subtract `months` months from `reference`, clamping the day if the
    target month is shorter (e.g. Aug 31 - 6 months -> Feb 28/29)."""
    year = reference.year
    month = reference.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = reference.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def _parse_launch_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _fetch_live_bedrock_model_ids(region: str) -> set[str] | None:
    """Best-effort live check: returns the set of model/inference-profile
    IDs Bedrock currently reports for `region`, or None if the check could
    not be performed (missing creds, network error, etc.)."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        logger.warning("boto3 not available; skipping live availability check")
        return None

    try:
        client = boto3.client("bedrock", region_name=region)
        model_ids: set[str] = set()

        for page in client.get_paginator("list_foundation_models").paginate():
            for summary in page.get("modelSummaries", []):
                if summary.get("modelId"):
                    model_ids.add(summary["modelId"])

        for page in client.get_paginator("list_inference_profiles").paginate():
            for summary in page.get("inferenceProfileSummaries", []):
                if summary.get("inferenceProfileId"):
                    model_ids.add(summary["inferenceProfileId"])

        return model_ids
    except (BotoCoreError, ClientError) as exc:
        logger.warning("Live Bedrock availability check failed, skipping: %s", exc)
        return None


def _all_model_ids(entry: dict[str, Any]) -> list[str]:
    """Every model-ID form a catalog entry might be invoked under, across
    all of its supported endpoints (see `endpoint_model_ids` for per-
    endpoint overrides, e.g. gpt-oss-120b's mantle ID drops its `-1:0`
    runtime suffix)."""
    ids = [entry["model_id"]]
    ids.extend((entry.get("endpoint_model_ids") or {}).values())
    return ids


def refresh_models_json(
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    lookback_months: int = DEFAULT_LOOKBACK_MONTHS,
    region: str = "us-east-1",
    skip_live_check: bool = False,
    reference_date: date | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Filter the curated catalog into `output_path` (unless `dry_run`) and
    return a summary dict: {"included": [...], "excluded_stale": [...],
    "excluded_incomplete": [...], "excluded_unavailable": [...], "cutoff": "..."}."""
    with open(catalog_path) as f:
        catalog: list[dict[str, Any]] = json.load(f)

    cutoff = _months_ago(reference_date or date.today(), lookback_months)
    live_ids = None if skip_live_check else _fetch_live_bedrock_model_ids(region)

    included: list[dict[str, Any]] = []
    excluded_stale: list[str] = []
    excluded_incomplete: list[str] = []
    excluded_unavailable: list[str] = []

    for entry in catalog:
        model_id = entry["model_id"]

        launch_date = _parse_launch_date(entry.get("launch_date"))
        if launch_date is not None and launch_date < cutoff:
            excluded_stale.append(model_id)
            continue

        if (
            entry.get("max_tokens") is None
            or entry.get("input_price_per_1k_tokens") is None
            or entry.get("output_price_per_1k_tokens") is None
        ):
            excluded_incomplete.append(model_id)
            continue

        if live_ids is not None and not any(mid in live_ids for mid in _all_model_ids(entry)):
            excluded_unavailable.append(model_id)
            continue

        included.append(entry)

    included.sort(key=lambda e: (e.get("group") or "", e.get("display_name") or ""))

    if not dry_run:
        with open(output_path, "w") as f:
            json.dump(included, f, indent=2)
            f.write("\n")

    return {
        "included": [e["model_id"] for e in included],
        "excluded_stale": excluded_stale,
        "excluded_incomplete": excluded_incomplete,
        "excluded_unavailable": excluded_unavailable,
        "cutoff": cutoff.isoformat(),
    }


def reload_supported_models() -> list[dict[str, Any]]:
    """Re-read `etc/models.json` from disk and push it into
    `app.routers.agents.SUPPORTED_MODELS` — `refresh_models_json` only
    rewrites the file; without this, the running process would keep
    serving the load-once-at-import snapshot until restarted."""
    import app.routers.agents as agents_module  # local import: avoids a circular import at module load time

    models = agents_module._load_models()
    agents_module.SUPPORTED_MODELS = models
    return models
