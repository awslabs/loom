"""Security management endpoints for roles, authorizers, and permission requests."""
import json
import logging
import os
from typing import Any

import boto3

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, get_current_user, require_scopes
from app.models.managed_role import ManagedRole
from app.models.authorizer_config import AuthorizerConfig
from app.models.authorizer_credential import AuthorizerCredential
from app.models.permission_request import PermissionRequest
from app.models.agent import Agent
from app.services.security import (
    apply_permissions_to_role,
    create_iam_role_with_policy,
    delete_iam_role,
    get_role_policy_details,
    update_iam_role_policy,
)
from app.services.secrets import store_secret, get_secret, delete_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/security", tags=["security"])

DEFAULT_REGION = os.getenv("AWS_REGION", "us-east-1")


def _get_region() -> str:
    return os.getenv("AWS_REGION", DEFAULT_REGION)


def _get_account_id() -> str:
    return os.getenv("AWS_ACCOUNT_ID", "")


def _get_user_group(user: UserInfo) -> str | None:
    """Extract the loom:group value from user's Cognito groups (e.g. 'demo' from 'g-users-demo')."""
    for group in user.groups:
        if group.startswith("g-users-"):
            return group[len("g-users-"):]
    return None


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------
class CreateRoleRequest(BaseModel):
    mode: str = Field(..., description="'import' or 'wizard'")
    role_arn: str | None = Field(None, description="Existing role ARN (import mode)")
    role_name: str | None = Field(None, description="New role name (wizard mode)")
    role_type: str = Field(default="agent", description="Role type: 'agent' or 'code_interpreter'")
    description: str = Field(default="", description="Role description")
    policy_document: dict = Field(default_factory=dict, description="IAM policy document (wizard mode)")
    tags: dict[str, str] | None = Field(None, description="Tags to apply (merged with AWS IAM tags on import)")


class UpdateRoleRequest(BaseModel):
    description: str | None = None
    policy_document: dict | None = None


class CreateAuthorizerRequest(BaseModel):
    name: str
    authorizer_type: str  # "cognito" or "other"
    pool_id: str | None = None
    discovery_url: str | None = None
    allowed_audience: list[str] = Field(default_factory=list)
    allowed_clients: list[str] = Field(default_factory=list)
    allowed_scopes: list[str] = Field(default_factory=list)
    client_id: str | None = None
    client_secret: str | None = None
    user_client_id: str | None = None
    user_client_secret: str | None = None
    user_redirect_uri: str | None = None


class UpdateAuthorizerRequest(BaseModel):
    name: str | None = None
    authorizer_type: str | None = None
    pool_id: str | None = None
    discovery_url: str | None = None
    allowed_audience: list[str] | None = None
    allowed_clients: list[str] | None = None
    allowed_scopes: list[str] | None = None
    client_id: str | None = None
    client_secret: str | None = None
    user_client_id: str | None = None
    user_client_secret: str | None = None
    user_redirect_uri: str | None = None


class LinkCallbackRequest(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str


class CreatePermissionRequestBody(BaseModel):
    managed_role_id: int
    requested_actions: list[str]
    requested_resources: list[str]
    justification: str


class ReviewPermissionRequestBody(BaseModel):
    status: str  # "approved" or "denied"
    reviewer_notes: str | None = None


# ---------------------------------------------------------------------------
# Managed Roles
# ---------------------------------------------------------------------------
@router.post("/roles", status_code=status.HTTP_201_CREATED)
def create_role(request: CreateRoleRequest, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)) -> dict:
    """Create or import a managed role."""
    region = _get_region()
    account_id = _get_account_id()

    if request.mode == "import":
        if not request.role_arn:
            raise HTTPException(status_code=400, detail="role_arn is required for import mode")

        # Check for duplicate
        existing = db.query(ManagedRole).filter(ManagedRole.role_arn == request.role_arn).first()
        if existing:
            raise HTTPException(status_code=409, detail="Role ARN already managed")

        # Extract role name from ARN
        role_name = request.role_arn.split("/")[-1]

        # Fetch existing policy from AWS
        try:
            policy_details = get_role_policy_details(role_name, region)
            policy_doc = {"Version": "2012-10-17", "Statement": policy_details["statements"]}
        except Exception as e:
            logger.warning("Could not fetch policy for %s: %s", role_name, e)
            policy_doc = {}

        # Fetch tags from AWS IAM, then merge with any provided tags (provided take precedence)
        tags: dict[str, str] = {}
        try:
            iam_client = boto3.client("iam", region_name=region)
            response = iam_client.list_role_tags(RoleName=role_name)
            for tag in response.get("Tags", []):
                tags[tag["Key"]] = tag["Value"]
        except Exception as e:
            logger.warning("Could not fetch tags for role %s: %s", role_name, e)
        if request.tags:
            tags.update(request.tags)

        role = ManagedRole(
            role_name=role_name,
            role_arn=request.role_arn,
            role_type=request.role_type,
            description=request.description,
            policy_document=json.dumps(policy_doc),
        )
        role.set_tags(tags)
        db.add(role)
        db.commit()
        db.refresh(role)
        return role.to_dict()

    elif request.mode == "wizard":
        if not request.role_name:
            raise HTTPException(status_code=400, detail="role_name is required for wizard mode")

        try:
            role_arn = create_iam_role_with_policy(
                role_name=request.role_name,
                policy_document=request.policy_document,
                region=region,
                account_id=account_id,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to create IAM role: {e}")

        role = ManagedRole(
            role_name=request.role_name,
            role_arn=role_arn,
            role_type=request.role_type,
            description=request.description,
            policy_document=json.dumps(request.policy_document),
        )
        db.add(role)
        db.commit()
        db.refresh(role)
        return role.to_dict()

    else:
        raise HTTPException(status_code=400, detail="mode must be 'import' or 'wizard'")


@router.get("/roles")
def list_roles(user: UserInfo = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    """List managed roles. security:read returns all; agent:write returns group-filtered roles."""
    if "security:read" in user.scopes:
        roles = db.query(ManagedRole).order_by(ManagedRole.id).all()
    elif "agent:write" in user.scopes:
        user_group = _get_user_group(user)
        all_roles = db.query(ManagedRole).order_by(ManagedRole.id).all()
        roles = [r for r in all_roles if r.get_tags().get("loom:group") == user_group] if user_group else []
    else:
        raise HTTPException(status_code=403, detail="Missing required scope: security:read or agent:write")
    return [r.to_dict() for r in roles]


@router.get("/roles/{role_id}")
def get_role(role_id: int, user: UserInfo = Depends(require_scopes("security:read")), db: Session = Depends(get_db)) -> dict:
    """Get a managed role with its policy details."""
    role = db.query(ManagedRole).filter(ManagedRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    result = role.to_dict()

    # Try to fetch live policy from AWS
    region = _get_region()
    try:
        live_policy = get_role_policy_details(role.role_name, region)
        result["live_policy"] = live_policy
    except Exception:
        result["live_policy"] = None

    return result


@router.put("/roles/{role_id}")
def update_role(role_id: int, request: UpdateRoleRequest, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)) -> dict:
    """Update a managed role's description and/or policy."""
    role = db.query(ManagedRole).filter(ManagedRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if request.description is not None:
        role.description = request.description

    if request.policy_document is not None:
        region = _get_region()
        try:
            update_iam_role_policy(role.role_name, request.policy_document, region)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to update IAM policy: {e}")
        role.policy_document = json.dumps(request.policy_document)

    db.commit()
    db.refresh(role)
    return role.to_dict()


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: int, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)) -> None:
    """Delete a managed role. Refuses if any agent uses it."""
    role = db.query(ManagedRole).filter(ManagedRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Check if any agent references this role
    agent_using = db.query(Agent).filter(Agent.execution_role_arn == role.role_arn).first()
    if agent_using:
        raise HTTPException(
            status_code=409,
            detail=f"Role is in use by agent '{agent_using.name}' (id={agent_using.id})",
        )

    db.delete(role)
    db.commit()


# ---------------------------------------------------------------------------
# Cognito Pools (discovery)
# ---------------------------------------------------------------------------
@router.get("/cognito-pools")
def list_cognito_pools(user: UserInfo = Depends(require_scopes("security:read"))) -> list[dict]:
    """List available Cognito User Pools in the current region."""
    region = _get_region()
    client = boto3.client("cognito-idp", region_name=region)
    pools: list[dict] = []

    paginator = client.get_paginator("list_user_pools")
    for page in paginator.paginate(MaxResults=60):
        for pool in page.get("UserPools", []):
            pool_id = pool["Id"]
            pool_name = pool["Name"]
            discovery_url = (
                f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
                "/.well-known/openid-configuration"
            )
            pools.append({
                "pool_id": pool_id,
                "pool_name": pool_name,
                "discovery_url": discovery_url,
            })

    return pools


# ---------------------------------------------------------------------------
# Authorizer Configs
# ---------------------------------------------------------------------------
@router.post("/authorizers", status_code=status.HTTP_201_CREATED)
def create_authorizer(request: CreateAuthorizerRequest, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)) -> dict:
    """Create an authorizer configuration."""
    existing = db.query(AuthorizerConfig).filter(AuthorizerConfig.name == request.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Authorizer with this name already exists")

    client_secret_arn = None
    if request.client_secret:
        region = _get_region()
        secret_name = f"loom/authorizers/{request.name}/client-secret"
        try:
            client_secret_arn = store_secret(
                name=secret_name,
                secret_value=request.client_secret,
                region=region,
                description=f"Client secret for Loom authorizer '{request.name}'",
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to store client secret: {e}")

    # Fetch tags from the Cognito User Pool if applicable
    tags: dict[str, str] = {}
    if request.authorizer_type == "cognito" and request.pool_id:
        try:
            region = _get_region()
            cognito_client = boto3.client("cognito-idp", region_name=region)
            pool_info = cognito_client.describe_user_pool(UserPoolId=request.pool_id)
            raw_tags = pool_info.get("UserPool", {}).get("UserPoolTags", {})
            tags = {k: v for k, v in raw_tags.items()}
        except Exception as e:
            logger.warning("Could not fetch tags for Cognito pool %s: %s", request.pool_id, e)

    user_client_secret_arn = None
    if request.user_client_secret:
        region = _get_region()
        user_secret_name = f"loom/authorizers/{request.name}/user-client-secret"
        try:
            user_client_secret_arn = store_secret(
                name=user_secret_name,
                secret_value=request.user_client_secret,
                region=region,
                description=f"User client secret for Loom authorizer '{request.name}'",
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to store user client secret: {e}")

    auth = AuthorizerConfig(
        name=request.name,
        authorizer_type=request.authorizer_type,
        pool_id=request.pool_id,
        discovery_url=request.discovery_url,
        allowed_audience=json.dumps(request.allowed_audience),
        allowed_clients=json.dumps(request.allowed_clients),
        allowed_scopes=json.dumps(request.allowed_scopes),
        client_id=request.client_id,
        client_secret_arn=client_secret_arn,
        user_client_id=request.user_client_id,
        user_client_secret_arn=user_client_secret_arn,
        user_redirect_uri=request.user_redirect_uri,
    )
    auth.set_tags(tags)
    db.add(auth)
    db.commit()
    db.refresh(auth)
    return auth.to_dict()


@router.get("/authorizers")
def list_authorizers(user: UserInfo = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    """List all authorizer configurations. Requires security:read, agent:write, or agent:read."""
    if "security:read" not in user.scopes and "agent:write" not in user.scopes and "agent:read" not in user.scopes:
        raise HTTPException(status_code=403, detail="Missing required scope: security:read, agent:write, or agent:read")
    auths = db.query(AuthorizerConfig).order_by(AuthorizerConfig.id).all()
    return [a.to_dict() for a in auths]


@router.get("/authorizers/{auth_id}")
def get_authorizer(auth_id: int, user: UserInfo = Depends(require_scopes("security:read")), db: Session = Depends(get_db)) -> dict:
    """Get an authorizer configuration."""
    auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == auth_id).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorizer not found")
    return auth.to_dict()


@router.put("/authorizers/{auth_id}")
def update_authorizer(
    auth_id: int, request: UpdateAuthorizerRequest, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)
) -> dict:
    """Update an authorizer configuration."""
    auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == auth_id).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorizer not found")

    if request.name is not None:
        auth.name = request.name
    if request.authorizer_type is not None:
        auth.authorizer_type = request.authorizer_type
    if request.pool_id is not None:
        auth.pool_id = request.pool_id
    if request.discovery_url is not None:
        auth.discovery_url = request.discovery_url
    if request.allowed_audience is not None:
        auth.allowed_audience = json.dumps(request.allowed_audience)
    if request.allowed_clients is not None:
        auth.allowed_clients = json.dumps(request.allowed_clients)
    if request.allowed_scopes is not None:
        auth.allowed_scopes = json.dumps(request.allowed_scopes)
    if request.client_id is not None:
        auth.client_id = request.client_id
    if request.client_secret is not None:
        region = _get_region()
        secret_name = f"loom/authorizers/{auth.name}/client-secret"
        try:
            client_secret_arn = store_secret(
                name=secret_name,
                secret_value=request.client_secret,
                region=region,
                description=f"Client secret for Loom authorizer '{auth.name}'",
            )
            auth.client_secret_arn = client_secret_arn
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to store client secret: {e}")
    if request.user_client_id is not None:
        auth.user_client_id = request.user_client_id
    if request.user_redirect_uri is not None:
        auth.user_redirect_uri = request.user_redirect_uri
    if request.user_client_secret is not None:
        region = _get_region()
        user_secret_name = f"loom/authorizers/{auth.name}/user-client-secret"
        try:
            user_client_secret_arn = store_secret(
                name=user_secret_name,
                secret_value=request.user_client_secret,
                region=region,
                description=f"User client secret for Loom authorizer '{auth.name}'",
            )
            auth.user_client_secret_arn = user_client_secret_arn
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to store user client secret: {e}")

    db.commit()
    db.refresh(auth)
    return auth.to_dict()


@router.delete("/authorizers/{auth_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_authorizer(auth_id: int, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)) -> None:
    """Delete an authorizer configuration and its credentials."""
    auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == auth_id).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorizer not found")

    region = _get_region()

    # Clean up secrets for child credentials
    creds = db.query(AuthorizerCredential).filter(
        AuthorizerCredential.authorizer_config_id == auth_id
    ).all()
    for cred in creds:
        if cred.client_secret_arn:
            delete_secret(cred.client_secret_arn, region)

    # Bulk-delete credentials before the parent to satisfy FK constraint
    db.query(AuthorizerCredential).filter(
        AuthorizerCredential.authorizer_config_id == auth_id
    ).delete(synchronize_session="fetch")

    if auth.client_secret_arn:
        delete_secret(auth.client_secret_arn, region)
    if auth.user_client_secret_arn:
        delete_secret(auth.user_client_secret_arn, region)

    db.delete(auth)
    db.commit()


# ---------------------------------------------------------------------------
# Authorizer Credentials
# ---------------------------------------------------------------------------
class CreateCredentialRequest(BaseModel):
    label: str
    client_id: str
    client_secret: str | None = None


@router.post("/authorizers/{auth_id}/credentials", status_code=status.HTTP_201_CREATED)
def create_credential(auth_id: int, request: CreateCredentialRequest, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)) -> dict:
    """Add a client credential to an authorizer configuration."""
    auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == auth_id).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorizer not found")

    client_secret_arn = None
    if request.client_secret:
        region = _get_region()
        secret_name = f"loom/authorizers/{auth.name}/credentials/{request.label}"
        try:
            client_secret_arn = store_secret(
                name=secret_name,
                secret_value=request.client_secret,
                region=region,
                description=f"Client secret for credential '{request.label}' on authorizer '{auth.name}'",
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to store client secret: {e}")

    cred = AuthorizerCredential(
        authorizer_config_id=auth_id,
        label=request.label,
        client_id=request.client_id,
        client_secret_arn=client_secret_arn,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred.to_dict()


@router.get("/authorizers/{auth_id}/credentials")
def list_credentials(auth_id: int, user: UserInfo = Depends(require_scopes("security:read")), db: Session = Depends(get_db)) -> list[dict]:
    """List credentials for an authorizer."""
    creds = db.query(AuthorizerCredential).filter(
        AuthorizerCredential.authorizer_config_id == auth_id
    ).order_by(AuthorizerCredential.id).all()
    return [c.to_dict() for c in creds]


@router.delete("/authorizers/{auth_id}/credentials/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(auth_id: int, cred_id: int, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)) -> None:
    """Delete a credential from an authorizer."""
    cred = db.query(AuthorizerCredential).filter(
        AuthorizerCredential.id == cred_id,
        AuthorizerCredential.authorizer_config_id == auth_id,
    ).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    if cred.client_secret_arn:
        region = _get_region()
        delete_secret(cred.client_secret_arn, region)
    db.delete(cred)
    db.commit()


@router.post("/authorizers/{auth_id}/credentials/{cred_id}/token")
def get_credential_token(auth_id: int, cred_id: int, user: UserInfo = Depends(require_scopes("security:read")), db: Session = Depends(get_db)) -> dict:
    """Generate an access token using a credential's client_id and client_secret."""
    auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == auth_id).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorizer not found")

    cred = db.query(AuthorizerCredential).filter(
        AuthorizerCredential.id == cred_id,
        AuthorizerCredential.authorizer_config_id == auth_id,
    ).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    if not cred.client_secret_arn:
        raise HTTPException(status_code=400, detail="Credential has no client secret stored")

    region = _get_region()
    allowed_scopes = json.loads(auth.allowed_scopes) if auth.allowed_scopes else None

    try:
        client_secret = get_secret(cred.client_secret_arn, region)

        if auth.authorizer_type == "cognito" and auth.pool_id:
            from app.services.cognito import get_cognito_token
            token_response = get_cognito_token(
                pool_id=auth.pool_id,
                client_id=cred.client_id,
                client_secret=client_secret,
                scopes=allowed_scopes or None,
            )
        elif auth.discovery_url:
            from app.services.token import get_oauth2_token
            token_response = get_oauth2_token(
                discovery_url=auth.discovery_url,
                client_id=cred.client_id,
                client_secret=client_secret,
                scopes=allowed_scopes or None,
            )
        else:
            raise HTTPException(status_code=400, detail="Authorizer has no Cognito pool or discovery URL configured")

        return {
            "access_token": token_response["access_token"],
            "token_type": token_response.get("token_type", "Bearer"),
            "expires_in": token_response.get("expires_in"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to get token: {e}")


# ---------------------------------------------------------------------------
# Authorizer Linking (per-user cross-IdP token storage)
# ---------------------------------------------------------------------------
@router.get("/authorizers/{auth_id}/link/status")
def get_link_status(auth_id: int, user: UserInfo = Depends(require_scopes("agent:read")), db: Session = Depends(get_db)) -> dict:
    """Check if the current user has linked their account to this authorizer."""
    from app.services.authorizer_linking import check_link_status
    auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == auth_id).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorizer not found")
    linkable = bool(auth.user_client_id and auth.discovery_url)
    if not linkable:
        return {"linked": False, "linkable": False}
    region = _get_region()
    linked = check_link_status(auth_id, user.sub, region)
    return {"linked": linked, "linkable": True}


@router.get("/authorizers/{auth_id}/link/authorize")
def get_link_authorize_url(auth_id: int, request: Request, user: UserInfo = Depends(require_scopes("agent:read")), db: Session = Depends(get_db)) -> dict:
    """Return the authorization URL for the user to link their account via OAuth popup."""
    from app.services.oidc import fetch_discovery
    auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == auth_id).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorizer not found")
    if not auth.user_client_id or not auth.discovery_url:
        raise HTTPException(status_code=400, detail="Authorizer not configured for user linking")

    disc = fetch_discovery(auth.discovery_url)
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    if origin:
        redirect_uri = origin.rstrip("/") + "/oauth/link-callback"
    else:
        redirect_uri = auth.user_redirect_uri or ""

    import secrets, hashlib, base64
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)

    scope = "openid"
    params = {
        "response_type": "code",
        "client_id": auth.user_client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "prompt": "login",
    }
    import urllib.parse
    authorize_url = f"{disc['authorization_endpoint']}?{urllib.parse.urlencode(params)}"

    return {
        "authorize_url": authorize_url,
        "code_verifier": code_verifier,
        "state": state,
        "redirect_uri": redirect_uri,
    }


@router.post("/authorizers/{auth_id}/link/callback")
def link_callback(auth_id: int, request: LinkCallbackRequest, user: UserInfo = Depends(require_scopes("agent:read")), db: Session = Depends(get_db)) -> dict:
    """Exchange authorization code for tokens and store the refresh token."""
    from app.services.authorizer_linking import exchange_code_for_tokens, store_user_tokens
    auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == auth_id).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorizer not found")
    if not auth.user_client_id or not auth.discovery_url:
        raise HTTPException(status_code=400, detail="Authorizer not configured for user linking")

    region = _get_region()
    user_client_secret = get_secret(auth.user_client_secret_arn, region) if auth.user_client_secret_arn else None

    try:
        token_response = exchange_code_for_tokens(
            discovery_url=auth.discovery_url,
            user_client_id=auth.user_client_id,
            user_client_secret=user_client_secret,
            code=request.code,
            code_verifier=request.code_verifier,
            redirect_uri=request.redirect_uri,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {e}")

    refresh_token = token_response.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token received; ensure offline_access scope is granted")

    store_user_tokens(auth_id, user.sub, refresh_token, region)
    return {"linked": True}


@router.delete("/authorizers/{auth_id}/link", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(auth_id: int, user: UserInfo = Depends(require_scopes("agent:read")), db: Session = Depends(get_db)) -> None:
    """Remove the current user's linked tokens for this authorizer."""
    from app.services.authorizer_linking import delete_user_tokens
    auth = db.query(AuthorizerConfig).filter(AuthorizerConfig.id == auth_id).first()
    if not auth:
        raise HTTPException(status_code=404, detail="Authorizer not found")
    region = _get_region()
    delete_user_tokens(auth_id, user.sub, region)


# ---------------------------------------------------------------------------
# Permission Requests
# ---------------------------------------------------------------------------
@router.post("/permission-requests", status_code=status.HTTP_201_CREATED)
def create_permission_request(
    request: CreatePermissionRequestBody, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)
) -> dict:
    """Create a new permission request."""
    role = db.query(ManagedRole).filter(ManagedRole.id == request.managed_role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Managed role not found")

    perm_req = PermissionRequest(
        managed_role_id=request.managed_role_id,
        requested_actions=json.dumps(request.requested_actions),
        requested_resources=json.dumps(request.requested_resources),
        justification=request.justification,
    )
    db.add(perm_req)
    db.commit()
    db.refresh(perm_req)
    return perm_req.to_dict()


@router.get("/permission-requests")
def list_permission_requests(
    request_status: str | None = Query(None, alias="status"),
    user: UserInfo = Depends(require_scopes("security:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List permission requests, optionally filtered by status."""
    query = db.query(PermissionRequest)
    if request_status:
        query = query.filter(PermissionRequest.status == request_status)
    requests = query.order_by(PermissionRequest.id.desc()).all()
    return [r.to_dict() for r in requests]


@router.put("/permission-requests/{request_id}")
def review_permission_request(
    request_id: int, body: ReviewPermissionRequestBody, user: UserInfo = Depends(require_scopes("security:write")), db: Session = Depends(get_db)
) -> dict:
    """Approve or deny a permission request."""
    perm_req = db.query(PermissionRequest).filter(PermissionRequest.id == request_id).first()
    if not perm_req:
        raise HTTPException(status_code=404, detail="Permission request not found")

    if perm_req.status != "pending":
        raise HTTPException(status_code=400, detail="Permission request is not pending")

    if body.status not in ("approved", "denied"):
        raise HTTPException(status_code=400, detail="status must be 'approved' or 'denied'")

    perm_req.status = body.status
    perm_req.reviewer_notes = body.reviewer_notes

    if body.status == "approved":
        role = db.query(ManagedRole).filter(ManagedRole.id == perm_req.managed_role_id).first()
        if not role:
            raise HTTPException(status_code=404, detail="Associated managed role not found")

        actions = json.loads(perm_req.requested_actions) if perm_req.requested_actions else []
        resources = json.loads(perm_req.requested_resources) if perm_req.requested_resources else []
        region = _get_region()

        try:
            updated_doc = apply_permissions_to_role(role.role_name, actions, resources, region)
            role.policy_document = json.dumps(updated_doc)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to apply permissions: {e}")

    db.commit()
    db.refresh(perm_req)
    return perm_req.to_dict()
