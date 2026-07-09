"""Agent registration, deployment, and management endpoints."""
import concurrent.futures
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db, SessionLocal
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.authorizer_config import AuthorizerConfig
from app.models.config_entry import ConfigEntry
from app.models.a2a import A2aAgent as A2aAgentModel, A2aAgentAccess
from app.models.memory import Memory
from app.models.mcp import McpServer, McpServerAccess
from app.models.session import InvocationSession
from app.models.invocation import Invocation
from app.models.tag_policy import TagPolicy
from app.models.tag_profile import TagProfile
from app.models.managed_role import ManagedRole
from app.models.vpc_config import VpcConfig
from app.routers.utils import get_agent_or_404

from app.services.agentcore import describe_runtime, list_runtime_endpoints
from app.services.deployment import (
    _merge_tags,
    build_agent_artifact,
    create_runtime,
    delete_runtime,
    delete_runtime_endpoint,
    get_runtime,
    get_runtime_endpoint,
    update_runtime,
)
from app.services.iam import (
    _iam_tags,
    create_execution_role,
    delete_execution_role,
    list_agentcore_roles,
    list_cognito_pools,
)
from app.services.credential import create_oauth2_credential_provider, delete_credential_provider
from app.services.harness import (
    create_harness as create_harness_api,
    update_harness as update_harness_api,
    get_harness as get_harness_api,
    delete_harness as delete_harness_api,
)
from app.services.secrets import store_secret, delete_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

DEFAULT_REGION = os.getenv("AWS_REGION", "us-east-1")

_MODELS_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "etc" / "models.json"

def _load_models() -> list[dict[str, Any]]:
    with open(_MODELS_JSON_PATH) as f:
        return json.load(f)

SUPPORTED_MODELS: list[dict[str, Any]] = _load_models()

_RUNTIME_PRICING_PATH = _MODELS_JSON_PATH.parent / "runtime_pricing.json"

def _load_runtime_pricing() -> dict[str, Any]:
    with open(_RUNTIME_PRICING_PATH) as f:
        return json.load(f)

AGENTCORE_RUNTIME_PRICING: dict[str, Any] = _load_runtime_pricing()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class AgentRegisterRequest(BaseModel):
    """Request body for registering an existing agent by ARN."""
    source: str = Field(default="register", description="Must be 'register'")
    arn: str = Field(..., description="AgentCore Runtime ARN")


class AgentDeployRequest(BaseModel):
    """Request body for deploying a new agent."""
    source: str = Field(default="deploy", description="Must be 'deploy'")
    name: str = Field(..., description="Name for the agent runtime")
    description: str = Field(default="", description="Agent description")
    agent_description: str = Field(default="", description="What the agent does")
    behavioral_guidelines: str = Field(default="", description="How it should behave")
    output_expectations: str = Field(default="", description="Output format/style")
    model_id: str = Field(..., description="Bedrock model ID")
    role_arn: str | None = Field(None, description="Existing IAM role ARN or null to create new")
    protocol: str = Field(default="HTTP", description="HTTP, MCP, or A2A")
    network_mode: str = Field(default="PUBLIC", description="PUBLIC or VPC")
    vpc_config_id: int | None = Field(None, description="VPC configuration ID (required when network_mode is VPC)")
    idle_timeout: int | None = Field(None, description="Idle runtime session timeout (seconds)")
    max_lifetime: int | None = Field(None, description="Max lifetime (seconds)")
    authorizer_type: str | None = Field(None, description="Authorizer type: 'cognito', 'entra_id', 'okta', or 'other'")
    authorizer_pool_id: str | None = Field(None, description="Cognito pool ID for authorizer (when type is 'cognito')")
    authorizer_discovery_url: str | None = Field(None, description="OIDC discovery URL (when type is 'other')")
    authorizer_allowed_audience: list[str] = Field(default_factory=list, description="Allowed JWT audience values")
    authorizer_allowed_clients: list[str] = Field(default_factory=list, description="Allowed client IDs")
    authorizer_allowed_scopes: list[str] = Field(default_factory=list, description="Allowed OAuth scopes")
    authorizer_client_id: str | None = Field(None, description="App client ID for Cognito token retrieval")
    authorizer_client_secret: str | None = Field(None, description="App client secret for Cognito token retrieval")
    memory_enabled: bool = Field(default=False, description="Enable memory integration")
    memory_ids: list[int] = Field(default_factory=list, description="Memory resource IDs to integrate")
    mcp_servers: list[int] = Field(default_factory=list, description="MCP server IDs to integrate")
    a2a_agents: list[int] = Field(default_factory=list, description="A2A agent IDs to integrate")
    tags: dict[str, str] | None = Field(None, description="Build-time tag values")


class AgentCreateRequest(BaseModel):
    """Unified request model that accepts register, deploy, or harness payloads."""
    source: str = Field(default="register", description="Creation mode: 'register', 'deploy', or 'harness'")
    # Register fields
    arn: str | None = Field(None, description="AgentCore Runtime ARN (required for register)")
    # Deploy fields
    name: str | None = Field(None, description="Agent name (required for deploy/harness)")
    description: str = Field(default="", description="Agent description")
    agent_description: str = Field(default="", description="What the agent does")
    behavioral_guidelines: str = Field(default="", description="How it should behave")
    output_expectations: str = Field(default="", description="Output format/style")
    model_id: str | None = Field(None, description="Bedrock model ID (required for deploy/harness)")
    allowed_model_ids: list[str] | None = Field(None, description="Subset of models the user may select at invoke time")
    role_arn: str | None = Field(None, description="Existing IAM role ARN or null to create new")
    protocol: str = Field(default="HTTP", description="HTTP, MCP, or A2A")
    network_mode: str = Field(default="PUBLIC", description="PUBLIC or VPC")
    vpc_config_id: int | None = Field(None, description="VPC configuration ID (required when network_mode is VPC)")
    idle_timeout: int | None = Field(None, description="Idle runtime session timeout (seconds)")
    max_lifetime: int | None = Field(None, description="Max lifetime (seconds)")
    authorizer_type: str | None = Field(None, description="Authorizer type: 'cognito', 'entra_id', 'okta', or 'other'")
    authorizer_pool_id: str | None = Field(None, description="Cognito pool ID for authorizer (when type is 'cognito')")
    authorizer_discovery_url: str | None = Field(None, description="OIDC discovery URL (when type is 'other')")
    authorizer_allowed_audience: list[str] = Field(default_factory=list, description="Allowed JWT audience values")
    authorizer_allowed_clients: list[str] = Field(default_factory=list, description="Allowed client IDs")
    authorizer_allowed_scopes: list[str] = Field(default_factory=list, description="Allowed OAuth scopes")
    authorizer_client_id: str | None = Field(None, description="App client ID for Cognito token retrieval")
    authorizer_client_secret: str | None = Field(None, description="App client secret for Cognito token retrieval")
    memory_enabled: bool = Field(default=False, description="Enable memory integration")
    memory_ids: list[int] = Field(default_factory=list, description="Memory resource IDs to integrate")
    mcp_servers: list[int] = Field(default_factory=list, description="MCP server IDs to integrate")
    a2a_agents: list[int] = Field(default_factory=list, description="A2A agent IDs to integrate")
    code_interpreter_enabled: bool = Field(default=False, description="Enable Code Interpreter tool")
    code_interpreter_region: str = Field(default="", description="AWS region for Code Interpreter (empty = agent region)")
    code_interpreter_network_mode: str = Field(default="SANDBOX", description="Code Interpreter network mode: PUBLIC, SANDBOX, or VPC")
    code_interpreter_role_id: int | None = Field(None, description="Managed role ID for Code Interpreter execution role")
    tags: dict[str, str] | None = Field(None, description="Build-time tag values")
    # Harness-specific fields
    harness_tools: list[dict[str, Any]] | None = Field(None, description="Harness tool configurations")
    harness_max_iterations: int | None = Field(None, description="Max agent loop iterations (default: 75)")
    harness_max_tokens: int | None = Field(None, description="Max tokens for model output")


class AgentResponse(BaseModel):
    """Response model for agent details."""
    id: int
    arn: str
    runtime_id: str
    name: str | None
    description: str | None = None
    status: str | None
    region: str
    account_id: str
    log_group: str | None
    available_qualifiers: list[str]
    source: str | None = None
    deployment_status: str | None = None
    execution_role_arn: str | None = None
    config_hash: str | None = None
    endpoint_name: str | None = None
    endpoint_arn: str | None = None
    endpoint_status: str | None = None
    protocol: str | None = None
    network_mode: str | None = None
    vpc_config_id: int | None = None
    tags: dict[str, str] = {}
    authorizer_config: dict | None = None
    model_id: str | None = None
    allowed_model_ids: list[str] = []
    deployed_at: str | None = None
    harness_id: str | None = None
    registry_record_id: str | None = None
    registry_status: str | None = None
    registered_at: str | None
    last_refreshed_at: str | None
    active_session_count: int
    cost_summary: dict | None = None
    memory_names: list[str] = []
    mcp_names: list[str] = []
    a2a_names: list[str] = []
    code_interpreter_id: str | None = None
    code_interpreter_status: str | None = None
    status_reason: str | None = None


class ConfigEntryResponse(BaseModel):
    """Response model for a config entry."""
    id: int
    agent_id: int
    key: str
    value: str | None
    is_secret: bool
    source: str | None
    created_at: str | None
    updated_at: str | None


class ConfigUpdateRequest(BaseModel):
    """Request body for updating agent config entries."""
    config: dict[str, str] = Field(..., description="Key-value pairs to set")


class AgentUpdateRequest(BaseModel):
    """Request body for patching editable agent fields."""
    description: str | None = None
    model_id: str | None = None
    allowed_model_ids: list[str] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_arn(arn: str) -> tuple[str, str, str]:
    """
    Parse AgentCore Runtime ARN to extract region, account_id, and runtime_id.

    Returns:
        tuple of (region, account_id, runtime_id)
    """
    pattern = r"^arn:aws:bedrock-agentcore:([^:]+):([^:]+):runtime/(.+)$"
    match = re.match(pattern, arn)
    if not match:
        raise ValueError(f"Invalid AgentCore Runtime ARN format: {arn}")
    return match.group(1), match.group(2), match.group(3)


def derive_log_group(runtime_id: str, qualifier: str) -> str:
    """Derive CloudWatch log group name for a runtime and qualifier."""
    return f"/aws/bedrock-agentcore/runtimes/{runtime_id}-{qualifier}"


def compute_active_session_count(agent_id: int, db: Session) -> int:
    """Count sessions that are likely still warm in AWS."""
    timeout_seconds = int(os.getenv("LOOM_SESSION_IDLE_TIMEOUT_SECONDS", "300"))
    now_ts = time.time()
    now_dt = datetime.utcnow()

    sessions = db.query(InvocationSession).filter(
        InvocationSession.agent_id == agent_id
    ).all()

    count = 0
    for session in sessions:
        if session.status in ("pending", "streaming"):
            count += 1
            continue

        max_done_time = db.query(func.max(Invocation.client_done_time)).filter(
            Invocation.session_id == session.session_id
        ).scalar()

        if max_done_time is not None:
            if (now_ts - max_done_time) < timeout_seconds:
                count += 1
        elif session.created_at:
            if (now_dt - session.created_at).total_seconds() < timeout_seconds:
                count += 1

    return count


def _agent_response(agent: Agent, db: Session) -> AgentResponse:
    """Build an AgentResponse from an Agent ORM object."""
    model_id = None
    memory_names: list[str] = []
    mcp_names: list[str] = []
    a2a_names: list[str] = []

    for entry in agent.config_entries:
        if entry.key == "AGENT_CONFIG_JSON":
            try:
                config = json.loads(entry.value)
                model_id = config.get("model_id")

                # Extract integration names from config
                integrations = config.get("integrations", {})

                # Memory resources
                memory_resources = integrations.get("memory", {}).get("resources", [])
                for mem_res in memory_resources:
                    mem_id = mem_res.get("memory_id")
                    if mem_id:
                        mem_record = db.query(Memory).filter(Memory.memory_id == mem_id).first()
                        if mem_record:
                            memory_names.append(mem_record.name)

                # MCP servers
                mcp_servers = integrations.get("mcp_servers", [])
                for mcp_server in mcp_servers:
                    mcp_name = mcp_server.get("name")
                    if mcp_name:
                        mcp_names.append(mcp_name)

                # A2A agents
                a2a_agents = integrations.get("a2a_agents", [])
                for a2a_agent in a2a_agents:
                    a2a_name = a2a_agent.get("name")
                    if a2a_name:
                        a2a_names.append(a2a_name)

            except (json.JSONDecodeError, TypeError):
                pass
            break

    agent_dict = agent.to_dict()

    # Enrich authorizer_config with the matching AuthorizerConfig name
    auth_cfg = agent_dict.get("authorizer_config")
    if auth_cfg:
        ac = None
        if auth_cfg.get("pool_id"):
            ac = db.query(AuthorizerConfig).filter(AuthorizerConfig.pool_id == auth_cfg["pool_id"]).first()
        if not ac and auth_cfg.get("discovery_url"):
            ac = db.query(AuthorizerConfig).filter(AuthorizerConfig.discovery_url == auth_cfg["discovery_url"]).first()
        if ac:
            auth_cfg["name"] = ac.name

    # Compute cost summary from invocations.
    # Sum per-invocation pre-rounded values so totals match what the detail
    # pages display (avoids rounding discrepancies from recomputing off
    # aggregate duration).
    base_q = db.query(Invocation).join(
        InvocationSession, Invocation.session_id == InvocationSession.session_id
    ).filter(InvocationSession.agent_id == agent.id)
    total_input = base_q.with_entities(func.sum(Invocation.input_tokens)).scalar() or 0
    total_output = base_q.with_entities(func.sum(Invocation.output_tokens)).scalar() or 0
    total_est = base_q.with_entities(func.sum(Invocation.estimated_cost)).scalar() or 0.0
    total_idle_mem = base_q.with_entities(func.sum(Invocation.idle_memory_cost)).scalar() or 0.0
    total_stm = base_q.with_entities(func.sum(Invocation.stm_cost)).scalar() or 0.0
    total_ltm = base_q.with_entities(func.sum(Invocation.ltm_cost)).scalar() or 0.0
    inv_count = base_q.with_entities(func.count(Invocation.id)).scalar() or 0

    # Recompute per-invocation runtime costs at view time (matching _apply_view_time_costs)
    from app.routers.settings import get_cpu_io_wait_discount
    io_discount = get_cpu_io_wait_discount(db)
    invocations = base_q.all()
    rt_cpu = 0.0
    rt_mem_compute = 0.0
    for inv in invocations:
        dur = inv.client_duration_ms
        if dur is not None and dur > 0:
            hours = dur / 1000 / 3600
            raw_cpu = hours * AGENTCORE_RUNTIME_PRICING["default_vcpu"] * AGENTCORE_RUNTIME_PRICING["cpu_per_vcpu_hour"]
            rt_cpu += round(raw_cpu * (1.0 - io_discount), 6)
            rt_mem_compute += round(hours * AGENTCORE_RUNTIME_PRICING["default_memory_gb"] * AGENTCORE_RUNTIME_PRICING["memory_per_gb_hour"], 6)
    rt_total = rt_cpu + rt_mem_compute + total_idle_mem
    mem_total = total_stm + total_ltm
    grand_total = total_est + rt_total + mem_total

    # Derive allowed_model_ids: use agent column if set, else default to [model_id]
    allowed_models = agent_dict.pop("allowed_model_ids", [])
    if not allowed_models and model_id:
        allowed_models = [model_id]

    result = AgentResponse(
        **agent_dict,
        model_id=model_id,
        allowed_model_ids=allowed_models,
        active_session_count=compute_active_session_count(agent.id, db),
        memory_names=memory_names,
        mcp_names=mcp_names,
        a2a_names=a2a_names,
        code_interpreter_status=None,
    )
    if inv_count > 0 and grand_total > 0:
        result.cost_summary = {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_model_cost": round(total_est, 6),
            "total_runtime_cost": round(rt_total, 6),
            "total_memory_cost": round(mem_total, 6),
            "total_cost": round(grand_total, 6),
            "total_invocations": inv_count,
        }
    else:
        result.cost_summary = None
    return result


def _resolve_tags(
    db: Session,
    user_tags: dict[str, str] | None = None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Resolve final tag values from tag policies and user-supplied tags.

    Returns:
        Tuple of (resolved_tags dict, tag_policies as list of dicts).
    Raises:
        HTTPException if required tags are missing.
    """
    policies = db.query(TagPolicy).all()
    policy_dicts = [{"key": p.key, "default_value": p.default_value, "required": p.required} for p in policies]

    resolved: dict[str, str] = {}
    missing: list[str] = []
    user_tags = user_tags or {}

    for p in policies:
        if p.key in user_tags:
            resolved[p.key] = user_tags[p.key]
        elif p.required:
            if p.default_value:
                resolved[p.key] = p.default_value
            else:
                missing.append(p.key)
        elif p.default_value:
            resolved[p.key] = p.default_value

    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required tags: {', '.join(missing)}",
        )

    return resolved, policy_dicts


def _build_system_prompt(request: AgentCreateRequest) -> str:
    """Combine agent_description, behavioral_guidelines, output_expectations into a system prompt."""
    parts = []
    if request.agent_description:
        parts.append(request.agent_description)
    if request.behavioral_guidelines:
        parts.append(request.behavioral_guidelines)
    if request.output_expectations:
        parts.append(request.output_expectations)
    return "\n\n".join(parts) if parts else "You are a helpful assistant."


# ---------------------------------------------------------------------------
# Discovery endpoints
# ---------------------------------------------------------------------------
@router.get("/roles")
def list_roles(user: UserInfo = Depends(require_scopes("agent:read"))) -> list[dict]:
    """List available IAM roles with bedrock-agentcore trust policy."""
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    return list_agentcore_roles(region)


@router.get("/cognito-pools")
def get_cognito_pools(user: UserInfo = Depends(require_scopes("agent:read"))) -> list[dict]:
    """List available Cognito user pools."""
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    return list_cognito_pools(region)


@router.get("/models")
def get_models(
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return list of admin-enabled model IDs. If none configured, returns all."""
    from app.routers.settings import get_enabled_model_ids
    enabled = get_enabled_model_ids(db)
    if not enabled:
        return SUPPORTED_MODELS
    enabled_set = set(enabled)
    return [m for m in SUPPORTED_MODELS if m["model_id"] in enabled_set]


@router.get("/models/pricing")
def get_model_pricing(
    user: UserInfo = Depends(require_scopes("agent:read")),
) -> list[dict]:
    """Return models with pricing data."""
    return SUPPORTED_MODELS


@router.get("/defaults")
def get_defaults(user: UserInfo = Depends(require_scopes("agent:read"))) -> dict:
    """Return configurable default values for the frontend."""
    return {
        "idle_timeout_seconds": int(os.getenv("LOOM_SESSION_IDLE_TIMEOUT_SECONDS", "300")),
        "max_lifetime_seconds": int(os.getenv("LOOM_SESSION_MAX_LIFETIME_SECONDS", "3600")),
        "region": DEFAULT_REGION,
    }


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------
@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    request: AgentCreateRequest,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> AgentResponse:
    """Create a new agent via registration (existing ARN) or deployment (new runtime)."""
    # Enforce demo-admin group restriction
    if "g-admins-demo" in user.groups and "g-admins-super" not in user.groups:
        agent_group = (request.tags or {}).get("loom:group", "")
        if agent_group != "demo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo admins can only create agents in the 'demo' group"
            )

    # Enforce demo user restrictions: name must start with "demo_"
    if "g-users-demo" in user.groups:
        name = request.name or ""
        if not name.startswith("demo_"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Demo users must prefix agent names with 'demo_'",
            )

    if request.source == "register":
        return _register_agent(request, db)
    elif request.source == "deploy":
        return _deploy_agent(request, db, background_tasks)
    elif request.source == "harness":
        return _deploy_harness(request, db, background_tasks)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source: {request.source}. Must be 'register', 'deploy', or 'harness'."
        )


def _register_agent(request: AgentCreateRequest, db: Session) -> AgentResponse:
    """Register an existing agent by ARN."""
    if not request.arn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'arn' is required when source is 'register'"
        )

    existing_agent = db.query(Agent).filter(Agent.arn == request.arn).first()
    if existing_agent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with ARN {request.arn} is already registered with ID {existing_agent.id}"
        )

    try:
        region, account_id, runtime_id = parse_arn(request.arn)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        metadata = describe_runtime(request.arn, region)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to describe runtime: {str(e)}"
        )

    try:
        qualifiers = list_runtime_endpoints(runtime_id, region)
    except Exception:
        qualifiers = ["DEFAULT"]

    protocol_config = metadata.get("protocolConfiguration", {})
    protocol = protocol_config.get("serverProtocol", "HTTP")
    network_config = metadata.get("networkConfiguration", {})
    network_mode = network_config.get("networkMode", "PUBLIC")

    # Extract authorizer configuration from runtime metadata
    authorizer_metadata = metadata.get("authorizerConfiguration", {})
    jwt_authorizer = authorizer_metadata.get("customJWTAuthorizer", {})
    imported_authorizer = None
    if jwt_authorizer:
        discovery_url = jwt_authorizer.get("discoveryUrl", "")
        auth_type = "cognito" if "cognito-idp" in discovery_url else "other"
        imported_authorizer = {
            "type": auth_type,
            "discovery_url": discovery_url,
            "allowed_audience": jwt_authorizer.get("allowedAudience", []),
            "allowed_clients": jwt_authorizer.get("allowedClients", []),
            "allowed_scopes": jwt_authorizer.get("allowedScopes", []),
        }

    agent = Agent(
        arn=request.arn,
        runtime_id=runtime_id,
        name=metadata.get("agentRuntimeName"),
        status=metadata.get("status"),
        region=region,
        account_id=account_id,
        log_group=derive_log_group(runtime_id, qualifiers[0]) if qualifiers else None,
        source="register",
        protocol=protocol,
        network_mode=network_mode,
        registered_at=datetime.utcnow(),
        last_refreshed_at=datetime.utcnow(),
    )
    agent.set_available_qualifiers(qualifiers)
    agent.set_raw_metadata(metadata)
    if imported_authorizer:
        agent.set_authorizer_config(imported_authorizer)

    db.add(agent)
    db.commit()
    db.refresh(agent)

    # Fetch tags from AWS for registered agents
    aws_tags: dict[str, str] = {}
    try:
        import boto3
        control_client = boto3.client("bedrock-agentcore-control", region_name=region)
        tag_response = control_client.list_tags_for_resource(resourceArn=request.arn)
        aws_tags = tag_response.get("tags", {})
    except Exception as e:
        logger.debug("Could not fetch tags for registered agent %s: %s", request.arn, e)

    # Enforce tag policies: add missing required tags with value "missing"
    policies = db.query(TagPolicy).all()
    for p in policies:
        if p.key not in aws_tags and p.required:
            aws_tags[p.key] = p.default_value if p.default_value else "missing"

    if aws_tags:
        agent.set_tags(aws_tags)
        db.commit()

    # Store model_id as config entry if provided
    if request.model_id:
        config_json = json.dumps({"model_id": request.model_id})
        entry = ConfigEntry(
            agent_id=agent.id,
            key="AGENT_CONFIG_JSON",
            value=config_json,
            is_secret=False,
            source="env_var",
        )
        db.add(entry)

    # Store allowed_model_ids (default to [model_id] if not specified)
    if request.allowed_model_ids:
        agent.set_allowed_model_ids(request.allowed_model_ids)
    elif request.model_id:
        agent.set_allowed_model_ids([request.model_id])

    db.commit()
    db.refresh(agent)

    return _agent_response(agent, db)


def _deploy_agent(request: AgentCreateRequest, db: Session, background_tasks: BackgroundTasks) -> AgentResponse:
    """Deploy a new agent runtime to AgentCore.

    Validates inputs synchronously, creates the agent record, then schedules the
    heavy work (credential providers, IAM role, artifact build, runtime creation)
    as a background task so the API returns immediately.
    """
    if not request.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'name' is required when source is 'deploy'"
        )
    if not request.model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'model_id' is required when source is 'deploy'"
        )

    # AgentCore runtime names must match [a-zA-Z][a-zA-Z0-9_]{0,47}
    runtime_name_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$")
    if not runtime_name_pattern.match(request.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid agent name '{request.name}'. "
                "Must start with a letter, contain only letters, digits, and underscores, "
                "and be at most 48 characters."
            )
        )

    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    account_id = os.getenv("AWS_ACCOUNT_ID", "")

    # Resolve tags from tag policies + user-supplied profile values
    resolved_tags, tag_policy_dicts = _resolve_tags(db, request.tags)

    # Build system prompt and model config
    system_prompt = _build_system_prompt(request)
    model_max_tokens = next(
        (m["max_tokens"] for m in SUPPORTED_MODELS if m["model_id"] == request.model_id),
        4096,
    )

    # Validate MCP server IDs early (before creating agent record)
    mcp_records: list[McpServer] = []
    if request.mcp_servers:
        mcp_records = db.query(McpServer).filter(McpServer.id.in_(request.mcp_servers)).all()
        found_ids = {s.id for s in mcp_records}
        missing = set(request.mcp_servers) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MCP server IDs not found: {sorted(missing)}"
            )

        # If registry is configured, only allow APPROVED MCP servers
        from app.services.registry import get_registry_client
        reg_client = get_registry_client()
        if reg_client.registry_id:
            for srv in mcp_records:
                if srv.registry_status and srv.registry_status != "APPROVED":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"MCP server '{srv.name}' is not approved in the registry (status: {srv.registry_status}). Only approved servers can be used in agent deployments.",
                    )

    # Validate A2A agent IDs early
    a2a_records: list[A2aAgentModel] = []
    if request.a2a_agents:
        a2a_records = db.query(A2aAgentModel).filter(A2aAgentModel.id.in_(request.a2a_agents)).all()
        found_ids = {a.id for a in a2a_records}
        missing = set(request.a2a_agents) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A2A agent IDs not found: {sorted(missing)}"
            )

        # If registry is configured, only allow APPROVED A2A agents
        from app.services.registry import get_registry_client as _get_reg_client
        _reg_client = _get_reg_client()
        if _reg_client.registry_id:
            for a2a in a2a_records:
                if a2a.registry_status and a2a.registry_status != "APPROVED":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"A2A agent '{a2a.name}' is not approved in the registry (status: {a2a.registry_status}). Only approved agents can be used in agent deployments.",
                    )

    # Validate Memory IDs early
    memory_records: list[Memory] = []
    if request.memory_ids:
        memory_records = db.query(Memory).filter(Memory.id.in_(request.memory_ids)).all()
        found_ids = {m.id for m in memory_records}
        missing = set(request.memory_ids) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Memory IDs not found: {sorted(missing)}"
            )

    # Snapshot MCP server data for the background task (avoid lazy-load after session close)
    mcp_snapshots = [
        {
            "name": s.name,
            "endpoint_url": s.endpoint_url,
            "transport_type": s.transport_type,
            "auth_type": s.auth_type,
            "oauth2_well_known_url": s.oauth2_well_known_url,
            "oauth2_client_id": s.oauth2_client_id,
            "oauth2_client_secret": s.oauth2_client_secret,
            "oauth2_scopes": s.oauth2_scopes,
            "delegation_mode": (s.delegation_mode or "m2m"),
            "obo_grant_type": s.obo_grant_type,
            "oauth2_audience": s.oauth2_audience,
            "api_key_header_name": s.api_key_header_name,
            "supports_elicitation": s.supports_elicitation == "true",
        }
        for s in mcp_records
    ]

    # Snapshot A2A agent data
    a2a_snapshots = [
        {
            "name": a.name,
            "base_url": a.base_url,
            "auth_type": a.auth_type,
            "oauth2_well_known_url": a.oauth2_well_known_url,
            "oauth2_client_id": a.oauth2_client_id,
            "oauth2_client_secret": a.oauth2_client_secret,
            "oauth2_scopes": a.oauth2_scopes,
            "delegation_mode": (a.delegation_mode or "m2m"),
            "obo_grant_type": a.obo_grant_type,
        }
        for a in a2a_records
    ]

    # Snapshot memory data
    memory_snapshots = [
        {"name": m.name, "memory_id": m.memory_id, "arn": m.arn}
        for m in memory_records
    ]

    # Use a unique placeholder for ARN until deployment completes
    placeholder_arn = f"pending-{uuid4()}"

    # Create agent record with CREATING status — returned to frontend immediately
    # Resolve allowed models: use explicit list if provided, else default to [model_id]
    effective_allowed = request.allowed_model_ids if request.allowed_model_ids else [request.model_id]
    # Ensure the primary model_id is always in the allowed list
    if request.model_id not in effective_allowed:
        effective_allowed = [request.model_id] + effective_allowed

    agent = Agent(
        arn=placeholder_arn,
        runtime_id="",
        name=request.name,
        description=request.description or None,
        status="CREATING",
        region=region,
        account_id=account_id,
        source="deploy",
        deployment_status="initializing",
        protocol=request.protocol,
        network_mode=request.network_mode,
        registered_at=datetime.utcnow(),
    )
    agent.set_allowed_model_ids(effective_allowed)
    if request.network_mode == "VPC":
        agent.vpc_config_id = request.vpc_config_id
    db.add(agent)
    db.commit()
    db.refresh(agent)

    # Apply resolved tags immediately so tag-based filtering (e.g. demo user
    # group restriction) sees the agent as soon as it enters CREATING status.
    if resolved_tags:
        agent.set_tags(resolved_tags)
        db.commit()
        db.refresh(agent)

    agent_id = agent.id
    response_data = AgentResponse(**agent.to_dict(), active_session_count=0)

    # Auto-grant access control for MCP servers and A2A agents with existing rules
    for mcp_server_id in request.mcp_servers:
        # Check if any access rules exist for this MCP server
        existing_rules = db.query(McpServerAccess).filter(
            McpServerAccess.server_id == mcp_server_id
        ).first()

        if existing_rules:
            # Check if a rule already exists for the new agent
            agent_rule = db.query(McpServerAccess).filter(
                McpServerAccess.server_id == mcp_server_id,
                McpServerAccess.persona_id == agent_id
            ).first()

            if not agent_rule:
                # Create new access rule for this agent
                new_rule = McpServerAccess(
                    server_id=mcp_server_id,
                    persona_id=agent_id,
                    access_level="all_tools",
                    allowed_tool_names=None
                )
                db.add(new_rule)

    for a2a_agent_id in request.a2a_agents:
        # Check if any access rules exist for this A2A agent
        existing_rules = db.query(A2aAgentAccess).filter(
            A2aAgentAccess.agent_id == a2a_agent_id
        ).first()

        if existing_rules:
            # Check if a rule already exists for the new agent
            agent_rule = db.query(A2aAgentAccess).filter(
                A2aAgentAccess.agent_id == a2a_agent_id,
                A2aAgentAccess.persona_id == agent_id
            ).first()

            if not agent_rule:
                # Create new access rule for this agent
                new_rule = A2aAgentAccess(
                    agent_id=a2a_agent_id,
                    persona_id=agent_id,
                    access_level="all_skills",
                    allowed_skill_ids=None
                )
                db.add(new_rule)

    # Commit all auto-granted access rules
    if request.mcp_servers or request.a2a_agents:
        db.commit()

    # Schedule heavy deployment work in the background
    background_tasks.add_task(
        _deploy_agent_background,
        agent_id=agent_id,
        request=request,
        mcp_snapshots=mcp_snapshots,
        a2a_snapshots=a2a_snapshots,
        memory_snapshots=memory_snapshots,
        resolved_tags=resolved_tags,
        tag_policy_dicts=tag_policy_dicts,
        system_prompt=system_prompt,
        model_max_tokens=model_max_tokens,
        region=region,
        account_id=account_id,
    )

    return response_data


def _deploy_agent_background(
    agent_id: int,
    request: AgentCreateRequest,
    mcp_snapshots: list[dict[str, Any]],
    a2a_snapshots: list[dict[str, Any]],
    memory_snapshots: list[dict[str, Any]],
    resolved_tags: dict[str, str],
    tag_policy_dicts: list[dict[str, Any]],
    system_prompt: str,
    model_max_tokens: int,
    region: str,
    account_id: str,
) -> None:
    """Background task that performs the actual deployment steps.

    Uses its own DB session since the request session is closed after the response.
    Updates deployment_status at each stage so the frontend can show progress.
    """
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            logger.error("Background deploy: agent %s not found", agent_id)
            return

        # --- Step 1: Create credential providers (if OAuth2 MCP servers or A2A agents exist) ---
        has_oauth2 = any(s["auth_type"] == "oauth2" for s in mcp_snapshots) or any(a["auth_type"] == "oauth2" for a in a2a_snapshots)
        if has_oauth2:
            agent.deployment_status = "creating_credentials"
            db.commit()

        mcp_server_configs: list[dict[str, Any]] = []
        for server in mcp_snapshots:
            entry: dict[str, Any] = {
                "name": server["name"],
                "enabled": True,
                "transport": server["transport_type"],
                "endpoint_url": server["endpoint_url"],
            }
            if server["auth_type"] == "oauth2":
                cp_name = f"loom-{request.name}-mcp-{server['name']}"
                mcp_delegation = server.get("delegation_mode") or "m2m"
                mcp_obo_grant = server.get("obo_grant_type")
                try:
                    cp_response = create_oauth2_credential_provider(
                        name=cp_name,
                        client_id=server["oauth2_client_id"] or "",
                        client_secret=server["oauth2_client_secret"] or "",
                        auth_server_url=server["oauth2_well_known_url"] or "",
                        region=region,
                        tags=resolved_tags,
                        delegation_mode=mcp_delegation,
                        obo_grant_type=mcp_obo_grant,
                    )
                    logger.info(
                        "Created credential provider '%s' for MCP server '%s' (delegation=%s callback=%s)",
                        cp_name, server["name"], mcp_delegation, cp_response.get("callbackUrl"),
                    )
                except Exception as e:
                    logger.error(
                        "Failed to create credential provider for MCP server '%s' after retries: %s",
                        server["name"], e,
                    )
                    agent.status = "FAILED"
                    agent.deployment_status = "credential_creation_failed"
                    db.commit()
                    return
                auth_entry: dict[str, str] = {
                    "type": "oauth2",
                    "credential_provider_name": cp_name,
                    "delegation_mode": mcp_delegation,
                }
                if mcp_obo_grant:
                    auth_entry["obo_grant_type"] = mcp_obo_grant
                if server["oauth2_well_known_url"]:
                    auth_entry["well_known_endpoint"] = server["oauth2_well_known_url"]
                if server["oauth2_scopes"]:
                    auth_entry["scopes"] = server["oauth2_scopes"]
                if server.get("oauth2_audience"):
                    auth_entry["audience"] = server["oauth2_audience"]
                entry["auth"] = auth_entry
            elif server["auth_type"] == "api_key":
                secret_name = f"loom/mcp/{server['name']}/api-key/{{actor_id}}"
                entry["auth"] = {
                    "type": "api_key",
                    "credentials_secret_arn": secret_name,
                    "api_key_header_name": server["api_key_header_name"] or "x-api-key",
                }
            entry["delegation_mode"] = server.get("delegation_mode") or "m2m"
            if server.get("supports_elicitation"):
                entry["supports_elicitation"] = "true"
            mcp_server_configs.append(entry)

        # Build A2A agent configs from snapshots
        a2a_agent_configs: list[dict[str, Any]] = []
        for a2a in a2a_snapshots:
            entry: dict[str, Any] = {
                "name": a2a["name"],
                "enabled": True,
                "endpoint_url": a2a["base_url"],
            }
            if a2a["auth_type"] == "oauth2":
                cp_name = f"loom-{request.name}-a2a-{a2a['name']}"
                a2a_delegation = a2a.get("delegation_mode") or "m2m"
                a2a_obo_grant = a2a.get("obo_grant_type")
                try:
                    cp_response = create_oauth2_credential_provider(
                        name=cp_name,
                        client_id=a2a["oauth2_client_id"] or "",
                        client_secret=a2a["oauth2_client_secret"] or "",
                        auth_server_url=a2a["oauth2_well_known_url"] or "",
                        region=region,
                        tags=resolved_tags,
                        delegation_mode=a2a_delegation,
                        obo_grant_type=a2a_obo_grant,
                    )
                    logger.info(
                        "Created credential provider '%s' for A2A agent '%s' (delegation=%s callback=%s)",
                        cp_name, a2a["name"], a2a_delegation, cp_response.get("callbackUrl"),
                    )
                except Exception as e:
                    logger.error(
                        "Failed to create credential provider for A2A agent '%s' after retries: %s",
                        a2a["name"], e,
                    )
                    agent.status = "FAILED"
                    agent.deployment_status = "credential_creation_failed"
                    db.commit()
                    return
                a2a_auth: dict[str, str] = {
                    "type": "oauth2",
                    "credential_provider_name": cp_name,
                    "delegation_mode": a2a_delegation,
                }
                if a2a_obo_grant:
                    a2a_auth["obo_grant_type"] = a2a_obo_grant
                if a2a["oauth2_well_known_url"]:
                    a2a_auth["well_known_endpoint"] = a2a["oauth2_well_known_url"]
                if a2a["oauth2_scopes"]:
                    a2a_auth["scopes"] = a2a["oauth2_scopes"]
                entry["auth"] = a2a_auth
            entry["delegation_mode"] = a2a.get("delegation_mode") or "m2m"
            a2a_agent_configs.append(entry)

        # Build memory configs from snapshots
        memory_configs = [
            {"name": m["name"], "memory_id": m["memory_id"], "arn": m["arn"]}
            for m in memory_snapshots
        ]

        integrations_config: dict[str, Any] = {
            "mcp_servers": mcp_server_configs,
            "a2a_agents": a2a_agent_configs,
            "memory": {
                "enabled": request.memory_enabled or len(memory_configs) > 0,
                "resources": memory_configs,
            },
        }
        ci_config: dict[str, Any] | None = None
        if request.code_interpreter_enabled:
            ci_config = {
                "enabled": True,
                "region": request.code_interpreter_region or "",
                "network_mode": request.code_interpreter_network_mode or "SANDBOX",
            }
            if request.code_interpreter_role_id:
                ci_role = db.query(ManagedRole).filter(ManagedRole.id == request.code_interpreter_role_id).first()
                if ci_role:
                    ci_config["execution_role_arn"] = ci_role.role_arn
            integrations_config["code_interpreter"] = ci_config

        # --- Step 2: Create or use provided IAM execution role ---
        agent.deployment_status = "creating_role"
        db.commit()

        created_role = False
        execution_role_arn = request.role_arn
        if not execution_role_arn:
            try:
                execution_role_arn = create_execution_role(
                    agent_name=request.name,
                    runtime_id=f"pending-{agent.id}",
                    region=region,
                    account_id=account_id,
                    tag_policies=tag_policy_dicts,
                    extra_tags=resolved_tags,
                    code_interpreter=request.code_interpreter_enabled,
                )
                created_role = True
                agent.execution_role_arn = execution_role_arn
                db.commit()
            except Exception as e:
                agent.deployment_status = "failed"
                agent.status = "FAILED"
                db.commit()
                logger.error("Failed to create execution role for agent %s: %s", agent.id, e)
                return
        else:
            agent.execution_role_arn = execution_role_arn
            db.commit()

        # --- Step 3: Build agent artifact (and optionally create CI resource in parallel) ---
        agent.deployment_status = "building_artifact"
        db.commit()

        _needs_ci_resource = (
            request.code_interpreter_enabled
            and ci_config is not None
            and bool(ci_config.get("execution_role_arn"))
        )

        def _create_ci_resource() -> tuple[str, str]:
            import boto3
            ci_region = (request.code_interpreter_region or "").strip() or region
            base_name = re.sub(r"_?code_interpreter$", "", request.name).strip("_")
            raw_name = f"loom_ci_{base_name}"
            sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name)[:48]
            network_mode = request.code_interpreter_network_mode or "PUBLIC"
            boto_client = boto3.client("bedrock-agentcore-control", region_name=ci_region)
            resp = boto_client.create_code_interpreter(
                name=sanitized,
                executionRoleArn=ci_config["execution_role_arn"],
                networkConfiguration={"networkMode": network_mode},
            )
            return resp["codeInterpreterId"], resp["codeInterpreterArn"]

        ci_future: concurrent.futures.Future | None = None
        ci_executor: concurrent.futures.ThreadPoolExecutor | None = None
        if _needs_ci_resource:
            agent.deployment_status = "creating_ci_resource"
            db.commit()
            ci_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            ci_future = ci_executor.submit(_create_ci_resource)

        try:
            artifact_bucket, artifact_key = build_agent_artifact(region)
        except Exception as e:
            agent.deployment_status = "failed"
            agent.status = "FAILED"
            db.commit()
            if ci_future is not None:
                ci_future.cancel()
            if ci_executor is not None:
                ci_executor.shutdown(wait=False)
            if created_role and execution_role_arn:
                _cleanup_role(execution_role_arn)
            logger.error("Failed to build artifact for agent %s: %s", agent.id, e)
            return

        if ci_future is not None:
            try:
                ci_id, ci_arn = ci_future.result(timeout=60)
                agent.code_interpreter_id = ci_id
                if ci_config is not None:
                    ci_config["identifier"] = ci_id
                db.commit()
                logger.info("Created CI resource %s for agent %s", ci_id, agent.id)
                ci_region = (request.code_interpreter_region or "").strip() or region
                try:
                    from app.services.observability import enable_code_interpreter_observability
                    # Parse account_id from the CI ARN directly — the env var may be empty
                    ci_arn_parts = ci_arn.split(":")
                    ci_account_id = ci_arn_parts[4] if len(ci_arn_parts) >= 6 else account_id
                    ci_obs = enable_code_interpreter_observability(
                        ci_arn=ci_arn,
                        ci_id=ci_id,
                        account_id=ci_account_id,
                        region=ci_region,
                    )
                    logger.info("Enabled CI observability for agent %s: %s", agent.id, ci_obs)
                except Exception as ci_obs_err:
                    logger.warning("Failed to enable CI observability for agent %s: %s", agent.id, ci_obs_err)
            except Exception as ci_err:
                logger.warning("CI resource creation failed for agent %s, continuing: %s", agent.id, ci_err)
            finally:
                if ci_executor is not None:
                    ci_executor.shutdown(wait=False)

        agent.deployment_status = "building_artifact"
        db.commit()

        config_json = json.dumps({
            "system_prompt": system_prompt,
            "model_id": request.model_id,
            "max_tokens": model_max_tokens,
            "integrations": integrations_config,
        })
        env_vars = {
            "AGENT_CONFIG_JSON": config_json,
            "OTEL_SERVICE_NAME": request.name,
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_PROPAGATORS": "xray,tracecontext,b3",
            "WORKLOAD_IDENTITY_NAME": f"loom-{request.name}",
            "AGENT_OBSERVABILITY_ENABLED": "true",
            "AWS_REGION": region,
        }

        for key, value in env_vars.items():
            db.add(ConfigEntry(
                agent_id=agent.id,
                key=key,
                value=value,
                is_secret=False,
                source="env_var",
            ))
        db.commit()

        # Build optional configs
        lifecycle_config = None
        if request.idle_timeout or request.max_lifetime:
            lifecycle_config = {}
            if request.idle_timeout:
                lifecycle_config["idleRuntimeSessionTimeout"] = request.idle_timeout
            if request.max_lifetime:
                lifecycle_config["maxLifetime"] = request.max_lifetime

        authorizer_config = None
        user_client_id = os.getenv("LOOM_COGNITO_USER_CLIENT_ID", "")
        if request.authorizer_type == "cognito" and request.authorizer_pool_id:
            jwt_config: dict[str, Any] = {
                "discoveryUrl": f"https://cognito-idp.{region}.amazonaws.com/{request.authorizer_pool_id}/.well-known/openid-configuration"
            }
            allowed_clients = list(request.authorizer_allowed_clients) if request.authorizer_allowed_clients else []
            if user_client_id and user_client_id not in allowed_clients:
                allowed_clients.append(user_client_id)
            if allowed_clients:
                jwt_config["allowedClients"] = allowed_clients
            if request.authorizer_allowed_audience:
                jwt_config["allowedAudience"] = request.authorizer_allowed_audience
            if request.authorizer_allowed_scopes:
                jwt_config["allowedScopes"] = request.authorizer_allowed_scopes
            authorizer_config = {"customJWTAuthorizer": jwt_config}
        elif request.authorizer_type in ("other", "entra_id", "okta") and request.authorizer_discovery_url:
            jwt_config = {"discoveryUrl": request.authorizer_discovery_url}
            if request.authorizer_allowed_audience:
                jwt_config["allowedAudience"] = request.authorizer_allowed_audience
            # Entra ID v1.0 tokens use 'appid' and Okta tokens use 'cid'
            # instead of the standard 'azp' claim that AgentCore validates
            # allowedClients against, so omit it for these providers.
            if request.authorizer_allowed_clients and request.authorizer_type not in ("entra_id", "okta"):
                jwt_config["allowedClients"] = request.authorizer_allowed_clients
            if request.authorizer_allowed_scopes:
                jwt_config["allowedScopes"] = request.authorizer_allowed_scopes
            authorizer_config = {"customJWTAuthorizer": jwt_config}

        # --- Step 4: Deploy to AgentCore ---
        if authorizer_config:
            logger.info("Deploying with authorizer_config: %s", authorizer_config)
        agent.deployment_status = "deploying"
        db.commit()

        try:
            vpc_cfg = db.query(VpcConfig).filter(VpcConfig.id == request.vpc_config_id).first() if request.network_mode == "VPC" and request.vpc_config_id else None
            response = create_runtime(
                name=request.name,
                description=request.description,
                role_arn=execution_role_arn,
                env_vars=env_vars,
                network_mode=request.network_mode,
                vpc_subnet_ids=vpc_cfg.get_subnet_ids() if vpc_cfg else None,
                vpc_security_group_ids=vpc_cfg.get_sg_ids() if vpc_cfg else None,
                protocol=request.protocol,
                lifecycle_config=lifecycle_config,
                authorizer_config=authorizer_config,
                artifact_bucket=artifact_bucket,
                artifact_prefix=artifact_key,
                tags=resolved_tags,
                region=region,
            )

            runtime_arn = response.get("agentRuntimeArn", "")
            runtime_id = response.get("agentRuntimeId", "")

            # Extract account_id from the returned ARN
            try:
                _, arn_account_id, _ = parse_arn(runtime_arn)
                agent.account_id = arn_account_id
            except ValueError:
                pass

            agent.arn = runtime_arn
            agent.runtime_id = runtime_id
            agent.deployment_status = "deployed"
            agent.status = response.get("status", "CREATING")
            agent.deployed_at = datetime.utcnow()
            agent.last_refreshed_at = datetime.utcnow()
            agent.log_group = derive_log_group(runtime_id, "DEFAULT") if runtime_id else None
            agent.set_available_qualifiers(["DEFAULT"])
            agent.set_tags(resolved_tags)

            # Enable USAGE_LOGS and APPLICATION_LOGS observability
            try:
                from app.services.observability import enable_runtime_observability
                obs_result = enable_runtime_observability(
                    runtime_arn=runtime_arn,
                    runtime_id=runtime_id,
                    account_id=agent.account_id,
                    region=region,
                )
                logger.info("Enabled observability for agent %s: %s", agent.id, obs_result)
            except Exception as obs_err:
                logger.warning("Failed to enable observability for agent %s: %s", agent.id, obs_err)

            # Persist authorizer config for token retrieval at invoke time
            if request.authorizer_type:
                stored_clients = list(request.authorizer_allowed_clients) if request.authorizer_allowed_clients else []
                if user_client_id and user_client_id not in stored_clients:
                    stored_clients.append(user_client_id)
                agent.set_authorizer_config({
                    "type": request.authorizer_type,
                    "pool_id": request.authorizer_pool_id,
                    "discovery_url": request.authorizer_discovery_url,
                    "allowed_audience": request.authorizer_allowed_audience,
                    "allowed_clients": stored_clients,
                    "allowed_scopes": request.authorizer_allowed_scopes,
                })

                # Store Cognito client credentials for token retrieval
                if request.authorizer_client_id:
                    db.add(ConfigEntry(
                        agent_id=agent.id,
                        key="COGNITO_CLIENT_ID",
                        value=request.authorizer_client_id,
                        is_secret=False,
                        source="env_var",
                    ))
                if request.authorizer_client_id and request.authorizer_client_secret:
                    secret_name = f"loom/agents/{agent.id}/cognito-client-secret"
                    secret_arn = store_secret(
                        name=secret_name,
                        secret_value=request.authorizer_client_secret,
                        region=region,
                        description=f"Cognito client secret for Loom agent {agent.id} (client_id: {request.authorizer_client_id})",
                    )
                    db.add(ConfigEntry(
                        agent_id=agent.id,
                        key="COGNITO_CLIENT_SECRET_ARN",
                        value=secret_arn,
                        is_secret=True,
                        source="secrets_manager",
                    ))

            db.commit()
        except Exception as e:
            agent.deployment_status = "failed"
            agent.status = "FAILED"
            db.commit()
            if created_role and execution_role_arn:
                _cleanup_role(execution_role_arn)
            logger.error("Failed to deploy agent %s: %s", agent.id, e)
    except Exception as e:
        logger.error("Unexpected error in background deploy for agent %s: %s", agent_id, e)
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                agent.deployment_status = "failed"
                agent.status = "FAILED"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _update_deploy_agent_background(
    agent_id: int,
    request: AgentCreateRequest,
    mcp_snapshots: list[dict[str, Any]],
    a2a_snapshots: list[dict[str, Any]],
    memory_snapshots: list[dict[str, Any]],
    resolved_tags: dict[str, str],
    tag_policy_dicts: list[dict[str, Any]],
    system_prompt: str,
    model_max_tokens: int,
    old_cp_names: set[str],
    region: str,
    account_id: str,
) -> None:
    """Background task that updates an existing deploy-type agent runtime in-place.

    Rebuilds the artifact, reconciles credential providers, and calls update_runtime
    so the existing AgentCore Runtime ID is preserved.
    """
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            logger.error("Background deploy update: agent %s not found", agent_id)
            return

        # --- Step 1: Reconcile credential providers ---
        new_cp_names: set[str] = set()
        mcp_server_configs: list[dict[str, Any]] = []

        for server in mcp_snapshots:
            entry: dict[str, Any] = {
                "name": server["name"],
                "enabled": True,
                "transport": server["transport_type"],
                "endpoint_url": server["endpoint_url"],
            }
            if server["auth_type"] == "oauth2":
                cp_name = f"loom-{request.name}-mcp-{server['name']}"
                new_cp_names.add(cp_name)
                mcp_delegation = server.get("delegation_mode") or "m2m"
                mcp_obo_grant = server.get("obo_grant_type")
                if cp_name not in old_cp_names:
                    try:
                        create_oauth2_credential_provider(
                            name=cp_name,
                            client_id=server["oauth2_client_id"] or "",
                            client_secret=server["oauth2_client_secret"] or "",
                            auth_server_url=server["oauth2_well_known_url"] or "",
                            region=region,
                            tags=resolved_tags,
                            delegation_mode=mcp_delegation,
                            obo_grant_type=mcp_obo_grant,
                        )
                        logger.info("Created credential provider '%s' for MCP server '%s'", cp_name, server["name"])
                    except Exception as e:
                        logger.error("Failed to create credential provider for MCP '%s': %s", server["name"], e)
                        agent.status = "FAILED"
                        agent.deployment_status = "credential_creation_failed"
                        db.commit()
                        return
                auth_entry: dict[str, str] = {
                    "type": "oauth2",
                    "credential_provider_name": cp_name,
                    "delegation_mode": mcp_delegation,
                }
                if mcp_obo_grant:
                    auth_entry["obo_grant_type"] = mcp_obo_grant
                if server["oauth2_well_known_url"]:
                    auth_entry["well_known_endpoint"] = server["oauth2_well_known_url"]
                if server["oauth2_scopes"]:
                    auth_entry["scopes"] = server["oauth2_scopes"]
                if server.get("oauth2_audience"):
                    auth_entry["audience"] = server["oauth2_audience"]
                entry["auth"] = auth_entry
            elif server["auth_type"] == "api_key":
                secret_name = f"loom/mcp/{server['name']}/api-key/{{actor_id}}"
                entry["auth"] = {
                    "type": "api_key",
                    "credentials_secret_arn": secret_name,
                    "api_key_header_name": server["api_key_header_name"] or "x-api-key",
                }
            entry["delegation_mode"] = server.get("delegation_mode") or "m2m"
            if server.get("supports_elicitation"):
                entry["supports_elicitation"] = "true"
            mcp_server_configs.append(entry)

        removed_cps = old_cp_names - new_cp_names
        for cp_name in removed_cps:
            try:
                delete_credential_provider(cp_name, region)
                logger.info("Deleted old credential provider '%s'", cp_name)
            except Exception as e:
                logger.warning("Failed to delete old credential provider '%s': %s", cp_name, e)

        # Build A2A agent configs
        a2a_agent_configs: list[dict[str, Any]] = []
        for a2a in a2a_snapshots:
            entry = {
                "name": a2a["name"],
                "enabled": True,
                "endpoint_url": a2a["base_url"],
            }
            if a2a["auth_type"] == "oauth2":
                cp_name = f"loom-{request.name}-a2a-{a2a['name']}"
                new_cp_names.add(cp_name)
                a2a_delegation = a2a.get("delegation_mode") or "m2m"
                a2a_obo_grant = a2a.get("obo_grant_type")
                if cp_name not in old_cp_names:
                    try:
                        create_oauth2_credential_provider(
                            name=cp_name,
                            client_id=a2a["oauth2_client_id"] or "",
                            client_secret=a2a["oauth2_client_secret"] or "",
                            auth_server_url=a2a["oauth2_well_known_url"] or "",
                            region=region,
                            tags=resolved_tags,
                            delegation_mode=a2a_delegation,
                            obo_grant_type=a2a_obo_grant,
                        )
                    except Exception as e:
                        logger.error("Failed to create credential provider for A2A '%s': %s", a2a["name"], e)
                        agent.status = "FAILED"
                        agent.deployment_status = "credential_creation_failed"
                        db.commit()
                        return
                a2a_auth: dict[str, str] = {
                    "type": "oauth2",
                    "credential_provider_name": cp_name,
                    "delegation_mode": a2a_delegation,
                }
                if a2a_obo_grant:
                    a2a_auth["obo_grant_type"] = a2a_obo_grant
                if a2a["oauth2_well_known_url"]:
                    a2a_auth["well_known_endpoint"] = a2a["oauth2_well_known_url"]
                if a2a["oauth2_scopes"]:
                    a2a_auth["scopes"] = a2a["oauth2_scopes"]
                entry["auth"] = a2a_auth
            entry["delegation_mode"] = a2a.get("delegation_mode") or "m2m"
            a2a_agent_configs.append(entry)

        memory_configs = [
            {"name": m["name"], "memory_id": m["memory_id"], "arn": m["arn"]}
            for m in memory_snapshots
        ]

        integrations_config: dict[str, Any] = {
            "mcp_servers": mcp_server_configs,
            "a2a_agents": a2a_agent_configs,
            "memory": {
                "enabled": request.memory_enabled or len(memory_configs) > 0,
                "resources": memory_configs,
            },
        }
        if request.code_interpreter_enabled:
            ci_config: dict[str, Any] = {
                "enabled": True,
                "region": request.code_interpreter_region or "",
                "network_mode": request.code_interpreter_network_mode or "SANDBOX",
            }
            if request.code_interpreter_role_id:
                ci_role = db.query(ManagedRole).filter(ManagedRole.id == request.code_interpreter_role_id).first()
                if ci_role:
                    ci_config["execution_role_arn"] = ci_role.role_arn
            integrations_config["code_interpreter"] = ci_config

        # --- Step 2: Rebuild artifact ---
        agent.deployment_status = "building_artifact"
        db.commit()

        try:
            artifact_bucket, artifact_key = build_agent_artifact(region)
        except Exception as e:
            agent.deployment_status = "failed"
            agent.status = "FAILED"
            db.commit()
            logger.error("Failed to build artifact for agent %s: %s", agent.id, e)
            return

        config_json = json.dumps({
            "system_prompt": system_prompt,
            "model_id": request.model_id,
            "max_tokens": model_max_tokens,
            "integrations": integrations_config,
        })
        env_vars = {
            "AGENT_CONFIG_JSON": config_json,
            "OTEL_SERVICE_NAME": request.name,
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_PROPAGATORS": "xray,tracecontext,b3",
            "WORKLOAD_IDENTITY_NAME": f"loom-{request.name}",
            "AGENT_OBSERVABILITY_ENABLED": "true",
            "AWS_REGION": region,
        }

        # Replace config entries
        db.query(ConfigEntry).filter(ConfigEntry.agent_id == agent_id).delete()
        for key, value in env_vars.items():
            db.add(ConfigEntry(
                agent_id=agent.id,
                key=key,
                value=value,
                is_secret=False,
                source="env_var",
            ))
        db.commit()

        lifecycle_config = None
        if request.idle_timeout or request.max_lifetime:
            lifecycle_config = {}
            if request.idle_timeout:
                lifecycle_config["idleRuntimeSessionTimeout"] = request.idle_timeout
            if request.max_lifetime:
                lifecycle_config["maxLifetime"] = request.max_lifetime

        authorizer_config = None
        user_client_id = os.getenv("LOOM_COGNITO_USER_CLIENT_ID", "")
        if request.authorizer_type == "cognito" and request.authorizer_pool_id:
            jwt_config: dict[str, Any] = {
                "discoveryUrl": f"https://cognito-idp.{region}.amazonaws.com/{request.authorizer_pool_id}/.well-known/openid-configuration"
            }
            allowed_clients = list(request.authorizer_allowed_clients) if request.authorizer_allowed_clients else []
            if user_client_id and user_client_id not in allowed_clients:
                allowed_clients.append(user_client_id)
            if allowed_clients:
                jwt_config["allowedClients"] = allowed_clients
            if request.authorizer_allowed_audience:
                jwt_config["allowedAudience"] = request.authorizer_allowed_audience
            if request.authorizer_allowed_scopes:
                jwt_config["allowedScopes"] = request.authorizer_allowed_scopes
            authorizer_config = {"customJWTAuthorizer": jwt_config}
        elif request.authorizer_type in ("other", "entra_id", "okta") and request.authorizer_discovery_url:
            jwt_config = {"discoveryUrl": request.authorizer_discovery_url}
            if request.authorizer_allowed_audience:
                jwt_config["allowedAudience"] = request.authorizer_allowed_audience
            if request.authorizer_allowed_clients and request.authorizer_type not in ("entra_id", "okta"):
                jwt_config["allowedClients"] = request.authorizer_allowed_clients
            if request.authorizer_allowed_scopes:
                jwt_config["allowedScopes"] = request.authorizer_allowed_scopes
            authorizer_config = {"customJWTAuthorizer": jwt_config}

        # --- Step 3: Update runtime in-place ---
        agent.deployment_status = "deploying"
        db.commit()

        try:
            vpc_cfg = db.query(VpcConfig).filter(VpcConfig.id == request.vpc_config_id).first() if request.network_mode == "VPC" and request.vpc_config_id else None
            response = update_runtime(
                runtime_id=agent.runtime_id,
                description=request.description,
                role_arn=agent.execution_role_arn,
                env_vars=env_vars,
                authorizer_config=authorizer_config,
                artifact_bucket=artifact_bucket,
                artifact_prefix=artifact_key,
                network_mode=request.network_mode,
                vpc_subnet_ids=vpc_cfg.get_subnet_ids() if vpc_cfg else None,
                vpc_security_group_ids=vpc_cfg.get_sg_ids() if vpc_cfg else None,
                lifecycle_config=lifecycle_config,
                region=region,
            )

            agent.description = request.description or agent.description
            agent.network_mode = request.network_mode
            agent.vpc_config_id = request.vpc_config_id if request.network_mode == "VPC" else None
            agent.deployment_status = "deployed"
            agent.status = response.get("status", "UPDATING")
            agent.deployed_at = datetime.utcnow()
            agent.last_refreshed_at = datetime.utcnow()

            effective_allowed = request.allowed_model_ids if request.allowed_model_ids else [request.model_id]
            if request.model_id not in effective_allowed:
                effective_allowed = [request.model_id] + effective_allowed
            agent.set_allowed_model_ids(effective_allowed)

            if resolved_tags:
                agent.set_tags(resolved_tags)

            if request.authorizer_type:
                stored_clients = list(request.authorizer_allowed_clients) if request.authorizer_allowed_clients else []
                if user_client_id and user_client_id not in stored_clients:
                    stored_clients.append(user_client_id)
                agent.set_authorizer_config({
                    "type": request.authorizer_type,
                    "pool_id": request.authorizer_pool_id,
                    "discovery_url": request.authorizer_discovery_url,
                    "allowed_audience": request.authorizer_allowed_audience,
                    "allowed_clients": stored_clients,
                    "allowed_scopes": request.authorizer_allowed_scopes,
                })

            db.commit()
            logger.info("Deploy agent update complete: agent=%s runtime_id=%s", agent_id, agent.runtime_id)
        except Exception as e:
            agent.deployment_status = "failed"
            agent.status = "FAILED"
            db.commit()
            logger.error("Failed to update runtime for agent %s: %s", agent.id, e)
    except Exception as e:
        logger.error("Unexpected error in background deploy update for agent %s: %s", agent_id, e)
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                agent.deployment_status = "failed"
                agent.status = "FAILED"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _deploy_harness(request: AgentCreateRequest, db: Session, background_tasks: BackgroundTasks) -> AgentResponse:
    """Deploy a managed agent via AgentCore Harness.

    Simpler than _deploy_agent — no artifact build or credential provider creation.
    """
    if not request.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'name' is required when source is 'harness'"
        )
    if not request.model_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'model_id' is required when source is 'harness'"
        )
    if not request.role_arn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'role_arn' is required when source is 'harness'"
        )

    runtime_name_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$")
    if not runtime_name_pattern.match(request.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid agent name '{request.name}'. "
                "Must start with a letter, contain only letters, digits, and underscores, "
                "and be at most 48 characters."
            )
        )

    existing = db.query(Agent).filter(Agent.name == request.name, Agent.source == "harness").first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A harness agent named '{request.name}' already exists (id={existing.id}). Use the update endpoint or delete it first.",
        )

    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    account_id = os.getenv("AWS_ACCOUNT_ID", "")

    resolved_tags, _ = _resolve_tags(db, request.tags)

    system_prompt = _build_system_prompt(request)

    # Snapshot MCP server data for the background task
    mcp_snapshots: list[dict[str, Any]] = []
    if request.mcp_servers:
        mcp_records = db.query(McpServer).filter(McpServer.id.in_(request.mcp_servers)).all()
        found_ids = {s.id for s in mcp_records}
        missing = set(request.mcp_servers) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MCP server IDs not found: {sorted(missing)}"
            )
        for server in mcp_records:
            mcp_snapshots.append({
                "name": server.name,
                "endpoint_url": server.endpoint_url,
                "transport_type": server.transport_type,
                "auth_type": server.auth_type,
                "oauth2_client_id": server.oauth2_client_id,
                "oauth2_client_secret": server.oauth2_client_secret,
                "oauth2_well_known_url": server.oauth2_well_known_url,
                "oauth2_scopes": server.oauth2_scopes,
                "delegation_mode": (server.delegation_mode or "m2m"),
                "obo_grant_type": server.obo_grant_type,
                "api_key_header_name": server.api_key_header_name,
                "supports_elicitation": server.supports_elicitation == "true",
            })

    extra_harness_tools = request.harness_tools or []

    # Snapshot memory data (first memory resource is passed to harness API)
    memory_snapshots: list[dict[str, Any]] = []
    if request.memory_ids:
        memory_records = db.query(Memory).filter(Memory.id.in_(request.memory_ids)).all()
        memory_snapshots = [
            {"name": m.name, "memory_id": m.memory_id, "arn": m.arn}
            for m in memory_records
        ]

    # Resolve VPC subnet/SG IDs for harness VPC networking
    harness_vpc_subnet_ids: list[str] | None = None
    harness_vpc_sg_ids: list[str] | None = None
    if request.network_mode == "VPC" and request.vpc_config_id:
        vpc_cfg = db.query(VpcConfig).filter(VpcConfig.id == request.vpc_config_id).first()
        if vpc_cfg:
            harness_vpc_subnet_ids = vpc_cfg.get_subnet_ids()
            harness_vpc_sg_ids = vpc_cfg.get_sg_ids()

    # Resolve Code Interpreter config for harness
    harness_ci_config: dict[str, Any] | None = None
    if request.code_interpreter_enabled:
        ci_role_arn = ""
        if request.code_interpreter_role_id:
            ci_role = db.query(ManagedRole).filter(ManagedRole.id == request.code_interpreter_role_id).first()
            if ci_role:
                ci_role_arn = ci_role.role_arn
        harness_ci_config = {
            "region": (request.code_interpreter_region or "").strip(),
            "network_mode": request.code_interpreter_network_mode or "SANDBOX",
            "execution_role_arn": ci_role_arn,
        }

    effective_allowed = request.allowed_model_ids if request.allowed_model_ids else [request.model_id]
    if request.model_id not in effective_allowed:
        effective_allowed = [request.model_id] + effective_allowed

    # Build authorizer configuration (same logic as custom agent deploy)
    authorizer_config = None
    user_client_id = os.getenv("LOOM_COGNITO_USER_CLIENT_ID", "")
    if request.authorizer_type == "cognito" and request.authorizer_pool_id:
        jwt_config: dict[str, Any] = {
            "discoveryUrl": f"https://cognito-idp.{region}.amazonaws.com/{request.authorizer_pool_id}/.well-known/openid-configuration"
        }
        allowed_clients = list(request.authorizer_allowed_clients) if request.authorizer_allowed_clients else []
        if user_client_id and user_client_id not in allowed_clients:
            allowed_clients.append(user_client_id)
        if allowed_clients:
            jwt_config["allowedClients"] = allowed_clients
        if request.authorizer_allowed_audience:
            jwt_config["allowedAudience"] = request.authorizer_allowed_audience
        if request.authorizer_allowed_scopes:
            jwt_config["allowedScopes"] = request.authorizer_allowed_scopes
        authorizer_config = {"customJWTAuthorizer": jwt_config}
    elif request.authorizer_type in ("other", "entra_id", "okta") and request.authorizer_discovery_url:
        jwt_config = {"discoveryUrl": request.authorizer_discovery_url}
        if request.authorizer_allowed_audience:
            jwt_config["allowedAudience"] = request.authorizer_allowed_audience
        if request.authorizer_allowed_clients and request.authorizer_type not in ("entra_id", "okta"):
            jwt_config["allowedClients"] = request.authorizer_allowed_clients
        if request.authorizer_allowed_scopes:
            jwt_config["allowedScopes"] = request.authorizer_allowed_scopes
        authorizer_config = {"customJWTAuthorizer": jwt_config}

    placeholder_arn = f"pending-{uuid4()}"

    agent = Agent(
        arn=placeholder_arn,
        runtime_id="",
        name=request.name,
        description=request.description or None,
        status="CREATING",
        region=region,
        account_id=account_id,
        source="harness",
        deployment_status="initializing",
        execution_role_arn=request.role_arn,
        protocol="HTTP",
        network_mode=request.network_mode,
        vpc_config_id=request.vpc_config_id if request.network_mode == "VPC" else None,
        registered_at=datetime.utcnow(),
    )
    agent.set_allowed_model_ids(effective_allowed)
    if authorizer_config:
        jwt = authorizer_config.get("customJWTAuthorizer", {})
        agent.set_authorizer_config({
            "type": request.authorizer_type,
            "pool_id": request.authorizer_pool_id,
            "discovery_url": jwt.get("discoveryUrl"),
            "allowed_audience": jwt.get("allowedAudience", []),
            "allowed_clients": jwt.get("allowedClients", []),
            "allowed_scopes": jwt.get("allowedScopes", []),
        })
    db.add(agent)
    db.commit()
    db.refresh(agent)

    if resolved_tags:
        agent.set_tags(resolved_tags)
        db.commit()
        db.refresh(agent)

    agent_id = agent.id
    response_data = AgentResponse(**agent.to_dict(), active_session_count=0)

    background_tasks.add_task(
        _deploy_harness_background,
        agent_id=agent_id,
        name=request.name,
        execution_role_arn=request.role_arn,
        model_id=request.model_id,
        system_prompt=system_prompt,
        mcp_snapshots=mcp_snapshots,
        memory_snapshots=memory_snapshots,
        extra_harness_tools=extra_harness_tools,
        max_iterations=request.harness_max_iterations,
        max_tokens=request.harness_max_tokens,
        authorizer_config=authorizer_config,
        network_mode=request.network_mode,
        vpc_subnet_ids=harness_vpc_subnet_ids,
        vpc_security_group_ids=harness_vpc_sg_ids,
        idle_timeout=request.idle_timeout,
        max_lifetime=request.max_lifetime,
        resolved_tags=resolved_tags,
        region=region,
        account_id=account_id,
        ci_config=harness_ci_config,
    )

    return response_data


def _build_harness_tool_for_mcp(server: dict[str, Any]) -> dict[str, Any]:
    """Build a remote_mcp harness tool entry for an MCP server."""
    return {
        "type": "remote_mcp",
        "name": server["name"],
        "config": {"remoteMcp": {"url": server["endpoint_url"]}},
    }


def _deploy_harness_background(
    agent_id: int,
    name: str,
    execution_role_arn: str,
    model_id: str,
    system_prompt: str,
    mcp_snapshots: list[dict[str, Any]],
    extra_harness_tools: list[dict[str, Any]],
    max_iterations: int | None,
    max_tokens: int | None,
    authorizer_config: dict[str, Any] | None,
    network_mode: str,
    idle_timeout: int | None,
    max_lifetime: int | None,
    resolved_tags: dict[str, str],
    region: str,
    account_id: str,
    memory_snapshots: list[dict[str, Any]] | None = None,
    vpc_subnet_ids: list[str] | None = None,
    vpc_security_group_ids: list[str] | None = None,
    ci_config: dict[str, Any] | None = None,
) -> None:
    """Background task that creates credential providers and the harness in AWS."""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            logger.error("Background harness deploy: agent %s not found", agent_id)
            return

        # --- Step 1: Create credential providers for OAuth2 MCP servers ---
        has_oauth2 = any(s["auth_type"] == "oauth2" for s in mcp_snapshots)
        if has_oauth2:
            agent.deployment_status = "creating_credentials"
            db.commit()

        harness_tools: list[dict[str, Any]] = []
        mcp_server_configs: list[dict[str, Any]] = []
        for server in mcp_snapshots:
            cp_name: str | None = None
            cp_arn: str | None = None
            if server["auth_type"] == "oauth2":
                cp_name = f"loom-{name}-mcp-{server['name']}"
                mcp_delegation = server.get("delegation_mode") or "m2m"
                mcp_obo_grant = server.get("obo_grant_type")
                try:
                    cp_response = create_oauth2_credential_provider(
                        name=cp_name,
                        client_id=server["oauth2_client_id"] or "",
                        client_secret=server["oauth2_client_secret"] or "",
                        auth_server_url=server["oauth2_well_known_url"] or "",
                        region=region,
                        tags=resolved_tags if resolved_tags else None,
                        delegation_mode=mcp_delegation,
                        obo_grant_type=mcp_obo_grant,
                    )
                    cp_arn = cp_response.get("arn") or cp_response.get("credentialProviderArn")
                    logger.info(
                        "Created credential provider '%s' for harness MCP server '%s' (arn=%s)",
                        cp_name, server["name"], cp_arn,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to create credential provider for harness MCP '%s': %s",
                        server["name"], e,
                    )
                    agent.status = "FAILED"
                    agent.deployment_status = "credential_creation_failed"
                    db.commit()
                    return

            # Register all MCP tools at deploy time; OAuth2 tokens are injected
            # into remoteMcp.headers at invocation time.
            harness_tools.append(_build_harness_tool_for_mcp(server))

            mcp_entry: dict[str, Any] = {
                "name": server["name"],
                "endpoint_url": server["endpoint_url"],
                "auth_type": server["auth_type"],
            }
            if cp_name:
                harness_auth: dict[str, str] = {
                    "type": "oauth2",
                    "credential_provider_name": cp_name,
                    "delegation_mode": server.get("delegation_mode") or "m2m",
                }
                if server.get("obo_grant_type"):
                    harness_auth["obo_grant_type"] = server["obo_grant_type"]
                mcp_entry["auth"] = harness_auth
            mcp_entry["delegation_mode"] = server.get("delegation_mode") or "m2m"
            if server.get("supports_elicitation"):
                mcp_entry["supports_elicitation"] = "true"
            mcp_server_configs.append(mcp_entry)

        harness_tools.extend(extra_harness_tools)

        # --- Step 2: Create Code Interpreter resource if requested ---
        ci_arn: str | None = None
        if ci_config and ci_config.get("execution_role_arn"):
            agent.deployment_status = "creating_ci_resource"
            db.commit()
            try:
                import boto3 as _boto3
                ci_region = ci_config.get("region") or region
                base_name = re.sub(r"_?code_interpreter$", "", name).strip("_")
                raw_ci_name = f"loom_ci_{base_name}"
                sanitized_ci_name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_ci_name)[:48]
                ci_net_mode = ci_config.get("network_mode") or "SANDBOX"
                ci_boto = _boto3.client("bedrock-agentcore-control", region_name=ci_region)
                # Reuse existing CI resource with this name if it already exists
                ci_id: str | None = None
                ci_arn_val: str | None = None
                existing_cis = ci_boto.list_code_interpreters().get("codeInterpreterSummaries", [])
                for existing_ci in existing_cis:
                    if existing_ci.get("name") == sanitized_ci_name:
                        ci_id = existing_ci["codeInterpreterId"]
                        ci_arn_val = existing_ci["codeInterpreterArn"]
                        logger.info("Reusing existing CI resource %s for harness agent %s", ci_id, agent_id)
                        break
                if not ci_id:
                    ci_resp = ci_boto.create_code_interpreter(
                        name=sanitized_ci_name,
                        executionRoleArn=ci_config["execution_role_arn"],
                        networkConfiguration={"networkMode": ci_net_mode},
                    )
                    ci_id = ci_resp["codeInterpreterId"]
                    ci_arn_val = ci_resp["codeInterpreterArn"]
                    logger.info("Created CI resource %s for harness agent %s", ci_id, agent_id)
                ci_arn = ci_arn_val
                agent.code_interpreter_id = ci_id
                db.commit()
                try:
                    from app.services.observability import enable_code_interpreter_observability
                    ci_arn_parts = ci_arn.split(":")
                    ci_account_id = ci_arn_parts[4] if len(ci_arn_parts) >= 6 else account_id
                    enable_code_interpreter_observability(
                        ci_arn=ci_arn,
                        ci_id=ci_id,
                        account_id=ci_account_id,
                        region=ci_region,
                    )
                except Exception as obs_err:
                    logger.warning("Failed to enable CI observability for harness agent %s: %s", agent_id, obs_err)
            except Exception as ci_err:
                logger.error("Failed to create CI resource for harness agent %s: %s", agent_id, ci_err)
                agent.status = "FAILED"
                agent.deployment_status = "failed"
                db.commit()
                return

        # Add code_interpreter tool to harness if CI resource was created
        if ci_arn:
            harness_tools.append({
                "type": "agentcore_code_interpreter",
                "name": "code_interpreter",
                "config": {"agentCoreCodeInterpreter": {"codeInterpreterArn": ci_arn}},
            })

        agent.deployment_status = "deploying"
        db.commit()

        # Build all MCP tools (for invocation-time injection with auth headers)
        all_mcp_tools = [_build_harness_tool_for_mcp(s) for s in mcp_snapshots]
        all_mcp_tools.extend(extra_harness_tools)

        # Resolve memory: harness supports one memory resource.
        # Fetch strategies from AWS to build retrievalConfig (required by CreateHarness).
        memory_configs = []
        primary_memory_arn = None
        primary_memory_retrieval_config: dict[str, Any] | None = None
        for m in (memory_snapshots or []):
            try:
                import boto3 as _boto3
                mem_client = _boto3.client("bedrock-agentcore-control", region_name=region)
                mem_resp = mem_client.get_memory(memoryId=m["memory_id"])
                mem_obj = mem_resp.get("memory", {})
                mem_status = mem_obj.get("status")
                if mem_status not in (None, "DELETING", "FAILED"):
                    retrieval_config: dict[str, Any] = {}
                    for strategy in mem_obj.get("strategies", []):
                        sid = strategy.get("strategyId")
                        if sid and strategy.get("status") == "ACTIVE":
                            retrieval_config[sid] = {"topK": 10, "strategyId": sid}
                    memory_configs.append({"name": m["name"], "memory_id": m["memory_id"], "arn": m["arn"]})
                    if not primary_memory_arn:
                        primary_memory_arn = m["arn"]
                        primary_memory_retrieval_config = retrieval_config or None
                else:
                    logger.warning("Memory %s has status %s, skipping", m["memory_id"], mem_status)
            except Exception as mem_err:
                logger.warning("Memory %s not found in AWS, skipping: %s", m["memory_id"], mem_err)

        # Build config JSON — deploy_tools go to create_harness, all tools
        # are stored for invocation-time injection with auth headers
        config_json = json.dumps({
            "system_prompt": system_prompt,
            "model_id": model_id,
            "max_tokens": max_tokens,
            "harness_config": {
                "tools": all_mcp_tools,
                "deploy_tools": harness_tools,
                "max_iterations": max_iterations,
            },
            "integrations": {
                "mcp_servers": mcp_server_configs,
                "a2a_agents": [],
                "memory": {"enabled": len(memory_configs) > 0, "resources": memory_configs},
            },
        })

        # Store config entry
        db.add(ConfigEntry(
            agent_id=agent.id,
            key="AGENT_CONFIG_JSON",
            value=config_json,
            is_secret=False,
            source="env_var",
        ))
        db.commit()


        # Delete any existing harness with the same name left over from a prior failed deploy.
        try:
            import boto3 as _boto3
            _hc = _boto3.client("bedrock-agentcore-control", region_name=region)
            existing_harnesses = _hc.list_harnesses().get("harnesses", [])
            for _h in existing_harnesses:
                if _h.get("harnessName") == name:
                    logger.info("Deleting conflicting existing harness %s before create", _h["harnessId"])
                    _hc.delete_harness(harnessId=_h["harnessId"])
                    break
        except Exception as _pre_err:
            logger.warning("Pre-create harness conflict check failed: %s", _pre_err)

        response = create_harness_api(
            name=name,
            execution_role_arn=execution_role_arn,
            model_id=model_id,
            system_prompt=system_prompt,
            tools=harness_tools if harness_tools else None,
            max_iterations=max_iterations,
            max_tokens=max_tokens,
            authorizer_config=authorizer_config,
            network_mode=network_mode,
            vpc_subnet_ids=vpc_subnet_ids,
            vpc_security_group_ids=vpc_security_group_ids,
            idle_timeout=idle_timeout,
            max_lifetime=max_lifetime,
            memory_arn=primary_memory_arn,
            memory_retrieval_config=primary_memory_retrieval_config,
            tags=resolved_tags if resolved_tags else None,
            region=region,
        )

        harness_id = response.get("harnessId", "")
        harness_arn = response.get("arn") or response.get("harnessArn", "")

        agent.harness_id = harness_id
        agent.arn = harness_arn
        agent.runtime_id = harness_id
        harness_status = response.get("status", "CREATING")
        agent.status = harness_status
        agent.deployment_status = "READY" if harness_status == "READY" else "deployed"
        agent.deployed_at = datetime.utcnow()
        agent.last_refreshed_at = datetime.utcnow()
        agent.set_tags(resolved_tags)

        # Extract auto-provisioned runtime from environment
        env = response.get("environment", {}).get("agentCoreRuntimeEnvironment", {})
        runtime_arn = env.get("agentRuntimeArn", "")
        runtime_id = env.get("agentRuntimeId", "")
        if runtime_id:
            agent.runtime_id = runtime_id
            agent.log_group = derive_log_group(runtime_id, "DEFAULT") if runtime_id else None
        agent.set_available_qualifiers(["DEFAULT"])

        # Extract account from harness ARN
        try:
            arn_parts = harness_arn.split(":")
            if len(arn_parts) >= 5:
                agent.account_id = arn_parts[4]
        except Exception:
            pass

        # Enable USAGE_LOGS and APPLICATION_LOGS observability on the auto-provisioned runtime
        if runtime_arn and runtime_id and agent.account_id:
            try:
                from app.services.observability import enable_runtime_observability
                obs_result = enable_runtime_observability(
                    runtime_arn=runtime_arn,
                    runtime_id=runtime_id,
                    account_id=agent.account_id,
                    region=region,
                )
                logger.info("Enabled observability for harness agent %s: %s", agent_id, obs_result)
            except Exception as obs_err:
                logger.warning("Failed to enable observability for harness agent %s: %s", agent_id, obs_err)

        db.commit()
        logger.info("Harness deploy complete: agent=%s harness_id=%s", agent_id, harness_id)

    except Exception as e:
        logger.error("Failed to deploy harness for agent %s: %s", agent_id, e)
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                agent.deployment_status = "failed"
                agent.status = "FAILED"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _update_harness_background(
    agent_id: int,
    harness_id: str,
    name: str,
    execution_role_arn: str,
    model_id: str,
    system_prompt: str,
    mcp_snapshots: list[dict[str, Any]],
    extra_harness_tools: list[dict[str, Any]],
    max_iterations: int | None,
    max_tokens: int | None,
    authorizer_config: dict[str, Any] | None,
    network_mode: str,
    idle_timeout: int | None,
    max_lifetime: int | None,
    resolved_tags: dict[str, str],
    old_cp_names: set[str],
    region: str,
    account_id: str,
    memory_snapshots: list[dict[str, Any]] | None = None,
    vpc_subnet_ids: list[str] | None = None,
    vpc_security_group_ids: list[str] | None = None,
    ci_config: dict[str, Any] | None = None,
) -> None:
    """Background task that updates an existing harness via UpdateHarness API."""
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            logger.error("Background harness update: agent %s not found", agent_id)
            return

        # --- Step 1: Handle credential providers for OAuth2 MCP servers ---
        new_cp_names: set[str] = set()
        harness_tools: list[dict[str, Any]] = []
        mcp_server_configs: list[dict[str, Any]] = []

        for server in mcp_snapshots:
            cp_name: str | None = None
            if server["auth_type"] == "oauth2":
                cp_name = f"loom-{name}-mcp-{server['name']}"
                new_cp_names.add(cp_name)
                mcp_delegation = server.get("delegation_mode") or "m2m"
                mcp_obo_grant = server.get("obo_grant_type")
                if cp_name not in old_cp_names:
                    try:
                        from app.services.deployment import create_oauth2_credential_provider
                        create_oauth2_credential_provider(
                            name=cp_name,
                            client_id=server["oauth2_client_id"] or "",
                            client_secret=server["oauth2_client_secret"] or "",
                            auth_server_url=server["oauth2_well_known_url"] or "",
                            region=region,
                            tags=resolved_tags if resolved_tags else None,
                            delegation_mode=mcp_delegation,
                            obo_grant_type=mcp_obo_grant,
                        )
                        logger.info("Created credential provider '%s' for MCP server '%s'", cp_name, server["name"])
                    except Exception as e:
                        logger.error("Failed to create credential provider for MCP '%s': %s", server["name"], e)
                        agent.status = "FAILED"
                        agent.deployment_status = "credential_creation_failed"
                        db.commit()
                        return

            harness_tools.append(_build_harness_tool_for_mcp(server))

            mcp_entry: dict[str, Any] = {
                "name": server["name"],
                "endpoint_url": server["endpoint_url"],
                "auth_type": server["auth_type"],
            }
            if cp_name:
                harness_auth: dict[str, str] = {
                    "type": "oauth2",
                    "credential_provider_name": cp_name,
                    "delegation_mode": server.get("delegation_mode") or "m2m",
                }
                if server.get("obo_grant_type"):
                    harness_auth["obo_grant_type"] = server["obo_grant_type"]
                mcp_entry["auth"] = harness_auth
            mcp_entry["delegation_mode"] = server.get("delegation_mode") or "m2m"
            if server.get("supports_elicitation"):
                mcp_entry["supports_elicitation"] = "true"
            mcp_server_configs.append(mcp_entry)

        harness_tools.extend(extra_harness_tools)

        # Delete old credential providers no longer needed
        removed_cps = old_cp_names - new_cp_names
        for cp_name in removed_cps:
            try:
                from app.services.deployment import delete_oauth2_credential_provider
                delete_oauth2_credential_provider(cp_name, region)
                logger.info("Deleted old credential provider '%s'", cp_name)
            except Exception as e:
                logger.warning("Failed to delete old credential provider '%s': %s", cp_name, e)

        # --- Step 2: Update harness via API ---
        agent.deployment_status = "updating"
        db.commit()

        all_mcp_tools = [_build_harness_tool_for_mcp(s) for s in mcp_snapshots]
        all_mcp_tools.extend(extra_harness_tools)

        memory_configs = []
        primary_memory_arn = None
        primary_memory_retrieval_config: dict[str, Any] | None = None
        for m in (memory_snapshots or []):
            try:
                import boto3 as _boto3
                mem_client = _boto3.client("bedrock-agentcore-control", region_name=region)
                mem_resp = mem_client.get_memory(memoryId=m["memory_id"])
                mem_obj = mem_resp.get("memory", {})
                mem_status = mem_obj.get("status")
                if mem_status not in (None, "DELETING", "FAILED"):
                    retrieval_config: dict[str, Any] = {}
                    for strategy in mem_obj.get("strategies", []):
                        sid = strategy.get("strategyId")
                        if sid and strategy.get("status") == "ACTIVE":
                            retrieval_config[sid] = {"topK": 10, "strategyId": sid}
                    memory_configs.append({"name": m["name"], "memory_id": m["memory_id"], "arn": m["arn"]})
                    if not primary_memory_arn:
                        primary_memory_arn = m["arn"]
                        primary_memory_retrieval_config = retrieval_config or None
                else:
                    logger.warning("Memory %s has status %s, skipping", m["memory_id"], mem_status)
            except Exception as mem_err:
                logger.warning("Memory %s not found in AWS, skipping: %s", m["memory_id"], mem_err)

        # Handle Code Interpreter: reuse existing resource or create new one
        update_ci_arn: str | None = None
        if ci_config and ci_config.get("execution_role_arn"):
            existing_ci_id = ci_config.get("existing_id")
            if existing_ci_id:
                # Fetch ARN from existing resource
                try:
                    import boto3 as _boto3
                    ci_region_upd = ci_config.get("region") or region
                    ci_boto_upd = _boto3.client("bedrock-agentcore-control", region_name=ci_region_upd)
                    ci_info = ci_boto_upd.get_code_interpreter(codeInterpreterId=existing_ci_id)
                    update_ci_arn = ci_info.get("codeInterpreterArn")
                except Exception as ci_get_err:
                    logger.warning("Could not fetch existing CI ARN for harness update %s: %s", agent_id, ci_get_err)
            if not update_ci_arn:
                # Create a new CI resource
                try:
                    import boto3 as _boto3
                    ci_region_upd = ci_config.get("region") or region
                    base_name_upd = re.sub(r"_?code_interpreter$", "", name).strip("_")
                    raw_ci_name_upd = f"loom_ci_{base_name_upd}"
                    san_ci_name_upd = re.sub(r"[^a-zA-Z0-9_]", "_", raw_ci_name_upd)[:48]
                    ci_net_upd = ci_config.get("network_mode") or "SANDBOX"
                    ci_boto_upd = _boto3.client("bedrock-agentcore-control", region_name=ci_region_upd)
                    ci_resp_upd = ci_boto_upd.create_code_interpreter(
                        name=san_ci_name_upd,
                        executionRoleArn=ci_config["execution_role_arn"],
                        networkConfiguration={"networkMode": ci_net_upd},
                    )
                    update_ci_arn = ci_resp_upd["codeInterpreterArn"]
                    agent.code_interpreter_id = ci_resp_upd["codeInterpreterId"]
                    db.commit()
                    logger.info("Created new CI resource %s for harness update %s", agent.code_interpreter_id, agent_id)
                except Exception as ci_create_err:
                    logger.warning("Failed to create CI resource for harness update %s: %s", agent_id, ci_create_err)

        if update_ci_arn:
            harness_tools.append({
                "type": "agentcore_code_interpreter",
                "name": "code_interpreter",
                "config": {"agentCoreCodeInterpreter": {"codeInterpreterArn": update_ci_arn}},
            })

        config_json = json.dumps({
            "system_prompt": system_prompt,
            "model_id": model_id,
            "max_tokens": max_tokens,
            "harness_config": {
                "tools": all_mcp_tools,
                "deploy_tools": harness_tools,
                "max_iterations": max_iterations,
            },
            "integrations": {
                "mcp_servers": mcp_server_configs,
                "a2a_agents": [],
                "memory": {"enabled": len(memory_configs) > 0, "resources": memory_configs},
            },
        })

        db.add(ConfigEntry(
            agent_id=agent.id,
            key="AGENT_CONFIG_JSON",
            value=config_json,
            is_secret=False,
            source="env_var",
        ))
        db.commit()

        response = update_harness_api(
            harness_id=harness_id,
            execution_role_arn=execution_role_arn,
            model_id=model_id,
            system_prompt=system_prompt,
            tools=harness_tools if harness_tools else None,
            max_iterations=max_iterations,
            max_tokens=max_tokens,
            authorizer_config=authorizer_config,
            network_mode=network_mode,
            vpc_subnet_ids=vpc_subnet_ids,
            vpc_security_group_ids=vpc_security_group_ids,
            idle_timeout=idle_timeout,
            max_lifetime=max_lifetime,
            memory_arn=primary_memory_arn,
            memory_retrieval_config=primary_memory_retrieval_config,
            region=region,
        )

        harness_status = response.get("status", "UPDATING")
        agent.status = "READY" if harness_status == "READY" else harness_status
        agent.deployment_status = "READY" if harness_status == "READY" else "deployed"
        agent.deployed_at = datetime.utcnow()
        agent.last_refreshed_at = datetime.utcnow()
        db.commit()

        logger.info("Harness update complete: agent=%s harness_id=%s", agent_id, harness_id)

    except Exception as e:
        logger.error("Failed to update harness for agent %s: %s", agent_id, e)
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                agent.deployment_status = "failed"
                agent.status = "FAILED"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _is_resource_not_found(e: Exception) -> bool:
    """Return True if an AWS error indicates the resource no longer exists."""
    from botocore.exceptions import ClientError
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        return code in ("ResourceNotFoundException", "NotFoundException")
    return False


def _is_permanent_error(e: Exception) -> bool:
    """Return True if an AWS error is permanent and polling should stop."""
    from botocore.exceptions import ClientError
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        return code in ("AccessDeniedException", "UnauthorizedException")
    return False


def _cleanup_role(role_arn: str) -> None:
    """Best-effort cleanup of an IAM role on deploy failure."""
    try:
        role_name = role_arn.split("/")[-1]
        delete_execution_role(role_name)
    except Exception as e:
        logger.warning("Failed to clean up orphaned IAM role %s: %s", role_arn, e)


def _delete_code_interpreter(ci_id: str, region: str) -> None:
    """Best-effort deletion of a custom Code Interpreter resource.

    If active sessions are present, terminates them and retries once.
    """
    import boto3
    client = boto3.client("bedrock-agentcore-control", region_name=region)
    data_client = boto3.client("bedrock-agentcore", region_name=region)

    def _attempt_delete() -> bool:
        try:
            client.delete_code_interpreter(codeInterpreterId=ci_id)
            logger.info("Deleted CI resource %s", ci_id)
            return True
        except client.exceptions.ConflictException as e:
            raise e
        except Exception as e:
            logger.warning("Failed to delete CI resource %s: %s", ci_id, e)
            return False

    try:
        _attempt_delete()
    except Exception as e:
        err_msg = str(e)
        if "active sessions" in err_msg.lower() or "ConflictException" in type(e).__name__:
            logger.info("CI resource %s has active sessions; terminating before retry", ci_id)
            try:
                paginator_resp = data_client.list_code_interpreter_sessions(codeInterpreterIdentifier=ci_id)
                sessions = paginator_resp.get("items", [])
                for s in sessions:
                    sid = s.get("sessionId")
                    if sid:
                        try:
                            data_client.stop_code_interpreter_session(
                                codeInterpreterIdentifier=ci_id,
                                sessionId=sid,
                            )
                            logger.info("Stopped CI session %s", sid)
                        except Exception as stop_err:
                            logger.warning("Failed to stop CI session %s: %s", sid, stop_err)
            except Exception as list_err:
                logger.warning("Failed to list CI sessions for %s: %s", ci_id, list_err)
            # Retry delete after terminating sessions
            try:
                client.delete_code_interpreter(codeInterpreterId=ci_id)
                logger.info("Deleted CI resource %s after session cleanup", ci_id)
            except Exception as retry_err:
                logger.warning("Failed to delete CI resource %s after session cleanup: %s", ci_id, retry_err)
        else:
            logger.warning("Failed to delete CI resource %s: %s", ci_id, e)


@router.get("", response_model=list[AgentResponse])
def list_agents(
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> list[AgentResponse]:
    """List all registered agents."""
    agents = db.query(Agent).order_by(Agent.registered_at.desc()).all()

    # Tag-based filtering:
    # - Admins (t-admin): See ALL resources including untagged
    # - Users (t-user): See only resources tagged with their groups (g-users-* → strip prefix)
    if "t-admin" not in user.groups:
        # User view: filter by group tags (strip "g-users-" prefix)
        user_groups = [g for g in user.groups if g.startswith("g-users-")]
        allowed_tags = [g.replace("g-users-", "", 1) for g in user_groups]
        agents = [a for a in agents if a.get_tags().get("loom:group") in allowed_tags]

    # Registry visibility: when registry is enabled, t-user only sees APPROVED agents
    if "t-admin" not in user.groups:
        from app.services.registry import get_registry_client
        reg_client = get_registry_client()
        if reg_client.registry_id:
            agents = [a for a in agents if a.registry_status == "APPROVED"]
        else:
            agents = [a for a in agents if not a.registry_status or a.registry_status == "APPROVED"]

    return [_agent_response(agent, db) for agent in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: int, user: UserInfo = Depends(require_scopes("agent:read")), db: Session = Depends(get_db)) -> AgentResponse:
    """Get metadata for a specific registered agent."""
    agent = get_agent_or_404(agent_id, db)
    return _agent_response(agent, db)


@router.get("/{agent_id}/status", response_model=AgentResponse)
def get_agent_status(agent_id: int, user: UserInfo = Depends(require_scopes("agent:read")), db: Session = Depends(get_db)) -> AgentResponse:
    """Poll AWS for current runtime and endpoint status, update local DB.

    If the runtime is READY and no endpoint exists yet, creates one automatically.
    During local build phases (before create_runtime is called), returns current
    DB state without making AWS API calls.
    """
    agent = get_agent_or_404(agent_id, db)

    # Local build phases — runtime doesn't exist in AWS yet, just return DB state
    _local_phases = {"initializing", "creating_credentials", "creating_role", "building_artifact", "creating_ci_resource", "deploying"}
    if agent.deployment_status in _local_phases:
        return _agent_response(agent, db)

    # Harness agents: poll harness status via get_harness
    if agent.harness_id and agent.source == "harness":
        try:
            harness = get_harness_api(agent.harness_id, agent.region)
            agent.status = harness.get("status", agent.status)
            agent.arn = harness.get("arn") or harness.get("harnessArn") or agent.arn
            agent.last_refreshed_at = datetime.utcnow()

            if agent.status == "READY":
                agent.deployment_status = "READY"
                agent.endpoint_name = "DEFAULT"
                agent.endpoint_status = "READY"
                env = harness.get("environment", {}).get("agentCoreRuntimeEnvironment", {})
                runtime_arn = env.get("agentRuntimeArn", "")
                runtime_id = env.get("agentRuntimeId", "")
                if runtime_id and runtime_id != agent.runtime_id:
                    agent.runtime_id = runtime_id
                    agent.log_group = derive_log_group(runtime_id, "DEFAULT")
                    if runtime_arn and agent.account_id:
                        try:
                            from app.services.observability import enable_runtime_observability
                            enable_runtime_observability(
                                runtime_arn=runtime_arn,
                                runtime_id=runtime_id,
                                account_id=agent.account_id,
                                region=agent.region,
                            )
                            logger.info("Enabled observability for harness agent %s during status poll", agent.id)
                        except Exception as obs_err:
                            logger.warning("Failed to enable observability for harness agent %s: %s", agent.id, obs_err)
        except Exception as e:
            logger.warning("Failed to poll harness status for %s: %s", agent.harness_id, e)
            if agent.status == "DELETING" and _is_resource_not_found(e):
                db.delete(agent)
                db.flush()
                db.commit()
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent deleted")
            if _is_permanent_error(e):
                agent.status = "FAILED"
                agent.deployment_status = "failed"
                db.commit()
                db.refresh(agent)
                return _agent_response(agent, db)

        # Auto-register in Agent Registry once harness is fully READY
        if agent.deployment_status == "READY" and not agent.registry_record_id:
            try:
                from app.services.registry import get_registry_client
                reg_client = get_registry_client()
                if reg_client.registry_id:
                    descriptors = reg_client.build_agent_descriptors(agent)
                    reg_result = reg_client.create_record(
                        name=agent.name or agent.harness_id,
                        descriptor_type="A2A",
                        descriptors=descriptors,
                        record_version="1",
                        description=agent.description,
                    )
                    reg_record_id = reg_result.get("recordId", "")
                    if reg_record_id:
                        rec = reg_client.wait_for_record(reg_record_id)
                        agent.registry_record_id = reg_record_id
                        agent.registry_status = rec.get("status", "DRAFT")
                        logger.info("Auto-registered harness agent %s in registry: %s", agent.id, reg_record_id)
            except Exception as reg_err:
                logger.warning("Failed to auto-register harness agent %s in registry: %s", agent.id, reg_err)

        db.commit()
        db.refresh(agent)
        return _agent_response(agent, db)

    if agent.runtime_id and agent.source == "deploy":
        # Check runtime status
        try:
            rt = get_runtime(agent.runtime_id, agent.region)
            agent.status = rt.get("status", agent.status)
            agent.status_reason = rt.get("failureReason")
            agent.arn = rt.get("agentRuntimeArn", agent.arn)
            agent.last_refreshed_at = datetime.utcnow()
        except Exception as e:
            logger.warning("Failed to poll runtime status for %s: %s", agent.runtime_id, e)
            # If the agent was DELETING and the runtime is confirmed gone, purge from DB
            if agent.status == "DELETING" and _is_resource_not_found(e):
                logger.info("Runtime %s no longer exists; purging agent %s", agent.runtime_id, agent.id)
                db.delete(agent)
                db.flush()
                db.commit()
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent deleted")
            # Stop polling on permanent errors (auth, not found)
            if _is_permanent_error(e):
                agent.status = "FAILED"
                agent.deployment_status = "failed"
                db.commit()
                db.refresh(agent)
                return _agent_response(agent, db)

        # Use the DEFAULT endpoint that is auto-created with the runtime
        if agent.status == "READY" and not agent.endpoint_name:
            agent.endpoint_name = "DEFAULT"

        # If endpoint exists, check its status
        if agent.endpoint_name:
            try:
                ep = get_runtime_endpoint(agent.runtime_id, agent.endpoint_name, agent.region)
                agent.endpoint_status = ep.get("status", agent.endpoint_status)
                agent.endpoint_arn = ep.get("agentRuntimeEndpointArn", agent.endpoint_arn)
                if agent.endpoint_status == "READY":
                    agent.deployment_status = "READY"
            except Exception as e:
                logger.warning("Failed to poll endpoint status for %s: %s", agent.endpoint_name, e)

        # Auto-register in Agent Registry once deployment is fully READY
        if agent.deployment_status == "READY" and not agent.registry_record_id:
            try:
                from app.services.registry import get_registry_client
                reg_client = get_registry_client()
                if reg_client.registry_id:
                    descriptors = reg_client.build_agent_descriptors(agent)
                    reg_result = reg_client.create_record(
                        name=agent.name or agent.runtime_id,
                        descriptor_type="A2A",
                        descriptors=descriptors,
                        record_version="1",
                        description=agent.description,
                    )
                    reg_record_id = reg_result.get("recordId", "")
                    if reg_record_id:
                        rec = reg_client.wait_for_record(reg_record_id)
                        agent.registry_record_id = reg_record_id
                        agent.registry_status = rec.get("status", "DRAFT")
                        logger.info("Auto-registered agent %s in registry: %s", agent.id, reg_record_id)
            except Exception as reg_err:
                logger.warning("Failed to auto-register agent %s in registry: %s", agent.id, reg_err)

    ci_status: str | None = None
    if agent.code_interpreter_id and agent.status != "DELETING":
        try:
            import boto3
            ci_region = agent.region
            boto_client = boto3.client("bedrock-agentcore-control", region_name=ci_region)
            ci_resp = boto_client.get_code_interpreter(codeInterpreterId=agent.code_interpreter_id)
            ci_status = ci_resp.get("status")
        except Exception as ci_poll_err:
            if _is_resource_not_found(ci_poll_err):
                logger.debug("CI resource %s not found during poll (already deleted)", agent.code_interpreter_id)
            else:
                logger.warning("Failed to poll CI status for agent %s: %s", agent.id, ci_poll_err)

    db.commit()
    db.refresh(agent)

    response = _agent_response(agent, db)
    if ci_status is not None:
        response.code_interpreter_status = ci_status
    return response


@router.delete("/{agent_id}", response_model=AgentResponse)
def delete_agent(
    agent_id: int,
    cleanup_aws: bool = False,
    background_tasks: BackgroundTasks = None,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> AgentResponse:
    """Remove an agent from the local registry.

    Args:
        cleanup_aws: If True, also delete the runtime, endpoint, and IAM role from AWS.
    """
    agent = get_agent_or_404(agent_id, db)

    # Enforce demo-admin group restriction
    if "g-admins-demo" in user.groups and "g-admins-super" not in user.groups:
        agent_group = agent.get_tags().get("loom:group", "")
        if agent_group != "demo":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo admins can only delete agents in the 'demo' group"
            )

    # Extract credential provider names from agent config for cleanup
    config_map = {e.key: e.value for e in agent.config_entries}
    cp_names: list[str] = []
    config_json_str = config_map.get("AGENT_CONFIG_JSON")
    if config_json_str:
        try:
            agent_config = json.loads(config_json_str)
            integrations = agent_config.get("integrations", {})
            for mcp in integrations.get("mcp_servers", []):
                cp_name = (mcp.get("auth") or {}).get("credential_provider_name")
                if cp_name:
                    cp_names.append(cp_name)
            for a2a in integrations.get("a2a_agents", []):
                cp_name = (a2a.get("auth") or {}).get("credential_provider_name")
                if cp_name:
                    cp_names.append(cp_name)
        except (json.JSONDecodeError, TypeError):
            pass

    # For local-only deletion (no AWS cleanup or no runtime)
    if not cleanup_aws or not agent.runtime_id:
        # Clean up Cognito client secret from Secrets Manager
        secret_arn = config_map.get("COGNITO_CLIENT_SECRET_ARN")
        if secret_arn:
            delete_secret(secret_arn, agent.region)

        result = _agent_response(agent, db)
        # Delete invocations before sessions to avoid FK constraint violations
        # when PRAGMA foreign_keys=ON (SQLite) or equivalent DB-level enforcement.
        session_ids = [
            s.session_id for s in
            db.query(InvocationSession.session_id).filter(InvocationSession.agent_id == agent.id).all()
        ]
        if session_ids:
            db.query(Invocation).filter(Invocation.session_id.in_(session_ids)).delete(synchronize_session="fetch")
        db.query(InvocationSession).filter(InvocationSession.agent_id == agent.id).delete()
        db.delete(agent)
        db.flush()
        db.commit()
        return result

    # Delete registry record if one exists
    if agent.registry_record_id:
        try:
            from app.services.registry import get_registry_client
            reg_client = get_registry_client()
            reg_client.delete_record(agent.registry_record_id)
            logger.info("Deleted registry record %s for agent %s", agent.registry_record_id, agent.id)
            agent.registry_record_id = None
            agent.registry_status = None
        except Exception as reg_err:
            logger.warning("Failed to delete registry record for agent %s: %s", agent.id, reg_err)

    # Capture values needed by the background task before the request session closes
    _agent_id = agent.id
    _runtime_id = agent.runtime_id
    _endpoint_name = agent.endpoint_name
    _region = agent.region
    _secret_arn = config_map.get("COGNITO_CLIENT_SECRET_ARN")
    _ci_id = agent.code_interpreter_id
    _ci_region = None
    if _ci_id:
        try:
            agent_cfg = json.loads(config_map.get("AGENT_CONFIG_JSON") or "{}")
            _ci_region = (agent_cfg.get("integrations", {}).get("code_interpreter") or {}).get("region") or _region
        except (json.JSONDecodeError, TypeError):
            _ci_region = _region

    # Initiate async deletion in AWS
    _harness_id = agent.harness_id

    if agent.source == "harness" and _harness_id:
        try:
            delete_harness_api(_harness_id, _region)
        except Exception as e:
            logger.warning("Failed to delete harness %s: %s", _harness_id, e)
        if _runtime_id:
            try:
                from app.services.observability import cleanup_runtime_observability
                cleanup_runtime_observability(_runtime_id, _region)
            except Exception as obs_err:
                logger.warning("Failed to cleanup observability for harness %s: %s", _harness_id, obs_err)
    else:
        # Skip DEFAULT endpoint — AWS removes it automatically when the runtime is deleted
        if _endpoint_name and _endpoint_name != "DEFAULT":
            try:
                delete_runtime_endpoint(_runtime_id, _endpoint_name, _region)
            except Exception as e:
                logger.warning("Failed to delete endpoint %s: %s", _endpoint_name, e)

        try:
            delete_runtime(_runtime_id, _region)
        except Exception as e:
            logger.warning("Failed to delete runtime %s: %s", _runtime_id, e)

    # Delete custom Code Interpreter resource if one was created
    if _ci_id and _ci_region:
        _delete_code_interpreter(_ci_id, _ci_region)
    elif agent.source == "harness" and agent.name:
        # Fallback: no code_interpreter_id stored, but a CI may exist from a failed deploy.
        # Reconstruct the expected name and look it up.
        try:
            import boto3 as _boto3
            _fallback_region = _region
            base_name = re.sub(r"_?code_interpreter$", "", agent.name).strip("_")
            expected_ci_name = re.sub(r"[^a-zA-Z0-9_]", "_", f"loom_ci_{base_name}")[:48]
            ci_client = _boto3.client("bedrock-agentcore-control", region_name=_fallback_region)
            summaries = ci_client.list_code_interpreters().get("codeInterpreterSummaries", [])
            for s in summaries:
                if s.get("name") == expected_ci_name:
                    _delete_code_interpreter(s["codeInterpreterId"], _fallback_region)
                    break
        except Exception as ci_scan_err:
            logger.warning("Failed to scan/delete orphaned CI for harness %s: %s", agent.name, ci_scan_err)

    # Clean up credential providers
    for cp_name in cp_names:
        try:
            delete_credential_provider(cp_name, _region)
            logger.info("Deleted credential provider '%s'", cp_name)
        except Exception as e:
            logger.warning("Failed to delete credential provider '%s': %s", cp_name, e)

    # Clean up Cognito client secret from Secrets Manager
    if _secret_arn:
        delete_secret(_secret_arn, _region)

    # Delete sessions/invocations immediately so they don't appear if a new
    # agent reuses the same ID or the DELETING agent is still visible.
    session_ids = [
        s.session_id for s in
        db.query(InvocationSession.session_id).filter(InvocationSession.agent_id == agent.id).all()
    ]
    if session_ids:
        db.query(Invocation).filter(Invocation.session_id.in_(session_ids)).delete(synchronize_session="fetch")
    db.query(InvocationSession).filter(InvocationSession.agent_id == agent.id).delete()

    # Mark as DELETING so frontend can poll for completion
    agent.status = "DELETING"
    agent.deployment_status = "removing"
    db.flush()
    db.commit()
    db.refresh(agent)
    result = _agent_response(agent, db)

    # Schedule background task to wait for AWS deletion and then purge the DB record
    if background_tasks is not None:
        background_tasks.add_task(
            _delete_agent_background,
            _agent_id,
            _runtime_id,
            _region,
        )

    return result


def _delete_agent_background(
    agent_id: int,
    runtime_id: str,
    region: str,
) -> None:
    """Background task: poll until the runtime is gone, then purge the DB record."""
    max_attempts = 30
    poll_interval = 5

    for attempt in range(max_attempts):
        time.sleep(poll_interval)
        try:
            rt = get_runtime(runtime_id, region)
            rt_status = rt.get("status", "")
            logger.info("Delete poll %d/%d for runtime %s: status=%s", attempt + 1, max_attempts, runtime_id, rt_status)
            if rt_status == "FAILED":
                logger.warning("Runtime %s entered FAILED state during deletion", runtime_id)
                break
        except Exception:
            # Runtime no longer exists — deletion complete
            logger.info("Runtime %s no longer exists; deletion confirmed", runtime_id)
            break
    else:
        logger.warning("Runtime %s still exists after %d poll attempts; purging DB record anyway", runtime_id, max_attempts)

    # Purge the agent record and its sessions/invocations from the database.
    # Explicitly delete sessions first to guarantee cleanup even if the ORM
    # cascade is bypassed (e.g. stale objects, ID reuse in SQLite).
    db = SessionLocal()
    try:
        session_ids = [
            s.session_id for s in
            db.query(InvocationSession.session_id).filter(InvocationSession.agent_id == agent_id).all()
        ]
        if session_ids:
            db.query(Invocation).filter(Invocation.session_id.in_(session_ids)).delete(synchronize_session="fetch")
        db.query(InvocationSession).filter(InvocationSession.agent_id == agent_id).delete()
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if agent and agent.runtime_id == runtime_id:
            db.delete(agent)
            db.flush()
            db.commit()
            logger.info("Purged agent %d and its sessions from database", agent_id)
        elif agent:
            db.commit()
            logger.info("Agent %d has a different runtime_id (%s vs %s); skipping purge (likely recreated)", agent_id, agent.runtime_id, runtime_id)
        else:
            db.commit()
            logger.info("Agent %d already removed from database; cleaned up orphan sessions", agent_id)
    except Exception as e:
        db.rollback()
        logger.warning("Failed to purge agent %d from database: %s", agent_id, e)
    finally:
        db.close()


@router.delete("/{agent_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_agent(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> None:
    """Remove an agent and its sessions/invocations from the local database (no AWS call)."""
    agent = get_agent_or_404(agent_id, db)
    # Delete invocations before sessions to respect FK constraints
    session_ids = [
        s.session_id for s in
        db.query(InvocationSession.session_id).filter(InvocationSession.agent_id == agent_id).all()
    ]
    if session_ids:
        db.query(Invocation).filter(Invocation.session_id.in_(session_ids)).delete(synchronize_session="fetch")
    db.query(InvocationSession).filter(InvocationSession.agent_id == agent_id).delete()
    db.delete(agent)
    db.commit()


@router.post("/{agent_id}/refresh", response_model=AgentResponse)
def refresh_agent(agent_id: int, user: UserInfo = Depends(require_scopes("agent:write")), db: Session = Depends(get_db)) -> AgentResponse:
    """Re-fetch metadata from AgentCore and update the local record."""
    agent = get_agent_or_404(agent_id, db)

    # Harness agents: refresh via get_harness
    if agent.harness_id and agent.source == "harness":
        try:
            harness = get_harness_api(agent.harness_id, agent.region)
            agent.status = harness.get("status", agent.status)
            agent.arn = harness.get("arn") or harness.get("harnessArn") or agent.arn
            agent.last_refreshed_at = datetime.utcnow()

            if agent.status == "READY":
                agent.deployment_status = "READY"
                agent.endpoint_name = "DEFAULT"
                agent.endpoint_status = "READY"
                env = harness.get("environment", {}).get("agentCoreRuntimeEnvironment", {})
                runtime_arn = env.get("agentRuntimeArn", "")
                runtime_id = env.get("agentRuntimeId", "")
                if runtime_id and runtime_id != agent.runtime_id:
                    agent.runtime_id = runtime_id
                    agent.log_group = derive_log_group(runtime_id, "DEFAULT")
                    if runtime_arn and agent.account_id:
                        try:
                            from app.services.observability import enable_runtime_observability
                            enable_runtime_observability(
                                runtime_arn=runtime_arn,
                                runtime_id=runtime_id,
                                account_id=agent.account_id,
                                region=agent.region,
                            )
                            logger.info("Enabled observability for harness agent %s during refresh", agent.id)
                        except Exception as obs_err:
                            logger.warning("Failed to enable observability for harness agent %s: %s", agent.id, obs_err)

            db.commit()
            db.refresh(agent)
            return _agent_response(agent, db)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to describe harness: {str(e)}"
            )

    try:
        metadata = describe_runtime(agent.arn, agent.region)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to describe runtime: {str(e)}"
        )

    try:
        qualifiers = list_runtime_endpoints(agent.runtime_id, agent.region)
    except Exception:
        qualifiers = agent.get_available_qualifiers()

    agent.name = metadata.get("agentRuntimeName")
    agent.status = metadata.get("status")
    agent.status_reason = metadata.get("failureReason")
    protocol_config = metadata.get("protocolConfiguration", {})
    agent.protocol = protocol_config.get("serverProtocol", agent.protocol or "HTTP")
    network_config = metadata.get("networkConfiguration", {})
    agent.network_mode = network_config.get("networkMode", agent.network_mode or "PUBLIC")
    if agent.network_mode == "VPC":
        agent.set_vpc_subnet_ids(network_config.get("vpcSubnetIds") or agent.get_vpc_subnet_ids() or None)
        agent.set_vpc_security_group_ids(network_config.get("vpcSecurityGroupIds") or agent.get_vpc_security_group_ids() or None)
    if not agent.account_id:
        try:
            _, arn_account_id, _ = parse_arn(agent.arn)
            agent.account_id = arn_account_id
        except ValueError:
            pass
    agent.set_available_qualifiers(qualifiers)
    agent.set_raw_metadata(metadata)
    agent.last_refreshed_at = datetime.utcnow()

    # Update authorizer config from runtime metadata (for imported agents)
    if not agent.get_authorizer_config():
        authorizer_metadata = metadata.get("authorizerConfiguration", {})
        jwt_authorizer = authorizer_metadata.get("customJWTAuthorizer", {})
        if jwt_authorizer:
            discovery_url = jwt_authorizer.get("discoveryUrl", "")
            auth_type = "cognito" if "cognito-idp" in discovery_url else "other"
            agent.set_authorizer_config({
                "type": auth_type,
                "discovery_url": discovery_url,
                "allowed_audience": jwt_authorizer.get("allowedAudience", []),
                "allowed_clients": jwt_authorizer.get("allowedClients", []),
                "allowed_scopes": jwt_authorizer.get("allowedScopes", []),
            })

    db.commit()
    db.refresh(agent)

    return _agent_response(agent, db)


@router.post("/{agent_id}/redeploy", response_model=AgentResponse)
def redeploy_agent_endpoint(agent_id: int, user: UserInfo = Depends(require_scopes("agent:write")), db: Session = Depends(get_db)) -> AgentResponse:
    """Redeploy an agent with its current code and config."""
    agent = get_agent_or_404(agent_id, db)

    if agent.source != "deploy":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only deployed agents can be redeployed"
        )

    if not agent.runtime_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent is missing runtime_id"
        )

    config_entries = db.query(ConfigEntry).filter(ConfigEntry.agent_id == agent_id).all()
    env_vars = {entry.key: entry.value for entry in config_entries if entry.value is not None}

    agent.deployment_status = "deploying"
    db.commit()

    try:
        response = update_runtime(
            runtime_id=agent.runtime_id,
            env_vars=env_vars if env_vars else None,
            region=agent.region,
        )
        agent.deployment_status = "deployed"
        agent.status = response.get("status", "ACTIVE")
        agent.deployed_at = datetime.utcnow()
        agent.last_refreshed_at = datetime.utcnow()
        db.commit()
        db.refresh(agent)
    except Exception as e:
        agent.deployment_status = "failed"
        db.commit()
        logger.error("Failed to redeploy agent %s: %s", agent.id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to redeploy agent: {str(e)}"
        )

    return _agent_response(agent, db)


@router.put("/{agent_id}/redeploy-deploy", response_model=AgentResponse)
def redeploy_deploy_agent(
    agent_id: int,
    request: AgentCreateRequest,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> AgentResponse:
    """Update and redeploy a deploy-type agent with new configuration.

    Rebuilds the artifact and calls update_agent_runtime in-place so the
    existing runtime ID and ARN are preserved.
    """
    agent = get_agent_or_404(agent_id, db)

    if agent.source != "deploy":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only deploy-type agents can be updated via this endpoint",
        )

    if not agent.runtime_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent has no runtime_id — cannot update. Delete and redeploy instead.",
        )

    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    account_id = os.getenv("AWS_ACCOUNT_ID", "")

    # Collect old credential provider names before wiping config entries
    old_config_entry = db.query(ConfigEntry).filter(
        ConfigEntry.agent_id == agent_id, ConfigEntry.key == "AGENT_CONFIG_JSON"
    ).first()
    old_cp_names: set[str] = set()
    if old_config_entry:
        try:
            old_config = json.loads(old_config_entry.value)
            for srv in old_config.get("integrations", {}).get("mcp_servers", []):
                cp_name = (srv.get("auth", {}) or {}).get("credential_provider_name")
                if cp_name:
                    old_cp_names.add(cp_name)
            for a2a in old_config.get("integrations", {}).get("a2a_agents", []):
                cp_name = (a2a.get("auth", {}) or {}).get("credential_provider_name")
                if cp_name:
                    old_cp_names.add(cp_name)
        except (json.JSONDecodeError, TypeError):
            pass

    # Validate and snapshot MCP servers
    mcp_records: list[McpServer] = []
    if request.mcp_servers:
        mcp_records = db.query(McpServer).filter(McpServer.id.in_(request.mcp_servers)).all()
        found_ids = {s.id for s in mcp_records}
        missing = set(request.mcp_servers) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"MCP server IDs not found: {sorted(missing)}",
            )

    mcp_snapshots = [
        {
            "name": s.name,
            "endpoint_url": s.endpoint_url,
            "transport_type": s.transport_type,
            "auth_type": s.auth_type,
            "oauth2_well_known_url": s.oauth2_well_known_url,
            "oauth2_client_id": s.oauth2_client_id,
            "oauth2_client_secret": s.oauth2_client_secret,
            "oauth2_scopes": s.oauth2_scopes,
            "delegation_mode": (s.delegation_mode or "m2m"),
            "obo_grant_type": s.obo_grant_type,
            "oauth2_audience": s.oauth2_audience,
            "api_key_header_name": s.api_key_header_name,
            "supports_elicitation": s.supports_elicitation == "true",
        }
        for s in mcp_records
    ]

    # Validate and snapshot A2A agents
    a2a_records: list[A2aAgentModel] = []
    if request.a2a_agents:
        a2a_records = db.query(A2aAgentModel).filter(A2aAgentModel.id.in_(request.a2a_agents)).all()
        found_ids = {a.id for a in a2a_records}
        missing = set(request.a2a_agents) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A2A agent IDs not found: {sorted(missing)}",
            )

    a2a_snapshots = [
        {
            "name": a.name,
            "base_url": a.base_url,
            "auth_type": a.auth_type,
            "oauth2_well_known_url": a.oauth2_well_known_url,
            "oauth2_client_id": a.oauth2_client_id,
            "oauth2_client_secret": a.oauth2_client_secret,
            "oauth2_scopes": a.oauth2_scopes,
            "delegation_mode": (a.delegation_mode or "m2m"),
            "obo_grant_type": a.obo_grant_type,
        }
        for a in a2a_records
    ]

    # Validate and snapshot memory
    memory_records: list[Memory] = []
    if request.memory_ids:
        memory_records = db.query(Memory).filter(Memory.id.in_(request.memory_ids)).all()
        found_ids = {m.id for m in memory_records}
        missing = set(request.memory_ids) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Memory IDs not found: {sorted(missing)}",
            )

    memory_snapshots = [
        {"name": m.name, "memory_id": m.memory_id, "arn": m.arn}
        for m in memory_records
    ]

    resolved_tags, tag_policy_dicts = _resolve_tags(db, request.tags)
    system_prompt = _build_system_prompt(request)
    model_max_tokens = next(
        (m["max_tokens"] for m in SUPPORTED_MODELS if m["model_id"] == request.model_id),
        4096,
    )

    agent.status = "UPDATING"
    agent.deployment_status = "updating"
    db.commit()
    db.refresh(agent)

    background_tasks.add_task(
        _update_deploy_agent_background,
        agent_id=agent_id,
        request=request,
        mcp_snapshots=mcp_snapshots,
        a2a_snapshots=a2a_snapshots,
        memory_snapshots=memory_snapshots,
        resolved_tags=resolved_tags,
        tag_policy_dicts=tag_policy_dicts,
        system_prompt=system_prompt,
        model_max_tokens=model_max_tokens,
        old_cp_names=old_cp_names,
        region=region,
        account_id=account_id,
    )

    return _agent_response(agent, db)


@router.put("/{agent_id}/redeploy-harness", response_model=AgentResponse)
def redeploy_harness_agent(
    agent_id: int,
    request: AgentCreateRequest,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> AgentResponse:
    """Update and redeploy a harness agent with new configuration.

    Uses the UpdateHarness API to modify the existing harness in-place,
    then updates the local agent record and config.
    """
    agent = get_agent_or_404(agent_id, db)

    if agent.source != "harness":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only harness agents can be updated via this endpoint",
        )

    if not agent.harness_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent has no harness_id — cannot update. Delete and redeploy instead.",
        )

    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    account_id = os.getenv("AWS_ACCOUNT_ID", "")

    # Clean up old credential providers that are no longer needed
    old_config_entry = db.query(ConfigEntry).filter(
        ConfigEntry.agent_id == agent_id, ConfigEntry.key == "AGENT_CONFIG_JSON"
    ).first()
    old_cp_names: set[str] = set()
    if old_config_entry:
        try:
            old_config = json.loads(old_config_entry.value)
            old_mcp = old_config.get("integrations", {}).get("mcp_servers", [])
            for srv in old_mcp:
                cp_name = (srv.get("auth", {}) or {}).get("credential_provider_name")
                if cp_name:
                    old_cp_names.add(cp_name)
        except (json.JSONDecodeError, TypeError):
            pass
        db.delete(old_config_entry)
        db.commit()

    # Update agent fields
    resolved_tags, _ = _resolve_tags(db, request.tags)
    system_prompt = _build_system_prompt(request)

    agent.description = request.description or agent.description
    agent.execution_role_arn = request.role_arn or agent.execution_role_arn
    agent.network_mode = request.network_mode or agent.network_mode
    agent.vpc_config_id = request.vpc_config_id if agent.network_mode == "VPC" else None
    agent.status = "UPDATING"
    agent.deployment_status = "updating"

    effective_allowed = request.allowed_model_ids if request.allowed_model_ids else [request.model_id]
    if request.model_id and request.model_id not in effective_allowed:
        effective_allowed = [request.model_id] + effective_allowed
    agent.set_allowed_model_ids(effective_allowed)

    if resolved_tags:
        agent.set_tags(resolved_tags)

    # Rebuild authorizer config
    authorizer_config = None
    user_client_id = os.getenv("LOOM_COGNITO_USER_CLIENT_ID", "")
    if request.authorizer_type == "cognito" and request.authorizer_pool_id:
        jwt_config: dict[str, Any] = {
            "discoveryUrl": f"https://cognito-idp.{region}.amazonaws.com/{request.authorizer_pool_id}/.well-known/openid-configuration"
        }
        allowed_clients = list(request.authorizer_allowed_clients) if request.authorizer_allowed_clients else []
        if user_client_id and user_client_id not in allowed_clients:
            allowed_clients.append(user_client_id)
        if allowed_clients:
            jwt_config["allowedClients"] = allowed_clients
        if request.authorizer_allowed_audience:
            jwt_config["allowedAudience"] = request.authorizer_allowed_audience
        if request.authorizer_allowed_scopes:
            jwt_config["allowedScopes"] = request.authorizer_allowed_scopes
        authorizer_config = {"customJWTAuthorizer": jwt_config}
    elif request.authorizer_type in ("other", "entra_id", "okta") and request.authorizer_discovery_url:
        jwt_config = {"discoveryUrl": request.authorizer_discovery_url}
        if request.authorizer_allowed_audience:
            jwt_config["allowedAudience"] = request.authorizer_allowed_audience
        if request.authorizer_allowed_clients and request.authorizer_type not in ("entra_id", "okta"):
            jwt_config["allowedClients"] = request.authorizer_allowed_clients
        if request.authorizer_allowed_scopes:
            jwt_config["allowedScopes"] = request.authorizer_allowed_scopes
        authorizer_config = {"customJWTAuthorizer": jwt_config}

    if authorizer_config:
        jwt = authorizer_config.get("customJWTAuthorizer", {})
        agent.set_authorizer_config({
            "type": request.authorizer_type,
            "pool_id": request.authorizer_pool_id,
            "discovery_url": jwt.get("discoveryUrl"),
            "allowed_audience": jwt.get("allowedAudience", []),
            "allowed_clients": jwt.get("allowedClients", []),
            "allowed_scopes": jwt.get("allowedScopes", []),
        })

    db.commit()
    db.refresh(agent)

    # Snapshot MCP servers
    mcp_snapshots: list[dict[str, Any]] = []
    if request.mcp_servers:
        mcp_records = db.query(McpServer).filter(McpServer.id.in_(request.mcp_servers)).all()
        for server in mcp_records:
            mcp_snapshots.append({
                "name": server.name,
                "endpoint_url": server.endpoint_url,
                "transport_type": server.transport_type,
                "auth_type": server.auth_type,
                "oauth2_client_id": server.oauth2_client_id,
                "oauth2_client_secret": server.oauth2_client_secret,
                "oauth2_well_known_url": server.oauth2_well_known_url,
                "oauth2_scopes": server.oauth2_scopes,
                "delegation_mode": (server.delegation_mode or "m2m"),
                "obo_grant_type": server.obo_grant_type,
                "api_key_header_name": server.api_key_header_name,
                "supports_elicitation": server.supports_elicitation == "true",
            })

    extra_harness_tools = request.harness_tools or []

    # Snapshot memory resources for update
    update_memory_snapshots: list[dict[str, Any]] = []
    if request.memory_ids:
        mem_records = db.query(Memory).filter(Memory.id.in_(request.memory_ids)).all()
        update_memory_snapshots = [
            {"name": m.name, "memory_id": m.memory_id, "arn": m.arn}
            for m in mem_records
        ]

    # Resolve VPC subnet/SG IDs for harness VPC networking
    update_vpc_subnet_ids: list[str] | None = None
    update_vpc_sg_ids: list[str] | None = None
    if request.network_mode == "VPC" and request.vpc_config_id:
        vpc_cfg = db.query(VpcConfig).filter(VpcConfig.id == request.vpc_config_id).first()
        if vpc_cfg:
            update_vpc_subnet_ids = vpc_cfg.get_subnet_ids()
            update_vpc_sg_ids = vpc_cfg.get_sg_ids()

    # Resolve Code Interpreter config for harness update
    update_ci_config: dict[str, Any] | None = None
    if request.code_interpreter_enabled:
        ci_role_arn_update = ""
        if request.code_interpreter_role_id:
            ci_role_upd = db.query(ManagedRole).filter(ManagedRole.id == request.code_interpreter_role_id).first()
            if ci_role_upd:
                ci_role_arn_update = ci_role_upd.role_arn
        update_ci_config = {
            "region": (request.code_interpreter_region or "").strip(),
            "network_mode": request.code_interpreter_network_mode or "SANDBOX",
            "execution_role_arn": ci_role_arn_update,
            "existing_id": agent.code_interpreter_id,
        }

    background_tasks.add_task(
        _update_harness_background,
        agent_id=agent_id,
        harness_id=agent.harness_id,
        name=agent.name,
        execution_role_arn=agent.execution_role_arn,
        model_id=request.model_id,
        system_prompt=system_prompt,
        mcp_snapshots=mcp_snapshots,
        memory_snapshots=update_memory_snapshots,
        extra_harness_tools=extra_harness_tools,
        max_iterations=request.harness_max_iterations,
        max_tokens=request.harness_max_tokens,
        authorizer_config=authorizer_config,
        network_mode=request.network_mode,
        vpc_subnet_ids=update_vpc_subnet_ids,
        vpc_security_group_ids=update_vpc_sg_ids,
        idle_timeout=request.idle_timeout,
        max_lifetime=request.max_lifetime,
        resolved_tags=resolved_tags,
        old_cp_names=old_cp_names,
        region=region,
        account_id=account_id,
        ci_config=update_ci_config,
    )

    return _agent_response(agent, db)


@router.get("/{agent_id}/config", response_model=list[ConfigEntryResponse])
def get_agent_config(agent_id: int, user: UserInfo = Depends(require_scopes("agent:read")), db: Session = Depends(get_db)) -> list[ConfigEntryResponse]:
    """Get all configuration entries for an agent. Secret values are masked."""
    get_agent_or_404(agent_id, db)
    entries = db.query(ConfigEntry).filter(ConfigEntry.agent_id == agent_id).all()
    result = []
    for entry in entries:
        d = entry.to_dict()
        if entry.is_secret:
            d["value"] = "********"
        result.append(ConfigEntryResponse(**d))
    return result


@router.get("/{agent_id}/export")
def export_agent(agent_id: int, user: UserInfo = Depends(require_scopes("admin:write")), db: Session = Depends(get_db)):
    """Export agent config in form-compatible format. Super admin only."""
    agent = get_agent_or_404(agent_id, db)
    data: dict[str, Any] = {}

    # Extract from AGENT_CONFIG_JSON
    entries = db.query(ConfigEntry).filter(ConfigEntry.agent_id == agent_id).all()
    agent_config: dict = {}
    for entry in entries:
        if entry.key == "AGENT_CONFIG_JSON":
            try:
                agent_config = json.loads(entry.value)
            except (json.JSONDecodeError, TypeError):
                pass

    # Order matches form layout
    data["deployment_type"] = "managed" if agent.source == "harness" else "custom"
    data["name"] = agent.name
    if agent.description:
        data["description"] = agent.description

    system_prompt = agent_config.get("system_prompt", "")
    if system_prompt:
        data["system_prompt"] = system_prompt

    if agent_config.get("model_id"):
        data["model"] = agent_config["model_id"]
    allowed = agent.get_allowed_model_ids()
    if allowed:
        data["allowed_models"] = allowed

    if agent.network_mode and agent.network_mode != "PUBLIC":
        vpc_block: dict[str, Any] = {"mode": agent.network_mode}
        if agent.network_mode == "VPC" and agent.vpc_config_id:
            vpc_cfg = db.query(VpcConfig).filter(VpcConfig.id == agent.vpc_config_id).first()
            if vpc_cfg:
                vpc_block["config"] = vpc_cfg.name
        data["vpc"] = vpc_block

    if agent.execution_role_arn:
        managed_role = db.query(ManagedRole).filter(ManagedRole.role_arn == agent.execution_role_arn).first()
        if managed_role:
            data["role"] = managed_role.role_name
        else:
            data["role_arn"] = agent.execution_role_arn

    tags = agent.get_tags()
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

    auth_config = agent.get_authorizer_config()
    if auth_config:
        ac = None
        if auth_config.get("pool_id"):
            ac = db.query(AuthorizerConfig).filter(AuthorizerConfig.pool_id == auth_config["pool_id"]).first()
        if not ac and auth_config.get("discovery_url"):
            ac = db.query(AuthorizerConfig).filter(AuthorizerConfig.discovery_url == auth_config["discovery_url"]).first()
        if ac:
            data["authorizer"] = ac.name

    if agent.source == "harness":
        max_iterations = agent_config.get("max_iterations") or agent_config.get("harness", {}).get("max_iterations")
        if max_iterations:
            data["max_iterations"] = max_iterations
        max_tokens = agent_config.get("max_tokens") or agent_config.get("harness", {}).get("max_tokens")
        if max_tokens:
            data["max_tokens"] = max_tokens
        harness_cfg = agent_config.get("harness_config", {})
        deploy_tools = harness_cfg.get("deploy_tools", [])
        for tool in deploy_tools:
            if tool.get("type") == "inline_function" and tool.get("name") == "user_confirmation":
                data["human_confirmation"] = True
                inline_fn = tool.get("config", {}).get("inlineFunction", {})
                if inline_fn.get("description"):
                    data["confirmation_policy"] = inline_fn["description"]
                break

    integrations = agent_config.get("integrations", {})
    mcp_servers = integrations.get("mcp_servers", [])
    if mcp_servers:
        names = [s.get("name", "") for s in mcp_servers if s.get("name")]
        verified = [n for n in names if db.query(McpServer).filter(McpServer.name == n).first()]
        if verified:
            data["mcp_servers"] = verified
    a2a_agents = integrations.get("a2a_agents", [])
    if a2a_agents:
        names = [a.get("name", "") for a in a2a_agents if a.get("name")]
        verified = [n for n in names if db.query(A2aAgentModel).filter(A2aAgentModel.name == n).first()]
        if verified:
            data["a2a_agents"] = verified
    memory_cfg = integrations.get("memory", {})
    memory_resources = memory_cfg.get("resources", [])
    if memory_resources:
        names = [m.get("name", "") for m in memory_resources if m.get("name")]
        verified = [n for n in names if db.query(Memory).filter(Memory.name == n).first()]
        if verified:
            data["memories"] = verified
    ci_cfg = integrations.get("code_interpreter", {})
    if ci_cfg.get("enabled"):
        ci_export: dict[str, Any] = {
            "enabled": True,
            "region": ci_cfg.get("region") or "us-east-1",
            "network_mode": ci_cfg.get("network_mode") or "SANDBOX",
        }
        if ci_cfg.get("execution_role_arn"):
            role_arn = ci_cfg["execution_role_arn"]
            managed_role = db.query(ManagedRole).filter(ManagedRole.role_arn == role_arn).first()
            if managed_role:
                ci_export["role"] = managed_role.role_name
            else:
                ci_export["role"] = role_arn
        data["code_interpreter"] = ci_export

    return data


@router.patch("/{agent_id}", response_model=AgentResponse)
def patch_agent(
    agent_id: int,
    request: AgentUpdateRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> AgentResponse:
    """Update editable fields on an agent (e.g. description, model_id, allowed_model_ids)."""
    agent = get_agent_or_404(agent_id, db)
    if "description" in request.model_fields_set:
        agent.description = request.description
        if agent.runtime_id and agent.source == "deploy":
            try:
                update_runtime(agent.runtime_id, description=request.description or "")
            except Exception:
                logger.warning("Failed to propagate description to AgentCore for agent %s", agent_id, exc_info=True)
    if "model_id" in request.model_fields_set and request.model_id is not None:
        valid_ids = {m["model_id"] for m in SUPPORTED_MODELS}
        if request.model_id not in valid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid model ID: {request.model_id}",
            )
        for entry in agent.config_entries:
            if entry.key == "AGENT_CONFIG_JSON":
                try:
                    config = json.loads(entry.value)
                    config["model_id"] = request.model_id
                    entry.value = json.dumps(config)
                except (json.JSONDecodeError, TypeError):
                    pass
                break
    if "allowed_model_ids" in request.model_fields_set and request.allowed_model_ids is not None:
        valid_ids = {m["model_id"] for m in SUPPORTED_MODELS}
        invalid = [m for m in request.allowed_model_ids if m not in valid_ids]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid model IDs: {invalid}",
            )
        agent.set_allowed_model_ids(request.allowed_model_ids)
    db.commit()
    db.refresh(agent)
    return _agent_response(agent, db)


@router.put("/{agent_id}/config", response_model=list[ConfigEntryResponse])
def update_agent_config(
    agent_id: int,
    request: ConfigUpdateRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> list[ConfigEntryResponse]:
    """Update configuration entries for an agent. Adds new keys and updates existing ones."""
    get_agent_or_404(agent_id, db)

    for key, value in request.config.items():
        existing = db.query(ConfigEntry).filter(
            ConfigEntry.agent_id == agent_id,
            ConfigEntry.key == key,
        ).first()
        if existing:
            existing.value = value
        else:
            entry = ConfigEntry(
                agent_id=agent_id,
                key=key,
                value=value,
                is_secret=False,
                source="env_var",
            )
            db.add(entry)

    db.commit()

    entries = db.query(ConfigEntry).filter(ConfigEntry.agent_id == agent_id).all()
    result = []
    for entry in entries:
        d = entry.to_dict()
        if entry.is_secret:
            d["value"] = "********"
        result.append(ConfigEntryResponse(**d))
    return result


# ---------------------------------------------------------------------------
# External Integration Info
# ---------------------------------------------------------------------------

class IntegrationEndpoint(BaseModel):
    qualifier: str
    invocation_url: str
    protocol_url: str | None = None
    protocol_url_label: str | None = None

class IntegrationAuthSigV4(BaseModel):
    method: str = "SigV4"
    iam_action: str
    resource_arn: str
    execution_role_arn: str | None = None
    example_policy: dict
    example_boto3: str
    example_cli: str

class IntegrationAuthOAuth2(BaseModel):
    method: str = "OAuth2"
    authorizer_type: str
    discovery_url: str | None = None
    token_endpoint: str | None = None
    allowed_client_ids: list[str] = []
    allowed_scopes: list[str] = []
    example_token_request: str
    example_invocation: str

class IntegrationInfoResponse(BaseModel):
    runtime_arn: str
    region: str
    protocol: str
    network_mode: str
    endpoints: list[IntegrationEndpoint]
    auth: IntegrationAuthSigV4 | IntegrationAuthOAuth2


def _build_integration_info(agent, db) -> IntegrationInfoResponse:
    from urllib.parse import quote

    region = agent.region or "us-east-1"
    arn = agent.arn or ""
    runtime_id = agent.runtime_id or ""
    protocol = (agent.protocol or "HTTP").upper()
    network_mode = (agent.network_mode or "PUBLIC").upper()
    source = agent.source or "custom"
    base_host = f"https://bedrock-agentcore.{region}.amazonaws.com"

    qualifiers_raw = agent.available_qualifiers
    if isinstance(qualifiers_raw, str):
        import json as _json
        try:
            qualifiers = _json.loads(qualifiers_raw)
        except Exception:
            qualifiers = [qualifiers_raw]
    elif isinstance(qualifiers_raw, list):
        qualifiers = qualifiers_raw
    else:
        qualifiers = ["DEFAULT"]

    encoded_arn = quote(arn, safe="")
    endpoints: list[IntegrationEndpoint] = []
    if source == "harness":
        for q in qualifiers:
            endpoints.append(IntegrationEndpoint(
                qualifier=q,
                invocation_url=f"{base_host}/harnesses/invoke",
                protocol_url=None,
                protocol_url_label=None,
            ))
    else:
        for q in qualifiers:
            invoke_url = f"{base_host}/runtimes/{encoded_arn}/invocations"
            proto_url = None
            proto_label = None
            if protocol == "MCP":
                proto_url = f"{base_host}/runtimes/{encoded_arn}/mcp"
                proto_label = "MCP Streamable HTTP"
            elif protocol == "A2A":
                proto_url = f"{base_host}/runtimes/{encoded_arn}/.well-known/agent.json"
                proto_label = "A2A Agent Card"
            endpoints.append(IntegrationEndpoint(
                qualifier=q,
                invocation_url=invoke_url,
                protocol_url=proto_url,
                protocol_url_label=proto_label,
            ))

    auth_config = agent.authorizer_config
    if isinstance(auth_config, str):
        import json as _json
        try:
            auth_config = _json.loads(auth_config)
        except Exception:
            auth_config = None

    if not auth_config or not auth_config.get("type"):
        iam_action = "bedrock-agentcore:InvokeHarness" if source == "harness" else "bedrock-agentcore:InvokeAgentRuntime"
        example_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": iam_action,
                "Resource": arn or f"arn:aws:bedrock-agentcore:{region}:*:runtime/{runtime_id}",
            }],
        }
        first_url = endpoints[0].invocation_url if endpoints else "<invocation_url>"
        if source == "harness":
            harness_arn = getattr(agent, "harness_id", None) or arn
            example_boto3 = (
                'import boto3\n'
                'import json\n\n'
                f'client = boto3.client("bedrock-agentcore", region_name="{region}")\n'
                f'response = client.invoke_harness(\n'
                f'    harnessArn="{harness_arn}",\n'
                f'    runtimeSessionId="your-session-id",\n'
                f'    messages=[{{"role": "user", "content": [{{"text": "Hello"}}]}}]\n'
                f')'
            )
            example_cli = (
                f'aws bedrock-agentcore invoke-harness \\\n'
                f'  --harness-arn "{harness_arn}" \\\n'
                f'  --runtime-session-id "your-session-id" \\\n'
                f'  --messages \'[{{"role":"user","content":[{{"text":"Hello"}}]}}]\' \\\n'
                f'  --region {region}'
            )
        else:
            example_boto3 = (
                'import boto3\n'
                'import json\n\n'
                f'client = boto3.client("bedrock-agentcore", region_name="{region}")\n'
                f'response = client.invoke_agent_runtime(\n'
                f'    agentRuntimeArn="{arn}",\n'
                f'    qualifier="{qualifiers[0]}",\n'
                f'    runtimeSessionId="your-session-id",\n'
                f'    contentType="application/json",\n'
                f'    accept="application/json",\n'
                f'    payload=json.dumps({{"prompt": "Hello", "session_id": "your-session-id"}})\n'
                f')'
            )
            example_cli = (
                f'aws bedrock-agentcore invoke-agent-runtime \\\n'
                f'  --agent-runtime-arn "{arn}" \\\n'
                f'  --qualifier "{qualifiers[0]}" \\\n'
                f'  --runtime-session-id "your-session-id" \\\n'
                f'  --content-type "application/json" \\\n'
                f'  --accept "application/json" \\\n'
                f'  --payload \'{{"prompt": "Hello", "session_id": "your-session-id"}}\' \\\n'
                f'  --region {region} \\\n'
                f'  output.json'
            )
        execution_role = getattr(agent, "execution_role_arn", None)
        auth: IntegrationAuthSigV4 | IntegrationAuthOAuth2 = IntegrationAuthSigV4(
            iam_action=iam_action,
            resource_arn=arn or f"arn:aws:bedrock-agentcore:{region}:*:runtime/{runtime_id}",
            execution_role_arn=execution_role,
            example_policy=example_policy,
            example_boto3=example_boto3,
            example_cli=example_cli,
        )
    else:
        auth_type = auth_config.get("type", "custom")
        pool_id = auth_config.get("pool_id", "")
        discovery_url = auth_config.get("discovery_url", "")
        allowed_clients = auth_config.get("allowed_clients", [])
        allowed_scopes = auth_config.get("allowed_scopes", [])

        if auth_type.lower() == "cognito" and pool_id:
            discovery_url = discovery_url or f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
            try:
                from app.services.cognito import _get_pool_domain
                cognito_domain = _get_pool_domain(pool_id, region)
                token_endpoint = f"https://{cognito_domain}/oauth2/token"
            except Exception:
                token_endpoint = f"https://<your-domain>.auth.{region}.amazoncognito.com/oauth2/token"
        else:
            token_endpoint = discovery_url.replace("/.well-known/openid-configuration", "/oauth2/token") if discovery_url else "<token_endpoint>"

        first_url = endpoints[0].invocation_url if endpoints else "<invocation_url>"
        client_id_placeholder = allowed_clients[0] if allowed_clients else "<client_id>"

        scope_param = ""
        if allowed_scopes:
            scopes_str = " ".join(allowed_scopes)
            scope_param = f"&scope={scopes_str}"

        example_token = (
            f'TOKEN=$(curl -s -X POST "{token_endpoint}" \\\n'
            f'  -H "Content-Type: application/x-www-form-urlencoded" \\\n'
            f'  -d "grant_type=client_credentials'
            f'&client_id={client_id_placeholder}'
            f'&client_secret=YOUR_SECRET'
            f'{scope_param}" \\\n'
            f'  | jq -r \'.access_token\')'
        )
        if source == "harness":
            harness_arn = getattr(agent, "harness_id", None) or arn
            invoke_body = json.dumps({
                "harnessArn": harness_arn,
                "runtimeSessionId": "your-session-id",
                "messages": [{"role": "user", "content": [{"text": "Hello"}]}],
            }, indent=2)
        else:
            invoke_body = json.dumps({
                "prompt": "Hello",
                "session_id": "your-session-id",
            })
        example_invoke = (
            f'curl -X POST "{first_url}" \\\n'
            f'  -H "Authorization: Bearer $TOKEN" \\\n'
            f'  -H "Content-Type: application/json" \\\n'
            f'  --no-buffer \\\n'
            f"  -d '{invoke_body}'"
        )
        auth = IntegrationAuthOAuth2(
            authorizer_type=auth_type,
            discovery_url=discovery_url or None,
            token_endpoint=token_endpoint,
            allowed_client_ids=allowed_clients,
            allowed_scopes=allowed_scopes,
            example_token_request=example_token,
            example_invocation=example_invoke,
        )

    return IntegrationInfoResponse(
        runtime_arn=arn,
        region=region,
        protocol=protocol,
        network_mode=network_mode,
        endpoints=endpoints,
        auth=auth,
    )


@router.get("/{agent_id}/integration", response_model=IntegrationInfoResponse)
async def get_agent_integration(
    agent_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_scopes("agent:read")),
):
    agent = get_agent_or_404(agent_id, db)
    if agent.status != "READY":
        raise HTTPException(status_code=400, detail="Integration info is only available for agents with status READY")
    return _build_integration_info(agent, db)


# ---------------------------------------------------------------------------
# OBO validation / dry-run test endpoint (R7)
# ---------------------------------------------------------------------------
class TestOboRequest(BaseModel):
    credential_provider_name: str = Field(..., description="Name of the OBO credential provider to exercise")
    scopes: list[str] = Field(default_factory=list, description="Scopes requested on the downstream token")
    workload_name: str | None = Field(default=None, description="Optional ACPS workload identity name (defaults to agent-derived)")


class TestOboResponse(BaseModel):
    success: bool
    message: str
    access_token_present: bool = False
    claims: dict | None = None
    scopes: str | None = None
    error: str | None = None


def _decode_jwt_claims(token: str) -> dict | None:
    """Best-effort decode of a JWT's payload (no signature verification)."""
    import base64
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None


@router.post("/{agent_id}/test-obo", response_model=TestOboResponse)
def test_obo_exchange(
    agent_id: int,
    body: TestOboRequest,
    request: Request,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> TestOboResponse:
    """Dry-run an OBO token exchange for a given credential provider.

    Uses the caller's Authorization bearer token as the user subject token,
    calls ACPS ``get-resource-oauth2-token`` with
    ``oauth2Flow=ON_BEHALF_OF_TOKEN_EXCHANGE``, and returns the decoded claims.
    """
    agent = get_agent_or_404(agent_id, db)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User access token required in Authorization header",
        )
    user_token = auth_header[7:]

    region = agent.region or os.getenv("AWS_REGION", "us-east-1")
    workload_name = body.workload_name or f"loom-{agent.name}"

    import boto3
    try:
        acps = boto3.client("acps", region_name=region)
    except Exception as e:
        logger.warning("ACPS client not available: %s", e)
        return TestOboResponse(
            success=False,
            message="ACPS client is not configured in this environment",
            error=str(e),
        )

    try:
        wl = acps.get_workload_access_token_for_jwt(
            workloadName=workload_name,
            userToken=user_token,
        )
        workload_token = wl.get("workloadAccessToken")
        if not workload_token:
            return TestOboResponse(
                success=False,
                message="ACPS returned no workload access token",
                error="missing workloadAccessToken",
            )

        kwargs: dict[str, Any] = {
            "workloadIdentityToken": workload_token,
            "resourceCredentialProviderName": body.credential_provider_name,
            "oauth2Flow": "ON_BEHALF_OF_TOKEN_EXCHANGE",
        }
        if body.scopes:
            kwargs["scopes"] = body.scopes

        token_resp = acps.get_resource_oauth2_token(**kwargs)
        access_token = token_resp.get("accessToken")
        if not access_token:
            return TestOboResponse(
                success=False,
                message="OBO exchange did not return an access token",
                error="missing accessToken",
            )

        claims = _decode_jwt_claims(access_token)
        scp = claims.get("scp") if isinstance(claims, dict) else None
        return TestOboResponse(
            success=True,
            message="OBO token exchange succeeded",
            access_token_present=True,
            claims=claims,
            scopes=scp,
        )
    except Exception as e:
        logger.exception("OBO dry-run failed for agent=%s provider=%s: %s",
                         agent_id, body.credential_provider_name, e)
        return TestOboResponse(
            success=False,
            message="OBO token exchange failed",
            error=str(e),
        )
