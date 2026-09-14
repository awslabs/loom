import unittest

from cursor_adapter.domain.errors import (
    auth_failed,
    auth_missing,
    from_sdk_error,
    invalid_workspace,
    mcp_failed,
    run_failed,
    startup_failed,
    timeout,
    tool_failed,
    unavailable,
)


class _SdkError(Exception):
    def __init__(self, message: str, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.is_retryable = is_retryable


_SdkError.__name__ = "CursorAgentError"


class TestErrorMapping(unittest.TestCase):
    def test_table(self) -> None:
        cases = [
            (unavailable(), 503, "cursor_adapter_unavailable", True),
            (startup_failed(retryable=True), 503, "cursor_startup_failed", True),
            (startup_failed(retryable=False), 500, "cursor_startup_failed", False),
            (auth_missing(), 401, "cursor_auth_missing", False),
            (auth_failed(), 401, "cursor_auth_failed", False),
            (invalid_workspace(), 400, "invalid_workspace", False),
            (timeout(), 504, "cursor_timeout", True),
            (run_failed("run-1"), 502, "cursor_run_failed", False),
            (tool_failed(), 502, "cursor_tool_failed", False),
            (mcp_failed(), 502, "cursor_mcp_failed", False),
        ]
        for error, status, code, retryable in cases:
            self.assertEqual(error.status, status, code)
            self.assertEqual(error.code, code)
            self.assertEqual(error.retryable, retryable)
            self.assertNotIn("sk-", str(error.to_body()))
            self.assertNotIn("cursor_", str(error.to_body().get("error", {}).get("key", "")))

    def test_sdk_auth_message(self) -> None:
        mapped = from_sdk_error(_SdkError("401 unauthorized api key"))
        self.assertEqual(mapped.code, "cursor_auth_failed")
        self.assertEqual(mapped.status, 401)

    def test_sdk_retryable_startup(self) -> None:
        mapped = from_sdk_error(_SdkError("network blip", is_retryable=True))
        self.assertEqual(mapped.code, "cursor_startup_failed")
        self.assertTrue(mapped.retryable)


if __name__ == "__main__":
    unittest.main()
