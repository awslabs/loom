"""EvaluationTestCase/EvaluationRun ORM models: a saved, re-runnable test
prompt for an agent, and the results of running it.

Loom doesn't judge anything itself — running a test case invokes the agent,
downloads that session's OTEL spans from CloudWatch, and hands them directly
to AgentCore's on-demand Evaluate API, which does the actual judging
(see app/services/evaluations.py). Unlike AgentCore's batch evaluations,
on-demand evaluation has no persisted AWS-side resource to re-query later —
the Evaluate call is synchronous and its result would be gone the moment the
response returns — so EvaluationRun is Loom's own record of each run's
outcome; nothing else keeps it.
"""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base

DEFAULT_PASS_THRESHOLD = 0.7


class EvaluationTestCase(Base):
    """A named prompt + expected-response + evaluator selection for an agent."""
    __tablename__ = "evaluation_test_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    expected_response = Column(Text, nullable=True)
    evaluator_ids = Column(Text, nullable=False, default="[]")  # JSON list of evaluator IDs, e.g. ["Builtin.Helpfulness"]
    pass_threshold = Column(Float, nullable=False, default=DEFAULT_PASS_THRESHOLD)
    model_id = Column(String, nullable=True)  # None = invoke with the agent's own configured model
    # Despite the name, this holds str(EvaluationRun.id) now, not an AWS batch
    # evaluation ID — kept so every existing "has this test case ever run?"
    # check (both here and in the frontend) keeps working unchanged.
    last_batch_evaluation_id = Column(String, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    agent = relationship("Agent", back_populates="evaluation_test_cases")
    runs = relationship("EvaluationRun", back_populates="test_case", cascade="all, delete-orphan",
                        order_by="desc(EvaluationRun.created_at)")

    def get_evaluator_ids(self) -> list[str]:
        try:
            return json.loads(self.evaluator_ids or "[]")
        except json.JSONDecodeError:
            return []

    def set_evaluator_ids(self, ids: list[str]) -> None:
        self.evaluator_ids = json.dumps(ids)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "name": self.name,
            "prompt": self.prompt,
            "expected_response": self.expected_response,
            "evaluator_ids": self.get_evaluator_ids(),
            "pass_threshold": self.pass_threshold,
            "model_id": self.model_id,
            "last_batch_evaluation_id": self.last_batch_evaluation_id,
            "last_run_at": (self.last_run_at.isoformat() + "Z") if self.last_run_at else None,
            "created_at": (self.created_at.isoformat() + "Z") if self.created_at else None,
            "updated_at": (self.updated_at.isoformat() + "Z") if self.updated_at else None,
        }


class EvaluationRun(Base):
    """One on-demand evaluation of a test case's invoked session.

    `status` is "PENDING" while a background task is still waiting for the
    session's spans to become available in CloudWatch (see
    wait_for_session_spans / _background_wait_and_evaluate), "COMPLETED" once
    at least one evaluator produced a score, or "ERROR" if none did.
    """
    __tablename__ = "evaluation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_case_id = Column(Integer, ForeignKey("evaluation_test_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    results_json = Column(Text, nullable=False, default="[]")  # JSON list of {evaluator, value, label, explanation, level}
    errors_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    test_case = relationship("EvaluationTestCase", back_populates="runs")

    def get_results(self) -> list[dict]:
        try:
            return json.loads(self.results_json or "[]")
        except json.JSONDecodeError:
            return []

    def set_results(self, results: list[dict]) -> None:
        self.results_json = json.dumps(results)

    def get_errors(self) -> list[str]:
        try:
            return json.loads(self.errors_json or "[]")
        except json.JSONDecodeError:
            return []

    def set_errors(self, errors: list[str]) -> None:
        self.errors_json = json.dumps(errors)
