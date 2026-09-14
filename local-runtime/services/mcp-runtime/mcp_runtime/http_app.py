"""Compat shim — prefer ``adapters.inbound.http_app``."""
from mcp_runtime.adapters.inbound.http_app import *  # noqa: F403
from mcp_runtime.adapters.inbound.http_app import RuntimeHandler, serve  # noqa: F401
