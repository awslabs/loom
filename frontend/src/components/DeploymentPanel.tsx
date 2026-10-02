import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loader2, Check, X } from "lucide-react";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant } from "@/lib/status";
import { StatusPill } from "@/components/StatusPill";
import { CopyField } from "@/components/CopyField";
import { fetchModels } from "@/api/agents";
import type { AgentResponse, ModelOption } from "@/api/types";
import { groupModels } from "@/lib/models";

interface DeploymentPanelProps {
  agent: AgentResponse;
  onRedeploy: (id: number) => Promise<void>;
  onPatchAgent?: (id: number, updates: { model_id?: string; allowed_model_ids?: string[] }) => Promise<AgentResponse>;
}

const DEPLOY_IN_PROGRESS = new Set([
  "initializing",
  "creating_credentials",
  "creating_role",
  "building_artifact",
  "creating_ci_resource",
  "deploying",
  "ENDPOINT_CREATING",
]);

function isCreating(agent: AgentResponse): boolean {
  return (
    agent.status === "CREATING" ||
    DEPLOY_IN_PROGRESS.has(agent.deployment_status ?? "") ||
    agent.endpoint_status === "CREATING"
  );
}

function sourceLabel(agent: AgentResponse): string {
  if (agent.source === "harness") return "Managed (Harness)";
  if (agent.source === "deploy") return "Custom (Runtime)";
  return agent.source ?? "Unknown";
}

/** Provider-labeled model chip rows, shared between the deployed (DeploymentPanel) and registered-only paths. */
export function ModelsCard({
  agent,
  onPatchAgent,
}: {
  agent: AgentResponse;
  onPatchAgent?: (id: number, updates: { model_id?: string; allowed_model_ids?: string[] }) => Promise<AgentResponse>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const [defaultDraft, setDefaultDraft] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [allModels, setAllModels] = useState<ModelOption[]>([]);

  useEffect(() => {
    fetchModels().then(setAllModels).catch(() => {});
  }, []);

  const allowedIds = agent.allowed_model_ids ?? [];
  if (allowedIds.length === 0 && !agent.model_id) return null;

  const handleEdit = () => {
    setDraft([...allowedIds]);
    setDefaultDraft(agent.model_id ?? "");
    setEditing(true);
  };

  const handleSave = async () => {
    if (!onPatchAgent) return;
    setSaving(true);
    try {
      const updates: { model_id?: string; allowed_model_ids: string[] } = { allowed_model_ids: draft };
      if (defaultDraft && defaultDraft !== agent.model_id) updates.model_id = defaultDraft;
      await onPatchAgent(agent.id, updates);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const toggle = (modelId: string) => {
    if (modelId === defaultDraft) return;
    setDraft((prev) => (prev.includes(modelId) ? prev.filter((id) => id !== modelId) : [...prev, modelId]));
  };

  // Deprecated ids (dropped from the catalog by a models.json refresh, see
  // #64) have no entry in allModels — synthesize a placeholder so they
  // still render as a chip instead of silently vanishing.
  const deprecatedIds = new Set(agent.deprecated_model_ids ?? []);
  const knownIds = new Set(allModels.map((m) => m.model_id));
  const assignedIds = [...allowedIds, ...(agent.model_id ? [agent.model_id] : [])];
  const missingIds = [...new Set(assignedIds.filter((id) => !knownIds.has(id)))];
  const deprecatedEntries: ModelOption[] = missingIds.map((id) => ({ model_id: id, display_name: id, group: "Deprecated" }));

  // Edit mode groups the full catalog by vendor (like the Settings models
  // browser); deprecated entries are kept out of that grouping and shown
  // as their own clearly-labeled section instead, so they're easy to spot
  // and uncheck rather than blending into a vendor's model list.
  const editGrouped = groupModels(allModels);

  const shownModels = [...allModels.filter((m) => allowedIds.includes(m.model_id) || m.model_id === agent.model_id), ...deprecatedEntries];
  const grouped = groupModels(shownModels);

  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex-row items-center gap-2 border-b py-3.5 px-[18px] [.border-b]:pb-3.5">
        <CardTitle className="text-[13.5px] font-semibold">Allowed models</CardTitle>
        <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-mono">{allowedIds.length || 1}</Badge>
        {!editing && onPatchAgent && (
          <button type="button" onClick={handleEdit} className="ml-auto text-[11.5px] text-primary hover:underline">
            Edit
          </button>
        )}
      </CardHeader>
      <CardContent className="flex flex-col px-[18px] py-2">
        {editing ? (
          <div className="flex flex-col gap-3 py-2">
            <p className="text-xs text-muted-foreground">Select which models users may choose at invoke time:</p>
            <div className="flex flex-col overflow-hidden rounded-md border">
              {editGrouped.map(([group, models], i) => {
                const enabledCount = models.filter((m) => draft.includes(m.model_id)).length;
                return (
                  <div key={group} className={`flex flex-col gap-1.5 px-3 py-2.5 ${i < editGrouped.length - 1 ? "border-b" : ""}`}>
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] font-semibold">{group}</span>
                      <span className="rounded-md border bg-card px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-muted-foreground">
                        {enabledCount} / {models.length}
                      </span>
                    </div>
                    <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
                      {models.map((m) => {
                        const isDefault = m.model_id === defaultDraft;
                        const isChecked = draft.includes(m.model_id);
                        return (
                          <label key={m.model_id} className="flex items-center gap-2.5 py-1 text-xs" title={m.model_id}>
                            <input type="checkbox" className="h-3.5 w-3.5 shrink-0 accent-primary" checked={isChecked} disabled={isDefault} onChange={() => toggle(m.model_id)} />
                            <span className="min-w-0 flex-1 truncate">{m.display_name}</span>
                            {isChecked && (
                              <button
                                type="button"
                                onClick={(e) => { e.preventDefault(); setDefaultDraft(m.model_id); }}
                                className={`shrink-0 text-[9.5px] tracking-wide uppercase ${isDefault ? "text-primary" : "text-muted-foreground hover:text-foreground"}`}
                              >
                                {isDefault ? "default" : "set default"}
                              </button>
                            )}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
            {deprecatedEntries.length > 0 && (
              <div className="flex flex-col gap-1.5 rounded-md border border-warning/40 bg-warning-bg px-3 py-2.5">
                <span className="text-[10.5px] font-semibold uppercase tracking-wide text-warning">
                  Deprecated — no longer in the model catalog
                </span>
                <div className="flex flex-col">
                  {deprecatedEntries.map((m) => {
                    const isDefault = m.model_id === defaultDraft;
                    const isChecked = draft.includes(m.model_id);
                    return (
                      <label key={m.model_id} className="flex items-center gap-2.5 py-1 text-xs" title="Still works, but consider updating this agent to a current model">
                        <input type="checkbox" className="h-3.5 w-3.5 shrink-0 accent-warning" checked={isChecked} disabled={isDefault} onChange={() => toggle(m.model_id)} />
                        <span className="min-w-0 flex-1 truncate font-mono text-warning">{m.model_id}</span>
                        {isDefault ? (
                          <span className="shrink-0 text-[9.5px] tracking-wide uppercase text-warning">set a new default to uncheck</span>
                        ) : isChecked ? (
                          <span className="shrink-0 text-[9.5px] tracking-wide uppercase text-warning">uncheck to update</span>
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="flex gap-2 pt-1">
              <Button size="sm" className="h-6 text-xs" onClick={() => void handleSave()} disabled={saving}>
                <Check className="h-3 w-3 mr-1" />Save
              </Button>
              <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setEditing(false)} disabled={saving}>
                <X className="h-3 w-3 mr-1" />Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col">
            {grouped.map(([group, models], i) => (
              <div key={group} className={`grid grid-cols-[96px_1fr] items-center gap-3.5 py-3.5 ${i < grouped.length - 1 ? "border-b" : ""}`}>
                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">{group}</span>
                <div className="flex flex-wrap gap-1.5">
                  {models.map((m) => {
                    const isDefault = m.model_id === agent.model_id;
                    const isDeprecated = deprecatedIds.has(m.model_id);
                    return (
                      <span
                        key={m.model_id}
                        title={isDeprecated ? "No longer in the model catalog — still works, but consider updating this agent's model" : undefined}
                        className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-[11.5px] ${
                          isDeprecated
                            ? "border border-warning/40 bg-warning-bg text-warning"
                            : isDefault ? "border border-primary/30 bg-primary/[0.07] text-primary" : "border bg-muted text-foreground"
                        }`}
                      >
                        {isDefault && !isDeprecated && <span className="h-1 w-1 rounded-full bg-primary" />}
                        {m.display_name}
                        {isDefault && <span className="text-[9.5px] tracking-wide">DEFAULT</span>}
                        {isDeprecated && <span className="text-[9.5px] tracking-wide uppercase">deprecated</span>}
                      </span>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function DeploymentPanel({ agent }: DeploymentPanelProps) {
  const { timezone } = useTimezone();

  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex-row items-center gap-2.5 border-b py-3.5 px-[18px] [.border-b]:pb-3.5">
        <CardTitle className="text-[13.5px] font-semibold">Deployment</CardTitle>
        <StatusPill label={agent.status ?? "UNKNOWN"} variant={statusVariant(agent.status)} />
        {isCreating(agent) && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        {agent.deployed_at && (
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">deployed {formatTimestamp(agent.deployed_at, timezone)}</span>
        )}
      </CardHeader>
      <CardContent className="grid grid-cols-3 gap-x-5 gap-y-4 px-[18px] py-4">
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Type</span>
          <span className="text-[13px]">{sourceLabel(agent)}</span>
        </div>
        {agent.source !== "harness" && (
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Protocol</span>
            <span className="text-[13px]">{agent.protocol ?? "—"}</span>
          </div>
        )}
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Network</span>
          <span className="text-[13px]">{agent.network_mode ?? "—"}</span>
        </div>
        {agent.code_interpreter_id && (
          <div className="col-span-3 flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Code interpreter</span>
            <div className="flex items-center gap-2">
              <StatusPill label={agent.code_interpreter_status ?? "PROVISIONED"} variant={statusVariant(agent.code_interpreter_status ?? null)} />
              <span className="truncate font-mono text-[12px] text-muted-foreground">{agent.code_interpreter_id}</span>
            </div>
          </div>
        )}
        {agent.execution_role_arn && (
          <div className="col-span-3">
            <CopyField label="Execution role" value={agent.execution_role_arn} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
