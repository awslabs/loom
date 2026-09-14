import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ResourceTagFields } from "@/components/ResourceTagFields";
import {
  createLocalAgent,
  fetchAllModelOptions,
  fetchLocalAgentTemplates,
  type LocalAgentTemplate,
} from "@/api/agents";
import { listMcpServers } from "@/api/mcp";
import { listA2aAgents } from "@/api/a2a";
import type { A2aAgent, McpServer, ModelOption } from "@/api/types";
import { toast } from "sonner";

interface LocalAgentCreateFormProps {
  onCreated: () => Promise<unknown> | unknown;
  isLoading?: boolean;
  groupRestriction?: string;
  ownerRestriction?: string;
}

function toggleId(prev: number[], id: number, checked: boolean): number[] {
  if (checked) return prev.includes(id) ? prev : [...prev, id];
  return prev.filter((x) => x !== id);
}

function toggleModel(prev: string[], id: string, checked: boolean): string[] {
  if (checked) return prev.includes(id) ? prev : [...prev, id];
  return prev.filter((x) => x !== id);
}

export function LocalAgentCreateForm({
  onCreated,
  isLoading,
  groupRestriction,
  ownerRestriction,
}: LocalAgentCreateFormProps) {
  const [templates, setTemplates] = useState<LocalAgentTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [tagValues, setTagValues] = useState<Record<string, string>>({});
  const [modelId, setModelId] = useState("");
  const [allowedModelIds, setAllowedModelIds] = useState<string[]>([]);
  const [mcpServerIds, setMcpServerIds] = useState<number[]>([]);
  const [a2aAgentIds, setA2aAgentIds] = useState<number[]>([]);
  const [timeoutS, setTimeoutS] = useState("300");
  const [maxToolRounds, setMaxToolRounds] = useState("20");
  const [catalog, setCatalog] = useState<ModelOption[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [a2aAgents, setA2aAgents] = useState<A2aAgent[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void fetchLocalAgentTemplates()
      .then((res) => {
        setTemplates(res.templates || []);
        if (res.templates?.[0]?.id) {
          setTemplateId(res.templates[0].id);
        }
      })
      .catch((err: Error) => {
        toast.error(err.message || "Failed to load local templates");
      });
    void fetchAllModelOptions()
      .then(setCatalog)
      .catch(() => setCatalog([]));
    void listMcpServers()
      .then(setMcpServers)
      .catch(() => setMcpServers([]));
    void listA2aAgents()
      .then(setA2aAgents)
      .catch(() => setA2aAgents([]));
  }, []);

  const selected = useMemo(
    () => templates.find((t) => t.id === templateId),
    [templates, templateId],
  );

  useEffect(() => {
    if (!selected) return;
    const next: Record<string, string> = {};
    for (const key of Object.keys(selected.params_schema || {})) {
      next[key] = params[key] ?? "";
    }
    setParams(next);
    setModelId(selected.model_id || "");
    setAllowedModelIds([...(selected.allowed_model_ids || [])]);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when template changes
  }, [selected?.id]);

  const modelOptions = useMemo(() => {
    const byId = new Map<string, ModelOption>();
    for (const m of catalog) {
      byId.set(m.model_id, m);
    }
    const ensure = (id: string | undefined) => {
      if (!id || byId.has(id)) return;
      byId.set(id, { model_id: id, display_name: id });
    };
    ensure(selected?.model_id);
    for (const id of selected?.allowed_model_ids || []) {
      ensure(id);
    }
    ensure(modelId);
    for (const id of allowedModelIds) {
      ensure(id);
    }
    return [...byId.values()].sort((a, b) =>
      (a.display_name || a.model_id).localeCompare(b.display_name || b.model_id),
    );
  }, [catalog, selected, modelId, allowedModelIds]);

  const activeMcp = useMemo(
    () => mcpServers.filter((s) => s.status !== "inactive"),
    [mcpServers],
  );
  const activeA2a = useMemo(
    () => a2aAgents.filter((a) => a.status !== "inactive"),
    [a2aAgents],
  );

  const handleSubmit = async () => {
    if (!templateId || !name.trim()) {
      toast.error("Name and template are required");
      return;
    }
    if (!modelId.trim()) {
      toast.error("Model is required");
      return;
    }
    const tags = Object.fromEntries(
      Object.entries(tagValues).filter(([, v]) => typeof v === "string" && v.trim() !== ""),
    );
    const allowed = [...allowedModelIds];
    if (!allowed.includes(modelId)) {
      allowed.unshift(modelId);
    }
    const timeoutVal = Number(timeoutS);
    const roundsVal = Number(maxToolRounds);
    if (!Number.isFinite(timeoutVal) || timeoutVal < 5 || timeoutVal > 3600) {
      toast.error("Timeout must be between 5 and 3600 seconds");
      return;
    }
    if (!Number.isFinite(roundsVal) || roundsVal < 1 || roundsVal > 100) {
      toast.error("Max tool rounds must be between 1 and 100");
      return;
    }
    setSubmitting(true);
    try {
      await createLocalAgent({
        template_id: templateId,
        name: name.trim(),
        description: description.trim(),
        params,
        model_id: modelId.trim(),
        allowed_model_ids: allowed,
        tags: Object.keys(tags).length > 0 ? tags : undefined,
        mcp_server_ids: mcpServerIds,
        a2a_agent_ids: a2aAgentIds,
        timeout_s: timeoutVal,
        max_tool_rounds: roundsVal,
      });
      toast.success("Local agent created");
      setName("");
      setDescription("");
      setMcpServerIds([]);
      setA2aAgentIds([]);
      await onCreated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">
        Create a <span className="font-medium">source=local</span> agent from an allowlisted
        template. Workers stay generic; the objective is stored on the agent config.
      </p>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Template</label>
        <select
          className="w-full h-8 rounded-md border bg-background px-2 text-sm"
          value={templateId}
          onChange={(e) => setTemplateId(e.target.value)}
          disabled={!templates.length}
        >
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.display_name} ({t.id})
            </option>
          ))}
        </select>
        {selected?.description ? (
          <p className="text-[11px] text-muted-foreground whitespace-pre-wrap">{selected.description}</p>
        ) : null}
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Name</label>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="ex. FAQ interno" />
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Description</label>
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Optional"
        />
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Default model</label>
        <select
          className="w-full h-8 rounded-md border bg-background px-2 text-sm"
          value={modelId}
          onChange={(e) => {
            const next = e.target.value;
            setModelId(next);
            setAllowedModelIds((prev) => (prev.includes(next) ? prev : [...prev, next]));
          }}
          disabled={!modelOptions.length}
        >
          {modelOptions.map((m) => (
            <option key={m.model_id} value={m.model_id}>
              {m.display_name || m.model_id}
              {m.model_id !== m.display_name ? ` (${m.model_id})` : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Allowed models</label>
        <div className="max-h-36 overflow-y-auto space-y-1 rounded-md border p-2">
          {modelOptions.length === 0 ? (
            <p className="text-[11px] text-muted-foreground italic">No models in catalog.</p>
          ) : (
            modelOptions.map((m) => (
              <label key={m.model_id} className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5"
                  checked={allowedModelIds.includes(m.model_id)}
                  onChange={(e) =>
                    setAllowedModelIds((prev) => toggleModel(prev, m.model_id, e.target.checked))
                  }
                />
                <span>{m.display_name || m.model_id}</span>
              </label>
            ))
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Timeout (s)</label>
          <Input value={timeoutS} onChange={(e) => setTimeoutS(e.target.value)} inputMode="numeric" />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Max tool rounds</label>
          <Input
            value={maxToolRounds}
            onChange={(e) => setMaxToolRounds(e.target.value)}
            inputMode="numeric"
          />
        </div>
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">MCP servers</label>
        <div className="max-h-36 overflow-y-auto space-y-1 rounded-md border p-2">
          {activeMcp.length === 0 ? (
            <p className="text-[11px] text-muted-foreground italic">No active MCP servers.</p>
          ) : (
            activeMcp.map((server) => (
              <label key={server.id} className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5"
                  checked={mcpServerIds.includes(server.id)}
                  onChange={(e) =>
                    setMcpServerIds((prev) => toggleId(prev, server.id, e.target.checked))
                  }
                />
                <span>{server.name}</span>
              </label>
            ))
          )}
        </div>
        <p className="text-[11px] text-muted-foreground">
          Linked MCPs are used by Chat and Hub (Hub ∩ profile grants).
        </p>
      </div>
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">A2A agents</label>
        <div className="max-h-36 overflow-y-auto space-y-1 rounded-md border p-2">
          {activeA2a.length === 0 ? (
            <p className="text-[11px] text-muted-foreground italic">No active A2A agents.</p>
          ) : (
            activeA2a.map((a2a) => (
              <label key={a2a.id} className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5"
                  checked={a2aAgentIds.includes(a2a.id)}
                  onChange={(e) =>
                    setA2aAgentIds((prev) => toggleId(prev, a2a.id, e.target.checked))
                  }
                />
                <span>{a2a.name}</span>
              </label>
            ))
          )}
        </div>
      </div>
      {selected &&
        Object.entries(selected.params_schema || {}).map(([key, schema]) => (
          <div key={key} className="space-y-1">
            <label className="text-xs text-muted-foreground">
              {key}
              {schema.description ? ` — ${schema.description}` : ""}
            </label>
            <Textarea
              rows={3}
              value={params[key] ?? ""}
              onChange={(e) => setParams((prev) => ({ ...prev, [key]: e.target.value }))}
              placeholder={key}
            />
          </div>
        ))}
      <ResourceTagFields
        onChange={setTagValues}
        groupRestriction={groupRestriction}
        ownerRestriction={ownerRestriction}
      />
      <Button
        size="sm"
        onClick={() => void handleSubmit()}
        disabled={submitting || isLoading || !templates.length || !modelId}
      >
        Create local agent
      </Button>
    </div>
  );
}
