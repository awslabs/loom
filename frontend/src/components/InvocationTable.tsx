import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp, formatMs } from "@/lib/format";
import type { InvocationResponse } from "@/api/types";

interface InvocationTableProps {
  invocations: InvocationResponse[];
  onSelectInvocation?: (invocationId: string) => void;
}

function formatTokens(count: number | null | undefined): string {
  if (count == null) return "—";
  if (count >= 10000) return `${(count / 1000).toFixed(1)}K`;
  return count.toLocaleString();
}

function formatCost(cost: number | null | undefined): string {
  if (cost == null) return "—";
  if (cost === 0) return "~$0.00";
  if (cost < 0.01) return `~$${cost.toFixed(6)}`;
  return `~$${cost.toFixed(4)}`;
}

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "complete":
      return "default";
    case "streaming":
    case "pending":
      return "secondary";
    case "error":
      return "destructive";
    default:
      return "outline";
  }
}

function invocationRuntime(inv: InvocationResponse): number | null {
  const cpuCost = inv.compute_cpu_cost ?? 0;
  const memCost = (inv.compute_memory_cost ?? 0) + (inv.idle_memory_cost ?? 0);
  const total = cpuCost + memCost;
  return total > 0 ? total : null;
}

function invocationMemory(inv: InvocationResponse): number | null {
  const stm = inv.stm_cost ?? 0;
  const ltm = inv.ltm_cost ?? 0;
  const total = stm + ltm;
  return total > 0 ? total : null;
}

function invocationTotal(inv: InvocationResponse): number | null {
  const model = inv.estimated_cost ?? 0;
  const rt = invocationRuntime(inv) ?? 0;
  const mem = invocationMemory(inv) ?? 0;
  const total = model + rt + mem;
  return total > 0 ? total : null;
}

export function InvocationTable({ invocations, onSelectInvocation }: InvocationTableProps) {
  const { timezone } = useTimezone();

  if (invocations.length === 0) {
    return <div className="text-sm text-muted-foreground py-4">No invocations</div>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[36ch]">Request ID</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Cold Start</TableHead>
          <TableHead className="text-right">Duration</TableHead>
          <TableHead className="text-right">Tokens</TableHead>
          <TableHead className="text-right">Model</TableHead>
          <TableHead className="text-right">Runtime</TableHead>
          <TableHead className="text-right">Memory</TableHead>
          <TableHead className="text-right">Total</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {invocations.map((inv) => (
          <TableRow
            key={inv.invocation_id}
            className={onSelectInvocation ? "cursor-pointer hover:bg-accent/50" : ""}
            onClick={() => onSelectInvocation?.(inv.invocation_id)}
          >
            <TableCell className="font-mono text-xs">
              {inv.request_id ?? "—"}
            </TableCell>
            <TableCell>
              <Badge variant={statusVariant(inv.status)}>{inv.status}</Badge>
            </TableCell>
            <TableCell className="font-mono text-xs text-right">
              {formatMs(inv.cold_start_latency_ms)}
            </TableCell>
            <TableCell className="font-mono text-xs text-right">
              {formatMs(inv.client_duration_ms)}
            </TableCell>
            <TableCell className="font-mono text-xs text-right">
              <span>{formatTokens(inv.input_tokens)}</span>
              <span className="text-muted-foreground mx-0.5">/</span>
              <span>{formatTokens(inv.output_tokens)}</span>
            </TableCell>
            <TableCell className="font-mono text-xs text-right">
              {formatCost(inv.estimated_cost)}
            </TableCell>
            <TableCell className="font-mono text-xs text-right">
              {formatCost(invocationRuntime(inv))}
            </TableCell>
            <TableCell className="font-mono text-xs text-right">
              {formatCost(invocationMemory(inv))}
            </TableCell>
            <TableCell className="font-mono text-xs text-right">
              {formatCost(invocationTotal(inv))}
            </TableCell>
            <TableCell className="text-xs text-muted-foreground">
              {formatTimestamp(inv.created_at, timezone)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
