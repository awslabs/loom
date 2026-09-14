"""Domain errors for the local agent runtime."""
from __future__ import annotations


class AgentRuntimeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TemplateError(ValueError):
    """Invalid or unknown local agent template (Spec 026)."""
