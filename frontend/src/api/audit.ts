import { apiFetch, BASE_URL, getAuthToken } from "./client";

export interface AuditLoginRecord {
  id: number;
  user_id: string;
  browser_session_id: string;
  logged_in_at: string;
}

export interface AuditActionRecord {
  id: number;
  user_id: string;
  browser_session_id: string;
  action_category: string;
  action_type: string;
  resource_name: string | null;
  performed_at: string;
}

export interface AuditPageViewRecord {
  id: number;
  user_id: string;
  browser_session_id: string;
  page_name: string;
  entered_at: string;
  duration_seconds: number | null;
}

export interface AuditSession {
  browser_session_id: string;
  user_id: string;
  logged_in_at: string;
  action_count: number;
  page_view_count: number;
  last_activity_at: string | null;
}

export interface AuditTimelineEvent {
  type: "login" | "action" | "page_view";
  timestamp: string;
  detail: Record<string, unknown>;
}

export interface AuditSummary {
  total_logins: number;
  total_duration: number;
  total_actions: number;
  total_page_views: number;
  actions_by_category: Record<string, number>;
  page_views_by_page: Record<string, number | { count: number; total_duration_seconds: number }>;
  logins_by_day: Array<{ date: string; count: number }>;
  actions_by_day: Array<{ date: string; count: number }>;
}

interface QueryParams {
  start?: string;
  end?: string;
  user_id?: string;
  limit?: number;
  offset?: number;
}

function buildQuery(params?: QueryParams): string {
  if (!params) return "";
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) qs.set(k, String(v));
  }
  const str = qs.toString();
  return str ? `?${str}` : "";
}

export async function recordLogin(
  userId: string,
  browserSessionId: string,
): Promise<AuditLoginRecord> {
  return apiFetch<AuditLoginRecord>("/api/admin/audit/login", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, browser_session_id: browserSessionId }),
  });
}

export async function recordAction(
  userId: string,
  browserSessionId: string,
  category: string,
  type: string,
  resourceName?: string,
): Promise<AuditActionRecord> {
  return apiFetch<AuditActionRecord>("/api/admin/audit/action", {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      browser_session_id: browserSessionId,
      action_category: category,
      action_type: type,
      resource_name: resourceName ?? null,
    }),
  });
}

export async function recordPageView(
  userId: string,
  browserSessionId: string,
  pageName: string,
  enteredAt: string,
  durationSeconds?: number,
): Promise<AuditPageViewRecord> {
  return apiFetch<AuditPageViewRecord>("/api/admin/audit/pageview", {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      browser_session_id: browserSessionId,
      page_name: pageName,
      entered_at: enteredAt,
      duration_seconds: durationSeconds ?? null,
    }),
  });
}

export async function fetchLogins(params?: QueryParams): Promise<AuditLoginRecord[]> {
  return apiFetch<AuditLoginRecord[]>(`/api/admin/audit/logins${buildQuery(params)}`);
}

export async function fetchActions(params?: QueryParams & { action_category?: string; action_type?: string }): Promise<AuditActionRecord[]> {
  const qs = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) qs.set(k, String(v));
    }
  }
  const str = qs.toString();
  return apiFetch<AuditActionRecord[]>(`/api/admin/audit/actions${str ? `?${str}` : ""}`);
}

export async function fetchPageViews(params?: QueryParams & { page_name?: string }): Promise<AuditPageViewRecord[]> {
  const qs = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) qs.set(k, String(v));
    }
  }
  const str = qs.toString();
  return apiFetch<AuditPageViewRecord[]>(`/api/admin/audit/pageviews${str ? `?${str}` : ""}`);
}

export async function fetchSessions(params?: QueryParams): Promise<AuditSession[]> {
  return apiFetch<AuditSession[]>(`/api/admin/audit/sessions${buildQuery(params)}`);
}

export async function fetchSessionTimeline(browserSessionId: string): Promise<AuditTimelineEvent[]> {
  return apiFetch<AuditTimelineEvent[]>(`/api/admin/audit/sessions/${encodeURIComponent(browserSessionId)}/timeline`);
}

export async function fetchAuditSummary(params?: QueryParams): Promise<AuditSummary> {
  return apiFetch<AuditSummary>(`/api/admin/audit/summary${buildQuery(params)}`);
}

export function trackAction(
  userId: string,
  browserSessionId: string,
  category: string,
  type: string,
  resourceName?: string,
): void {
  recordAction(userId, browserSessionId, category, type, resourceName).catch(() => {});
}

export function sendBeaconPageView(
  userId: string,
  browserSessionId: string,
  pageName: string,
  enteredAt: string,
  durationSeconds: number,
): void {
  const payload = JSON.stringify({
    user_id: userId,
    browser_session_id: browserSessionId,
    page_name: pageName,
    entered_at: enteredAt,
    duration_seconds: durationSeconds,
  });
  const url = `${BASE_URL}/api/admin/audit/pageview`;
  const headers: Record<string, string> = { type: "application/json" };
  const token = getAuthToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  navigator.sendBeacon(url, new Blob([payload], headers));
}
