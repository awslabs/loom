from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db import Base


class PermissionRequest(Base):
    __tablename__ = "permission_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    managed_role_id = Column(Integer, ForeignKey("managed_roles.id"), nullable=False)
    requested_actions = Column(Text, nullable=False)  # JSON array of AWS actions
    requested_resources = Column(Text, nullable=False)  # JSON array of resource ARNs
    justification = Column(Text, nullable=False)
    status = Column(String, default="pending")  # pending, approved, denied
    reviewer_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    managed_role = relationship("ManagedRole")

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "managed_role_id": self.managed_role_id,
            "role_name": self.managed_role.role_name if self.managed_role else None,
            "role_arn": self.managed_role.role_arn if self.managed_role else None,
            "requested_actions": json.loads(self.requested_actions) if self.requested_actions else [],
            "requested_resources": json.loads(self.requested_resources) if self.requested_resources else [],
            "justification": self.justification,
            "status": self.status,
            "reviewer_notes": self.reviewer_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
