import { useEffect, useState, useCallback, useRef, Fragment } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";
import { SortableTableHead, sortRows } from "@/components/SortableTableHead";
import { fetchCostDashboard, fetchCostActuals } from "@/api/costs";
import { listSiteSettings } from "@/api/settings";
import type { CostDashboardResponse, CostActualsResponse, AgentCostSummary, CostActualAgent } from "@/api/types";
import type { SortDirection } from "@/components/SortableCardGrid";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import { ScrollText, Loader2, ChevronRight, ChevronDown } from "lucide-react";

interface CostDashboardPageProps {
  readOnly?: boolean;
  groupRestriction?: string;
}

function formatCost(cost: number): string {
  if (cost === 0) return "~$0.00";
  if (cost < 0.01) return `~$${cost.toFixed(6)}`;
  if (cost < 1) return `~$${cost.toFixed(4)}`;
  return `~$${cost.toFixed(2)}`;
}

function formatTokens(count: number): string {
  if (count === 0) return "0";
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 10_000) return `${(count / 1_000).toFixed(1)}K`;
  return count.toLocaleString();
}

/* ---------- derived cost helpers ---------- */

function runtimeCpu(a: AgentCostSummary): number {
  return a.total_compute_cpu_cost;
}
function runtimeMem(a: AgentCostSummary): number {
  return a.total_compute_memory_cost + a.total_idle_memory_cost;
}
function runtimeTotal(a: AgentCostSummary): number {
  return runtimeCpu(a) + runtimeMem(a);
}
function memoryTotal(a: AgentCostSummary): number {
  return a.total_stm_cost + a.total_ltm_cost;
}
function grandTotal(a: AgentCostSummary): number {
  return a.total_estimated_cost + runtimeTotal(a) + memoryTotal(a);
}

const ACTUALS_SORT_GETTERS: Record<string, (a: CostActualAgent) => string | number> = {
  act_agent: (a) => a.agent_name ?? "",
  act_sessions: (a) => a.sessions.length,
  act_cpu: (a) => a.total_cpu_cost,
  act_mem: (a) => a.total_memory_cost,
  act_total: (a) => a.total_cost,
};

const MEM_SORT_GETTERS: Record<string, (m: { memory_name: string; total_log_events: number; retrieve_records: number; records_stored: number; extractions: number; consolidations: number; total_cost: number }) => string | number> = {
  mem_name: (m) => m.memory_name,
  mem_events: (m) => m.total_log_events,
  mem_retrievals: (m) => m.retrieve_records,
  mem_stored: (m) => m.records_stored,
  mem_extractions: (m) => m.extractions,
  mem_consolidations: (m) => m.consolidations,
  mem_total: (m) => m.total_cost,
};

const SORT_GETTERS: Record<string, (a: AgentCostSummary) => string | number> = {
  agent: (a) => a.agent_name ?? "",
  model: (a) => a.model_id ?? "",
  invocations: (a) => a.total_invocations,
  model_tokens: (a) => a.total_estimated_cost,
  rt_total: (a) => runtimeTotal(a),
  mem_total: (a) => memoryTotal(a),
  total: (a) => grandTotal(a),
  avg: (a) => a.avg_cost_per_invocation,
};

// Module-level cache so actuals survive component unmount/remount on navigation
let _actualsCache: CostActualsResponse | null = null;

export function CostDashboardPage({ readOnly: _readOnly, groupRestriction }: CostDashboardPageProps) {
  const { user, browserSessionId } = useAuth();
  const [data, setData] = useState<CostDashboardResponse | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [sortCol, setSortCol] = useState<string | null>("total");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");
  const [cpuIdlePercent, setCpuIdlePercent] = useState(75);
  const [actSortCol, setActSortCol] = useState<string | null>("act_total");
  const [actSortDir, setActSortDir] = useState<SortDirection>("desc");
  const [expandedAgents, setExpandedAgents] = useState<Set<number>>(new Set());
  const [memSortCol, setMemSortCol] = useState<string | null>("mem_total");
  const [memSortDir, setMemSortDir] = useState<SortDirection>("desc");
  const [actuals, setActualsRaw] = useState<CostActualsResponse | null>(_actualsCache);
  const setActuals = (val: CostActualsResponse | null) => {
    _actualsCache = val;
    setActualsRaw(val);
  };
  const [actualsLoading, setActualsLoading] = useState(false);
  const [actualsElapsed, setActualsElapsed] = useState(0);
  const actualsTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  };

  const handleActSort = (col: string) => {
    if (actSortCol === col) {
      setActSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setActSortCol(col);
      setActSortDir("desc");
    }
  };

  const handleMemSort = (col: string) => {
    if (memSortCol === col) {
      setMemSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setMemSortCol(col);
      setMemSortDir("desc");
    }
  };

  const loadCosts = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchCostDashboard(days, groupRestriction);
      setData(result);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [days, groupRestriction]);

  const loadSettings = useCallback(async () => {
    try {
      const settings = await listSiteSettings();
      const discount = settings.find((s) => s.key === "cpu_io_wait_discount");
      if (discount) setCpuIdlePercent(parseInt(discount.value, 10) || 75);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => { void loadCosts(); }, [loadCosts]);
  useEffect(() => { void loadSettings(); }, [loadSettings]);

  // Clear actuals cache when groupRestriction changes
  useEffect(() => {
    setActuals(null);
  }, [groupRestriction]);

  const pullActuals = async () => {
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "costs", "pull_actuals");
    setActualsLoading(true);
    setActualsElapsed(0);
    actualsTimerRef.current = setInterval(() => setActualsElapsed((t) => t + 1), 1000);
    try {
      const result = await fetchCostActuals(days, groupRestriction);
      setActuals(result);
    } catch (e) {
      console.error("Failed to pull cost actuals:", e);
    } finally {
      setActualsLoading(false);
      if (actualsTimerRef.current) {
        clearInterval(actualsTimerRef.current);
        actualsTimerRef.current = null;
      }
    }
  };

  // Backend filters by group, so use data directly
  const sortedAgents = data ? sortRows(data.agents, sortCol, sortDir, SORT_GETTERS) : [];

  // Derived totals - compute from all agents returned by backend
  const tModel = data?.agents.reduce((sum, a) => sum + a.total_estimated_cost, 0) || 0;
  const tRtCpu = data?.agents.reduce((sum, a) => sum + a.total_compute_cpu_cost, 0) || 0;
  const tRtMem = data?.agents.reduce((sum, a) => sum + a.total_compute_memory_cost + a.total_idle_memory_cost, 0) || 0;
  const tRtTotal = tRtCpu + tRtMem;
  const tStm = data?.agents.reduce((sum, a) => sum + a.total_stm_cost, 0) || 0;
  const tLtm = data?.agents.reduce((sum, a) => sum + a.total_ltm_cost, 0) || 0;
  const tMemTotal = tStm + tLtm;
  const tGrand = tModel + tRtTotal + tMemTotal;
  const tInvocations = data?.agents.reduce((sum, a) => sum + a.total_invocations, 0) || 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Cost Dashboard</h2>
          <p className="text-sm text-muted-foreground">
            <span className="font-semibold text-amber-600 dark:text-amber-400">Estimated</span>{" "}
            total cost = model tokens + runtime + memory.
          </p>
          <p className="text-sm text-muted-foreground">Runtime CPU assumes {cpuIdlePercent}% I/O wait discount, configurable in Settings.</p>
          <p className="text-sm text-muted-foreground">Estimates use 1 vCPU and 0.5 GB memory allocation. Idle cost is memory only.</p>
        </div>
        <div className="flex items-center gap-2">
          {[7, 30, 90, 0].map((d) => (
            <button
              key={d}
              onClick={() => { setDays(d); setActuals(null); }}
              className={`px-3 py-1 text-xs rounded-md border transition-colors ${
                days === d
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-accent"
              }`}
            >
              {d === 0 ? "All" : `${d}d`}
            </button>
          ))}
        </div>
      </div>

      {data && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="pt-2 pb-2">
                <div className="text-xs text-muted-foreground">Total Cost</div>
                <div className="bg-white dark:bg-background rounded-md px-2 py-1 mt-1">
                  <div className="text-xl font-mono font-semibold">{formatCost(tGrand)}</div>
                  <div className="text-[10px] text-muted-foreground">Model + Runtime + Memory</div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-2 pb-2">
                <div className="text-xs text-muted-foreground">Model Tokens</div>
                <div className="bg-white dark:bg-background rounded-md px-2 py-1 mt-1">
                  <div className="text-xl font-mono font-semibold">{formatCost(tModel)}</div>
                  <div className="text-[10px] text-muted-foreground">{tInvocations.toLocaleString()} invocations</div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-2 pb-2">
                <div className="text-xs text-muted-foreground">Runtime</div>
                <div className="bg-white dark:bg-background rounded-md px-2 py-1 mt-1">
                  <div className="text-xl font-mono font-semibold">{formatCost(tRtTotal)}</div>
                  <div className="text-[10px] text-muted-foreground">CPU {formatCost(tRtCpu)} + Mem {formatCost(tRtMem)}</div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-2 pb-2">
                <div className="text-xs text-muted-foreground">Memory</div>
                <div className="bg-white dark:bg-background rounded-md px-2 py-1 mt-1">
                  <div className="text-xl font-mono font-semibold">{formatCost(tMemTotal)}</div>
                  <div className="text-[10px] text-muted-foreground">STM {formatCost(tStm)} + LTM {formatCost(tLtm)}</div>
                </div>
              </CardContent>
            </Card>
          </div>

          {data.group && (
            <div className="text-xs text-muted-foreground">
              Showing costs for group: <Badge variant="secondary" className="text-[10px]">{data.group}</Badge>
              {" "}over {data.days === 0 ? "all time" : `${data.days} days`}
            </div>
          )}

          <Card className="bg-muted/30">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Estimated Costs</CardTitle>
              <p className="text-xs text-muted-foreground">Estimated cost breakdown per agent. 1 vCPU and 0.5 GB used as <em>estimated</em> factors. Compare to Actual Costs below to validate estimates.</p>
              <div className="text-[10px] text-muted-foreground mt-1 font-mono space-y-0.5">
                <div>Runtime CPU = invocation_duration_hours × 1 vCPU × $0.0895/vCPU·h × (1 − {cpuIdlePercent}% I/O wait)</div>
                <div>Runtime Mem = invocation_duration_hours × 0.5 GB × $0.00945/GB·h</div>
                <div>Idle Mem = idle_timeout_seconds × 0.5 GB × $0.00945/GB·h ÷ 3600</div>
              </div>
            </CardHeader>
            <CardContent>
              {data.agents.length === 0 ? (
                <p className="text-sm text-muted-foreground">No invocations in this period.</p>
              ) : (
                <div className="border rounded-md overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableTableHead column="agent" activeColumn={sortCol} direction={sortDir} onSort={handleSort}>Agent</SortableTableHead>
                      <SortableTableHead column="model" activeColumn={sortCol} direction={sortDir} onSort={handleSort}>Model</SortableTableHead>
                      <SortableTableHead column="invocations" activeColumn={sortCol} direction={sortDir} onSort={handleSort} className="text-right">Invocations</SortableTableHead>
                      <SortableTableHead column="model_tokens" activeColumn={sortCol} direction={sortDir} onSort={handleSort} className="text-right">Model Tokens</SortableTableHead>
                      <SortableTableHead column="rt_total" activeColumn={sortCol} direction={sortDir} onSort={handleSort} className="text-right">AgentCore Runtime</SortableTableHead>
                      <SortableTableHead column="mem_total" activeColumn={sortCol} direction={sortDir} onSort={handleSort} className="text-right">AgentCore Memory</SortableTableHead>
                      <SortableTableHead column="avg" activeColumn={sortCol} direction={sortDir} onSort={handleSort} className="text-right">Per Invoke</SortableTableHead>
                      <SortableTableHead column="total" activeColumn={sortCol} direction={sortDir} onSort={handleSort} className="text-right">Total</SortableTableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sortedAgents.map((a) => {
                      const rtCpu = runtimeCpu(a);
                      const rtMem = runtimeMem(a);
                      const rtTot = runtimeTotal(a);
                      const memTot = memoryTotal(a);
                      const total = grandTotal(a);
                      return (
                        <TableRow key={a.agent_id} className="bg-white dark:bg-transparent">
                          <TableCell className="text-xs font-medium">{a.agent_name ?? `Agent #${a.agent_id}`}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">{a.model_id?.split(".").pop() ?? "—"}</TableCell>
                          <TableCell className="text-xs text-right font-mono">{a.total_invocations}</TableCell>
                          <TableCell className="text-xs text-right font-mono">
                            {formatCost(a.total_estimated_cost)}
                            <div className="text-[10px] text-muted-foreground">{formatTokens(a.total_input_tokens)} in / {formatTokens(a.total_output_tokens)} out</div>
                          </TableCell>
                          <TableCell className="text-xs text-right font-mono">
                            {formatCost(rtTot)}
                            <div className="text-[10px] text-muted-foreground">CPU {formatCost(rtCpu)} + Mem {formatCost(rtMem)}</div>
                          </TableCell>
                          <TableCell className="text-xs text-right font-mono">
                            {formatCost(memTot)}
                            <div className="text-[10px] text-muted-foreground">STM {formatCost(a.total_stm_cost)} + LTM {formatCost(a.total_ltm_cost)}</div>
                          </TableCell>
                          <TableCell className="text-xs text-right font-mono">{formatCost(a.avg_cost_per_invocation)}</TableCell>
                          <TableCell className="text-xs text-right font-mono font-semibold">{formatCost(total)}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Cost Actuals from USAGE_LOGS */}
          <Card className="bg-muted/30">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-sm font-medium">Actual Costs</CardTitle>
                  <p className="text-xs text-muted-foreground mt-1">
                    Actual costs from CloudWatch usage logs for runtime and memory resources. Only invocations tracked in Loom are included.
                  </p>
                  <p className="text-xs text-muted-foreground">
                    NOTE: Delivery of usage logs for calculating actual costs can be delayed. If costs are not showing up, try again in 15 minutes.
                  </p>
                </div>
                <button
                  onClick={() => void pullActuals()}
                  disabled={actualsLoading}
                  className="w-[190px] px-3 py-1 text-xs rounded-md border bg-background transition-colors hover:bg-accent disabled:opacity-50 flex items-center justify-center gap-2 shrink-0"
                >
                  <ScrollText className="h-3 w-3" />
                  <span>Pull Actuals</span>
                  {actualsLoading && (
                    <>
                      <Loader2 className="h-3 w-3 animate-spin" />
                      <span className="font-mono">{actualsElapsed}s</span>
                    </>
                  )}
                </button>
              </div>
            </CardHeader>
            <CardContent>
              {actuals ? (
                <div className="space-y-4">
                  {/* Runtime Actuals */}
                  <Card className="border shadow-sm bg-background">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-medium">Runtime</CardTitle>
                      <p className="text-xs text-muted-foreground">
                        Costs from runtime USAGE_LOGS, filtered to Loom-tracked sessions. CPU I/O wait discount: {actuals.io_wait_discount_percent}%, configurable in Settings.
                      </p>
                    </CardHeader>
                    <CardContent>
                      {actuals?.agents.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No usage log data found for this period.</p>
                      ) : (
                        <div className="border rounded-md overflow-hidden">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <SortableTableHead column="act_agent" activeColumn={actSortCol} direction={actSortDir} onSort={handleActSort}>Agent</SortableTableHead>
                                <SortableTableHead column="act_sessions" activeColumn={actSortCol} direction={actSortDir} onSort={handleActSort} className="text-right">Sessions</SortableTableHead>
                                <SortableTableHead column="act_cpu" activeColumn={actSortCol} direction={actSortDir} onSort={handleActSort} className="text-right">Runtime CPU</SortableTableHead>
                                <SortableTableHead column="act_mem" activeColumn={actSortCol} direction={actSortDir} onSort={handleActSort} className="text-right">Runtime Memory</SortableTableHead>
                                <SortableTableHead column="act_total" activeColumn={actSortCol} direction={actSortDir} onSort={handleActSort} className="text-right">Total</SortableTableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {sortRows(actuals.agents, actSortCol, actSortDir, ACTUALS_SORT_GETTERS).map((agent) => (
                                <Fragment key={agent.agent_id}>
                                  <TableRow
                                    className="bg-white dark:bg-transparent cursor-pointer hover:bg-muted/20"
                                    onClick={() => setExpandedAgents((prev) => {
                                      const next = new Set(prev);
                                      if (next.has(agent.agent_id)) next.delete(agent.agent_id);
                                      else next.add(agent.agent_id);
                                      return next;
                                    })}
                                  >
                                    <TableCell className="text-xs font-medium">
                                      <span className="inline-flex items-center gap-1">
                                        {expandedAgents.has(agent.agent_id)
                                          ? <ChevronDown className="h-3 w-3" />
                                          : <ChevronRight className="h-3 w-3" />}
                                        {agent.agent_name}
                                      </span>
                                    </TableCell>
                                    <TableCell className="text-xs text-right font-mono">{agent.sessions.length}</TableCell>
                                    <TableCell className="text-xs text-right font-mono">{formatCost(agent.total_cpu_cost)}</TableCell>
                                    <TableCell className="text-xs text-right font-mono">{formatCost(agent.total_memory_cost)}</TableCell>
                                    <TableCell className="text-xs text-right font-mono font-semibold">{formatCost(agent.total_cost)}</TableCell>
                                  </TableRow>
                                  {expandedAgents.has(agent.agent_id) && agent.sessions.map((sess, idx) => (
                                    <TableRow key={`${agent.agent_id}-${idx}`} className="bg-white dark:bg-transparent">
                                      <TableCell className="text-[10px] text-muted-foreground pl-8">{sess.session_id ?? "—"}</TableCell>
                                      <TableCell className="text-[10px] text-muted-foreground text-right font-mono">{sess.event_count} events</TableCell>
                                      <TableCell className="text-[10px] text-muted-foreground text-right font-mono">
                                        {formatCost(sess.cpu_cost)}
                                        <span className="ml-1">({sess.vcpu_hours.toFixed(6)} vCPU·h)</span>
                                      </TableCell>
                                      <TableCell className="text-[10px] text-muted-foreground text-right font-mono">
                                        {formatCost(sess.memory_cost)}
                                        <span className="ml-1">({sess.memory_gb_hours.toFixed(6)} GB·h)</span>
                                      </TableCell>
                                      <TableCell className="text-[10px] text-muted-foreground text-right font-mono">{formatCost(sess.total_cost)}</TableCell>
                                    </TableRow>
                                  ))}
                                </Fragment>
                              ))}
                              {actuals.agents.length > 1 && (
                                <TableRow className="border-t-2 font-medium bg-white dark:bg-transparent">
                                  <TableCell className="text-xs">Total ({actuals.agents.length} agents)</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{actuals.agents.reduce((n, a) => n + a.sessions.length, 0)}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{formatCost(actuals.agents.reduce((s, a) => s + a.total_cpu_cost, 0))}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{formatCost(actuals.agents.reduce((s, a) => s + a.total_memory_cost, 0))}</TableCell>
                                  <TableCell className="text-xs text-right font-mono font-semibold">{formatCost(actuals.agents.reduce((s, a) => s + a.total_cost, 0))}</TableCell>
                                </TableRow>
                              )}
                            </TableBody>
                          </Table>
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  {/* Memory Actuals */}
                  <Card className="border shadow-sm bg-background">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-medium">Memory</CardTitle>
                      <p className="text-xs text-muted-foreground">
                        Costs from memory APPLICATION_LOGS, filtered to Loom-tracked sessions.
                      </p>
                    </CardHeader>
                    <CardContent>
                      {!actuals?.memory || actuals.memory.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No memory log data found for this period.</p>
                      ) : (
                        <div className="border rounded-md overflow-hidden">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <SortableTableHead column="mem_name" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort}>Memory</SortableTableHead>
                                <SortableTableHead column="mem_events" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Log Events</SortableTableHead>
                                <SortableTableHead column="mem_extractions" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Extractions</SortableTableHead>
                                <SortableTableHead column="mem_consolidations" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Consolidations</SortableTableHead>
                                <SortableTableHead column="mem_retrievals" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">LTM Retrievals</SortableTableHead>
                                <SortableTableHead column="mem_stored" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Records Stored</SortableTableHead>
                                <SortableTableHead column="mem_total" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Total</SortableTableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {sortRows(actuals.memory, memSortCol, memSortDir, MEM_SORT_GETTERS).map((mem) => (
                                <TableRow key={mem.memory_id} className="bg-white dark:bg-transparent">
                                  <TableCell className="text-xs font-medium">{mem.memory_name}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{mem.total_log_events.toLocaleString()}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{mem.extractions.toLocaleString()}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{mem.consolidations.toLocaleString()}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">
                                    {mem.retrieve_records.toLocaleString()}
                                    <div className="text-[10px] text-muted-foreground">{formatCost(mem.ltm_retrieval_cost)}</div>
                                  </TableCell>
                                  <TableCell className="text-xs text-right font-mono">
                                    {mem.records_stored.toLocaleString()}
                                    <div className="text-[10px] text-muted-foreground">{formatCost(mem.ltm_storage_cost)}</div>
                                  </TableCell>
                                  <TableCell className="text-xs text-right font-mono font-semibold">{formatCost(mem.total_cost)}</TableCell>
                                </TableRow>
                              ))}
                              {actuals.memory.length > 1 && (
                                <TableRow className="border-t-2 font-medium bg-white dark:bg-transparent">
                                  <TableCell className="text-xs">Total ({actuals.memory.length} resources)</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{actuals.memory.reduce((s, m) => s + m.total_log_events, 0).toLocaleString()}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{actuals.memory.reduce((s, m) => s + m.extractions, 0).toLocaleString()}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{actuals.memory.reduce((s, m) => s + m.consolidations, 0).toLocaleString()}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{actuals.memory.reduce((s, m) => s + m.retrieve_records, 0).toLocaleString()}</TableCell>
                                  <TableCell className="text-xs text-right font-mono">{actuals.memory.reduce((s, m) => s + m.records_stored, 0).toLocaleString()}</TableCell>
                                  <TableCell className="text-xs text-right font-mono font-semibold">{formatCost(actuals.memory.reduce((s, m) => s + m.total_cost, 0))}</TableCell>
                                </TableRow>
                              )}
                            </TableBody>
                          </Table>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
      )}

      {loading && !data && (
        <div className="text-sm text-muted-foreground">Loading cost data...</div>
      )}
    </div>
  );
}
