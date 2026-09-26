"""Read-only AgentCore Evaluations results for an agent.

Endpoints:
  GET /api/agents/{agent_id}/evaluations
      Online evaluation configs and batch evaluation runs that score this
      agent, with when each last produced a result.
  GET /api/agents/{agent_id}/evaluations/results?source_type=&source_id=
      Per-trace scores and judge explanations from one source.
  GET /api/agents/{agent_id}/evaluations/traces/{trace_id}/exchange
      The prompt and answer of one evaluated trace, read from the runtime's
      OTEL logs.

The results endpoint re-reads the chosen source from AWS and checks that it
evaluates this agent before reading its results log group, so a caller can
never point it at an arbitrary log group.
"""

import logging
import re
from typing import List, Literal, Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.routers.agents import derive_log_group
from app.routers.utils import get_agent_or_404
from app.services import evaluations as evals
from app.services.otel import fetch_otel_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["evaluations"])

_TRACE_ID_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")
# Online config and batch run IDs look like ``<name>-<suffix>``; names are
# alphanumeric plus underscore, so anything else can be refused before any AWS call.
_SOURCE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class OnlineEvaluationSource(BaseModel):
    """An online evaluation config that samples this agent's live sessions."""
    id: str
    name: Optional[str]
    status: Optional[str]
    execution_status: Optional[str]
    sampling_percentage: Optional[float]
    session_timeout_minutes: Optional[int]
    evaluators: List[str]
    shared: bool = False
    last_evaluated_at: Optional[str]
    updated_at: Optional[str]


class EvaluatorSummary(BaseModel):
    """Average score of one evaluator across a batch run."""
    evaluator_id: Optional[str]
    average_score: Optional[float]
    total_evaluated: Optional[int]
    total_failed: Optional[int]


class BatchEvaluationSource(BaseModel):
    """A one-off batch evaluation run over a chosen set of sessions."""
    id: str
    name: Optional[str]
    description: Optional[str]
    status: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    evaluators: List[str]
    shared: bool = False
    targeted_session_count: int
    sessions_total: Optional[int]
    sessions_completed: Optional[int]
    sessions_failed: Optional[int]
    sessions_ignored: Optional[int]
    evaluator_summaries: List[EvaluatorSummary]


class EvaluationOverviewResponse(BaseModel):
    """All evaluation sources that score this agent."""
    online: List[OnlineEvaluationSource]
    batch: List[BatchEvaluationSource]


class EvaluationScore(BaseModel):
    """One evaluator's verdict on one trace."""
    evaluator: Optional[str]
    value: Optional[float]
    label: Optional[str]
    explanation: Optional[str]
    level: Optional[str]


class EvaluatedTrace(BaseModel):
    """All evaluator verdicts for one evaluated trace."""
    session_id: Optional[str]
    trace_id: Optional[str]
    trace_time: Optional[str]
    evaluated_at: Optional[str]
    scores: List[EvaluationScore]


class EvaluationResultsResponse(BaseModel):
    """Evaluated traces from one evaluation source."""
    results: List[EvaluatedTrace]
    truncated: bool


class EvaluatedExchangeResponse(BaseModel):
    """What the user asked and what the agent answered in one trace."""
    prompt: Optional[str]
    answer: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agent_target(agent: Agent) -> evals.AgentTarget:
    """How this agent appears in evaluation data: runtime log groups and OTEL service names.

    AgentCore Runtime names an agent's spans ``<runtime name>.<endpoint>``
    (for example ``my_agent.DEFAULT``). The runtime name is the runtime ID
    without its generated ``-XXXXXXXXXX`` suffix; runtime names cannot
    contain ``-``, so the split is exact.
    """
    if not agent.runtime_id:
        return evals.AgentTarget(frozenset(), frozenset())
    qualifiers = agent.get_available_qualifiers() or ["DEFAULT"]
    runtime_name = agent.runtime_id.rsplit("-", 1)[0]
    return evals.AgentTarget(
        log_groups=frozenset(derive_log_group(agent.runtime_id, q) for q in qualifiers),
        service_names=frozenset(f"{runtime_name}.{q}" for q in qualifiers),
    )


def _aws_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        message = exc.response.get("Error", {}).get("Message", "")
        detail = f"AgentCore Evaluations request failed ({code}): {message}"
    else:
        detail = f"AgentCore Evaluations request failed: {exc}"
    logger.warning(detail)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


_NOT_FOUND = "Evaluation source not found for this agent"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/evaluations", response_model=EvaluationOverviewResponse)
def get_agent_evaluations(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> EvaluationOverviewResponse:
    """List the online configs and batch runs that evaluate this agent."""
    agent = get_agent_or_404(agent_id, db, user)
    target = _agent_target(agent)
    if not target.log_groups:
        return EvaluationOverviewResponse(online=[], batch=[])
    try:
        sources = evals.discover_sources(target, agent.region)
    except (ClientError, BotoCoreError) as exc:
        raise _aws_error(exc) from exc
    return EvaluationOverviewResponse(
        online=[OnlineEvaluationSource(**s) for s in sources["online"]],
        batch=[BatchEvaluationSource(**s) for s in sources["batch"]],
    )


@router.get("/{agent_id}/evaluations/results", response_model=EvaluationResultsResponse)
def get_evaluation_results(
    agent_id: int,
    source_type: Literal["online", "batch"] = Query(..., description="online or batch"),
    source_id: str = Query(..., min_length=1, max_length=128),
    days: int = Query(7, ge=1, le=30, description="Look-back window for online results"),
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> EvaluationResultsResponse:
    """Per-trace scores from one online config or one batch run of this agent."""
    if not _SOURCE_ID_RE.match(source_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid source id")
    agent = get_agent_or_404(agent_id, db, user)
    target = _agent_target(agent)
    if not target.log_groups:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    try:
        location = evals.resolve_results_location(source_type, source_id, target, agent.region)
        if location is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
        records, truncated = evals.read_results(location, agent.region, days=days)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("ResourceNotFoundException", "ValidationException"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND) from exc
        raise _aws_error(exc) from exc
    except BotoCoreError as exc:
        raise _aws_error(exc) from exc

    return EvaluationResultsResponse(
        results=[EvaluatedTrace(**r) for r in evals.group_by_trace(records)],
        truncated=truncated,
    )


@router.get("/{agent_id}/evaluations/traces/{trace_id}/exchange", response_model=EvaluatedExchangeResponse)
def get_evaluated_exchange(
    agent_id: int,
    trace_id: str,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> EvaluatedExchangeResponse:
    """The prompt and answer of an evaluated trace, from the runtime's OTEL logs."""
    if not _TRACE_ID_RE.match(trace_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid trace id")
    agent = get_agent_or_404(agent_id, db, user)
    for log_group in sorted(_agent_target(agent).log_groups):
        events = fetch_otel_events(log_group=log_group, region=agent.region, filter_pattern=f'"{trace_id}"')
        if events:
            return EvaluatedExchangeResponse(**evals.extract_exchange(events))
    return EvaluatedExchangeResponse(prompt=None, answer=None)
