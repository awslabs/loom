"""Domain errors for mcp-runtime."""
from __future__ import annotations


class TemplateError(ValueError):
    """Template missing, invalid, or params fail the schema."""


class SecretError(ValueError):
    """Secret backend missing or reference empty."""


class StdioError(RuntimeError):
    """Child closed or timed out."""
