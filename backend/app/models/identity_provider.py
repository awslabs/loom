import json
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.db import Base


class IdentityProvider(Base):
    __tablename__ = "identity_providers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    provider_type = Column(String, nullable=False)  # "cognito", "entra_id", "okta", "auth0", "generic_oidc"
    issuer_url = Column(String, nullable=False)  # OIDC issuer base URL
    client_id = Column(String, nullable=False)
    client_secret_arn = Column(String, nullable=True)  # Secrets Manager ARN (write-only)
    client_type = Column(String, nullable=True, default="public")  # "public" or "confidential"
    scopes = Column(String, nullable=True)  # space-separated scopes to request
    audience = Column(String, nullable=True)  # expected aud claim (if different from client_id)
    group_claim_path = Column(String, nullable=True)  # claim path for groups: "cognito:groups", "groups", "roles"
    group_mappings = Column(Text, nullable=True)  # JSON: {"ExternalGroup": ["t-admin", "g-admins-super"], ...}
    status = Column(String, nullable=False, default="active")  # "active" or "inactive"
    # Cached OIDC discovery metadata
    jwks_uri = Column(String, nullable=True)
    authorization_endpoint = Column(String, nullable=True)
    token_endpoint = Column(String, nullable=True)
    discovery_scopes = Column(Text, nullable=True)  # JSON array of supported scopes from discovery
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def get_group_mappings(self) -> dict[str, list[str]]:
        if not self.group_mappings:
            return {}
        return json.loads(self.group_mappings)

    def set_group_mappings(self, mappings: dict[str, list[str]]) -> None:
        self.group_mappings = json.dumps(mappings)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider_type": self.provider_type,
            "issuer_url": self.issuer_url,
            "client_id": self.client_id,
            "has_client_secret": bool(self.client_secret_arn),
            "client_type": self.client_type or ("confidential" if self.client_secret_arn else "public"),
            "scopes": self.scopes,
            "audience": self.audience,
            "group_claim_path": self.group_claim_path,
            "group_mappings": self.get_group_mappings(),
            "status": self.status,
            "jwks_uri": self.jwks_uri,
            "authorization_endpoint": self.authorization_endpoint,
            "token_endpoint": self.token_endpoint,
            "discovery_scopes": json.loads(self.discovery_scopes) if self.discovery_scopes else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
