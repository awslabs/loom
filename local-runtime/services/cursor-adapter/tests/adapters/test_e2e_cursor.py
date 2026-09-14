import os
import unittest


@unittest.skipUnless(os.getenv("CURSOR_API_KEY"), "real Cursor e2e is opt-in; never run in CI without a key")
class TestCursorE2E(unittest.TestCase):
    def test_analyze_workspace(self) -> None:
        from cursor_adapter.adapters.outbound.memory_sessions import SessionManager
        from cursor_adapter.adapters.outbound.sdk_runner import run_prompt

        workspace = os.environ.get("CURSOR_WORKSPACE")
        result = run_prompt(
            [{
                "role": "user",
                "content": "Analise este repositório e identifique oportunidades de melhoria arquitetural.",
            }],
            workspace=workspace,
            session_id="e2e-local",
            agent_id="e2e",
            sessions=SessionManager(),
        )
        self.assertEqual(result["object"], "chat.completion")
        self.assertTrue(result["choices"][0]["message"]["content"])


if __name__ == "__main__":
    unittest.main()
