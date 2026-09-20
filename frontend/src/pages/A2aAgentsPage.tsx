import { useState, useEffect } from "react";
import { getRegistryConfig } from "@/api/settings";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ViewModeToggle } from "@/components/ViewModeToggle";
import { StatusPill } from "@/components/StatusPill";
import { CopyField } from "@/components/CopyField";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant, statusDotClass, type BadgeVariant } from "@/lib/status";
import { useA2aAgents } from "@/hooks/useA2aAgents";
import { A2aAgentForm } from "@/components/A2aAgentForm";
import { A2aAgentCardView } from "@/components/A2aAgentCardView";
import { A2aSkillList } from "@/components/A2aSkillList";
import { A2aAccessControl } from "@/components/A2aAccessControl";
import { SortableCardGrid, SortButton, loadSortDirection, toggleSortDirection, saveSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import { SortableTableHead, sortRows } from "@/components/SortableTableHead";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import { RegistryActions } from "@/components/RegistryActions";
import type { A2aAgent, A2aAgentCreateRequest, AgentResponse } from "@/api/types";

interface A2aAgentsPageProps {
  viewMode: "cards" | "table";
  onViewModeChange: (mode: "cards" | "table") => void;
  readOnly?: boolean;
  initialSelectedId?: number | null;
  agents?: AgentResponse[];
  onCountChange?: (count: number) => void;
}

function a2aSkillsCount(agent: A2aAgent): number | null {
  const raw = agent.agent_card_raw?.skills;
  return Array.isArray(raw) ? raw.length : null;
}

function a2aHealth(agent: A2aAgent, timezone: Parameters<typeof formatTimestamp>[1]): { label: string; variant: BadgeVariant } {
  if (agent.status === "error") return { label: "fetch failed", variant: "destructive" };
  if (agent.last_fetched_at) return { label: `fetched ${formatTimestamp(agent.last_fetched_at, timezone).split(",")[0]}`, variant: "success" };
  return { label: "not fetched", variant: "neutral" };
}

export function A2aAgentsPage({ viewMode, onViewModeChange, readOnly, initialSelectedId, agents = [], onCountChange }: A2aAgentsPageProps) {
  const { timezone } = useTimezone();
  const { user, browserSessionId } = useAuth();
  const { agents: a2aAgents, loading, fetchAgents, createAgent, updateAgent, deleteAgent, refreshCard } = useA2aAgents();
  const [showAddForm, setShowAddForm] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(initialSelectedId ?? null);
  const [detailTab, setDetailTab] = useState<"skills" | "access">("skills");
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<number | null>(null);
  const [editingAgent, setEditingAgent] = useState<A2aAgent | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [registryEnabled, setRegistryEnabled] = useState(false);

  useEffect(() => {
    getRegistryConfig().then((c) => setRegistryEnabled(c.enabled)).catch(() => {});
  }, []);

  useEffect(() => {
    onCountChange?.(a2aAgents.length);
  }, [a2aAgents.length, onCountChange]);

  const [cardSortDir, setCardSortDir] = useState<SortDirection>(() => loadSortDirection("a2a-agents"));
  const [tableCol, setTableCol] = useState<string | null>("name");
  const [tableDir, setTableDir] = useState<SortDirection>("asc");

  const handleTableSort = (col: string) => {
    if (tableCol === col) {
      setTableDir(tableDir === "asc" ? "desc" : "asc");
    } else {
      setTableCol(col);
      setTableDir("asc");
    }
  };

  const selectedAgent = a2aAgents.find((a) => a.id === selectedAgentId) ?? null;

  const dependentsOf = (agentName: string) => agents.filter((a) => a.a2a_names?.includes(agentName));

  const handleCreate = async (data: A2aAgentCreateRequest) => {
    try {
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'a2a', 'add_agent', data.name);
      await createAgent(data);
      setShowAddForm(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to register agent");
    }
  };

  const handleUpdate = async (data: A2aAgentCreateRequest) => {
    if (!editingAgent) return;
    try {
      await updateAgent(editingAgent.id, data);
      setEditingAgent(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update agent");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const agentName = a2aAgents.find(a => a.id === id)?.name ?? String(id);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'a2a', 'delete_agent', agentName);
      await deleteAgent(id);
      setConfirmingDeleteId(null);
      if (selectedAgentId === id) setSelectedAgentId(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to remove agent");
    }
  };

  const handleRefresh = async () => {
    if (!selectedAgent) return;
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'a2a', 'test_connection', selectedAgent.name);
    setRefreshing(true);
    try {
      await refreshCard(selectedAgent.id);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to refresh Agent Card");
    } finally {
      setRefreshing(false);
    }
  };

  // Detail view
  if (selectedAgent) {
    const dependents = dependentsOf(selectedAgent.name);
    return (
      <Tabs key={selectedAgent.id} value={detailTab} onValueChange={(v) => setDetailTab(v as typeof detailTab)} className="gap-0">
        <div className="flex flex-col gap-4 rounded-t-xl border bg-card px-6 pt-5">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <button type="button" onClick={() => { setSelectedAgentId(null); setEditingAgent(null); }} className="hover:text-foreground">Integrations</button>
            <span>/</span>
            <button type="button" onClick={() => { setSelectedAgentId(null); setEditingAgent(null); }} className="hover:text-foreground">A2A agents</button>
            <span>/</span>
            <span className="font-mono text-foreground">{selectedAgent.name}</span>
          </div>
          <div className="flex items-start gap-4">
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="truncate font-mono text-2xl font-semibold tracking-tight">{selectedAgent.name}</h1>
                <span className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[10px] tracking-wide text-muted-foreground">v{selectedAgent.agent_version}</span>
                <RegistryStatusBadge status={selectedAgent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                <StatusPill label={selectedAgent.status} variant={statusVariant(selectedAgent.status === "active" ? "READY" : selectedAgent.status === "error" ? "FAILED" : "CREATING")} />
              </div>
              <div className="flex items-center gap-1.5 text-[13.5px] text-muted-foreground">
                <span className="max-w-xl truncate">{selectedAgent.description || <span className="italic">No description set.</span>}</span>
                {!readOnly && (
                  <button type="button" onClick={() => setEditingAgent(selectedAgent)} className="shrink-0 text-[11.5px] text-primary hover:underline">
                    Edit
                  </button>
                )}
              </div>
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => void handleRefresh()} disabled={refreshing}>
                {refreshing ? "Refetching…" : "Refetch card"}
              </Button>
              {!readOnly && registryEnabled && (
                <RegistryActions
                  resourceType="a2a"
                  resourceId={selectedAgent.id}
                  registryRecordId={selectedAgent.registry_record_id}
                  registryStatus={selectedAgent.registry_status}
                  onAction={() => void fetchAgents()}
                />
              )}
              {!readOnly && (
                <button
                  type="button"
                  onClick={() => setConfirmingDeleteId(selectedAgent.id)}
                  className="text-muted-foreground/60 transition-colors hover:text-destructive"
                  title="Delete agent"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
          <TabsList variant="line" className="h-auto justify-start gap-5 rounded-none bg-transparent p-0">
            <TabsTrigger value="skills" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">Skills</TabsTrigger>
            <TabsTrigger value="access" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">Access</TabsTrigger>
          </TabsList>
        </div>

        {editingAgent && (
          <Card className="mt-4">
            <CardContent className="pt-4">
              <A2aAgentForm
                onSubmit={handleUpdate}
                onCancel={() => setEditingAgent(null)}
                initialData={{
                  id: editingAgent.id,
                  name: editingAgent.name,
                  base_url: editingAgent.base_url,
                  auth_type: editingAgent.auth_type,
                  oauth2_well_known_url: editingAgent.oauth2_well_known_url ?? undefined,
                  oauth2_client_id: editingAgent.oauth2_client_id ?? undefined,
                  oauth2_scopes: editingAgent.oauth2_scopes ?? undefined,
                  delegation_mode: editingAgent.delegation_mode ?? undefined,
                }}
              />
            </CardContent>
          </Card>
        )}

        {confirmingDeleteId === selectedAgent.id && (
          <div className="mt-4 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm">
            <span>Delete <span className="font-mono">{selectedAgent.name}</span>? This can't be undone.</span>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfirmingDeleteId(null)}>Cancel</Button>
              <Button size="sm" variant="destructive" onClick={() => void handleDelete(selectedAgent.id)}>Delete</Button>
            </div>
          </div>
        )}

        <TabsContent value="skills" className="grid grid-cols-1 gap-4 pt-4 lg:grid-cols-[1fr_320px]">
          <A2aSkillList agentId={selectedAgent.id} />
          <div className="flex flex-col gap-3.5">
            <A2aAgentCardView agent={selectedAgent} />

            <Card className="gap-2.5 py-4">
              <CardHeader className="px-[18px]">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-[13px] font-semibold">Used by</CardTitle>
                  <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-mono">{dependents.length}</Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-1.5 px-[18px]">
                {dependents.length === 0 ? (
                  <p className="rounded-md border border-dashed px-3 py-2.5 text-[11.5px] text-muted-foreground">No agents delegate to this peer yet.</p>
                ) : (
                  <>
                    {dependents.map((a) => (
                      <div key={a.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 font-mono text-[11.5px]">
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDotClass(statusVariant(a.status))}`} />
                        <span className="truncate">{a.name ?? a.runtime_id}</span>
                      </div>
                    ))}
                    <p className="text-[11px] text-muted-foreground">Deleting this agent may break {dependents.length === 1 ? "this agent" : "these agents"}.</p>
                  </>
                )}
              </CardContent>
            </Card>

            <Card className="gap-2.5 py-4">
              <CardContent className="flex flex-col gap-2.5">
                <span className="text-[13px] font-semibold">Raw agent card</span>
                <p className="text-[12px] leading-[1.5] text-muted-foreground">The JSON fetched from the peer's well-known endpoint.</p>
                <details className="group">
                  <summary className="cursor-pointer list-none rounded-md border px-3 py-1.5 text-center font-mono text-[11.5px] text-muted-foreground select-none hover:text-foreground">
                    View JSON
                  </summary>
                  <pre className="mt-2 max-h-[320px] overflow-auto rounded-md border bg-muted p-3 font-mono text-[11px] leading-[1.6]">
                    {JSON.stringify(selectedAgent.agent_card_raw, null, 2)}
                  </pre>
                </details>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
        <TabsContent value="access" className="pt-4">
          <A2aAccessControl agentId={selectedAgent.id} readOnly={readOnly} />
        </TabsContent>
      </Tabs>
    );
  }

  // List view
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">A2A agents</h2>
          <p className="text-sm text-muted-foreground">
            Peer agents this platform can delegate to over Agent-to-Agent protocol.
          </p>
        </div>
        <ViewModeToggle viewMode={viewMode} onViewModeChange={onViewModeChange} />
      </div>

      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">Agents</h3>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <SortButton direction={cardSortDir} onClick={() => setCardSortDir(toggleSortDirection("a2a-agents", cardSortDir))} />
          {!readOnly && (
            <Button
              size="sm"
              onClick={() => setShowAddForm(!showAddForm)}
            >
              <Plus className="h-3.5 w-3.5 mr-1" />
              Add A2A Agent
            </Button>
          )}
        </div>
      </div>

      {showAddForm && (
        <Card>
          <CardContent className="pt-4">
            <A2aAgentForm
              onSubmit={handleCreate}
              onCancel={() => setShowAddForm(false)}
            />
          </CardContent>
        </Card>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : a2aAgents.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8">
          No A2A agents registered yet. Add one above.
        </p>
      ) : viewMode === "cards" ? (
        <SortableCardGrid
          items={a2aAgents}
          getId={(a) => String(a.id)}
          getName={(a) => a.name}
          storageKey="a2a-agents"
          sortDirection={cardSortDir}
          onSortDirectionChange={(d) => { if (d) { setCardSortDir(d); saveSortDirection("a2a-agents", d); } }}
          renderItem={(agent) => {
            const health = a2aHealth(agent, timezone);
            const dependentCount = dependentsOf(agent.name).length;
            const skillsCount = a2aSkillsCount(agent);
            return (
              <Card
                className="group relative flex h-full cursor-pointer flex-col gap-3.5 py-4 transition-colors hover:bg-accent/50"
                onClick={() => setSelectedAgentId(agent.id)}
              >
                <CardHeader className="gap-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="min-w-0 flex-1 truncate font-mono text-sm font-medium tracking-tight" title={agent.name}>
                      {agent.name}
                    </CardTitle>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <RegistryStatusBadge status={agent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setEditingAgent(agent); setSelectedAgentId(agent.id); }}
                          className="text-muted-foreground/50 opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100"
                          title="Edit agent"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setConfirmingDeleteId(agent.id); }}
                          className="text-muted-foreground/50 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100"
                          title="Delete agent"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col gap-3.5">
                  <div onClick={(e) => e.stopPropagation()}>
                    <CopyField value={agent.base_url} />
                  </div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2.5 text-xs">
                    <div className="flex flex-col gap-0.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Auth</span>
                      <span className="truncate">{agent.auth_type === "oauth2" ? "OAuth2" : "None"}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Skills</span>
                      <span className="truncate">{skillsCount ?? "—"}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Version</span>
                      <span className="truncate">v{agent.agent_version}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Streaming</span>
                      <span className="truncate">{agent.capabilities.streaming ? "Yes" : "No"}</span>
                    </div>
                  </div>
                  <div className="mt-auto flex items-center gap-2 border-t pt-3 text-[11px] text-muted-foreground">
                    <span className="flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDotClass(health.variant)}`} />
                      {health.label}
                    </span>
                    <span className="h-2.5 w-px bg-border" />
                    <span>{dependentCount} agent{dependentCount === 1 ? "" : "s"}</span>
                  </div>
                  {confirmingDeleteId === agent.id && (
                    <div
                      className="absolute inset-x-0 bottom-0 rounded-b-lg border-t bg-card px-4 py-2"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 text-xs"
                          onClick={() => setConfirmingDeleteId(null)}
                        >
                          Cancel
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-6 text-xs"
                          onClick={() => void handleDelete(agent.id)}
                        >
                          Confirm
                        </Button>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          }}
        />
      ) : (
        <div className="rounded-md border overflow-hidden">
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="bg-card hover:bg-card">
                <SortableTableHead column="name" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[18%]">Name</SortableTableHead>
                <SortableTableHead column="url" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[38%]">URL</SortableTableHead>
                <SortableTableHead column="version" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[8%]">Version</SortableTableHead>
                <SortableTableHead column="auth" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[8%]">Auth</SortableTableHead>
                <SortableTableHead column="registry" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[12%]">Registry</SortableTableHead>
                <SortableTableHead column="created" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[16%]">Created</SortableTableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortRows(a2aAgents, tableCol, tableDir, {
                name: (a) => a.name,
                url: (a) => a.base_url,
                version: (a) => a.agent_version,
                auth: (a) => a.auth_type,
                registry: (a) => a.registry_status ?? "",
                created: (a) => a.created_at ?? "",
              }).map((agent) => (
                <TableRow
                  key={agent.id}
                  className="bg-input-bg hover:bg-input-bg/80 cursor-pointer"
                  onClick={() => setSelectedAgentId(agent.id)}
                >
                  <TableCell className="font-medium text-sm">{agent.name}</TableCell>
                  <TableCell className="text-xs text-muted-foreground truncate">{agent.base_url}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{agent.agent_version}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{agent.auth_type === "oauth2" ? "OAuth2" : "None"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    <RegistryStatusBadge status={agent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatTimestamp(agent.created_at, timezone)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
