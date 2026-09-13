"""Map Cursor / adapter failures onto LiteLLM-facing HTTP payloads."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterError(Exception):
    status: int
    code: str
    message: str
    retryable: bool = False
    run_id: str | None = None

    def __str__(self) -> str:
        return self.code

    def to_body(self) -> dict[str, object]:
        error: dict[str, object] = {"message": self.message, "code": self.code, "retryable": self.retryable}
        if self.run_id:
            error["run_id"] = self.run_id
        return {"error": error}


def unavailable() -> AdapterError:
    return AdapterError(503, "cursor_adapter_unavailable", "cursor_adapter_unavailable", retryable=True)


def startup_failed(*, retryable: bool, status: int | None = None) -> AdapterError:
    return AdapterError(
        status if status is not None else (503 if retryable else 500),
        "cursor_startup_failed",
        "cursor_startup_failed",
        retryable=retryable,
    )


def auth_missing() -> AdapterError:
    return AdapterError(401, "cursor_auth_missing", "cursor_auth_missing")


def auth_failed() -> AdapterError:
    return AdapterError(401, "cursor_auth_failed", "cursor_auth_failed")


def invalid_workspace() -> AdapterError:
    return AdapterError(400, "invalid_workspace", "invalid_workspace")


def timeout() -> AdapterError:
    return AdapterError(504, "cursor_timeout", "cursor_timeout", retryable=True)


def run_failed(run_id: str | None = None) -> AdapterError:
    return AdapterError(502, "cursor_run_failed", "cursor_run_failed", run_id=run_id)


def tool_failed() -> AdapterError:
    return AdapterError(502, "cursor_tool_failed", "cursor_tool_failed")


def mcp_failed() -> AdapterError:
    return AdapterError(502, "cursor_mcp_failed", "cursor_mcp_failed")


def from_sdk_error(exc: BaseException) -> AdapterError:
    """Map a CursorAgentError-like object without importing the SDK in tests."""
    name = type(exc).__name__
    message = str(exc).lower()
    retryable = bool(getattr(exc, "is_retryable", False) or getattr(exc, "isRetryable", False))
    if "401" in message or "unauthorized" in message or "api key" in message:
        return auth_failed()
    if name == "CursorAgentError":
        return startup_failed(retryable=retryable)
    return startup_failed(retryable=retryable)
