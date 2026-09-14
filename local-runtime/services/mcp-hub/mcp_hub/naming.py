"""Tool naming helpers (spec 016)."""
from __future__ import annotations

from typing import Any


def expose_tools(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, tuple[int, str]]]:
    name_owners: dict[str, list[tuple[int, str, dict[str, Any], str]]] = {}
    for entry in entries:
        sid = int(entry["server_id"])
        slug = str(entry["server_slug"])
        for tool in entry.get("tools") or []:
            original = str(tool["name"])
            name_owners.setdefault(original, []).append((sid, slug, tool, original))

    exposed: list[dict[str, Any]] = []
    mapping: dict[str, tuple[int, str]] = {}
    for _original, owners in name_owners.items():
        collide = len({sid for sid, _, _, _ in owners}) > 1
        for sid, slug, tool, orig in owners:
            exposed_name = f"{slug}__{orig}" if collide else orig
            mapping[exposed_name] = (sid, orig)
            exposed.append({
                "name": exposed_name,
                "description": tool.get("description") or "",
                "inputSchema": tool.get("inputSchema") or {"type": "object", "properties": {}},
            })
    exposed.sort(key=lambda t: t["name"])
    return exposed, mapping
