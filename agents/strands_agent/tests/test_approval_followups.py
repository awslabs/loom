"""Approval matching across frameworks, and refusal on non-interactive channels."""
import unittest
from typing import Any
from unittest.mock import MagicMock

from src.integrations.approval import (
    NON_INTERACTIVE_STATE_KEY,
    ApprovalHook,
    _match_names,
    _matches_tool,
)


def _ci_input(action_type: str) -> dict[str, Any]:
    return {"code_interpreter_input": {"action": {"type": action_type, "code": "print(1)"}}}


def _hook(rules: list[str]) -> ApprovalHook:
    return ApprovalHook(policies=[{
        "name": "Guard", "policy_type": "loop_hook", "tool_match_rules": rules,
        "approval_mode": "require_approval", "enabled": True,
    }])


def _event(name: str, tool_input: Any, state: dict[str, Any] | None = None) -> MagicMock:
    event = MagicMock()
    event.tool_use = {"name": name, "input": tool_input}
    values = state or {}
    event.agent.state.get.side_effect = lambda key: values.get(key)
    event.interrupt.return_value = "y"
    event.cancel_tool = None
    return event


class TestCodeInterpreterNames(unittest.TestCase):
    """The ADK agent names its code interpreter tools per operation
    (code_interpreter_execute_code, ...); a rule written that way must gate the
    matching Strands operation too, and the family name must still gate all."""

    def test_operation_names_derived_from_action(self) -> None:
        self.assertEqual(_match_names("code_interpreter", _ci_input("executeCode")),
                         ["code_interpreter", "code_interpreter_execute_code"])
        self.assertEqual(_match_names("code_interpreter", _ci_input("writeFiles")),
                         ["code_interpreter", "code_interpreter_write_files"])

    def test_operation_rule_gates_only_that_operation(self) -> None:
        rules = ["code_interpreter_execute_code"]
        self.assertTrue(_matches_tool("code_interpreter", rules, _ci_input("executeCode")))
        self.assertFalse(_matches_tool("code_interpreter", rules, _ci_input("readFiles")))

    def test_family_and_glob_rules_still_gate_everything(self) -> None:
        for rules in (["code_interpreter"], ["code_interpreter*"], ["*"], []):
            with self.subTest(rules=rules):
                self.assertTrue(_matches_tool("code_interpreter", rules, _ci_input("executeCommand")))

    def test_adk_spelling_also_answers_to_the_family_name(self) -> None:
        self.assertTrue(_matches_tool("code_interpreter_execute_code", ["code_interpreter"]))

    def test_malformed_input_falls_back_to_the_tool_name(self) -> None:
        for bad in (None, "x", {}, {"code_interpreter_input": "x"}, {"code_interpreter_input": {"action": "x"}}):
            with self.subTest(bad=bad):
                self.assertEqual(_match_names("code_interpreter", bad), ["code_interpreter"])

    def test_hook_interrupts_for_an_adk_style_rule(self) -> None:
        event = _event("code_interpreter", _ci_input("executeCode"))
        _hook(["code_interpreter_execute_code"])._check_approval(event)
        event.interrupt.assert_called_once()


class TestNonInteractiveChannel(unittest.TestCase):
    """The WebSocket path can't relay an approval request and resume, so a
    gated tool is refused there instead of running or leaving a pending
    interrupt."""

    def test_gated_tool_is_cancelled_without_interrupting(self) -> None:
        event = _event("db_write", {}, {NON_INTERACTIVE_STATE_KEY: True})
        _hook(["*"])._check_approval(event)
        event.interrupt.assert_not_called()
        self.assertIn("requires approval", event.cancel_tool)

    def test_ungated_tool_still_runs(self) -> None:
        event = _event("read_only", {}, {NON_INTERACTIVE_STATE_KEY: True})
        _hook(["db_*"])._check_approval(event)
        event.interrupt.assert_not_called()
        self.assertIsNone(event.cancel_tool)

    def test_session_trust_still_applies(self) -> None:
        event = _event("db_write", {}, {NON_INTERACTIVE_STATE_KEY: True, "db_write-approval": "t"})
        _hook(["*"])._check_approval(event)
        event.interrupt.assert_not_called()
        self.assertIsNone(event.cancel_tool)

    def test_interactive_channel_still_interrupts(self) -> None:
        """Positive control: without the flag the same call pauses for approval."""
        event = _event("db_write", {})
        _hook(["*"])._check_approval(event)
        event.interrupt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
