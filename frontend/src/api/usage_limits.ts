import { apiFetch } from "./client";
import type { UsageLimit } from "./types";

export function listUsageLimits(): Promise<UsageLimit[]> {
  return apiFetch<UsageLimit[]>("/api/settings/usage-limits");
}

export function getUsageLimit(id: number): Promise<UsageLimit> {
  return apiFetch<UsageLimit>(`/api/settings/usage-limits/${id}`);
}

export function createUsageLimit(data: {
  name: string;
  scope: Record<string, unknown>;
  target?: Record<string, unknown>;
  measure: string;
  threshold: number;
  window?: string;
  enforcement?: string;
  enabled?: boolean;
}): Promise<UsageLimit> {
  return apiFetch<UsageLimit>("/api/settings/usage-limits", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateUsageLimit(
  id: number,
  data: Partial<{
    name: string;
    scope: Record<string, unknown>;
    target: Record<string, unknown>;
    measure: string;
    threshold: number;
    window: string;
    enforcement: string;
    enabled: boolean;
  }>,
): Promise<UsageLimit> {
  return apiFetch<UsageLimit>(`/api/settings/usage-limits/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteUsageLimit(id: number): Promise<void> {
  return apiFetch<void>(`/api/settings/usage-limits/${id}`, {
    method: "DELETE",
  });
}
