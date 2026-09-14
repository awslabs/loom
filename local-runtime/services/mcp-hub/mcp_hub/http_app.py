"""Compat shim — prefer ``mcp_hub.adapters.inbound.http_app``."""
from mcp_hub.adapters.inbound.http_app import *  # noqa: F403
from mcp_hub.adapters.inbound.http_app import serve  # noqa: F401
