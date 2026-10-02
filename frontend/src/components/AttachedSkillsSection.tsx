import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Puzzle, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useAuth } from "@/contexts/AuthContext";
import { listIntegrations, createIntegration, deleteIntegration } from "@/api/integrations";
import { listRegistryRecords } from "@/api/registry";
import type { AgentIntegration, RegistryRecord } from "@/api/types";

interface AttachedSkillsSectionProps {
  agentId: number;
}

/** Attach approved SKILL registry records to this agent. Attached skills'
 * SKILL.md content is fetched live (never cached) and folded into the
 * system prompt on the agent's next full redeploy (redeploy-deploy or
 * redeploy-harness) — the quick "Redeploy" button, which just resends the
 * existing config unchanged, does not pick up new attachments. See
 * `_get_attached_skill_prompt_text` in backend/app/routers/agents.py. */
export function AttachedSkillsSection({ agentId }: AttachedSkillsSectionProps) {
  const { hasScope } = useAuth();
  const canView = hasScope("registry:read");
  const [attached, setAttached] = useState<AgentIntegration[]>([]);
  const [approvedSkills, setApprovedSkills] = useState<RegistryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState("");
  const [attaching, setAttaching] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [integrations, skills] = await Promise.all([
        listIntegrations(agentId),
        listRegistryRecords({ status: "APPROVED", descriptorType: "SKILL" }),
      ]);
      setAttached(integrations.filter((i) => i.integration_type === "skill" && i.enabled));
      setApprovedSkills(skills);
    } catch {
      // Registry may not be configured — leave the section empty rather than erroring the whole page.
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => { if (canView) void load(); }, [load, canView]);

  // Same gate as SkillsPage.tsx: don't fetch or render any skill name/id
  // without registry:read, even though the parent (AgentDetailPage) already
  // hides this whole section for that case — belt and suspenders.
  if (!canView) return null;

  const attachedRecordIds = new Set(attached.map((i) => i.integration_config?.record_id));
  const availableOptions = approvedSkills
    .filter((s) => !attachedRecordIds.has(s.record_id))
    .map((s) => ({ value: s.record_id, label: s.name }));

  const nameForRecordId = (recordId: string | undefined) =>
    approvedSkills.find((s) => s.record_id === recordId)?.name ?? recordId ?? "unknown";

  const handleAttach = async () => {
    if (!selected) return;
    setAttaching(true);
    try {
      await createIntegration(agentId, {
        integration_type: "skill",
        integration_config: { record_id: selected },
      });
      toast.success("Skill attached — redeploy the agent to apply it");
      setSelected("");
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to attach skill");
    } finally {
      setAttaching(false);
    }
  };

  const handleRemove = async (integration: AgentIntegration) => {
    setRemovingId(integration.id);
    try {
      await deleteIntegration(agentId, integration.id);
      toast.success("Skill detached — redeploy the agent to apply it");
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to detach skill");
    } finally {
      setRemovingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading skills…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2.5">
      {attached.length === 0 && (
        <p className="text-[12px] text-muted-foreground">No skills attached.</p>
      )}
      {attached.map((integration) => (
        <div key={integration.id} className="flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5">
          <div className="flex items-center gap-1.5 min-w-0">
            <Puzzle className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <span className="truncate text-[12.5px]">{nameForRecordId(integration.integration_config?.record_id)}</span>
          </div>
          <Button
            size="sm"
            variant="ghost"
            disabled={removingId === integration.id}
            onClick={() => void handleRemove(integration)}
            className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
            aria-label="Detach skill"
          >
            {removingId === integration.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
          </Button>
        </div>
      ))}

      <div className="flex items-center gap-2 pt-1">
        <SearchableSelect
          options={availableOptions}
          value={selected}
          onValueChange={setSelected}
          placeholder={availableOptions.length === 0 ? "No approved skills available" : "Select a skill to attach…"}
          className="flex-1"
        />
        <Button size="sm" disabled={!selected || attaching} onClick={() => void handleAttach()} className="gap-1.5">
          {attaching ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
          Attach
        </Button>
      </div>
    </div>
  );
}
