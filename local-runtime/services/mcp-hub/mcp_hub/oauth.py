"""Compat shim — prefer ``mcp_hub.adapters.outbound.oauth_jwks``."""
from __future__ import annotations

import sys

from mcp_hub.adapters.outbound import oauth_jwks as _impl

sys.modules[__name__] = _impl
