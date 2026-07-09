import { useState, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatLogTime } from "@/lib/format";
import type { LogEvent } from "@/api/types";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Search, X } from "lucide-react";

const PAGE_SIZE = 100;

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
      <mark key={i} className="bg-yellow-200 dark:bg-yellow-800 rounded-sm px-0.5">{part}</mark>
    ) : (
      part
    ),
  );
}

interface LogViewerProps {
  logs: LogEvent[];
  loading: boolean;
  showTimestamp?: boolean;
  showLineNumbers?: boolean;
}

export function LogViewer({ logs, loading, showTimestamp = true, showLineNumbers = true }: LogViewerProps) {
  const { timezone } = useTimezone();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");

  // Filter logs across all pages, preserving original line numbers
  const filteredEntries = useMemo(() => {
    const entries = logs.map((e, i) => ({ event: e, originalIndex: i + 1 }));
    if (!search.trim()) return entries;
    const term = search.toLowerCase();
    return entries.filter((e) => e.event.message.toLowerCase().includes(term));
  }, [logs, search]);
  const filteredLogs = useMemo(() => filteredEntries.map((e) => e.event), [filteredEntries]);

  // Reset to page 1 when logs or search change
  useEffect(() => {
    setPage(1);
  }, [logs, search]);

  if (loading) {
    return (
      <div className="space-y-1">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-4 w-full" />
        ))}
      </div>
    );
  }

  if (logs.length === 0) {
    return <div className="text-sm text-muted-foreground py-4">No logs available</div>;
  }

  const totalPages = Math.ceil(filteredEntries.length / PAGE_SIZE);
  const start = (page - 1) * PAGE_SIZE;
  const end = Math.min(start + PAGE_SIZE, filteredEntries.length);
  const visibleEntries = filteredEntries.slice(start, end);

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          placeholder="Filter logs (e.g. LOOM_MEMORY_TELEMETRY)"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 pl-8 pr-8 text-xs font-mono"
        />
        {search && (
          <button
            onClick={() => setSearch("")}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {search && (
        <div className="text-xs text-muted-foreground">
          {filteredLogs.length} of {logs.length} log lines match &ldquo;{search}&rdquo;
        </div>
      )}

      {filteredEntries.length > 0 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            Showing {start + 1}&ndash;{end} of {filteredEntries.length} log lines
          </span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === 1} onClick={() => setPage(1)}>
              <ChevronsLeft className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            {getPageNumbers(page, totalPages).map((n, i) =>
              n === null ? (
                <span key={`e-${i}`} className="px-0.5">…</span>
              ) : (
                <Button key={n} variant={n === page ? "default" : "ghost"} size="icon" className="h-6 w-6 text-xs" onClick={() => setPage(n)}>{n}</Button>
              )
            )}
            <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === totalPages} onClick={() => setPage((p) => p + 1)}>
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === totalPages} onClick={() => setPage(totalPages)}>
              <ChevronsRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}

      <div className="rounded border bg-input-bg p-3 font-mono text-xs leading-relaxed">
        {visibleEntries.map(({ event, originalIndex }) => (
          <div key={originalIndex} className="flex gap-3 hover:bg-accent/30 py-0.5">
            {showLineNumbers && (
              <span className="shrink-0 text-muted-foreground text-right select-none" style={{ minWidth: `${String(logs.length).length + 0.5}ch` }}>
                {originalIndex}
              </span>
            )}
            {showTimestamp && (
              <span className="shrink-0 text-muted-foreground">
                {formatLogTime(event.timestamp_iso, timezone)}
              </span>
            )}
            <span className="whitespace-pre-wrap break-all">
              {search.trim() ? highlightMatch(event.message, search) : event.message}
            </span>
          </div>
        ))}
      </div>

      {filteredEntries.length > 0 && (
        <div className="flex items-center justify-end text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === 1} onClick={() => setPage(1)}>
              <ChevronsLeft className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            {getPageNumbers(page, totalPages).map((n, i) =>
              n === null ? (
                <span key={`e-${i}`} className="px-0.5">…</span>
              ) : (
                <Button key={n} variant={n === page ? "default" : "ghost"} size="icon" className="h-6 w-6 text-xs" onClick={() => setPage(n)}>{n}</Button>
              )
            )}
            <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === totalPages} onClick={() => setPage((p) => p + 1)}>
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6" disabled={page === totalPages} onClick={() => setPage(totalPages)}>
              <ChevronsRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
