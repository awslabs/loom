import { apiFetch } from "./client";
import type { TraceListResponse, TraceDetailResponse } from "./types";

export function getSessionTraces(
  agentId: number,
  sessionId: string,
): Promise<TraceListResponse> {
  return apiFetch<TraceListResponse>(
    `/api/agents/${agentId}/sessions/${encodeURIComponent(sessionId)}/traces`,
  );
}

export function getTraceDetail(
  agentId: number,
  traceId: string,
): Promise<TraceDetailResponse> {
  return apiFetch<TraceDetailResponse>(
    `/api/agents/${agentId}/traces/${encodeURIComponent(traceId)}`,
  );
}
