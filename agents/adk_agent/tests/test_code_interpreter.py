"""Tests for Code Interpreter integration."""

import unittest
from unittest.mock import patch, MagicMock

from src.config import (
    AgentConfig,
    CodeInterpreterConfig,
    IntegrationsConfig,
    MemoryConfig,
)
from src.agent import build_agent
from src.integrations.code_interpreter import (
    AgentCoreCodeInterpreterTools,
    build_code_interpreter_tools,
    _session_cache,
)


def _make_config(ci_enabled: bool = False, ci_region: str = "", ci_identifier: str = "") -> AgentConfig:
    return AgentConfig(
        system_prompt="Test prompt",
        model_id="us.anthropic.claude-sonnet-4-20250514",
        integrations=IntegrationsConfig(
            memory=MemoryConfig(enabled=False),
            code_interpreter=CodeInterpreterConfig(
                enabled=ci_enabled,
                region=ci_region,
                identifier=ci_identifier,
            ),
        ),
    )


class TestCodeInterpreterIntegration(unittest.IsolatedAsyncioTestCase):
    """Tests for Code Interpreter tool registration in build_agent."""

    @patch("src.agent.build_code_interpreter_tools")
    async def test_code_interpreter_enabled(self, mock_build_ci: MagicMock) -> None:
        mock_tool = MagicMock()
        mock_ci_instance = MagicMock()
        mock_build_ci.return_value = ([mock_tool], mock_ci_instance)

        config = _make_config(ci_enabled=True, ci_region="us-west-2")
        agent, plugins, ci = await build_agent(config)

        mock_build_ci.assert_called_once()
        self.assertIn(mock_tool, agent.tools)
        self.assertIs(ci, mock_ci_instance)

    async def test_code_interpreter_disabled(self) -> None:
        config = _make_config(ci_enabled=False)
        agent, plugins, ci = await build_agent(config)

        self.assertIsNone(ci)
        self.assertEqual(agent.tools, [])


class TestCodeInterpreterConfig(unittest.TestCase):
    """Tests for CodeInterpreterConfig parsing."""

    def test_default_config(self) -> None:
        config = CodeInterpreterConfig()
        self.assertFalse(config.enabled)
        self.assertEqual(config.region, "")
        self.assertEqual(config.identifier, "")

    def test_config_with_values(self) -> None:
        config = CodeInterpreterConfig(enabled=True, region="us-west-2", identifier="custom-ci")
        self.assertTrue(config.enabled)
        self.assertEqual(config.region, "us-west-2")
        self.assertEqual(config.identifier, "custom-ci")


class TestBuildCodeInterpreterTools(unittest.TestCase):
    """Tests for build_code_interpreter_tools."""

    def test_returns_six_tools(self) -> None:
        config = CodeInterpreterConfig(enabled=True)
        tools, ci = build_code_interpreter_tools(config)
        self.assertEqual(len(tools), 6)
        self.assertIsInstance(ci, AgentCoreCodeInterpreterTools)

    def test_passes_region_and_identifier(self) -> None:
        config = CodeInterpreterConfig(enabled=True, region="us-west-2", identifier="custom-ci")
        _, ci = build_code_interpreter_tools(config)
        self.assertEqual(ci.region, "us-west-2")
        self.assertEqual(ci.identifier, "custom-ci")

    def test_default_identifier(self) -> None:
        config = CodeInterpreterConfig(enabled=True)
        _, ci = build_code_interpreter_tools(config)
        self.assertEqual(ci.identifier, "aws.codeinterpreter.v1")


class TestSessionLifecycle(unittest.TestCase):
    """Tests for AgentCoreCodeInterpreterTools session creation/reconnection."""

    def setUp(self) -> None:
        _session_cache.clear()

    def tearDown(self) -> None:
        _session_cache.clear()

    @patch("src.integrations.code_interpreter._CodeInterpreterClient")
    def test_creates_new_session(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.session_id = "aws-session-1"
        mock_client_cls.return_value = mock_client

        tools = AgentCoreCodeInterpreterTools(region="us-east-1")
        client = tools._ensure_session("my-session")

        mock_client.start.assert_called_once_with(identifier="aws.codeinterpreter.v1", name="my-session")
        self.assertIs(client, mock_client)
        self.assertIn("my-session", _session_cache)

    @patch("src.integrations.code_interpreter._CodeInterpreterClient")
    def test_reconnects_to_cached_session(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.session_id = "aws-session-1"
        mock_client_cls.return_value = mock_client

        tools = AgentCoreCodeInterpreterTools(region="us-east-1")
        client1 = tools._ensure_session("my-session")
        client2 = tools._ensure_session("my-session")

        # start() called only once — second call reconnects via cache
        mock_client.start.assert_called_once()
        self.assertIs(client1, client2)

    @patch("src.integrations.code_interpreter._CodeInterpreterClient")
    def test_default_session_name_used_when_none(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.session_id = "aws-session-1"
        mock_client_cls.return_value = mock_client

        tools = AgentCoreCodeInterpreterTools(region="us-east-1")
        tools._ensure_session(None)

        call_kwargs = mock_client.start.call_args.kwargs
        self.assertEqual(call_kwargs["name"], tools.default_session)

    @patch("src.integrations.code_interpreter._CodeInterpreterClient")
    def test_prewarm_creates_default_session(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.session_id = "aws-session-1"
        mock_client_cls.return_value = mock_client

        tools = AgentCoreCodeInterpreterTools(region="us-east-1")
        tools.prewarm()

        mock_client.start.assert_called_once()

    @patch("src.integrations.code_interpreter._CodeInterpreterClient")
    def test_prewarm_swallows_errors(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.start.side_effect = Exception("boom")
        mock_client_cls.return_value = mock_client

        tools = AgentCoreCodeInterpreterTools(region="us-east-1")
        # Should not raise
        tools.prewarm()


class TestCodeInterpreterTools(unittest.TestCase):
    """Tests for the individual FunctionTools built by build_tools()."""

    def setUp(self) -> None:
        _session_cache.clear()

    def tearDown(self) -> None:
        _session_cache.clear()

    @patch("src.integrations.code_interpreter._CodeInterpreterClient")
    def test_execute_code_tool(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.session_id = "s1"
        mock_client.execute_code.return_value = {"status": "success"}
        mock_client_cls.return_value = mock_client

        tools = AgentCoreCodeInterpreterTools(region="us-east-1")
        function_tools = tools.build_tools()
        execute_code_tool = next(t for t in function_tools if t.name == "code_interpreter_execute_code")

        result = execute_code_tool.func(code="print(1)", tool_context=MagicMock(), language="python")
        self.assertEqual(result, {"status": "success"})
        mock_client.execute_code.assert_called_once_with(code="print(1)", language="python", clear_context=False)

    @patch("src.integrations.code_interpreter._CodeInterpreterClient")
    def test_write_files_tool_uses_content_key(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.session_id = "s1"
        mock_client_cls.return_value = mock_client

        tools = AgentCoreCodeInterpreterTools(region="us-east-1")
        function_tools = tools.build_tools()
        write_tool = next(t for t in function_tools if t.name == "code_interpreter_write_files")

        write_tool.func(files=[{"path": "a.txt", "content": "hello"}], tool_context=MagicMock())
        mock_client.upload_files.assert_called_once_with([{"path": "a.txt", "content": "hello"}])

    @patch("src.integrations.code_interpreter._CodeInterpreterClient")
    def test_list_files_tool(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.session_id = "s1"
        mock_client_cls.return_value = mock_client

        tools = AgentCoreCodeInterpreterTools(region="us-east-1")
        function_tools = tools.build_tools()
        list_tool = next(t for t in function_tools if t.name == "code_interpreter_list_files")

        list_tool.func(path="/", tool_context=MagicMock())
        mock_client.invoke.assert_called_once_with("listFiles", {"path": "/"})


if __name__ == "__main__":
    unittest.main()
