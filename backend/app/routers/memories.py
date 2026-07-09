"""Memory resource management endpoints."""
import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.invocation import Invocation
from app.models.memory import Memory
from app.models.session import InvocationSession
from app.models.tag_policy import TagPolicy
from app.models.tag_profile import TagProfile
from app.services.memory import (
    create_memory as svc_create_memory,
    get_memory as svc_get_memory,
    list_memories as svc_list_memories,
    delete_memory as svc_delete_memory,
    list_memory_records as svc_list_memory_records,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memories", tags=["memories"])

DEFAULT_REGION = os.getenv("AWS_REGION", "us-east-1")

STRATEGY_TYPE_MAP = {
    "semantic": "semanticMemoryStrategy",
    "summary": "summaryMemoryStrategy",
    "user_preference": "userPreferenceMemoryStrategy",
    "episodic": "episodicMemoryStrategy",
    "custom": "customMemoryStrategy",
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class MemoryStrategyRequest(BaseModel):
    """A single memory strategy configuration."""
    strategy_type: str = Field(..., description="Strategy type: semantic, summary, user_preference, episodic, custom")
    name: str = Field(..., description="Strategy name")
    description: str | None = Field(None, description="Strategy description")
    namespaces: list[str] | None = Field(None, description="Namespaces for the strategy")
    configuration: dict | None = Field(None, description="Additional strategy configuration")


class MemoryCreateRequest(BaseModel):
    """Request body for creating a memory resource."""
    name: str = Field(..., description="Name for the memory resource")
    description: str | None = Field(None, description="Memory resource description")
    event_expiry_duration: int = Field(..., description="Duration in days before events expire")
    memory_execution_role_arn: str | None = Field(None, description="IAM role ARN for memory execution")
    encryption_key_arn: str | None = Field(None, description="KMS key ARN for encryption")
    memory_strategies: list[MemoryStrategyRequest] | None = Field(None, description="Memory strategy configurations")
    tags: dict[str, str] | None = Field(None, description="Build-time tag values from a tag profile")


class MemoryImportRequest(BaseModel):
    """Request body for importing an existing memory resource by its AWS memory ID."""
    memory_id: str = Field(..., description="AWS memory ID (e.g. my_memory-zYcvlyGXsK)")


class MemoryRecordItem(BaseModel):
    """A single stored memory record for a user."""
    memoryRecordId: str
    text: str
    memoryStrategyId: str
    createdAt: str
    updatedAt: str


class MemoryRecordsResponse(BaseModel):
    """Response model for a user's memory records within a memory resource."""
    memory_id: str
    actor_id: str
    records: list[MemoryRecordItem]


class MemoryResponse(BaseModel):
    """Response model for memory resource details."""
    id: int
    name: str
    description: str | None = None
    arn: str | None = None
    memory_id: str | None = None
    status: str
    event_expiry_duration: int
    strategies_config: Any | None = None
    strategies_response: Any | None = None
    tags: dict[str, str] = {}
    failure_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    region: str
    account_id: str
    memory_execution_role_arn: str | None = None
    encryption_key_arn: str | None = None
    cost_summary: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _memory_cost_summary(memory: Memory, db: Session) -> dict | None:
    """Compute aggregated memory cost for a memory resource.

    Finds agents whose config references this memory's ``memory_id`` and
    sums ``memory_estimated_cost`` from their invocations.
    """
    if not memory.memory_id:
        return None

    # Find agents that reference this memory_id in their config
    from app.models.config_entry import ConfigEntry
    pattern = f'%"memory_id": "{memory.memory_id}"%'
    agent_ids = [
        row.agent_id for row in
        db.query(ConfigEntry.agent_id).filter(
            ConfigEntry.key == "AGENT_CONFIG_JSON",
            ConfigEntry.value.like(pattern),
        ).all()
    ]

    if not agent_ids:
        return None

    base_q = db.query(Invocation).join(
        InvocationSession, Invocation.session_id == InvocationSession.session_id
    ).filter(InvocationSession.agent_id.in_(agent_ids))

    total_stm = base_q.with_entities(func.sum(Invocation.stm_cost)).scalar() or 0.0
    total_ltm = base_q.with_entities(func.sum(Invocation.ltm_cost)).scalar() or 0.0
    total_retrievals = base_q.with_entities(func.sum(Invocation.memory_retrievals)).scalar() or 0
    total_events_sent = base_q.with_entities(func.sum(Invocation.memory_events_sent)).scalar() or 0

    total_memory_cost = total_stm + total_ltm
    if total_memory_cost == 0 and total_retrievals == 0 and total_events_sent == 0:
        return None

    return {
        "total_memory_estimated_cost": round(total_memory_cost, 6),
        "total_stm_cost": round(total_stm, 6),
        "total_ltm_cost": round(total_ltm, 6),
        "total_retrievals": total_retrievals,
        "total_events_sent": total_events_sent,
    }


def _build_memory_response(memory: Memory, db: Session) -> MemoryResponse:
    """Build a MemoryResponse with cost summary."""
    resp = MemoryResponse(**memory.to_dict())
    resp.cost_summary = _memory_cost_summary(memory, db)
    return resp


def _handle_aws_error(e: Exception) -> None:
    """Map AWS exceptions to HTTP errors."""
    error_name = type(e).__name__
    logger.error("AWS error [%s]: %s", error_name, e)
    error_map = {
        "ValidationException": status.HTTP_400_BAD_REQUEST,
        "ConflictException": status.HTTP_409_CONFLICT,
        "ResourceNotFoundException": status.HTTP_404_NOT_FOUND,
        "ServiceQuotaExceededException": status.HTTP_429_TOO_MANY_REQUESTS,
        "AccessDeniedException": status.HTTP_403_FORBIDDEN,
        "ThrottledException": status.HTTP_429_TOO_MANY_REQUESTS,
    }
    status_code = error_map.get(error_name, status.HTTP_502_BAD_GATEWAY)
    raise HTTPException(status_code=status_code, detail=str(e))


AGENTCORE_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$")


def _validate_agentcore_name(name: str, field_label: str) -> None:
    """Validate that a name matches the AgentCore naming convention."""
    if not AGENTCORE_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid {field_label} '{name}'. "
                "Must start with a letter, contain only letters, digits, and underscores, "
                "and be at most 48 characters."
            )
        )


def _transform_strategies(strategies: list[MemoryStrategyRequest]) -> list[dict]:
    """Transform simplified strategy format to AWS tagged union format."""
    aws_strategies = []
    for strategy in strategies:
        if strategy.strategy_type not in STRATEGY_TYPE_MAP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid strategy type: '{strategy.strategy_type}'. Must be one of: {', '.join(STRATEGY_TYPE_MAP.keys())}"
            )
        _validate_agentcore_name(strategy.name, "strategy name")
        aws_key = STRATEGY_TYPE_MAP[strategy.strategy_type]
        strategy_config: dict[str, Any] = {"name": strategy.name}
        if strategy.description:
            strategy_config["description"] = strategy.description
        if strategy.namespaces:
            strategy_config["namespaces"] = strategy.namespaces
        if strategy.configuration:
            strategy_config.update(strategy.configuration)
        aws_strategies.append({aws_key: strategy_config})
    return aws_strategies


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------
@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
def create_memory(
    request: MemoryCreateRequest,
    user: UserInfo = Depends(require_scopes("memory:write")),
    db: Session = Depends(get_db),
) -> MemoryResponse:
    """Create a new memory resource."""
    # Enforce demo-admin group restriction
    if "g-admins-demo" in user.groups and "g-admins-super" not in user.groups:
        memory_group = (request.tags or {}).get("loom:group", "")
        if memory_group != "demo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo admins can only create memory resources in the 'demo' group"
            )

    # Enforce demo user restrictions: name must start with "demo_"
    if "g-users-demo" in user.groups:
        if not request.name.startswith("demo_"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Demo users must prefix memory names with 'demo_'",
            )

    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    account_id = os.getenv("AWS_ACCOUNT_ID", "")

    _validate_agentcore_name(request.name, "memory name")

    # Resolve tags from tag policies + user-supplied profile tags
    resolved_tags: dict[str, str] = {}
    user_tags = request.tags or {}
    policies = db.query(TagPolicy).all()
    for p in policies:
        if p.key in user_tags:
            resolved_tags[p.key] = user_tags[p.key]
        elif p.required:
            resolved_tags[p.key] = p.default_value if p.default_value else "missing"

    # Transform strategies
    aws_strategies = None
    if request.memory_strategies:
        aws_strategies = _transform_strategies(request.memory_strategies)

    try:
        response = svc_create_memory(
            name=request.name,
            event_expiry_duration=request.event_expiry_duration,
            description=request.description,
            encryption_key_arn=request.encryption_key_arn,
            memory_execution_role_arn=request.memory_execution_role_arn,
            memory_strategies=aws_strategies,
            tags=resolved_tags or None,
            region=region,
        )
    except Exception as e:
        _handle_aws_error(e)

    # Response is nested: {"memory": {"arn": ..., "id": ..., "status": ..., ...}}
    mem_data = response.get("memory", {})
    logger.info("create_memory response: %s", json.dumps(mem_data, default=str))

    memory_arn = mem_data.get("arn", "")
    memory_id = mem_data.get("id", "")

    # Extract account_id from ARN if available
    # ARN format: arn:aws:bedrock-agentcore:{region}:{account_id}:memory/{memory_id}
    if memory_arn:
        try:
            parts = memory_arn.split(":")
            if len(parts) >= 5:
                account_id = parts[4]
        except (IndexError, ValueError):
            pass

    logger.info("create_memory resolved: memory_id=%s memory_arn=%s account_id=%s", memory_id, memory_arn, account_id)

    memory = Memory(
        name=mem_data.get("name", request.name),
        description=request.description,
        arn=memory_arn,
        memory_id=memory_id,
        region=region,
        account_id=account_id,
        status=mem_data.get("status", "CREATING"),
        event_expiry_duration=request.event_expiry_duration,
        memory_execution_role_arn=request.memory_execution_role_arn,
        encryption_key_arn=request.encryption_key_arn,
    )

    if aws_strategies:
        memory.set_strategies_config(aws_strategies)

    strategies_resp = mem_data.get("strategies")
    if strategies_resp:
        memory.set_strategies_response(strategies_resp)

    if resolved_tags:
        memory.set_tags(resolved_tags)

    db.add(memory)
    db.commit()
    db.refresh(memory)

    # Enable APPLICATION_LOGS observability via vended log delivery
    if memory_arn and memory_id:
        try:
            from app.services.observability import enable_memory_observability
            obs_result = enable_memory_observability(
                memory_arn=memory_arn,
                memory_id=memory_id,
                account_id=account_id,
                region=region,
            )
            logger.info("Enabled observability for memory %s: %s", memory_id, obs_result)
        except Exception as obs_err:
            logger.warning("Failed to enable observability for memory %s: %s", memory_id, obs_err)

    return _build_memory_response(memory, db)


@router.post("/import", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
def import_memory(
    request: MemoryImportRequest,
    user: UserInfo = Depends(require_scopes("memory:write")),
    db: Session = Depends(get_db),
) -> MemoryResponse:
    """Import an existing memory resource from AWS by its memory ID."""
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    account_id = os.getenv("AWS_ACCOUNT_ID", "")

    # Check if already imported
    existing = db.query(Memory).filter(Memory.memory_id == request.memory_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Memory '{request.memory_id}' is already imported (id={existing.id})"
        )

    try:
        response = svc_get_memory(request.memory_id, region)
    except Exception as e:
        _handle_aws_error(e)

    # Response is nested: {"memory": {"arn": ..., "id": ..., "status": ..., ...}}
    mem_data = response.get("memory", {})

    memory_arn = mem_data.get("arn", "")
    memory_name = mem_data.get("name", request.memory_id)
    memory_status = mem_data.get("status", "UNKNOWN")
    description = mem_data.get("description")
    event_expiry = mem_data.get("eventExpiryDuration", 0)
    encryption_key_arn = mem_data.get("encryptionKeyArn")
    memory_execution_role_arn = mem_data.get("memoryExecutionRoleArn")

    # Extract account_id from ARN
    if memory_arn:
        try:
            parts = memory_arn.split(":")
            if len(parts) >= 5:
                account_id = parts[4]
        except (IndexError, ValueError):
            pass

    logger.info("import_memory: memoryId=%s name=%s status=%s arn=%s",
                request.memory_id, memory_name, memory_status, memory_arn)

    memory = Memory(
        name=memory_name,
        description=description,
        arn=memory_arn,
        memory_id=mem_data.get("id", request.memory_id),
        region=region,
        account_id=account_id,
        status=memory_status,
        event_expiry_duration=event_expiry,
        memory_execution_role_arn=memory_execution_role_arn,
        encryption_key_arn=encryption_key_arn,
    )

    strategies_resp = mem_data.get("strategies")
    if strategies_resp:
        memory.set_strategies_response(strategies_resp)

    # Enforce tag policies: fetch AWS tags and fill missing required tags with "missing"
    aws_tags: dict[str, str] = {}
    try:
        import boto3
        control_client = boto3.client("bedrock-agentcore-control", region_name=region)
        tag_response = control_client.list_tags_for_resource(resourceArn=memory_arn)
        aws_tags = tag_response.get("tags", {})
    except Exception as e:
        logger.debug("Could not fetch tags for imported memory %s: %s", request.memory_id, e)

    policies = db.query(TagPolicy).all()
    for p in policies:
        if p.key not in aws_tags and p.required:
            aws_tags[p.key] = p.default_value if p.default_value else "missing"

    if aws_tags:
        memory.set_tags(aws_tags)

    db.add(memory)
    db.commit()
    db.refresh(memory)

    # Enable APPLICATION_LOGS observability via vended log delivery
    imported_memory_id = mem_data.get("id", request.memory_id)
    if memory_arn and imported_memory_id:
        try:
            from app.services.observability import enable_memory_observability
            obs_result = enable_memory_observability(
                memory_arn=memory_arn,
                memory_id=imported_memory_id,
                account_id=account_id,
                region=region,
            )
            logger.info("Enabled observability for imported memory %s: %s", imported_memory_id, obs_result)
        except Exception as obs_err:
            logger.warning("Failed to enable observability for imported memory %s: %s", imported_memory_id, obs_err)

    return _build_memory_response(memory, db)


@router.get("", response_model=list[MemoryResponse])
def list_memories(
    user: UserInfo = Depends(require_scopes("memory:read")),
    db: Session = Depends(get_db),
) -> list[MemoryResponse]:
    """List all memory resources."""
    memories = db.query(Memory).order_by(Memory.created_at.desc()).all()

    # Tag-based filtering:
    # - Admins (t-admin): See ALL resources including untagged
    # - Users (t-user): See only resources tagged with their groups (g-users-* → strip prefix)
    if "t-admin" not in user.groups:
        # User view: filter by group tags (strip "g-users-" prefix)
        user_groups = [g for g in user.groups if g.startswith("g-users-")]
        allowed_tags = [g.replace("g-users-", "", 1) for g in user_groups]
        memories = [m for m in memories if m.get_tags().get("loom:group") in allowed_tags]

    return [_build_memory_response(m, db) for m in memories]


@router.get("/{memory_id}", response_model=MemoryResponse)
def get_memory(memory_id: int, user: UserInfo = Depends(require_scopes("memory:read")), db: Session = Depends(get_db)) -> MemoryResponse:
    """Get a specific memory resource by DB ID."""
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory with id {memory_id} not found"
        )
    return _build_memory_response(memory, db)


@router.get("/{memory_id}/export")
def export_memory(memory_id: int, user: UserInfo = Depends(require_scopes("admin:write")), db: Session = Depends(get_db)):
    """Export memory config in create-compatible format. Super admin only."""
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Memory with id {memory_id} not found")
    data: dict = {
        "name": memory.name,
        "description": memory.description,
        "event_expiry_duration": memory.event_expiry_duration,
    }
    if memory.memory_execution_role_arn:
        data["memory_execution_role_arn"] = memory.memory_execution_role_arn
    if memory.encryption_key_arn:
        data["encryption_key_arn"] = memory.encryption_key_arn
    # Reverse AWS tagged-union format back to create-request format
    aws_key_to_type = {v: k for k, v in STRATEGY_TYPE_MAP.items()}
    strategies_config = memory.get_strategies_config()
    if strategies_config:
        strategies = []
        for entry in strategies_config:
            for aws_key, config in entry.items():
                strategy_type = aws_key_to_type.get(aws_key, "custom")
                strat: dict = {
                    "strategy_type": strategy_type,
                    "name": config.get("name", ""),
                }
                if config.get("description"):
                    strat["description"] = config["description"]
                if config.get("namespaces"):
                    strat["namespaces"] = config["namespaces"]
                strategies.append(strat)
        data["memory_strategies"] = strategies
    tags = memory.get_tags()
    if tags:
        profiles = db.query(TagProfile).all()
        matched_profile = None
        best_match_size = 0
        for profile in profiles:
            profile_tags = profile.get_tags()
            if not profile_tags:
                continue
            if all(tags.get(k) == v for k, v in profile_tags.items()) and len(profile_tags) > best_match_size:
                matched_profile = profile
                best_match_size = len(profile_tags)
        if matched_profile:
            data["tags"] = matched_profile.name
        else:
            data["tags"] = tags
    return data


@router.post("/{memory_id}/refresh", response_model=MemoryResponse)
def refresh_memory(memory_id: int, user: UserInfo = Depends(require_scopes("memory:read")), db: Session = Depends(get_db)) -> MemoryResponse:
    """Refresh memory status from AWS."""
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory with id {memory_id} not found"
        )

    # Resolve the AWS memory ID: prefer stored memory_id, fallback to ARN extraction
    aws_memory_id = memory.memory_id
    if not aws_memory_id and memory.arn:
        try:
            resource = memory.arn.split(":")[-1]
            if resource.startswith("memory/"):
                aws_memory_id = resource[len("memory/"):]
                logger.info("refresh_memory: extracted memory_id from ARN: %s", aws_memory_id)
        except (IndexError, ValueError):
            pass

    if not aws_memory_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Memory does not have an AWS memory_id"
        )

    logger.info("refresh_memory: using aws_memory_id=%s for DB id=%d", aws_memory_id, memory_id)

    try:
        response = svc_get_memory(aws_memory_id, memory.region)
    except Exception as e:
        _handle_aws_error(e)

    # Response is nested: {"memory": {"arn": ..., "id": ..., "status": ..., ...}}
    mem_data = response.get("memory", {})

    # Backfill memory_id if it was missing
    if not memory.memory_id and aws_memory_id:
        memory.memory_id = aws_memory_id

    memory.status = mem_data.get("status", memory.status)
    memory.arn = mem_data.get("arn", memory.arn)
    memory.failure_reason = mem_data.get("failureReason", memory.failure_reason)

    strategies_resp = mem_data.get("strategies")
    if strategies_resp:
        memory.set_strategies_response(strategies_resp)

    memory.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(memory)

    return _build_memory_response(memory, db)


@router.delete("/{memory_id}", response_model=MemoryResponse)
def delete_memory(
    memory_id: int,
    cleanup_aws: bool = True,
    user: UserInfo = Depends(require_scopes("memory:write")),
    db: Session = Depends(get_db),
) -> MemoryResponse:
    """Delete a memory resource. When cleanup_aws=True, initiates async deletion in AWS."""
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory with id {memory_id} not found"
        )

    # Enforce demo-admin group restriction
    if "g-admins-demo" in user.groups and "g-admins-super" not in user.groups:
        memory_group = memory.get_tags().get("loom:group", "")
        if memory_group != "demo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo admins can only delete memory resources in the 'demo' group"
            )

    # If not cleaning up AWS, just remove from DB
    if not cleanup_aws or not memory.memory_id or memory.status in ("FAILED",):
        result = _build_memory_response(memory, db)
        db.delete(memory)
        db.commit()
        return result

    # Clean up observability resources (best-effort)
    try:
        from app.services.observability import cleanup_memory_observability
        cleanup_memory_observability(memory.memory_id, memory.region)
    except Exception as obs_err:
        logger.warning("Failed to cleanup observability for memory %s: %s", memory.memory_id, obs_err)

    # Initiate async deletion in AWS
    try:
        svc_delete_memory(memory.memory_id, memory.region)
    except Exception as e:
        error_name = type(e).__name__
        if error_name == "ResourceNotFoundException":
            # Already gone from AWS — remove locally
            result = _build_memory_response(memory, db)
            db.delete(memory)
            db.commit()
            return result
        logger.warning("Failed to delete memory %s from AWS: %s", memory.memory_id, e)

    # Mark as DELETING so the frontend can poll for completion
    memory.status = "DELETING"
    memory.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(memory)
    return _build_memory_response(memory, db)


@router.delete("/{memory_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_memory(memory_id: int, user: UserInfo = Depends(require_scopes("memory:write")), db: Session = Depends(get_db)) -> None:
    """Remove a memory resource from the local database (no AWS call)."""
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory with id {memory_id} not found"
        )
    db.delete(memory)
    db.commit()


@router.get("/{memory_id}/records", response_model=MemoryRecordsResponse)
def get_memory_records(
    memory_id: int,
    user: UserInfo = Depends(require_scopes("memory:read")),
    db: Session = Depends(get_db),
) -> MemoryRecordsResponse:
    """
    Retrieve stored memory records for the authenticated user within a memory resource.

    Records are scoped to the requesting user's username (from JWT) as the actorId.
    Users cannot access records belonging to other actors.
    """
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory with id {memory_id} not found",
        )
    if not memory.memory_id:
        return MemoryRecordsResponse(memory_id="", actor_id=user.username, records=[])

    # R1: Use same actor_id logic as write side (invocations.py:901)
    actor_id = user.username or user.sub or "loom-agent"

    # Resolve strategy metadata so the service can build namespace queries
    strategies = memory.get_strategies_response() or []

    # R6: Debug logging before API call
    logger.info("get_memory_records: memory_id=%s actor_id=%s strategies=%d",
                memory.memory_id, actor_id, len(strategies))

    try:
        raw_records = svc_list_memory_records(
            memory_id=memory.memory_id,
            actor_id=actor_id,
            strategies=strategies,
            region=memory.region,
        )
    except Exception as e:
        logger.warning("Failed to list memory records for memory_id=%s actor=%s: %s", memory.memory_id, actor_id, e)
        return MemoryRecordsResponse(memory_id=memory.memory_id, actor_id=actor_id, records=[])

    # R6: Log number of raw records returned
    logger.info("get_memory_records: received %d raw records for memory_id=%s actor_id=%s",
                len(raw_records), memory.memory_id, actor_id)

    # R5: Filter records and log dropped count
    records = [
        MemoryRecordItem(
            memoryRecordId=r["memoryRecordId"],
            text=r["text"],
            memoryStrategyId=r["memoryStrategyId"],
            createdAt=str(r["createdAt"]),
            updatedAt=str(r["updatedAt"]),
        )
        for r in raw_records
        if r.get("text")
    ]

    # R6: Log filtering results
    filtered_count = len(raw_records) - len(records)
    if filtered_count > 0:
        logger.info("get_memory_records: filtered out %d records with empty text (kept %d records)",
                    filtered_count, len(records))
    else:
        logger.info("get_memory_records: returning %d records", len(records))

    return MemoryRecordsResponse(
        memory_id=memory.memory_id,
        actor_id=actor_id,
        records=records,
    )
