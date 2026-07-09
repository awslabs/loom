import { useState, useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loader2, Pencil, Check, X } from "lucide-react";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant } from "@/lib/status";
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

export function DeploymentPanel({ agent, onPatchAgent }: DeploymentPanelProps) {
  const { timezone } = useTimezone();
  const [editingModels, setEditingModels] = useState(false);
  const [modelsDraft, setModelsDraft] = useState<string[]>([]);
  const [defaultModelDraft, setDefaultModelDraft] = useState<string>("");
  const [savingModels, setSavingModels] = useState(false);
  const [allModels, setAllModels] = useState<ModelOption[]>([]);

  useEffect(() => {
    fetchModels().then(setAllModels).catch(() => {});
  }, []);

  const handleEditModels = () => {
    setModelsDraft([...agent.allowed_model_ids]);
    setDefaultModelDraft(agent.model_id ?? "");
    setEditingModels(true);
  };

  const handleSaveModels = async () => {
    if (!onPatchAgent) return;
    setSavingModels(true);
    try {
      const updates: { model_id?: string; allowed_model_ids: string[] } = {
        allowed_model_ids: modelsDraft,
      };
      if (defaultModelDraft && defaultModelDraft !== agent.model_id) {
        updates.model_id = defaultModelDraft;
      }
      await onPatchAgent(agent.id, updates);
      setEditingModels(false);
    } finally {
      setSavingModels(false);
    }
  };

  const toggleModel = (modelId: string) => {
    if (modelId === defaultModelDraft) return;
    setModelsDraft((prev) =>
      prev.includes(modelId) ? prev.filter((id) => id !== modelId) : [...prev, modelId]
    );
  };

  const getDisplayName = (modelId: string) =>
    allModels.find((m) => m.model_id === modelId)?.display_name ?? modelId;

  return (
    <div className="space-y-3">
      {/* Allowed Models */}
      <div className="text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <span className="font-medium">Allowed Models:</span>
          {!editingModels && onPatchAgent && (
            <Button variant="ghost" size="icon" className="h-5 w-5" onClick={handleEditModels}>
              <Pencil className="h-3 w-3" />
            </Button>
          )}
        </div>
        {editingModels ? (
          <div className="space-y-2 mt-1">
            <div className="space-y-1.5">
              {groupModels(allModels).map(([group, models]) => (
                <div key={group} className="flex flex-wrap gap-x-4 gap-y-1 items-center">
                  <span className="text-[10px] font-medium text-muted-foreground w-16 shrink-0">{group}</span>
                  {models.map((m) => {
                    const isDefault = m.model_id === defaultModelDraft;
                    const isChecked = modelsDraft.includes(m.model_id);
                    return (
                      <label key={m.model_id} className="flex items-center gap-1.5 text-xs cursor-pointer">
                        <input
                          type="checkbox"
                          className="h-3.5 w-3.5 shrink-0"
                          checked={isChecked}
                          disabled={isDefault}
                          onChange={() => toggleModel(m.model_id)}
                        />
                        <span>{m.display_name}</span>
                        {isChecked && (
                          <button
                            type="button"
                            onClick={() => setDefaultModelDraft(m.model_id)}
                            className={`text-[10px] px-1 rounded ${
                              isDefault
                                ? "bg-primary text-primary-foreground"
                                : "bg-accent text-muted-foreground hover:bg-accent/80"
                            }`}
                          >
                            {isDefault ? "default" : "set default"}
                          </button>
                        )}
                      </label>
                    );
                  })}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Button size="sm" className="h-6 text-xs" onClick={() => void handleSaveModels()} disabled={savingModels}>
                <Check className="h-3 w-3 mr-1" />
                Save
              </Button>
              <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setEditingModels(false)} disabled={savingModels}>
                <X className="h-3 w-3 mr-1" />
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-0.5">
            {agent.allowed_model_ids.length > 0 ? (
              <div className="space-y-1">
                {groupModels(allModels.filter((m) => agent.allowed_model_ids.includes(m.model_id))).map(([group, models]) => (
                  <div key={group} className="flex flex-wrap gap-1 items-center">
                    <span className="text-[10px] font-medium text-muted-foreground w-16 shrink-0">{group}</span>
                    {models.map((m) => (
                      <Badge key={m.model_id} variant="outline" className="text-[10px] px-1.5 py-0">
                        {m.display_name}{m.model_id === agent.model_id ? " (default)" : ""}
                      </Badge>
                    ))}
                  </div>
                ))}
              </div>
            ) : agent.model_id ? (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                {getDisplayName(agent.model_id)} (default)
              </Badge>
            ) : (
              <span className="italic">None configured</span>
            )}
          </div>
        )}
      </div>

      {/* Deployed configuration details */}
      <div className="rounded-md border bg-background p-3 space-y-1.5 text-xs text-muted-foreground">
        <div className="flex items-center justify-between">
          <span className="font-medium text-foreground">Deployed Configuration</span>
          {isCreating(agent) && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          )}
        </div>
        <div>Deployment Type: {sourceLabel(agent)}</div>
        <div className="flex items-center gap-1.5">
          <span>Runtime Status:</span>
          <Badge variant={statusVariant(agent.status)} className="text-[10px] px-1.5 py-0">
            {agent.status ?? "—"}
          </Badge>
        </div>
        {agent.source !== "harness" && <div>Protocol: {agent.protocol ?? "—"}</div>}
        <div>Network: {agent.network_mode ?? "—"}</div>
        {agent.code_interpreter_id && (
          <div className="flex items-center gap-1.5">
            <span>Code Interpreter:</span>
            <Badge variant={statusVariant(agent.code_interpreter_status ?? null)} className="text-[10px] px-1.5 py-0">
              {agent.code_interpreter_status ?? "UNKNOWN"}
            </Badge>
            <span className="text-[10px] text-muted-foreground/60 font-mono truncate">{agent.code_interpreter_id}</span>
          </div>
        )}
        <div className="truncate">Execution Role: {agent.execution_role_arn ?? "—"}</div>
        {agent.deployed_at && (
          <div>Deployed: {formatTimestamp(agent.deployed_at, timezone)}</div>
        )}
      </div>
    </div>
  );
}
