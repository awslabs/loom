"""Shared utilities for router modules."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.agent import Agent


def get_agent_or_404(agent_id: int, db: Session) -> Agent:
    """Fetch an agent by ID or raise 404."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with ID {agent_id} not found"
        )
    return agent
