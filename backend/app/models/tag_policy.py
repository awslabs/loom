"""TagPolicy ORM model for configurable resource tagging rules."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.db import Base


class TagPolicy(Base):
    """Defines a tag key that should be applied to AWS resources managed by Loom."""
    __tablename__ = "tag_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False)
    default_value = Column(String, nullable=True)
    source = Column(String, nullable=True, default="")  # deprecated, kept for DB compat
    required = Column(Boolean, nullable=False, default=True)
    show_on_card = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def designation(self) -> str:
        """Computed designation based on required flag."""
        if self.required:
            return "platform:required"
        return "custom:optional"

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "key": self.key,
            "default_value": self.default_value,
            "designation": self.designation,
            "required": self.required,
            "show_on_card": self.show_on_card,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
