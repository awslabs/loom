import { useState, useMemo } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import type { SessionResponse } from "@/api/types";

interface SessionTableProps {
  sessions: SessionResponse[];
  onSelectSession: (sessionId: string) => void;
  loading: boolean;
  currentUserId?: string;
}

type SortDir = "asc" | "desc";

const PAGE_SIZE = 5;

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "active":
      return "default";
    case "streaming":
    case "pending":
      return "secondary";
    case "expired":
      return "outline";
    case "error":
      return "destructive";
    default:
      return "outline";
  }
}

export function SessionTable({ sessions, onSelectSession, loading, currentUserId }: SessionTableProps) {
  const { timezone } = useTimezone();
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    return [...sessions].sort((a, b) => {
      const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
      const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
      return sortDir === "desc" ? tb - ta : ta - tb;
    });
  }, [sessions, sortDir]);

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const paged = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const toggleSort = () => {
    setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    setPage(0);
  };

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (sessions.length === 0) {
    return <div className="text-sm text-muted-foreground py-4">No sessions yet</div>;
  }

  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[36ch]">Session ID</TableHead>
            <TableHead>Invoked By</TableHead>
            <TableHead>Qualifier</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Invocations</TableHead>
            <TableHead>
              <Button
                variant="ghost"
                size="sm"
                className="h-auto p-0 font-medium hover:bg-transparent"
                onClick={toggleSort}
              >
                Created {sortDir === "desc" ? "↓" : "↑"}
              </Button>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {paged.map((session) => (
            <TableRow
              key={session.session_id}
              className="cursor-pointer hover:bg-accent/50"
              onClick={() => onSelectSession(session.session_id)}
            >
              <TableCell className="font-mono text-xs">
                {session.session_id}
              </TableCell>
              <TableCell className="text-xs">
                {session.user_id ? (
                  <span className={currentUserId && session.user_id !== currentUserId ? "text-muted-foreground" : ""}>
                    {session.user_id}
                  </span>
                ) : (
                  <span className="text-muted-foreground">&mdash;</span>
                )}
              </TableCell>
              <TableCell>
                <Badge variant="outline">{session.qualifier}</Badge>
              </TableCell>
              <TableCell>
                <Badge variant={statusVariant(session.live_status)}>{session.live_status}</Badge>
              </TableCell>
              <TableCell>{session.invocations.length}</TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatTimestamp(session.created_at, timezone)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2 px-1">
          <span className="text-xs text-muted-foreground">
            {sorted.length} sessions &mdash; page {page + 1} of {totalPages}
          </span>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" className="h-6 text-xs" disabled={page === 0} onClick={() => setPage(page - 1)}>
              Prev
            </Button>
            <Button variant="ghost" size="sm" className="h-6 text-xs" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
