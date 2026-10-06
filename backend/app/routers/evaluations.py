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
from datetime import datetime
from uuid import uuid4
from typing import List, Literal, Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db, SessionLocal
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.evaluation import EvaluationTestCase, EvaluationRun, DEFAULT_PASS_THRESHOLD
from app.models.invocation import Invocation
from app.models.session import InvocationSession
from app.routers.agents import derive_log_group
from app.routers.utils import get_agent_or_404
from app.services import evaluations as evals
from app.services.agentcore import invoke_agent
from app.services.cognito import get_cognito_token
from app.services.otel import fetch_otel_events
from app.services.secrets import get_secret

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


class EvaluatorInfo(BaseModel):
    """An evaluator that can be selected for a test case."""
    id: str
    name: Optional[str]
    description: Optional[str]
    type: Optional[str]
    group: str


class TestCaseRequest(BaseModel):
    """Create/update body for a saved test case."""
    name: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1)
    expected_response: Optional[str] = None
    evaluator_ids: List[str] = Field(..., min_length=1)
    pass_threshold: float = Field(DEFAULT_PASS_THRESHOLD, ge=0.0, le=1.0)
    model_id: Optional[str] = None


class TestCaseResponse(BaseModel):
    """A saved test case."""
    id: int
    agent_id: int
    name: str
    prompt: str
    expected_response: Optional[str]
    evaluator_ids: List[str]
    pass_threshold: float
    model_id: Optional[str]
    last_batch_evaluation_id: Optional[str]
    last_run_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class RunTestCaseResponse(BaseModel):
    """Result of kicking off a test case run."""
    batch_evaluation_id: str
    status: str
    agent_response: Optional[str]


class TestCaseScoreDetail(BaseModel):
    """One evaluator's verdict within a test case's latest run."""
    evaluator: Optional[str]
    value: Optional[float]
    label: Optional[str]
    explanation: Optional[str]
    level: Optional[str]


class TestCaseRunDetailResponse(BaseModel):
    """Status, per-evaluator scores, and failure reasons for one test case run."""
    status: Optional[str]
    scores: List[TestCaseScoreDetail]
    errors: List[str] = []
    session_id: Optional[str] = None


class TestCaseRunSummary(BaseModel):
    """One past run of a test case, for the run-history list."""
    batch_evaluation_id: str
    status: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    errors: List[str] = []


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


# ---------------------------------------------------------------------------
# Creating evaluations: saved test cases + running them
# ---------------------------------------------------------------------------
#
# A test case is just a saved prompt + evaluator selection. Running one
# invokes the agent (producing a real session), then scores that session via
# AgentCore's on-demand Evaluate API — see the module docstring on
# app/services/evaluations.py's "Creating evaluations" section for why that
# API rather than batch evaluation. Unlike batch evaluation, on-demand
# evaluation has no AWS-side resource Loom can re-query later, so each run's
# outcome is persisted in Loom's own EvaluationRun table.


def _test_case_to_response(tc: EvaluationTestCase) -> TestCaseResponse:
    return TestCaseResponse(**tc.to_dict())


def _get_test_case_or_404(agent_id: int, test_case_id: int, db: Session) -> EvaluationTestCase:
    tc = db.query(EvaluationTestCase).filter(
        EvaluationTestCase.id == test_case_id,
        EvaluationTestCase.agent_id == agent_id,
    ).first()
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")
    return tc


@router.get("/{agent_id}/evaluations/evaluators", response_model=List[EvaluatorInfo])
def list_evaluators(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> List[EvaluatorInfo]:
    """Evaluators available to pick for a test case (built-in + any custom)."""
    agent = get_agent_or_404(agent_id, db, user)
    try:
        return [EvaluatorInfo(**e) for e in evals.list_evaluators(agent.region)]
    except (ClientError, BotoCoreError) as exc:
        raise _aws_error(exc) from exc


@router.get("/{agent_id}/evaluations/test-cases", response_model=List[TestCaseResponse])
def list_test_cases(
    agent_id: int,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> List[TestCaseResponse]:
    """Saved test cases for this agent."""
    get_agent_or_404(agent_id, db, user)
    rows = db.query(EvaluationTestCase).filter(EvaluationTestCase.agent_id == agent_id).order_by(EvaluationTestCase.created_at.desc()).all()
    return [_test_case_to_response(tc) for tc in rows]


@router.post("/{agent_id}/evaluations/test-cases", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
def create_test_case(
    agent_id: int,
    request: TestCaseRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> TestCaseResponse:
    """Save a new test case for this agent."""
    get_agent_or_404(agent_id, db, user)
    tc = EvaluationTestCase(
        agent_id=agent_id,
        name=request.name.strip(),
        prompt=request.prompt,
        expected_response=request.expected_response.strip() if request.expected_response else None,
        pass_threshold=request.pass_threshold,
        model_id=request.model_id or None,
    )
    tc.set_evaluator_ids(request.evaluator_ids)
    db.add(tc)
    db.commit()
    db.refresh(tc)
    return _test_case_to_response(tc)


@router.put("/{agent_id}/evaluations/test-cases/{test_case_id}", response_model=TestCaseResponse)
def update_test_case(
    agent_id: int,
    test_case_id: int,
    request: TestCaseRequest,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> TestCaseResponse:
    """Update a saved test case's prompt, expected response, or evaluators."""
    get_agent_or_404(agent_id, db, user)
    tc = _get_test_case_or_404(agent_id, test_case_id, db)
    tc.name = request.name.strip()
    tc.prompt = request.prompt
    tc.expected_response = request.expected_response.strip() if request.expected_response else None
    tc.pass_threshold = request.pass_threshold
    tc.model_id = request.model_id or None
    tc.set_evaluator_ids(request.evaluator_ids)
    db.commit()
    db.refresh(tc)
    return _test_case_to_response(tc)


@router.delete("/{agent_id}/evaluations/test-cases/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_case(
    agent_id: int,
    test_case_id: int,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> None:
    """Delete a saved test case and its run history.

    Nothing to clean up on AWS's side — on-demand evaluation (unlike batch
    evaluation) never creates a persisted AWS resource; EvaluationRun rows
    cascade-delete with the test case.
    """
    get_agent_or_404(agent_id, db, user)
    tc = _get_test_case_or_404(agent_id, test_case_id, db)
    db.delete(tc)
    db.commit()


def _resolve_access_token(agent: Agent, request: Request) -> str | None:
    """A bearer token for invoking an authorizer-protected agent.

    Mirrors the two self-service priorities from the main invoke endpoint
    (``routers/invocations.py``) that don't depend on request-body fields
    specific to that endpoint (manual token / credential_id / linked-user
    token): forward the caller's own login token first — Loom's frontend and
    the agent typically share the same authorization server — then fall back
    to the agent's own M2M client credentials if it was deployed with one.
    Non-authorizer agents (plain SigV4) return None, same as today.
    """
    auth_config = agent.get_authorizer_config()
    if not auth_config or not auth_config.get("type"):
        return None

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    if auth_config.get("type") == "cognito" and auth_config.get("pool_id"):
        config_map = {e.key: e.value for e in agent.config_entries}
        client_id = config_map.get("COGNITO_CLIENT_ID", "")
        secret_arn = config_map.get("COGNITO_CLIENT_SECRET_ARN", "")
        if client_id and secret_arn:
            try:
                client_secret = get_secret(secret_arn, agent.region)
                token_response = get_cognito_token(
                    pool_id=auth_config["pool_id"],
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=auth_config.get("allowed_scopes") or None,
                )
                return token_response.get("access_token")
            except Exception as e:
                logger.warning("Failed to get Cognito M2M token for agent %s: %s", agent.id, e)
    return None


# How long to wait for the session's spans before giving up as ERROR.
# Generous on purpose: unlike batch evaluation's internal (and too-short)
# budget, nothing times this out from the other end — waiting longer here is
# just waiting longer, not racing anything.
_SPAN_WAIT_S = 180.0


def _finish_evaluation_run(db: Session, run: "EvaluationRun", tc: EvaluationTestCase,
                           spans: list, region: str) -> None:
    """Score a run's spans and record the outcome. COMPLETED needs at least
    one evaluator to have actually produced a score. Per-evaluator failures
    are kept on the run even when some other evaluator succeeded — they used
    to be discarded here (only logged server-side), which made a run look
    like a single clean PASS/FAIL even when most of its evaluators silently
    failed. The frontend treats a non-empty error list alongside scores as a
    partial result, not a hard ERROR."""
    scores, errors = evals.run_on_demand_evaluation(tc.get_evaluator_ids(), spans, region)
    run.set_results(scores)
    run.set_errors(errors)
    run.status = "COMPLETED" if scores else "ERROR"
    if not scores and not errors:
        run.set_errors(["No evaluator returned a score for this session."])
    for e in errors:
        logger.warning("Evaluator error for run %s: %s", run.id, e)
    run.updated_at = datetime.utcnow()
    db.commit()


def _execute_run(run_id: int, test_case_id: int, agent_id: int, session_id: str,
                 prompt: str | None, model_id: str | None, access_token: str | None,
                 username: str | None) -> None:
    """Do the actual work of a test case run as a background task, moving
    the run through named phases (INVOKING, WAITING_FOR_LOGS, EVALUATING) as
    it goes — not just one opaque "running" state for however long the whole
    thing takes — so the frontend has something concrete to show while it
    waits. Returning from the endpoint before any of this starts (see
    run_test_case/rescore_test_case) is what makes "Run all" feel responsive
    instead of blocking on each test case's full invoke+wait+evaluate chain
    in turn. Uses its own DB session since the request's is closed once this
    task is scheduled.

    `prompt` is None for a rescore (same session, no re-invocation).
    """
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        tc = db.query(EvaluationTestCase).filter(EvaluationTestCase.id == test_case_id).first()
        run = db.query(EvaluationRun).filter(EvaluationRun.id == run_id).first()
        if not agent or not tc or not run:
            return

        if prompt is not None:
            run.status = "INVOKING"
            db.commit()
            qualifier = "DEFAULT"
            try:
                chunks = list(invoke_agent(
                    arn=agent.arn, qualifier=qualifier, session_id=session_id,
                    prompt=prompt, region=agent.region, runtime_model_id=model_id,
                    access_token=access_token,
                ))
            except Exception as exc:
                run.status = "ERROR"
                run.set_errors([f"Failed to invoke agent: {exc}"])
                run.updated_at = datetime.utcnow()
                db.commit()
                return
            agent_response = "".join(c.get("content", "") for c in chunks if c.get("type") == "text") or None

            # Record this as a real session/invocation — test-case runs
            # invoke the agent through the service layer directly rather than
            # the main /invoke endpoint, so without this they're invisible to
            # Loom's own session tracking. That breaks "Open session" / "View
            # in session trace" from the evaluations tab: the session
            # genuinely exists in AgentCore (and is what gets scored), but
            # GET /sessions/{id} 404s because Loom never persisted it.
            db.add(InvocationSession(
                agent_id=agent.id, session_id=session_id, qualifier=qualifier,
                status="complete", created_at=datetime.utcnow(), user_id=username,
            ))
            db.add(Invocation(
                session_id=session_id, invocation_id=str(uuid4()), status="complete",
                prompt_text=prompt, response_text=agent_response, created_at=datetime.utcnow(),
            ))
            db.commit()

        run.status = "WAITING_FOR_LOGS"
        db.commit()
        log_group = derive_log_group(agent.runtime_id, "DEFAULT")
        spans = evals.wait_for_session_spans(log_group, session_id, agent.region, timeout_s=_SPAN_WAIT_S)
        if not spans:
            run.status = "ERROR"
            run.set_errors(["No trace spans were found for this session after several minutes."])
            run.updated_at = datetime.utcnow()
            db.commit()
            return

        run.status = "EVALUATING"
        db.commit()
        _finish_evaluation_run(db, run, tc, spans, agent.region)
    finally:
        db.close()


@router.post("/{agent_id}/evaluations/test-cases/{test_case_id}/run", response_model=RunTestCaseResponse)
def run_test_case(
    agent_id: int,
    test_case_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> RunTestCaseResponse:
    """Kick off a test case run (invoke the agent, then score that session
    via on-demand evaluation) in the background and return immediately — the
    whole sequence can take anywhere from several seconds to a few minutes,
    and the caller shouldn't have to hold a connection open for that."""
    agent = get_agent_or_404(agent_id, db, user)
    tc = _get_test_case_or_404(agent_id, test_case_id, db)
    if not agent.arn or not agent.runtime_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent has no runtime to invoke yet")

    # Resolved here, not in the background task: it depends on this request's
    # own headers/context, which won't exist anymore once this returns.
    access_token = _resolve_access_token(agent, request)

    session_id = str(uuid4())
    run = EvaluationRun(test_case_id=tc.id, session_id=session_id, status="PENDING")
    db.add(run)
    db.commit()
    db.refresh(run)
    tc.last_batch_evaluation_id = str(run.id)
    tc.last_run_at = datetime.utcnow()
    db.commit()

    background_tasks.add_task(
        _execute_run, run.id, test_case_id, agent_id, session_id,
        tc.prompt, tc.model_id, access_token, user.username,
    )

    return RunTestCaseResponse(batch_evaluation_id=str(run.id), status=run.status, agent_response=None)


@router.get("/{agent_id}/evaluations/test-cases/{test_case_id}/last-run", response_model=TestCaseRunDetailResponse)
def get_test_case_last_run(
    agent_id: int,
    test_case_id: int,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> TestCaseRunDetailResponse:
    """Status and per-evaluator scores for this test case's latest run."""
    get_agent_or_404(agent_id, db, user)
    tc = _get_test_case_or_404(agent_id, test_case_id, db)
    run = db.query(EvaluationRun).filter(EvaluationRun.test_case_id == tc.id).order_by(EvaluationRun.created_at.desc()).first()
    if not run:
        return TestCaseRunDetailResponse(status=None, scores=[], errors=[], session_id=None)
    return TestCaseRunDetailResponse(
        status=run.status,
        scores=[TestCaseScoreDetail(**s) for s in run.get_results()],
        errors=run.get_errors(),
        session_id=run.session_id,
    )


@router.post("/{agent_id}/evaluations/test-cases/{test_case_id}/rescore", response_model=RunTestCaseResponse)
def rescore_test_case(
    agent_id: int,
    test_case_id: int,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> RunTestCaseResponse:
    """Re-score the test case's last run's session without re-invoking the agent.

    For an ERROR result (no spans yet, a transient evaluator failure) the
    agent's response is usually still fine — only scoring failed — so this
    re-evaluates the same session's spans instead of invoking the agent again.
    """
    agent = get_agent_or_404(agent_id, db, user)
    tc = _get_test_case_or_404(agent_id, test_case_id, db)
    last_run = db.query(EvaluationRun).filter(EvaluationRun.test_case_id == tc.id).order_by(EvaluationRun.created_at.desc()).first()
    if not last_run:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This test case has no prior run to rescore")
    if not agent.runtime_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent has no runtime")

    run = EvaluationRun(test_case_id=tc.id, session_id=last_run.session_id, status="PENDING")
    db.add(run)
    db.commit()
    db.refresh(run)
    tc.last_batch_evaluation_id = str(run.id)
    tc.last_run_at = datetime.utcnow()
    db.commit()

    background_tasks.add_task(
        _execute_run, run.id, test_case_id, agent_id, last_run.session_id,
        None, tc.model_id, None, None,
    )

    return RunTestCaseResponse(batch_evaluation_id=str(run.id), status=run.status, agent_response=None)


@router.get("/{agent_id}/evaluations/test-cases/{test_case_id}/runs", response_model=List[TestCaseRunSummary])
def list_test_case_runs(
    agent_id: int,
    test_case_id: int,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> List[TestCaseRunSummary]:
    """Every past run of this test case, newest first, including failed ones."""
    get_agent_or_404(agent_id, db, user)
    tc = _get_test_case_or_404(agent_id, test_case_id, db)
    runs = db.query(EvaluationRun).filter(EvaluationRun.test_case_id == tc.id).order_by(EvaluationRun.created_at.desc()).limit(25).all()
    return [
        TestCaseRunSummary(
            batch_evaluation_id=str(r.id),
            status=r.status,
            created_at=(r.created_at.isoformat() + "Z") if r.created_at else None,
            updated_at=(r.updated_at.isoformat() + "Z") if r.updated_at else None,
            errors=r.get_errors(),
        )
        for r in runs
    ]


@router.get("/{agent_id}/evaluations/test-cases/{test_case_id}/runs/{batch_evaluation_id}",
            response_model=TestCaseRunDetailResponse)
def get_test_case_run(
    agent_id: int,
    test_case_id: int,
    batch_evaluation_id: str,
    user: UserInfo = Depends(require_scopes("agent:read")),
    db: Session = Depends(get_db),
) -> TestCaseRunDetailResponse:
    """Status, scores, and failure reasons for one specific past run."""
    get_agent_or_404(agent_id, db, user)
    tc = _get_test_case_or_404(agent_id, test_case_id, db)
    try:
        run_id = int(batch_evaluation_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    run = db.query(EvaluationRun).filter(EvaluationRun.id == run_id, EvaluationRun.test_case_id == tc.id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return TestCaseRunDetailResponse(
        status=run.status,
        scores=[TestCaseScoreDetail(**s) for s in run.get_results()],
        errors=run.get_errors(),
        session_id=run.session_id,
    )
