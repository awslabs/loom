"""Resolve which MCP Client grants apply to a Hub session user profile."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


# Same IdP vocabulary as Loom Chat (full group names, not short loom:group tags).
LOOM_PROFILE_GROUPS: tuple[str, ...] = (
    "g-users-demo",
    "g-users-test",
    "g-users-strategics",
    "g-admins-demo",
    "g-admins-mcp",
    "g-admins-security",
    "g-admins-memory",
    "g-admins-a2a",
    "g-admins-registry",
)


def profile_keys_for_user(user_groups: list[str]) -> set[str] | None:
    """Return grant profile keys that match this user.

    ``None`` means super-admin: every grant on the client applies.
    Cohort admins (``g-admins-{name}``) also match ``g-users-{name}`` grants.
    """
    ug = set(user_groups or [])
    if "g-admins-super" in ug:
        return None
    keys = {g for g in ug if g.startswith("g-users-") or g.startswith("g-admins-")}
    for group in list(keys):
        if group.startswith("g-admins-") and group != "g-admins-super":
            keys.add("g-users-" + group[len("g-admins-") :])
    return keys


def grants_for_user(user_groups: list[str], grants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter client grants to those the user's profile may see; strip ``group`` for Loom BFF."""
    keys = profile_keys_for_user(user_groups)
    out: list[dict[str, Any]] = []
    for grant in grants or []:
        profile = str(grant.get("group") or "").strip()
        if keys is None:
            pass
        elif not profile:
            # Legacy grant without profile: do not expose (force re-save per profile).
            continue
        elif profile not in keys:
            continue
        cleaned = deepcopy(grant)
        cleaned.pop("group", None)
        out.append(cleaned)
    return out


def merge_profile_grants(
    existing: list[dict[str, Any]],
    *,
    group: str,
    profile_grants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace all grants for ``group`` with ``profile_grants``; keep other profiles."""
    group = str(group).strip()
    kept = [g for g in (existing or []) if str(g.get("group") or "").strip() != group]
    for g in profile_grants:
        row = deepcopy(g)
        row["group"] = group
        kept.append(row)
    return kept
