"""AgentKillSwitchEvent ORM model: the audit trail of every agent Stop and Resume."""
import json
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db import Base


class AgentKillSwitchEvent(Base):
    """One Stop or Resume of one agent, with who, when, why and the AWS request id.

    ``agent_id`` is deliberately a plain column, not a foreign key: the history
    of a stop has to survive the deletion of the agent it describes, so a
    post-mortem can still read it.
    """
    __tablename__ = "agent_kill_switch_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, nullable=False, index=True)
    agent_name = Column(String, nullable=True)
    runtime_arn = Column(String, nullable=False)
    action = Column(String, nullable=False)  # "stop" | "resume"
    reason = Column(Text, nullable=False)
    actor = Column(String, nullable=False)
    # What the action did to the runtime's resource policy: "deny_added",
    # "already_denied", "deny_removed" or "already_removed".
    policy_change = Column(String, nullable=False)
    request_id = Column(String, nullable=True)  # AgentCore request id of the policy write
    sessions = Column(Text, nullable=True)  # JSON list of per-session stop results
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    def get_sessions(self) -> list[dict]:
        if not self.sessions:
            return []
        try:
            return json.loads(self.sessions)
        except json.JSONDecodeError:
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "runtime_arn": self.runtime_arn,
            "action": self.action,
            "reason": self.reason,
            "actor": self.actor,
            "policy_change": self.policy_change,
            "request_id": self.request_id,
            "sessions": self.get_sessions(),
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
        }
