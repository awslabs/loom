"""Tests for the approval integration module."""
import json
import os
import unittest
from unittest.mock import patch, MagicMock

from integrations.approval import (
    ApprovalHook,
    check_access,
    _matches_tool,
    _matches_agent,
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


class TestApprovalHook(unittest.TestCase):
    def _make_hook(self, policies):
        return ApprovalHook(policies=policies)

    def test_find_matching_policy(self):
        hook = self._make_hook([
            {"name": "Guard DB", "policy_type": "loop_hook", "tool_match_rules": ["db_*"], "enabled": True},
            {"name": "Disabled", "policy_type": "loop_hook", "tool_match_rules": ["*"], "enabled": False},
            {"name": "Tool Context Only", "policy_type": "tool_context", "tool_match_rules": ["*"], "enabled": True},
        ])
        policy = hook._find_matching_policy("db_write")
        self.assertIsNotNone(policy)
        self.assertEqual(policy["name"], "Guard DB")

    def test_no_match_for_unrelated_tool(self):
        hook = self._make_hook([
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["db_*"], "enabled": True},
        ])
        self.assertIsNone(hook._find_matching_policy("file_read"))

    def test_empty_policies(self):
        hook = self._make_hook([])
        self.assertIsNone(hook._find_matching_policy("anything"))

    def test_notify_only_does_not_interrupt(self):
        hook = self._make_hook([
            {"name": "Notify", "policy_type": "loop_hook", "tool_match_rules": ["*"],
             "approval_mode": "notify_only", "enabled": True},
        ])
        event = MagicMock()
        event.tool_use = {"name": "some_tool", "input": {}}
        event.agent.state.get.return_value = None
        hook._check_approval(event)
        event.interrupt.assert_not_called()

    def test_interrupt_called_for_matching_tool(self):
        hook = self._make_hook([
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["db_*"],
             "approval_mode": "require_approval", "timeout_seconds": 60, "enabled": True},
        ])
        event = MagicMock()
        event.tool_use = {"name": "db_write", "input": {"table": "users"}}
        event.agent.state.get.return_value = None
        event.interrupt.return_value = "y"

        hook._check_approval(event)
        event.interrupt.assert_called_once()
        call_args = event.interrupt.call_args
        self.assertEqual(call_args[0][0], "db_write-approval")
        reason = call_args[1]["reason"]
        self.assertEqual(reason["tool_name"], "db_write")

    def test_denied_sets_cancel_tool(self):
        hook = self._make_hook([
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["*"],
             "approval_mode": "require_approval", "enabled": True},
        ])
        event = MagicMock()
        event.tool_use = {"name": "dangerous_tool", "input": {}}
        event.agent.state.get.return_value = None
        event.interrupt.return_value = "n"

        hook._check_approval(event)
        self.assertIn("denied", event.cancel_tool)

    def test_trust_caches_in_state(self):
        hook = self._make_hook([
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["*"],
             "approval_mode": "require_approval", "enabled": True},
        ])
        event = MagicMock()
        event.tool_use = {"name": "my_tool", "input": {}}
        event.agent.state.get.return_value = None
        event.interrupt.return_value = "t"

        hook._check_approval(event)
        event.agent.state.set.assert_called_once_with("my_tool-approval", "t")

    def test_cached_approval_skips_interrupt(self):
        hook = self._make_hook([
            {"name": "Guard", "policy_type": "loop_hook", "tool_match_rules": ["*"],
             "approval_mode": "require_approval", "enabled": True},
        ])
        event = MagicMock()
        event.tool_use = {"name": "my_tool", "input": {}}
        event.agent.state.get.return_value = "t"

        hook._check_approval(event)
        event.interrupt.assert_not_called()

    @patch.dict(os.environ, {"LOOM_APPROVAL_POLICIES": json.dumps([
        {"name": "Env", "policy_type": "loop_hook", "tool_match_rules": ["*"], "enabled": True}
    ])})
    def test_loads_from_env(self):
        hook = ApprovalHook()
        self.assertEqual(len(hook.policies), 1)
        self.assertEqual(hook.policies[0]["name"], "Env")


class TestCheckAccess(unittest.TestCase):
    def _make_context(self, user_role=None, state_overrides=None):
        ctx = MagicMock()
        state = state_overrides or {}
        ctx.agent.state.get.side_effect = lambda k: state.get(k, user_role if k == "user_role" else None)
        ctx.interrupt.return_value = "y"
        return ctx

    def test_wrong_role_denied(self):
        ctx = self._make_context(user_role="Nurse")
        result = check_access(ctx, "patient-123", "read-records", required_role="Physician")
        self.assertIsNotNone(result)
        self.assertIn("Access denied", result)
        ctx.interrupt.assert_not_called()

    def test_correct_role_prompts_interrupt(self):
        ctx = self._make_context(user_role="Physician")
        result = check_access(ctx, "patient-123", "read-records", required_role="Physician")
        self.assertIsNone(result)
        ctx.interrupt.assert_called_once()

    def test_denied_by_user(self):
        ctx = self._make_context(user_role="Physician")
        ctx.interrupt.return_value = "n"
        result = check_access(ctx, "patient-123", "read-records", required_role="Physician")
        self.assertIsNotNone(result)
        self.assertIn("denied", result)

    def test_trust_caches(self):
        ctx = self._make_context(user_role="Physician")
        ctx.interrupt.return_value = "t"
        result = check_access(ctx, "patient-123", "read-records", required_role="Physician")
        self.assertIsNone(result)
        ctx.agent.state.set.assert_called_once_with("read-records-patient-123-approval", "t")

    def test_no_role_required(self):
        ctx = self._make_context(user_role="")
        result = check_access(ctx, "res-1", "action", required_role="")
        self.assertIsNone(result)
        ctx.interrupt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
