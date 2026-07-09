"""Human-in-the-loop approval integration for Strands agents.

Implements HITL patterns using the Strands SDK interrupt mechanism:

1. **ApprovalHook** (Method 1) — A ``HookProvider`` that registers a
   ``BeforeToolCallEvent`` callback. When a tool call matches configured
   approval policies, the hook calls ``event.interrupt()`` which pauses
   the agent and returns control to the caller.

2. **Tool Context** (Method 2) — Individual tools can use
   ``tool_context.interrupt()`` directly within their implementation for
   fine-grained, tool-specific approval logic.

Both patterns produce interrupts that the entrypoint handler detects via
``result.stop_reason == "interrupt"`` and relays to the caller as
structured events. The caller resumes the agent by re-invoking with
``interruptResponse`` payloads.

Reference implementations:
  - Method 1: github.com/aws-samples/sample-human-in-the-loop-patterns/method1_hook
  - Method 2: github.com/aws-samples/sample-human-in-the-loop-patterns/method2_tool_context
"""

import fnmatch
import json
import logging
import os
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

logger = logging.getLogger(__name__)


def _load_policies() -> list[dict[str, Any]]:
    raw = os.environ.get("LOOM_APPROVAL_POLICIES", "[]")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LOOM_APPROVAL_POLICIES")
        return []


def _matches_tool(tool_name: str, rules: list[str]) -> bool:
    if not rules:
        return True
    return any(fnmatch.fnmatch(tool_name, pattern) for pattern in rules)


def _matches_agent(policy: dict[str, Any], agent_tags: dict[str, str] | None = None) -> bool:
    scope = policy.get("agent_scope", {"type": "all"})
    scope_type = scope.get("type", "all")
    if scope_type == "all":
        return True
    if scope_type == "tag_filter" and agent_tags:
        key = scope.get("tag_key", "")
        value = scope.get("tag_value", "")
        return agent_tags.get(key) == value
    return True


class ApprovalHook(HookProvider):
    """Strands HookProvider that intercepts tool calls requiring approval.

    Registered as a hook on the Agent instance. When a tool call matches
    an approval policy, calls ``event.interrupt()`` to pause the agent.
    The agent returns with ``result.stop_reason == "interrupt"`` and a list
    of pending interrupts. The caller sends ``interruptResponse`` payloads
    to resume execution.

    Supports per-session "trust" caching: if the user responds "t" (trust),
    subsequent calls to the same tool in that session are auto-approved via
    agent state.

    Usage::

        agent = Agent(
            hooks=[ApprovalHook()],
            tools=[...],
        )

    The hook reads policies from the LOOM_APPROVAL_POLICIES environment
    variable (JSON array) or from an explicit list passed at construction.
    """

    def __init__(
        self,
        policies: list[dict[str, Any]] | None = None,
        agent_tags: dict[str, str] | None = None,
    ):
        self.policies = policies if policies is not None else _load_policies()
        self.agent_tags = agent_tags or {}

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._check_approval)

    def _check_approval(self, event: BeforeToolCallEvent) -> None:
        tool_name = event.tool_use["name"]
        policy = self._find_matching_policy(tool_name)
        if policy is None:
            return

        approval_mode = policy.get("approval_mode", "require_approval")
        if approval_mode == "notify_only":
            return

        approval_key = f"{tool_name}-approval"
        if event.agent.state.get(approval_key) == "t":
            return

        tool_input = event.tool_use.get("input", {})
        input_summary = str(tool_input)[:500] if tool_input else ""

        approval = event.interrupt(
            approval_key,
            reason={
                "reason": f"Authorize {tool_name}",
                "tool_name": tool_name,
                "tool_input_summary": input_summary,
                "policy_name": policy.get("name", ""),
                "policy_type": policy.get("policy_type", "loop_hook"),
                "approval_mode": approval_mode,
                "timeout_seconds": policy.get("timeout_seconds", 300),
            },
        )

        if approval.lower() not in ["y", "yes", "t", "approved"]:
            event.cancel_tool = f"User denied permission to run {tool_name}"
            return

        if approval.lower() == "t":
            event.agent.state.set(approval_key, "t")

    def _find_matching_policy(self, tool_name: str) -> dict[str, Any] | None:
        for policy in self.policies:
            if not policy.get("enabled", True):
                continue
            if policy.get("policy_type") not in ("loop_hook", None):
                continue
            if not _matches_agent(policy, self.agent_tags):
                continue
            if _matches_tool(tool_name, policy.get("tool_match_rules", [])):
                return policy
        return None


def check_access(tool_context, resource_id: str, action: str, required_role: str = ""):
    """Role-based approval check for Method 2 (tool context interrupt).

    Call this inside a ``@tool(context=True)`` function to implement
    fine-grained, per-operation approval with role-based access control.

    Returns None if approved, or a denial message string.

    Usage::

        @tool(context=True)
        def sensitive_tool(tool_context, patient_id: str) -> str:
            denial = check_access(tool_context, patient_id, "read-records", required_role="Physician")
            if denial:
                return denial
            return do_sensitive_thing()
    """
    user_role = tool_context.agent.state.get("user_role") or ""

    if required_role and user_role != required_role:
        return f"Access denied: {action} for {resource_id} requires {required_role} role (current: {user_role or 'none'})"

    approval_key = f"{action}-{resource_id}-approval"
    if tool_context.agent.state.get(approval_key) == "t":
        return None

    approval = tool_context.interrupt(
        approval_key,
        reason={"reason": f"[{user_role or 'user'}] Authorize {action} for {resource_id}"},
    )
    if approval.lower() not in ["y", "yes", "t", "approved"]:
        return f"User denied access to {action} for {resource_id}"

    if approval.lower() == "t":
        tool_context.agent.state.set(approval_key, "t")

    return None
