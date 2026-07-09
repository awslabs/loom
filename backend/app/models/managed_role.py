import json
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.db import Base


class ManagedRole(Base):
    __tablename__ = "managed_roles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    role_name = Column(String, nullable=False)
    role_arn = Column(String, nullable=False, unique=True)
    role_type = Column(String, nullable=False, default="agent")  # "agent" or "code_interpreter"
    description = Column(Text, default="")
    policy_document = Column(Text, default="{}")  # JSON string
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
            "role_name": self.role_name,
            "role_arn": self.role_arn,
            "role_type": self.role_type or "agent",
            "description": self.description,
            "policy_document": json.loads(self.policy_document) if self.policy_document else {},
            "tags": self.get_tags(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
