import { useState, useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { ChevronRight, ChevronDown } from "lucide-react";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import type { TraceDetailResponse, TraceSpan, TraceEvent } from "@/api/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(ms: number): string {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

const ROLE_COLORS: Record<string, string> = {
  user: "text-blue-600 dark:text-blue-400",
  assistant: "text-green-600 dark:text-green-400",
  tool: "text-orange-600 dark:text-orange-400",
  system: "text-muted-foreground",
};

function roleColor(role: string): string {
  return ROLE_COLORS[role] ?? "text-foreground";
}

/** Try to parse a JSON string; return formatted if valid, raw otherwise. */
function tryFormatJson(value: unknown): string {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return value;
    }
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value, null, 2);
  }
  return String(value ?? "");
}

/** Derive a short summary from an event body for the event list header. */
function summarizeBody(body: Record<string, unknown> | string): string {
  if (typeof body === "string") {
    return body.length > 80 ? body.slice(0, 80) + "…" : body;
  }

  if ("input" in body) {
    const msgs = ((body.input as Record<string, unknown>)?.messages as Record<string, unknown>[]) ?? [];
    return msgs[0]?.role ? `input (${msgs[0].role})` : "input";
  }
  if ("output" in body) {
    const msgs = ((body.output as Record<string, unknown>)?.messages as Record<string, unknown>[]) ?? [];
    return msgs[0]?.role ? `output (${msgs[0].role})` : "output";
  }

  // Fallback: try to get a short description from body keys
  const keys = Object.keys(body);
  if (keys.length === 0) return "empty";
  return keys.slice(0, 3).join(", ");
}

// Palette for span bars
const SPAN_COLORS = [
  { bg: "bg-blue-500", hover: "bg-blue-400", ring: "ring-blue-300" },
  { bg: "bg-emerald-500", hover: "bg-emerald-400", ring: "ring-emerald-300" },
  { bg: "bg-amber-500", hover: "bg-amber-400", ring: "ring-amber-300" },
  { bg: "bg-violet-500", hover: "bg-violet-400", ring: "ring-violet-300" },
  { bg: "bg-rose-500", hover: "bg-rose-400", ring: "ring-rose-300" },
  { bg: "bg-cyan-500", hover: "bg-cyan-400", ring: "ring-cyan-300" },
  { bg: "bg-orange-500", hover: "bg-orange-400", ring: "ring-orange-300" },
  { bg: "bg-indigo-500", hover: "bg-indigo-400", ring: "ring-indigo-300" },
];

// ---------------------------------------------------------------------------
// Waterfall timeline visualization
// ---------------------------------------------------------------------------

interface WaterfallProps {
  trace: TraceDetailResponse;
  selectedSpanId: string | null;
  hoveredSpanId: string | null;
  onSelectSpan: (spanId: string | null) => void;
  onHoverSpan: (spanId: string | null) => void;
}

function Waterfall({ trace, selectedSpanId, hoveredSpanId, onSelectSpan, onHoverSpan }: WaterfallProps) {
  const { timezone } = useTimezone();
  const traceStart = new Date(trace.start_time_iso).getTime();
  const totalMs = trace.duration_ms || 1;

  const hoveredSpan = hoveredSpanId ? trace.spans.find((s) => s.span_id === hoveredSpanId) : null;

  return (
    <div className="rounded-md border bg-muted/40 overflow-hidden">
      <div className="bg-muted/30 px-3 py-2 border-b flex items-center justify-between">
        <div className="text-xs font-medium">Trace Timeline</div>
        <div className="text-[10px] text-muted-foreground font-mono">
          {formatDuration(trace.duration_ms)}
        </div>
      </div>
      <div className="divide-y" onMouseLeave={() => onHoverSpan(null)}>
        {trace.spans.map((span, i) => {
          const spanStart = new Date(span.start_time_iso).getTime();
          const offsetMs = spanStart - traceStart;
          const leftPct = Math.max(0, (offsetMs / totalMs) * 100);
          const widthPct = Math.max(0.5, (span.duration_ms / totalMs) * 100);
          const color = SPAN_COLORS[i % SPAN_COLORS.length]!;
          const isSelected = selectedSpanId === span.span_id;
          const isHovered = hoveredSpanId === span.span_id;

          return (
            <button
              key={span.span_id}
              type="button"
              className={`w-full text-left flex items-center gap-3 px-3 py-2 transition-colors ${
                isSelected ? "bg-muted" : isHovered ? "bg-foreground/5" : "hover:bg-foreground/5"
              }`}
              onClick={() => onSelectSpan(isSelected ? null : span.span_id)}
              onMouseEnter={() => onHoverSpan(span.span_id)}
            >
              {/* Label */}
              <div className="w-[200px] shrink-0 min-w-0">
                <div className="text-[10px] font-mono truncate">
                  {span.span_id}
                </div>
                <div className="text-[10px] text-muted-foreground truncate" title={span.scope}>
                  {span.scope}
                </div>
              </div>

              {/* Bar area */}
              <div className="flex-1 min-w-0 relative h-7">
                {/* Background track */}
                <div className="absolute inset-0 bg-muted/30 rounded" />
                {/* Span bar */}
                <div
                  className={`absolute top-0.5 bottom-0.5 rounded transition-all ${color.bg} ${
                    isHovered || isSelected ? `${color.hover} ring-2 ${color.ring}` : ""
                  }`}
                  style={{
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    minWidth: "4px",
                  }}
                />
                {/* Duration label */}
                <div
                  className="absolute top-0.5 bottom-0.5 flex items-center pointer-events-none"
                  style={{ left: `${leftPct + widthPct + 0.5}%` }}
                >
                  <span className="text-[10px] font-mono text-muted-foreground whitespace-nowrap pl-1">
                    {formatDuration(span.duration_ms)}
                  </span>
                </div>
              </div>

              {/* Event count */}
              <div className="w-[50px] shrink-0 text-right">
                <Badge variant="outline" className="text-[9px] px-1 py-0">
                  {span.event_count}
                </Badge>
              </div>
            </button>
          );
        })}
      </div>

      {/* Span detail panel — always visible, fixed two rows */}
      <div className="border-t bg-muted/20 px-3 py-2 text-xs space-y-0.5">
        <div className="flex gap-4">
          <div>
            <span className="text-muted-foreground">Span ID: </span>
            <span className="font-mono">{hoveredSpan ? hoveredSpan.span_id : "—"}</span>
          </div>
          {hoveredSpan && (
            <div>
              <span className="text-muted-foreground">Scope: </span>
              <span>{hoveredSpan.scope}</span>
            </div>
          )}
        </div>
        {hoveredSpan ? (
          <div className="flex gap-4 overflow-hidden">
            <div className="shrink-0">
              <span className="text-muted-foreground">Duration: </span>
              <span className="font-mono">{formatDuration(hoveredSpan.duration_ms)}</span>
            </div>
            <div className="shrink-0">
              <span className="text-muted-foreground">Events: </span>
              <span className="font-mono">{hoveredSpan.event_count}</span>
            </div>
            <div className="shrink-0">
              <span className="text-muted-foreground">Start: </span>
              <span className="font-mono">{formatTimestamp(hoveredSpan.start_time_iso, timezone)}</span>
            </div>
            <div className="shrink-0">
              <span className="text-muted-foreground">End: </span>
              <span className="font-mono">{formatTimestamp(hoveredSpan.end_time_iso, timezone)}</span>
            </div>
          </div>
        ) : (
          <div className="text-muted-foreground">Hover over a span to see details</div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------

function MessageBlock({ message }: { message: Record<string, unknown> }) {
  const role = (message.role as string) ?? "unknown";
  const content = message.content as Record<string, unknown> | string | undefined;

  let displayContent: string;
  if (typeof content === "string") {
    displayContent = tryFormatJson(content);
  } else if (content && typeof content === "object") {
    const inner = (content as Record<string, unknown>).message
      ?? (content as Record<string, unknown>).content
      ?? content;
    displayContent = tryFormatJson(inner);
  } else {
    displayContent = tryFormatJson(message);
  }

  return (
    <div className="space-y-0.5">
      <div className={`text-[10px] font-medium uppercase tracking-wide ${roleColor(role)}`}>
        {role}
      </div>
      <pre className="whitespace-pre-wrap font-mono text-xs text-foreground break-all">
        {displayContent}
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Event body rendering
// ---------------------------------------------------------------------------

function EventBody({ body }: { body: Record<string, unknown> | string }) {
  if (typeof body === "string") {
    return (
      <pre className="whitespace-pre-wrap font-mono text-xs text-foreground break-all">
        {body}
      </pre>
    );
  }

  // Single direction: input or output with messages
  const direction = "input" in body ? "input" : "output" in body ? "output" : null;
  if (direction) {
    const messages = ((body[direction] as Record<string, unknown>)?.messages as Record<string, unknown>[]) ?? [];
    if (messages.length > 0) {
      return (
        <div className="space-y-1">
          <div className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">{direction}</div>
          {messages.map((msg, i) => (
            <MessageBlock key={`${direction}-${i}`} message={msg} />
          ))}
        </div>
      );
    }
  }

  return (
    <pre className="whitespace-pre-wrap font-mono text-xs text-foreground break-all">
      {tryFormatJson(body)}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// Flattened event with span context (for the right panel)
// ---------------------------------------------------------------------------

interface FlatEvent {
  span: TraceSpan;
  event: TraceEvent;
  globalIndex: number;
  duration_ms: number;
}

// ---------------------------------------------------------------------------
// Main TraceGraph component
// ---------------------------------------------------------------------------

interface TraceGraphProps {
  trace: TraceDetailResponse;
  loading?: boolean;
}

export function TraceGraph({ trace, loading }: TraceGraphProps) {
  const { timezone } = useTimezone();
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [hoveredSpanId, setHoveredSpanId] = useState<string | null>(null);
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set());

  // Build flat event list with global numbering and per-event durations
  const allEvents: FlatEvent[] = useMemo(() => {
    const result: FlatEvent[] = [];
    for (const span of trace.spans) {
      const spanEvts = [...span.events].sort((a, b) =>
        a.observed_time_iso.localeCompare(b.observed_time_iso),
      );
      for (let i = 0; i < spanEvts.length; i++) {
        const ev = spanEvts[i]!;
        const curMs = new Date(ev.observed_time_iso).getTime();
        const prevMs = i > 0
          ? new Date(spanEvts[i - 1]!.observed_time_iso).getTime()
          : new Date(span.start_time_iso).getTime();
        result.push({ span, event: ev, globalIndex: 0, duration_ms: Math.max(0, curMs - prevMs) });
      }
    }
    // Sort all events by observed time
    result.sort((a, b) =>
      a.event.observed_time_iso.localeCompare(b.event.observed_time_iso),
    );
    // Re-number after sort
    result.forEach((e, i) => (e.globalIndex = i));
    return result;
  }, [trace.spans]);

  // Filter events by selected span
  const visibleEvents = selectedSpanId
    ? allEvents.filter((e) => e.span.span_id === selectedSpanId)
    : allEvents;

  const maxEventDuration = useMemo(
    () => visibleEvents.reduce((max, e) => Math.max(max, e.duration_ms), 0),
    [visibleEvents],
  );

  const toggleEvent = (idx: number) => {
    setExpandedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  if (loading) {
    return <div className="text-sm text-muted-foreground py-4">Loading trace detail...</div>;
  }

  return (
    <div className="space-y-3">
      {/* Waterfall timeline */}
      <Waterfall
        trace={trace}
        selectedSpanId={selectedSpanId}
        hoveredSpanId={hoveredSpanId}
        onSelectSpan={setSelectedSpanId}
        onHoverSpan={setHoveredSpanId}
      />

      {/* Two-panel layout */}
      <div className="flex gap-4 items-start">
        {/* Left panel: Span list */}
        <div className="w-[320px] shrink-0 rounded-md border bg-muted/40 overflow-hidden">
          <div className="bg-muted/30 px-3 py-2 border-b">
            <div className="text-xs font-medium">
              Total spans ({trace.span_count})
            </div>
          </div>
          <div className="max-h-[600px] overflow-y-auto divide-y">
            {/* "All spans" option */}
            <button
              type="button"
              className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                selectedSpanId === null ? "bg-muted" : "bg-card hover:bg-foreground/10"
              }`}
              onClick={() => setSelectedSpanId(null)}
            >
              <div className="font-medium">All spans</div>
              <div className="text-muted-foreground">{trace.event_count} events</div>
            </button>
            {trace.spans.map((span) => (
              <button
                key={span.span_id}
                type="button"
                className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                  selectedSpanId === span.span_id ? "bg-muted" : "bg-card hover:bg-foreground/10"
                }`}
                onClick={() => setSelectedSpanId(span.span_id)}
                onMouseEnter={() => setHoveredSpanId(span.span_id)}
                onMouseLeave={() => setHoveredSpanId(null)}
              >
                <div className="flex items-center gap-1.5">
                  <span className="font-mono truncate flex-1">{span.span_id}</span>
                  <Badge variant="outline" className="text-[9px] px-1 py-0 shrink-0">
                    {span.event_count}
                  </Badge>
                </div>
                <div className="text-muted-foreground truncate mt-0.5">
                  {span.scope}
                </div>
                <div className="text-muted-foreground mt-0.5">
                  {formatDuration(span.duration_ms)}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Right panel: Events */}
        <div className="flex-1 min-w-0 rounded-md border bg-muted/40 overflow-hidden">
          <div className="bg-muted/30 px-3 py-2 border-b flex items-center justify-between">
            <div className="text-xs font-medium">
              {selectedSpanId
                ? `Events for span ${selectedSpanId} (${visibleEvents.length})`
                : `All Events (${visibleEvents.length})`}
            </div>
            {visibleEvents.length > 0 && (
              <button
                type="button"
                className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                onClick={() => {
                  const allVisible = visibleEvents.every((e) => expandedEvents.has(e.globalIndex));
                  if (allVisible) {
                    setExpandedEvents(new Set());
                  } else {
                    setExpandedEvents(new Set(visibleEvents.map((e) => e.globalIndex)));
                  }
                }}
              >
                {visibleEvents.every((e) => expandedEvents.has(e.globalIndex)) ? "Collapse all" : "Expand all"}
              </button>
            )}
          </div>
          <div className="max-h-[600px] overflow-y-auto divide-y">
            {visibleEvents.length === 0 && (
              <div className="text-sm text-muted-foreground py-8 text-center">
                No events found.
              </div>
            )}
            {visibleEvents.map((fe) => {
              const isExpanded = expandedEvents.has(fe.globalIndex);
              const summary = summarizeBody(fe.event.body);
              const isSlowest = fe.duration_ms > 0 && fe.duration_ms === maxEventDuration;
              return (
                <div key={fe.globalIndex} className="bg-card">
                  {/* Event header — always visible */}
                  <button
                    type="button"
                    className="w-full text-left px-3 py-2 hover:bg-muted/50 transition-colors"
                    onClick={() => toggleEvent(fe.globalIndex)}
                  >
                    <div className="flex items-start gap-2">
                      {isExpanded ? (
                        <ChevronDown className="h-3.5 w-3.5 shrink-0 mt-0.5 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 mt-0.5 text-muted-foreground" />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="text-[9px] px-1.5 py-0 shrink-0 bg-white dark:bg-zinc-900">
                            Event {fe.globalIndex + 1}
                          </Badge>
                          <span className="text-xs text-foreground truncate">{summary}</span>
                          <span className={`ml-auto shrink-0 text-[10px] font-mono px-1.5 py-0 rounded border ${
                            isSlowest
                              ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 border-amber-300 dark:border-amber-700"
                              : "bg-white dark:bg-zinc-900 text-muted-foreground border-border"
                          }`}>
                            {formatDuration(fe.duration_ms)}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 mt-0.5">
                          <span className="text-[10px] text-muted-foreground font-mono">
                            {formatTimestamp(fe.event.observed_time_iso, timezone)}
                          </span>
                          <button
                            type="button"
                            className="text-[10px] font-mono text-blue-600 dark:text-blue-400 hover:underline"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedSpanId(fe.span.span_id);
                            }}
                          >
                            {fe.span.span_id}
                          </button>
                          <span className="text-[10px] text-muted-foreground truncate">
                            {fe.event.scope}
                          </span>
                        </div>
                      </div>
                    </div>
                  </button>

                  {/* Event body — expanded */}
                  {isExpanded && (
                    <div className="px-3 pb-3 pl-8">
                      <div className="rounded-md border bg-background p-3">
                        <EventBody body={fe.event.body} />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
