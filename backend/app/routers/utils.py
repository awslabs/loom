"""Shared utilities for router modules."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import UserInfo
from app.models.agent import Agent


def check_resource_group_access(resource, user: UserInfo, resource_label: str = "resource") -> None:
    """Enforce the same loom:group ownership check the agent invoke route applies.

    List routes already filter by loom:group; this closes the matching gap on
    single-object fetch-by-ID helpers, which previously resolved by ID alone
    with no group check, letting any authenticated user read/write/delete
    another group's resources by guessing/enumerating IDs. Super-admins
    (g-admins-super) bypass; an untagged resource is accessible to anyone
    (matching list-route behavior for untagged resources); other admins
    (g-admins-*) are confined to their own group; users (t-user) are confined
    to the union of their g-users-* groups.
    """
    if "g-admins-super" in user.groups:
        return
    resource_group = resource.get_tags().get("loom:group", "")
    if not resource_group:
        return
    if "t-admin" in user.groups:
        admin_groups = [g for g in user.groups if g.startswith("g-admins-")]
        allowed_tags = [g.replace("g-admins-", "", 1) for g in admin_groups]
    else:
        user_groups = [g for g in user.groups if g.startswith("g-users-")]
        allowed_tags = [g.replace("g-users-", "", 1) for g in user_groups]
    if resource_group not in allowed_tags:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have access to this {resource_label} (group: {resource_group})",
        )


def get_agent_or_404(agent_id: int, db: Session, user: UserInfo) -> Agent:
    """Fetch an agent by ID, raise 404 if missing, 403 if outside the caller's group."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found"
        )
    check_resource_group_access(agent, user, resource_label="agent")
    return agent
