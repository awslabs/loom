"""Compat shim — prefer ``adapters.outbound.stdio_session``."""
from mcp_runtime.adapters.outbound.stdio_session import *  # noqa: F403
from mcp_runtime.domain.errors import StdioError  # noqa: F401
