"""Amazon Bedrock Guardrails — control-plane support for Loom (issue #17).

Loom never sits on the data plane for guardrails. This module:

* resolves the *effective* guardrail for an agent at deploy time (global
  default → per-agent selection) and produces the ``guardrail`` block baked
  into the agent's ``AGENT_CONFIG_JSON`` (custom agents enforce it in their
  own runtime) or into the harness ``bedrockModelConfig.additionalParams``
  (managed agents — see
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-models.html#harness-model-guardrails);
* validates per-invocation guardrail selections against the agent's allowlist;
* lists the account's guardrails for pickers (``ListGuardrails``);
* reads intervention history that agents write to their runtime log group
  (``loom_event: guardrail_intervention`` lines) via Logs Insights.

Block / mask / detect behavior is a property of each guardrail policy in
Bedrock; Loom only adds ``enforce`` (inline) vs ``monitor`` (agent-side
``ApplyGuardrail``, log-only).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from botocore.exceptions import ClientError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

GUARDRAIL_DEFAULT_SETTING_KEY = "guardrail_default"
INTERVENTION_LOG_MARKER = "guardrail_intervention"

GuardrailMode = Literal["enforce", "monitor"]
StreamProcessingMode = Literal["sync", "async"]
GuardrailSelectionKind = Literal["default", "custom", "none"]

_GUARDRAIL_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789")


class GuardrailError(ValueError):
    """Raised when a guardrail configuration or selection is invalid."""


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class GuardrailRef(BaseModel):
    """Reference to one version of one Bedrock guardrail."""
    guardrail_id: str = Field(..., min_length=1, max_length=2048, description="Guardrail ID or ARN")
    guardrail_arn: str = Field(default="", max_length=2048, description="Guardrail ARN (optional)")
    guardrail_version: str = Field(default="DRAFT", description="Numeric version or DRAFT")

    @field_validator("guardrail_id")
    @classmethod
    def _strip_id(cls, value: str) -> str:
        value = value.strip()
        # Accept a full ARN in guardrail_id; the ID itself is lowercase alnum.
        if value.startswith("arn:"):
            if ":guardrail/" not in value:
                raise ValueError("guardrail_id ARN must be a Bedrock guardrail ARN")
            return value
        if not value or not set(value) <= _GUARDRAIL_ID_CHARS:
            raise ValueError("guardrail_id must be a Bedrock guardrail ID or ARN")
        return value

    @field_validator("guardrail_arn")
    @classmethod
    def _check_arn(cls, value: str) -> str:
        value = value.strip()
        if value and (not value.startswith("arn:") or ":guardrail/" not in value):
            raise ValueError("guardrail_arn must be a Bedrock guardrail ARN")
        return value

    @field_validator("guardrail_version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        value = (value or "DRAFT").strip()
        if value != "DRAFT" and not value.isdigit():
            raise ValueError("guardrail_version must be a positive integer or DRAFT")
        return value

    def key(self) -> tuple[str, str]:
        """Identity used for allowlist comparisons (ID without ARN, version)."""
        return (_bare_id(self.guardrail_arn or self.guardrail_id), self.guardrail_version)


class GuardrailConfig(GuardrailRef):
    """Full guardrail configuration for an agent or the global default."""
    mode: GuardrailMode = "enforce"
    stream_processing_mode: StreamProcessingMode = "sync"
    redact_history: bool = True
    allowed: list[GuardrailRef] = Field(default_factory=list, max_length=10)


class GuardrailSelection(BaseModel):
    """Per-agent guardrail selection on create/redeploy requests."""
    selection: GuardrailSelectionKind = "default"
    config: GuardrailConfig | None = None


class GuardrailDefault(BaseModel):
    """Global default guardrail (site setting with environment fallback)."""
    enabled: bool = False
    locked: bool = False
    config: GuardrailConfig | None = None


def _bare_id(identifier: str) -> str:
    """Return the guardrail ID from an ID or ARN."""
    if identifier.startswith("arn:") and ":guardrail/" in identifier:
        return identifier.rsplit("/", 1)[-1]
    return identifier


# ---------------------------------------------------------------------------
# Global default
# ---------------------------------------------------------------------------
def _env_default() -> GuardrailDefault | None:
    """Build the default from LOOM_GUARDRAIL_* env vars, or None if unset."""
    guardrail_id = os.getenv("LOOM_GUARDRAIL_ID", "").strip()
    if not guardrail_id:
        return None
    try:
        config = GuardrailConfig(
            guardrail_id=guardrail_id,
            guardrail_version=os.getenv("LOOM_GUARDRAIL_VERSION", "").strip() or "DRAFT",
            mode=(os.getenv("LOOM_GUARDRAIL_MODE", "").strip().lower() or "enforce"),  # type: ignore[arg-type]
        )
    except ValueError as exc:
        logger.warning("Ignoring invalid LOOM_GUARDRAIL_* environment configuration: %s", exc)
        return None
    locked = os.getenv("LOOM_GUARDRAIL_LOCKED", "").strip().lower() in ("1", "true", "yes")
    return GuardrailDefault(enabled=True, locked=locked, config=config)


def get_guardrail_default(db: Session) -> tuple[GuardrailDefault, str]:
    """Return the effective global default and where it came from.

    A Settings-page value (site setting) always wins once saved — even a
    saved "disabled" — otherwise the CFN-seeded environment fallback applies.

    Returns:
        (default, source) where source is "settings", "environment" or "none".
    """
    from app.models.site_setting import SiteSetting

    row = db.query(SiteSetting).filter(SiteSetting.key == GUARDRAIL_DEFAULT_SETTING_KEY).first()
    if row and row.value:
        try:
            return GuardrailDefault.model_validate_json(row.value), "settings"
        except ValueError as exc:
            logger.warning("Stored guardrail_default setting is invalid, ignoring: %s", exc)
    env_default = _env_default()
    if env_default:
        return env_default, "environment"
    return GuardrailDefault(), "none"


def save_guardrail_default(db: Session, default: GuardrailDefault) -> None:
    """Persist the global default as a site setting."""
    from app.models.site_setting import SiteSetting

    if default.enabled and default.config is None:
        raise GuardrailError("A guardrail must be selected when the default is enabled")
    value = default.model_dump_json()
    row = db.query(SiteSetting).filter(SiteSetting.key == GUARDRAIL_DEFAULT_SETTING_KEY).first()
    if row:
        row.value = value
        row.updated_at = datetime.utcnow()
    else:
        db.add(SiteSetting(key=GUARDRAIL_DEFAULT_SETTING_KEY, value=value))
    db.commit()


# ---------------------------------------------------------------------------
# Support matrix
# ---------------------------------------------------------------------------
def supported_modes(source: str | None, provider: str | None) -> dict[str, bool]:
    """Which guardrail modes an agent type supports.

    * custom (deploy) + bedrock: enforce (native guardrailConfig) and monitor
    * custom + non-bedrock provider: monitor only (no Bedrock call to attach to)
    * harness + bedrock: enforce only (additionalParams.guardrailConfig; no hooks)
    * harness + litellm, registered agents: none
    """
    provider = (provider or "bedrock").lower()
    if source == "deploy":
        return {"enforce": provider == "bedrock", "monitor": True}
    if source == "harness":
        return {"enforce": provider == "bedrock", "monitor": False}
    return {"enforce": False, "monitor": False}


def _check_supported(config: GuardrailConfig, source: str, provider: str) -> None:
    support = supported_modes(source, provider)
    if not support[config.mode]:
        kind = "managed (harness)" if source == "harness" else "custom"
        if not any(support.values()):
            raise GuardrailError(
                f"Guardrails are not supported for {kind} agents using provider '{provider}'"
            )
        if config.mode == "monitor":
            raise GuardrailError(
                "Monitor mode is not available for managed (harness) agents — the harness has no "
                "hooks to run ApplyGuardrail. Use enforce mode with a guardrail whose policies are "
                "set to detect (no action) in Bedrock instead."
            )
        raise GuardrailError(
            f"Enforce mode requires the Bedrock provider (agent uses '{provider}'); use monitor mode instead"
        )


# ---------------------------------------------------------------------------
# Deploy-time resolution
# ---------------------------------------------------------------------------
def config_to_block(config: GuardrailConfig, source: str) -> dict[str, Any]:
    """Serialize a config into the AGENT_CONFIG_JSON ``guardrail`` block."""
    return {
        "guardrail_id": _bare_id(config.guardrail_id),
        "guardrail_arn": config.guardrail_arn or (config.guardrail_id if config.guardrail_id.startswith("arn:") else ""),
        "guardrail_version": config.guardrail_version,
        "mode": config.mode,
        "stream_processing_mode": config.stream_processing_mode,
        "redact_history": config.redact_history,
        "source": source,
        "allowed": [
            {
                "guardrail_id": _bare_id(ref.guardrail_id),
                "guardrail_arn": ref.guardrail_arn or (ref.guardrail_id if ref.guardrail_id.startswith("arn:") else ""),
                "guardrail_version": ref.guardrail_version,
            }
            for ref in config.allowed
        ],
    }


def resolve_agent_guardrail(
    db: Session,
    request: GuardrailSelection | None,
    source: str,
    provider: str | None,
) -> tuple[str, dict[str, Any] | None]:
    """Resolve the guardrail to bake into an agent at deploy time.

    Args:
        db: Database session (for the global default).
        request: The create/redeploy request's selection (None = inherit default).
        source: Agent source ("deploy" or "harness").
        provider: Model provider ("bedrock", "litellm", ...).

    Returns:
        (selection, block) — block is None when no guardrail applies.

    Raises:
        GuardrailError: on lock violations or support-matrix violations.
    """
    provider = (provider or "bedrock").lower()
    selection = request or GuardrailSelection()
    default, _ = get_guardrail_default(db)
    default_cfg = default.config if default.enabled else None

    if selection.selection == "none":
        if default.locked and default_cfg is not None:
            raise GuardrailError("The global default guardrail is locked; agents cannot opt out")
        return "none", None

    if selection.selection == "custom":
        if selection.config is None:
            raise GuardrailError("guardrail.config is required when selection is 'custom'")
        if (
            default.locked
            and default_cfg is not None
            and default_cfg.mode == "enforce"
            and selection.config.mode == "monitor"
        ):
            raise GuardrailError(
                "The global default guardrail is locked in enforce mode; agents cannot switch to monitor mode"
            )
        _check_supported(selection.config, source, provider)
        return "custom", config_to_block(selection.config, "agent")

    # Inherit the global default.
    if default_cfg is None:
        return "default", None
    support = supported_modes(source, provider)
    if not support[default_cfg.mode]:
        if default.locked:
            # A locked default the agent type can't run would silently leave
            # the agent unguarded — refuse instead.
            _check_supported(default_cfg, source, provider)
        logger.info(
            "Global default guardrail mode '%s' is not supported for source=%s provider=%s; not applied",
            default_cfg.mode, source, provider,
        )
        return "default", None
    return "default", config_to_block(default_cfg, "default")


def _comparable(block: dict[str, Any] | None) -> dict[str, Any] | None:
    if not block:
        return None
    return {
        "id": _bare_id(block.get("guardrail_arn") or block.get("guardrail_id") or ""),
        "version": block.get("guardrail_version"),
        "mode": block.get("mode"),
        "stream": block.get("stream_processing_mode"),
        "redact": bool(block.get("redact_history", True)),
        "allowed": sorted(
            (_bare_id(a.get("guardrail_arn") or a.get("guardrail_id") or ""), a.get("guardrail_version"))
            for a in block.get("allowed") or []
        ),
    }


def compute_drift(
    db: Session,
    selection: str | None,
    block: dict[str, Any] | None,
    source: str | None,
    provider: str | None,
) -> bool:
    """True when an inheriting agent's baked-in guardrail differs from the current default."""
    if selection != "default" or source not in ("deploy", "harness"):
        return False
    default, _ = get_guardrail_default(db)
    expected: dict[str, Any] | None = None
    if default.enabled and default.config is not None:
        if supported_modes(source, provider)[default.config.mode]:
            expected = config_to_block(default.config, "default")
    return _comparable(block) != _comparable(expected)


def validate_invocation_guardrail(
    block: dict[str, Any] | None,
    guardrail_id: str | None,
    guardrail_version: str | None,
) -> dict[str, str] | None:
    """Validate a per-invocation guardrail selection against the agent's allowlist.

    Returns:
        The matching ref ({guardrail_id, guardrail_arn, guardrail_version}),
        or None when no selection was requested or it equals the primary.

    Raises:
        GuardrailError: when the selection isn't the primary or an allowed alternate.
    """
    if not guardrail_id:
        return None
    if not block:
        raise GuardrailError("This agent has no guardrail configured, so a guardrail cannot be selected")
    wanted = (_bare_id(guardrail_id.strip()), (guardrail_version or "DRAFT").strip())
    primary_key = (_bare_id(block.get("guardrail_arn") or block.get("guardrail_id") or ""), block.get("guardrail_version"))
    if wanted == primary_key:
        return None
    for ref in block.get("allowed") or []:
        ref_key = (_bare_id(ref.get("guardrail_arn") or ref.get("guardrail_id") or ""), ref.get("guardrail_version"))
        if wanted == ref_key:
            return {
                "guardrail_id": ref.get("guardrail_id", ""),
                "guardrail_arn": ref.get("guardrail_arn", ""),
                "guardrail_version": ref.get("guardrail_version", "DRAFT"),
            }
    raise GuardrailError(
        f"Guardrail '{guardrail_id}' version '{wanted[1]}' is not allowed for this agent"
    )


# ---------------------------------------------------------------------------
# Harness model config
# ---------------------------------------------------------------------------
def harness_additional_params(
    block: dict[str, Any] | None,
    override: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Build ``bedrockModelConfig.additionalParams`` for a harness agent.

    Only enforce mode applies (harness has no hooks for monitor mode).
    ``override`` (a validated allowlist entry) swaps the guardrail ID/version
    for one invocation; the mode and stream settings stay the agent's.
    """
    if not block or block.get("mode") != "enforce":
        return None
    ref = override or block
    guardrail_config: dict[str, Any] = {
        "guardrailIdentifier": ref.get("guardrail_arn") or ref.get("guardrail_id"),
        "guardrailVersion": ref.get("guardrail_version") or "DRAFT",
        "trace": "enabled",
    }
    if block.get("stream_processing_mode") == "async":
        guardrail_config["streamProcessingMode"] = "async"
    return {"guardrailConfig": guardrail_config}


def guardrail_block_from_config_json(config_json: str | None) -> dict[str, Any] | None:
    """Extract the ``guardrail`` block from a stored AGENT_CONFIG_JSON string."""
    if not config_json:
        return None
    try:
        block = json.loads(config_json).get("guardrail")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
    return block if isinstance(block, dict) else None


# ---------------------------------------------------------------------------
# Trace summarization (no matched text — the trace `match` field holds raw PII)
# ---------------------------------------------------------------------------
_POLICY_LISTS: dict[str, tuple[tuple[str, str], ...]] = {
    "contentPolicy": (("filters", "type"),),
    "topicPolicy": (("topics", "name"),),
    "wordPolicy": (("customWords", ""), ("managedWordLists", "type")),
    "sensitiveInformationPolicy": (("piiEntities", "type"), ("regexes", "name")),
    "contextualGroundingPolicy": (("filters", "type"),),
}


def summarize_assessment(assessment: dict[str, Any] | None) -> list[dict[str, str]]:
    """Reduce a guardrail assessment to policy/type/action entries.

    Deliberately drops ``match``, ``regex`` and any other field that could
    carry the evaluated text.
    """
    out: list[dict[str, str]] = []
    if not isinstance(assessment, dict):
        return out
    for policy, lists in _POLICY_LISTS.items():
        section = assessment.get(policy)
        if not isinstance(section, dict):
            continue
        for list_key, label_key in lists:
            for item in section.get(list_key) or []:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action", ""))
                if action in ("", "NONE") and not item.get("detected"):
                    continue
                entry: dict[str, str] = {"policy": policy, "action": action or "DETECTED"}
                if label_key == "name":
                    entry["name"] = str(item.get("name", ""))
                elif label_key == "type":
                    entry["type"] = str(item.get("type", ""))
                else:
                    entry["type"] = "CUSTOM_WORD"
                out.append(entry)
    return out


def summarize_trace(trace: dict[str, Any] | None) -> tuple[str, list[dict[str, str]]]:
    """Summarize a Converse ``trace.guardrail`` object.

    Returns:
        (source, policies) — source is INPUT, OUTPUT or UNKNOWN.
    """
    if not isinstance(trace, dict):
        return "UNKNOWN", []
    input_policies: list[dict[str, str]] = []
    for assessment in (trace.get("inputAssessment") or {}).values():
        input_policies.extend(summarize_assessment(assessment))
    output_policies: list[dict[str, str]] = []
    outputs = trace.get("outputAssessments") or {}
    for assessments in outputs.values():
        for assessment in assessments or []:
            output_policies.extend(summarize_assessment(assessment))
    if input_policies:
        return "INPUT", input_policies
    if output_policies:
        return "OUTPUT", output_policies
    return "UNKNOWN", []


def sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Whitelist fields of an agent-emitted guardrail event before forwarding."""
    policies: list[dict[str, str]] = []
    for p in event.get("policies") or []:
        if not isinstance(p, dict):
            continue
        clean = {k: str(p[k]) for k in ("policy", "type", "name", "action") if k in p}
        if clean:
            policies.append(clean)
    return {
        "mode": str(event.get("mode", "")),
        "source": str(event.get("source", "UNKNOWN")),
        "action": str(event.get("action", "")),
        "guardrail_id": str(event.get("guardrail_id", "")),
        "guardrail_version": str(event.get("guardrail_version", "")),
        "policies": policies,
    }


# ---------------------------------------------------------------------------
# Bedrock control plane reads
# ---------------------------------------------------------------------------
def list_guardrails(region: str) -> list[dict[str, Any]]:
    """List the account's guardrails with their versions (newest first, DRAFT first)."""
    import boto3

    client = boto3.client("bedrock", region_name=region)
    summaries: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"maxResults": 100}
        if token:
            kwargs["nextToken"] = token
        resp = client.list_guardrails(**kwargs)
        summaries.extend(resp.get("guardrails", []))
        token = resp.get("nextToken")
        if not token:
            break

    results: list[dict[str, Any]] = []
    for g in summaries:
        gid = g.get("id", "")
        versions: set[str] = {"DRAFT"}
        try:
            vtoken: str | None = None
            while True:
                vkwargs: dict[str, Any] = {"guardrailIdentifier": gid, "maxResults": 100}
                if vtoken:
                    vkwargs["nextToken"] = vtoken
                vresp = client.list_guardrails(**vkwargs)
                versions.update(v.get("version", "") for v in vresp.get("guardrails", []) if v.get("version"))
                vtoken = vresp.get("nextToken")
                if not vtoken:
                    break
        except ClientError as exc:
            logger.warning("Failed to list versions for guardrail %s: %s", gid, exc)
        numbered = sorted((v for v in versions if v.isdigit()), key=int, reverse=True)
        results.append({
            "guardrail_id": gid,
            "guardrail_arn": g.get("arn", ""),
            "name": g.get("name", ""),
            "description": g.get("description", "") or "",
            "status": g.get("status", ""),
            "versions": ["DRAFT", *numbered],
        })
    results.sort(key=lambda r: r["name"].lower())
    return results


# ---------------------------------------------------------------------------
# Guardrail policy details (snapshotted at deploy/update time)
# ---------------------------------------------------------------------------
# Read with GetGuardrail when an agent is deployed or updated and stored on the
# agent row, so the agent page never calls Bedrock (no per-page-load
# throttling). DRAFT versions are mutable, so the snapshot can be refreshed
# explicitly (POST /api/agents/{id}/guardrails/refresh).
_NOT_FOUND_CODES = ("ResourceNotFoundException", "ValidationException")


def _region_for(ref: dict[str, Any], default_region: str) -> str:
    arn = ref.get("guardrail_arn") or (ref.get("guardrail_id") if str(ref.get("guardrail_id", "")).startswith("arn:") else "")
    parts = arn.split(":") if arn else []
    return parts[3] if len(parts) > 3 and parts[3] else default_region


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _io_action(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize per-direction action/enabled fields to Bedrock's effective behavior.

    Explicit ``inputAction``/``outputAction``/``*Enabled`` always win. Without
    them, the general ``action`` applies in both directions — except
    ``ANONYMIZE``, which Bedrock applies to responses only: a PII entity with
    only ``action: ANONYMIZE`` is not evaluated on prompts at all (verified
    with ApplyGuardrail ``outputScope: FULL``, where such entities are absent
    from INPUT assessments). Showing that as "mask" on input would misstate
    what the guardrail does.
    """
    base = item.get("action")
    output_only = base == "ANONYMIZE" and "inputAction" not in item and "inputEnabled" not in item
    return {
        "input_action": item.get("inputAction") or (None if output_only else base),
        "output_action": item.get("outputAction") or base,
        "input_enabled": item.get("inputEnabled", not output_only),
        "output_enabled": item.get("outputEnabled", True),
    }


def summarize_guardrail(resp: dict[str, Any]) -> dict[str, Any]:
    """Reduce a GetGuardrail response to what the agent page displays.

    Custom word lists and regex patterns are summarized as counts/names
    rather than copied, keeping the stored snapshot small and free of
    potentially sensitive policy terms.
    """
    content = resp.get("contentPolicy") or {}
    topics = resp.get("topicPolicy") or {}
    words = resp.get("wordPolicy") or {}
    sensitive = resp.get("sensitiveInformationPolicy") or {}
    grounding = resp.get("contextualGroundingPolicy") or {}
    reasoning = resp.get("automatedReasoningPolicy") or {}
    cross_region = resp.get("crossRegionDetails") or {}
    return {
        "guardrail_id": resp.get("guardrailId", ""),
        "guardrail_arn": resp.get("guardrailArn", ""),
        "version": resp.get("version", ""),
        "name": resp.get("name", ""),
        "description": resp.get("description") or "",
        "status": resp.get("status", ""),
        "updated_at": _iso_or_none(resp.get("updatedAt")),
        "blocked_input_messaging": resp.get("blockedInputMessaging") or "",
        "blocked_outputs_messaging": resp.get("blockedOutputsMessaging") or "",
        "encrypted_with_cmk": bool(resp.get("kmsKeyArn")),
        "cross_region_profile": cross_region.get("guardrailProfileId") or None,
        "content_filters": [
            {
                "type": f.get("type", ""),
                "input_strength": f.get("inputStrength", ""),
                "output_strength": f.get("outputStrength", ""),
                **_io_action(f),
            }
            for f in content.get("filters") or []
        ],
        "content_tier": (content.get("tier") or {}).get("tierName"),
        "denied_topics": [
            {
                "name": t.get("name", ""),
                "definition": t.get("definition", ""),
                "example_count": len(t.get("examples") or []),
                **_io_action(t),
            }
            for t in topics.get("topics") or []
        ],
        "topic_tier": (topics.get("tier") or {}).get("tierName"),
        "custom_word_count": len(words.get("words") or []),
        "managed_word_lists": [
            {"type": w.get("type", ""), **_io_action(w)} for w in words.get("managedWordLists") or []
        ],
        "pii_entities": [
            {"type": e.get("type", ""), **_io_action(e)} for e in sensitive.get("piiEntities") or []
        ],
        "regexes": [
            {"name": r.get("name", ""), **_io_action(r)} for r in sensitive.get("regexes") or []
        ],
        "contextual_grounding": [
            {
                "type": g.get("type", ""),
                "threshold": g.get("threshold"),
                "action": g.get("action") or "BLOCK",
                "enabled": g.get("enabled", True),
            }
            for g in grounding.get("filters") or []
        ],
        "automated_reasoning_policy_count": len(reasoning.get("policies") or []),
    }


def fetch_guardrail_details(ref: dict[str, Any], default_region: str, strict: bool) -> dict[str, Any]:
    """GetGuardrail for one guardrail version and summarize it.

    Args:
        ref: {guardrail_id, guardrail_arn?, guardrail_version}.
        default_region: Region used when the ref carries no ARN.
        strict: Raise GuardrailError when the guardrail/version doesn't exist
            (deploy-time validation). Otherwise record the error in the entry.

    Other failures (access denied, throttling) never raise — the entry
    records the error so a missing IAM permission can't block a deploy.
    """
    import boto3

    identifier = ref.get("guardrail_arn") or ref.get("guardrail_id") or ""
    version = ref.get("guardrail_version") or "DRAFT"
    region = _region_for(ref, default_region)
    base = {"guardrail_id": _bare_id(identifier), "version": version, "region": region}
    try:
        resp = boto3.client("bedrock", region_name=region).get_guardrail(
            guardrailIdentifier=identifier, guardrailVersion=version,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in _NOT_FOUND_CODES:
            message = f"Guardrail '{base['guardrail_id']}' version '{version}' was not found in {region}"
            if strict:
                raise GuardrailError(message) from exc
            return {**base, "error": message}
        logger.warning("GetGuardrail failed for %s v%s: %s", identifier, version, exc)
        return {**base, "error": f"Unable to read guardrail details ({code or 'error'})"}
    except Exception as exc:  # network/credential errors must not block deploys
        logger.warning("GetGuardrail failed for %s v%s: %s", identifier, version, exc)
        return {**base, "error": "Unable to read guardrail details"}
    return {**summarize_guardrail(resp), "region": region}


def snapshot_guardrail_details(
    block: dict[str, Any] | None, default_region: str, strict: bool = True,
) -> dict[str, Any] | None:
    """Snapshot details for an agent's primary guardrail and its alternates.

    Returns:
        {"fetched_at", "guardrails": [primary, *alternates]} or None when
        the agent has no guardrail.
    """
    if not block:
        return None
    refs = [block, *(block.get("allowed") or [])]
    return {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "guardrails": [fetch_guardrail_details(ref, default_region, strict) for ref in refs],
    }


# ---------------------------------------------------------------------------
# Intervention history (agent-written log lines)
# ---------------------------------------------------------------------------
def parse_intervention_message(message: str) -> dict[str, Any] | None:
    """Parse one agent log line into an intervention record (or None)."""
    if INTERVENTION_LOG_MARKER not in message:
        return None
    start = message.find("{")
    if start < 0:
        return None
    try:
        data = json.loads(message[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("loom_event") != INTERVENTION_LOG_MARKER:
        return None
    record = sanitize_event(data)
    record["session_id"] = str(data.get("session_id", ""))
    record["timestamp"] = str(data.get("timestamp", ""))
    return record


def query_interventions(
    log_group: str,
    region: str,
    session_id: str | None = None,
    hours: int = 24,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read guardrail intervention records from an agent runtime log group."""
    import boto3

    logs = boto3.client("logs", region_name=region)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    query = (
        "fields @timestamp, @message\n"
        f"| filter @message like /{INTERVENTION_LOG_MARKER}/\n"
    )
    if session_id:
        # session IDs are UUID-like; strip anything that could break the query.
        safe_session = "".join(c for c in session_id if c.isalnum() or c in "-_")
        query += f'| filter @message like "{safe_session}"\n'
    query += "| sort @timestamp desc"
    try:
        query_id = logs.start_query(
            logGroupName=log_group,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query,
            limit=limit,
        )["queryId"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return []
        raise

    result: dict[str, Any] = {"status": "Running"}
    for _ in range(30):
        result = logs.get_query_results(queryId=query_id)
        if result.get("status") in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(1)
    if result.get("status") != "Complete":
        return []

    records: list[dict[str, Any]] = []
    for row in result.get("results", []):
        fields = {f.get("field"): f.get("value") for f in row}
        record = parse_intervention_message(fields.get("@message") or "")
        if record is None:
            continue
        if session_id and record["session_id"] != session_id:
            continue
        if not record["timestamp"]:
            record["timestamp"] = fields.get("@timestamp") or ""
        records.append(record)
    return records
