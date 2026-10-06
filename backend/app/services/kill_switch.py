"""Agent kill switch: stop an agent by denying its execution role everything but telemetry.

Stop attaches one customer-managed deny policy -- created once per account by
``shared/iac/kill_switch.yaml`` -- to the agent's execution role, then stops the
runtime sessions Loom knows about. IAM evaluates that deny on every request the
agent makes, so its next model, memory, gateway or credential call fails while
its logs, traces and metrics keep flowing. Resume detaches the policy; nothing is
redeployed and nothing is deleted.

The role's attached policies are the source of truth. Loom's own record (the
``stopped_*`` columns on the agent) is compared with them on every read, so a
policy detached or attached outside Loom shows up as drift instead of being
silently trusted.
"""
from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

KILL_SWITCH_POLICY_ARN_ENV = "LOOM_KILL_SWITCH_POLICY_ARN"

# The deny policy leaves exactly these actions to the role's own allows, so a
# stopped agent can still be observed. Must match shared/iac/kill_switch.yaml
# (a unit test compares the two).
TELEMETRY_ACTIONS: tuple[str, ...] = (
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents",
    "logs:DescribeLogGroups",
    "logs:DescribeLogStreams",
    "xray:PutTraceSegments",
    "xray:PutTelemetryRecords",
    "xray:GetSamplingRules",
    "xray:GetSamplingTargets",
    "cloudwatch:PutMetricData",
)

# A runtime session cannot outlive its instance's maxLifetime (AgentCore default
# 8 hours, configurable up to 14 days), so only sessions started inside that
# window can still be running. When Loom does not know the runtime's setting it
# uses the API maximum: stopping a session that already ended is harmless.
SESSION_MAX_LIFETIME_CEILING = timedelta(seconds=1_209_600)
MAX_SESSIONS_TO_STOP = 200
_SESSION_STOP_WORKERS = 8

# Loom may stop only agents whose execution role is a Loom role: the ECS task
# role may attach the policy to role/loom-* only, the same boundary as its
# iam:PassRole. A role outside it (for example one created by the AgentCore
# starter toolkit) can also run runtimes Loom does not manage, which a stop
# would silently stop too.
LOOM_ROLE_PREFIX = "loom-"

_POLICY_ARN_RE = re.compile(r"^arn:aws[a-z-]*:iam::\d{12}:policy/[\w+=,.@/-]+$")
_ROLE_ARN_RE = re.compile(r"^arn:aws[a-z-]*:iam::\d{12}:role/(?:[\w+=,.@-]+/)*([\w+=,.@-]{1,64})$")
_RUNTIME_ARN_RE = re.compile(r"^arn:aws[a-z-]*:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime/[\w-]+$")


class KillSwitchUnavailable(Exception):
    """The kill switch cannot act on this agent; the message says why."""


def _iam_client():
    import boto3
    return boto3.client("iam")


def _agentcore_client(region: str):
    import boto3
    return boto3.client("bedrock-agentcore", region_name=region)


def _request_id(payload: dict[str, Any] | None) -> str | None:
    return ((payload or {}).get("ResponseMetadata") or {}).get("RequestId")


def _error_code(err: ClientError) -> str:
    return err.response.get("Error", {}).get("Code", "Unknown")


def describe_client_error(err: ClientError) -> str:
    """'<code>: <message>' for an AWS error, without the request internals."""
    error = err.response.get("Error", {})
    message = error.get("Message") or ""
    return f"{error.get('Code', 'Unknown')}: {message}".rstrip(": ")


# ---------------------------------------------------------------------------
# Configuration and target resolution
# ---------------------------------------------------------------------------

def policy_arn() -> str:
    """The configured kill-switch policy ARN, or raise KillSwitchUnavailable."""
    value = os.getenv(KILL_SWITCH_POLICY_ARN_ENV, "").strip()
    if not value:
        raise KillSwitchUnavailable(
            "The kill switch is not configured: deploy shared/iac/kill_switch.yaml once per account "
            f"and set {KILL_SWITCH_POLICY_ARN_ENV} on the backend."
        )
    if not _POLICY_ARN_RE.match(value):
        raise KillSwitchUnavailable(f"{KILL_SWITCH_POLICY_ARN_ENV} is not an IAM policy ARN.")
    return value


def execution_role_arn(agent: Any) -> str | None:
    """The agent's execution role: Loom's record, else the role AgentCore reports for it."""
    if agent.execution_role_arn:
        return agent.execution_role_arn
    try:
        role = (agent.get_raw_metadata() or {}).get("roleArn")
    except Exception:
        role = None
    return role or None


def role_name(role_arn: str) -> str:
    """The role name from a role ARN (the last path segment), or raise KillSwitchUnavailable."""
    match = _ROLE_ARN_RE.match(role_arn or "")
    if not match:
        raise KillSwitchUnavailable(f"The execution role '{role_arn}' is not an IAM role ARN.")
    return match.group(1)


def resolve_target(agent: Any) -> tuple[str, str, str]:
    """(policy ARN, role ARN, role name) for the agent, or raise KillSwitchUnavailable."""
    configured_policy = policy_arn()
    role_arn = execution_role_arn(agent)
    if not role_arn:
        raise KillSwitchUnavailable(
            "This agent has no execution role that Loom knows about, so Loom cannot stop it."
        )
    name = role_name(role_arn)
    # The resource part must start with the prefix, so a role under a path
    # (role/service-role/loom-x) is outside role/loom-* too, as in the IaC grant.
    if not role_arn.split(":role/", 1)[-1].startswith(LOOM_ROLE_PREFIX):
        raise KillSwitchUnavailable(
            f"Loom can only stop agents whose execution role is a Loom role (role/{LOOM_ROLE_PREFIX}*). "
            f"This agent uses {name}, which runtimes outside Loom may share."
        )
    return configured_policy, role_arn, name


def stopped_message(agent: Any) -> str | None:
    """The refusal text for an action on a stopped agent, or None when it is running."""
    if not agent.stopped_at:
        return None
    when = agent.stopped_at.strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"This agent was stopped by {agent.stopped_by or 'an operator'} at {when}: "
        f"{agent.stop_reason or 'no reason recorded'}. Resume it first."
    )


# ---------------------------------------------------------------------------
# IAM: the deny policy on the execution role
# ---------------------------------------------------------------------------

def is_attached(role: str, policy: str) -> bool:
    """Whether the kill-switch policy is attached to the role right now."""
    paginator = _iam_client().get_paginator("list_attached_role_policies")
    for page in paginator.paginate(RoleName=role):
        if any(p.get("PolicyArn") == policy for p in page.get("AttachedPolicies", [])):
            return True
    return False


def attach(role: str, policy: str) -> str | None:
    """Attach the deny policy; returns the IAM request id."""
    return _request_id(_iam_client().attach_role_policy(RoleName=role, PolicyArn=policy))


def detach(role: str, policy: str) -> tuple[bool, str | None]:
    """Detach the deny policy. Returns (detached, request id); (False, id) when it was not attached."""
    try:
        response = _iam_client().detach_role_policy(RoleName=role, PolicyArn=policy)
        return True, _request_id(response)
    except ClientError as err:
        if _error_code(err) == "NoSuchEntity":
            return False, _request_id(err.response)
        raise


def derive_state(stopped_in_loom: bool, deny_attached: bool | None) -> str:
    """Combine Loom's record with the role's live state.

    running             -- not stopped, policy not attached
    stopped             -- stopped, policy attached
    stop_not_enforced   -- Loom records a stop, but the policy is no longer attached
    stopped_outside_loom -- the policy is attached, but Loom recorded no stop
    unknown             -- the role's policies could not be read
    """
    if deny_attached is None:
        return "unknown"
    if stopped_in_loom:
        return "stopped" if deny_attached else "stop_not_enforced"
    return "stopped_outside_loom" if deny_attached else "running"


# ---------------------------------------------------------------------------
# AgentCore: stop the sessions Loom knows about
# ---------------------------------------------------------------------------

def session_window(agent: Any) -> timedelta:
    """How far back a session of this agent can still be running: its maxLifetime, else the API maximum."""
    try:
        lifecycle = (agent.get_raw_metadata() or {}).get("lifecycleConfiguration") or {}
        seconds = int(lifecycle.get("maxLifetime") or 0)
    except (TypeError, ValueError, AttributeError):
        seconds = 0
    if seconds <= 0:
        return SESSION_MAX_LIFETIME_CEILING
    return min(timedelta(seconds=seconds), SESSION_MAX_LIFETIME_CEILING)


def recent_sessions(db: Any, agent: Any, now: datetime | None = None) -> list[tuple[str, str]]:
    """(session id, qualifier) of the agent's sessions that may still be running, newest first."""
    from app.models.session import InvocationSession

    cutoff = (now or datetime.utcnow()) - session_window(agent)
    rows = (
        db.query(InvocationSession.session_id, InvocationSession.qualifier)
        .filter(InvocationSession.agent_id == agent.id, InvocationSession.created_at >= cutoff)
        .order_by(InvocationSession.created_at.desc())
        .limit(MAX_SESSIONS_TO_STOP)
        .all()
    )
    return [(row[0], row[1] or "DEFAULT") for row in rows]


def stop_sessions(agent: Any, sessions: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Call StopRuntimeSession for each session; one result per session, never raises.

    A session AgentCore no longer has is ``not_running``. Agents that are not
    AgentCore Runtime agents (for example managed harness agents) are
    ``skipped``: the deny policy still refuses their next AWS call.
    """
    if not sessions:
        return []
    if not _RUNTIME_ARN_RE.match(agent.arn or ""):
        return [
            {"session_id": sid, "qualifier": qualifier, "result": "skipped", "request_id": None,
             "error": "Only AgentCore Runtime sessions can be stopped; the deny policy still applies."}
            for sid, qualifier in sessions
        ]

    client = _agentcore_client(agent.region)

    def _stop(item: tuple[str, str]) -> dict[str, Any]:
        sid, qualifier = item
        result: dict[str, Any] = {"session_id": sid, "qualifier": qualifier, "result": "stopped",
                                  "request_id": None, "error": None}
        try:
            response = client.stop_runtime_session(
                agentRuntimeArn=agent.arn, runtimeSessionId=sid, qualifier=qualifier,
            )
            result["request_id"] = _request_id(response)
        except ClientError as err:
            result["request_id"] = _request_id(err.response)
            if _error_code(err) == "ResourceNotFoundException":
                result["result"] = "not_running"
            else:
                result["result"] = "failed"
                result["error"] = describe_client_error(err)
        except Exception as err:  # network errors and the like: record, keep going
            result["result"] = "failed"
            result["error"] = type(err).__name__
        return result

    with ThreadPoolExecutor(max_workers=min(_SESSION_STOP_WORKERS, len(sessions))) as pool:
        return list(pool.map(_stop, sessions))
