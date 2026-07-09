"""InvocationSession ORM model for storing session containers."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class InvocationSession(Base):
    """
    Represents a session container for multiple agent invocations.

    A session groups related invocations together and tracks the overall session status.
    """
    __tablename__ = "invocation_sessions"

    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, primary_key=True)
    qualifier = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending, streaming, complete, error
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    user_id = Column(String, nullable=True, index=True)
    hidden_at = Column(DateTime, nullable=True)  # Set when user hides the session from their view

    # Relationships
    agent = relationship("Agent", back_populates="sessions")
    invocations = relationship("Invocation", back_populates="session", cascade="all, delete-orphan", order_by="Invocation.created_at")

    def to_dict(self) -> dict:
        """Convert session to dictionary for API responses."""
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "qualifier": self.qualifier,
            "status": self.status,
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
            "user_id": self.user_id,
            "hidden_at": (self.hidden_at.isoformat() + "Z") if self.hidden_at else None,
            "invocations": [inv.to_dict() for inv in self.invocations] if self.invocations else [],
        }
