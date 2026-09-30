import json

from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime
from sqlalchemy.sql import func
from app.db import Base


class UsageLimit(Base):
    __tablename__ = "usage_limits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    # No default here on purpose — unlike target, "who does this apply to" should
    # never be left implicit. Force whoever creates a limit to say so explicitly.
    scope = Column(Text, nullable=False)  # JSON: {type: "user", username: ...} | {type: "group", group: ...}
    target = Column(Text, default='{"type": "all"}')  # JSON: {type: "all"} | {type: "model", model_id: ...} | {type: "family", family: ...}
    measure = Column(String, nullable=False)  # tokens, budget
    threshold = Column(Float, nullable=False)
    window = Column(String, nullable=False, default="daily")  # daily, weekly, monthly, rolling
    enforcement = Column(String, nullable=False, default="warn")  # warn, throttle, block
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    cached_usage = Column(Float, nullable=True)
    cached_usage_updated_at = Column(DateTime, nullable=True)

    def get_scope(self) -> dict:
        # Should never actually be empty since scope is NOT NULL, but keep the
        # same defensive fallback pattern the rest of the models use.
        if not self.scope:
            return {}
        return json.loads(self.scope)

    def get_target(self) -> dict:
        if not self.target:
            return {"type": "all"}
        return json.loads(self.target)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.get_scope(),
            "target": self.get_target(),
            "measure": self.measure,
            "threshold": self.threshold,
            "window": self.window,
            "enforcement": self.enforcement,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "cached_usage": self.cached_usage,
            "cached_usage_updated_at": self.cached_usage_updated_at.isoformat() if self.cached_usage_updated_at else None,
        }
