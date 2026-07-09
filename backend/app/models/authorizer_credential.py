from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.db import Base


class AuthorizerCredential(Base):
    __tablename__ = "authorizer_credentials"
    id = Column(Integer, primary_key=True, autoincrement=True)
    authorizer_config_id = Column(Integer, ForeignKey("authorizer_configs.id"), nullable=False)
    label = Column(String, nullable=False)
    client_id = Column(String, nullable=False)
    client_secret_arn = Column(String, nullable=True)  # ARN in Secrets Manager
    created_at = Column(DateTime, server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "authorizer_config_id": self.authorizer_config_id,
            "label": self.label,
            "client_id": self.client_id,
            "has_secret": bool(self.client_secret_arn),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
