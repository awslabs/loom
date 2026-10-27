"""EvaluationTestCase/EvaluationRun ORM models: a saved, re-runnable test
prompt for an agent, and the results of running it.

Loom doesn't judge anything itself — running a test case invokes the agent,
waits for that session's OTEL spans to become queryable in CloudWatch, and
has AgentCore Evaluations score them (see app/services/evaluations.py), in
one of two modes:

- **on_demand** hands the downloaded spans to the synchronous Evaluate API.
  Nothing persists on AWS's side, so EvaluationRun is the only record.
- **batch** starts a StartBatchEvaluation job for the session. The job and
  its per-session results stay in AWS (and the console); EvaluationRun keeps
  the job ID alongside the same scores, so history reads the same either way.
"""
import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base

DEFAULT_PASS_THRESHOLD = 0.7

EVALUATION_MODE_ON_DEMAND = "on_demand"
EVALUATION_MODE_BATCH = "batch"
DEFAULT_EVALUATION_MODE = EVALUATION_MODE_BATCH


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
    evaluation_mode = Column(String, nullable=False, default=DEFAULT_EVALUATION_MODE)  # "batch" or "on_demand"
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
            "evaluation_mode": self.evaluation_mode or DEFAULT_EVALUATION_MODE,
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
    # Snapshotted from the test case when the run starts, so history shows
    # how each run was actually scored even after the test case's mode changes.
    evaluation_mode = Column(String, nullable=True, default=DEFAULT_EVALUATION_MODE)
    batch_job_id = Column(String, nullable=True)  # AgentCore batchEvaluationId, batch mode only
    # Every batch job the run used (a retry adds a second one), so deleting
    # the run's test case can delete them all in AWS. JSON list.
    batch_job_ids = Column(Text, nullable=True)
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

    def get_batch_job_ids(self) -> list[str]:
        try:
            ids = json.loads(self.batch_job_ids or "[]")
        except json.JSONDecodeError:
            ids = []
        if self.batch_job_id and self.batch_job_id not in ids:
            ids.append(self.batch_job_id)
        return ids

    def set_batch_job_ids(self, ids: list[str]) -> None:
        self.batch_job_ids = json.dumps(list(dict.fromkeys(ids)))

    def get_errors(self) -> list[str]:
        try:
            return json.loads(self.errors_json or "[]")
        except json.JSONDecodeError:
            return []

    def set_errors(self, errors: list[str]) -> None:
        self.errors_json = json.dumps(errors)
