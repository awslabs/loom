"""Shared client/grant record helpers (pure)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_grant(g: dict[str, Any], *, group: str) -> dict[str, Any] | None:
    try:
        server_id = int(g["server_id"])
    except (KeyError, TypeError, ValueError):
        return None
    level = str(g.get("access_level") or "selected_tools")
    if level not in ("all_tools", "selected_tools"):
        level = "selected_tools"
    names = g.get("tool_names") or []
    if not isinstance(names, list):
        names = []
    return {
        "group": group[:128],
        "server_id": server_id,
        "access_level": level,
        "tool_names": [str(n) for n in names][:500],
    }


def refresh_allowed_groups(row: dict[str, Any]) -> None:
    row["allowed_groups"] = sorted({
        str(g.get("group"))
        for g in (row.get("grants") or [])
        if g.get("group")
    })


def client_summary(row: dict[str, Any]) -> dict[str, Any]:
    """List/detail payload without embedding all profile grants."""
    out = deepcopy(row)
    grants = list(out.pop("grants", None) or [])
    profiles = sorted({str(g.get("group")) for g in grants if g.get("group")})
    out["granted_profiles"] = profiles
    out["grant_count"] = len(grants)
    out["allowed_groups"] = profiles
    out["agents_enabled"] = bool(out.get("agents_enabled", False))
    return out
