import { apiFetch } from "./client";
import type {
  EvaluationOverviewResponse,
  EvaluationResultsResponse,
  EvaluatedExchangeResponse,
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
