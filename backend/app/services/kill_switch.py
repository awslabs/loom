"""Agent kill switch: stop an agent by denying every invocation of its runtime.

Stop adds one explicit-deny statement to the AgentCore Runtime's own
resource-based policy (``PutResourcePolicy`` on ``bedrock-agentcore-control``),
then stops the runtime sessions Loom knows about. AgentCore evaluates that
policy on every ``InvokeAgentRuntime*`` call from any caller -- through Loom or
not -- and an explicit deny wins over any identity-based allow, so nobody can
start a new invocation of a stopped agent. Resume removes the statement;
nothing is redeployed and nothing is deleted.

Loom never touches IAM: the execution role is provisioned outside Loom
(``shared/iac/role.yaml``) and is not modified. Any statements the runtime's
policy already holds are kept as they are; Loom only adds and removes its own
statement, identified by ``DENY_SID``.

The runtime's policy is the source of truth. Loom's own record (the
``stopped_*`` columns on the agent) is compared with it on every read, so a
statement removed or added outside Loom shows up as drift instead of being
silently trusted.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# The statement id Loom owns in the runtime's resource policy. Loom adds and
# removes only a statement with this Sid and leaves every other one alone.
DENY_SID = "LoomKillSwitch"

# Every data-plane action that starts or continues work on the runtime. The
# list is the runtime actions documented for resource-based policies, minus
# StopRuntimeSession (Loom needs it to end running sessions, and stopping is
# never harmful) and GetAgentCard (read-only metadata).
DENIED_ACTIONS: tuple[str, ...] = (
    "bedrock-agentcore:InvokeAgentRuntime",
    "bedrock-agentcore:InvokeAgentRuntimeForUser",
    "bedrock-agentcore:InvokeAgentRuntimeCommand",
    "bedrock-agentcore:InvokeAgentRuntimeCommandShell",
    "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream",
    "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStreamForUser",
)

POLICY_VERSION = "2012-10-17"

# A runtime session cannot outlive its instance's maxLifetime (AgentCore default
# 8 hours, configurable up to 14 days), so only sessions started inside that
# window can still be running. When Loom does not know the runtime's setting it
# uses the API maximum: stopping a session that already ended is harmless.
SESSION_MAX_LIFETIME_CEILING = timedelta(seconds=1_209_600)
MAX_SESSIONS_TO_STOP = 200
_SESSION_STOP_WORKERS = 8

_RUNTIME_ARN_RE = re.compile(
    r"^arn:aws[a-z-]*:bedrock-agentcore:([a-z0-9-]+):\d{12}:runtime/[\w-]+$"
)


class KillSwitchUnavailable(Exception):
    """The kill switch cannot act on this agent; the message says why."""


class ForeignPolicyStatement(Exception):
    """The runtime policy holds a statement with Loom's Sid that Loom did not write."""


def _control_client(region: str):
    import boto3
    return boto3.client("bedrock-agentcore-control", region_name=region)


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
# Target resolution
# ---------------------------------------------------------------------------

def resolve_target(agent: Any) -> tuple[str, str]:
    """(runtime ARN, region) for the agent, or raise KillSwitchUnavailable.

    Only AgentCore Runtime agents have a runtime resource policy; other agent
    kinds (for example managed harness agents) cannot be stopped this way.
    """
    match = _RUNTIME_ARN_RE.match(agent.arn or "")
    if not match:
        raise KillSwitchUnavailable(
            "Only AgentCore Runtime agents can be stopped: the kill switch denies invocations "
            "in the runtime's resource policy, and this agent has no runtime ARN."
        )
    return agent.arn, agent.region or match.group(1)


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
# The deny statement in the runtime's resource policy
# ---------------------------------------------------------------------------

def deny_statement(runtime_arn: str) -> dict[str, Any]:
    """Loom's deny statement. ``Resource`` must be the exact runtime ARN (AgentCore rejects '*')."""
    return {
        "Sid": DENY_SID,
        "Effect": "Deny",
        "Principal": "*",
        "Action": list(DENIED_ACTIONS),
        "Resource": runtime_arn,
    }


def get_policy(runtime_arn: str, region: str) -> tuple[dict[str, Any] | None, str | None]:
    """(the runtime's resource policy as a dict or None when it has none, request id)."""
    try:
        response = _control_client(region).get_resource_policy(resourceArn=runtime_arn)
    except ClientError as err:
        if _error_code(err) == "ResourceNotFoundException":
            return None, _request_id(err.response)
        raise
    raw = response.get("policy")
    if not raw:
        return None, _request_id(response)
    return json.loads(raw), _request_id(response)


def _statements(policy: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not policy:
        return []
    statements = policy.get("Statement") or []
    if isinstance(statements, dict):  # IAM allows a single statement object
        statements = [statements]
    return list(statements)


def has_deny(policy: dict[str, Any] | None, runtime_arn: str) -> bool:
    """Whether the policy holds Loom's deny statement.

    Raises ForeignPolicyStatement when a statement uses Loom's Sid but is not
    the exact statement Loom writes: Loom will not count it as a stop, and
    will not overwrite or delete it.
    """
    for statement in _statements(policy):
        if statement.get("Sid") != DENY_SID:
            continue
        if _same_deny(statement, runtime_arn):
            return True
        raise ForeignPolicyStatement(
            f"The runtime's resource policy has a statement with Sid '{DENY_SID}' that Loom did not "
            "write. Remove or rename it before using the kill switch."
        )
    return False


def _same_deny(statement: dict[str, Any], runtime_arn: str) -> bool:
    actions = statement.get("Action")
    if isinstance(actions, str):
        actions = [actions]
    return (
        statement.get("Effect") == "Deny"
        and statement.get("Principal") == "*"
        and statement.get("Resource") == runtime_arn
        and not statement.get("Condition")
        and set(actions or []) == set(DENIED_ACTIONS)
    )


def add_deny(runtime_arn: str, region: str) -> tuple[bool, str | None]:
    """Add Loom's deny statement, keeping every other statement. Returns (added, request id)."""
    policy, _ = get_policy(runtime_arn, region)
    if has_deny(policy, runtime_arn):
        return False, None
    document = dict(policy or {"Version": POLICY_VERSION})
    document["Statement"] = [*_statements(policy), deny_statement(runtime_arn)]
    response = _control_client(region).put_resource_policy(
        resourceArn=runtime_arn, policy=json.dumps(document),
    )
    return True, _request_id(response)


def remove_deny(runtime_arn: str, region: str) -> tuple[bool, str | None]:
    """Remove Loom's deny statement, keeping every other one. Returns (removed, request id).

    When Loom's statement was the only one, the whole policy is deleted, which
    puts the runtime back exactly as it was before the stop.
    """
    policy, _ = get_policy(runtime_arn, region)
    if not has_deny(policy, runtime_arn):
        return False, None
    remaining = [s for s in _statements(policy) if s.get("Sid") != DENY_SID]
    client = _control_client(region)
    if not remaining:
        try:
            response = client.delete_resource_policy(resourceArn=runtime_arn)
        except ClientError as err:
            if _error_code(err) == "ResourceNotFoundException":
                return False, _request_id(err.response)
            raise
        return True, _request_id(response)
    document = dict(policy or {})
    document["Statement"] = remaining
    response = client.put_resource_policy(resourceArn=runtime_arn, policy=json.dumps(document))
    return True, _request_id(response)


def derive_state(stopped_in_loom: bool, deny_present: bool | None) -> str:
    """Combine Loom's record with the runtime policy's live state.

    running              -- not stopped, no deny statement
    stopped              -- stopped, deny statement present
    stop_not_enforced    -- Loom records a stop, but the deny statement is gone
    stopped_outside_loom -- the deny statement is present, but Loom recorded no stop
    unknown              -- the runtime's policy could not be read
    """
    if deny_present is None:
        return "unknown"
    if stopped_in_loom:
        return "stopped" if deny_present else "stop_not_enforced"
    return "stopped_outside_loom" if deny_present else "running"


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


def stop_sessions(runtime_arn: str, region: str, sessions: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Call StopRuntimeSession for each session; one result per session, never raises.

    A session AgentCore no longer has is ``not_running``. Ending the sessions
    is what stops work already in progress: the deny only refuses new calls.
    """
    if not sessions:
        return []
    client = _agentcore_client(region)

    def _stop(item: tuple[str, str]) -> dict[str, Any]:
        sid, qualifier = item
        result: dict[str, Any] = {"session_id": sid, "qualifier": qualifier, "result": "stopped",
                                  "request_id": None, "error": None}
        try:
            response = client.stop_runtime_session(
                agentRuntimeArn=runtime_arn, runtimeSessionId=sid, qualifier=qualifier,
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
