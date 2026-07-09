import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import type { TraceSummary } from "@/api/types";

interface TraceListProps {
  traces: TraceSummary[];
  loading: boolean;
  onSelectTrace?: (traceId: string) => void;
}

function formatDuration(ms: number): string {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function TraceList({ traces, loading, onSelectTrace }: TraceListProps) {
  const { timezone } = useTimezone();

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (traces.length === 0) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        No traces found. Traces appear after invocations complete and OTEL telemetry is exported.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[280px]">Trace ID</TableHead>
          <TableHead>Start Time</TableHead>
          <TableHead>End Time</TableHead>
          <TableHead className="text-right">Duration</TableHead>
          <TableHead className="text-right">Spans</TableHead>
          <TableHead className="text-right">Events</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {traces.map((t) => (
          <TableRow
            key={t.trace_id}
            className={onSelectTrace ? "cursor-pointer hover:bg-muted/50" : ""}
            onClick={() => onSelectTrace?.(t.trace_id)}
          >
            <TableCell className="font-mono text-xs truncate max-w-[280px]">
              {t.trace_id}
            </TableCell>
            <TableCell className="text-sm whitespace-nowrap">
              {formatTimestamp(t.start_time_iso, timezone)}
            </TableCell>
            <TableCell className="text-sm whitespace-nowrap">
              {formatTimestamp(t.end_time_iso, timezone)}
            </TableCell>
            <TableCell className="text-right font-mono text-sm">
              {formatDuration(t.duration_ms)}
            </TableCell>
            <TableCell className="text-right font-mono text-sm">
              {t.span_count}
            </TableCell>
            <TableCell className="text-right font-mono text-sm">
              {t.event_count}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
