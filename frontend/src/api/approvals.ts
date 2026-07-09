import { apiFetch } from "./client";
import type { ApprovalPolicy, ApprovalLog } from "./types";

export function listApprovalPolicies(): Promise<ApprovalPolicy[]> {
  return apiFetch<ApprovalPolicy[]>("/api/settings/approval-policies");
}

export function getApprovalPolicy(id: number): Promise<ApprovalPolicy> {
  return apiFetch<ApprovalPolicy>(`/api/settings/approval-policies/${id}`);
}

export function createApprovalPolicy(data: {
  name: string;
  policy_type: string;
  tool_match_rules?: string[];
  approval_mode?: string;
  timeout_seconds?: number;
  agent_scope?: Record<string, unknown>;
  approval_cache_ttl?: number;
  enabled?: boolean;
}): Promise<ApprovalPolicy> {
  return apiFetch<ApprovalPolicy>("/api/settings/approval-policies", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateApprovalPolicy(
  id: number,
  data: Partial<{
    name: string;
    policy_type: string;
    tool_match_rules: string[];
    approval_mode: string;
    timeout_seconds: number;
    agent_scope: Record<string, unknown>;
    approval_cache_ttl: number;
    enabled: boolean;
  }>,
): Promise<ApprovalPolicy> {
  return apiFetch<ApprovalPolicy>(`/api/settings/approval-policies/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteApprovalPolicy(id: number): Promise<void> {
  return apiFetch<void>(`/api/settings/approval-policies/${id}`, {
    method: "DELETE",
  });
}

export function submitApprovalDecision(
  requestId: string,
  decision: "approved" | "rejected",
  reason?: string,
  content?: Record<string, unknown>,
): Promise<{ request_id: string; status: string }> {
  return apiFetch<{ request_id: string; status: string }>(
    `/api/settings/approvals/${requestId}/decide`,
    {
      method: "POST",
      body: JSON.stringify({ decision, reason, content }),
    },
  );
}

export function listApprovalLogs(params?: {
  agent_id?: number;
  session_id?: string;
  status?: string;
}): Promise<ApprovalLog[]> {
  const searchParams = new URLSearchParams();
  if (params?.agent_id) searchParams.set("agent_id", String(params.agent_id));
  if (params?.session_id) searchParams.set("session_id", params.session_id);
  if (params?.status) searchParams.set("status", params.status);
  const qs = searchParams.toString();
  return apiFetch<ApprovalLog[]>(`/api/settings/approvals/logs${qs ? `?${qs}` : ""}`);
}
