import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import { getAgentAccess, updateAgentAccess, getAgentSkills } from "@/api/a2a";
import { listAgents } from "@/api/agents";
import type { A2aAgentAccess, A2aAgentSkill, AgentResponse } from "@/api/types";

interface A2aAccessControlProps {
  agentId: number;
  readOnly?: boolean;
}

interface AccessRule {
  persona_id: number;
  enabled: boolean;
  access_level: "all_skills" | "selected_skills";
  allowed_skill_ids: string[];
}

export function A2aAccessControl({ agentId, readOnly }: A2aAccessControlProps) {
  const { user, browserSessionId } = useAuth();
  const [agents, setAgents] = useState<AgentResponse[]>([]);
  const [skills, setSkills] = useState<A2aAgentSkill[]>([]);
  const [rules, setRules] = useState<AccessRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [agentsData, accessData, skillsData] = await Promise.all([
        listAgents(),
        getAgentAccess(agentId),
        getAgentSkills(agentId),
      ]);
      setAgents(agentsData);
      setSkills(skillsData);

      const accessMap = new Map<number, A2aAgentAccess>();
      for (const a of accessData) {
        accessMap.set(a.persona_id, a);
      }

      const initialRules: AccessRule[] = agentsData.map((agent) => {
        const existing = accessMap.get(agent.id);
        return {
          persona_id: agent.id,
          enabled: !!existing,
          access_level: existing?.access_level ?? "all_skills",
          allowed_skill_ids: existing?.allowed_skill_ids ?? [],
        };
      });
      setRules(initialRules);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to load access data");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const updateRule = (personaId: number, updates: Partial<AccessRule>) => {
    setRules((prev) =>
      prev.map((r) => (r.persona_id === personaId ? { ...r, ...updates } : r)),
    );
  };

  const toggleSkill = (personaId: number, skillId: string) => {
    setRules((prev) =>
      prev.map((r) => {
        if (r.persona_id !== personaId) return r;
        const ids = r.allowed_skill_ids.includes(skillId)
          ? r.allowed_skill_ids.filter((id) => id !== skillId)
          : [...r.allowed_skill_ids, skillId];
        return { ...r, allowed_skill_ids: ids };
      }),
    );
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'a2a', 'update_permissions', String(agentId));
      const enabledRules = rules.filter((r) => r.enabled);
      await updateAgentAccess(agentId, {
        rules: enabledRules.map((r) => ({
          persona_id: r.persona_id,
          access_level: r.access_level,
          allowed_skill_ids: r.access_level === "selected_skills" ? r.allowed_skill_ids : undefined,
        })),
      });
      toast.success("Access rules saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save access rules");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-medium">Persona Access</h4>
          <p className="text-xs text-muted-foreground mt-0.5">
            Grant agents access to this A2A agent. Deny by default.
          </p>
        </div>
        {!readOnly && (
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? (
              <>
                <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                Saving...
              </>
            ) : (
              "Save"
            )}
          </Button>
        )}
      </div>

      {agents.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4">No agents registered.</p>
      ) : (
        <div className="space-y-2">
          {rules.map((rule) => {
            const agent = agents.find((a) => a.id === rule.persona_id);
            if (!agent) return null;
            return (
              <div key={rule.persona_id} className="rounded border bg-input-bg p-3 space-y-2">
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 cursor-pointer select-none flex-1 min-w-0">
                    <input
                      type="checkbox"
                      checked={rule.enabled}
                      onChange={(e) => updateRule(rule.persona_id, { enabled: e.target.checked })}
                      disabled={readOnly}
                      className="h-3.5 w-3.5"
                    />
                    <span className="text-sm font-medium truncate">
                      {agent.name ?? agent.runtime_id}
                    </span>
                  </label>
                </div>

                {rule.enabled && (
                  <div className="pl-6 space-y-2">
                    <div className="flex items-center gap-4">
                      <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                        <input
                          type="radio"
                          checked={rule.access_level === "all_skills"}
                          onChange={() => updateRule(rule.persona_id, { access_level: "all_skills" })}
                          disabled={readOnly}
                          className="h-3 w-3"
                        />
                        All Skills
                      </label>
                      <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                        <input
                          type="radio"
                          checked={rule.access_level === "selected_skills"}
                          onChange={() => updateRule(rule.persona_id, { access_level: "selected_skills" })}
                          disabled={readOnly}
                          className="h-3 w-3"
                        />
                        Selected Skills
                      </label>
                    </div>

                    {rule.access_level === "selected_skills" && (
                      <div className="space-y-1">
                        {skills.length === 0 ? (
                          <span className="text-xs text-muted-foreground italic">No skills available. Refresh the Agent Card first.</span>
                        ) : (
                          skills.map((skill) => (
                            <label key={skill.id} className="flex items-start gap-1.5 text-xs cursor-pointer">
                              <input
                                type="checkbox"
                                checked={rule.allowed_skill_ids.includes(skill.skill_id)}
                                onChange={() => toggleSkill(rule.persona_id, skill.skill_id)}
                                disabled={readOnly}
                                className="h-3 w-3 mt-0.5"
                              />
                              <div className="min-w-0">
                                <span className="font-medium">{skill.name}</span>
                                <span className="text-muted-foreground/70 ml-1">{skill.description}</span>
                              </div>
                            </label>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
