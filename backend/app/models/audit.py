"""Audit ORM models for tracking user logins, actions, and page views."""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.db import Base


class AuditLogin(Base):
    __tablename__ = "audit_login"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    browser_session_id = Column(String, nullable=False)
    logged_in_at = Column(DateTime, nullable=False, server_default=func.now())


class AuditAction(Base):
    __tablename__ = "audit_action"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    browser_session_id = Column(String, nullable=False)
    action_category = Column(String, nullable=False)
    action_type = Column(String, nullable=False)
    resource_name = Column(String, nullable=True)
    performed_at = Column(DateTime, nullable=False, server_default=func.now())


class AuditPageView(Base):
    __tablename__ = "audit_page_view"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    browser_session_id = Column(String, nullable=False)
    page_name = Column(String, nullable=False)
    entered_at = Column(DateTime, nullable=False)
    duration_seconds = Column(Integer, nullable=True)
