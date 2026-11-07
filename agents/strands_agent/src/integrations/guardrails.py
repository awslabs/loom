"""Bedrock Guardrails support (issue #17).

Shared, framework-agnostic pieces used by the handler:

- Per-invocation guardrail override validation (Contract 2).
- ``summarize_assessments`` — turns Bedrock guardrail assessments into the
  Contract 3 ``policies`` list. Only an allow-listed set of fields is copied,
  so ``match`` (which holds the *original* PII/matched text), ``regex`` and
  any other pattern fields can never leak into events or logs.
- ``apply_guardrail`` — the standalone ``ApplyGuardrail`` call used by
  monitor mode.
- ``GuardrailSession`` — per-invocation state that turns enforce-mode
  signals (stream trace, stop reason) and monitor-mode ``ApplyGuardrail``
  results into Contract 3 stream events, and writes the Contract 4
  ``guardrail_intervention`` log line for every event.
"""

import asyncio
import dataclasses
import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import boto3
from botocore.config import Config as BotoConfig

from src.config import GuardrailConfig

logger = logging.getLogger(__name__)

GUARDRAIL_NOT_ALLOWED_TEXT = "Requested guardrail is not allowed for this agent."
GUARDRAIL_NOT_ALLOWED_MESSAGE = f"\n\nError: {GUARDRAIL_NOT_ALLOWED_TEXT}"

LOG_EVENT_MARKER = "guardrail_intervention"

# Actions that mean Bedrock changed or blocked content.
_INTERVENING_ACTIONS = frozenset({"BLOCKED", "ANONYMIZED"})

# Monitor-mode ApplyGuardrail calls must never hold up the stream for long.
_MONITOR_TIMEOUT_SECONDS = float(os.environ.get("LOOM_GUARDRAIL_MONITOR_TIMEOUT_SECONDS", "5"))

_clients: dict[str, Any] = {}
_clients_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Contract 2: per-invocation override
# ---------------------------------------------------------------------------

def resolve_invocation_guardrail(
    configured: Optional[GuardrailConfig], requested: Any
) -> tuple[Optional[GuardrailConfig], bool]:
    """Resolve the guardrail to use for one invocation.

    Returns ``(guardrail, ok)``. With no request, the configured (primary)
    guardrail is used. A request is accepted only when its
    ``(guardrail_id, guardrail_version)`` matches the primary or an
    ``allowed`` entry; the mode and other settings always stay the primary's,
    so a payload can never disable or downgrade the guardrail. A request on
    an agent with no configured guardrail is rejected. ``ok`` is False when
    the request must be rejected.
    """
    if requested is None:
        return configured, True
    if configured is None or not isinstance(requested, dict):
        return None, False
    req_id = requested.get("guardrail_id")
    req_version = requested.get("guardrail_version")
    if not isinstance(req_id, str) or not req_id or req_version is None:
        return None, False
    req_version = str(req_version)

    if req_id == configured.guardrail_id and req_version == configured.guardrail_version:
        return configured, True
    for ref in configured.allowed:
        if req_id == ref.guardrail_id and req_version == ref.guardrail_version:
            return dataclasses.replace(
                configured,
                guardrail_id=ref.guardrail_id,
                guardrail_version=ref.guardrail_version,
                guardrail_arn=ref.guardrail_arn,
            ), True
    return None, False


def enforce_applies(guardrail: Optional[GuardrailConfig], provider: str) -> bool:
    """True when the guardrail should be attached inline to model calls."""
    return (
        guardrail is not None
        and guardrail.mode == "enforce"
        and (provider or "bedrock") == "bedrock"
    )


def guardrail_cache_key(guardrail: Optional[GuardrailConfig], provider: str) -> Optional[tuple[str, str, str, bool]]:
    """Part of the model-cache key that depends on the inline guardrail.

    Only enforce mode changes the model object; monitor mode (or no
    guardrail) shares the plain model.
    """
    if not enforce_applies(guardrail, provider):
        return None
    assert guardrail is not None
    return (
        guardrail.identifier,
        guardrail.guardrail_version,
        guardrail.stream_processing_mode,
        guardrail.redact_history,
    )


# ---------------------------------------------------------------------------
# Assessment summarisation (no match / regex / pattern fields, ever)
# ---------------------------------------------------------------------------

def _entry_triggered(entry: dict[str, Any]) -> bool:
    action = entry.get("action")
    if action and action != "NONE":
        return True
    return entry.get("detected") is True


def _summarize_one(assessment: dict[str, Any]) -> list[dict[str, str]]:
    policies: list[dict[str, str]] = []

    def add(policy: str, action: Any, type_: Any = None, name: Any = None) -> None:
        item: dict[str, str] = {"policy": policy}
        if type_:
            item["type"] = str(type_)
        if name:
            item["name"] = str(name)
        item["action"] = str(action or "NONE")
        policies.append(item)

    content = assessment.get("contentPolicy") or {}
    for f in content.get("filters") or []:
        if isinstance(f, dict) and _entry_triggered(f):
            add("contentPolicy", f.get("action"), type_=f.get("type"))

    topic = assessment.get("topicPolicy") or {}
    for t in topic.get("topics") or []:
        if isinstance(t, dict) and _entry_triggered(t):
            add("topicPolicy", t.get("action"), name=t.get("name"))

    sensitive = assessment.get("sensitiveInformationPolicy") or {}
    for p in sensitive.get("piiEntities") or []:
        if isinstance(p, dict) and _entry_triggered(p):
            add("sensitiveInformationPolicy", p.get("action"), type_=p.get("type"))
    for r in sensitive.get("regexes") or []:
        if isinstance(r, dict) and _entry_triggered(r):
            # ``name`` is the operator-defined label; ``regex``/``match`` are dropped.
            add("sensitiveInformationPolicy", r.get("action"), type_="REGEX", name=r.get("name"))

    word = assessment.get("wordPolicy") or {}
    for w in word.get("customWords") or []:
        if isinstance(w, dict) and _entry_triggered(w):
            add("wordPolicy", w.get("action"), type_="CUSTOM_WORD")
    for w in word.get("managedWordLists") or []:
        if isinstance(w, dict) and _entry_triggered(w):
            add("wordPolicy", w.get("action"), type_=w.get("type"))

    grounding = assessment.get("contextualGroundingPolicy") or {}
    for g in grounding.get("filters") or []:
        if isinstance(g, dict) and _entry_triggered(g):
            add("contextualGroundingPolicy", g.get("action"), type_=g.get("type"))

    return policies


def summarize_assessments(assessments: Any) -> list[dict[str, str]]:
    """Summarise one or more guardrail assessments into Contract 3 ``policies``.

    Accepts a single assessment dict, a list of them (``ApplyGuardrail`` /
    ``outputAssessments`` values), or a mapping of guardrail id to either
    (Converse trace ``inputAssessment`` / ``outputAssessments``). Each entry
    carries only ``policy``, ``type``/``name`` and ``action``; duplicates
    are collapsed.
    """
    flat: list[dict[str, Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, list):
            for v in value:
                collect(v)
        elif isinstance(value, dict):
            if any(k.endswith("Policy") for k in value):
                flat.append(value)
            else:
                for v in value.values():
                    collect(v)

    collect(assessments)

    seen: set[tuple[tuple[str, str], ...]] = set()
    out: list[dict[str, str]] = []
    for assessment in flat:
        for item in _summarize_one(assessment):
            key = tuple(sorted(item.items()))
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out


def _has_intervention(policies: Iterable[dict[str, str]]) -> bool:
    return any(p.get("action") in _INTERVENING_ACTIONS for p in policies)


# ---------------------------------------------------------------------------
# Contract 3 event + Contract 4 log line
# ---------------------------------------------------------------------------

def build_event(
    guardrail: GuardrailConfig, source: str, action: str, policies: list[dict[str, str]]
) -> dict[str, Any]:
    """Build the Contract 3 ``{"guardrail": {...}}`` stream event."""
    return {"guardrail": {
        "mode": guardrail.mode,
        "source": source,
        "action": action,
        "guardrail_id": guardrail.guardrail_id,
        "guardrail_version": guardrail.guardrail_version,
        "policies": policies,
    }}


def log_intervention(session_id: str, event: dict[str, Any]) -> None:
    """Write the Contract 4 single-line JSON record to stdout.

    Never contains matched text or prompt/response content — only the
    already-summarised Contract 3 fields.
    """
    body = event.get("guardrail", event)
    record = {
        "loom_event": LOG_EVENT_MARKER,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": body.get("mode"),
        "source": body.get("source"),
        "action": body.get("action"),
        "guardrail_id": body.get("guardrail_id"),
        "guardrail_version": body.get("guardrail_version"),
        "policies": body.get("policies", []),
    }
    try:
        print(json.dumps(record, separators=(",", ":")), file=sys.stdout, flush=True)
    except Exception as e:  # never let logging break the stream
        logger.warning("Failed to write guardrail intervention log line: %s", e)


# ---------------------------------------------------------------------------
# Monitor mode: standalone ApplyGuardrail
# ---------------------------------------------------------------------------

def _region_for(guardrail: GuardrailConfig) -> str:
    arn = guardrail.guardrail_arn or ""
    parts = arn.split(":")
    if arn.startswith("arn:") and len(parts) > 3 and parts[3]:
        return parts[3]
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def _get_client(region: str) -> Any:
    with _clients_lock:
        client = _clients.get(region)
        if client is None:
            client = boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=BotoConfig(
                    connect_timeout=3,
                    read_timeout=_MONITOR_TIMEOUT_SECONDS,
                    retries={"max_attempts": 2, "mode": "standard"},
                ),
            )
            _clients[region] = client
        return client


def apply_guardrail(guardrail: GuardrailConfig, source: str, text: str) -> dict[str, Any]:
    """Call ``bedrock-runtime:ApplyGuardrail`` on ``text`` (blocking).

    Raises on failure; callers are expected to catch and log.
    """
    client = _get_client(_region_for(guardrail))
    return client.apply_guardrail(
        guardrailIdentifier=guardrail.identifier,
        guardrailVersion=guardrail.guardrail_version,
        source=source,
        content=[{"text": {"text": text}}],
    )


# ---------------------------------------------------------------------------
# Per-invocation session
# ---------------------------------------------------------------------------

class GuardrailSession:
    """Turns guardrail signals for one invocation into Contract 3 events.

    Enforce mode (Bedrock only): ``observe_trace`` summarises a Converse
    ``metadata.trace.guardrail`` block and emits one event per source
    (``INPUT``/``OUTPUT``) that shows a block or mask. ``finish`` falls back
    to an ``UNKNOWN``-source event when the stop reason says the guardrail
    intervened but no trace was seen, so an intervention is reported once
    even when both signals fire.

    Monitor mode (any provider): ``start_input`` launches ``ApplyGuardrail``
    on the prompt in a worker thread (the model call is not delayed);
    ``finish`` collects it and checks the final response text. Events are
    emitted only when ``ApplyGuardrail`` returns ``GUARDRAIL_INTERVENED``.
    All monitor failures are logged and swallowed.

    Every emitted event is also written as a Contract 4 log line.
    """

    def __init__(self, guardrail: GuardrailConfig, session_id: str) -> None:
        self.guardrail = guardrail
        self.session_id = session_id
        self._emitted = 0
        self._seen: set[tuple[str, tuple[tuple[tuple[str, str], ...], ...]]] = set()
        self._input_task: Optional[asyncio.Task] = None
        self._output_parts: list[str] = []

    @classmethod
    def create(
        cls, guardrail: Optional[GuardrailConfig], provider: str, session_id: str
    ) -> Optional["GuardrailSession"]:
        """Return a session when the guardrail is active for this provider."""
        if guardrail is None:
            return None
        if guardrail.mode == "enforce" and not enforce_applies(guardrail, provider):
            # Not attached to the model (see the agent's model builder); nothing to observe.
            return None
        return cls(guardrail, session_id)

    @property
    def is_enforce(self) -> bool:
        return self.guardrail.mode == "enforce"

    @property
    def is_monitor(self) -> bool:
        return self.guardrail.mode == "monitor"

    def _emit(self, source: str, action: str, policies: list[dict[str, str]]) -> dict[str, Any]:
        event = build_event(self.guardrail, source, action, policies)
        log_intervention(self.session_id, event)
        self._emitted += 1
        return event

    # -- enforce ----------------------------------------------------------

    def observe_trace(self, guardrail_trace: Any) -> list[dict[str, Any]]:
        """Summarise a Converse ``trace.guardrail`` block (enforce mode)."""
        if not self.is_enforce or not isinstance(guardrail_trace, dict):
            return []
        events: list[dict[str, Any]] = []
        for source, key in (("INPUT", "inputAssessment"), ("OUTPUT", "outputAssessments")):
            policies = summarize_assessments(guardrail_trace.get(key) or {})
            if not _has_intervention(policies):
                continue
            signature = (source, tuple(tuple(sorted(p.items())) for p in policies))
            if signature in self._seen:
                # Same intervention re-reported (e.g. the whole history is
                # re-evaluated on the next model call in the tool loop).
                continue
            self._seen.add(signature)
            events.append(self._emit(source, "intervened", policies))
        return events

    def observe_stream_event(self, event: Any) -> list[dict[str, Any]]:
        """Inspect a Strands stream event for a raw ``metadata.trace.guardrail`` chunk."""
        if not self.is_enforce or not isinstance(event, dict):
            return []
        chunk = event.get("event")
        if not isinstance(chunk, dict):
            return []
        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict):
            return []
        trace = metadata.get("trace")
        if not isinstance(trace, dict) or "guardrail" not in trace:
            return []
        return self.observe_trace(trace["guardrail"])

    def observe_stop(self, intervened: bool) -> list[dict[str, Any]]:
        """Fallback when the stop reason reports an intervention with no trace seen."""
        if not self.is_enforce or not intervened or self._emitted:
            return []
        return [self._emit("UNKNOWN", "intervened", [])]

    # -- monitor ----------------------------------------------------------

    def start_input(self, prompt: Any) -> None:
        """Start the monitor-mode INPUT check in the background."""
        if not self.is_monitor or self._input_task is not None:
            return
        if not isinstance(prompt, str) or not prompt.strip():
            return
        self._input_task = asyncio.ensure_future(self._check("INPUT", prompt))

    def record_output(self, text: str) -> None:
        """Accumulate streamed response text for the monitor-mode OUTPUT check."""
        if self.is_monitor and text:
            self._output_parts.append(text)

    def poll(self) -> list[dict[str, Any]]:
        """Return the INPUT detection as soon as it is ready (non-blocking)."""
        task = self._input_task
        if task is None or not task.done():
            return []
        self._input_task = None
        return self._task_events(task)

    def _task_events(self, task: "asyncio.Future[Optional[dict[str, Any]]]") -> list[dict[str, Any]]:
        try:
            event = task.result()
        except BaseException as e:  # defensive; _check already swallows errors
            logger.warning("Guardrail monitor check failed: %s", e)
            return []
        return [event] if event else []

    async def _check(self, source: str, text: str) -> Optional[dict[str, Any]]:
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(apply_guardrail, self.guardrail, source, text),
                timeout=_MONITOR_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.warning(
                "ApplyGuardrail (%s) failed for guardrail %s: %s",
                source, self.guardrail.guardrail_id, type(e).__name__ if not str(e) else e,
            )
            return None
        if not isinstance(response, dict) or response.get("action") != "GUARDRAIL_INTERVENED":
            return None
        policies = summarize_assessments(response.get("assessments") or [])
        return self._emit(source, "detected", policies)

    # -- end of invocation ------------------------------------------------

    async def finish(self, stop_intervened: bool = False) -> list[dict[str, Any]]:
        """Collect the remaining events once the model stream has ended."""
        if self.is_enforce:
            return self.observe_stop(stop_intervened)

        events: list[dict[str, Any]] = []
        task = self._input_task
        if task is not None:
            self._input_task = None
            # asyncio.wait never raises the task's own exception; _check is
            # already bounded by its own timeout.
            await asyncio.wait({task})
            events.extend(self._task_events(task))
        output_text = "".join(self._output_parts)
        if output_text.strip():
            event = await self._check("OUTPUT", output_text)
            if event:
                events.append(event)
        return events
