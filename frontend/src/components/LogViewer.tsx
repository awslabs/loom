import { useState, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatLogTime } from "@/lib/format";
import { mergeLogEvents, type LogLevel, type MergedLogEntry } from "@/lib/logParser";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Search, X } from "lucide-react";

const PAGE_SIZE = 100;

const LEVEL_STYLE: Record<LogLevel, { chip: string; text: string }> = {
  DEBUG: { chip: "bg-status-neutral-bg text-status-neutral", text: "text-foreground" },
  INFO: { chip: "bg-status-neutral-bg text-status-neutral", text: "text-foreground" },
  WARN: { chip: "bg-warning-bg text-warning", text: "text-foreground" },
  ERROR: { chip: "bg-destructive/10 text-destructive", text: "text-destructive" },
};

function getPageNumbers(current: number, total: number): (number | null)[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  if (current <= 4) return [1, 2, 3, 4, 5, null, total];
  if (current >= total - 3) return [1, null, total - 4, total - 3, total - 2, total - 1, total];
  return [1, null, current - 1, current, current + 1, null, total];
}

function highlightMatch(text: string, term: string): React.ReactNode {
  if (!term.trim()) return text;
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return parts.map((part, i) =>
    part.toLowerCase() === term.toLowerCase() ? (
      <mark key={i} className="rounded-sm bg-yellow-400/40 px-0.5">{part}</mark>
    ) : (
      part
    ),
  );
}

function summarizeJson(json: unknown): string {
  if (Array.isArray(json)) return `${json.length} item${json.length === 1 ? "" : "s"}`;
  if (json && typeof json === "object") {
    const keys = Object.keys(json as Record<string, unknown>);
    return `${keys.length} field${keys.length === 1 ? "" : "s"}`;
  }
  return "";
}

function JsonDetail({ json }: { json: unknown }) {
  const [expanded, setExpanded] = useState(false);
  const pretty = JSON.stringify(json, null, 2);
  const handleCopy = () => {
    navigator.clipboard.writeText(pretty);
    toast.success("Copied JSON");
  };
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      {expanded && (
        <pre className="overflow-x-auto rounded-md border bg-muted px-2.5 py-2 font-mono text-[11px] leading-[1.5] whitespace-pre-wrap text-foreground">
          {pretty}
        </pre>
      )}
      <div className="flex items-center gap-2.5 font-mono text-[10.5px] text-muted-foreground">
        <button type="button" onClick={() => setExpanded((v) => !v)} className="hover:text-foreground">
          {expanded ? "collapse" : `expand · ${summarizeJson(json)}`}
        </button>
        {expanded && (
          <button type="button" onClick={handleCopy} className="hover:text-foreground">copy json</button>
        )}
      </div>
    </div>
  );
}

function LogRow({ entry, index, wrap, search }: { entry: MergedLogEntry; index: number; wrap: boolean; search: string }) {
  const { timezone } = useTimezone();
  const level = entry.parsed.level ?? "INFO";
  const style = LEVEL_STYLE[level];
  const time = formatLogTime(entry.event.timestamp_iso, timezone).slice(0, -2);

  return (
    <div className={`flex min-w-0 items-start gap-0 border-b px-3 py-[5px] ${entry.parsed.level === "ERROR" ? "bg-destructive/5" : ""}`}>
      <span className="w-[26px] shrink-0 pt-px text-right font-mono text-[10.5px] text-muted-foreground">{index}</span>
      <span className="w-[74px] shrink-0 pt-px pl-2.5 font-mono text-[10.5px] text-muted-foreground">{time}</span>
      <span className="w-[52px] shrink-0 pt-px pl-2">
        <span className={`rounded-[4px] px-[5px] py-[1px] font-mono text-[9.5px] tracking-wide ${style.chip}`}>{level}</span>
      </span>
      <div className="min-w-0 flex-1 pl-2">
        <div className={`font-mono text-[11.5px] leading-[1.55] ${style.text} ${wrap ? "overflow-hidden text-ellipsis whitespace-nowrap" : "whitespace-pre-wrap break-all"}`}>
          {entry.parsed.logger && <span className="text-success">{entry.parsed.logger} </span>}
          {search.trim() ? highlightMatch(entry.parsed.text, search) : entry.parsed.text}
        </div>
        {entry.detailJson !== null && <JsonDetail json={entry.detailJson} />}
      </div>
    </div>
  );
}

interface LogViewerProps {
  logs: import("@/api/types").LogEvent[];
  loading: boolean;
  wrap?: boolean;
  /** Extra required substring (e.g. a selected request id) ANDed with the user's search — matched against the raw message + any merged JSON detail. */
  requiredText?: string;
}

export function LogViewer({ logs, loading, wrap = true, requiredText }: LogViewerProps) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [activeLevels, setActiveLevels] = useState<Set<LogLevel>>(new Set(["DEBUG", "INFO", "WARN", "ERROR"]));

  const merged = useMemo(() => mergeLogEvents(logs), [logs]);

  const levelCounts = useMemo(() => {
    const counts: Record<LogLevel, number> = { DEBUG: 0, INFO: 0, WARN: 0, ERROR: 0 };
    merged.forEach((e) => { counts[e.parsed.level ?? "INFO"]++; });
    return counts;
  }, [merged]);

  const filteredEntries = useMemo(() => {
    const withIndex = merged.map((e, i) => ({ entry: e, originalIndex: i + 1 }));
    return withIndex.filter(({ entry }) => {
      if (!activeLevels.has(entry.parsed.level ?? "INFO")) return false;
      if (requiredText) {
        const haystack = `${entry.event.message} ${JSON.stringify(entry.detailJson ?? "")}`.toLowerCase();
        if (!haystack.includes(requiredText.toLowerCase())) return false;
      }
      if (!search.trim()) return true;
      return entry.parsed.text.toLowerCase().includes(search.toLowerCase());
    });
  }, [merged, search, activeLevels, requiredText]);

  useEffect(() => { setPage(1); }, [logs, search, activeLevels, requiredText]);

  const toggleLevel = (level: LogLevel) => {
    setActiveLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level); else next.add(level);
      return next.size === 0 ? new Set(["DEBUG", "INFO", "WARN", "ERROR"]) : next;
    });
  };

  if (loading) {
    return (
      <div className="space-y-1 p-3">
        {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-4 w-full" />)}
      </div>
    );
  }

  if (logs.length === 0) {
    return <div className="p-4 text-sm text-muted-foreground">No logs available</div>;
  }

  const totalPages = Math.max(1, Math.ceil(filteredEntries.length / PAGE_SIZE));
  const start = (page - 1) * PAGE_SIZE;
  const end = Math.min(start + PAGE_SIZE, filteredEntries.length);
  const visibleEntries = filteredEntries.slice(start, end);

  return (
    <div className="flex min-w-0 w-full flex-col overflow-hidden rounded-b-xl border-x border-b">
      {/* search + level filters */}
      <div className="flex flex-wrap items-center gap-2.5 border-b bg-muted px-3.5 py-2.5">
        <div className="relative min-w-[180px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter logs — e.g. a logger name or keyword"
            className="h-[29px] w-full rounded-md border bg-card pl-8 pr-8 font-mono text-[11.5px] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {(["DEBUG", "INFO", "WARN", "ERROR"] as LogLevel[]).filter((l) => levelCounts[l] > 0).map((level) => {
            const active = activeLevels.has(level);
            const colorClass = level === "ERROR" ? "border-destructive/30 bg-destructive/10 text-destructive" : level === "WARN" ? "border-warning/30 bg-warning-bg text-warning" : "border-border bg-input-bg text-muted-foreground";
            return (
              <button
                key={level}
                type="button"
                onClick={() => toggleLevel(level)}
                className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10.5px] transition-opacity ${colorClass} ${active ? "" : "opacity-40"}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${level === "ERROR" ? "bg-destructive" : level === "WARN" ? "bg-warning" : "bg-status-neutral"}`} />
                {level}<span>{levelCounts[level]}</span>
              </button>
            );
          })}
        </div>
        <div className="h-3.5 w-px bg-border" />
        <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">
          {filteredEntries.length > 0 ? `${start + 1}–${end} of ${filteredEntries.length}` : "0 of 0"}
        </span>
      </div>

      {/* body */}
      <div className="flex min-w-0 flex-col overflow-x-hidden bg-card">
        {visibleEntries.length === 0 ? (
          <div className="p-4 text-sm text-muted-foreground">No log lines match the current filters.</div>
        ) : (
          visibleEntries.map(({ entry, originalIndex }) => (
            <LogRow key={originalIndex} entry={entry} index={originalIndex} wrap={wrap} search={search} />
          ))
        )}

        {filteredEntries.length > 0 && (
          <div className="flex items-center gap-2.5 bg-muted px-3 py-2">
            <span className="font-mono text-[10.5px] text-muted-foreground tabular-nums">{visibleEntries.length} of {filteredEntries.length} lines</span>
            <div className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:bg-accent hover:text-foreground" disabled={page === 1} onClick={() => setPage(1)}>
                <ChevronsLeft className="h-3.5 w-3.5" />
              </Button>
              <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:bg-accent hover:text-foreground" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              {getPageNumbers(page, totalPages).map((n, i) =>
                n === null ? (
                  <span key={`e-${i}`} className="px-0.5 text-muted-foreground">…</span>
                ) : (
                  <button
                    key={n}
                    onClick={() => setPage(n)}
                    className={`flex h-6 min-w-6 items-center justify-center rounded-[5px] font-mono text-[10.5px] ${n === page ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}
                  >
                    {n}
                  </button>
                ),
              )}
              <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:bg-accent hover:text-foreground" disabled={page === totalPages} onClick={() => setPage((p) => p + 1)}>
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
              <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:bg-accent hover:text-foreground" disabled={page === totalPages} onClick={() => setPage(totalPages)}>
                <ChevronsRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
