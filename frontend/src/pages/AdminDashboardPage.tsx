import { useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChevronsLeft, ChevronLeft, ChevronRight, ChevronsRight } from "lucide-react";
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
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LabelList,
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
import type {
  AuditSummary,
  AuditSession,
  AuditActionRecord,
  AuditPageViewRecord,
  AuditTimelineEvent,
} from "@/api/audit";

type TimeRange = "today" | "7d" | "30d" | "all";

function getDateRange(range: TimeRange, useUtc: boolean): { start?: string; end?: string } {
  if (range === "all") return {};
  const now = new Date();
  // "sv" locale produces ISO-style "YYYY-MM-DD" in the requested timezone
  const todayDate = useUtc
    ? now.toISOString().slice(0, 10)
    : now.toLocaleDateString("sv");
  const end = `${todayDate}T23:59:59`;
  if (range === "today") return { start: todayDate, end };
  const days = range === "7d" ? 7 : 30;
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

const PAGE_SIZE = 25;

function getPageNumbers(current: number, total: number): (number | null)[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  if (current <= 4) return [1, 2, 3, 4, 5, null, total];
  if (current >= total - 3) return [1, null, total - 4, total - 3, total - 2, total - 1, total];
  return [1, null, current - 1, current, current + 1, null, total];
}

export function AdminDashboardPage() {
  const { user, browserSessionId } = useAuth();
  const { timezone } = useTimezone();
  const useUtc = timezone === "UTC";
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
  const [pageNameFilter, setPageNameFilter] = useState<string>("all");

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

  const handleAdminTabChange = (tab: string) => {
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "tab_click", `admin_${tab}`);
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

  // Derived data for charts
  // Backend returns page_views_by_page values as {count, total_duration_seconds} objects
  const pageData = effectiveSummary
    ? Object.entries(effectiveSummary.page_views_by_page ?? {}).map(([name, raw]) => ({
        name,
        value: typeof raw === "number" ? raw : (raw as { count: number }).count,
      }))
    : [];
  const mostActivePage = pageData.length > 0
    ? pageData.reduce((a, b) => (b.value > a.value ? b : a)).name
    : "-";

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
  const pageOptions = [...new Set(userFilteredPageViews.map((p) => p.page_name))].sort();

  // Filtered data
  const filteredActions = userFilteredActions.filter((a) => {
    if (actionCategoryFilter !== "all" && a.action_category !== actionCategoryFilter) return false;
    if (actionTypeFilter !== "all" && a.action_type !== actionTypeFilter) return false;
    return true;
  });
  const filteredPageViews = pageNameFilter !== "all"
    ? userFilteredPageViews.filter((p) => p.page_name === pageNameFilter)
    : userFilteredPageViews;

  const sortedSessions = sortRows(userFilteredSessions, sessionSortCol, sessionSortDir, sessionGetters);
  const sortedActions = sortRows(filteredActions, actionSortCol, actionSortDir, actionGetters);
  const sortedPageViews = sortRows(filteredPageViews, pvSortCol, pvSortDir, pvGetters);

  const pagedSessions = sortedSessions.slice((sessionPage - 1) * PAGE_SIZE, sessionPage * PAGE_SIZE);
  const pagedActions = sortedActions.slice((actionPage - 1) * PAGE_SIZE, actionPage * PAGE_SIZE);
  const pagedPageViews = sortedPageViews.slice((pvPage - 1) * PAGE_SIZE, pvPage * PAGE_SIZE);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Admin Dashboard</h2>
          <p className="text-sm text-muted-foreground">User activity and audit trail</p>
        </div>
        <div className="flex items-center gap-3">
          {allUserOptions.length > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Users:</span>
              <MultiSelect
                values={selectedUsers}
                options={allUserOptions}
                onChange={(v) => { setSelectedUsers(v); setSessionPage(1); setActionPage(1); setPvPage(1); }}
                placeholder="All users"
              />
            </div>
          )}
          <div className="flex items-center gap-2">
            {(["today", "7d", "30d", "all"] as TimeRange[]).map((r) => (
              <button
                key={r}
                onClick={() => setTimeRange(r)}
                className={`px-3 py-1 text-xs rounded-md border transition-colors ${
                  timeRange === r
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-accent"
                }`}
              >
                {r === "today" ? "Today" : r === "all" ? "All" : r}
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading && !summary && (
        <div className="text-sm text-muted-foreground">Loading audit data...</div>
      )}

      {effectiveSummary && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <Card>
              <CardContent className="pt-2 pb-2">
                <div className="text-xs text-muted-foreground">Total Logins</div>
                <div className="bg-white dark:bg-background rounded-md px-2 py-1 mt-1">
                  <div className="text-xl font-mono font-semibold">{effectiveSummary.total_logins}</div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-2 pb-2">
                <div className="text-xs text-muted-foreground">Total Page Views</div>
                <div className="bg-white dark:bg-background rounded-md px-2 py-1 mt-1">
                  <div className="text-xl font-mono font-semibold">{effectiveSummary.total_page_views}</div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-2 pb-2">
                <div className="text-xs text-muted-foreground">Total Actions</div>
                <div className="bg-white dark:bg-background rounded-md px-2 py-1 mt-1">
                  <div className="text-xl font-mono font-semibold">{effectiveSummary.total_actions}</div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-2 pb-2">
                <div className="text-xs text-muted-foreground">Total Duration</div>
                <div className="bg-white dark:bg-background rounded-md px-2 py-1 mt-1">
                  <div className="text-xl font-mono font-semibold">{formatDuration(effectiveSummary.total_duration)}</div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-2 pb-2">
                <div className="text-xs text-muted-foreground">Most Active Page</div>
                <div className="bg-white dark:bg-background rounded-md px-2 py-1 mt-1">
                  <div className="text-xl font-mono font-semibold truncate">{mostActivePage}</div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Logins Over Time</CardTitle>
              </CardHeader>
              <CardContent className="pb-3">
                {(effectiveSummary.logins_by_day?.length ?? 0) > 0 ? (
                  <div className="bg-white dark:bg-background rounded-md pt-2 px-2 pb-0">
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={effectiveSummary.logins_by_day ?? []} margin={{ top: 16, right: 10, bottom: 0, left: -20 }}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 10 }} allowDecimals={false} width={28} />
                        <Tooltip
                          cursor={{ fill: "var(--muted, #f1f5f9)", opacity: 0.5 }}
                          content={({ active, payload }) => {
                            if (!active || !payload?.length || !payload[0]) return null;
                            const d = payload[0].payload as { date: string; count: number };
                            return (
                              <div className="rounded-md border bg-background px-3 py-1.5 text-xs shadow-sm">
                                <p className="font-medium">{d.date}</p>
                                <p className="text-muted-foreground">{d.count} logins</p>
                              </div>
                            );
                          }}
                        />
                        <Bar dataKey="count" fill="var(--chart-1, #2563eb)" radius={[2, 2, 0, 0]}>
                          <LabelList dataKey="count" position="top" style={{ fontSize: 9, fill: "currentColor" }} />
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">No login data</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Actions Over Time</CardTitle>
              </CardHeader>
              <CardContent className="pb-3">
                {(effectiveSummary.actions_by_day?.length ?? 0) > 0 ? (
                  <div className="bg-white dark:bg-background rounded-md pt-2 px-2 pb-0">
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={effectiveSummary.actions_by_day ?? []} margin={{ top: 16, right: 10, bottom: 0, left: -20 }}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 10 }} allowDecimals={false} width={28} />
                        <Tooltip
                          cursor={{ fill: "var(--muted, #f1f5f9)", opacity: 0.5 }}
                          content={({ active, payload }) => {
                            if (!active || !payload?.length || !payload[0]) return null;
                            const d = payload[0].payload as { date: string; count: number };
                            return (
                              <div className="rounded-md border bg-background px-3 py-1.5 text-xs shadow-sm">
                                <p className="font-medium">{d.date}</p>
                                <p className="text-muted-foreground">{d.count} actions</p>
                              </div>
                            );
                          }}
                        />
                        <Bar dataKey="count" fill="var(--chart-3, #ea580c)" radius={[2, 2, 0, 0]}>
                          <LabelList dataKey="count" position="top" style={{ fontSize: 9, fill: "currentColor" }} />
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">No action data</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Page Views</CardTitle>
              </CardHeader>
              <CardContent className="pb-3">
                {pageData.length > 0 ? (
                  <div className="bg-white dark:bg-background rounded-md pt-2 px-2 pb-0">
                    <ResponsiveContainer width="100%" height={Math.max(150, pageData.length * 20)}>
                      <BarChart data={pageData} layout="vertical" margin={{ top: 4, right: 30, bottom: 0, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-border" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 10 }} allowDecimals={false} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={50} interval={0} />
                        <Tooltip
                          cursor={{ fill: "var(--muted, #f1f5f9)", opacity: 0.5 }}
                          content={({ active, payload }) => {
                            if (!active || !payload?.length || !payload[0]) return null;
                            const d = payload[0].payload as { name: string; value: number };
                            return (
                              <div className="rounded-md border bg-background px-3 py-1.5 text-xs shadow-sm">
                                <p className="font-medium">{d.name}</p>
                                <p className="text-muted-foreground">{d.value} views</p>
                              </div>
                            );
                          }}
                        />
                        <Bar dataKey="value" fill="var(--chart-2, #16a34a)" radius={[0, 2, 2, 0]}>
                          <LabelList dataKey="value" position="right" style={{ fontSize: 9, fill: "currentColor" }} />
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">No page view data</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Tabbed section */}
          <Tabs defaultValue="sessions" onValueChange={handleAdminTabChange}>
            <TabsList>
              <TabsTrigger value="sessions">Sessions</TabsTrigger>
              <TabsTrigger value="actions">Actions</TabsTrigger>
              <TabsTrigger value="pageviews">Page Views</TabsTrigger>
            </TabsList>

            {/* Sessions Tab */}
            <TabsContent value="sessions">
              <Card className="bg-muted/30 mt-2">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium">Browser Sessions</CardTitle>
                  <p className="text-xs text-muted-foreground">Each row is a unique browser session. Click a row to see the full activity timeline.</p>
                </CardHeader>
                <CardContent>
                  {selectedSession ? (
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <h3 className="text-sm font-medium font-mono">
                            Session {selectedSession.browser_session_id}
                          </h3>
                          <p className="text-xs text-muted-foreground">
                            User: {selectedSession.user_id} | Login: {fmtTs(selectedSession.logged_in_at, timezone)}
                          </p>
                        </div>
                        <button
                          onClick={() => setSelectedSession(null)}
                          className="text-xs text-muted-foreground hover:text-foreground"
                        >
                          Back to sessions
                        </button>
                      </div>
                      {timelineLoading ? (
                        <p className="text-xs text-muted-foreground">Loading timeline...</p>
                      ) : timeline.length === 0 ? (
                        <p className="text-xs text-muted-foreground">No timeline events</p>
                      ) : (
                        <div className="border rounded-md overflow-hidden">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="text-xs">Type</TableHead>
                                <TableHead className="text-xs">Action</TableHead>
                                <TableHead className="text-xs">Entered At</TableHead>
                                <TableHead className="text-xs">Exited At</TableHead>
                                <TableHead className="text-xs">Duration</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {timeline.map((evt, i) => {
                                const exitedAt = evt.type === "page_view" && evt.detail.duration_seconds != null
                                  ? new Date(new Date(evt.timestamp).getTime() + (evt.detail.duration_seconds as number) * 1000).toISOString()
                                  : null;
                                return (
                                  <TableRow key={i} className="bg-white dark:bg-transparent hover:bg-muted/50 dark:hover:bg-muted/20">
                                    <TableCell className="text-xs">
                                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                                        evt.type === "login"
                                          ? "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
                                          : evt.type === "action"
                                            ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                                            : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                                      }`}>
                                        {evt.type}
                                      </span>
                                    </TableCell>
                                    <TableCell className="text-xs text-muted-foreground">
                                      {evt.type === "action"
                                        ? `${evt.detail.action_category ?? ""} / ${evt.detail.action_type ?? ""}${evt.detail.resource_name ? ` (${evt.detail.resource_name})` : ""}`
                                        : evt.type === "page_view"
                                          ? String(evt.detail.page_name ?? "")
                                          : "Logged in"}
                                    </TableCell>
                                    <TableCell className="text-xs font-mono">{fmtTs(evt.timestamp, timezone)}</TableCell>
                                    <TableCell className="text-xs font-mono">
                                      {exitedAt ? fmtTs(exitedAt, timezone) : "-"}
                                    </TableCell>
                                    <TableCell className="text-xs font-mono">
                                      {evt.type === "page_view" && evt.detail.duration_seconds != null
                                        ? formatDuration(evt.detail.duration_seconds as number)
                                        : "-"}
                                    </TableCell>
                                  </TableRow>
                                );
                              })}
                            </TableBody>
                          </Table>
                        </div>
                      )}
                    </div>
                  ) : sessions.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No sessions found</p>
                  ) : (
                    <>
                    <div className="flex items-center justify-between px-2 pb-2 text-xs text-muted-foreground">
                      <span>Showing {(sessionPage - 1) * PAGE_SIZE + 1}–{Math.min(sessionPage * PAGE_SIZE, sortedSessions.length)} of {sortedSessions.length}</span>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={sessionPage === 1} onClick={() => setSessionPage(1)}><ChevronsLeft className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={sessionPage === 1} onClick={() => setSessionPage((p) => p - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
                        {getPageNumbers(sessionPage, Math.ceil(sortedSessions.length / PAGE_SIZE)).map((n, i) =>
                          n === null ? <span key={`e-${i}`} className="px-0.5">…</span> : <Button key={n} variant={n === sessionPage ? "default" : "ghost"} size="icon" className="h-6 w-6 text-xs" onClick={() => setSessionPage(n)}>{n}</Button>
                        )}
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={sessionPage * PAGE_SIZE >= sortedSessions.length} onClick={() => setSessionPage((p) => p + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={sessionPage * PAGE_SIZE >= sortedSessions.length} onClick={() => setSessionPage(Math.ceil(sortedSessions.length / PAGE_SIZE))}><ChevronsRight className="h-3.5 w-3.5" /></Button>
                      </div>
                    </div>
                    <div className="border rounded-md overflow-hidden">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <SortableTableHead column="session" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort}>Browser Session</SortableTableHead>
                            <SortableTableHead column="user" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort}>User</SortableTableHead>
                            <SortableTableHead column="login_time" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort}>Login Time</SortableTableHead>
                            <SortableTableHead column="last_activity" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort}>Last Activity</SortableTableHead>
                            <SortableTableHead column="page_views" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort} className="text-right">Page Views</SortableTableHead>
                            <SortableTableHead column="actions" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort} className="text-right">Actions</SortableTableHead>
                            <SortableTableHead column="duration" activeColumn={sessionSortCol} direction={sessionSortDir} onSort={handleSessionSort} className="text-right">Duration</SortableTableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {pagedSessions.map((s) => (
                            <TableRow
                              key={s.browser_session_id}
                              className="bg-white dark:bg-transparent cursor-pointer hover:bg-muted/50 dark:hover:bg-muted/20"
                              onClick={() => void handleSessionClick(s)}
                            >
                              <TableCell className="text-xs font-mono">{s.browser_session_id}</TableCell>
                              <TableCell className="text-xs">{s.user_id}</TableCell>
                              <TableCell className="text-xs font-mono">{fmtTs(s.logged_in_at, timezone)}</TableCell>
                              <TableCell className="text-xs font-mono">
                                {s.last_activity_at ? fmtTs(s.last_activity_at, timezone) : "-"}
                              </TableCell>
                              <TableCell className="text-xs text-right font-mono">{s.page_view_count}</TableCell>
                              <TableCell className="text-xs text-right font-mono">{s.action_count}</TableCell>
                              <TableCell className="text-xs text-right font-mono">
                                {s.last_activity_at
                                  ? formatDuration((new Date(s.last_activity_at).getTime() - new Date(s.logged_in_at).getTime()) / 1000)
                                  : "-"}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                    <div className="flex items-center justify-between px-2 pt-2 text-xs text-muted-foreground">
                      <span>Showing {(sessionPage - 1) * PAGE_SIZE + 1}–{Math.min(sessionPage * PAGE_SIZE, sortedSessions.length)} of {sortedSessions.length}</span>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={sessionPage === 1} onClick={() => setSessionPage(1)}><ChevronsLeft className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={sessionPage === 1} onClick={() => setSessionPage((p) => p - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
                        {getPageNumbers(sessionPage, Math.ceil(sortedSessions.length / PAGE_SIZE)).map((n, i) =>
                          n === null ? <span key={`e-${i}`} className="px-0.5">…</span> : <Button key={n} variant={n === sessionPage ? "default" : "ghost"} size="icon" className="h-6 w-6 text-xs" onClick={() => setSessionPage(n)}>{n}</Button>
                        )}
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={sessionPage * PAGE_SIZE >= sortedSessions.length} onClick={() => setSessionPage((p) => p + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={sessionPage * PAGE_SIZE >= sortedSessions.length} onClick={() => setSessionPage(Math.ceil(sortedSessions.length / PAGE_SIZE))}><ChevronsRight className="h-3.5 w-3.5" /></Button>
                      </div>
                    </div>
                    </>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* Actions Tab */}
            <TabsContent value="actions">
              <Card className="bg-muted/30 mt-2">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium">User Actions</CardTitle>
                  <p className="text-xs text-muted-foreground">Explicit user submissions tracked at the point of action.</p>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Select value={actionCategoryFilter} onValueChange={(v) => { setActionCategoryFilter(v); setActionTypeFilter("all"); setActionPage(1); }}>
                      <SelectTrigger className="h-8 w-48 text-xs">
                        <SelectValue placeholder="Category" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All Categories</SelectItem>
                        {categoryOptions.map((c) => (
                          <SelectItem key={c} value={c}>{c}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Select value={actionTypeFilter} onValueChange={(v) => { setActionTypeFilter(v); setActionPage(1); }}>
                      <SelectTrigger className="h-8 w-48 text-xs">
                        <SelectValue placeholder="Type" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All Types</SelectItem>
                        {typeOptions.map((t) => (
                          <SelectItem key={t} value={t}>{t}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  {filteredActions.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No actions found</p>
                  ) : (
                    <>
                    <div className="flex items-center justify-between px-2 pb-2 text-xs text-muted-foreground">
                      <span>Showing {(actionPage - 1) * PAGE_SIZE + 1}–{Math.min(actionPage * PAGE_SIZE, sortedActions.length)} of {sortedActions.length}</span>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={actionPage === 1} onClick={() => setActionPage(1)}><ChevronsLeft className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={actionPage === 1} onClick={() => setActionPage((p) => p - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
                        {getPageNumbers(actionPage, Math.ceil(sortedActions.length / PAGE_SIZE)).map((n, i) =>
                          n === null ? <span key={`e-${i}`} className="px-0.5">…</span> : <Button key={n} variant={n === actionPage ? "default" : "ghost"} size="icon" className="h-6 w-6 text-xs" onClick={() => setActionPage(n)}>{n}</Button>
                        )}
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={actionPage * PAGE_SIZE >= sortedActions.length} onClick={() => setActionPage((p) => p + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={actionPage * PAGE_SIZE >= sortedActions.length} onClick={() => setActionPage(Math.ceil(sortedActions.length / PAGE_SIZE))}><ChevronsRight className="h-3.5 w-3.5" /></Button>
                      </div>
                    </div>
                    <div className="border rounded-md overflow-hidden">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <SortableTableHead column="session" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Browser Session</SortableTableHead>
                            <SortableTableHead column="category" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Category</SortableTableHead>
                            <SortableTableHead column="type" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Type</SortableTableHead>
                            <SortableTableHead column="user" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>User</SortableTableHead>
                            <SortableTableHead column="resource" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Resource</SortableTableHead>
                            <SortableTableHead column="time" activeColumn={actionSortCol} direction={actionSortDir} onSort={handleActionSort}>Time</SortableTableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {pagedActions.map((a) => (
                            <TableRow key={a.id} className="bg-white dark:bg-transparent hover:bg-muted/50 dark:hover:bg-muted/20">
                              <TableCell className="text-xs font-mono">{a.browser_session_id}</TableCell>
                              <TableCell className="text-xs">{a.action_category}</TableCell>
                              <TableCell className="text-xs">{a.action_type}</TableCell>
                              <TableCell className="text-xs">{a.user_id}</TableCell>
                              <TableCell className="text-xs text-muted-foreground">{a.resource_name ?? "-"}</TableCell>
                              <TableCell className="text-xs font-mono">{fmtTs(a.performed_at, timezone)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                    <div className="flex items-center justify-between px-2 pt-2 text-xs text-muted-foreground">
                      <span>Showing {(actionPage - 1) * PAGE_SIZE + 1}–{Math.min(actionPage * PAGE_SIZE, sortedActions.length)} of {sortedActions.length}</span>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={actionPage === 1} onClick={() => setActionPage(1)}><ChevronsLeft className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={actionPage === 1} onClick={() => setActionPage((p) => p - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
                        {getPageNumbers(actionPage, Math.ceil(sortedActions.length / PAGE_SIZE)).map((n, i) =>
                          n === null ? <span key={`e-${i}`} className="px-0.5">…</span> : <Button key={n} variant={n === actionPage ? "default" : "ghost"} size="icon" className="h-6 w-6 text-xs" onClick={() => setActionPage(n)}>{n}</Button>
                        )}
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={actionPage * PAGE_SIZE >= sortedActions.length} onClick={() => setActionPage((p) => p + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={actionPage * PAGE_SIZE >= sortedActions.length} onClick={() => setActionPage(Math.ceil(sortedActions.length / PAGE_SIZE))}><ChevronsRight className="h-3.5 w-3.5" /></Button>
                      </div>
                    </div>
                    </>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            {/* Page Views Tab */}
            <TabsContent value="pageviews">
              <Card className="bg-muted/30 mt-2">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium">Page Views</CardTitle>
                  <p className="text-xs text-muted-foreground">Navigation events recorded when users leave a page.</p>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Select value={pageNameFilter} onValueChange={(v) => { setPageNameFilter(v); setPvPage(1); }}>
                      <SelectTrigger className="h-8 w-48 text-xs">
                        <SelectValue placeholder="Page" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All Pages</SelectItem>
                        {pageOptions.map((p) => (
                          <SelectItem key={p} value={p}>{p}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  {filteredPageViews.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No page views found</p>
                  ) : (
                    <>
                    <div className="flex items-center justify-between px-2 pb-2 text-xs text-muted-foreground">
                      <span>Showing {(pvPage - 1) * PAGE_SIZE + 1}–{Math.min(pvPage * PAGE_SIZE, sortedPageViews.length)} of {sortedPageViews.length}</span>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={pvPage === 1} onClick={() => setPvPage(1)}><ChevronsLeft className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={pvPage === 1} onClick={() => setPvPage((p) => p - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
                        {getPageNumbers(pvPage, Math.ceil(sortedPageViews.length / PAGE_SIZE)).map((n, i) =>
                          n === null ? <span key={`e-${i}`} className="px-0.5">…</span> : <Button key={n} variant={n === pvPage ? "default" : "ghost"} size="icon" className="h-6 w-6 text-xs" onClick={() => setPvPage(n)}>{n}</Button>
                        )}
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={pvPage * PAGE_SIZE >= sortedPageViews.length} onClick={() => setPvPage((p) => p + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={pvPage * PAGE_SIZE >= sortedPageViews.length} onClick={() => setPvPage(Math.ceil(sortedPageViews.length / PAGE_SIZE))}><ChevronsRight className="h-3.5 w-3.5" /></Button>
                      </div>
                    </div>
                    <div className="border rounded-md overflow-hidden">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <SortableTableHead column="session" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>Browser Session</SortableTableHead>
                            <SortableTableHead column="page" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>Page</SortableTableHead>
                            <SortableTableHead column="user" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>User</SortableTableHead>
                            <SortableTableHead column="entered_at" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>Entered At</SortableTableHead>
                            <SortableTableHead column="exited_at" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>Exited At</SortableTableHead>
                            <SortableTableHead column="duration" activeColumn={pvSortCol} direction={pvSortDir} onSort={handlePvSort}>Duration</SortableTableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {pagedPageViews.map((p) => (
                            <TableRow key={p.id} className="bg-white dark:bg-transparent hover:bg-muted/50 dark:hover:bg-muted/20">
                              <TableCell className="text-xs font-mono">{p.browser_session_id}</TableCell>
                              <TableCell className="text-xs">{p.page_name}</TableCell>
                              <TableCell className="text-xs">{p.user_id}</TableCell>
                              <TableCell className="text-xs font-mono">{fmtTs(p.entered_at, timezone)}</TableCell>
                              <TableCell className="text-xs font-mono">
                                {p.duration_seconds != null
                                  ? fmtTs(new Date(new Date(p.entered_at).getTime() + p.duration_seconds * 1000).toISOString(), timezone)
                                  : "-"}
                              </TableCell>
                              <TableCell className="text-xs font-mono">{formatDuration(p.duration_seconds)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                    <div className="flex items-center justify-between px-2 pt-2 text-xs text-muted-foreground">
                      <span>Showing {(pvPage - 1) * PAGE_SIZE + 1}–{Math.min(pvPage * PAGE_SIZE, sortedPageViews.length)} of {sortedPageViews.length}</span>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={pvPage === 1} onClick={() => setPvPage(1)}><ChevronsLeft className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={pvPage === 1} onClick={() => setPvPage((p) => p - 1)}><ChevronLeft className="h-3.5 w-3.5" /></Button>
                        {getPageNumbers(pvPage, Math.ceil(sortedPageViews.length / PAGE_SIZE)).map((n, i) =>
                          n === null ? <span key={`e-${i}`} className="px-0.5">…</span> : <Button key={n} variant={n === pvPage ? "default" : "ghost"} size="icon" className="h-6 w-6 text-xs" onClick={() => setPvPage(n)}>{n}</Button>
                        )}
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={pvPage * PAGE_SIZE >= sortedPageViews.length} onClick={() => setPvPage((p) => p + 1)}><ChevronRight className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" disabled={pvPage * PAGE_SIZE >= sortedPageViews.length} onClick={() => setPvPage(Math.ceil(sortedPageViews.length / PAGE_SIZE))}><ChevronsRight className="h-3.5 w-3.5" /></Button>
                      </div>
                    </div>
                    </>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
