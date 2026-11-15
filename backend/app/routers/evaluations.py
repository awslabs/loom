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

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4
from typing import Callable, List, Literal, NamedTuple, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db import get_db, SessionLocal
from app.dependencies.auth import UserInfo, require_scopes
from app.models.agent import Agent
from app.models.evaluation import (
    DEFAULT_EVALUATION_MODE, DEFAULT_PASS_THRESHOLD, EVALUATION_MODE_BATCH,
    EvaluationRun, EvaluationTestCase,
)
from app.models.invocation import Invocation
from app.models.session import InvocationSession
from app.routers.agents import derive_log_group
from app.routers.utils import get_agent_or_404
from app.services import evaluations as evals
from app.services.agentcore import invoke_agent
from app.services.cognito import get_cognito_token
from app.services.otel import fetch_otel_events
from app.services.secrets import get_secret
from app.services.usage_limits import check_usage_limits, resolve_effective_model_id
from app.services.model_catalog import get_model_family

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
    evaluation_mode: Literal["on_demand", "batch"] = DEFAULT_EVALUATION_MODE

    @model_validator(mode="after")
    def _batch_evaluator_limit(self) -> "TestCaseRequest":
        if self.evaluation_mode == EVALUATION_MODE_BATCH and len(self.evaluator_ids) > evals.BATCH_MAX_EVALUATORS:
            raise ValueError(f"Batch mode supports at most {evals.BATCH_MAX_EVALUATORS} evaluators per test case")
        return self


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
    evaluation_mode: str
    last_batch_evaluation_id: Optional[str]
    last_run_at: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class RunTestCaseResponse(BaseModel):
    """Result of kicking off a test case run."""
    batch_evaluation_id: str
    status: str
    agent_response: Optional[str]


class RunAllEntry(BaseModel):
    """One test case started by run-all."""
    test_case_id: int
    batch_evaluation_id: str
    evaluation_mode: str


class RunAllResponse(BaseModel):
    """What run-all started: one run per test case, and how many batch jobs
    the batch-mode runs were grouped into (one per distinct evaluator set)."""
    runs: List[RunAllEntry]
    batch_jobs: int


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
    evaluation_mode: Optional[str] = None
    batch_job_id: Optional[str] = None


class TestCaseRunSummary(BaseModel):
    """One past run of a test case, for the run-history list."""
    batch_evaluation_id: str
    status: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    errors: List[str] = []
    evaluation_mode: Optional[str] = None
    batch_job_id: Optional[str] = None


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
# invokes the agent (producing a real session), waits until that session's
# spans are queryable, then scores it in the test case's evaluation mode:
# on-demand Evaluate calls, or one StartBatchEvaluation job — see the
# "Creating evaluations" section in app/services/evaluations.py. Either way
# each run's outcome is persisted in Loom's own EvaluationRun table, so run
# history reads the same for both modes.


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
        evaluation_mode=request.evaluation_mode,
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
    tc.evaluation_mode = request.evaluation_mode
    tc.set_evaluator_ids(request.evaluator_ids)
    db.commit()
    db.refresh(tc)
    return _test_case_to_response(tc)


@router.delete("/{agent_id}/evaluations/test-cases/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_case(
    agent_id: int,
    test_case_id: int,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> None:
    """Delete a saved test case, its run history, and its batch jobs in AWS.

    EvaluationRun rows cascade-delete with the test case. The batch jobs its
    runs used are deleted in AWS too (in the background: a running job has
    to be stopped first), except a job shared with another test case's run
    from the same Run all, which stays until that run goes as well.
    On-demand runs never created anything in AWS.
    """
    agent = get_agent_or_404(agent_id, db, user)
    tc = _get_test_case_or_404(agent_id, test_case_id, db)
    run_ids = {r.id for r in tc.runs}
    jobs = _unreferenced_batch_jobs(db, agent_id, {j for r in tc.runs for j in r.get_batch_job_ids()},
                                    excluding_run_ids=run_ids)
    db.delete(tc)
    db.commit()
    if jobs:
        background_tasks.add_task(evals.delete_batch_jobs, jobs, agent.region)


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


# How long to wait for the session's agent spans to become queryable before
# giving up as ERROR. The delay before Logs Insights returns a new session's
# spans varies: under a minute to over four minutes in the same afternoon.
# Matches the 300s AWS's own span collector (CloudWatchAgentSpanCollector)
# waits by default.
_SPAN_WAIT_S = 300.0


def _finish_evaluation_run(db: Session, run: "EvaluationRun", tc: EvaluationTestCase,
                           spans: list, region: str, stopped: Callable[[], bool] = lambda: False) -> None:
    """Score a run's spans with on-demand Evaluate calls and record the
    outcome, unless the run was stopped while the Evaluate calls ran."""
    scores, errors = evals.run_on_demand_evaluation(tc.get_evaluator_ids(), spans, region)
    if stopped():
        return
    db.refresh(run)
    _record_outcome(db, run, scores, errors)


# Parallelism for a group of batch-mode runs: invoking the agent and waiting
# for each session's spans happen concurrently, then each evaluator-set
# group's batch job runs concurrently. Database writes stay on the calling
# thread; worker threads only make AWS calls.
_BATCH_WORKERS = 8
# How many of Run all's runs (each on-demand run, plus the batch group) go at
# once. They share one background task, and FastAPI runs a request's
# background tasks one after another, so this is what keeps them parallel.
_RUN_ALL_WORKERS = 8


def _warm_boto3_clients(region: str) -> None:
    """Create one client per service before starting worker threads.

    The worker threads each create their own boto3 clients from the default
    session, which isn't safe to initialise concurrently. Doing it once here
    resolves credentials and loads the service models before any thread starts.
    """
    for service in ("bedrock-agentcore", "logs"):
        boto3.client(service, region_name=region)


def _evaluator_set(tc: EvaluationTestCase) -> tuple[str, ...]:
    """Grouping key for batch jobs: a job applies one evaluator list to every
    session in it, so only runs with the same evaluators (in any order) share one."""
    return tuple(sorted(set(tc.get_evaluator_ids())))


def _invoke_text(arn: str, region: str, session_id: str, prompt: str, model_id: str | None,
                 access_token: str | None) -> tuple[str | None, str | None]:
    """Invoke the agent. Returns (response text, error)."""
    try:
        chunks = list(invoke_agent(
            arn=arn, qualifier="DEFAULT", session_id=session_id, prompt=prompt, region=region,
            runtime_model_id=model_id, access_token=access_token,
        ))
    except Exception as exc:
        return None, str(exc)
    return "".join(c.get("content", "") for c in chunks if c.get("type") == "text") or None, None


def _record_invocation(db: Session, agent_id: int, session_id: str, prompt: str,
                       response: str | None, username: str | None,
                       groups: list[str] | None = None,
                       model_id: str | None = None,
                       region: str | None = None) -> None:
    """Record a test-case invocation as a real session/invocation.

    Test-case runs invoke the agent through the service layer directly rather
    than the main /invoke endpoint, so without this they're invisible to
    Loom's own session tracking. That breaks "Open session" / "View in
    session trace" from the evaluations tab: the session genuinely exists in
    AgentCore (and is what gets scored), but GET /sessions/{id} 404s because
    Loom never persisted it.
    """
    input_tokens = max(1, len(prompt) // 4)
    output_tokens = len(response) // 4 if response else 0
    try:
        from app.services.tokens import count_input_tokens, count_output_tokens
        if model_id and region:
            input_tokens = count_input_tokens(model_id, prompt, region)
            if response:
                output_tokens = count_output_tokens(model_id, response, region)
    except Exception:
        pass

    db.add(InvocationSession(
        agent_id=agent_id, session_id=session_id, qualifier="DEFAULT",
        status="complete", created_at=datetime.utcnow(), user_id=username,
        groups=json.dumps(groups or []),
    ))
    db.add(Invocation(
        session_id=session_id, invocation_id=str(uuid4()), status="complete",
        prompt_text=prompt, response_text=response, created_at=datetime.utcnow(),
        input_tokens=input_tokens, output_tokens=output_tokens,
        model_id=model_id,
        model_family=get_model_family(model_id) if model_id else None,
    ))
    db.commit()


def _fail_run(db: Session, run: "EvaluationRun", message: str) -> None:
    run.status = "ERROR"
    run.set_errors([message])
    run.updated_at = datetime.utcnow()
    db.commit()


def _spans_not_ready_message(spans: list) -> str:
    """Why a run can't be scored when its wait ended without an agent span.

    Without one there is nothing either mode can score: Evaluate rejects the
    set ("no spans with supported scope") and a batch job fails ("No
    evaluable agent spans found"). Say what actually happened instead.
    """
    if not spans:
        return "No trace spans were found for this session after several minutes."
    return ("The agent's spans weren't queryable in CloudWatch after several minutes "
            "(only infrastructure spans had arrived). Score again in a few minutes.")


# A run moves through these until it ends as COMPLETED, ERROR, or STOPPED.
_RUN_IN_PROGRESS = frozenset({"PENDING", "INVOKING", "WAITING_FOR_LOGS", "EVALUATING"})
_RUN_STOPPED = "STOPPED"


def _runs_stopped(run_ids: list[int]) -> bool:
    """Whether every one of these runs was stopped by its user, or deleted.

    Read through a fresh session on each call: the background work calls
    this from worker threads while it polls, and the stop itself comes from
    another request (possibly in another backend process), so the database
    is the only place both sides can see.
    """
    if not run_ids:
        return True
    db = SessionLocal()
    try:
        rows = db.query(EvaluationRun.id, EvaluationRun.status).filter(EvaluationRun.id.in_(run_ids)).all()
    finally:
        db.close()
    return all(status_ == _RUN_STOPPED for _, status_ in rows)


def _record_started_job(job_id: str, run_ids: list[int]) -> None:
    """Save a batch job's ID on its runs as soon as it starts, so a stop or a
    deletion can find it while it's still running. Own session: this runs
    on a worker thread."""
    db = SessionLocal()
    try:
        for run in db.query(EvaluationRun).filter(EvaluationRun.id.in_(run_ids)).all():
            run.batch_job_id = job_id
            run.set_batch_job_ids(run.get_batch_job_ids() + [job_id])
        db.commit()
    finally:
        db.close()


def _unreferenced_batch_jobs(db: Session, agent_id: int, job_ids: set[str],
                             excluding_run_ids: set[int] = frozenset()) -> list[str]:
    """The jobs in ``job_ids`` that no other run of this agent still points at.

    A Run all job can score several test cases, so deleting one of them must
    not delete a job another test case's run still shows results from. Jobs
    are only ever shared within one agent.
    """
    if not job_ids:
        return []
    still_used: set[str] = set()
    others = db.query(EvaluationRun).join(EvaluationTestCase).filter(
        EvaluationTestCase.agent_id == agent_id,
        EvaluationRun.batch_job_id.isnot(None) | EvaluationRun.batch_job_ids.isnot(None),
    )
    for run in others.all():
        if run.id not in excluding_run_ids:
            still_used.update(run.get_batch_job_ids())
    return sorted(job_ids - still_used)


class _BatchItem(NamedTuple):
    """What a batch-mode run needs, as plain values captured up front.

    A test case (or its agent) can be deleted while its batch group is still
    running, and touching a deleted row's ORM object raises. So the group
    works from these values, and only loads the rows that still exist when it
    needs to write (see _existing_runs).
    """
    run_id: int
    session_id: str
    test_case_id: int
    test_case_name: str
    evaluator_set: tuple[str, ...]
    model_id: str | None
    prompt: str | None


def _existing_runs(db: Session, items: list[_BatchItem]) -> dict[int, "EvaluationRun"]:
    """The runs among ``items`` still to be worked on, by id: rows that
    still exist and haven't been stopped by their user."""
    if not items:
        return {}
    rows = db.query(EvaluationRun).populate_existing().filter(
        EvaluationRun.id.in_([i.run_id for i in items])).all()
    return {r.id: r for r in rows if r.status != _RUN_STOPPED}


def _execute_batch_runs(items: list[tuple[int, str | None]], agent_id: int,
                        access_token: str | None, user: UserInfo) -> None:
    """Run a set of batch-mode test-case runs, sharing batch jobs.

    ``items`` is (run id, prompt) pairs; a None prompt means rescore the
    run's existing session without invoking the agent. All the runs are
    invoked, then waited on, in parallel. Each run whose spans became
    queryable is scored in one job per evaluator set; a run whose spans
    didn't arrive in time ends as ERROR on its own without holding up the
    rest, and "Score again" scores it later.

    The caller's access to the agent is checked again here, not just in the
    route that queued this: the work can start minutes later, after the
    agent's group has changed.
    """
    db = SessionLocal()
    try:
        runs = {r.id: r for r in db.query(EvaluationRun).filter(EvaluationRun.id.in_([i for i, _ in items])).all()}
        if not runs:
            return
        try:
            agent = get_agent_or_404(agent_id, db, user)
        except HTTPException as exc:
            for run in runs.values():
                _fail_run(db, run, f"Not scored: {exc.detail}")
            return
        tcs = {tc.id: tc for tc in db.query(EvaluationTestCase).filter(
            EvaluationTestCase.id.in_({r.test_case_id for r in runs.values()})).all()}
        work = [
            _BatchItem(run_id, runs[run_id].session_id, runs[run_id].test_case_id,
                       tcs[runs[run_id].test_case_id].name, _evaluator_set(tcs[runs[run_id].test_case_id]),
                       tcs[runs[run_id].test_case_id].model_id, prompt)
            for run_id, prompt in items if run_id in runs and runs[run_id].test_case_id in tcs
        ]
        arn, region, agent_name = agent.arn, agent.region, agent.name
        log_group = derive_log_group(agent.runtime_id, "DEFAULT")
        _warm_boto3_clients(region)

        with ThreadPoolExecutor(max_workers=_BATCH_WORKERS) as pool:
            rows = _existing_runs(db, work)
            work = [i for i in work if i.run_id in rows]
            allowed_work = []
            for item in work:
                if item.prompt is not None:
                    eff_m = resolve_effective_model_id(agent, item.model_id)
                    decision = check_usage_limits(db, user.username, user.groups or [], eff_m)
                    if decision.enforcement == "block":
                        _fail_run(
                            db,
                            rows[item.run_id],
                            f"Usage limit '{decision.limit_name}' exceeded "
                            f"({decision.current_usage}/{decision.threshold} {decision.measure})",
                        )
                        continue
                    rows[item.run_id].status = "INVOKING"
                    allowed_work.append(item)
                else:
                    allowed_work.append(item)
            work = allowed_work
            db.commit()
            invoked = {i.run_id: pool.submit(_invoke_text, arn, region, i.session_id, i.prompt, resolve_effective_model_id(agent, i.model_id),
                                             access_token)
                       for i in work if i.prompt is not None}
            rows = _existing_runs(db, work)
            live = []
            for item in work:
                if item.prompt is not None:
                    response, error = invoked[item.run_id].result()
                    if item.run_id not in rows:
                        continue
                    if error is not None:
                        _fail_run(db, rows[item.run_id], f"Failed to invoke agent: {error}")
                        continue
                    eff_m = resolve_effective_model_id(agent, item.model_id)
                    _record_invocation(
                        db,
                        agent_id,
                        item.session_id,
                        item.prompt,
                        response,
                        user.username,
                        groups=user.groups,
                        model_id=eff_m,
                        region=region,
                    )
                if item.run_id in rows:
                    live.append(item)

            rows = _existing_runs(db, live)
            live = [i for i in live if i.run_id in rows]
            for item in live:
                rows[item.run_id].status = "WAITING_FOR_LOGS"
            db.commit()
            waits = {i.run_id: pool.submit(evals.wait_for_session_spans, log_group, i.session_id, region,
                                           timeout_s=_SPAN_WAIT_S,
                                           should_stop=lambda run_id=i.run_id: _runs_stopped([run_id]))
                     for i in live}
            spans_by_run = {i.run_id: waits[i.run_id].result() for i in live}
            rows = _existing_runs(db, live)
            groups: dict[tuple[str, ...], list[_BatchItem]] = {}
            for item in live:
                if item.run_id not in rows:
                    continue
                if not evals.has_evaluatable_span(spans_by_run[item.run_id]):
                    _fail_run(db, rows[item.run_id], _spans_not_ready_message(spans_by_run[item.run_id]))
                    continue
                rows[item.run_id].status = "EVALUATING"
                groups.setdefault(item.evaluator_set, []).append(item)
            db.commit()

            run_of_session = {i.session_id: i.run_id for i in work}

            def runs_for(session_ids: list[str]) -> list[int]:
                return [run_of_session[sid] for sid in session_ids if sid in run_of_session]

            jobs = {}
            for evaluator_ids, members in groups.items():
                service_name = next((name for m in members
                                     if (name := evals.session_service_name(spans_by_run[m.run_id]))), agent_name)
                sessions = [evals.BatchSession(m.session_id, m.test_case_name,
                                               {"loom_test_case_id": str(m.test_case_id)}) for m in members]
                jobs[evaluator_ids] = pool.submit(
                    evals.run_batch_evaluation, list(evaluator_ids), sessions, service_name, log_group,
                    region, f"loom_a{agent_id}_r{members[0].run_id}_{uuid4().hex[:6]}",
                    on_job_started=lambda job_id, sids: _record_started_job(job_id, runs_for(sids)),
                    should_stop=lambda sids: _runs_stopped(runs_for(sids)),
                )
            started_jobs: set[str] = set()
            for evaluator_ids, members in groups.items():
                outcomes = jobs[evaluator_ids].result()
                rows = _existing_runs(db, members)
                for item in members:
                    outcome = outcomes.get(item.session_id) or evals.SessionOutcome(
                        [], ["No result was recorded for this session."], None)
                    started_jobs.update(outcome.job_ids)
                    run = rows.get(item.run_id)
                    if run is None:
                        continue
                    run.batch_job_id = outcome.job_id
                    run.set_batch_job_ids(run.get_batch_job_ids() + list(outcome.job_ids))
                    _record_outcome(db, run, outcome.scores, outcome.errors)
            # Jobs started for runs whose test case was deleted meanwhile: once
            # no remaining run points at them, they go the same way the test
            # case's earlier jobs went.
            orphaned = _unreferenced_batch_jobs(db, agent_id, started_jobs)
            if orphaned:
                evals.delete_batch_jobs(orphaned, region)
    finally:
        db.close()


def _record_outcome(db: Session, run: "EvaluationRun", scores: list, errors: list) -> None:
    """Record a run's scores and errors. COMPLETED needs at least one
    evaluator to have actually produced a score. Per-evaluator failures are
    kept on the run even when some other evaluator succeeded — they used to
    be discarded (only logged server-side), which made a run look like a
    single clean PASS/FAIL even when most of its evaluators silently failed.
    The frontend treats a non-empty error list alongside scores as a partial
    result, not a hard ERROR."""
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
                 user: UserInfo) -> None:
    """Do the actual work of a test case run as a background task, moving
    the run through named phases (INVOKING, WAITING_FOR_LOGS, EVALUATING) as
    it goes — not just one opaque "running" state for however long the whole
    thing takes — so the frontend has something concrete to show while it
    waits. Returning from the endpoint before any of this starts (see
    run_test_case/rescore_test_case) is what makes "Run all" feel responsive
    instead of blocking on each test case's full invoke+wait+evaluate chain
    in turn. Uses its own DB session since the request's is closed once this
    task is scheduled.

    `prompt` is None for a rescore (same session, no re-invocation). The
    caller's access to the agent is checked again here, since the route's
    check happened before this was queued.
    """
    db = SessionLocal()
    try:
        tc = db.query(EvaluationTestCase).filter(EvaluationTestCase.id == test_case_id).first()
        run = db.query(EvaluationRun).filter(EvaluationRun.id == run_id).first()
        if not tc or not run:
            return
        try:
            agent = get_agent_or_404(agent_id, db, user)
        except HTTPException as exc:
            _fail_run(db, run, f"Not scored: {exc.detail}")
            return
        if run.evaluation_mode == EVALUATION_MODE_BATCH:
            db.close()
            _execute_batch_runs([(run_id, prompt)], agent_id, access_token, user)
            return

        def stopped() -> bool:
            # Re-read: a stop (or deletion) comes from another request.
            return _runs_stopped([run_id])

        if prompt is not None:
            if stopped():
                return
            eff_model_id = resolve_effective_model_id(agent, model_id)
            decision = check_usage_limits(db, user.username, user.groups or [], eff_model_id)
            if decision.enforcement == "block":
                _fail_run(
                    db,
                    run,
                    f"Usage limit '{decision.limit_name}' exceeded "
                    f"({decision.current_usage}/{decision.threshold} {decision.measure})",
                )
                return

            run.status = "INVOKING"
            db.commit()
            response, error = _invoke_text(agent.arn, agent.region, session_id, prompt, eff_model_id, access_token)
            if stopped():
                return
            db.refresh(run)
            if error is not None:
                _fail_run(db, run, f"Failed to invoke agent: {error}")
                return
            _record_invocation(
                db,
                agent.id,
                session_id,
                prompt,
                response,
                user.username,
                groups=user.groups,
                model_id=eff_model_id,
                region=agent.region,
            )

        if stopped():
            return
        db.refresh(run)
        run.status = "WAITING_FOR_LOGS"
        db.commit()
        log_group = derive_log_group(agent.runtime_id, "DEFAULT")
        spans = evals.wait_for_session_spans(log_group, session_id, agent.region, timeout_s=_SPAN_WAIT_S,
                                             should_stop=stopped)
        if stopped():
            return
        db.refresh(run)
        if not evals.has_evaluatable_span(spans):
            _fail_run(db, run, _spans_not_ready_message(spans))
            return

        run.status = "EVALUATING"
        db.commit()
        _finish_evaluation_run(db, run, tc, spans, agent.region, stopped)
    finally:
        db.close()


def _execute_run_all(on_demand: list[tuple], batch_items: list[tuple[int, str | None]], agent_id: int,
                     region: str, access_token: str | None, user: UserInfo) -> None:
    """Run all of Run all's work concurrently: each on-demand run on its own,
    and every batch-mode run together through _execute_batch_runs."""
    _warm_boto3_clients(region)
    with ThreadPoolExecutor(max_workers=_RUN_ALL_WORKERS) as pool:
        futures = [pool.submit(_execute_run, *args) for args in on_demand]
        if batch_items:
            futures.append(pool.submit(_execute_batch_runs, batch_items, agent_id, access_token, user))
        for future in futures:
            try:
                future.result()
            except Exception:
                logger.exception("Run all: a test case run failed unexpectedly for agent %s", agent_id)


def _start_run(db: Session, tc: EvaluationTestCase, session_id: str) -> "EvaluationRun":
    """Create a PENDING run for a test case and make it the test case's latest."""
    run = EvaluationRun(test_case_id=tc.id, session_id=session_id, status="PENDING",
                        evaluation_mode=tc.evaluation_mode or DEFAULT_EVALUATION_MODE)
    db.add(run)
    db.commit()
    db.refresh(run)
    tc.last_batch_evaluation_id = str(run.id)
    tc.last_run_at = datetime.utcnow()
    db.commit()
    return run


@router.post("/{agent_id}/evaluations/test-cases/run-all", response_model=RunAllResponse)
def run_all_test_cases(
    agent_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> RunAllResponse:
    """Run every test case for this agent in the background.

    On-demand test cases run individually, as with /run. Batch-mode test
    cases are grouped by evaluator set, and each group is scored by a single
    batch job, so a suite run shows up as one job per evaluator set in the
    AgentCore console instead of one job per test case.
    """
    agent = get_agent_or_404(agent_id, db, user)
    if not agent.arn or not agent.runtime_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent has no runtime to invoke yet")
    access_token = _resolve_access_token(agent, request)

    test_cases = db.query(EvaluationTestCase).filter(EvaluationTestCase.agent_id == agent_id).order_by(
        EvaluationTestCase.created_at.asc()).all()
    entries: list[RunAllEntry] = []
    on_demand: list[tuple] = []
    batch_items: list[tuple[int, str | None]] = []
    batch_sets: set[tuple[str, ...]] = set()
    for tc in test_cases:
        run = _start_run(db, tc, str(uuid4()))
        entries.append(RunAllEntry(test_case_id=tc.id, batch_evaluation_id=str(run.id),
                                   evaluation_mode=run.evaluation_mode))
        if run.evaluation_mode == EVALUATION_MODE_BATCH:
            batch_items.append((run.id, tc.prompt))
            batch_sets.add(_evaluator_set(tc))
        else:
            on_demand.append((run.id, tc.id, agent_id, run.session_id, tc.prompt, tc.model_id,
                              access_token, user))
    if on_demand or batch_items:
        background_tasks.add_task(_execute_run_all, on_demand, batch_items, agent_id, agent.region,
                                  access_token, user)
    return RunAllResponse(runs=entries, batch_jobs=len(batch_sets))


@router.post("/{agent_id}/evaluations/test-cases/{test_case_id}/run", response_model=RunTestCaseResponse)
def run_test_case(
    agent_id: int,
    test_case_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> RunTestCaseResponse:
    """Kick off a test case run (invoke the agent, then score that session in
    the test case's evaluation mode) in the background and return immediately — the
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
    run = _start_run(db, tc, session_id)

    background_tasks.add_task(
        _execute_run, run.id, test_case_id, agent_id, session_id,
        tc.prompt, tc.model_id, access_token, user,
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
        evaluation_mode=run.evaluation_mode,
        batch_job_id=run.batch_job_id,
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

    run = _start_run(db, tc, last_run.session_id)

    background_tasks.add_task(
        _execute_run, run.id, test_case_id, agent_id, last_run.session_id,
        None, tc.model_id, None, user,
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
            evaluation_mode=r.evaluation_mode,
            batch_job_id=r.batch_job_id,
        )
        for r in runs
    ]


@router.post("/{agent_id}/evaluations/test-cases/{test_case_id}/runs/{batch_evaluation_id}/stop",
             response_model=TestCaseRunDetailResponse)
def stop_test_case_run(
    agent_id: int,
    test_case_id: int,
    batch_evaluation_id: str,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(require_scopes("agent:write")),
    db: Session = Depends(get_db),
) -> TestCaseRunDetailResponse:
    """Stop a test case run that's still in progress.

    The run is marked STOPPED straight away. Its background work checks for
    that at each phase and while polling, so nothing more is invoked, waited
    on, or scored for it. A batch job only this run was using is stopped in
    AWS (and still cleaned up when the test case is deleted); a job shared
    with other runs from the same Run all keeps going for them, and this
    run just ignores its results. An agent invocation already streaming
    can't be interrupted; its response is kept as a normal session but not
    scored.
    """
    agent = get_agent_or_404(agent_id, db, user)
    tc = _get_test_case_or_404(agent_id, test_case_id, db)
    try:
        run_id = int(batch_evaluation_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    run = db.query(EvaluationRun).filter(EvaluationRun.id == run_id, EvaluationRun.test_case_id == tc.id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status not in _RUN_IN_PROGRESS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"This run has already finished ({run.status}).")

    run.status = _RUN_STOPPED
    run.set_errors([f"Stopped by {user.username}."])
    run.updated_at = datetime.utcnow()
    db.commit()

    still_wanted: set[str] = set()
    others = db.query(EvaluationRun).join(EvaluationTestCase).filter(
        EvaluationTestCase.agent_id == agent_id, EvaluationRun.id != run.id,
        EvaluationRun.status.in_(_RUN_IN_PROGRESS))
    for other in others.all():
        still_wanted.update(other.get_batch_job_ids())
    jobs = [j for j in run.get_batch_job_ids() if j not in still_wanted]
    if jobs:
        background_tasks.add_task(evals.stop_batch_jobs, jobs, agent.region)
    return TestCaseRunDetailResponse(
        status=run.status,
        scores=[TestCaseScoreDetail(**sc) for sc in run.get_results()],
        errors=run.get_errors(),
        session_id=run.session_id,
        evaluation_mode=run.evaluation_mode,
        batch_job_id=run.batch_job_id,
    )


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
        evaluation_mode=run.evaluation_mode,
        batch_job_id=run.batch_job_id,
    )
