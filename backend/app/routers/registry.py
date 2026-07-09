"""Registry management endpoints for AWS Agent Registry integration."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.a2a import A2aAgent
from app.models.agent import Agent
from app.models.mcp import McpServer, McpTool
from app.services.registry import get_registry_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/registry", tags=["registry"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
MCP_NAMESPACES = ("aws.agentcore", "remote.mcp", "npm", "custom")


class RegistryRecordCreateRequest(BaseModel):
    resource_type: str = Field(..., description="Resource type: 'mcp', 'a2a', or 'agent'")
    resource_id: int = Field(..., description="ID of the MCP server, A2A agent, or agent")
    namespace: str | None = Field(None, description="Namespace prefix for MCP servers")


class RegistryRecordResponse(BaseModel):
    record_id: str
    name: str
    descriptor_type: str
    status: str
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class RegistryRecordDetailResponse(RegistryRecordResponse):
    descriptors: dict = {}
    record_version: str | None = None
    status_reason: str | None = None


class StatusReasonRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000, description="Reason for the status change")


class SearchResponse(BaseModel):
    results: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_resource_by_record_id(record_id: str, db: Session) -> McpServer | A2aAgent | Agent | None:
    """Look up an McpServer, A2aAgent, or Agent by its registry_record_id."""
    server = db.query(McpServer).filter(McpServer.registry_record_id == record_id).first()
    if server:
        return server
    agent_a2a = db.query(A2aAgent).filter(A2aAgent.registry_record_id == record_id).first()
    if agent_a2a:
        return agent_a2a
    agent = db.query(Agent).filter(Agent.registry_record_id == record_id).first()
    return agent


def _to_str(val) -> str:
    """Coerce a value to string — handles datetime objects from boto3."""
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _record_to_response(rec: dict) -> RegistryRecordResponse:
    """Map an AWS API record dict to a RegistryRecordResponse."""
    return RegistryRecordResponse(
        record_id=rec.get("recordId", ""),
        name=rec.get("name", ""),
        descriptor_type=rec.get("descriptorType", ""),
        status=rec.get("status", ""),
        description=rec.get("description"),
        created_at=_to_str(rec.get("createdAt")),
        updated_at=_to_str(rec.get("updatedAt")),
    )


def _record_to_detail_response(rec: dict) -> RegistryRecordDetailResponse:
    """Map an AWS API record dict to a RegistryRecordDetailResponse."""
    return RegistryRecordDetailResponse(
        record_id=rec.get("recordId", ""),
        name=rec.get("name", ""),
        descriptor_type=rec.get("descriptorType", ""),
        status=rec.get("status", ""),
        description=rec.get("description"),
        created_at=_to_str(rec.get("createdAt")),
        updated_at=_to_str(rec.get("updatedAt")),
        descriptors=rec.get("descriptors", {}),
        record_version=rec.get("recordVersion"),
        status_reason=rec.get("statusReason"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/records", response_model=list[RegistryRecordResponse])
def list_records(
    status_filter: str | None = Query(None, alias="status", description="Filter by record status"),
    descriptor_type: str | None = Query(None, description="Filter by descriptor type"),
    user: UserInfo = Depends(require_scopes("registry:read")),
) -> list[RegistryRecordResponse]:
    """List all registry records, optionally filtered by status or descriptor type."""
    client = get_registry_client()
    response = client.list_records()
    records = response.get("registryRecords", [])

    results: list[RegistryRecordResponse] = []
    for rec in records:
        if status_filter and rec.get("status") != status_filter:
            continue
        if descriptor_type and rec.get("descriptorType") != descriptor_type:
            continue
        results.append(_record_to_response(rec))
    return results


@router.get("/records/{record_id}", response_model=RegistryRecordDetailResponse)
def get_record(
    record_id: str,
    user: UserInfo = Depends(require_scopes("registry:read")),
) -> RegistryRecordDetailResponse:
    """Get full detail for a single registry record."""
    client = get_registry_client()
    rec = client.get_record(record_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Registry record {record_id} not found",
        )
    return _record_to_detail_response(rec)


@router.post("/records", response_model=RegistryRecordDetailResponse, status_code=status.HTTP_201_CREATED)
def create_record(
    request: RegistryRecordCreateRequest,
    user: UserInfo = Depends(require_scopes("registry:write")),
    db: Session = Depends(get_db),
) -> RegistryRecordDetailResponse:
    """Create a registry record from a Loom MCP server or A2A agent."""
    client = get_registry_client()

    if request.resource_type == "mcp":
        ns = request.namespace or "aws.agentcore"
        if ns not in MCP_NAMESPACES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"namespace must be one of: {', '.join(MCP_NAMESPACES)}",
            )
        server = db.query(McpServer).filter(McpServer.id == request.resource_id).first()
        if not server:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MCP server with id {request.resource_id} not found",
            )
        tools = db.query(McpTool).filter(McpTool.server_id == server.id).all()
        descriptors = client.build_mcp_descriptors(server, tools, namespace=ns)
        name = server.name
        description = server.description
        descriptor_type = "MCP"
        resource = server

    elif request.resource_type == "a2a":
        agent = db.query(A2aAgent).filter(A2aAgent.id == request.resource_id).first()
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"A2A agent with id {request.resource_id} not found",
            )
        descriptors = client.build_a2a_descriptors(agent)
        name = agent.name
        description = agent.description
        descriptor_type = "A2A"
        resource = agent

    elif request.resource_type == "agent":
        agent_record = db.query(Agent).filter(Agent.id == request.resource_id).first()
        if not agent_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent with id {request.resource_id} not found",
            )
        descriptors = client.build_agent_descriptors(agent_record)
        name = agent_record.name or agent_record.runtime_id
        description = agent_record.description
        descriptor_type = "A2A"
        resource = agent_record

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="resource_type must be 'mcp', 'a2a', or 'agent'",
        )

    rv = "1.0"
    result = client.create_record(
        name=name,
        descriptor_type=descriptor_type,
        descriptors=descriptors,
        record_version=rv,
        description=description,
    )

    record_id = result.get("recordId", "")
    if record_id:
        rec = client.wait_for_record(record_id)
        resource.registry_record_id = record_id
        resource.registry_status = rec.get("status", "DRAFT")
        db.commit()
        db.refresh(resource)
        return _record_to_detail_response(rec)

    return _record_to_detail_response(result)


class RegistryRecordUpdateRequest(BaseModel):
    namespace: str | None = Field(None, description="Namespace prefix for MCP servers")


@router.put("/records/{record_id}", response_model=RegistryRecordDetailResponse)
def update_record(
    record_id: str,
    request: RegistryRecordUpdateRequest = RegistryRecordUpdateRequest(),
    user: UserInfo = Depends(require_scopes("registry:write")),
    db: Session = Depends(get_db),
) -> RegistryRecordDetailResponse:
    """Update a registry record by re-building descriptors from the linked Loom resource."""
    client = get_registry_client()

    server = db.query(McpServer).filter(McpServer.registry_record_id == record_id).first()
    if server:
        ns = request.namespace or "aws.agentcore"
        if ns not in MCP_NAMESPACES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"namespace must be one of: {', '.join(MCP_NAMESPACES)}",
            )
        tools = db.query(McpTool).filter(McpTool.server_id == server.id).all()
        descriptors = client.build_mcp_descriptors(server, tools, namespace=ns)
        name = server.name
        description = server.description
        descriptor_type = "MCP"
    else:
        agent_a2a = db.query(A2aAgent).filter(A2aAgent.registry_record_id == record_id).first()
        if agent_a2a:
            descriptors = client.build_a2a_descriptors(agent_a2a)
            name = agent_a2a.name
            description = agent_a2a.description
            descriptor_type = "A2A"
        else:
            agent = db.query(Agent).filter(Agent.registry_record_id == record_id).first()
            if agent:
                descriptors = client.build_agent_descriptors(agent)
                name = agent.name or agent.runtime_id
                description = agent.description
                descriptor_type = "A2A"
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No Loom resource found linked to registry record {record_id}",
                )

    result = client.update_record(
        record_id=record_id,
        name=name,
        descriptor_type=descriptor_type,
        descriptors=descriptors,
        record_version="1.0",
        description=description,
    )
    rec = client.get_record(record_id)
    return _record_to_detail_response(rec) if rec else _record_to_detail_response(result)


@router.post("/records/{record_id}/submit", response_model=RegistryRecordResponse)
def submit_for_approval(
    record_id: str,
    user: UserInfo = Depends(require_scopes("registry:write")),
    db: Session = Depends(get_db),
) -> RegistryRecordResponse:
    """Submit a registry record for approval."""
    client = get_registry_client()
    result = client.submit_for_approval(record_id)

    resource = _find_resource_by_record_id(record_id, db)
    if resource:
        resource.registry_status = "PENDING_APPROVAL"
        db.commit()

    return _record_to_response(result) if result else RegistryRecordResponse(
        record_id=record_id, name="", descriptor_type="", status="PENDING_APPROVAL",
    )


@router.post("/records/{record_id}/approve", response_model=RegistryRecordResponse)
def approve_record(
    record_id: str,
    body: StatusReasonRequest,
    user: UserInfo = Depends(require_scopes("registry:write")),
    db: Session = Depends(get_db),
) -> RegistryRecordResponse:
    """Approve a registry record."""
    client = get_registry_client()
    result = client.approve_record(record_id, reason=body.reason)

    resource = _find_resource_by_record_id(record_id, db)
    if resource:
        resource.registry_status = "APPROVED"
        db.commit()

    return _record_to_response(result) if result else RegistryRecordResponse(
        record_id=record_id, name="", descriptor_type="", status="APPROVED",
    )


@router.post("/records/{record_id}/reject", response_model=RegistryRecordResponse)
def reject_record(
    record_id: str,
    body: StatusReasonRequest,
    user: UserInfo = Depends(require_scopes("registry:write")),
    db: Session = Depends(get_db),
) -> RegistryRecordResponse:
    """Reject a registry record with a reason."""
    client = get_registry_client()
    result = client.reject_record(record_id, reason=body.reason)

    resource = _find_resource_by_record_id(record_id, db)
    if resource:
        resource.registry_status = "REJECTED"
        db.commit()

    return _record_to_response(result) if result else RegistryRecordResponse(
        record_id=record_id, name="", descriptor_type="", status="REJECTED",
    )


@router.delete("/records/{record_id}", response_model=dict)
def delete_record(
    record_id: str,
    user: UserInfo = Depends(require_scopes("registry:write")),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a registry record and clear the Loom resource link."""
    client = get_registry_client()
    client.delete_record(record_id)

    resource = _find_resource_by_record_id(record_id, db)
    if resource:
        resource.registry_record_id = None
        resource.registry_status = None
        db.commit()

    return {"deleted": True, "record_id": record_id}


@router.get("/search", response_model=SearchResponse)
def search_records(
    q: str = Query(..., description="Semantic search query"),
    max_results: int = Query(10, description="Maximum number of results"),
    user: UserInfo = Depends(require_scopes("registry:read")),
) -> SearchResponse:
    """Semantic search over registry records."""
    client = get_registry_client()
    result = client.search_records(query=q, max_results=max_results)
    return SearchResponse(results=result.get("results", []))
