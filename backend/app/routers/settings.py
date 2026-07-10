"""Settings endpoints for managing tag policies and site settings."""
import json
import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, get_current_user, require_scopes
from app.models.tag_policy import TagPolicy
from app.models.tag_profile import TagProfile
from app.models.site_setting import SiteSetting
from app.models.vpc_config import VpcConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Site settings defaults and helpers
# ---------------------------------------------------------------------------
SITE_SETTING_DEFAULTS: dict[str, str] = {
    "cpu_io_wait_discount": "75",
    "enabled_model_ids": "[]",
    "loom_registry_id": "",
    "litellm_proxy_base_url": "",
}


def get_site_setting(db: Session, key: str) -> str:
    """Get a site setting value, returning the default if not set."""
    row = db.query(SiteSetting).filter(SiteSetting.key == key).first()
    if row:
        return row.value
    return SITE_SETTING_DEFAULTS.get(key, "")


def get_cpu_io_wait_discount(db: Session) -> float:
    """Get the CPU I/O wait discount as a float (0.0–0.99).

    Stored as an integer percentage (0–99). Returns the decimal equivalent.
    """
    val = get_site_setting(db, "cpu_io_wait_discount")
    try:
        pct = int(float(val))
        pct = max(0, min(99, pct))
        return pct / 100.0
    except (ValueError, TypeError):
        return 0.75




class TagPolicyRequest(BaseModel):
    """Request body for creating/updating a tag policy."""
    key: str = Field(..., description="Tag key name")
    default_value: str | None = Field(None, description="Default value for the tag")
    required: bool = Field(True, description="Whether this tag is required")
    show_on_card: bool = Field(False, description="Whether to display on agent cards")


class TagPolicyResponse(BaseModel):
    """Response model for a tag policy."""
    id: int
    key: str
    default_value: str | None
    designation: str
    required: bool
    show_on_card: bool
    created_at: str | None
    updated_at: str | None


@router.get("/tags", response_model=list[TagPolicyResponse])
def list_tag_policies(user: UserInfo = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TagPolicyResponse]:
    """List all tag policies. Requires authentication but no specific scope (used for displaying tags on cards)."""
    policies = db.query(TagPolicy).order_by(TagPolicy.id).all()
    return [TagPolicyResponse(**p.to_dict()) for p in policies]


@router.post("/tags", response_model=TagPolicyResponse, status_code=status.HTTP_201_CREATED)
def create_tag_policy(
    request: TagPolicyRequest,
    user: UserInfo = Depends(require_scopes("tagging:write")),
    db: Session = Depends(get_db),
) -> TagPolicyResponse:
    """Create a new tag policy."""
    existing = db.query(TagPolicy).filter(TagPolicy.key == request.key).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tag policy with key '{request.key}' already exists",
        )

    policy = TagPolicy(
        key=request.key,
        default_value=request.default_value,
        required=request.required,
        show_on_card=request.show_on_card,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return TagPolicyResponse(**policy.to_dict())


@router.put("/tags/{tag_id}", response_model=TagPolicyResponse)
def update_tag_policy(
    tag_id: int,
    request: TagPolicyRequest,
    user: UserInfo = Depends(require_scopes("tagging:write")),
    db: Session = Depends(get_db),
) -> TagPolicyResponse:
    """Update an existing tag policy."""
    policy = db.query(TagPolicy).filter(TagPolicy.id == tag_id).first()
    if not policy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag policy not found")

    # Check uniqueness if key changed
    if request.key != policy.key:
        conflict = db.query(TagPolicy).filter(TagPolicy.key == request.key).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tag policy with key '{request.key}' already exists",
            )

    policy.key = request.key
    policy.default_value = request.default_value
    policy.required = request.required
    policy.show_on_card = request.show_on_card
    policy.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(policy)
    return TagPolicyResponse(**policy.to_dict())


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag_policy(
    tag_id: int,
    user: UserInfo = Depends(require_scopes("tagging:write")),
    db: Session = Depends(get_db),
) -> None:
    """Delete a tag policy."""
    policy = db.query(TagPolicy).filter(TagPolicy.id == tag_id).first()
    if not policy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag policy not found")
    db.delete(policy)
    db.commit()


# ---------------------------------------------------------------------------
# Tag Profile CRUD
# ---------------------------------------------------------------------------
class TagProfileRequest(BaseModel):
    """Request body for creating/updating a tag profile."""
    name: str = Field(..., description="Profile name")
    tags: dict[str, str] = Field(..., description="Tag key-value pairs")


class TagProfileResponse(BaseModel):
    """Response model for a tag profile."""
    id: int
    name: str
    tags: dict[str, str]
    created_at: str | None
    updated_at: str | None


@router.get("/tag-profiles", response_model=list[TagProfileResponse])
def list_tag_profiles(user: UserInfo = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TagProfileResponse]:
    """List all tag profiles. Requires authentication but no specific scope (used for resource creation forms)."""
    profiles = db.query(TagProfile).order_by(TagProfile.name).all()
    return [TagProfileResponse(**p.to_dict()) for p in profiles]


@router.post("/tag-profiles", response_model=TagProfileResponse, status_code=status.HTTP_201_CREATED)
def create_tag_profile(
    request: TagProfileRequest,
    user: UserInfo = Depends(require_scopes("tagging:write")),
    db: Session = Depends(get_db),
) -> TagProfileResponse:
    """Create a new tag profile."""
    existing = db.query(TagProfile).filter(TagProfile.name == request.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tag profile with name '{request.name}' already exists",
        )

    # Validate that all required tag policies have values
    policies = db.query(TagPolicy).filter(TagPolicy.required == True).all()
    missing = [p.key for p in policies if not request.tags.get(p.key, "").strip()]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required tag values: {', '.join(missing)}",
        )

    profile = TagProfile(name=request.name)
    profile.set_tags(request.tags)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return TagProfileResponse(**profile.to_dict())


@router.put("/tag-profiles/{profile_id}", response_model=TagProfileResponse)
def update_tag_profile(
    profile_id: int,
    request: TagProfileRequest,
    user: UserInfo = Depends(require_scopes("tagging:write")),
    db: Session = Depends(get_db),
) -> TagProfileResponse:
    """Update an existing tag profile."""
    profile = db.query(TagProfile).filter(TagProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag profile not found")

    # Check name uniqueness if changed
    if request.name != profile.name:
        conflict = db.query(TagProfile).filter(TagProfile.name == request.name).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tag profile with name '{request.name}' already exists",
            )

    # Validate required tags
    policies = db.query(TagPolicy).filter(TagPolicy.required == True).all()
    missing = [p.key for p in policies if not request.tags.get(p.key, "").strip()]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required tag values: {', '.join(missing)}",
        )

    profile.name = request.name
    profile.set_tags(request.tags)
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return TagProfileResponse(**profile.to_dict())


@router.delete("/tag-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag_profile(
    profile_id: int,
    user: UserInfo = Depends(require_scopes("tagging:write")),
    db: Session = Depends(get_db),
) -> None:
    """Delete a tag profile."""
    profile = db.query(TagProfile).filter(TagProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag profile not found")
    db.delete(profile)
    db.commit()


# ---------------------------------------------------------------------------
# Site Settings CRUD
# ---------------------------------------------------------------------------
class SiteSettingRequest(BaseModel):
    """Request body for creating/updating a site setting."""
    key: str = Field(..., description="Setting key")
    value: str = Field(..., description="Setting value")


class SiteSettingResponse(BaseModel):
    """Response model for a site setting."""
    id: int | None
    key: str
    value: str
    updated_at: str | None


@router.get("/site", response_model=list[SiteSettingResponse])
def list_site_settings(
    user: UserInfo = Depends(require_scopes("settings:read")),
    db: Session = Depends(get_db),
) -> list[SiteSettingResponse]:
    """List all site settings, including defaults for unset keys."""
    stored = {s.key: s for s in db.query(SiteSetting).all()}
    result = []
    for key, default in SITE_SETTING_DEFAULTS.items():
        if key in stored:
            result.append(SiteSettingResponse(**stored[key].to_dict()))
        else:
            result.append(SiteSettingResponse(id=None, key=key, value=default, updated_at=None))
    # Include any stored settings not in defaults
    for key, setting in stored.items():
        if key not in SITE_SETTING_DEFAULTS:
            result.append(SiteSettingResponse(**setting.to_dict()))
    return result


@router.put("/site/{key}", response_model=SiteSettingResponse)
def update_site_setting(
    key: str,
    request: SiteSettingRequest,
    user: UserInfo = Depends(require_scopes("settings:write")),
    db: Session = Depends(get_db),
) -> SiteSettingResponse:
    """Create or update a site setting."""
    setting = db.query(SiteSetting).filter(SiteSetting.key == key).first()
    if setting:
        setting.value = request.value
        setting.updated_at = datetime.utcnow()
    else:
        setting = SiteSetting(key=key, value=request.value)
        db.add(setting)
    db.commit()
    db.refresh(setting)
    return SiteSettingResponse(**setting.to_dict())


# ---------------------------------------------------------------------------
# Registry Configuration
# ---------------------------------------------------------------------------
class RegistryConfigResponse(BaseModel):
    """Response for registry configuration."""
    registry_arn: str
    registry_id: str
    enabled: bool


@router.get("/registry", response_model=RegistryConfigResponse)
def get_registry_config(
    user: UserInfo = Depends(require_scopes("settings:read")),
    db: Session = Depends(get_db),
) -> RegistryConfigResponse:
    """Get the current registry configuration."""
    arn = get_site_setting(db, "loom_registry_id")
    from app.services.registry import get_registry_client
    client = get_registry_client()
    return RegistryConfigResponse(
        registry_arn=arn,
        registry_id=client.registry_id,
        enabled=bool(client.registry_id),
    )


class RegistryConfigRequest(BaseModel):
    """Request to update registry configuration."""
    registry_arn: str = Field(..., description="Registry ARN (empty string to disable)")


@router.put("/registry", response_model=RegistryConfigResponse)
def update_registry_config(
    request: RegistryConfigRequest,
    user: UserInfo = Depends(require_scopes("settings:write")),
    db: Session = Depends(get_db),
) -> RegistryConfigResponse:
    """Update the registry configuration. Validates the ARN before saving."""
    from app.services.registry import validate_registry_arn, configure_registry, parse_registry_id_from_arn

    registry_id = ""
    if request.registry_arn:
        try:
            registry_id = validate_registry_arn(request.registry_arn)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # Save to DB
    setting = db.query(SiteSetting).filter(SiteSetting.key == "loom_registry_id").first()
    if setting:
        setting.value = request.registry_arn
        setting.updated_at = datetime.utcnow()
    else:
        setting = SiteSetting(key="loom_registry_id", value=request.registry_arn)
        db.add(setting)
    db.commit()

    # Reconfigure the in-memory singleton
    client = configure_registry(registry_id)

    # When (re-)enabling, sync stored registry statuses against the actual registry
    if registry_id:
        _sync_registry_statuses(client, db)

    return RegistryConfigResponse(
        registry_arn=request.registry_arn,
        registry_id=registry_id,
        enabled=bool(registry_id),
    )


# ---------------------------------------------------------------------------
# LiteLLM Proxy Configuration
# ---------------------------------------------------------------------------
class LitellmProxyConfigResponse(BaseModel):
    """Response for LiteLLM proxy configuration. Never returns the master key itself."""
    enabled: bool
    base_url: str
    discovery_base_url: str
    has_master_key: bool


@router.get("/litellm-proxy", response_model=LitellmProxyConfigResponse)
def get_litellm_proxy_config(
    user: UserInfo = Depends(require_scopes("settings:read")),
    db: Session = Depends(get_db),
) -> LitellmProxyConfigResponse:
    """Get the current LiteLLM proxy configuration (URLs only; key is write-only).

    Reflects the env-seeded defaults (LOOM_LITELLM_PROXY_BASE_URL /
    LOOM_LITELLM_DISCOVERY_BASE_URL) when no Settings-page override has been
    saved yet, so the page shows real values to edit rather than blanks.
    """
    from app.services.litellm import get_effective_config, has_master_key

    config = get_effective_config(db)
    return LitellmProxyConfigResponse(
        enabled=config["enabled"],
        base_url=config["agent_base_url"],
        discovery_base_url=config["discovery_base_url"],
        has_master_key=has_master_key(db),
    )


class LitellmProxyConfigRequest(BaseModel):
    """Request to update LiteLLM proxy configuration."""
    enabled: bool = Field(..., description="Whether the LiteLLM connection is active")
    base_url: str = Field(..., description="Agent Base URL — what deployed agents/harnesses use at runtime")
    discovery_base_url: str = Field(
        "", description="Discovery Base URL — what Loom itself uses to list models. "
        "Leave empty to reuse Agent Base URL (they're typically the same in production)."
    )
    master_key: str | None = Field(None, description="Master key. Omit to keep the currently stored key.")


@router.put("/litellm-proxy", response_model=LitellmProxyConfigResponse)
def update_litellm_proxy_config(
    request: LitellmProxyConfigRequest,
    user: UserInfo = Depends(require_scopes("settings:write")),
    db: Session = Depends(get_db),
) -> LitellmProxyConfigResponse:
    """Update the LiteLLM proxy configuration. Omitting master_key leaves the stored key untouched."""
    from app.services.litellm import MASTER_KEY_SECRET_NAME, has_master_key, is_enabled
    from app.services.model_catalog import clear_litellm_cache
    from app.services.secrets import store_secret

    for key, value in (
        ("litellm_enabled", "true" if request.enabled else "false"),
        ("litellm_proxy_base_url", request.base_url),
        ("litellm_discovery_base_url", request.discovery_base_url),
    ):
        setting = db.query(SiteSetting).filter(SiteSetting.key == key).first()
        if setting:
            setting.value = value
            setting.updated_at = datetime.utcnow()
        else:
            db.add(SiteSetting(key=key, value=value))
    db.commit()

    if request.master_key:
        region = os.getenv("AWS_REGION", "us-east-1")
        store_secret(
            name=MASTER_KEY_SECRET_NAME,
            secret_value=request.master_key,
            region=region,
            description="LiteLLM proxy master key (site-level, used to vend per-agent virtual keys)",
        )

    clear_litellm_cache()

    return LitellmProxyConfigResponse(
        enabled=is_enabled(db),
        base_url=request.base_url,
        discovery_base_url=request.discovery_base_url,
        has_master_key=has_master_key(db),
    )


def _sync_registry_statuses(client, db: Session) -> None:  # noqa: ANN001
    """Validate stored registry_record_id / registry_status against the live registry."""
    from app.models.mcp import McpServer
    from app.models.a2a import A2aAgent
    from app.models.agent import Agent

    models = [McpServer, A2aAgent, Agent]
    updated = 0
    cleared = 0

    for model in models:
        resources = db.query(model).filter(model.registry_record_id.isnot(None)).all()
        for resource in resources:
            record_id = resource.registry_record_id
            try:
                rec = client.get_record(record_id)
                if not rec or not rec.get("recordId"):
                    logger.info("Registry record %s no longer exists; clearing from %s id=%s",
                                record_id, model.__tablename__, resource.id)
                    resource.registry_record_id = None
                    resource.registry_status = None
                    cleared += 1
                else:
                    new_status = rec.get("status")
                    if new_status and new_status != resource.registry_status:
                        logger.info("Registry record %s status changed: %s -> %s for %s id=%s",
                                    record_id, resource.registry_status, new_status,
                                    model.__tablename__, resource.id)
                        resource.registry_status = new_status
                        updated += 1
            except Exception:
                logger.warning("Failed to fetch registry record %s for %s id=%s; clearing stale link",
                               record_id, model.__tablename__, resource.id, exc_info=True)
                resource.registry_record_id = None
                resource.registry_status = None
                cleared += 1

    if updated or cleared:
        db.commit()
        logger.info("Registry sync complete: %d updated, %d cleared", updated, cleared)


# ---------------------------------------------------------------------------
# Enabled Models Configuration
# ---------------------------------------------------------------------------
def get_enabled_model_ids(db: Session) -> list[str]:
    """Return the list of admin-enabled model IDs. Empty list means all models."""
    raw = get_site_setting(db, "enabled_model_ids")
    try:
        ids = json.loads(raw)
        if isinstance(ids, list):
            return ids
    except (json.JSONDecodeError, TypeError):
        pass
    return []


class EnabledModelsRequest(BaseModel):
    """Request to update the set of enabled models."""
    model_ids: list[str] = Field(..., description="List of enabled model IDs (empty = all)")


class EnabledModelsResponse(BaseModel):
    """Response for enabled models configuration."""
    model_ids: list[str]
    all_models: list[dict[str, Any]]


@router.get("/models", response_model=EnabledModelsResponse)
def get_enabled_models(
    user: UserInfo = Depends(require_scopes("settings:read")),
    db: Session = Depends(get_db),
) -> EnabledModelsResponse:
    """Get the list of admin-enabled model IDs along with the full model catalog."""
    from app.routers.agents import DEFAULT_REGION
    from app.services.model_catalog import get_merged_models
    enabled = get_enabled_model_ids(db)
    return EnabledModelsResponse(model_ids=enabled, all_models=get_merged_models(DEFAULT_REGION))


@router.put("/models", response_model=EnabledModelsResponse)
def update_enabled_models(
    request: EnabledModelsRequest,
    user: UserInfo = Depends(require_scopes("settings:write")),
    db: Session = Depends(get_db),
) -> EnabledModelsResponse:
    """Update the set of admin-enabled models."""
    from app.routers.agents import DEFAULT_REGION
    from app.services.model_catalog import get_merged_models
    # Validate against the dynamic merged catalog (static + live LiteLLM/
    # Bedrock models) so dynamically-discovered ids can be enabled too — a
    # model that's momentarily unavailable per the live catalog is still a
    # known, valid model ID as long as it appears in the merged list.
    valid_ids = {m["model_id"] for m in get_merged_models(DEFAULT_REGION)}
    invalid = [mid for mid in request.model_ids if mid not in valid_ids]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown model IDs: {', '.join(invalid)}",
        )
    value = json.dumps(request.model_ids)
    setting = db.query(SiteSetting).filter(SiteSetting.key == "enabled_model_ids").first()
    if setting:
        setting.value = value
        setting.updated_at = datetime.utcnow()
    else:
        setting = SiteSetting(key="enabled_model_ids", value=value)
        db.add(setting)
    db.commit()
    return EnabledModelsResponse(model_ids=request.model_ids, all_models=get_merged_models(DEFAULT_REGION))


@router.post("/litellm-proxy/refresh", response_model=EnabledModelsResponse)
def refresh_litellm_models(
    user: UserInfo = Depends(require_scopes("settings:write")),
    db: Session = Depends(get_db),
) -> EnabledModelsResponse:
    """Force a live re-fetch of the LiteLLM proxy's model catalog, bypassing
    the cache — recovers from a stale empty result (e.g. cached while the
    proxy was unreachable) without waiting out the TTL or restarting."""
    from app.routers.agents import DEFAULT_REGION
    from app.services.model_catalog import clear_litellm_cache, get_merged_models

    clear_litellm_cache()
    enabled = get_enabled_model_ids(db)
    return EnabledModelsResponse(model_ids=enabled, all_models=get_merged_models(DEFAULT_REGION))


# ---------------------------------------------------------------------------
# VPC Configuration CRUD
# ---------------------------------------------------------------------------
class VpcConfigRequest(BaseModel):
    """Request body for creating/updating a VPC configuration."""
    name: str = Field(..., description="Friendly name for this VPC configuration")
    description: str | None = Field(None, description="Optional description")
    vpc_id: str = Field(..., description="VPC ID (vpc-xxxxxxxx)")
    subnet_ids: list[str] = Field(..., description="Private subnet IDs")
    sg_ids: list[str] = Field(..., description="Security group IDs")


class VpcConfigResponse(BaseModel):
    """Response model for a VPC configuration."""
    id: int
    name: str
    description: str | None
    vpc_id: str
    subnet_ids: list[str]
    sg_ids: list[str]
    created_at: str | None
    updated_at: str | None


@router.get("/vpc-configs", response_model=list[VpcConfigResponse])
def list_vpc_configs(
    user: UserInfo = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[VpcConfigResponse]:
    """List all VPC configurations. Requires authentication (used in agent deploy form)."""
    configs = db.query(VpcConfig).order_by(VpcConfig.name).all()
    return [VpcConfigResponse(**c.to_dict()) for c in configs]


@router.post("/vpc-configs", response_model=VpcConfigResponse, status_code=status.HTTP_201_CREATED)
def create_vpc_config(
    request: VpcConfigRequest,
    user: UserInfo = Depends(require_scopes("settings:write")),
    db: Session = Depends(get_db),
) -> VpcConfigResponse:
    """Create a new VPC configuration."""
    existing = db.query(VpcConfig).filter(VpcConfig.name == request.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VPC configuration with name '{request.name}' already exists",
        )
    config = VpcConfig(
        name=request.name,
        description=request.description,
        vpc_id=request.vpc_id,
    )
    config.set_subnet_ids(request.subnet_ids)
    config.set_sg_ids(request.sg_ids)
    db.add(config)
    db.commit()
    db.refresh(config)
    return VpcConfigResponse(**config.to_dict())


@router.put("/vpc-configs/{config_id}", response_model=VpcConfigResponse)
def update_vpc_config(
    config_id: int,
    request: VpcConfigRequest,
    user: UserInfo = Depends(require_scopes("settings:write")),
    db: Session = Depends(get_db),
) -> VpcConfigResponse:
    """Update an existing VPC configuration."""
    config = db.query(VpcConfig).filter(VpcConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VPC configuration not found")
    if request.name != config.name:
        conflict = db.query(VpcConfig).filter(VpcConfig.name == request.name).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"VPC configuration with name '{request.name}' already exists",
            )
    config.name = request.name
    config.description = request.description
    config.vpc_id = request.vpc_id
    config.set_subnet_ids(request.subnet_ids)
    config.set_sg_ids(request.sg_ids)
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return VpcConfigResponse(**config.to_dict())


class VpcSubnetDetail(BaseModel):
    """Enriched subnet info from EC2 DescribeSubnets."""
    subnet_id: str
    availability_zone: str | None
    availability_zone_id: str | None
    cidr_block: str | None
    available_ips: int | None
    name: str | None


class VpcSgRuleDetail(BaseModel):
    """A single inbound or outbound security group rule."""
    protocol: str
    from_port: int | None
    to_port: int | None
    cidr: str | None
    source_sg_id: str | None
    source_sg_name: str | None
    description: str | None


class VpcSgDetail(BaseModel):
    """Enriched security group info from EC2 DescribeSecurityGroups."""
    sg_id: str
    name: str | None
    ingress: list[VpcSgRuleDetail]
    egress: list[VpcSgRuleDetail]


class VpcConfigDetailResponse(BaseModel):
    """Enriched VPC configuration with live EC2 metadata."""
    id: int
    name: str
    description: str | None
    vpc_id: str
    subnets: list[VpcSubnetDetail]
    security_groups: list[VpcSgDetail]


def _parse_sg_rules(ip_permissions: list[dict]) -> list[VpcSgRuleDetail]:
    rules: list[VpcSgRuleDetail] = []
    for perm in ip_permissions:
        protocol = perm.get("IpProtocol", "-1")
        if protocol == "-1":
            protocol = "All"
        from_port = perm.get("FromPort")
        to_port = perm.get("ToPort")
        description_base = None

        for ip_range in perm.get("IpRanges", []):
            rules.append(VpcSgRuleDetail(
                protocol=protocol,
                from_port=from_port,
                to_port=to_port,
                cidr=ip_range.get("CidrIp"),
                source_sg_id=None,
                source_sg_name=None,
                description=ip_range.get("Description") or description_base,
            ))
        for sg_ref in perm.get("UserIdGroupPairs", []):
            rules.append(VpcSgRuleDetail(
                protocol=protocol,
                from_port=from_port,
                to_port=to_port,
                cidr=None,
                source_sg_id=sg_ref.get("GroupId"),
                source_sg_name=sg_ref.get("GroupName"),
                description=sg_ref.get("Description") or description_base,
            ))
        if not perm.get("IpRanges") and not perm.get("UserIdGroupPairs"):
            rules.append(VpcSgRuleDetail(
                protocol=protocol,
                from_port=from_port,
                to_port=to_port,
                cidr=None,
                source_sg_id=None,
                source_sg_name=None,
                description=description_base,
            ))
    return rules


@router.get("/vpc-configs/{config_id}/detail", response_model=VpcConfigDetailResponse)
def get_vpc_config_detail(
    config_id: int,
    user: UserInfo = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VpcConfigDetailResponse:
    """Return a VPC configuration enriched with live EC2 subnet and security group metadata."""
    import boto3
    import os

    config = db.query(VpcConfig).filter(VpcConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VPC configuration not found")

    region = os.getenv("AWS_REGION", "us-east-1")
    ec2 = boto3.client("ec2", region_name=region)

    subnet_ids = config.get_subnet_ids()
    sg_ids = config.get_sg_ids()

    subnets: list[VpcSubnetDetail] = []
    if subnet_ids:
        try:
            resp = ec2.describe_subnets(SubnetIds=subnet_ids)
            subnet_map = {s["SubnetId"]: s for s in resp.get("Subnets", [])}
        except Exception:
            subnet_map = {}
        for sid in subnet_ids:
            s = subnet_map.get(sid, {})
            name_tag = next((t["Value"] for t in s.get("Tags", []) if t["Key"] == "Name"), None)
            subnets.append(VpcSubnetDetail(
                subnet_id=sid,
                availability_zone=s.get("AvailabilityZone"),
                availability_zone_id=s.get("AvailabilityZoneId"),
                cidr_block=s.get("CidrBlock"),
                available_ips=s.get("AvailableIpAddressCount"),
                name=name_tag,
            ))

    security_groups: list[VpcSgDetail] = []
    if sg_ids:
        try:
            resp = ec2.describe_security_groups(GroupIds=sg_ids)
            sg_map = {g["GroupId"]: g for g in resp.get("SecurityGroups", [])}
        except Exception:
            sg_map = {}
        for sgid in sg_ids:
            g = sg_map.get(sgid, {})
            security_groups.append(VpcSgDetail(
                sg_id=sgid,
                name=g.get("GroupName"),
                ingress=_parse_sg_rules(g.get("IpPermissions", [])),
                egress=_parse_sg_rules(g.get("IpPermissionsEgress", [])),
            ))

    return VpcConfigDetailResponse(
        id=config.id,
        name=config.name,
        description=config.description,
        vpc_id=config.vpc_id,
        subnets=subnets,
        security_groups=security_groups,
    )


@router.delete("/vpc-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vpc_config(
    config_id: int,
    user: UserInfo = Depends(require_scopes("settings:write")),
    db: Session = Depends(get_db),
) -> None:
    """Delete a VPC configuration."""
    config = db.query(VpcConfig).filter(VpcConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VPC configuration not found")
    db.delete(config)
    db.commit()
