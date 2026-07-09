"""TagProfile ORM model for named sets of tag values."""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.db import Base


class TagProfile(Base):
    """A named preset of tag key-value pairs that can be applied to any Loom-managed resource."""
    __tablename__ = "tag_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    tags = Column(Text, nullable=False)  # JSON dict of tag key-value pairs
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_tags(self) -> dict[str, str]:
        """Parse tags from JSON text."""
        if not self.tags:
            return {}
        try:
            return json.loads(self.tags)
        except json.JSONDecodeError:
            return {}

    def set_tags(self, tags: dict[str, str]) -> None:
        """Serialize tags to JSON text."""
        self.tags = json.dumps(tags)

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "tags": self.get_tags(),
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }
