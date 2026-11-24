"""End-to-end approval enforcement through the real ADK runner.

The unit tests in test_approval.py check the matcher and predicates in
isolation. These run an actual ``LlmAgent`` with a scripted model, so they
fail if a tool call reaches its tool without the approval policy being
applied, whatever the tool's class:

- An A2A agent is attached as an ``AgentTool``, which never consulted the
  patched ``check_require_confirmation`` itself. ``ApprovalPlugin`` is now the
  enforcement point for every tool, so these tests run with the plugin only
  (no per-tool patching) to prove it doesn't depend on ADK's own gate.
- The code interpreter is one tool per operation here, so a rule named
  ``code_interpreter`` must still gate ``code_interpreter_execute_code``.
"""
import asyncio
import unittest
from typing import Any, AsyncGenerator

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from src.integrations.approval import ApprovalPlugin, ApprovalPolicyMatcher, _match_names

CONFIRMATION_CALL = "adk_request_confirmation"


class _ScriptedLlm(BaseLlm):
    """Calls one named tool on its first turn, then answers with text."""

    model: str = "scripted"
    tool_name: str = ""
    called: bool = False

    async def generate_content_async(self, llm_request: Any, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        if not self.called and self.tool_name:
            self.called = True
            args = {"request": "hello"} if self.tool_name == "remote_partner" else {"code": "print(1)"}
            part = types.Part(function_call=types.FunctionCall(name=self.tool_name, args=args))
        else:
            part = types.Part(text="done")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


class _CountingLlm(BaseLlm):
    """Stands in for the remote A2A agent; counts how often it runs."""

    model: str = "remote"
    runs: int = 0

    async def generate_content_async(self, llm_request: Any, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        self.runs += 1
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="remote ran")]))


def _policy(rules: list[str], mode: str = "require_approval") -> dict[str, Any]:
    return {
        "name": "gate", "enabled": True, "policy_type": "loop_hook",
        "approval_mode": mode, "tool_match_rules": rules,
    }


class _Harness:
    def __init__(self, tool_name: str, policies: list[dict[str, Any]]) -> None:
        self.remote_llm = _CountingLlm()
        self.code_runs = 0

        def code_interpreter_execute_code(code: str = "") -> dict:
            self.code_runs += 1
            return {"ok": True}

        remote = LlmAgent(name="remote_partner", model=self.remote_llm, description="stand-in A2A agent")
        tools = [AgentTool(agent=remote), FunctionTool(code_interpreter_execute_code)]
        root = LlmAgent(name="root", model=_ScriptedLlm(tool_name=tool_name), tools=tools)
        # Plugin only, deliberately: no apply_confirmation_to_tools.
        self.runner = InMemoryRunner(
            agent=root, app_name="t", plugins=[ApprovalPlugin(ApprovalPolicyMatcher(policies=policies))],
        )

    def run(self) -> bool:
        """Run one turn; True if the agent asked for confirmation."""
        async def _go() -> bool:
            session = await self.runner.session_service.create_session(app_name="t", user_id="u")
            paused = False
            message = types.Content(role="user", parts=[types.Part(text="go")])
            async for event in self.runner.run_async(user_id="u", session_id=session.id, new_message=message):
                for part in (event.content.parts if event.content else None) or []:
                    if part.function_call and part.function_call.name == CONFIRMATION_CALL:
                        paused = True
            return paused
        return asyncio.run(_go())


class TestA2aAgentToolIsGated(unittest.TestCase):
    def test_empty_rule_pauses_the_a2a_call(self) -> None:
        h = _Harness("remote_partner", [_policy([])])
        self.assertTrue(h.run())
        self.assertEqual(h.remote_llm.runs, 0, "the A2A agent ran without approval")

    def test_star_rule_pauses_the_a2a_call(self) -> None:
        h = _Harness("remote_partner", [_policy(["*"])])
        self.assertTrue(h.run())
        self.assertEqual(h.remote_llm.runs, 0)

    def test_no_policy_lets_the_a2a_call_through(self) -> None:
        """Positive control: the harness really does reach the remote agent."""
        h = _Harness("remote_partner", [])
        self.assertFalse(h.run())
        self.assertEqual(h.remote_llm.runs, 1)

    def test_notify_only_does_not_pause(self) -> None:
        h = _Harness("remote_partner", [_policy(["*"], mode="notify_only")])
        self.assertFalse(h.run())
        self.assertEqual(h.remote_llm.runs, 1)


class TestCodeInterpreterRuleNames(unittest.TestCase):
    def test_family_rule_pauses_execute_code(self) -> None:
        h = _Harness("code_interpreter_execute_code", [_policy(["code_interpreter"])])
        self.assertTrue(h.run())
        self.assertEqual(h.code_runs, 0, "code_interpreter rule missed the ADK operation")

    def test_operation_rule_and_globs_still_match(self) -> None:
        for rules in (["code_interpreter_execute_code"], ["code_interpreter*"], ["*"], []):
            with self.subTest(rules=rules):
                h = _Harness("code_interpreter_execute_code", [_policy(rules)])
                self.assertTrue(h.run())
                self.assertEqual(h.code_runs, 0)

    def test_unrelated_rule_does_not_match(self) -> None:
        h = _Harness("code_interpreter_execute_code", [_policy(["browser*"])])
        self.assertFalse(h.run())
        self.assertEqual(h.code_runs, 1)

    def test_match_names(self) -> None:
        self.assertEqual(_match_names("code_interpreter_execute_command"),
                         ["code_interpreter_execute_command", "code_interpreter"])
        self.assertEqual(_match_names("remote_partner"), ["remote_partner"])
        # A tool merely named like the family isn't aliased to anything else.
        self.assertEqual(_match_names("code_interpreterx"), ["code_interpreterx"])


if __name__ == "__main__":
    unittest.main()
