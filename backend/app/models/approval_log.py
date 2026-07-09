from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.db import Base


class ApprovalLog(Base):
    __tablename__ = "approval_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)
    agent_id = Column(Integer, nullable=True, index=True)
    tool_name = Column(String, nullable=False)
    tool_input_summary = Column(Text, nullable=True)
    policy_name = Column(String, nullable=True)
    pattern_type = Column(String, nullable=False)  # loop_hook, tool_context, mcp_elicitation
    status = Column(String, nullable=False, default="pending")  # pending, approved, rejected, timeout
    requested_at = Column(DateTime, server_default=func.now())
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String, nullable=True)
    reason = Column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "tool_input_summary": self.tool_input_summary,
            "policy_name": self.policy_name,
            "pattern_type": self.pattern_type,
            "status": self.status,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decided_by": self.decided_by,
            "reason": self.reason,
        }
