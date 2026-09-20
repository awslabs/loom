import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ExpandableRow } from "@/components/ExpandableRow";
import { SearchableSelect } from "@/components/ui/searchable-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SortButton, loadSortDirection, toggleSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import { sortRows } from "@/components/SortableTableHead";
import { useManagedRoles } from "@/hooks/useSecurity";
import { ChevronDown, ChevronRight, Trash2, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import * as settingsApi from "@/api/settings";
import type { TagProfile, PolicyStatement, AgentResponse } from "@/api/types";

function toArray(value: string | string[]): string[] {
  return Array.isArray(value) ? value : [value];
}

/** Best-effort human label for a raw IAM statement, since Loom's generated policies carry no Sid. */
function describeStatement(stmt: PolicyStatement): { label: string; service: string } {
  const actions = toArray(stmt.Action);
  const service = actions[0]?.split(":")[0] ?? "unknown";
  const joined = actions.join(" ").toLowerCase();
  if (service === "bedrock") return { label: "Model invocation", service };
  if (joined.includes("workloadaccesstoken") || joined.includes("createworkloadidentity")) return { label: "Workload identity", service };
  if (joined.includes("memory") || joined.includes("event")) return { label: "Memory access", service };
  if (service === "logs") return { label: "Observability", service };
  if (service === "secretsmanager") return { label: "Secrets access", service };
  if (joined.includes("codeinterpreter")) return { label: "Code interpreter", service };
  if (joined.includes("oauth2token") || joined.includes("apikeycredential")) return { label: "Credential vault access", service };
  return { label: `${service.charAt(0).toUpperCase()}${service.slice(1)} access`, service };
}

const ACTIONS_CLAMP = 3;

function TruncatedList({ items }: { items: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? items : items.slice(0, ACTIONS_CLAMP);
  const hidden = items.length - ACTIONS_CLAMP;
  return (
    <div className="flex flex-col gap-1 min-w-0">
      {visible.map((item) => (
        <span key={item} className="truncate font-mono text-[11.5px]" title={item}>{item}</span>
      ))}
      {!expanded && hidden > 0 && (
        <button type="button" onClick={() => setExpanded(true)} className="text-left font-mono text-[11px] text-primary hover:underline">
          {hidden} more
        </button>
      )}
    </div>
  );
}

function PolicyStatementTable({ statements }: { statements: PolicyStatement[] }) {
  const [viewMode, setViewMode] = useState<"grouped" | "json">("grouped");
  const [showAll, setShowAll] = useState(false);
  const clamp = 4;
  const visible = showAll ? statements : statements.slice(0, clamp);

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">
          {statements.length} statement{statements.length === 1 ? "" : "s"}
        </span>
        <div className="ml-auto flex items-center gap-0.5 rounded-md border bg-muted p-[3px]">
          <button type="button" onClick={() => setViewMode("grouped")} className={`rounded-[4px] px-2 py-0.5 font-mono text-[10.5px] ${viewMode === "grouped" ? "bg-card" : "text-muted-foreground"}`}>grouped</button>
          <button type="button" onClick={() => setViewMode("json")} className={`rounded-[4px] px-2 py-0.5 font-mono text-[10.5px] ${viewMode === "json" ? "bg-card" : "text-muted-foreground"}`}>json</button>
        </div>
      </div>

      {viewMode === "json" ? (
        <pre className="max-h-[420px] overflow-auto rounded-md border bg-muted p-3 font-mono text-[11px] leading-[1.6]">
          {JSON.stringify({ Version: "2012-10-17", Statement: statements }, null, 2)}
        </pre>
      ) : (
        <div className="flex flex-col overflow-hidden rounded-lg border">
          {visible.map((stmt, i) => {
            const { label, service } = describeStatement(stmt);
            const actions = toArray(stmt.Action);
            const resources = toArray(stmt.Resource);
            return (
              <div key={stmt.Sid ?? i} className="grid grid-cols-[150px_minmax(0,1fr)_minmax(0,1fr)] gap-4 border-b px-4 py-3.5 last:border-b-0">
                <div className="flex flex-col gap-1.5">
                  <span className={`w-fit rounded px-1.5 py-0.5 font-mono text-[9.5px] tracking-wide ${stmt.Effect === "Allow" ? "bg-success-bg text-success" : "bg-destructive/10 text-destructive"}`}>
                    {stmt.Effect.toUpperCase()}
                  </span>
                  <span className="text-[12.5px] font-medium">{label}</span>
                  <span className="font-mono text-[10.5px] text-muted-foreground">{service} · {actions.length} action{actions.length === 1 ? "" : "s"}</span>
                </div>
                <div className="flex flex-col gap-1 min-w-0">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Actions</span>
                  <TruncatedList items={actions} />
                </div>
                <div className="flex flex-col gap-1 min-w-0">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Resources</span>
                  <TruncatedList items={resources} />
                </div>
              </div>
            );
          })}
          {statements.length > clamp && (
            <button type="button" onClick={() => setShowAll((v) => !v)} className="bg-muted px-4 py-1.5 text-left font-mono text-[10.5px] text-primary">
              {showAll ? "show less" : `${statements.length - clamp} more`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function RoleManagementPanel({ readOnly, agents = [], onCountChange }: { readOnly?: boolean; agents?: AgentResponse[]; onCountChange?: (count: number) => void }) {
  const { user, browserSessionId } = useAuth();
  const { roles, loading, error, createRole, deleteRole } = useManagedRoles();
  const [showAddForm, setShowAddForm] = useState(false);
  const [importArn, setImportArn] = useState("");
  const [importRoleType, setImportRoleType] = useState<"agent" | "code_interpreter">("agent");
  const [tagProfiles, setTagProfiles] = useState<TagProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<string>("");
  const [expandedRoleId, setExpandedRoleId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<SortDirection>(() => loadSortDirection("security-roles"));
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());

  const toggleSection = (key: string) => {
    setCollapsedSections(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  useEffect(() => {
    void settingsApi.listTagProfiles().then(setTagProfiles).catch(() => {});
  }, []);

  useEffect(() => { onCountChange?.(roles.length); }, [roles.length, onCountChange]);

  const handleCreate = async () => {
    if (!importArn.trim() || !selectedProfileId) return;
    setSubmitting(true);
    try {
      const profile = tagProfiles.find((p) => p.id.toString() === selectedProfileId);
      const tags = profile?.tags ?? {};
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'security', 'add_role', importArn.trim());
      await createRole({ mode: "import", role_arn: importArn.trim(), role_type: importRoleType, tags });
      setImportArn("");
      setImportRoleType("agent");
      setSelectedProfileId("");
      setShowAddForm(false);
      toast.success("Role added");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to add role");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    setSubmitting(true);
    try {
      const roleName = roles.find(r => r.id === id)?.role_name ?? String(id);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'security', 'delete_role', roleName);
      await deleteRole(id);
      setConfirmDeleteId(null);
      toast.success("Role deleted");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete role");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopyArn = (arn: string) => {
    navigator.clipboard.writeText(arn);
    toast.success("Copied role ARN");
  };

  if (loading) {
    return <div className="space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>;
  }

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 rounded-md border bg-muted px-3.5 py-2.5">
        <span className="text-[12.5px] text-muted-foreground">Builders select from these roles when deploying. Role creation is restricted to the security team.</span>
        <span className="ml-auto shrink-0 font-mono text-[11.5px] text-muted-foreground">
          {roles.filter(r => (r.role_type ?? "agent") === "agent").length} agent role{roles.filter(r => (r.role_type ?? "agent") === "agent").length === 1 ? "" : "s"} · {roles.filter(r => r.role_type === "code_interpreter").length} gateway role{roles.filter(r => r.role_type === "code_interpreter").length === 1 ? "" : "s"}
        </span>
        <Button size="sm" onClick={() => setShowAddForm(!showAddForm)} disabled={readOnly}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add role
        </Button>
      </div>

      {showAddForm && (
        <Card>
          <CardContent className="pt-4 space-y-3">
            <div className="flex gap-2">
              <Input
                placeholder="arn:aws:iam::123456789012:role/my-role"
                value={importArn}
                onChange={(e) => setImportArn(e.target.value)}
                className="basis-3/5 min-w-0"
              />
              <div className="basis-1/5 min-w-0 flex">
                <Select value={importRoleType} onValueChange={(v) => setImportRoleType(v as "agent" | "code_interpreter")}>
                  <SelectTrigger className="h-9 text-sm w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="agent">Agent Role</SelectItem>
                    <SelectItem value="code_interpreter">Code Interpreter Role</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <SearchableSelect
                className="basis-1/5 min-w-0"
                options={tagProfiles.map((p) => ({ value: p.id.toString(), label: p.name }))}
                value={selectedProfileId}
                onValueChange={setSelectedProfileId}
                placeholder="Tag profile (required)"
              />
              <Button size="sm" onClick={handleCreate} disabled={submitting || !importArn.trim() || !selectedProfileId}>
                {submitting ? "Importing..." : "Import"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {roles.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8">No managed roles yet. Add one above.</p>
      ) : (
        <div className="space-y-4">
          {(["agent", "code_interpreter"] as const).map((type) => {
            const group = roles.filter((r) => (r.role_type ?? "agent") === type);
            if (group.length === 0) return null;
            const sectionKey = `roles-${type}`;
            const collapsed = collapsedSections.has(sectionKey);
            const label = type === "agent" ? "Agent roles" : "Code interpreter roles";
            const sorted = sortRows(group, "name", sortDir, { name: (r) => r.role_name });
            return (
              <section key={type} className="space-y-2">
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    className="flex items-center gap-1.5 text-sm font-medium hover:text-foreground/80"
                    onClick={() => toggleSection(sectionKey)}
                  >
                    {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    {label}
                    <span className="rounded-md border bg-muted px-1.5 py-0 font-mono text-[10px] text-muted-foreground">{group.length}</span>
                  </button>
                  {!collapsed && (
                    <SortButton direction={sortDir} onClick={() => setSortDir(toggleSortDirection("security-roles", sortDir))} />
                  )}
                </div>
                {!collapsed && (
                  <div className="flex flex-col gap-3">
                    {sorted.map((role) => {
                      const statements = role.policy_document.Statement ?? [];
                      const totalActions = statements.reduce((sum, s) => sum + toArray(s.Action).length, 0);
                      const dependentCount = agents.filter((a) => a.execution_role_arn === role.role_arn).length;
                      return (
                        <ExpandableRow
                          key={role.id}
                          expanded={expandedRoleId === role.id}
                          onToggle={() => setExpandedRoleId(expandedRoleId === role.id ? null : role.id)}
                          title={role.role_name}
                          typeBadge={`${statements.length} STATEMENTS · ${totalActions} ACTIONS`}
                          subtitle={role.role_arn}
                          meta={<span className="text-[11.5px] text-muted-foreground">used by {dependentCount} agent{dependentCount === 1 ? "" : "s"}</span>}
                          actions={
                            <>
                              <Button size="sm" variant="outline" className="h-[29px] font-mono" onClick={() => handleCopyArn(role.role_arn)}>Copy ARN</Button>
                              {!readOnly && (
                                <button type="button" onClick={() => setConfirmDeleteId(role.id)} className="text-muted-foreground/60 hover:text-destructive transition-colors" title="Delete">
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              )}
                            </>
                          }
                        >
                          {role.tags && Object.keys(role.tags).length > 0 && (
                            <div className="mb-3 flex flex-wrap gap-1.5">
                              {Object.entries(role.tags).map(([key, value]) => (
                                <span key={key} className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                                  <span className="text-muted-foreground">{key.replace(/^loom:/, "")}</span> {value}
                                </span>
                              ))}
                            </div>
                          )}
                          {confirmDeleteId === role.id && (
                            <div className="mb-3 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
                              <span>Delete <span className="font-mono">{role.role_name}</span>?</span>
                              <div className="flex items-center gap-2">
                                <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setConfirmDeleteId(null)}>Cancel</Button>
                                <Button size="sm" variant="destructive" className="h-6 text-xs" onClick={() => handleDelete(role.id)} disabled={submitting}>Confirm</Button>
                              </div>
                            </div>
                          )}
                          {statements.length === 0 ? (
                            <p className="text-xs text-muted-foreground italic">No policy statements</p>
                          ) : (
                            <PolicyStatementTable statements={statements} />
                          )}
                        </ExpandableRow>
                      );
                    })}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
