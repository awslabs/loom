import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import { getServerAccess, updateServerAccess, getServerTools } from "@/api/mcp";
import { listAgents } from "@/api/agents";
import type { McpServerAccess, McpTool, AgentResponse } from "@/api/types";

interface McpAccessControlProps {
  serverId: number;
  readOnly?: boolean;
}

interface AccessRule {
  persona_id: number;
  enabled: boolean;
  access_level: "all_tools" | "selected_tools";
  allowed_tool_names: string[];
}

export function McpAccessControl({ serverId, readOnly }: McpAccessControlProps) {
  const { user, browserSessionId } = useAuth();
  const [agents, setAgents] = useState<AgentResponse[]>([]);
  const [tools, setTools] = useState<McpTool[]>([]);
  const [rules, setRules] = useState<AccessRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [agentsData, accessData, toolsData] = await Promise.all([
        listAgents(),
        getServerAccess(serverId),
        getServerTools(serverId),
      ]);
      setAgents(agentsData);
      setTools(toolsData);

      const accessMap = new Map<number, McpServerAccess>();
      for (const a of accessData) {
        accessMap.set(a.persona_id, a);
      }

      const initialRules: AccessRule[] = agentsData.map((agent) => {
        const existing = accessMap.get(agent.id);
        return {
          persona_id: agent.id,
          enabled: !!existing,
          access_level: existing?.access_level ?? "all_tools",
          allowed_tool_names: existing?.allowed_tool_names ?? [],
        };
      });
      setRules(initialRules);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to load access data");
    } finally {
      setLoading(false);
    }
  }, [serverId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const updateRule = (personaId: number, updates: Partial<AccessRule>) => {
    setRules((prev) =>
      prev.map((r) => (r.persona_id === personaId ? { ...r, ...updates } : r)),
    );
  };

  const toggleTool = (personaId: number, toolName: string) => {
    setRules((prev) =>
      prev.map((r) => {
        if (r.persona_id !== personaId) return r;
        const names = r.allowed_tool_names.includes(toolName)
          ? r.allowed_tool_names.filter((n) => n !== toolName)
          : [...r.allowed_tool_names, toolName];
        return { ...r, allowed_tool_names: names };
      }),
    );
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'mcp', 'update_permissions', String(serverId));
      const enabledRules = rules.filter((r) => r.enabled);
      await updateServerAccess(serverId, {
        rules: enabledRules.map((r) => ({
          persona_id: r.persona_id,
          access_level: r.access_level,
          allowed_tool_names: r.access_level === "selected_tools" ? r.allowed_tool_names : undefined,
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
            Grant agents access to this MCP server. Deny by default.
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
                          checked={rule.access_level === "all_tools"}
                          onChange={() => updateRule(rule.persona_id, { access_level: "all_tools" })}
                          disabled={readOnly}
                          className="h-3 w-3"
                        />
                        All Tools
                      </label>
                      <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                        <input
                          type="radio"
                          checked={rule.access_level === "selected_tools"}
                          onChange={() => updateRule(rule.persona_id, { access_level: "selected_tools" })}
                          disabled={readOnly}
                          className="h-3 w-3"
                        />
                        Selected Tools
                      </label>
                    </div>

                    {rule.access_level === "selected_tools" && (
                      <div className="flex flex-wrap gap-2">
                        {tools.length === 0 ? (
                          <span className="text-xs text-muted-foreground italic">No tools available. Refresh tools first.</span>
                        ) : (
                          tools.map((tool) => (
                            <label key={tool.id} className="flex items-center gap-1.5 text-xs cursor-pointer">
                              <input
                                type="checkbox"
                                checked={rule.allowed_tool_names.includes(tool.tool_name)}
                                onChange={() => toggleTool(rule.persona_id, tool.tool_name)}
                                disabled={readOnly}
                                className="h-3 w-3"
                              />
                              {tool.tool_name}
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
