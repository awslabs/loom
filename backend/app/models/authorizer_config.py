import json

from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.db import Base


class AuthorizerConfig(Base):
    __tablename__ = "authorizer_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    authorizer_type = Column(String, nullable=False)  # "cognito" or "other"
    pool_id = Column(String, nullable=True)
    discovery_url = Column(String, nullable=True)
    allowed_audience = Column(Text, default="[]")  # JSON array
    allowed_clients = Column(Text, default="[]")  # JSON array
    allowed_scopes = Column(Text, default="[]")  # JSON array
    client_id = Column(String, nullable=True)
    client_secret_arn = Column(String, nullable=True)  # ARN in Secrets Manager
    user_client_id = Column(String, nullable=True)
    user_client_secret_arn = Column(String, nullable=True)
    user_redirect_uri = Column(String, nullable=True)
    tags = Column(Text, nullable=True)  # JSON dict
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def get_tags(self) -> dict[str, str]:
        if not self.tags:
            return {}
        return json.loads(self.tags)

    def set_tags(self, tags: dict[str, str]) -> None:
        self.tags = json.dumps(tags)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "authorizer_type": self.authorizer_type,
            "pool_id": self.pool_id,
            "discovery_url": self.discovery_url,
            "allowed_audience": json.loads(self.allowed_audience) if self.allowed_audience else [],
            "allowed_clients": json.loads(self.allowed_clients) if self.allowed_clients else [],
            "allowed_scopes": json.loads(self.allowed_scopes) if self.allowed_scopes else [],
            "client_id": self.client_id,
            "has_client_secret": bool(self.client_secret_arn),
            "user_client_id": self.user_client_id,
            "has_user_client_secret": bool(self.user_client_secret_arn),
            "user_redirect_uri": self.user_redirect_uri,
            "tags": self.get_tags(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
