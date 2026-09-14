"""Compat shim — prefer ``adapters.outbound.env_secrets``."""
from mcp_runtime.adapters.outbound.env_secrets import *  # noqa: F403
from mcp_runtime.domain.errors import SecretError  # noqa: F401
