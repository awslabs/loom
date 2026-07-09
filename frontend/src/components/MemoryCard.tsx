import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loader2, Trash2, Pencil } from "lucide-react";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant } from "@/lib/status";
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

  return (
    <Card className="relative py-3 gap-1 transition-colors hover:bg-accent/50">
      <CardHeader className="gap-1 pb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <CardTitle className="text-sm font-medium truncate" title={memory.name}>
              {memory.name}
            </CardTitle>
            {memory.status !== "ACTIVE" && (
              <Badge variant={statusVariant(memory.status)} className="text-[10px] px-1.5 py-0 shrink-0">
                {memory.status}
              </Badge>
            )}
            {memory.cost_summary && memory.cost_summary.total_memory_estimated_cost > 0 && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0 font-mono">
                ~${memory.cost_summary.total_memory_estimated_cost < 0.01
                  ? memory.cost_summary.total_memory_estimated_cost.toFixed(6)
                  : memory.cost_summary.total_memory_estimated_cost.toFixed(4)}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {onEdit && (
              <button
                type="button"
                onClick={() => onEdit(memory.id)}
                className="text-muted-foreground/50 hover:text-foreground transition-colors"
                title="Edit"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
            {canDelete && (
              <button
                type="button"
                onClick={() => setConfirmingRemove(true)}
                className="text-muted-foreground/50 hover:text-destructive transition-colors"
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
      <CardContent className="space-y-3 text-xs text-muted-foreground">
        <div className="rounded border bg-input-bg p-3 space-y-0.5">
          <div>Region: {memory.region}</div>
          <div>Account: {memory.account_id}</div>
          <div>Event Expiry: {memory.event_expiry_duration}d</div>
          <div>Strategies: {strategiesCount}</div>
          {memory.created_at && (
            <div>Registered: {formatTimestamp(memory.created_at, timezone)}</div>
          )}
        </div>
        {showOnCardKeys && showOnCardKeys.length > 0 && memory.tags && Object.keys(memory.tags).length > 0 && (
          <div className="flex flex-wrap gap-1 pt-1">
            {showOnCardKeys
              .filter(key => memory.tags[key])
              .map(key => (
                <Badge key={key} variant="outline" className="text-[10px] px-1.5 py-0 font-normal">
                  {key.replace(/^loom:/, "")}: {memory.tags[key]}
                </Badge>
              ))}
          </div>
        )}
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
