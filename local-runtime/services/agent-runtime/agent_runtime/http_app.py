"""Compat shim — prefer ``agent_runtime.adapters.inbound.http_app``."""
from agent_runtime.adapters.inbound.http_app import *  # noqa: F403
from agent_runtime.adapters.inbound.http_app import RuntimeHandler, serve  # noqa: F401
