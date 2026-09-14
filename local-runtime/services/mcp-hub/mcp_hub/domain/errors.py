"""Domain errors for the MCP Hub."""
from __future__ import annotations


class HubError(Exception):
    """Base Hub domain error."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class HubUnauthorized(HubError):
    def __init__(self, message: str = "unauthorized") -> None:
        super().__init__("unauthorized", message)


class ToolNotAllowed(HubError):
    def __init__(self, message: str = "tool_not_allowed") -> None:
        super().__init__("tool_not_allowed", message)


class AgentsDisabled(HubError):
    def __init__(self, message: str = "agents_disabled") -> None:
        super().__init__("agents_disabled", message)
