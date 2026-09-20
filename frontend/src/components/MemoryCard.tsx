import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loader2, Trash2, Pencil } from "lucide-react";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant } from "@/lib/status";
import { StatusPill } from "@/components/StatusPill";
import type { MemoryResponse } from "@/api/types";

interface MemoryCardProps {
  memory: MemoryResponse;
  now: number;
  submitting: boolean;
  onDelete: (id: number, deleteInAws: boolean) => void;
  onEdit?: (id: number) => void;
  readOnly?: boolean;
  showOnCardKeys?: string[];
  deleteStartTime?: number;
  userGroups?: string[];
  /** Highest cost among sibling cards in the same group, for the share-of-max bar. */
  maxCost?: number;
}

function isTransitional(status: string): boolean {
  return status === "CREATING" || status === "DELETING";
}

export function MemoryCard({
  memory,
  now,
  submitting,
  onDelete,
  onEdit,
  readOnly,
  showOnCardKeys,
  deleteStartTime,
  userGroups = [],
  maxCost,
}: MemoryCardProps) {
  const { timezone } = useTimezone();
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [cleanupAws, setCleanupAws] = useState(false);

  const transitional = isTransitional(memory.status);

  // Check if user can delete this resource
  const isSuperAdmin = userGroups.includes("g-admins-super");
  const isDemoAdmin = userGroups.includes("g-admins-demo") && !isSuperAdmin;
  const resourceGroup = memory.tags?.["loom:group"] || "";
  const canDelete = !readOnly && (!isDemoAdmin || resourceGroup === "demo");

  // For DELETING, use the recorded start time from when the user clicked delete.
  // For CREATING, use created_at as a reasonable proxy.
  const elapsedSeconds = (() => {
    if (!transitional) return 0;
    if (memory.status === "DELETING") {
      if (!deleteStartTime) return 0;
      return Math.max(0, Math.floor((now - deleteStartTime) / 1000));
    }
    if (!memory.created_at) return 0;
    return Math.max(0, Math.floor((now - new Date(memory.created_at).getTime()) / 1000));
  })();

  const strategiesCount = (() => {
    if (Array.isArray(memory.strategies_config)) return memory.strategies_config.length;
    if (Array.isArray(memory.strategies_response)) return memory.strategies_response.length;
    return 0;
  })();

  const cost = memory.cost_summary?.total_memory_estimated_cost ?? 0;
  const costLabel = cost > 0 ? (cost < 0.01 ? `$${cost.toFixed(6)}` : `$${cost.toFixed(4)}`) : null;
  const sharePct = maxCost && maxCost > 0 ? Math.min(100, Math.round((cost / maxCost) * 100)) : null;
  const labelCount = memory.tags ? Object.keys(memory.tags).length : 0;

  return (
    <Card className="group relative flex h-full flex-col gap-3.5 py-4 transition-colors hover:bg-accent/50">
      <CardHeader className="gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <CardTitle className="truncate font-mono text-sm font-medium tracking-tight" title={memory.name}>
              {memory.name}
            </CardTitle>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {memory.status !== "ACTIVE" && (
              <StatusPill label={memory.status} variant={statusVariant(memory.status)} className="shrink-0" />
            )}
            {onEdit && (
              <button
                type="button"
                onClick={() => onEdit(memory.id)}
                className="text-muted-foreground/50 opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100"
                title="Edit"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
            {canDelete && (
              <button
                type="button"
                onClick={() => setConfirmingRemove(true)}
                className="text-muted-foreground/50 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100"
                title="Delete memory"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
        {transitional && (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span className="text-[10px] tabular-nums">({elapsedSeconds}s)</span>
            <span className="text-[10px]">{memory.status === "CREATING" ? "Creating" : "Deleting"}</span>
          </div>
        )}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3.5">
        {costLabel && (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-lg font-semibold tracking-tight tabular-nums">{costLabel}</span>
              <span className="text-[11px] text-muted-foreground">est. / run</span>
              {sharePct !== null && (
                <span
                  className="ml-auto font-mono text-[10px] text-muted-foreground"
                  title={`${sharePct}% of the highest est. cost among memories currently shown (${maxCost && maxCost < 0.01 ? maxCost.toFixed(6) : maxCost?.toFixed(4)})`}
                >
                  {sharePct}% of highest shown
                </span>
              )}
            </div>
            {sharePct !== null && (
              <div className="h-[3px] overflow-hidden rounded-full bg-muted" title="Relative to the highest estimated cost among memories currently shown">
                <div className="h-full rounded-full bg-primary" style={{ width: `${sharePct}%` }} />
              </div>
            )}
          </div>
        )}
        <div className="grid grid-cols-2 gap-x-3 gap-y-2.5 text-xs">
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Region</span>
            <span className="truncate" title={memory.account_id ? `Account: ${memory.account_id}` : undefined}>{memory.region}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Event expiry</span>
            <span className="truncate">{memory.event_expiry_duration}d</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Strategies</span>
            <span className="truncate">{strategiesCount}</span>
          </div>
        </div>
        {showOnCardKeys && showOnCardKeys.length > 0 && memory.tags && Object.keys(memory.tags).length > 0 && (
          <div className="flex flex-wrap gap-1">
            {showOnCardKeys
              .filter(key => memory.tags[key])
              .map(key => (
                <Badge key={key} variant="outline" className="text-[10px] px-1.5 py-0 font-normal">
                  {key.replace(/^loom:/, "")}: {memory.tags[key]}
                </Badge>
              ))}
          </div>
        )}
        <div className="mt-auto flex items-center gap-2 border-t pt-3 text-[11px] text-muted-foreground">
          {memory.created_at && <span className="font-mono text-[10.5px]">{formatTimestamp(memory.created_at, timezone)}</span>}
          {labelCount > 0 && (
            <>
              <span className="h-2.5 w-px bg-border" />
              <span>{labelCount} label{labelCount === 1 ? "" : "s"}</span>
            </>
          )}
        </div>
        {confirmingRemove && (
          <div
            className="absolute inset-x-0 bottom-0 rounded-b-lg border-t bg-card px-4 py-2 space-y-1.5"
            onClick={(e) => e.stopPropagation()}
          >
            {memory.memory_id && (
              <label className="flex items-end justify-end gap-2 cursor-pointer select-none">
                <span className="text-[11px] whitespace-nowrap">Also delete in AgentCore</span>
                <input
                  type="checkbox"
                  checked={cleanupAws}
                  onChange={(e) => setCleanupAws(e.target.checked)}
                  className="h-3.5 w-3.5 shrink-0 mb-0.5"
                />
              </label>
            )}
            <div className="flex items-center justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                className="h-6 text-xs"
                onClick={() => {
                  setConfirmingRemove(false);
                  setCleanupAws(false);
                }}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="destructive"
                className="h-6 text-xs"
                onClick={() => {
                  onDelete(memory.id, cleanupAws);
                  setConfirmingRemove(false);
                  setCleanupAws(false);
                }}
                disabled={submitting}
              >
                Confirm
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
