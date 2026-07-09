import { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loader2, Trash2, Pencil } from "lucide-react";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant } from "@/lib/status";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import type { AgentResponse } from "@/api/types";

interface AgentCardProps {
  agent: AgentResponse;
  onSelect: (id: number) => void;
  onDelete: (id: number, cleanupAws: boolean) => void;
  onEdit?: (id: number) => void;
  readOnly?: boolean;
  showOnCardKeys?: string[];
  deleteStartTime?: number;
  updateStartTime?: number;
  userGroups?: string[];
  registryEnabled?: boolean;
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

function deploymentTypeLabel(agent: AgentResponse): string | null {
  if (agent.source === "harness") return "MANAGED";
  if (agent.source === "deploy") return "CUSTOM";
  return null;
}

function existsInAgentCore(agent: AgentResponse): boolean {
  return !!agent.runtime_id;
}

export function AgentCard({ agent, onSelect, onDelete, onEdit, readOnly, showOnCardKeys, deleteStartTime, updateStartTime, userGroups = [], registryEnabled = true }: AgentCardProps) {
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

  return (
    <Card
      className="relative cursor-pointer transition-colors hover:bg-accent/50 py-3 gap-1"
      onClick={() => onSelect(agent.id)}
    >
      <CardHeader className="gap-1 pb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0 overflow-hidden">
            <CardTitle className="text-sm font-medium truncate">
              {agent.name ?? agent.runtime_id}
            </CardTitle>
            {!creating && (
              <RegistryStatusBadge status={agent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
            )}
            {agent.status && agent.status !== "READY" && (
              <Badge variant={statusVariant(agent.status)} className="text-[10px] px-1.5 py-0 shrink-0">
                {agent.status}
              </Badge>
            )}
            {!creating && agent.active_session_count > 0 && (
              <span className="inline-flex items-center justify-center h-5 min-w-5 px-1.5 rounded-full bg-primary text-primary-foreground text-[10px] font-medium shrink-0">
                {agent.active_session_count}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {onEdit && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onEdit(agent.id); }}
                className="text-muted-foreground/50 hover:text-foreground transition-colors"
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
                className="text-muted-foreground/50 hover:text-destructive transition-colors"
                title="Remove agent"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
        {creating && (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span className="text-[10px] tabular-nums">({elapsedSeconds}s)</span>
            <span className="text-[10px]">{label ?? "Creating"}</span>
            {agent.status !== "DELETING" && agent.endpoint_status && agent.endpoint_status !== agent.status && (
              <Badge variant={statusVariant(agent.endpoint_status)} className="text-[10px] px-1.5 py-0">
                Endpoint: {agent.endpoint_status}
              </Badge>
            )}
          </div>
        )}
        {agent.status_reason && (agent.status === "CREATE_FAILED" || agent.status === "UPDATE_FAILED" || agent.deployment_status === "failed") && (
          <div className="text-[10px] text-destructive break-words">
            {agent.status_reason}
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-3 text-xs text-muted-foreground">
        <div className="rounded border bg-input-bg p-3 space-y-0.5">
          {agent.region && <div>Region: {agent.region}</div>}
          {agent.account_id && <div>Account: {agent.account_id}</div>}
          {agent.network_mode && (
            <div>Network: {agent.network_mode}</div>
          )}
          {agent.available_qualifiers.length > 0 && (
            <div>Endpoint: {agent.available_qualifiers.join(", ")}</div>
          )}
          <div className="flex flex-wrap items-center gap-1">
            <span>Authorizer:</span>
            {(() => {
              const ac = agent.authorizer_config;
              if (!ac) return <span className="text-muted-foreground/50">None</span>;
              return (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                  {ac.name ?? ac.type ?? "external"}
                </Badge>
              );
            })()}
          </div>
          {agent.memory_names && agent.memory_names.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span>Memory:</span>
              {agent.memory_names.map((name, idx) => (
                <Badge key={idx} variant="outline" className="text-[10px] px-1.5 py-0">
                  {name}
                </Badge>
              ))}
            </div>
          )}
          {agent.mcp_names && agent.mcp_names.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span>MCP:</span>
              {agent.mcp_names.map((name, idx) => (
                <Badge key={idx} variant="outline" className="text-[10px] px-1.5 py-0">
                  {name}
                </Badge>
              ))}
            </div>
          )}
          {agent.a2a_names && agent.a2a_names.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span>A2A:</span>
              {agent.a2a_names.map((name, idx) => (
                <Badge key={idx} variant="outline" className="text-[10px] px-1.5 py-0">
                  {name}
                </Badge>
              ))}
            </div>
          )}
          {agent.registered_at && (
            <div>Registered: {formatTimestamp(agent.registered_at, timezone)}</div>
          )}
        </div>
        {!creating && (deploymentTypeLabel(agent) || (agent.cost_summary && agent.cost_summary.total_cost > 0)) && (
          <div className="flex flex-wrap gap-1">
            {deploymentTypeLabel(agent) && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                {deploymentTypeLabel(agent)}
              </Badge>
            )}
            {agent.cost_summary && agent.cost_summary.total_cost > 0 && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-mono">
                {agent.cost_summary.total_cost < 0.01
                  ? `~$${agent.cost_summary.total_cost.toFixed(6)}`
                  : `~$${agent.cost_summary.total_cost.toFixed(4)}`}
              </Badge>
            )}
          </div>
        )}
        {showOnCardKeys && showOnCardKeys.length > 0 && agent.tags && Object.keys(agent.tags).length > 0 && (
          <div className="flex flex-wrap gap-1 pt-1">
            {showOnCardKeys
              .filter(key => agent.tags[key])
              .map(key => (
                <Badge key={key} variant="outline" className="text-[10px] px-1.5 py-0 font-normal">
                  {key.replace(/^loom:/, "")}: {agent.tags[key]}
                </Badge>
              ))}
          </div>
        )}
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
