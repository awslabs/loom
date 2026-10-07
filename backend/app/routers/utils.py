"""Shared utilities for router modules."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import UserInfo
from app.models.agent import Agent
from app.models.managed_role import ManagedRole


def check_resource_group_access(resource, user: UserInfo, resource_label: str = "resource") -> None:
    """Enforce the same loom:group ownership check the agent invoke route applies.

    This closes the gap on single-object fetch-by-ID helpers, which previously
    resolved by ID alone with no group check, letting any authenticated user
    read/write/delete another group's resources by guessing/enumerating IDs.
    List routes need the matching filter applied separately — see
    filter_visible_resources and visible_agent_ids; an earlier version of this
    docstring asserted that every list route already did, which was not true
    of the MCP, connector and A2A listings. Super-admins
    (g-admins-super) bypass; other admins (g-admins-*) are confined to their
    own group; users (t-user) are confined to the union of their g-users-*
    groups.

    An untagged resource is visible to super-admins only. This used to fail
    open — no loom:group tag meant "accessible to anyone" — which is the same
    shape of bug as an empty IdP group-mapping table meaning "trust the
    provider": absence of policy read as absence of restriction. A resource
    nobody has assigned to a group is now nobody's to read until somebody
    assigns it.
    """
    if "g-admins-super" in user.groups:
        return
    resource_group = resource.get_tags().get("loom:group", "")
    if not resource_group:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"This {resource_label} has no loom:group tag, so only a super-admin "
                "can access it. Assign it to a group to grant access."
            ),
        )
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

def get_session_or_404(agent_id: int, session_id: str, db: Session, user: UserInfo):
    """Fetch a session by agent + session ID, enforcing group *and* ownership.

    Resolving by session UUID used to skip both checks, so any holder of
    agent:read could read any conversation on any agent given its ID. The
    agent's loom:group is checked first (via get_agent_or_404), then ownership:
    a session belongs to the user who created it, and only an admin for the
    agent's group may read other people's conversations.
    """
    from app.models.session import InvocationSession

    agent = get_agent_or_404(agent_id, db, user)
    session = db.query(InvocationSession).filter(
        InvocationSession.agent_id == agent_id,
        InvocationSession.session_id == session_id,
    ).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found for agent {agent_id}",
        )
    assert_session_readable(session, user, agent)
    return session


def assert_session_readable(session, user: UserInfo, agent) -> None:
    """A session is readable by its owner, or by an admin for the agent's group.

    get_agent_or_404 has already confirmed the caller may see the agent, so
    this only decides whether they may read *other people's* conversations on
    it. Non-admins are confined to their own.
    """
    if "t-admin" in user.groups:
        return
    if session.user_id and session.user_id != user.username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this session",
        )


def visible_agent_ids(db: Session, user: UserInfo) -> list[int] | None:
    """Agent IDs the caller may see, or None when unrestricted (super-admin).

    For list endpoints that take a caller-supplied agent_id or none at all:
    scoping the query to these IDs means a forgotten check returns no rows
    rather than every row.
    """
    if "g-admins-super" in user.groups:
        return None
    allowed: list[int] = []
    for agent in db.query(Agent).all():
        try:
            check_resource_group_access(agent, user, resource_label="agent")
        except HTTPException:
            continue
        allowed.append(agent.id)
    return allowed

def bindable_role_arns(db: Session, user: UserInfo) -> set[str] | None:
    """Execution-role ARNs this caller may legitimately attach to an agent.

    None means unrestricted (super-admin).

    A role is usable only if it has a ManagedRole row the caller can reach —
    that is, somebody registered it under Security > Roles and tagged it into
    a group the caller belongs to. `iam.list_roles` returns every role in the
    account that trusts bedrock-agentcore, and most have no Loom record, so
    being visible in AWS is not entitlement.

    This used to also accept any ARN already attached to an agent the caller
    could reach, which was necessary while Loom created execution roles during
    deploy and gave them no ManagedRole row. Loom no longer creates roles, so
    that clause is gone: registration is the single way a role enters Loom.
    Agents whose role Loom auto-created before this change will fail to
    redeploy until that role is registered — deliberately, because an
    unregistered role has no group and therefore no owner.
    """
    if "g-admins-super" in user.groups:
        return None
    allowed: set[str] = set()
    for role in db.query(ManagedRole).all():
        try:
            check_resource_group_access(role, user, resource_label="managed role")
        except HTTPException:
            continue
        if role.role_arn:
            allowed.add(role.role_arn)
    return allowed


def assert_role_arn_bindable(
    role_arn: str | None, db: Session, user: UserInfo,
) -> None:
    """Refuse an execution role ARN the caller is not entitled to attach."""
    if not role_arn:
        return
    allowed = bindable_role_arns(db, user)
    if allowed is None or role_arn in allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "You cannot attach that execution role. It must be registered "
            "under Security > Roles and belong to one of your groups. Loom "
            "does not create execution roles — ask a platform engineer to "
            "provision one (see shared/iac/role.yaml) and register it."
        ),
    )


def assert_bindable(resources: list, user: UserInfo, resource_label: str = "resource") -> None:
    """Group-check every row a request is attaching to an agent by primary key.

    Agent create and redeploy resolve `mcp_servers`, `memory_ids` and
    `a2a_agents` straight from primary keys in the request body. Fetch-by-ID
    has been 403 across groups since the single-object helpers landed, but
    these binds never ran that check, so the IDs were a second way in: a
    caller could attach another group's MCP server — whose deploy snapshot
    carries `oauth2_client_secret` into a credential provider under the
    caller's own agent — or another group's `memory_id` into their own
    `AGENT_CONFIG_JSON`.

    Unlike filter_visible_resources this raises rather than filtering. A list
    silently omitting a row the caller cannot see is right; a deploy silently
    dropping an integration the caller asked for is not, and would leave them
    with a working agent quietly missing its tools.

    Keyed on what the *caller* can reach rather than on matching the agent's
    own loom:group: that is exactly the reporter's "do not snapshot secrets
    the caller cannot GET", it matches the semantics every other check already
    uses, and it leaves a super-admin able to compose across groups
    deliberately instead of breaking existing deployments that share one
    integration between several groups' agents.
    """
    for resource in resources:
        check_resource_group_access(resource, user, resource_label=resource_label)


def filter_visible_resources(resources: list, user: UserInfo, resource_label: str = "resource") -> list:
    """Drop the rows the caller's loom:group does not reach.

    The list-route counterpart to check_resource_group_access. A list wants the
    row omitted, not the whole response rejected — one unreachable row must not
    make the page unusable — so this swallows the 403 per row rather than
    letting it propagate.

    Returning a resource here is what tells a caller the resource exists at
    all. For MCP servers that mattered beyond metadata: the listing was the
    source of the display name needed to aim a name-keyed secret lookup at
    another group's credential.
    """
    if "g-admins-super" in user.groups:
        return resources
    visible = []
    for resource in resources:
        try:
            check_resource_group_access(resource, user, resource_label=resource_label)
        except HTTPException:
            continue
        visible.append(resource)
    return visible


def require_group_tag(tags: dict[str, str] | None, resource_label: str = "resource") -> dict[str, str]:
    """Reject a create/update whose tags carry no loom:group, and return them.

    Authorization is by loom:group, so a resource without one is unreachable
    for everyone except a super-admin (see check_resource_group_access, which
    now fails closed). Rather than let the API mint resources nobody can
    administer, refuse at the boundary.

    Deliberately enforced here and not in the models' set_tags(): internal
    paths and tests still need to be able to construct an untagged resource,
    not least to prove the fail-closed behaviour. The guarantee being offered
    is "the API cannot create one", not "the type cannot exist".
    """
    resolved = tags or {}
    if not resolved.get("loom:group"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A {resource_label} must carry a loom:group tag — pick a tag profile. "
                "Without one, only a super-admin could access it."
            ),
        )
    return resolved
