import { useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ChevronsLeft, ChevronLeft, ChevronRight, ChevronsRight, LayoutList } from "lucide-react";
import { MultiSelect } from "@/components/ui/multi-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SortableTableHead, sortRows } from "@/components/SortableTableHead";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { SortDirection } from "@/components/SortableCardGrid";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  BarChart,
  Bar,
  XAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  fetchAuditSummary,
  fetchSessions,
  fetchActions,
  fetchPageViews,
  fetchSessionTimeline,
  trackAction,
} from "@/api/audit";
import { useAuth } from "@/contexts/AuthContext";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp as fmtTs } from "@/lib/format";
import { CostDashboardPage } from "@/pages/CostDashboardPage";
import type {
  AuditSummary,
  AuditSession,
  AuditActionRecord,
  AuditPageViewRecord,
  AuditTimelineEvent,
} from "@/api/audit";

type TimeRange = "7d" | "30d" | "90d" | "all";

const RANGE_DAYS: Record<TimeRange, number> = { "7d": 7, "30d": 30, "90d": 90, all: 0 };

function getDateRange(range: TimeRange, useUtc: boolean): { start?: string; end?: string } {
  if (range === "all") return {};
  const now = new Date();
  // "sv" locale produces ISO-style "YYYY-MM-DD" in the requested timezone
  const todayDate = useUtc
    ? now.toISOString().slice(0, 10)
    : now.toLocaleDateString("sv");
  const end = `${todayDate}T23:59:59`;
  const days = RANGE_DAYS[range];
  const startDate = new Date(now.getTime() - days * 86400000);
  const startStr = useUtc
    ? startDate.toISOString().slice(0, 10)
    : startDate.toLocaleDateString("sv");
  return { start: startStr, end };
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

const PAGE_SIZE = 25;

function getPageNumbers(current: number, total: number): (number | null)[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  if (current <= 4) return [1, 2, 3, 4, 5, null, total];
  if (current >= total - 3) return [1, null, total - 4, total - 3, total - 2, total - 1, total];
  return [1, null, current - 1, current, current + 1, null, total];
}

function Pagination({ page, total, onChange }: { page: number; total: number; onChange: (p: number) => void }) {
  const pages = Math.ceil(total / PAGE_SIZE);
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-between px-3 py-2 text-xs text-muted-foreground">
      <span className="font-mono text-[11px]">{page} of {pages}</span>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === 1} onClick={() => onChange(1)}><ChevronsLeft className="h-3.5 w-3.5" /></Button>
        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === 1} onClick={() => onChange(page - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
        {getPageNumbers(page, pages).map((n, i) =>
          n === null ? <span key={`e-${i}`} className="px-0.5">…</span> : <Button key={n} variant={n === page ? "default" : "ghost"} size="icon" className="h-6 w-6 text-xs" onClick={() => onChange(n)}>{n}</Button>
        )}
        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page * PAGE_SIZE >= total} onClick={() => onChange(page + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page * PAGE_SIZE >= total} onClick={() => onChange(pages)}><ChevronsRight className="h-3.5 w-3.5" /></Button>
      </div>
    </div>
  );
}

interface AdminDashboardPageProps {
  canViewSessions?: boolean;
  canViewCosts?: boolean;
  canEditCosts?: boolean;
  costsGroupRestriction?: string;
}

export function AdminDashboardPage({
  canViewSessions = true,
  canViewCosts = false,
  costsGroupRestriction,
}: AdminDashboardPageProps) {
  const { user, browserSessionId } = useAuth();
  const { timezone } = useTimezone();
  const useUtc = timezone === "UTC";
  const [analyticsTab, setAnalyticsTab] = useState<"costs" | "activity">(canViewCosts ? "costs" : "activity");
  const [timeRange, setTimeRange] = useState<TimeRange>("7d");
  const [summary, setSummary] = useState<AuditSummary | null>(null);
  const [sessions, setSessions] = useState<AuditSession[]>([]);
  const [actions, setActions] = useState<AuditActionRecord[]>([]);
  const [pageViews, setPageViews] = useState<AuditPageViewRecord[]>([]);
  const [loading, setLoading] = useState(false);

  // Filters
  const [selectedUsers, setSelectedUsers] = useState<string[]>([]);
  const [actionCategoryFilter, setActionCategoryFilter] = useState<string>("all");
  const [actionTypeFilter, setActionTypeFilter] = useState<string>("all");
  const [activityView, setActivityView] = useState<"sessions" | "actions" | "pageviews">("sessions");

  // Sort state — default to most recent first
  const [sessionSortCol, setSessionSortCol] = useState<string | null>("login_time");
  const [sessionSortDir, setSessionSortDir] = useState<SortDirection>("desc");
  const [actionSortCol, setActionSortCol] = useState<string | null>("time");
  const [actionSortDir, setActionSortDir] = useState<SortDirection>("desc");
  const [pvSortCol, setPvSortCol] = useState<string | null>("entered_at");
  const [pvSortDir, setPvSortDir] = useState<SortDirection>("desc");

  // Pagination state
  const [sessionPage, setSessionPage] = useState(1);
  const [actionPage, setActionPage] = useState(1);
  const [pvPage, setPvPage] = useState(1);

  // Session timeline
  const [selectedSession, setSelectedSession] = useState<AuditSession | null>(null);
  const [timeline, setTimeline] = useState<AuditTimelineEvent[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    const params = getDateRange(timeRange, useUtc);
    try {
      const [s, sess, act, pv] = await Promise.all([
        fetchAuditSummary(params),
        fetchSessions(params),
        fetchActions(params),
        fetchPageViews(params),
      ]);
      setSummary(s);
      setSessions(sess);
      setActions(act);
      setPageViews(pv);
      setSessionPage(1);
      setActionPage(1);
      setPvPage(1);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [timeRange, useUtc]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleSessionClick = async (session: AuditSession) => {
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "session_timeline", session.browser_session_id);
    setSelectedSession(session);
    setTimelineLoading(true);
    try {
      const tl = await fetchSessionTimeline(session.browser_session_id);
      setTimeline(tl);
    } catch {
      setTimeline([]);
    } finally {
      setTimelineLoading(false);
    }
  };

  const handleAnalyticsTabChange = (tab: string) => {
    setAnalyticsTab(tab as "costs" | "activity");
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "tab_click", `analytics_${tab}`);
  };

  // User filter
  const allUserOptions = [...new Set([
    ...sessions.map((s) => s.user_id),
    ...actions.map((a) => a.user_id),
    ...pageViews.map((p) => p.user_id),
  ])].sort();
  const userFilterActive = selectedUsers.length > 0;
  const userFilteredSessions = userFilterActive ? sessions.filter((s) => selectedUsers.includes(s.user_id)) : sessions;
  const userFilteredActions = userFilterActive ? actions.filter((a) => selectedUsers.includes(a.user_id)) : actions;
  const userFilteredPageViews = userFilterActive ? pageViews.filter((p) => selectedUsers.includes(p.user_id)) : pageViews;

  // Recompute summary from filtered data when user filter is active
  const effectiveSummary = (() => {
    if (!summary) return null;
    if (!userFilterActive) return summary;
    const loginsByDay: Record<string, number> = {};
    userFilteredSessions.forEach((s) => {
      const date = s.logged_in_at.slice(0, 10);
      loginsByDay[date] = (loginsByDay[date] ?? 0) + 1;
    });
    const actionsByDay: Record<string, number> = {};
    userFilteredActions.forEach((a) => {
      const date = a.performed_at.slice(0, 10);
      actionsByDay[date] = (actionsByDay[date] ?? 0) + 1;
    });
    const pvByPage: Record<string, number> = {};
    userFilteredPageViews.forEach((p) => {
      pvByPage[p.page_name] = (pvByPage[p.page_name] ?? 0) + 1;
    });
    const totalDuration = userFilteredSessions.reduce((sum, s) => {
      if (!s.last_activity_at) return sum;
      return sum + (new Date(s.last_activity_at).getTime() - new Date(s.logged_in_at).getTime()) / 1000;
    }, 0);
    return {
      total_logins: userFilteredSessions.length,
      total_page_views: userFilteredPageViews.length,
      total_actions: userFilteredActions.length,
      total_duration: totalDuration,
      actions_by_category: {},
      page_views_by_page: pvByPage,
      logins_by_day: Object.entries(loginsByDay).map(([date, count]) => ({ date, count })).sort((a, b) => a.date.localeCompare(b.date)),
      actions_by_day: Object.entries(actionsByDay).map(([date, count]) => ({ date, count })).sort((a, b) => a.date.localeCompare(b.date)),
    } satisfies AuditSummary;
  })();

  // Page views by day, computed client-side (the backend summary only aggregates by page name)
  const pageViewsByDay: Record<string, number> = {};
  userFilteredPageViews.forEach((p) => {
    const date = p.entered_at.slice(0, 10);
    pageViewsByDay[date] = (pageViewsByDay[date] ?? 0) + 1;
  });

  // One grouped series for the daily activity chart
  const chartDates = [...new Set([
    ...(effectiveSummary?.logins_by_day ?? []).map((d) => d.date),
    ...(effectiveSummary?.actions_by_day ?? []).map((d) => d.date),
    ...Object.keys(pageViewsByDay),
  ])].sort();
  const loginsMap = new Map((effectiveSummary?.logins_by_day ?? []).map((d) => [d.date, d.count]));
  const actionsMap = new Map((effectiveSummary?.actions_by_day ?? []).map((d) => [d.date, d.count]));
  const chartData = chartDates.map((date) => ({
    date: shortDate(date),
    logins: loginsMap.get(date) ?? 0,
    pageViews: pageViewsByDay[date] ?? 0,
    actions: actionsMap.get(date) ?? 0,
  }));
  const daysWithActivity = chartData.filter((d) => d.logins > 0 || d.pageViews > 0 || d.actions > 0).length;

  // Derived data
  const pageData = effectiveSummary
    ? Object.entries(effectiveSummary.page_views_by_page ?? {}).map(([name, raw]) => ({
        name,
        value: typeof raw === "number" ? raw : (raw as { count: number }).count,
      })).sort((a, b) => b.value - a.value)
    : [];
  const totalPageViews = pageData.reduce((s, p) => s + p.value, 0);
  const topPage = pageData[0]?.name ?? "-";

  // Sort handlers
  const handleSessionSort = (col: string) => {
    if (sessionSortCol === col) setSessionSortDir((d) => d === "asc" ? "desc" : "asc");
    else { setSessionSortCol(col); setSessionSortDir("asc"); }
    setSessionPage(1);
  };
  const handleActionSort = (col: string) => {
    if (actionSortCol === col) setActionSortDir((d) => d === "asc" ? "desc" : "asc");
    else { setActionSortCol(col); setActionSortDir("asc"); }
    setActionPage(1);
  };
  const handlePvSort = (col: string) => {
    if (pvSortCol === col) setPvSortDir((d) => d === "asc" ? "desc" : "asc");
    else { setPvSortCol(col); setPvSortDir("asc"); }
    setPvPage(1);
  };

  // Sort getters
  const sessionGetters: Record<string, (s: AuditSession) => string | number> = {
    user: (s) => s.user_id,
    session: (s) => s.browser_session_id,
    login_time: (s) => s.logged_in_at,
    last_activity: (s) => s.last_activity_at ?? "",
    duration: (s) => s.last_activity_at
      ? (new Date(s.last_activity_at).getTime() - new Date(s.logged_in_at).getTime()) / 1000
      : -1,
    actions: (s) => s.action_count,
    page_views: (s) => s.page_view_count,
  };
  const actionGetters: Record<string, (a: AuditActionRecord) => string | number> = {
    category: (a) => a.action_category,
    type: (a) => a.action_type,
    user: (a) => a.user_id,
    session: (a) => a.browser_session_id,
    resource: (a) => a.resource_name ?? "",
    time: (a) => a.performed_at,
  };
  const pvGetters: Record<string, (p: AuditPageViewRecord) => string | number> = {
    page: (p) => p.page_name,
    user: (p) => p.user_id,
    session: (p) => p.browser_session_id,
    entered_at: (p) => p.entered_at,
    exited_at: (p) => p.duration_seconds != null
      ? new Date(new Date(p.entered_at).getTime() + p.duration_seconds * 1000).toISOString()
      : "",
    duration: (p) => p.duration_seconds ?? -1,
  };

  // Unique filter values
  const categoryOptions = [...new Set(userFilteredActions.map((a) => a.action_category))].sort();
  const typeOptions = [...new Set(
    userFilteredActions
      .filter((a) => actionCategoryFilter === "all" || a.action_category === actionCategoryFilter)
      .map((a) => a.action_type),
  )].sort();

  // Filtered data
  const filteredActions = userFilteredActions.filter((a) => {
    if (actionCategoryFilter !== "all" && a.action_category !== actionCategoryFilter) return false;
    if (actionTypeFilter !== "all" && a.action_type !== actionTypeFilter) return false;
    return true;
  });

  const sortedSessions = sortRows(userFilteredSessions, sessionSortCol, sessionSortDir, sessionGetters);
  const sortedActions = sortRows(filteredActions, actionSortCol, actionSortDir, actionGetters);
  const sortedPageViews = sortRows(userFilteredPageViews, pvSortCol, pvSortDir, pvGetters);

  const pagedSessions = sortedSessions.slice((sessionPage - 1) * PAGE_SIZE, sessionPage * PAGE_SIZE);
  const pagedActions = sortedActions.slice((actionPage - 1) * PAGE_SIZE, actionPage * PAGE_SIZE);
  const pagedPageViews = sortedPageViews.slice((pvPage - 1) * PAGE_SIZE, pvPage * PAGE_SIZE);

  const metrics: [string, string][] = effectiveSummary ? [
    ["Logins", String(effectiveSummary.total_logins)],
    ["Page views", String(effectiveSummary.total_page_views)],
    ["Actions", String(effectiveSummary.total_actions)],
    ["Session time", formatDuration(effectiveSummary.total_duration)],
    ["Top page", topPage],
  ] : [];

  const handleExportCsv = (rows: Record<string, unknown>[], filename: string) => {
    if (rows.length === 0) return;
    const headers = Object.keys(rows[0]!);
    const csv = [headers.join(","), ...rows.map((r) => headers.map((h) => JSON.stringify(r[h] ?? "")).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const activityContent = (
    <div className="flex flex-col gap-4">
      {loading && !summary && <div className="text-sm text-muted-foreground">Loading activity data...</div>}

      {effectiveSummary && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="flex min-w-0 flex-col gap-4">
            {/* metrics strip + chart */}
            <Card className="gap-4 py-[18px]">
              <CardContent className="flex flex-col gap-4 px-[18px]">
                <div className="grid grid-cols-2 overflow-hidden rounded-[10px] border bg-muted sm:grid-cols-5">
                  {metrics.map(([label, value], i) => (
                    <div key={label} className={`flex flex-col gap-1 px-3.5 py-2.5 ${i < metrics.length - 1 ? "border-r" : ""}`}>
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">{label}</span>
                      <span className="truncate font-mono text-[12.5px] tabular-nums">{value}</span>
                    </div>
                  ))}
                </div>

                <div className="flex flex-col gap-2.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[13.5px] font-semibold">Activity · {timeRange === "all" ? "all time" : `last ${timeRange}`}</span>
                    <div className="ml-auto flex items-center gap-3">
                      {[["logins", "Logins", "var(--chart-1)"], ["pageViews", "Page views", "var(--chart-2)"], ["actions", "Actions", "var(--chart-3)"]].map(([key, label, color]) => (
                        <span key={key} className="flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
                          <span className="h-1.5 w-1.5 shrink-0 rounded-[2px]" style={{ background: color }} />
                          {label}
                        </span>
                      ))}
                      <span className="font-mono text-[10.5px] text-muted-foreground">{daysWithActivity} of {chartData.length} days with activity</span>
                    </div>
                  </div>
                  {chartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={180}>
                      <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }} barGap={2}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                        <Tooltip
                          cursor={{ fill: "var(--muted)", opacity: 0.5 }}
                          content={({ active, payload, label }) => {
                            if (!active || !payload?.length) return null;
                            return (
                              <div className="rounded-md border bg-card px-3 py-1.5 text-xs shadow-sm">
                                <p className="font-medium">{label}</p>
                                {payload.map((p) => (
                                  <p key={p.dataKey as string} className="text-muted-foreground">{p.name}: {p.value}</p>
                                ))}
                              </div>
                            );
                          }}
                        />
                        <Bar dataKey="logins" name="Logins" fill="var(--chart-1)" radius={[2, 2, 0, 0]} />
                        <Bar dataKey="pageViews" name="Page views" fill="var(--chart-2)" radius={[2, 2, 0, 0]} />
                        <Bar dataKey="actions" name="Actions" fill="var(--chart-3)" radius={[2, 2, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-xs text-muted-foreground">No activity in this period.</p>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* activity table */}
            <Card className="gap-0 overflow-hidden py-0">
              <div className="flex flex-wrap items-center gap-2.5 border-b px-3.5 py-2.5">
                <div className="flex items-center gap-0.5 rounded-md border bg-muted p-[3px]">
                  {(["sessions", "actions", "pageviews"] as const).map((v) => (
                    <button key={v} onClick={() => setActivityView(v)} className={`rounded-[5px] px-2.5 py-1 text-xs capitalize transition-colors ${activityView === v ? "bg-card text-foreground" : "text-muted-foreground hover:text-foreground"}`}>
                      {v === "pageviews" ? "Page views" : v}
                    </button>
                  ))}
                </div>
                {activityView === "sessions" && !selectedSession && (
                  <span className="text-xs text-muted-foreground">Click a row for the full timeline</span>
                )}
                {activityView === "actions" && (
                  <>
                    <Select value={actionCategoryFilter} onValueChange={(v) => { setActionCategoryFilter(v); setActionTypeFilter("all"); setActionPage(1); }}>
                      <SelectTrigger className="h-7 w-40 text-xs"><SelectValue placeholder="Category" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All categories</SelectItem>
                        {categoryOptions.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Select value={actionTypeFilter} onValueChange={(v) => { setActionTypeFilter(v); setActionPage(1); }}>
                      <SelectTrigger className="h-7 w-40 text-xs"><SelectValue placeholder="Type" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All types</SelectItem>
                        {typeOptions.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </>
                )}
                <span className="ml-auto font-mono text-[10.5px] text-muted-foreground tabular-nums">
                  {activityView === "sessions" ? `${sortedSessions.length} of ${sortedSessions.length}` : activityView === "actions" ? `${sortedActions.length} of ${sortedActions.length}` : `${sortedPageViews.length} of ${sortedPageViews.length}`}
                </span>
              </div>

              {activityView === "sessions" && (
                selectedSession ? (
                  <div className="flex flex-col gap-3 p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="font-mono text-sm font-medium">Session {selectedSession.browser_session_id}</h3>
                        <p className="text-xs text-muted-foreground">User: {selectedSession.user_id} · Login: {fmtTs(selectedSession.logged_in_at, timezone)}</p>
                      </div>
                      <button onClick={() => setSelectedSession(null)} className="text-xs text-primary hover:underline">Back to sessions</button>
                    </div>
                    {timelineLoading ? (
                      <p className="text-xs text-muted-foreground">Loading timeline...</p>
                    ) : timeline.length === 0 ? (
                      <p className="text-xs text-muted-foreground">No timeline events</p>
                    ) : (
                      <div className="overflow-hidden rounded-md border">
                        <Table>
                          <TableHeader>
                            <TableRow className="bg-muted hover:bg-muted">
                              <TableHead className="text-xs">Type</TableHead>
                              <TableHead className="text-xs">Action</TableHead>
                              <TableHead className="text-xs">Entered</TableHead>
                              <TableHead className="text-xs">Duration</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {timeline.map((evt, i) => (
                              <TableRow key={i}>
                                <TableCell className="text-xs">
                                  <span className="rounded-full border bg-muted px-2 py-0.5 font-mono text-[10px]">{evt.type}</span>
                                </TableCell>
                                <TableCell className="text-xs text-muted-foreground">
                                  {evt.type === "action"
                                    ? `${evt.detail.action_category ?? ""} / ${evt.detail.action_type ?? ""}${evt.detail.resource_name ? ` (${evt.detail.resource_name})` : ""}`
                                    : evt.type === "page_view" ? String(evt.detail.page_name ?? "") : "Logged in"}
                                </TableCell>
                                <TableCell className="font-mono text-xs">{fmtTs(evt.timestamp, timezone)}</TableCell>
                                <TableCell className="font-mono text-xs">
                                  {evt.type === "page_view" && evt.detail.duration_seconds != null ? formatDuration(evt.detail.duration_seconds as number) : "-"}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </div>
                ) : sessions.length === 0 ? (
                  <p className="p-4 text-sm text-muted-foreground">No sessions found</p>
                ) : (
                  <>
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-muted hover:bg-muted">
                          <SortableTableHead column="session" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort}>Session</SortableTableHead>
                          <SortableTableHead column="user" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort}>User</SortableTableHead>
                          <SortableTableHead column="login_time" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort}>Login</SortableTableHead>
                          <SortableTableHead column="page_views" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort} className="text-right">Views</SortableTableHead>
                          <SortableTableHead column="actions" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort} className="text-right">Actions</SortableTableHead>
                          <SortableTableHead column="duration" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort} className="text-right">Duration</SortableTableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {pagedSessions.map((s) => (
                          <TableRow key={s.browser_session_id} className="cursor-pointer" onClick={() => void handleSessionClick(s)}>
                            <TableCell className="font-mono text-xs">
                              <span className="flex items-center gap-1.5">
                                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-success" />
                                <span className="truncate">{s.browser_session_id.slice(0, 18)}</span>
                              </span>
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">{s.user_id}</TableCell>
                            <TableCell className="font-mono text-xs text-muted-foreground">{fmtTs(s.logged_in_at, timezone)}</TableCell>
                            <TableCell className="text-right font-mono text-xs tabular-nums">{s.page_view_count}</TableCell>
                            <TableCell className="text-right font-mono text-xs tabular-nums">{s.action_count}</TableCell>
                            <TableCell className="text-right font-mono text-xs tabular-nums">
                              {s.last_activity_at ? formatDuration((new Date(s.last_activity_at).getTime() - new Date(s.logged_in_at).getTime()) / 1000) : "-"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    <Pagination page={sessionPage} total={sortedSessions.length} onChange={setSessionPage} />
                  </>
                )
              )}

              {activityView === "actions" && (
                filteredActions.length === 0 ? (
                  <p className="p-4 text-sm text-muted-foreground">No actions found</p>
                ) : (
                  <>
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-muted hover:bg-muted">
                          <SortableTableHead column="session" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Session</SortableTableHead>
                          <SortableTableHead column="category" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Category</SortableTableHead>
                          <SortableTableHead column="type" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Type</SortableTableHead>
                          <SortableTableHead column="user" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>User</SortableTableHead>
                          <SortableTableHead column="resource" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Resource</SortableTableHead>
                          <SortableTableHead column="time" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Time</SortableTableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {pagedActions.map((a) => (
                          <TableRow key={a.id}>
                            <TableCell className="font-mono text-xs">{a.browser_session_id.slice(0, 18)}</TableCell>
                            <TableCell className="text-xs">{a.action_category}</TableCell>
                            <TableCell className="text-xs">{a.action_type}</TableCell>
                            <TableCell className="text-xs text-muted-foreground">{a.user_id}</TableCell>
                            <TableCell className="text-xs text-muted-foreground">{a.resource_name ?? "-"}</TableCell>
                            <TableCell className="font-mono text-xs text-muted-foreground">{fmtTs(a.performed_at, timezone)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    <Pagination page={actionPage} total={sortedActions.length} onChange={setActionPage} />
                  </>
                )
              )}

              {activityView === "pageviews" && (
                userFilteredPageViews.length === 0 ? (
                  <p className="p-4 text-sm text-muted-foreground">No page views found</p>
                ) : (
                  <>
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-muted hover:bg-muted">
                          <SortableTableHead column="session" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>Session</SortableTableHead>
                          <SortableTableHead column="page" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>Page</SortableTableHead>
                          <SortableTableHead column="user" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>User</SortableTableHead>
                          <SortableTableHead column="entered_at" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>Entered</SortableTableHead>
                          <SortableTableHead column="duration" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort} className="text-right">Duration</SortableTableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {pagedPageViews.map((p) => (
                          <TableRow key={p.id}>
                            <TableCell className="font-mono text-xs">{p.browser_session_id.slice(0, 18)}</TableCell>
                            <TableCell className="text-xs">{p.page_name}</TableCell>
                            <TableCell className="text-xs text-muted-foreground">{p.user_id}</TableCell>
                            <TableCell className="font-mono text-xs text-muted-foreground">{fmtTs(p.entered_at, timezone)}</TableCell>
                            <TableCell className="text-right font-mono text-xs tabular-nums">{formatDuration(p.duration_seconds)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    <Pagination page={pvPage} total={sortedPageViews.length} onChange={setPvPage} />
                  </>
                )
              )}
            </Card>
          </div>

          {/* rail */}
          <div className="flex flex-col gap-3.5">
            <Card className="gap-3 py-4">
              <CardContent className="flex flex-col gap-3 px-4">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold">Top pages</span>
                  <span className="ml-auto font-mono text-[10.5px] text-muted-foreground">{totalPageViews} view{totalPageViews === 1 ? "" : "s"}</span>
                </div>
                {pageData.length === 0 ? (
                  <p className="text-[11.5px] text-muted-foreground">No pages viewed in this window.</p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {pageData.slice(0, 6).map((p) => (
                      <div key={p.name} className="flex flex-col gap-1">
                        <div className="flex items-center justify-between font-mono text-[11.5px]">
                          <span className="truncate">{p.name}</span>
                          <span className="tabular-nums">{p.value}</span>
                        </div>
                        <div className="h-1 overflow-hidden rounded-full bg-input-bg">
                          <div className="h-full rounded-full bg-primary" style={{ width: `${(p.value / (pageData[0]?.value || 1)) * 100}%` }} />
                        </div>
                      </div>
                    ))}
                    {pageData.length <= 1 && <p className="text-[11.5px] leading-[1.5] text-muted-foreground">No other pages were visited in this window.</p>}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="gap-3 py-4">
              <CardContent className="flex flex-col gap-3 px-4">
                <span className="text-[13px] font-semibold">Audit trail</span>
                {sortedActions.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-6 text-center">
                    <div className="rounded-lg border bg-muted p-2"><LayoutList className="h-4 w-4 text-muted-foreground" /></div>
                    <p className="text-[12.5px] font-medium">No actions recorded</p>
                    <p className="text-[12px] leading-[1.5] text-muted-foreground">Create, update, approve, and delete events appear here as users work.</p>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {sortedActions.slice(0, 5).map((a) => (
                      <div key={a.id} className="flex items-center justify-between gap-2 font-mono text-[11px]">
                        <span className="truncate text-muted-foreground">{a.action_category}/{a.action_type}</span>
                        <span className="shrink-0 text-muted-foreground">{fmtTs(a.performed_at, timezone).split(",")[0]}</span>
                      </div>
                    ))}
                    <button type="button" onClick={() => setActivityView("actions")} className="self-end font-mono text-[10.5px] text-primary hover:underline">view all →</button>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="gap-2.5 py-4">
              <CardContent className="flex flex-col gap-2.5 px-4">
                <span className="text-[13px] font-semibold">Export</span>
                <p className="text-[12.5px] leading-[1.55] text-muted-foreground">Sessions, actions, and page views for the selected window and user filter.</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleExportCsv(
                    activityView === "sessions" ? (sortedSessions as unknown as Record<string, unknown>[])
                      : activityView === "actions" ? (sortedActions as unknown as Record<string, unknown>[])
                      : (sortedPageViews as unknown as Record<string, unknown>[]),
                    `loom-${activityView}-${timeRange}.csv`,
                  )}
                >
                  Download CSV
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );

  const costsContent = (
    <CostDashboardPage groupRestriction={costsGroupRestriction} days={RANGE_DAYS[timeRange]} />
  );

  const showTabs = canViewSessions && canViewCosts;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Analytics</h2>
          <p className="text-sm text-muted-foreground">Spend and usage across the platform.</p>
        </div>
        <div className="flex items-center gap-2.5">
          {analyticsTab === "activity" && allUserOptions.length > 0 && (
            <MultiSelect
              values={selectedUsers}
              options={allUserOptions}
              onChange={(v) => { setSelectedUsers(v); setSessionPage(1); setActionPage(1); setPvPage(1); }}
              placeholder="All users"
            />
          )}
          <div className="flex items-center gap-0.5 rounded-md border bg-input-bg p-[3px]">
            {(["7d", "30d", "90d", "all"] as TimeRange[]).map((r) => (
              <button
                key={r}
                onClick={() => setTimeRange(r)}
                className={`rounded-[5px] px-2.5 py-1 text-xs transition-colors ${timeRange === r ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"}`}
              >
                {r === "all" ? "All" : r}
              </button>
            ))}
          </div>
          {analyticsTab === "activity" && (
            <Button variant="outline" size="sm" onClick={() => handleExportCsv(sortedSessions as unknown as Record<string, unknown>[], `loom-sessions-${timeRange}.csv`)}>Export CSV</Button>
          )}
        </div>
      </div>

      {showTabs ? (
        <Tabs value={analyticsTab} onValueChange={handleAnalyticsTabChange}>
          <TabsList variant="line" className="h-auto justify-start gap-5 rounded-none border-b bg-transparent p-0">
            <TabsTrigger value="costs" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">Costs</TabsTrigger>
            <TabsTrigger value="activity" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">User activity</TabsTrigger>
          </TabsList>
          <TabsContent value="costs" className="pt-4">{costsContent}</TabsContent>
          <TabsContent value="activity" className="pt-4">{activityContent}</TabsContent>
        </Tabs>
      ) : canViewCosts ? costsContent : activityContent}
    </div>
  );
}
