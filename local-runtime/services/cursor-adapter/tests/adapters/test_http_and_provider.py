import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from cursor_adapter.errors import AdapterError
from cursor_adapter.http_app import bind_address, handle_chat_completions
from cursor_adapter.sdk_runner import run_prompt
from cursor_adapter.sessions import SessionManager


class TestHttpContract(unittest.TestCase):
    def test_bind_defaults_to_loopback(self) -> None:
        with patch.dict(os.environ, {"CURSOR_ADAPTER_HOST": "", "CURSOR_ADAPTER_PORT": ""}, clear=False):
            os.environ.pop("CURSOR_ADAPTER_HOST", None)
            os.environ.pop("CURSOR_ADAPTER_PORT", None)
            self.assertEqual(bind_address(), ("127.0.0.1", 8765))

    def test_bind_reads_compose_env(self) -> None:
        with patch.dict(os.environ, {"CURSOR_ADAPTER_HOST": "0.0.0.0", "CURSOR_ADAPTER_PORT": "8765"}):
            self.assertEqual(bind_address(), ("0.0.0.0", 8765))

    def test_auth_missing(self) -> None:
        with patch.dict(os.environ, {"CURSOR_API_KEY": "", "CURSOR_WORKSPACE": ""}, clear=False):
            status, body, streamed = handle_chat_completions(
                {"messages": [{"role": "user", "content": "hi"}]},
                {},
            )
        self.assertFalse(streamed)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "cursor_auth_missing")

    def test_completion_shape_with_injected_launch(self) -> None:
        workspace = str(Path(__file__).resolve().parents[3])  # repo root-ish; adapter dir parent chain
        # Use this tests directory as a guaranteed existing workspace.
        workspace = str(Path(__file__).resolve().parent)

        def launch(**kwargs):
            return {"status": "finished", "text": "ok", "agent_id": "ag-1", "run_id": "run-1"}

        sessions = SessionManager()
        result = run_prompt(
            [{"role": "user", "content": "hi"}],
            workspace=workspace,
            session_id="s1",
            agent_id="loom-1",
            sessions=sessions,
            api_key="cursor_test",
            launch=launch,
        )
        self.assertEqual(result["object"], "chat.completion")
        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        key = sessions.make_key("local", "loom-1", str(Path(workspace).resolve()), "s1")
        self.assertEqual(sessions.get(key).cursor_agent_id, "ag-1")

    def test_run_failed_maps_502(self) -> None:
        workspace = str(Path(__file__).resolve().parent)

        def launch(**kwargs):
            return {"status": "error", "text": "", "agent_id": "ag-1", "run_id": "run-9"}

        with self.assertRaises(AdapterError) as ctx:
            run_prompt(
                [{"role": "user", "content": "hi"}],
                workspace=workspace,
                session_id=None,
                agent_id=None,
                sessions=SessionManager(),
                api_key="cursor_test",
                launch=launch,
            )
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.run_id, "run-9")


class TestCustomHandlerForward(unittest.TestCase):
    @staticmethod
    def _cursor_handler_path() -> Path:
        # tests/adapters → tests → cursor-adapter → services → local-runtime → repo root
        return (
            Path(__file__).resolve().parents[5]
            / "etc"
            / "docker"
            / "litellm"
            / "cursor_handler.py"
        )

    def test_unavailable_when_adapter_down(self) -> None:
        import importlib.util

        handler_path = self._cursor_handler_path()
        spec = importlib.util.spec_from_file_location("cursor_handler", handler_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with patch.dict(os.environ, {"CURSOR_ADAPTER_URL": "http://127.0.0.1:1"}):
            status, body = module.forward_to_adapter(
                [{"role": "user", "content": "hi"}],
                "cursor-default",
            )
        self.assertEqual(status, 503)
        self.assertEqual(body["error"]["code"], "cursor_adapter_unavailable")

    def test_litellm_mro_uses_our_completion_not_stubs(self) -> None:
        import importlib.util

        handler_path = self._cursor_handler_path()
        spec = importlib.util.spec_from_file_location("cursor_handler_mro", handler_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        class StubCustomLLM:
            def completion(self, *args, **kwargs):
                raise RuntimeError("Not implemented yet!")

            async def acompletion(self, *args, **kwargs):
                raise RuntimeError("Not implemented yet!")

        class Bound(module.CursorCustomLLM, StubCustomLLM):
            pass

        inst = Bound()
        fake_body = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        with patch.object(module, "forward_to_adapter", return_value=(200, fake_body)):
            result = inst.completion(messages=[{"role": "user", "content": "hi"}], model="cursor-default")
        self.assertEqual(result["choices"][0]["message"]["content"], "ok")


if __name__ == "__main__":
    unittest.main()
