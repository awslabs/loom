"""Tests for the approval integration module."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from src.integrations.approval import (
    ApprovalPolicyMatcher,
    apply_confirmation_to_tools,
    build_confirmation_predicate,
    check_access,
    _matches_agent,
    _matches_tool,
)


class TestMatchesTool(unittest.TestCase):
    def test_empty_rules_match_all(self):
        self.assertTrue(_matches_tool("any_tool", []))

    def test_exact_match(self):
        self.assertTrue(_matches_tool("db_write", ["db_write"]))

    def test_glob_match(self):
        self.assertTrue(_matches_tool("db_write", ["db_*"]))

    def test_no_match(self):
        self.assertFalse(_matches_tool("file_read", ["db_*"]))

    def test_multiple_rules(self):
        self.assertTrue(_matches_tool("file_write", ["db_*", "file_*"]))


class TestMatchesAgent(unittest.TestCase):
    def test_scope_all(self):
        policy = {"agent_scope": {"type": "all"}}
        self.assertTrue(_matches_agent(policy, {"env": "prod"}))

    def test_scope_tag_filter_match(self):
        policy = {"agent_scope": {"type": "tag_filter", "tag_key": "env", "tag_value": "prod"}}
        self.assertTrue(_matches_agent(policy, {"env": "prod"}))

    def test_scope_tag_filter_no_match(self):
        policy = {"agent_scope": {"type": "tag_filter", "tag_key": "env", "tag_value": "prod"}}
        self.assertFalse(_matches_agent(policy, {"env": "staging"}))

    def test_scope_default_all(self):
        policy = {}
        self.assertTrue(_matches_agent(policy, None))


class TestApprovalPolicyMatcher(unittest.TestCase):
    def _make_matcher(self, policies):
        return ApprovalPolicyMatcher(policies=policies)

    def test_find_matching_policy(self):
        matcher = self._make_matcher([
            {"name": "Guard DB", "policy_type": "loop_hook", "tool_match_rules": ["db_*"], "enabled": True},
            {"name": "Disabled", "policy_type": "loop_hook", "tool_match_rules": ["*"], "enabled": False},
            {"name": "Tool Context Only", "policy_type": "tool_context", "tool_match_rules": ["*"], "enabled": True},
        ])
        policy = matcher.find_matching_policy("db_write")
        self.assertIsNotNone(policy)
        self.assertEqual(policy["name"], "Guard DB")

    def test_no_match_for_unrelated_tool(self):
        matcher = self._make_matcher([
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["db_*"], "enabled": True},
        ])
        self.assertIsNone(matcher.find_matching_policy("file_read"))

    def test_empty_policies(self):
        matcher = self._make_matcher([])
        self.assertIsNone(matcher.find_matching_policy("anything"))

    @patch.dict(os.environ, {"LOOM_APPROVAL_POLICIES": json.dumps([
        {"name": "Env", "policy_type": "loop_hook", "tool_match_rules": ["*"], "enabled": True}
    ])})
    def test_loads_from_env(self):
        matcher = ApprovalPolicyMatcher()
        self.assertEqual(len(matcher.policies), 1)
        self.assertEqual(matcher.policies[0]["name"], "Env")


def _make_tool_context(state=None, tool_confirmation=None):
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx.tool_confirmation = tool_confirmation
    return ctx


class TestBuildConfirmationPredicate(unittest.TestCase):
    def test_notify_only_does_not_require_confirmation(self):
        matcher = ApprovalPolicyMatcher(policies=[
            {"name": "Notify", "policy_type": "loop_hook", "tool_match_rules": ["*"],
             "approval_mode": "notify_only", "enabled": True},
        ])
        predicate = build_confirmation_predicate("some_tool", matcher)
        result = predicate(tool_context=_make_tool_context())
        self.assertFalse(result)

    def test_requires_confirmation_for_matching_tool(self):
        matcher = ApprovalPolicyMatcher(policies=[
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["db_*"],
             "approval_mode": "require_approval", "enabled": True},
        ])
        predicate = build_confirmation_predicate("db_write", matcher)
        result = predicate(tool_context=_make_tool_context())
        self.assertTrue(result)

    def test_no_confirmation_for_non_matching_tool(self):
        matcher = ApprovalPolicyMatcher(policies=[
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["db_*"], "enabled": True},
        ])
        predicate = build_confirmation_predicate("file_read", matcher)
        result = predicate(tool_context=_make_tool_context())
        self.assertFalse(result)

    def test_trust_payload_caches_in_state(self):
        matcher = ApprovalPolicyMatcher(policies=[
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["*"], "enabled": True},
        ])
        predicate = build_confirmation_predicate("my_tool", matcher)
        confirmation = MagicMock(confirmed=True, payload={"trust": True})
        state = {}
        predicate(tool_context=_make_tool_context(state=state, tool_confirmation=confirmation))
        self.assertEqual(state["my_tool-approval"], "t")

    def test_cached_trust_skips_confirmation(self):
        matcher = ApprovalPolicyMatcher(policies=[
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["*"], "enabled": True},
        ])
        predicate = build_confirmation_predicate("my_tool", matcher)
        state = {"my_tool-approval": "t"}
        result = predicate(tool_context=_make_tool_context(state=state))
        self.assertFalse(result)

    def test_confirmed_without_trust_does_not_cache(self):
        matcher = ApprovalPolicyMatcher(policies=[
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["*"], "enabled": True},
        ])
        predicate = build_confirmation_predicate("my_tool", matcher)
        confirmation = MagicMock(confirmed=True, payload=None)
        state = {}
        predicate(tool_context=_make_tool_context(state=state, tool_confirmation=confirmation))
        self.assertNotIn("my_tool-approval", state)


class TestApplyConfirmationToTools(unittest.TestCase):
    def test_patches_check_require_confirmation(self):
        import asyncio

        tool = MagicMock()
        tool.name = "danger_tool"
        matcher = ApprovalPolicyMatcher(policies=[
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["danger_*"], "enabled": True},
        ])
        apply_confirmation_to_tools([tool], matcher)

        result = asyncio.run(tool.check_require_confirmation({}, _make_tool_context()))
        self.assertTrue(result)

    def test_non_matching_tool_does_not_require_confirmation(self):
        import asyncio

        tool = MagicMock()
        tool.name = "safe_tool"
        matcher = ApprovalPolicyMatcher(policies=[
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["danger_*"], "enabled": True},
        ])
        apply_confirmation_to_tools([tool], matcher)

        result = asyncio.run(tool.check_require_confirmation({}, _make_tool_context()))
        self.assertFalse(result)


class TestCheckAccess(unittest.TestCase):
    def _make_context(self, user_role=None, confirmed=True, trust=False):
        state = {"user_role": user_role} if user_role else {}
        confirmation = MagicMock(confirmed=confirmed, payload={"trust": True} if trust else None)
        ctx = MagicMock()
        ctx.state = state
        ctx.tool_confirmation = confirmation
        return ctx

    def test_wrong_role_denied(self):
        ctx = self._make_context(user_role="Nurse")
        result = check_access(ctx, "patient-123", "read-records", required_role="Physician")
        self.assertIsNotNone(result)
        self.assertIn("Access denied", result)

    def test_correct_role_approved(self):
        ctx = self._make_context(user_role="Physician", confirmed=True)
        result = check_access(ctx, "patient-123", "read-records", required_role="Physician")
        self.assertIsNone(result)

    def test_denied_by_user(self):
        ctx = self._make_context(user_role="Physician", confirmed=False)
        result = check_access(ctx, "patient-123", "read-records", required_role="Physician")
        self.assertIsNotNone(result)
        self.assertIn("denied", result)

    def test_trust_caches(self):
        ctx = self._make_context(user_role="Physician", confirmed=True, trust=True)
        result = check_access(ctx, "patient-123", "read-records", required_role="Physician")
        self.assertIsNone(result)
        self.assertEqual(ctx.state["read-records-patient-123-approval"], "t")

    def test_no_role_required(self):
        ctx = self._make_context(user_role="", confirmed=True)
        result = check_access(ctx, "res-1", "action", required_role="")
        self.assertIsNone(result)

    def test_cached_trust_skips_confirmation_check(self):
        ctx = self._make_context(user_role="Physician", confirmed=False)
        ctx.state["action-res-1-approval"] = "t"
        result = check_access(ctx, "res-1", "action", required_role="Physician")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
