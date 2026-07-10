"""
Dynamic model catalog: merges the static model list with live Bedrock
availability and live LiteLLM pricing data.

The static `models.json` list stays the source of truth for curated fields
(display_name, group, max_tokens defaults). This module enriches each known
entry at request time with:
  - `available`: whether Bedrock currently exposes the model/inference
    profile in the configured region (True/False), or None if the live
    check could not be performed.
  - `pricing_source` / `pricing_fetched_at`: whether pricing came from the
    live LiteLLM pricing JSON or fell back to the static file.

Both live fetches fail independently and gracefully — a failure in one
never blanks out the other, and if both fail the static list is returned
unchanged.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

_REGION_PREFIXES = ("us.", "eu.", "apac.", "bedrock/")

# Bedrock model labs surfaced in the dynamic catalog. Keys are the normalized
# model-id prefix Bedrock uses (e.g. "anthropic.claude-..." -> "anthropic");
# values are the display name used for auto-generated (uncurated) entries'
# `group` field.
_ALLOWED_BEDROCK_LABS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "amazon": "Amazon",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "zai": "Z.AI",
}

# Manual overrides for model IDs that _normalize_model_id can't reconcile
# between the static models.json IDs, Bedrock's IDs, and LiteLLM's pricing
# JSON keys. Keys and values are both normalized (post-_normalize_model_id).
_ALIAS_OVERRIDES: dict[str, str] = {}

_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}
_cache_lock = threading.Lock()

_litellm_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}
_litellm_cache_lock = threading.Lock()


def _normalize_model_id(model_id: str) -> str:
    """Normalize a model ID for cross-source matching.

    Strips a leading `bedrock/` prefix and region prefixes (`us.`, `eu.`,
    `apac.`), then lowercases. E.g. "us.anthropic.claude-sonnet-4-6" and
    "bedrock/anthropic.claude-sonnet-4-6" both normalize to
    "anthropic.claude-sonnet-4-6".
    """
    normalized = model_id.strip().lower()
    changed = True
    while changed:
        changed = False
        for prefix in _REGION_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                changed = True
    return _ALIAS_OVERRIDES.get(normalized, normalized)


def _fetch_bedrock_availability(region: str) -> set[str] | None:
    """Return the set of normalized Anthropic model IDs available in Bedrock.

    Combines list_foundation_models(byProvider="Anthropic") with
    list_inference_profiles() so cross-region inference profile IDs
    (e.g. "us.anthropic.claude-sonnet-4-6") are recognized as available too.

    Returns None (not an empty set) if the live check could not be
    performed, so callers can distinguish "confirmed unavailable" from
    "unknown due to error".
    """
    import boto3

    try:
        client = boto3.client("bedrock", region_name=region)
        available: set[str] = set()

        for summary in client.list_foundation_models(byProvider="Anthropic").get(
            "modelSummaries", []
        ):
            model_id = summary.get("modelId")
            if model_id:
                available.add(_normalize_model_id(model_id))

        next_token = None
        while True:
            params: dict[str, Any] = {"maxResults": 100}
            if next_token:
                params["nextToken"] = next_token
            response = client.list_inference_profiles(**params)
            for profile in response.get("inferenceProfileSummaries", []):
                profile_id = profile.get("inferenceProfileId")
                if profile_id:
                    available.add(_normalize_model_id(profile_id))
            next_token = response.get("nextToken")
            if not next_token:
                break

        return available
    except Exception:
        logger.warning("Failed to fetch Bedrock model availability", exc_info=True)
        return None


def _bedrock_lab(normalized_id: str) -> str | None:
    """Return the lab key (e.g. "anthropic") for a normalized model id, or
    None if it's not from an allowed lab (see _ALLOWED_BEDROCK_LABS)."""
    prefix = normalized_id.split(".", 1)[0]
    return prefix if prefix in _ALLOWED_BEDROCK_LABS else None


def _fetch_bedrock_catalog(region: str) -> dict[str, dict[str, Any]] | None:
    """Return live Bedrock model metadata keyed by normalized id, restricted
    to _ALLOWED_BEDROCK_LABS (Anthropic, OpenAI, Amazon, DeepSeek, Qwen,
    Z.AI) — Bedrock also hosts many other labs (Meta, Mistral, Cohere,
    AI21, Stability, etc.) that this app doesn't curate for.

    Companion to _fetch_bedrock_availability — captures modelId/modelName
    (and inference profile id/name) so a Bedrock model not yet curated in
    the static models.json can still be listed with a reasonable display
    name. Inference profile entries win over foundation-model entries for
    the same normalized id, since the profile id (e.g.
    "us.anthropic.claude-sonnet-4-6") is what curated entries use and what's
    typically invocable with cross-region routing enabled.

    Returns None if the live check could not be performed.
    """
    import boto3

    try:
        client = boto3.client("bedrock", region_name=region)
        catalog: dict[str, dict[str, Any]] = {}

        for summary in client.list_foundation_models().get("modelSummaries", []):
            model_id = summary.get("modelId")
            if not model_id:
                continue
            normalized = _normalize_model_id(model_id)
            lab = _bedrock_lab(normalized)
            if not lab:
                continue
            catalog[normalized] = {
                "model_id": model_id,
                "model_name": summary.get("modelName") or model_id,
                "lab": lab,
            }

        next_token = None
        while True:
            params: dict[str, Any] = {"maxResults": 100}
            if next_token:
                params["nextToken"] = next_token
            response = client.list_inference_profiles(**params)
            for profile in response.get("inferenceProfileSummaries", []):
                profile_id = profile.get("inferenceProfileId")
                if not profile_id:
                    continue
                normalized = _normalize_model_id(profile_id)
                lab = _bedrock_lab(normalized)
                if not lab:
                    continue
                catalog[normalized] = {
                    "model_id": profile_id,
                    "model_name": profile.get("inferenceProfileName") or profile_id,
                    "lab": lab,
                }
            next_token = response.get("nextToken")
            if not next_token:
                break

        return catalog
    except Exception:
        logger.warning("Failed to fetch Bedrock model catalog", exc_info=True)
        return None


def _build_bedrock_models(
    bedrock_catalog: dict[str, dict[str, Any]],
    pricing_by_normalized_id: dict[str, dict[str, Any]] | None,
    static_by_normalized_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build catalog entries for live Bedrock models not already curated.

    Only fills in models the static list doesn't already cover — the caller
    merges this with `_merge_models`'s static-list pass, so curated entries
    are never duplicated. Pricing comes from the same LiteLLM pricing map
    used to enrich curated Bedrock entries; a model with no pricing match is
    skipped entirely rather than surfaced with a fake $0/"unknown" price —
    users shouldn't be able to select a model with no cost estimate.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    models: list[dict[str, Any]] = []

    for normalized_id, info in bedrock_catalog.items():
        if normalized_id in static_by_normalized_id:
            continue

        price_match = (pricing_by_normalized_id or {}).get(normalized_id)
        if not price_match or price_match.get("input_cost_per_token") is None:
            continue

        input_price = price_match["input_cost_per_token"] * 1000
        output_price = (price_match.get("output_cost_per_token") or 0) * 1000
        max_tokens = price_match.get("max_tokens") or 8192

        lab_display_name = _ALLOWED_BEDROCK_LABS.get(info.get("lab", ""), "Other")
        models.append(
            {
                "model_id": info["model_id"],
                "display_name": info["model_name"],
                "group": lab_display_name,
                "provider": "bedrock",
                "max_tokens": max_tokens,
                "input_price_per_1k_tokens": round(input_price, 6),
                "output_price_per_1k_tokens": round(output_price, 6),
                "pricing_as_of": "live",
                "pricing_source": "litellm",
                "pricing_fetched_at": now_iso,
                "available": True,
            }
        )

    return models


def _fetch_litellm_proxy_catalog(timeout: float = 5.0) -> dict[str, dict[str, Any]] | None:
    """Return the model catalog from the deployed LiteLLM proxy's /model/info.

    Resolves the proxy base_url/master_key via app.services.litellm
    (Settings-page override, falling back to the CFN-seeded
    LOOM_LITELLM_PROXY_BASE_URL / LOOM_LITELLM_PROXY_API_KEY env vars). Opens
    its own short-lived DB session since this function has no caller-supplied
    Session, matching the SessionLocal()/try/finally pattern used elsewhere
    in this codebase for non-request-scoped DB access.

    Returns None if no proxy is configured, or if the request fails, times
    out, or returns unparseable data. Reshapes the proxy's
    `{"data": [{"model_name", "model_info"}]}` response into the same flat
    `{model_name: model_info}` dict shape the public catalog fetch returns,
    so downstream code (_build_litellm_models, _litellm_pricing_by_normalized_id)
    needs no changes.
    """
    from app.db import SessionLocal
    from app.services.litellm import get_litellm_proxy_config

    try:
        db = SessionLocal()
        try:
            config = get_litellm_proxy_config(db)
        finally:
            db.close()
    except Exception:
        logger.warning("Failed to resolve LiteLLM proxy config", exc_info=True)
        return None

    if config is None:
        return None
    base_url, api_key = config

    try:
        import httpx

        response = httpx.get(
            f"{base_url.rstrip('/')}/model/info",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        raw = response.json()
    except Exception:
        logger.warning("Failed to fetch LiteLLM proxy model catalog", exc_info=True)
        return None

    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        return None

    catalog: dict[str, dict[str, Any]] = {}
    for entry in raw["data"]:
        if not isinstance(entry, dict):
            continue
        model_name = entry.get("model_name")
        model_info = entry.get("model_info")
        if model_name and isinstance(model_info, dict):
            catalog[model_name] = model_info
    return catalog


def _fetch_litellm_catalog(timeout: float = 5.0) -> dict[str, dict[str, Any]] | None:
    """Return the raw LiteLLM `model_prices_and_context_window.json` catalog.

    Keys are the exact model names LiteLLM expects in its `model` field
    (e.g. "gpt-4o", "azure/gpt-4") — callers that need to address a model
    through LiteLLM must use these keys unmodified.

    Returns None if the fetch is disabled (LOOM_LITELLM_PRICING_URL=""),
    fails, times out, or returns unparseable data.
    """
    url = os.getenv("LOOM_LITELLM_PRICING_URL", DEFAULT_LITELLM_PRICING_URL)
    if not url:
        return None

    try:
        import httpx

        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        raw = response.json()
    except Exception:
        logger.warning("Failed to fetch LiteLLM model catalog", exc_info=True)
        return None

    if not isinstance(raw, dict):
        return None
    return raw


def _litellm_pricing_by_normalized_id(
    raw_catalog: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build a normalized-model-id -> pricing map, used to enrich Bedrock entries."""
    pricing: dict[str, dict[str, Any]] = {}
    for key, entry in raw_catalog.items():
        if not isinstance(entry, dict):
            continue
        input_cost = entry.get("input_cost_per_token")
        output_cost = entry.get("output_cost_per_token")
        if input_cost is None and output_cost is None:
            continue
        pricing[_normalize_model_id(key)] = {
            "input_cost_per_token": input_cost,
            "output_cost_per_token": output_cost,
            "max_tokens": entry.get("max_tokens"),
            "litellm_provider": entry.get("litellm_provider"),
        }
    return pricing


_LITELLM_CHAT_MODES = {None, "chat", "responses"}


def _is_direct_bedrock_alias(model_name: str, key_field: str | None) -> bool:
    """Return True if `key_field` (LiteLLM's underlying-model key, e.g.
    "anthropic.claude-sonnet-5") names the same model as `model_name` itself.

    A mismatch (or a hash-like/"auto_router/..." key) means `model_name` is
    an alias that resolves to one or more *other* underlying models — e.g.
    a fallback list or an Adaptive Router entry — rather than a direct,
    1:1 passthrough to a single Bedrock model.
    """
    if not key_field:
        return False
    suffix = key_field.split(".", 1)[-1] if "." in key_field else key_field
    return suffix.lower() == model_name.lower()


def _litellm_group(model_name: str, entry: dict[str, Any]) -> str:
    """Group label for a LiteLLM catalog entry.

    Direct Bedrock passthroughs get a clean "Bedrock" group. Anything that
    routes/aliases across multiple underlying models — LiteLLM's Adaptive
    Router (`litellm_provider == "auto_router"`) or a fallback-list alias
    whose own name doesn't match its underlying model key — is grouped
    under "Router" instead, regardless of what backs it.
    """
    provider_label = entry.get("litellm_provider") or "other"
    if provider_label == "auto_router":
        return "Router"
    if provider_label == "bedrock_converse":
        return "Bedrock" if _is_direct_bedrock_alias(model_name, entry.get("key")) else "Router"
    return f"LiteLLM / {provider_label}"


def _build_litellm_models(raw_catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Build one catalog entry per chat-capable model LiteLLM exposes.

    `model_id` is the literal key from LiteLLM's own catalog — the exact
    name its router/proxy expects in the `model` parameter, passed through
    unmodified. Pricing is computed directly from the same source LiteLLM
    publishes, so Loom's cost estimates stay consistent with LiteLLM's.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    models: list[dict[str, Any]] = []

    for key, entry in raw_catalog.items():
        if key == "sample_spec" or not isinstance(entry, dict):
            continue
        if entry.get("mode") not in _LITELLM_CHAT_MODES:
            continue
        input_cost = entry.get("input_cost_per_token")
        output_cost = entry.get("output_cost_per_token")
        if input_cost is None and output_cost is None:
            continue

        max_tokens = entry.get("max_input_tokens") or entry.get("max_tokens") or 4096

        models.append(
            {
                "model_id": key,
                "display_name": key,
                "group": _litellm_group(key, entry),
                "provider": "litellm",
                "max_tokens": max_tokens,
                "input_price_per_1k_tokens": round((input_cost or 0) * 1000, 6),
                "output_price_per_1k_tokens": round((output_cost or 0) * 1000, 6),
                "pricing_as_of": "live",
                "pricing_source": "litellm",
                "pricing_fetched_at": now_iso,
                "available": None,
            }
        )

    return models


def _merge_models(
    static_models: list[dict[str, Any]],
    availability: set[str] | None,
    pricing: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Enrich a copy of static_models with live availability and pricing."""
    now_iso = datetime.now(timezone.utc).isoformat()
    merged: list[dict[str, Any]] = []

    for model in static_models:
        entry = dict(model)
        normalized_id = _normalize_model_id(entry["model_id"])

        entry["available"] = (
            normalized_id in availability if availability is not None else None
        )

        price_match = pricing.get(normalized_id) if pricing is not None else None
        if price_match and price_match.get("input_cost_per_token") is not None:
            entry["input_price_per_1k_tokens"] = price_match["input_cost_per_token"] * 1000
            entry["output_price_per_1k_tokens"] = (price_match.get("output_cost_per_token") or 0) * 1000
            if price_match.get("max_tokens"):
                entry["max_tokens"] = price_match["max_tokens"]
            entry["pricing_source"] = "litellm"
            entry["pricing_fetched_at"] = now_iso
        else:
            entry["pricing_source"] = "static"
            entry["pricing_fetched_at"] = None

        merged.append(entry)

    return merged


def _ttl_seconds() -> float:
    try:
        return float(os.getenv("LOOM_MODEL_CATALOG_TTL_SECONDS", "900"))
    except ValueError:
        return 900.0


def get_bedrock_models(region: str) -> list[dict[str, Any]]:
    """Return the static + dynamically-discovered Bedrock model catalog.

    Never touches LiteLLM's proxy — this is the fast path used for the
    picker's eager page-load fetch, so selecting Bedrock never waits on a
    LiteLLM proxy round-trip. Pricing is still enriched from the LiteLLM
    pricing map (proxy-or-public) when available, matching today's
    behavior for curated Bedrock entries.

    Cached with a TTL (default 900s, overridable via
    LOOM_MODEL_CATALOG_TTL_SECONDS) to avoid re-fetching on every request.
    Thread-safe for concurrent sync FastAPI request handlers.
    """
    from app.routers.agents import SUPPORTED_MODELS

    now = time.monotonic()
    cached = _cache.get("data")
    if cached is not None and (now - _cache["fetched_at"]) < _ttl_seconds():
        return cached

    with _cache_lock:
        # Re-check after acquiring the lock — another thread may have
        # refreshed the cache while we were waiting.
        cached = _cache.get("data")
        if cached is not None and (time.monotonic() - _cache["fetched_at"]) < _ttl_seconds():
            return cached

        availability = _fetch_bedrock_availability(region)
        bedrock_catalog = _fetch_bedrock_catalog(region)
        # Public catalog only (not the proxy) — this function must never
        # depend on the LiteLLM proxy being configured/reachable.
        raw_litellm_catalog = _fetch_litellm_catalog()
        pricing = (
            _litellm_pricing_by_normalized_id(raw_litellm_catalog)
            if raw_litellm_catalog is not None
            else None
        )

        # Restrict curated static entries to the same allowed labs as the
        # dynamic catalog (Anthropic, OpenAI, Amazon, DeepSeek, Qwen, Z.AI) —
        # models.json may curate other labs (Meta, Google, etc.) that this
        # app doesn't want surfaced.
        static_bedrock_models = [
            model
            for model in SUPPORTED_MODELS
            if model.get("provider") != "litellm"
            and _bedrock_lab(_normalize_model_id(model["model_id"]))
        ]
        merged = _merge_models(static_bedrock_models, availability, pricing)

        if bedrock_catalog:
            static_by_normalized_id = {
                _normalize_model_id(m["model_id"]): m for m in static_bedrock_models
            }
            merged.extend(
                _build_bedrock_models(bedrock_catalog, pricing, static_by_normalized_id)
            )

        _cache["data"] = merged
        _cache["fetched_at"] = time.monotonic()
        return merged


def get_litellm_models_live() -> list[dict[str, Any]]:
    """Return only the models actually configured on the deployed LiteLLM
    proxy (resolved via app.services.litellm — Settings-page override,
    falling back to the CFN-seeded env vars). No public GitHub catalog
    fallback and no static placeholder — if the proxy isn't
    enabled/configured or the request fails, returns an empty list rather
    than a misleading universe of models the proxy may not actually have
    deployed.

    Cached with the same TTL as get_bedrock_models, independently, so
    selecting LiteLLM doesn't wait on/depend on the Bedrock fetch and vice
    versa.
    """
    now = time.monotonic()
    cached = _litellm_cache.get("data")
    if cached is not None and (now - _litellm_cache["fetched_at"]) < _ttl_seconds():
        return cached

    with _litellm_cache_lock:
        cached = _litellm_cache.get("data")
        if cached is not None and (time.monotonic() - _litellm_cache["fetched_at"]) < _ttl_seconds():
            return cached

        raw_catalog = _fetch_litellm_proxy_catalog()
        models = _build_litellm_models(raw_catalog) if raw_catalog else []

        _litellm_cache["data"] = models
        _litellm_cache["fetched_at"] = time.monotonic()
        return models


def clear_litellm_cache() -> None:
    """Drop the cached LiteLLM proxy catalog so the next call re-fetches
    live, bypassing the TTL — for recovering from a stale empty cache (e.g.
    the proxy was unreachable when first fetched) without a backend
    restart."""
    with _litellm_cache_lock:
        _litellm_cache["data"] = None
        _litellm_cache["fetched_at"] = 0.0


def get_merged_models(region: str) -> list[dict[str, Any]]:
    """Return the full catalog: Bedrock (static + dynamic) plus whatever
    LiteLLM models the proxy reports — used by callers that need the
    complete universe of valid model ids (settings validation, patch_agent,
    pricing), as opposed to the picker's provider-scoped lazy fetches.

    No placeholder fallback: if the LiteLLM proxy isn't configured/enabled/
    reachable, its models are simply absent rather than represented by a
    fake, unpriced stand-in.
    """
    return get_bedrock_models(region) + get_litellm_models_live()


def get_providers_merged() -> list[dict[str, Any]]:
    """Return the provider registry.

    No live provider discovery is performed today — this is a thin
    passthrough kept as a hook for future work (e.g. LiteLLM proxy
    discovery), so callers already point at the right function.
    """
    from app.routers.agents import SUPPORTED_PROVIDERS

    return SUPPORTED_PROVIDERS
