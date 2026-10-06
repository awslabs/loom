"""AgentKillSwitchEvent ORM model: the audit trail of every agent Stop and Resume."""
import json
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db import Base


class AgentKillSwitchEvent(Base):
    """One Stop or Resume of one agent, with who, when, why and the AWS request ids.

    ``agent_id`` is deliberately a plain column, not a foreign key: the history
    of a stop has to survive the deletion of the agent it describes, so a
    post-mortem can still read it.
    """
    __tablename__ = "agent_kill_switch_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, nullable=False, index=True)
    agent_name = Column(String, nullable=True)
    agent_arn = Column(String, nullable=True)
    action = Column(String, nullable=False)  # "stop" | "resume"
    reason = Column(Text, nullable=False)
    actor = Column(String, nullable=False)
    role_arn = Column(String, nullable=False)
    policy_arn = Column(String, nullable=False)
    # What the action did to the role: "attached", "already_attached",
    # "detached" or "already_detached".
    iam_change = Column(String, nullable=False)
    iam_request_id = Column(String, nullable=True)
    sessions = Column(Text, nullable=True)  # JSON list of per-session stop results
    shared_with = Column(Text, nullable=True)  # JSON list of other agent ids on the same role
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    def get_sessions(self) -> list[dict]:
        if not self.sessions:
            return []
        try:
            return json.loads(self.sessions)
        except json.JSONDecodeError:
            return []

    def get_shared_with(self) -> list[int]:
        if not self.shared_with:
            return []
        try:
            return json.loads(self.shared_with)
        except json.JSONDecodeError:
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "action": self.action,
            "reason": self.reason,
            "actor": self.actor,
            "role_arn": self.role_arn,
            "policy_arn": self.policy_arn,
            "iam_change": self.iam_change,
            "iam_request_id": self.iam_request_id,
            "sessions": self.get_sessions(),
            "shared_with": self.get_shared_with(),
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
        }
