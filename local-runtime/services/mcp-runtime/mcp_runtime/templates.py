"""Compat shim — prefer ``adapters.outbound.yaml_templates``."""
from mcp_runtime.adapters.outbound.yaml_templates import *  # noqa: F403
from mcp_runtime.domain.errors import TemplateError  # noqa: F401
