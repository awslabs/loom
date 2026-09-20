import { useEffect, useCallback, useState, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { X } from "lucide-react";
import { toast } from "sonner";
import { StatusPill } from "@/components/StatusPill";
import { LogViewer } from "@/components/LogViewer";
import { TraceList } from "@/components/TraceList";
import { TraceGraph } from "@/components/TraceGraph";
import { useLogs } from "@/hooks/useLogs";
import { useTraces } from "@/hooks/useTraces";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant } from "@/lib/status";
import type { SessionResponse, AgentResponse, LogStreamInfo, InvocationResponse } from "@/api/types";
import type { TimezonePreference } from "@/contexts/TimezoneContext";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";

const SESSION_LOGS_VALUE = "__session__";
const LIVE_TAIL_INTERVAL_MS = 4000;

/**
 * Simplify a log stream name for display, optionally including a timestamp.
 * Input:  "YYYY/MM/DD/[runtime-logs-<session-id>]<uuid>"
 * Output: "<session-id> (YYYY/MM/DD HH:MM)"
 */
function formatStreamName(name: string, lastEventTime?: number, tz?: TimezonePreference): string {
  const timeSuffix = lastEventTime
    ? new Date(lastEventTime).toLocaleString(undefined, {
        timeZone: tz === "UTC" ? "UTC" : undefined,
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      })
    : "";

  const match = name.match(/^(\d{4}\/\d{2}\/\d{2})\/\[runtime-logs-([^\]]+)\]/);
  if (match) {
    return timeSuffix ? `${match[2]} (${timeSuffix})` : `${match[2]} (${match[1]})`;
  }
  return timeSuffix ? `${name} (${timeSuffix})` : name;
}

function isOtelStream(name: string): boolean {
  return name.includes("otel-rt-logs");
}

function sortStreams(streams: LogStreamInfo[]): LogStreamInfo[] {
  const regular = streams.filter((s) => !isOtelStream(s.name));
  const otel = streams.filter((s) => isOtelStream(s.name));
  return [...regular, ...otel];
}

function formatSeconds(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatCost(cost: number | null | undefined): string {
  if (cost == null || cost === 0) return "—";
  if (cost < 0.01) return `$${cost.toFixed(6)}`;
  return `$${cost.toFixed(4)}`;
}

function invocationCostParts(inv: InvocationResponse) {
  const model = inv.estimated_cost ?? 0;
  const runtime = (inv.compute_cpu_cost ?? 0) + (inv.compute_memory_cost ?? 0) + (inv.idle_memory_cost ?? 0);
  const memory = (inv.stm_cost ?? 0) + (inv.ltm_cost ?? 0);
  return { model, runtime, memory, total: model + runtime + memory };
}

interface SessionDetailPageProps {
  agent: AgentResponse;
  session: SessionResponse;
  onSelectInvocation?: (invocationId: string) => void;
  onRerunInInvoke?: () => void;
  initialScopedInvocationId?: string | null;
}

export function SessionDetailPage({ agent, session, onSelectInvocation, onRerunInInvoke, initialScopedInvocationId }: SessionDetailPageProps) {
  const { user, browserSessionId } = useAuth();
  const {
    logs,
    loading: logsLoading,
    streams,
    streamsLoading,
    activeStream,
    vendedSources,
    fetchSessionLogs,
    fetchLogStreams,
    fetchStreamLogs,
    fetchVendedLogs,
  } = useLogs();
  const {
    traces,
    tracesLoading,
    selectedTrace,
    traceDetailLoading,
    fetchSessionTraces,
    fetchTraceDetail,
    setSelectedTrace,
  } = useTraces();
  const { timezone } = useTimezone();
  const [wrap, setWrap] = useState(true);
  const [liveTail, setLiveTail] = useState(false);
  const [scopedInvocationId, setScopedInvocationId] = useState<string | null>(initialScopedInvocationId ?? null);
  const tracesFetchedRef = useRef(false);

  const qualifier = session.qualifier || "DEFAULT";

  const refreshLogs = useCallback(() => {
    if (activeStream.startsWith("vended:")) {
      const source = vendedSources.find((s) => s.key === activeStream);
      if (source) void fetchVendedLogs(agent.id, source, true);
    } else if (activeStream) {
      void fetchStreamLogs(agent.id, qualifier, activeStream, true);
    } else {
      void fetchSessionLogs(agent.id, session.session_id, qualifier, true);
    }
  }, [agent.id, session.session_id, qualifier, activeStream, vendedSources, fetchSessionLogs, fetchStreamLogs, fetchVendedLogs]);

  // Fetch session logs and available streams on mount
  useEffect(() => {
    void fetchSessionLogs(agent.id, session.session_id, qualifier);
    void fetchLogStreams(agent.id, qualifier);
  }, [agent.id, session.session_id, qualifier, fetchSessionLogs, fetchLogStreams]);

  // Live tail: poll the active source while enabled
  useEffect(() => {
    if (!liveTail) return;
    const id = setInterval(refreshLogs, LIVE_TAIL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [liveTail, refreshLogs]);

  const handleStreamChange = (value: string) => {
    if (value === SESSION_LOGS_VALUE) {
      void fetchSessionLogs(agent.id, session.session_id, qualifier);
    } else if (value.startsWith("vended:")) {
      const source = vendedSources.find((s) => s.key === value);
      if (source) void fetchVendedLogs(agent.id, source);
    } else {
      void fetchStreamLogs(agent.id, qualifier, value);
    }
  };

  const handleTabChange = (tab: string) => {
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "tab_click", tab);
    if (tab === "traces" && !tracesFetchedRef.current) {
      tracesFetchedRef.current = true;
      void fetchSessionTraces(agent.id, session.session_id);
    }
  };

  const handleSelectTrace = (traceId: string) => {
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, "navigation", "trace_detail", traceId);
    void fetchTraceDetail(agent.id, traceId);
  };

  const handleCopySessionId = () => {
    navigator.clipboard.writeText(session.session_id);
    toast.success("Copied session id");
  };

  const handleExportLogs = () => {
    const text = logs.map((e) => `${e.timestamp_iso}\t${e.message}`).join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${session.session_id}.log`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const selectedValue = activeStream || SESSION_LOGS_VALUE;
  const sortedStreams = sortStreams(streams);
  const scopedInvocation = session.invocations.find((i) => i.invocation_id === scopedInvocationId);
  const requiredLogText = scopedInvocation?.request_id ?? undefined;

  const totalDurationMs = session.invocations.reduce((sum, i) => sum + (i.client_duration_ms ?? 0), 0);
  const coldStartMs = session.invocations.find((i) => i.cold_start_latency_ms != null)?.cold_start_latency_ms ?? null;
  const totalInputTokens = session.invocations.reduce((sum, i) => sum + (i.input_tokens ?? 0), 0);
  const totalOutputTokens = session.invocations.reduce((sum, i) => sum + (i.output_tokens ?? 0), 0);
  const totalCost = session.invocations.reduce((sum, i) => sum + invocationCostParts(i).total, 0);

  const metrics: [string, string][] = [
    ["Invoked by", session.user_id ?? "—"],
    ["Duration", formatSeconds(totalDurationMs)],
    ["Cold start", formatSeconds(coldStartMs)],
    ["Tokens", totalInputTokens + totalOutputTokens > 0 ? `${totalInputTokens} / ${totalOutputTokens}` : "—"],
    ["Est. cost", formatCost(totalCost)],
    ["Created", formatTimestamp(session.created_at, timezone)],
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* header */}
      <div className="flex flex-col gap-4 rounded-t-xl border bg-card px-6 pt-5 pb-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="truncate font-mono text-xl font-semibold tracking-tight">{session.session_id}</h1>
          <button type="button" onClick={handleCopySessionId} className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground hover:text-foreground">
            copy
          </button>
          <StatusPill
            label={session.live_status}
            variant={
              session.live_status === "active" ? "success"
                : session.live_status === "error" ? "destructive"
                : session.live_status === "expired" ? "neutral"
                : "warning"
            }
          />
          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleExportLogs}>Export logs</Button>
            {onRerunInInvoke && <Button size="sm" onClick={onRerunInInvoke}>Rerun in Invoke</Button>}
          </div>
        </div>

        {/* metrics strip */}
        <div className="grid grid-cols-2 overflow-hidden rounded-[10px] border bg-muted sm:grid-cols-3 lg:grid-cols-6">
          {metrics.map(([label, value], i) => (
            <div key={label} className={`flex flex-col gap-1 px-3.5 py-2.5 ${i < metrics.length - 1 ? "border-r" : ""}`}>
              <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">{label}</span>
              <span className="truncate font-mono text-[12.5px] tabular-nums">{value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* body: requests rail + log/trace viewer */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        <div className="flex flex-col gap-2.5 rounded-xl border bg-card p-4">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold">Requests</span>
            <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-mono">{session.invocations.length}</Badge>
          </div>
          {session.invocations.length === 0 ? (
            <div className="rounded-md border border-dashed px-3 py-2.5 text-[11.5px] text-muted-foreground">
              Requests in this session appear here — select one to scope the logs.
            </div>
          ) : (
            session.invocations.map((inv) => {
              const { model, runtime, memory, total } = invocationCostParts(inv);
              const isSelected = inv.invocation_id === scopedInvocationId;
              const variant = statusVariant(inv.status === "complete" ? "READY" : inv.status === "error" ? "FAILED" : "CREATING");
              return (
                <div
                  key={inv.invocation_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setScopedInvocationId(isSelected ? null : inv.invocation_id)}
                  onKeyDown={(e) => { if (e.key === "Enter") setScopedInvocationId(isSelected ? null : inv.invocation_id); }}
                  className={`flex cursor-pointer flex-col gap-2 rounded-[9px] border px-3 py-2.5 text-left transition-colors ${isSelected ? "border-primary/30 bg-primary/[0.05]" : "hover:bg-accent/50"}`}
                >
                  <div className="flex items-center gap-1.5">
                    <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${variant === "success" ? "bg-success" : variant === "destructive" ? "bg-destructive" : "bg-status-neutral"}`} />
                    <span className="truncate font-mono text-[11.5px]">{(inv.request_id ?? inv.invocation_id).slice(0, 18)}</span>
                    <span className="ml-auto shrink-0 font-mono text-[10px] tracking-wide uppercase text-muted-foreground">{inv.status}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 font-mono text-[10.5px] text-muted-foreground tabular-nums">
                    <span>{formatSeconds(inv.client_duration_ms)}</span>
                    {inv.cold_start_latency_ms != null && (<><span>·</span><span>cold {formatSeconds(inv.cold_start_latency_ms)}</span></>)}
                    <span>·</span>
                    <span>{inv.input_tokens ?? 0}/{inv.output_tokens ?? 0} tok</span>
                  </div>
                  {total > 0 && (
                    <>
                      <div className="h-px bg-border" />
                      <div className="flex flex-col gap-1.5">
                        {([["Model", model], ["Runtime", runtime], ["Memory", memory]] as [string, number][])
                          .filter(([, val]) => val > 0)
                          .map(([label, val]) => (
                            <div key={label} className="flex items-center gap-2">
                              <span className="w-[52px] shrink-0 font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">{label}</span>
                              <div className="h-[3px] flex-1 overflow-hidden rounded-full bg-input-bg">
                                <div className="h-full rounded-full bg-primary" style={{ width: `${(val / total) * 100}%` }} />
                              </div>
                              <span className="font-mono text-[10.5px] tabular-nums">{formatCost(val)}</span>
                            </div>
                          ))}
                      </div>
                    </>
                  )}
                  {onSelectInvocation && (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); onSelectInvocation(inv.invocation_id); }}
                      className="self-end text-[10.5px] text-primary hover:underline"
                    >
                      open details
                    </button>
                  )}
                </div>
              );
            })
          )}
        </div>

        <Tabs defaultValue="logs" onValueChange={handleTabChange} className="min-w-0 gap-0">
          <div className="flex flex-wrap items-center gap-2.5 rounded-t-xl border bg-card px-3.5 py-2.5">
            <TabsList className="h-auto gap-0.5 rounded-md border bg-muted p-[3px]">
              <TabsTrigger value="logs" className="rounded-[5px] px-2.5 py-1 text-xs data-[state=active]:shadow-none">Logs</TabsTrigger>
              <TabsTrigger value="traces" className="rounded-[5px] px-2.5 py-1 text-xs data-[state=active]:shadow-none">Traces</TabsTrigger>
            </TabsList>

            <TabsContent value="logs" className="contents">
              <Select value={selectedValue} onValueChange={handleStreamChange}>
                <SelectTrigger size="sm" className="max-w-[280px] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectLabel>Source</SelectLabel>
                    <SelectItem value={SESSION_LOGS_VALUE}>Service-level logs</SelectItem>
                  </SelectGroup>
                  {sortedStreams.length > 0 && (
                    <>
                      <SelectSeparator />
                      <SelectGroup>
                        <SelectLabel>Log Streams</SelectLabel>
                        {sortedStreams.map((s) => (
                          <SelectItem key={s.name} value={s.name}>{formatStreamName(s.name, s.last_event_time, timezone)}</SelectItem>
                        ))}
                      </SelectGroup>
                    </>
                  )}
                  {vendedSources.length > 0 && (
                    <>
                      <SelectSeparator />
                      <SelectGroup>
                        <SelectLabel>Vended Logs</SelectLabel>
                        {vendedSources.map((src) => (
                          <SelectItem key={src.key} value={src.key}>{src.label}</SelectItem>
                        ))}
                      </SelectGroup>
                    </>
                  )}
                </SelectContent>
              </Select>
              {streamsLoading && <span className="text-xs text-muted-foreground">Loading streams...</span>}

              <span className="flex items-center gap-1.5 rounded-md border bg-muted px-2 py-1 font-mono text-[11px]">
                session <span className="text-muted-foreground">{session.session_id.slice(0, 8)}</span>
              </span>
              {scopedInvocation && (
                <span className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/[0.06] px-2 py-1 font-mono text-[11px] text-primary">
                  request {(scopedInvocation.request_id ?? scopedInvocation.invocation_id).slice(0, 8)}
                  <button type="button" onClick={() => setScopedInvocationId(null)}><X className="h-3 w-3" /></button>
                </span>
              )}

              <div className="ml-auto flex items-center gap-2">
                <div className="flex items-center gap-0.5 rounded-md border bg-muted p-[3px]">
                  <button type="button" onClick={() => setWrap(true)} className={`rounded-[4px] px-2 py-0.5 font-mono text-[10.5px] ${wrap ? "bg-card" : "text-muted-foreground"}`}>wrap</button>
                  <button type="button" onClick={() => setWrap(false)} className={`rounded-[4px] px-2 py-0.5 font-mono text-[10.5px] ${!wrap ? "bg-card" : "text-muted-foreground"}`}>raw</button>
                </div>
                <button
                  type="button"
                  onClick={() => setLiveTail((v) => !v)}
                  className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs ${liveTail ? "border-success/30 bg-success-bg text-success" : "text-muted-foreground"}`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full bg-success ${liveTail ? "animate-pulse" : ""}`} />
                  Live tail
                </button>
              </div>
            </TabsContent>
          </div>

          <TabsContent value="logs" className="mt-0 min-w-0">
            <LogViewer logs={logs} loading={logsLoading} wrap={wrap} requiredText={requiredLogText} />
          </TabsContent>

          <TabsContent value="traces" className="mt-0 rounded-b-xl border-x border-b bg-card p-4">
            {selectedTrace ? (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h4 className="text-sm font-medium">Trace: <span className="font-mono">{selectedTrace.trace_id}</span></h4>
                  <Button variant="ghost" size="sm" onClick={() => setSelectedTrace(null)}>Back to list</Button>
                </div>
                <TraceGraph trace={selectedTrace} loading={traceDetailLoading} />
              </div>
            ) : (
              <>
                <div className="mb-2 text-xs text-muted-foreground">
                  Showing OTEL traces for session <span className="font-mono">{session.session_id}</span>. Click a trace ID to view detailed span and event information.
                </div>
                <TraceList traces={traces} loading={tracesLoading} onSelectTrace={handleSelectTrace} />
              </>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
