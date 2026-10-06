import { apiFetch } from "./client";
import type {
  EvaluationOverviewResponse,
  EvaluationResultsResponse,
  EvaluatedExchangeResponse,
  EvaluatorInfo,
  EvaluationTestCase,
  EvaluationTestCaseRequest,
  RunTestCaseResponse,
  TestCaseRunDetailResponse,
  TestCaseRunSummary,
} from "./types";

export type EvaluationSourceType = "online" | "batch";

/** Online configs and batch runs that evaluate this agent. */
export function getAgentEvaluations(agentId: number): Promise<EvaluationOverviewResponse> {
  return apiFetch<EvaluationOverviewResponse>(`/api/agents/${agentId}/evaluations`);
}

/** Per-trace scores from one evaluation source. `days` applies to online sources. */
export function getEvaluationResults(
  agentId: number,
  sourceType: EvaluationSourceType,
  sourceId: string,
  days = 7,
): Promise<EvaluationResultsResponse> {
  const qs = new URLSearchParams({ source_type: sourceType, source_id: sourceId, days: String(days) });
  return apiFetch<EvaluationResultsResponse>(`/api/agents/${agentId}/evaluations/results?${qs.toString()}`);
}

/** The prompt and answer of one evaluated trace. */
export function getEvaluatedExchange(agentId: number, traceId: string): Promise<EvaluatedExchangeResponse> {
  return apiFetch<EvaluatedExchangeResponse>(
    `/api/agents/${agentId}/evaluations/traces/${encodeURIComponent(traceId)}/exchange`,
  );
}

/** Evaluators available to pick for a test case (built-in + any custom). */
export function listEvaluators(agentId: number): Promise<EvaluatorInfo[]> {
  return apiFetch<EvaluatorInfo[]>(`/api/agents/${agentId}/evaluations/evaluators`);
}

/** Saved test cases for this agent. */
export function listTestCases(agentId: number): Promise<EvaluationTestCase[]> {
  return apiFetch<EvaluationTestCase[]>(`/api/agents/${agentId}/evaluations/test-cases`);
}

export function createTestCase(
  agentId: number,
  request: EvaluationTestCaseRequest,
): Promise<EvaluationTestCase> {
  return apiFetch<EvaluationTestCase>(`/api/agents/${agentId}/evaluations/test-cases`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function updateTestCase(
  agentId: number,
  testCaseId: number,
  request: EvaluationTestCaseRequest,
): Promise<EvaluationTestCase> {
  return apiFetch<EvaluationTestCase>(`/api/agents/${agentId}/evaluations/test-cases/${testCaseId}`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export function deleteTestCase(agentId: number, testCaseId: number): Promise<void> {
  return apiFetch<void>(`/api/agents/${agentId}/evaluations/test-cases/${testCaseId}`, {
    method: "DELETE",
  });
}

/** Invoke the agent with the test case's prompt, then start a batch evaluation scoped to that run. */
export function runTestCase(agentId: number, testCaseId: number): Promise<RunTestCaseResponse> {
  return apiFetch<RunTestCaseResponse>(`/api/agents/${agentId}/evaluations/test-cases/${testCaseId}/run`, {
    method: "POST",
  });
}

/** Status and per-evaluator scores for a test case's latest run. */
export function getTestCaseLastRun(agentId: number, testCaseId: number): Promise<TestCaseRunDetailResponse> {
  return apiFetch<TestCaseRunDetailResponse>(
    `/api/agents/${agentId}/evaluations/test-cases/${testCaseId}/last-run`,
  );
}

/** Re-score the test case's last run's session without re-invoking the agent. */
export function rescoreTestCase(agentId: number, testCaseId: number): Promise<RunTestCaseResponse> {
  return apiFetch<RunTestCaseResponse>(`/api/agents/${agentId}/evaluations/test-cases/${testCaseId}/rescore`, {
    method: "POST",
  });
}

/** Every past run of this test case, newest first, including failed ones. */
export function listTestCaseRuns(agentId: number, testCaseId: number): Promise<TestCaseRunSummary[]> {
  return apiFetch<TestCaseRunSummary[]>(
    `/api/agents/${agentId}/evaluations/test-cases/${testCaseId}/runs`,
  );
}

/** Status, scores, and failure reasons for one specific past run. */
export function getTestCaseRun(
  agentId: number,
  testCaseId: number,
  batchEvaluationId: string,
): Promise<TestCaseRunDetailResponse> {
  return apiFetch<TestCaseRunDetailResponse>(
    `/api/agents/${agentId}/evaluations/test-cases/${testCaseId}/runs/${encodeURIComponent(batchEvaluationId)}`,
  );
}
