"""Human-in-the-loop approval integration for ADK agents.

Ports the same policy semantics as ``agents/strands_agent/src/integrations/approval.py``
(same env var, same policy dict shape, same matching rules) onto ADK's HITL
primitive, which differs structurally from Strands' interrupt mechanism:

- Strands: any tool call is checked at call time by a ``BeforeToolCallEvent``
  hook, which calls ``event.interrupt()`` dynamically for a matching policy.
- ADK: each ``FunctionTool`` declares (statically or via a per-call predicate)
  whether it ``require_confirmation``. The framework itself pauses execution
  and returns an ``adk_request_confirmation`` function call; the caller
  resumes with a ``FunctionResponse`` carrying a ``ToolConfirmation`` (a
  ``confirmed`` bool plus an optional free-form ``payload``).

``build_confirmation_predicate()`` bridges the two: it returns a callable
suitable for ``FunctionTool(func, require_confirmation=...)`` that runs the
exact same policy-matching logic as Strands, evaluated per call against the
tool's args. Because ADK's ``confirmed`` bool has no room for Strands'
"trust for the rest of this session" semantics, trust is carried in the
confirmation's ``payload`` (``{"trust": true}``) and cached in
``tool_context.state`` exactly like Strands caches it in ``agent.state``.

The handler-side wire format Loom's backend/frontend already speak
(``interruptResponse``/``approval_policies``) is translated to/from ADK's
function-response-keyed resume shape in ``src/handler.py`` — this module
only implements the policy-matching and confirmation-predicate/trust-cache
logic, matching Strands' module boundary.

Reference implementations:
  - Method 1: github.com/aws-samples/sample-human-in-the-loop-patterns/method1_hook
  - Method 2: github.com/aws-samples/sample-human-in-the-loop-patterns/method2_tool_context
"""

import fnmatch
import json
import logging
import os
import types
from typing import Any, Callable

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

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


class ApprovalPolicyMatcher:
    """Holds the active approval policies and matches tool calls against them.

    Mirrors Strands' ``ApprovalHook`` policy semantics exactly (same env var,
    same policy dict shape, same matching precedence), but exposes a
    ``find_matching_policy`` method rather than registering a hook callback,
    since ADK's integration point is a per-tool ``require_confirmation``
    predicate rather than a ``BeforeToolCallEvent`` callback.
    """

    def __init__(
        self,
        policies: list[dict[str, Any]] | None = None,
        agent_tags: dict[str, str] | None = None,
    ):
        self.policies = policies if policies is not None else _load_policies()
        self.agent_tags = agent_tags or {}

    def find_matching_policy(self, tool_name: str) -> dict[str, Any] | None:
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


def build_confirmation_predicate(
    tool_name: str, matcher: ApprovalPolicyMatcher
) -> Callable[..., bool]:
    """Build a ``require_confirmation`` predicate for ``FunctionTool``.

    ADK calls this predicate with the wrapped tool's *own* call kwargs
    (filtered to the parameter names the tool function declares — see
    ``FunctionTool._prepare_invocation_args``/``check_require_confirmation``),
    not a fixed ``(args, tool_context)`` signature. Every tool built by this
    agent (see ``agent.py``, ``mcp_client.py``, ``a2a_client.py``) declares an
    explicit ``tool_context: ToolContext`` parameter so it's always present
    in those kwargs; the predicate takes ``**kwargs`` and pulls it out rather
    than assuming a fixed positional shape.

    The predicate is evaluated by ADK on every call to the wrapped tool
    (see ``FunctionTool.run_async``). Returning ``True`` when there is no
    prior ``tool_context.tool_confirmation`` causes ADK to pause and request
    one; returning ``True`` again on the resumed call (now with
    ``tool_confirmation`` populated) is required so the framework applies the
    ``confirmed``/rejection gate — ``FunctionTool.run_async`` calls this
    predicate unconditionally on every invocation, not just the first.

    A "trust" response (``payload={"trust": true}``) is cached in
    ``tool_context.state`` under the same key shape Strands uses
    (``f"{tool_name}-approval"``), so a trusted tool skips confirmation for
    the remainder of the session — matching Strands' trust-cache behavior.
    """

    def predicate(**kwargs: Any) -> bool:
        tool_context: ToolContext = kwargs["tool_context"]
        approval_key = f"{tool_name}-approval"
        if tool_context.state.get(approval_key) == "t":
            return False

        policy = matcher.find_matching_policy(tool_name)
        if policy is None:
            return False

        approval_mode = policy.get("approval_mode", "require_approval")
        if approval_mode == "notify_only":
            return False

        confirmation = tool_context.tool_confirmation
        if confirmation is not None and confirmation.confirmed:
            payload = confirmation.payload or {}
            if isinstance(payload, dict) and payload.get("trust"):
                tool_context.state[approval_key] = "t"

        return True

    return predicate


def apply_confirmation_to_tools(tools: list[BaseTool], matcher: ApprovalPolicyMatcher) -> None:
    """Patch ``check_require_confirmation`` on framework-generated tools.

    MCP-sourced tools (built by ``McpToolset.get_tools()``) and A2A/other
    tool objects the agent doesn't construct via ``FunctionTool(...,
    require_confirmation=...)`` directly can't take a
    ``build_confirmation_predicate``-style ``**kwargs`` predicate, because
    those tool classes' own ``check_require_confirmation`` inspects the
    *predicate's* signature to decide which args to forward, and won't
    always thread through ``tool_context`` the way a hand-written
    ``FunctionTool`` does. Rebinding the method directly on each tool
    instance (where ``self.name`` — the real tool name to match policies
    against — is available as ``self``) sidesteps that entirely; it works
    for any ``BaseTool`` subclass since only ``check_require_confirmation``'s
    call signature is standardized, not how ``require_confirmation`` is wired
    at construction time.
    """
    for tool in tools:
        async def _check_require_confirmation(
            self: BaseTool, args: dict[str, Any], tool_context: ToolContext
        ) -> bool:
            approval_key = f"{self.name}-approval"
            if tool_context.state.get(approval_key) == "t":
                return False
            policy = matcher.find_matching_policy(self.name)
            if policy is None:
                return False
            if policy.get("approval_mode", "require_approval") == "notify_only":
                return False
            confirmation = tool_context.tool_confirmation
            if confirmation is not None and confirmation.confirmed:
                payload = confirmation.payload or {}
                if isinstance(payload, dict) and payload.get("trust"):
                    tool_context.state[approval_key] = "t"
            return True

        tool.check_require_confirmation = types.MethodType(_check_require_confirmation, tool)


def check_access(
    tool_context: ToolContext, resource_id: str, action: str, required_role: str = ""
) -> str | None:
    """Role-based approval check for Method 2 (fine-grained per-operation access).

    Call this at the start of a tool function body to implement per-operation
    approval with role-based access control, mirroring Strands'
    ``check_access`` helper. Unlike Strands' variant (which blocks inline via
    ``tool_context.interrupt()``), ADK has no in-tool blocking primitive —
    the tool must be wrapped with a ``require_confirmation`` predicate (see
    ``build_confirmation_predicate``) so the framework has already paused and
    resumed the call by the time this function runs; this helper only
    evaluates the role/trust decision once confirmation is available.

    Returns None if approved, or a denial message string.
    """
    user_role = tool_context.state.get("user_role") or ""

    if required_role and user_role != required_role:
        return f"Access denied: {action} for {resource_id} requires {required_role} role (current: {user_role or 'none'})"

    approval_key = f"{action}-{resource_id}-approval"
    if tool_context.state.get(approval_key) == "t":
        return None

    confirmation = tool_context.tool_confirmation
    if confirmation is None or not confirmation.confirmed:
        return f"User denied access to {action} for {resource_id}"

    payload = confirmation.payload or {}
    if isinstance(payload, dict) and payload.get("trust"):
        tool_context.state[approval_key] = "t"

    return None
