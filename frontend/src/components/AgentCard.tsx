import { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Trash2, Pencil } from "lucide-react";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp, capitalize } from "@/lib/format";
import { statusVariant } from "@/lib/status";
import { StatusPill } from "@/components/StatusPill";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import type { AgentResponse } from "@/api/types";

interface AgentCardProps {
  agent: AgentResponse;
  onSelect: (id: number) => void;
  onDelete: (id: number, cleanupAws: boolean) => void;
  onEdit?: (id: number) => void;
  readOnly?: boolean;
  deleteStartTime?: number;
  updateStartTime?: number;
  userGroups?: string[];
  registryEnabled?: boolean;
  /** Highest cost among sibling cards in the same group, for the share-of-max bar. */
  maxCost?: number;
}

const DEPLOY_IN_PROGRESS = new Set([
  "initializing",
  "creating_credentials",
  "creating_role",
  "building_artifact",
  "creating_ci_resource",
  "deploying",
  "updating",
]);

function isTransitional(agent: AgentResponse): boolean {
  return (
    agent.status === "CREATING" ||
    agent.status === "UPDATING" ||
    agent.status === "DELETING" ||
    DEPLOY_IN_PROGRESS.has(agent.deployment_status ?? "") ||
    agent.endpoint_status === "CREATING"
  );
}

function phaseLabel(agent: AgentResponse): string | null {
  if (agent.status === "DELETING") return "Deleting";
  switch (agent.deployment_status) {
    case "initializing": return "Initializing";
    case "updating": return "Updating";
    case "creating_credentials": return "Creating credential provider";
    case "creating_role": return "Creating IAM role";
    case "building_artifact": return "Building artifact";
    case "creating_ci_resource": return "Building artifact & creating Code Interpreter";
    case "deploying": return agent.source === "harness" ? "Creating harness" : "Deploying runtime";
    default: break;
  }
  if (agent.status === "UPDATING") return "Updating";
  if (agent.status === "CREATING") return agent.source === "harness" ? "Creating harness" : "Completing deployment";
  if (agent.status === "READY" && agent.endpoint_status === "CREATING") return "Finalizing endpoint";
  return null;
}

function frameworkLabel(agent: AgentResponse): string | null {
  if (agent.source !== "deploy" || !agent.agent_framework) return null;
  return capitalize(agent.agent_framework);
}

function existsInAgentCore(agent: AgentResponse): boolean {
  return !!agent.runtime_id;
}

export function AgentCard({ agent, onSelect, onDelete, onEdit, readOnly, deleteStartTime, updateStartTime, userGroups = [], registryEnabled = true, maxCost }: AgentCardProps) {
  const { timezone } = useTimezone();
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [cleanupAws, setCleanupAws] = useState(false);
  const [now, setNow] = useState(Date.now());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const creating = isTransitional(agent);
  const label = phaseLabel(agent);

  // Check if user can delete this resource
  const isSuperAdmin = userGroups.includes("g-admins-super");
  const isDemoAdmin = userGroups.includes("g-admins-demo") && !isSuperAdmin;
  const resourceGroup = agent.tags?.["loom:group"] || "";
  const canDelete = !readOnly && (!isDemoAdmin || resourceGroup === "demo");

  useEffect(() => {
    if (creating) {
      if (!timerRef.current) {
        timerRef.current = setInterval(() => setNow(Date.now()), 1000);
      }
    } else {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    }
    return () => { if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; } };
  }, [creating]);

  const elapsedSeconds = (() => {
    if (!creating) return 0;
    if (agent.status === "DELETING") {
      if (!deleteStartTime) return 0;
      return Math.max(0, Math.floor((now - deleteStartTime) / 1000));
    }
    if (agent.status === "UPDATING") {
      if (!updateStartTime) return 0;
      return Math.max(0, Math.floor((now - updateStartTime) / 1000));
    }
    const ts = agent.registered_at;
    if (!ts) return 0;
    return Math.max(0, Math.floor((now - new Date(ts).getTime()) / 1000));
  })();

  const showCleanupOption = existsInAgentCore(agent);

  const cost = agent.cost_summary?.total_cost ?? 0;
  const costLabel = cost > 0 ? (cost < 0.01 ? `$${cost.toFixed(6)}` : `$${cost.toFixed(4)}`) : null;
  const sharePct = maxCost && maxCost > 0 ? Math.min(100, Math.round((cost / maxCost) * 100)) : null;

  const runtimeLabel = agent.source === "harness" ? "Managed" : agent.source === "deploy" ? "Custom" : (agent.source ?? "—");
  const networkLabel = [agent.network_mode, agent.region].filter(Boolean).join(" · ") || "—";
  const memoryLabel = agent.memory_names && agent.memory_names.length > 0
    ? agent.memory_names.length > 1 ? `${agent.memory_names[0]} +${agent.memory_names.length - 1}` : agent.memory_names[0]
    : "—";
  const fourthLabel = agent.mcp_names && agent.mcp_names.length > 0
    ? { key: "MCP", value: agent.mcp_names.length > 1 ? `${agent.mcp_names[0]} +${agent.mcp_names.length - 1}` : agent.mcp_names[0] }
    : agent.authorizer_config
      ? { key: "Authorizer", value: agent.authorizer_config.name ?? agent.authorizer_config.type ?? "external" }
      : agent.a2a_names && agent.a2a_names.length > 0
        ? { key: "A2A", value: agent.a2a_names.length > 1 ? `${agent.a2a_names[0]} +${agent.a2a_names.length - 1}` : agent.a2a_names[0] }
        : { key: "Authorizer", value: "None" };

  const labelCount = agent.tags ? Object.keys(agent.tags).length : 0;

  return (
    <Card
      className="group relative flex h-full cursor-pointer flex-col gap-3.5 py-4 transition-colors hover:bg-accent/50"
      onClick={() => onSelect(agent.id)}
    >
      <CardHeader className="gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
            <CardTitle className="truncate font-mono text-sm font-medium tracking-tight">
              {agent.name ?? agent.runtime_id}
            </CardTitle>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {!creating && (
              <RegistryStatusBadge status={agent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
            )}
            {!creating && agent.active_session_count > 0 && (
              <span className="inline-flex items-center justify-center h-5 min-w-5 px-1.5 rounded-full bg-primary text-primary-foreground text-[10px] font-medium shrink-0">
                {agent.active_session_count}
              </span>
            )}
            {onEdit && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onEdit(agent.id); }}
                className="text-muted-foreground/50 opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100"
                title="Edit"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
            {canDelete && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmingRemove(true);
                }}
                className="text-muted-foreground/50 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100"
                title="Remove agent"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
        {agent.status && agent.status !== "READY" && (
          <StatusPill label={agent.status} variant={statusVariant(agent.status)} className="w-fit" />
        )}
        {creating && (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span className="text-[10px] tabular-nums">({elapsedSeconds}s)</span>
            <span className="text-[10px]">{label ?? "Creating"}</span>
            {agent.status !== "DELETING" && agent.endpoint_status && agent.endpoint_status !== agent.status && (
              <StatusPill label={`Endpoint: ${agent.endpoint_status}`} variant={statusVariant(agent.endpoint_status)} />
            )}
          </div>
        )}
        {agent.status_reason && (agent.status === "CREATE_FAILED" || agent.status === "UPDATE_FAILED" || agent.deployment_status === "failed") && (
          <div className="text-[10px] text-destructive break-words">
            {agent.status_reason}
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
                  title={`${sharePct}% of the highest est. cost among agents currently shown (${maxCost && maxCost < 0.01 ? maxCost.toFixed(6) : maxCost?.toFixed(4)})`}
                >
                  {sharePct}% of highest shown
                </span>
              )}
            </div>
            {sharePct !== null && (
              <div className="h-[3px] overflow-hidden rounded-full bg-muted" title="Relative to the highest estimated cost among agents currently shown">
                <div className="h-full rounded-full bg-primary" style={{ width: `${sharePct}%` }} />
              </div>
            )}
          </div>
        )}
        <div className="grid grid-cols-2 gap-x-3 gap-y-2.5 text-xs">
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Runtime</span>
            <span className="truncate">{runtimeLabel}{frameworkLabel(agent) ? ` · ${frameworkLabel(agent)}` : ""}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Network</span>
            <span className="truncate" title={agent.account_id ? `Account: ${agent.account_id}` : undefined}>{networkLabel}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Memory</span>
            <span className="truncate font-mono text-[12px]">{memoryLabel}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">{fourthLabel.key}</span>
            <span className="truncate font-mono text-[12px]">{fourthLabel.value}</span>
          </div>
        </div>
        <div className="mt-auto flex items-center gap-2 border-t pt-3 text-[11px] text-muted-foreground">
          {agent.registered_at && <span className="font-mono text-[10.5px]">{formatTimestamp(agent.registered_at, timezone)}</span>}
          {labelCount > 0 && (
            <>
              <span className="h-2.5 w-px bg-border" />
              <span>{labelCount} label{labelCount === 1 ? "" : "s"}</span>
            </>
          )}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onSelect(agent.id); }}
            className="ml-auto text-primary hover:underline"
          >
            Details
          </button>
        </div>
        {confirmingRemove && (
          <div
            className="absolute inset-x-0 bottom-0 rounded-b-lg border-t bg-card px-4 py-2 space-y-1.5"
            onClick={(e) => e.stopPropagation()}
          >
            {showCleanupOption && (
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
                  onDelete(agent.id, cleanupAws);
                  setConfirmingRemove(false);
                  setCleanupAws(false);
                }}
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
