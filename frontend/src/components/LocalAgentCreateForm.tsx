import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  createLocalAgent,
  fetchLocalAgentTemplates,
  type LocalAgentTemplate,
} from "@/api/agents";
import { toast } from "sonner";

interface LocalAgentCreateFormProps {
  onCreated: () => Promise<unknown> | unknown;
  isLoading?: boolean;
}

export function LocalAgentCreateForm({ onCreated, isLoading }: LocalAgentCreateFormProps) {
  const [templates, setTemplates] = useState<LocalAgentTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when template changes
  }, [selected?.id]);

  const handleSubmit = async () => {
    if (!templateId || !name.trim()) {
      toast.error("Name and template are required");
      return;
    }
    setSubmitting(true);
    try {
      await createLocalAgent({
        template_id: templateId,
        name: name.trim(),
        description: description.trim(),
        params,
      });
      toast.success("Local agent created");
      setName("");
      setDescription("");
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
      <Button
        size="sm"
        onClick={() => void handleSubmit()}
        disabled={submitting || isLoading || !templates.length}
      >
        Create local agent
      </Button>
    </div>
  );
}
