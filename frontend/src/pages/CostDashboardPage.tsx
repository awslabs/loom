import { useEffect, useState, useCallback, useRef, Fragment } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  days: number;
}

function formatCost(cost: number): string {
  if (cost === 0) return "$0.00";
  if (cost < 0.01) return `$${cost.toFixed(6)}`;
  if (cost < 1) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
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

export function CostDashboardPage({ groupRestriction, days }: CostDashboardPageProps) {
  const { user, browserSessionId } = useAuth();
  const [data, setData] = useState<CostDashboardResponse | null>(null);
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
  const [showFormulas, setShowFormulas] = useState(false);
  const [showZeroRows, setShowZeroRows] = useState(false);

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

  // Clear actuals cache when the range or group changes
  useEffect(() => {
    setActuals(null);
  }, [groupRestriction, days]);

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

  const allAgents = data ? sortRows(data.agents, sortCol, sortDir, SORT_GETTERS) : [];
  const nonZeroAgents = allAgents.filter((a) => grandTotal(a) > 0 || a.total_invocations > 0);
  const zeroAgents = allAgents.filter((a) => !(grandTotal(a) > 0 || a.total_invocations > 0));

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
  const activeAgents = data?.agents.filter((a) => a.total_invocations > 0).length ?? 0;

  const modelShare = tGrand > 0 ? (tModel / tGrand) * 100 : 0;
  const rtShare = tGrand > 0 ? (tRtTotal / tGrand) * 100 : 0;
  const memShare = tGrand > 0 ? (tMemTotal / tGrand) * 100 : 0;

  // Actual totals (runtime + memory come from usage logs; model cost isn't separately tracked in actuals, so estimated model cost carries through)
  const actRtTotal = actuals ? actuals.agents.reduce((s, a) => s + a.total_cpu_cost + a.total_memory_cost, 0) : 0;
  const actMemTotal = actuals ? actuals.memory.reduce((s, m) => s + m.total_cost, 0) : 0;
  const actGrand = actuals ? actRtTotal + actMemTotal + tModel : 0;
  const variancePct = actuals && tGrand > 0 ? ((actGrand - tGrand) / tGrand) * 100 : null;

  return (
    <div className="flex flex-col gap-4">
      {/* status bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-md border bg-muted px-3.5 py-2">
        <span className="flex items-center gap-1.5 rounded-full border border-warning/30 bg-warning-bg px-2 py-0.5 font-mono text-[10px] tracking-wide text-warning">ESTIMATED</span>
        <span className="text-[12.5px] text-muted-foreground">Modeled from 1 vCPU / 0.5 GB with a {cpuIdlePercent}% I/O-wait discount. Compare with Actuals to validate.</span>
        <button type="button" onClick={() => setShowFormulas((v) => !v)} className="font-mono text-[11.5px] text-primary hover:underline">How this is calculated</button>
        <span className="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground">
          {data ? `last ${data.days === 0 ? "all time" : `${data.days} days`} · ${tInvocations} invocation${tInvocations === 1 ? "" : "s"}` : "—"}
        </span>
      </div>

      {data && data.group && (
        <div className="text-xs text-muted-foreground">
          Showing costs for group: <Badge variant="secondary" className="text-[10px]">{data.group}</Badge>
        </div>
      )}

      {loading && !data && <div className="text-sm text-muted-foreground">Loading cost data...</div>}

      {data && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="flex min-w-0 flex-col gap-4">
            {/* total + composition */}
            <Card className="gap-3.5 py-[18px]">
              <CardContent className="flex flex-col gap-3.5 px-[18px]">
                <div className="flex flex-wrap items-end gap-5">
                  <div className="flex flex-col gap-1">
                    <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">
                      Total estimated spend · {data.days === 0 ? "all" : `${data.days}d`}
                    </span>
                    <div className="flex items-baseline gap-2">
                      <span className="font-mono text-[30px] font-semibold tracking-tight tabular-nums">{formatCost(tGrand)}</span>
                      <span className="font-mono text-[11.5px] text-muted-foreground">{formatCost(tInvocations > 0 ? tGrand / tInvocations : 0)} / invocation</span>
                    </div>
                  </div>
                  <div className="ml-auto flex items-center gap-5">
                    <div className="flex flex-col items-end gap-0.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Invocations</span>
                      <span className="font-mono text-sm tabular-nums">{tInvocations}</span>
                    </div>
                    <div className="flex flex-col items-end gap-0.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Active agents</span>
                      <span className="font-mono text-sm tabular-nums">{activeAgents} <span className="text-muted-foreground">/ {data.agents.length}</span></span>
                    </div>
                  </div>
                </div>

                {tGrand > 0 && (
                  <div className="flex h-2 overflow-hidden rounded-full bg-input-bg">
                    <div className="bg-chart-1" style={{ width: `${modelShare}%` }} />
                    <div className="bg-chart-2" style={{ width: `${rtShare}%` }} />
                    <div className="bg-chart-3" style={{ width: `${memShare}%` }} />
                  </div>
                )}
                <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-[2px] bg-chart-1" />
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Model tokens</span>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <span className="font-mono text-[15px] font-semibold tabular-nums">{formatCost(tModel)}</span>
                      <span className="font-mono text-[10.5px] text-muted-foreground">{Math.round(modelShare)}%</span>
                    </div>
                    <span className="text-[11.5px] text-muted-foreground">{formatTokens(data.total_input_tokens)} in · {formatTokens(data.total_output_tokens)} out</span>
                  </div>
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-[2px] bg-chart-2" />
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Runtime</span>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <span className="font-mono text-[15px] font-semibold tabular-nums">{formatCost(tRtTotal)}</span>
                      <span className="font-mono text-[10.5px] text-muted-foreground">{Math.round(rtShare)}%</span>
                    </div>
                    <span className="text-[11.5px] text-muted-foreground">CPU {formatCost(tRtCpu)} · Mem {formatCost(tRtMem)}</span>
                  </div>
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-[2px] bg-chart-3" />
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Memory store</span>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <span className="font-mono text-[15px] font-semibold tabular-nums">{formatCost(tMemTotal)}</span>
                      <span className="font-mono text-[10.5px] text-muted-foreground">{Math.round(memShare)}%</span>
                    </div>
                    <span className="text-[11.5px] text-muted-foreground">STM {formatCost(tStm)}{tLtm > 0 ? ` · LTM ${formatCost(tLtm)}` : " · LTM unused"}</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* per-agent */}
            <Card className="gap-0 overflow-hidden py-0">
              <div className="flex items-center gap-2.5 border-b px-4 py-3">
                <span className="text-[13.5px] font-semibold">Spend by agent</span>
                <span className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">{activeAgents} active</span>
              </div>
              {data.agents.length === 0 ? (
                <p className="px-4 py-6 text-sm text-muted-foreground">No invocations in this period.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted hover:bg-muted">
                      <SortableTableHead column="agent" activeColumn={sortCol} direction={sortDir} onSort={handleSort}>Agent</SortableTableHead>
                      <SortableTableHead column="model" activeColumn={sortCol} direction={sortDir} onSort={handleSort}>Model</SortableTableHead>
                      <SortableTableHead column="invocations" activeColumn={sortCol} direction={sortDir} onSort={handleSort} className="text-right">Invokes</SortableTableHead>
                      <SortableTableHead column="total" activeColumn={sortCol} direction={sortDir} onSort={handleSort}>Composition</SortableTableHead>
                      <SortableTableHead column="avg" activeColumn={sortCol} direction={sortDir} onSort={handleSort} className="text-right">Per invoke</SortableTableHead>
                      <SortableTableHead column="total" activeColumn={sortCol} direction={sortDir} onSort={handleSort} className="text-right">Total</SortableTableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {nonZeroAgents.map((a) => {
                      const total = grandTotal(a);
                      const mPct = total > 0 ? (a.total_estimated_cost / total) * 100 : 0;
                      const rPct = total > 0 ? (runtimeTotal(a) / total) * 100 : 0;
                      const memPct = total > 0 ? (memoryTotal(a) / total) * 100 : 0;
                      return (
                        <TableRow key={a.agent_id}>
                          <TableCell className="font-mono text-[12.5px]">{a.agent_name ?? `Agent #${a.agent_id}`}</TableCell>
                          <TableCell className="font-mono text-[11.5px] text-muted-foreground">{a.model_id?.split(".").pop() ?? "—"}</TableCell>
                          <TableCell className="text-right font-mono text-xs tabular-nums">{a.total_invocations}</TableCell>
                          <TableCell>
                            <div className="flex h-1.5 min-w-[64px] overflow-hidden rounded-full bg-input-bg" title={`Model ${formatCost(a.total_estimated_cost)} · Runtime ${formatCost(runtimeTotal(a))} · Memory ${formatCost(memoryTotal(a))}`}>
                              <div className="bg-chart-1" style={{ width: `${mPct}%` }} />
                              <div className="bg-chart-2" style={{ width: `${rPct}%` }} />
                              <div className="bg-chart-3" style={{ width: `${memPct}%` }} />
                            </div>
                          </TableCell>
                          <TableCell className="text-right font-mono text-[11.5px] text-muted-foreground tabular-nums">{formatCost(a.avg_cost_per_invocation)}</TableCell>
                          <TableCell className="text-right font-mono text-[12.5px] font-semibold tabular-nums">{formatCost(total)}</TableCell>
                        </TableRow>
                      );
                    })}
                    {zeroAgents.length > 0 && (
                      <TableRow className="cursor-pointer bg-muted hover:bg-muted" onClick={() => setShowZeroRows((v) => !v)}>
                        <TableCell colSpan={5} className="font-mono text-xs text-muted-foreground">
                          <span className="mr-1.5">{showZeroRows ? "⌄" : "›"}</span>
                          {zeroAgents.length} agent{zeroAgents.length === 1 ? "" : "s"} with no invocations in this period
                          <span className="ml-2 text-primary">{showZeroRows ? "hide" : "show"}</span>
                        </TableCell>
                        <TableCell className="text-right font-mono text-[11.5px] text-muted-foreground tabular-nums">$0.00</TableCell>
                      </TableRow>
                    )}
                    {showZeroRows && zeroAgents.map((a) => (
                      <TableRow key={a.agent_id} className="text-muted-foreground">
                        <TableCell className="font-mono text-[12.5px]">{a.agent_name ?? `Agent #${a.agent_id}`}</TableCell>
                        <TableCell className="font-mono text-[11.5px]">{a.model_id?.split(".").pop() ?? "—"}</TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">0</TableCell>
                        <TableCell />
                        <TableCell className="text-right font-mono text-[11.5px] tabular-nums">—</TableCell>
                        <TableCell className="text-right font-mono text-[12.5px] tabular-nums">$0.00</TableCell>
                      </TableRow>
                    ))}
                    <TableRow className="bg-muted font-medium hover:bg-muted">
                      <TableCell className="text-[12.5px] font-semibold">Total</TableCell>
                      <TableCell />
                      <TableCell className="text-right font-mono text-xs tabular-nums">{tInvocations}</TableCell>
                      <TableCell />
                      <TableCell className="text-right font-mono text-[11.5px] text-muted-foreground tabular-nums">{formatCost(tInvocations > 0 ? tGrand / tInvocations : 0)}</TableCell>
                      <TableCell className="text-right font-mono text-sm font-semibold tabular-nums">{formatCost(tGrand)}</TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              )}
            </Card>

            {/* Memory actuals detail (secondary, appears once actuals are pulled) */}
            {actuals && actuals.memory.length > 0 && (
              <Card className="gap-0 overflow-hidden py-0">
                <div className="flex items-center gap-2.5 border-b px-4 py-3">
                  <span className="text-[13.5px] font-semibold">Memory actuals</span>
                  <span className="text-[11.5px] text-muted-foreground">From APPLICATION_LOGS, filtered to Loom-tracked sessions.</span>
                </div>
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted hover:bg-muted">
                      <SortableTableHead column="mem_name" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort}>Memory</SortableTableHead>
                      <SortableTableHead column="mem_events" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Log events</SortableTableHead>
                      <SortableTableHead column="mem_extractions" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Extractions</SortableTableHead>
                      <SortableTableHead column="mem_consolidations" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Consolidations</SortableTableHead>
                      <SortableTableHead column="mem_retrievals" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">LTM retrievals</SortableTableHead>
                      <SortableTableHead column="mem_stored" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Records stored</SortableTableHead>
                      <SortableTableHead column="mem_total" activeColumn={memSortCol} direction={memSortDir} onSort={handleMemSort} className="text-right">Total</SortableTableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sortRows(actuals.memory, memSortCol, memSortDir, MEM_SORT_GETTERS).map((mem) => (
                      <TableRow key={mem.memory_id}>
                        <TableCell className="font-mono text-[12.5px]">{mem.memory_name}</TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">{mem.total_log_events.toLocaleString()}</TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">{mem.extractions.toLocaleString()}</TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">{mem.consolidations.toLocaleString()}</TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">{mem.retrieve_records.toLocaleString()}</TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">{mem.records_stored.toLocaleString()}</TableCell>
                        <TableCell className="text-right font-mono text-[12.5px] font-semibold tabular-nums">{formatCost(mem.total_cost)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Card>
            )}
          </div>

          {/* rail */}
          <div className="flex flex-col gap-3.5">
            <Card className="gap-3 py-4">
              <CardContent className="flex flex-col gap-3 px-4">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold">Actual costs</span>
                  <Button size="sm" variant="outline" className="ml-auto h-[27px] gap-1.5 text-xs" onClick={() => void pullActuals()} disabled={actualsLoading}>
                    <ScrollText className="h-3 w-3" />
                    {actualsLoading ? (
                      <span className="flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" />{actualsElapsed}s</span>
                    ) : "Pull actuals"}
                  </Button>
                </div>
                {actuals ? (
                  <>
                    <div className="flex items-baseline gap-2">
                      <span className="font-mono text-xl font-semibold tabular-nums">{formatCost(actGrand)}</span>
                      {variancePct !== null && (
                        <span className={`rounded-md border px-1.5 py-0.5 font-mono text-[11px] ${variancePct >= 0 ? "border-warning/30 bg-warning-bg text-warning" : "border-success/30 bg-success-bg text-success"}`}>
                          {variancePct >= 0 ? "+" : ""}{variancePct.toFixed(1)}% vs est.
                        </span>
                      )}
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Runtime</span>
                        <span className="ml-auto font-mono text-[11.5px] tabular-nums">{formatCost(actRtTotal)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Memory</span>
                        <span className="ml-auto font-mono text-[11.5px] tabular-nums">{formatCost(actMemTotal)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Model</span>
                        <span className="ml-auto font-mono text-[11.5px] tabular-nums">{formatCost(tModel)}</span>
                      </div>
                    </div>
                    {actuals.agents.length > 0 && (
                      <div className="flex flex-col overflow-hidden rounded-md border">
                        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 border-b bg-muted px-2.5 py-1.5 font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">
                          <button type="button" onClick={() => handleActSort("act_agent")} className="text-left hover:text-foreground">Agent</button>
                          <button type="button" onClick={() => handleActSort("act_total")} className="text-right hover:text-foreground">Total</button>
                        </div>
                        {sortRows(actuals.agents, actSortCol, actSortDir, ACTUALS_SORT_GETTERS).map((agent) => (
                          <Fragment key={agent.agent_id}>
                            <button
                              type="button"
                              onClick={() => setExpandedAgents((prev) => { const next = new Set(prev); next.has(agent.agent_id) ? next.delete(agent.agent_id) : next.add(agent.agent_id); return next; })}
                              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-b px-2.5 py-1.5 text-left last:border-b-0 hover:bg-accent/50"
                            >
                              <span className="flex items-center gap-1 truncate font-mono text-[11.5px]">
                                {expandedAgents.has(agent.agent_id) ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
                                {agent.agent_name}
                              </span>
                              <span className="font-mono text-[11.5px] tabular-nums">{formatCost(agent.total_cost)}</span>
                            </button>
                            {expandedAgents.has(agent.agent_id) && agent.sessions.map((sess, idx) => (
                              <div key={idx} className="border-b px-2.5 py-1 pl-6 last:border-b-0">
                                <div className="flex items-center justify-between gap-2 font-mono text-[10px] text-muted-foreground">
                                  <span className="truncate">{sess.session_id ?? "—"}</span>
                                  <span className="tabular-nums">{formatCost(sess.total_cost)}</span>
                                </div>
                              </div>
                            ))}
                          </Fragment>
                        ))}
                      </div>
                    )}
                    <div className="flex items-center gap-1.5 rounded-md border bg-muted px-2.5 py-2 text-[11px] leading-[1.5] text-muted-foreground">
                      CloudWatch usage logs can lag ~15 minutes.
                    </div>
                  </>
                ) : (
                  <p className="text-[11.5px] leading-[1.5] text-muted-foreground">Pull actuals from CloudWatch usage logs to compare against estimates.</p>
                )}
              </CardContent>
            </Card>

            <Card className="gap-2.5 py-4">
              <CardContent className="flex flex-col gap-2.5 px-4">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold">Assumptions</span>
                </div>
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">vCPU</span>
                  <span className="font-mono text-[11.5px]">1 @ $0.0895/h</span>
                </div>
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Memory</span>
                  <span className="font-mono text-[11.5px]">0.5 GB @ $0.00945/h</span>
                </div>
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">I/O wait</span>
                  <span className="font-mono text-[11.5px]">{cpuIdlePercent}% discount</span>
                </div>
                <div className="h-px bg-border" />
                <div className="flex items-center gap-2">
                  <span className="text-[12.5px] text-muted-foreground">Formulas</span>
                  <button type="button" onClick={() => setShowFormulas((v) => !v)} className="ml-auto font-mono text-[11px] text-primary hover:underline">
                    {showFormulas ? "hide" : "show"}
                  </button>
                </div>
                {showFormulas && (
                  <div className="flex flex-col gap-1 rounded-md border bg-muted p-2.5 font-mono text-[10px] leading-[1.6] text-muted-foreground">
                    <span>Runtime CPU = duration_hours × 1 vCPU × $0.0895/vCPU·h × (1 − {cpuIdlePercent}%)</span>
                    <span>Runtime Mem = duration_hours × 0.5 GB × $0.00945/GB·h</span>
                    <span>Idle Mem = idle_timeout_s × 0.5 GB × $0.00945/GB·h ÷ 3600</span>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
