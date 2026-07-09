import { useEffect, useCallback, useState, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Clock, Hash, RefreshCw } from "lucide-react";
import { InvocationTable } from "@/components/InvocationTable";
import { LogViewer } from "@/components/LogViewer";
import { TraceList } from "@/components/TraceList";
import { TraceGraph } from "@/components/TraceGraph";
import { useLogs } from "@/hooks/useLogs";
import { useTraces } from "@/hooks/useTraces";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import type { SessionResponse, AgentResponse, LogStreamInfo } from "@/api/types";
import type { TimezonePreference } from "@/contexts/TimezoneContext";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";

const SESSION_LOGS_VALUE = "__session__";

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

interface SessionDetailPageProps {
  agent: AgentResponse;
  session: SessionResponse;
  onSelectInvocation?: (invocationId: string) => void;
}

export function SessionDetailPage({ agent, session, onSelectInvocation }: SessionDetailPageProps) {
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
  const [showTimestamp, setShowTimestamp] = useState(true);
  const [showLineNumbers, setShowLineNumbers] = useState(true);
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

  const selectedValue = activeStream || SESSION_LOGS_VALUE;
  const sortedStreams = sortStreams(streams);

  return (
    <div className="space-y-6">
      <Card className="max-w-lg">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Session Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <div className="text-xs text-muted-foreground">Session ID</div>
            <div className="font-mono text-sm">{session.session_id}</div>
          </div>
          <div className="flex gap-6 text-sm">
            {session.user_id && (
              <div>
                <div className="text-xs text-muted-foreground">Invoked By</div>
                <div className="text-sm mt-0.5 font-mono">{session.user_id}</div>
              </div>
            )}
            <div>
              <div className="text-xs text-muted-foreground">Qualifier</div>
              <Badge variant="outline" className="mt-0.5">{session.qualifier}</Badge>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Status</div>
              <Badge
                className="mt-0.5"
                variant={
                  session.live_status === "active"
                    ? "default"
                    : session.live_status === "error"
                      ? "destructive"
                      : session.live_status === "expired"
                        ? "outline"
                        : "secondary"
                }
              >
                {session.live_status}
              </Badge>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Created</div>
              <div className="text-sm mt-0.5">{formatTimestamp(session.created_at, timezone)}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <InvocationTable invocations={session.invocations} onSelectInvocation={onSelectInvocation} />

      <Tabs defaultValue="logs" onValueChange={handleTabChange}>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
            <TabsList>
              <TabsTrigger value="logs">Logs</TabsTrigger>
              <TabsTrigger value="traces">Traces</TabsTrigger>
            </TabsList>
            <TabsContent value="logs" className="mt-0 flex items-center gap-3">
              <Select value={selectedValue} onValueChange={handleStreamChange}>
                <SelectTrigger size="sm" className="text-xs max-w-[680px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectLabel>Source</SelectLabel>
                    <SelectItem value={SESSION_LOGS_VALUE}>
                      Service-level logs (filtered by session)
                    </SelectItem>
                  </SelectGroup>
                  {sortedStreams.length > 0 && (
                    <>
                      <SelectSeparator />
                      <SelectGroup>
                        <SelectLabel>Log Streams</SelectLabel>
                        {sortedStreams.map((s) => (
                          <SelectItem key={s.name} value={s.name}>
                            {formatStreamName(s.name, s.last_event_time, timezone)}
                          </SelectItem>
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
                          <SelectItem key={src.key} value={src.key}>
                            {src.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </>
                  )}
                </SelectContent>
              </Select>
              {streamsLoading && (
                <span className="text-xs text-muted-foreground">Loading streams...</span>
              )}
            </TabsContent>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant={showLineNumbers ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setShowLineNumbers((v) => !v)}
            >
              <Hash className="h-4 w-4 mr-1" />
              Lines
            </Button>
            <Button
              variant={showTimestamp ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setShowTimestamp((v) => !v)}
            >
              <Clock className="h-4 w-4 mr-1" />
              Timestamps
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="w-[120px]"
              onClick={refreshLogs}
              disabled={logsLoading}
            >
              <RefreshCw className={`h-4 w-4 mr-1 ${logsLoading ? "animate-spin" : ""}`} />
              {logsLoading ? "Refreshing..." : "Refresh"}
            </Button>
          </div>
        </div>
        <TabsContent value="logs" className="mt-0">
          <div className="text-xs text-muted-foreground mb-2">
            {activeStream.startsWith("vended:")
              ? <>Showing vended logs: {vendedSources.find((s) => s.key === activeStream)?.label ?? activeStream}</>
              : activeStream
                ? <>Showing stream: {formatStreamName(activeStream, undefined, timezone)}</>
                : <>Showing service-level logs matching session <span className="font-mono">{session.session_id}</span></>
            }
          </div>
          <LogViewer logs={logs} loading={logsLoading} showTimestamp={showTimestamp} showLineNumbers={showLineNumbers} />
        </TabsContent>

        <TabsContent value="traces" className="mt-0">
          {selectedTrace ? (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-medium">
                  Trace: <span className="font-mono">{selectedTrace.trace_id}</span>
                </h4>
                <Button variant="ghost" size="sm" onClick={() => setSelectedTrace(null)}>
                  Back to list
                </Button>
              </div>
              <TraceGraph trace={selectedTrace} loading={traceDetailLoading} />
            </div>
          ) : (
            <>
              <div className="text-xs text-muted-foreground mb-2">
                Showing OTEL traces for session <span className="font-mono">{session.session_id}</span>. Click a trace ID to view detailed span and event information.
              </div>
              <TraceList
                traces={traces}
                loading={tracesLoading}
                onSelectTrace={handleSelectTrace}
              />
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
