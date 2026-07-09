"""SiteSetting ORM model for configurable key-value settings."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.db import Base


class SiteSetting(Base):
    """Key-value store for site-wide configuration settings."""
    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime, nullable=True, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "updated_at": (self.updated_at.isoformat() + "Z") if self.updated_at else None,
        }
