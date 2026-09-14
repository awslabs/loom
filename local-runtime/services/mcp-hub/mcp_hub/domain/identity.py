"""clientInfo → slug / family (spec 022)."""
from __future__ import annotations

import re
from typing import Any

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_FAMILY_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("cursor", ("cursor",)),
    ("claude-code", ("claude-code", "claude code", "claude_code")),
    ("claude-desktop", ("claude-desktop", "claude desktop", "claude_desktop")),
    ("vscode", ("vscode", "visual studio code")),
    ("loom", ("loom", "loom-mcp", "local-runtime")),
]


def normalize_slug(name: str | None) -> str:
    raw = (name or "").strip().lower()
    slug = _SLUG_RE.sub("-", raw).strip("-")
    if not slug:
        return "unknown"
    return slug[:64]


def declared_family(name: str | None) -> str:
    raw = (name or "").strip().lower()
    if not raw:
        return "unknown"
    for family, needles in _FAMILY_ALIASES:
        for needle in needles:
            if needle in raw:
                return family
    return "unknown"


def parse_client_info(params: dict[str, Any] | None) -> tuple[str, str, str, str]:
    info = (params or {}).get("clientInfo") if isinstance(params, dict) else None
    if not isinstance(info, dict):
        info = {}
    name = str(info.get("name") or "").strip()
    version = str(info.get("version") or "").strip()[:64]
    slug = normalize_slug(name)
    family = declared_family(name)
    return slug, name, version, family
