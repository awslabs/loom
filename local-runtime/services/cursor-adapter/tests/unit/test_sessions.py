import unittest

from cursor_adapter.adapters.outbound.memory_sessions import SessionManager


class TestSessions(unittest.TestCase):
    def test_create_and_reuse(self) -> None:
        clock = {"t": 100.0}
        manager = SessionManager(ttl_seconds=60, now=lambda: clock["t"])
        key = manager.make_key("local", "agent-1", "/ws", "sess-1")
        manager.put(key, "cursor-abc", "/ws")
        self.assertEqual(manager.get(key).cursor_agent_id, "cursor-abc")

    def test_expire(self) -> None:
        clock = {"t": 0.0}
        manager = SessionManager(ttl_seconds=10, now=lambda: clock["t"])
        key = manager.make_key("local", "a", "/ws", "s")
        manager.put(key, "old", "/ws")
        clock["t"] = 11.0
        self.assertIsNone(manager.get(key))

    def test_lock_is_stable(self) -> None:
        manager = SessionManager()
        key = manager.make_key("t", "a", "/w", "s")
        self.assertIs(manager.lock_for(key), manager.lock_for(key))

    def test_invalid_workspace_rejected_by_runner(self) -> None:
        from cursor_adapter.adapters.outbound.sdk_runner import run_prompt
        from cursor_adapter.domain.errors import AdapterError

        with self.assertRaises(AdapterError) as ctx:
            run_prompt(
                [{"role": "user", "content": "hi"}],
                workspace="C:\\definitely-not-a-real-workspace-dir-xyz",
                session_id=None,
                agent_id=None,
                sessions=SessionManager(),
                api_key="cursor_test",
                launch=lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not launch")),
            )
        self.assertEqual(ctx.exception.code, "invalid_workspace")


if __name__ == "__main__":
    unittest.main()
