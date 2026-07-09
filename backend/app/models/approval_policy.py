import json

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from app.db import Base


class ApprovalPolicy(Base):
    __tablename__ = "approval_policies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    policy_type = Column(String, nullable=False)  # loop_hook, tool_context, mcp_elicitation
    tool_match_rules = Column(Text, default="[]")  # JSON array of patterns
    approval_mode = Column(String, nullable=False, default="require_approval")  # require_approval, notify_only
    timeout_seconds = Column(Integer, nullable=False, default=300)
    agent_scope = Column(Text, default='{"type": "all"}')  # JSON: {type: "all"} | {type: "specific", agent_ids: [...]} | {type: "tag_filter", tag_key: ..., tag_value: ...}
    approval_cache_ttl = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def get_tool_match_rules(self) -> list[str]:
        if not self.tool_match_rules:
            return []
        return json.loads(self.tool_match_rules)

    def get_agent_scope(self) -> dict:
        if not self.agent_scope:
            return {"type": "all"}
        return json.loads(self.agent_scope)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "policy_type": self.policy_type,
            "tool_match_rules": self.get_tool_match_rules(),
            "approval_mode": self.approval_mode,
            "timeout_seconds": self.timeout_seconds,
            "agent_scope": self.get_agent_scope(),
            "approval_cache_ttl": self.approval_cache_ttl,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
