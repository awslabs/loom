import { useState, useEffect } from "react";
import { Plus, LayoutGrid, TableIcon, X, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MultiSelect } from "@/components/ui/multi-select";
import { AddFilterDropdown } from "@/components/ui/add-filter-dropdown";
import { AgentRegistrationForm } from "@/components/AgentRegistrationForm";
import { AgentCard } from "@/components/AgentCard";
import { SortableCardGrid, SortButton, loadSortDirection, toggleSortDirection, saveSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import { SortableTableHead, sortRows } from "@/components/SortableTableHead";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant } from "@/lib/status";
import { listTagPolicies, getRegistryConfig } from "@/api/settings";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import type { AgentDeployRequest, AgentHarnessDeployRequest, AgentResponse, TagPolicy } from "@/api/types";

type BuilderTab = "register" | "deploy";

interface AgentListPageProps {
  agents: AgentResponse[];
  loading: boolean;
  viewMode: "cards" | "table";
  onViewModeChange: (mode: "cards" | "table") => void;
  onRegister: (arn: string, modelId?: string) => Promise<unknown>;
  onDeploy?: (request: AgentDeployRequest, existingAgentId?: number) => Promise<unknown>;
  onDeployHarness?: (request: AgentHarnessDeployRequest, existingAgentId?: number) => Promise<unknown>;
  onSelectAgent: (id: number) => void;
  onRefreshAgent: (id: number) => void;
  onDelete: (id: number, cleanupAws: boolean) => void;
  readOnly?: boolean;
  groupRestriction?: string;
  ownerRestriction?: string;
  deleteStartTimes?: Record<number, number>;
  updateStartTimes?: Record<number, number>;
  userGroups?: string[];
}

export function AgentListPage({
  agents,
  loading,
  viewMode,
  onViewModeChange,
  onRegister,
  onDeploy,
  onDeployHarness,
  onSelectAgent,
  onRefreshAgent: _onRefreshAgent,
  onDelete,
  readOnly,
  groupRestriction,
  ownerRestriction,
  deleteStartTimes,
  updateStartTimes,
  userGroups = [],
}: AgentListPageProps) {
  const { timezone } = useTimezone();
  const { user, browserSessionId, hasScope } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<BuilderTab>("deploy");
  const [showAddForm, setShowAddForm] = useState(false);
  const [exportAgentId, setExportAgentId] = useState<number | undefined>(undefined);
  const [tagPolicies, setTagPolicies] = useState<TagPolicy[]>([]);
  const [tagFilters, setTagFilters] = useState<Record<string, string[]>>(() => {
    try { return JSON.parse(localStorage.getItem("loom:tagFilters:agents") || "{}") as Record<string, string[]>; } catch { return {}; }
  });

  const [registryEnabled, setRegistryEnabled] = useState(false);

  useEffect(() => {
    void listTagPolicies().then(setTagPolicies).catch(() => {});
    getRegistryConfig().then((c) => setRegistryEnabled(c.enabled)).catch(() => {});
  }, []);


  const showOnCardPolicies = tagPolicies.filter(tp => tp.show_on_card);
  const showOnCardKeys = showOnCardPolicies.map(tp => tp.key);

  // R3: Progressive disclosure filtering
  const requiredPolicies = showOnCardPolicies.filter(tp => tp.required);
  const customPolicies = showOnCardPolicies.filter(tp => !tp.required);
  const [activeCustomFilterKeys, setActiveCustomFilterKeys] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("loom:customFilterKeys:agents") || "[]") as string[]; } catch { return []; }
  });

  // Persist filter state to localStorage
  useEffect(() => { localStorage.setItem("loom:tagFilters:agents", JSON.stringify(tagFilters)); }, [tagFilters]);
  useEffect(() => { localStorage.setItem("loom:customFilterKeys:agents", JSON.stringify(activeCustomFilterKeys)); }, [activeCustomFilterKeys]);

  // R4: Custom tag show/hide toggle
  const [showCustomTags, setShowCustomTags] = useState(() => localStorage.getItem("loom:showCustomTags") !== "false");
  const requiredKeySet = new Set(requiredPolicies.map(tp => tp.key));
  const effectiveShowOnCardKeys = showCustomTags ? showOnCardKeys : showOnCardKeys.filter(k => requiredKeySet.has(k));

  const [agentSortDir, setAgentSortDir] = useState<SortDirection>(() => loadSortDirection("builder-agents"));
  const [agentTableCol, setAgentTableCol] = useState<string | null>("name");
  const [agentTableDir, setAgentTableDir] = useState<SortDirection>("asc");

  const handleAgentTableSort = (col: string) => {
    if (agentTableCol === col) {
      setAgentTableDir(agentTableDir === "asc" ? "desc" : "asc");
    } else {
      setAgentTableCol(col);
      setAgentTableDir("asc");
    }
  };

  const filteredAgents = agents
    .filter(agent => {
      return Object.entries(tagFilters).every(([key, values]) => {
        if (values.length === 0) return true;
        return values.includes(agent.tags?.[key] ?? "");
      });
    })
    .filter(agent => !groupRestriction || agent.tags?.["loom:group"] === groupRestriction);

  const handleRegister = async (arn: string, modelId?: string) => {
    setSubmitting(true);
    try {
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'agent', 'import', arn);
      await onRegister(arn, modelId);
      setShowAddForm(false);
      toast.success("Agent registered");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Registration failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeploy = async (request: AgentDeployRequest) => {
    if (!onDeploy) return;
    const action = exportAgentId ? "update_deploy" : "deploy";
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'agent', action, request.name);
    setShowAddForm(false);
    try {
      await onDeploy(request, exportAgentId);
      setExportAgentId(undefined);
      toast.success(exportAgentId ? "Agent update started" : "Agent deployment started");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Deployment failed");
    }
  };

  const handleDeployHarness = async (request: AgentHarnessDeployRequest) => {
    if (!onDeployHarness) return;
    const action = exportAgentId ? "update_harness" : "deploy_harness";
    if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'agent', action, request.name);
    setShowAddForm(false);
    try {
      await onDeployHarness(request, exportAgentId);
      setExportAgentId(undefined);
      toast.success(exportAgentId ? "Agent update started" : "Harness deployment started");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Deployment failed");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Agent Administration</h2>
          <p className="text-sm text-muted-foreground">Deploy new agents or import existing ones.</p>
        </div>
        <div className="flex rounded-md border text-sm shrink-0" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "cards"}
            className={`px-2 py-1 rounded-l-md transition-colors ${viewMode === "cards" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
            onClick={() => onViewModeChange("cards")}
            title="Card view"
          >
            <LayoutGrid className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "table"}
            className={`px-2 py-1 rounded-r-md transition-colors ${viewMode === "table" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
            onClick={() => onViewModeChange("table")}
            title="Table view"
          >
            <TableIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium">Agents</h3>
            <p className="text-xs text-muted-foreground mt-1 whitespace-pre-line">
              {"An agent can be deployed directly from here.\nAn agent that was previously created can also be imported here."}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0 ml-4">
            <SortButton direction={agentSortDir} onClick={() => setAgentSortDir(toggleSortDirection("builder-agents", agentSortDir))} />
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowAddForm(!showAddForm)}
              disabled={readOnly}
            >
              <Plus className="h-3.5 w-3.5 mr-1" />
              Add Agent
            </Button>
          </div>
        </div>

        {showAddForm && (
          <Card>
            <CardContent className="pt-4 space-y-3">
              <div className="flex rounded-md border text-sm w-fit" role="tablist">
                {(["deploy", "register"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === tab}
                    className={`px-4 py-1.5 transition-colors ${
                      tab === "deploy" ? "rounded-l-md" : "rounded-r-md"
                    } ${
                      activeTab === tab
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-accent"
                    }`}
                    onClick={() => setActiveTab(tab)}
                  >
                    {tab === "deploy" ? "Deploy" : "Import"}
                  </button>
                ))}
              </div>

              <AgentRegistrationForm
                mode={activeTab}
                onRegister={handleRegister}
                onDeploy={onDeploy ? handleDeploy : undefined}
                onDeployHarness={onDeployHarness ? handleDeployHarness : undefined}
                isLoading={submitting}
                groupRestriction={groupRestriction}
                ownerRestriction={ownerRestriction}
                exportAgentId={exportAgentId}
              />
            </CardContent>
          </Card>
        )}

        {/* Tag Filters */}
        {showOnCardPolicies.length > 0 && agents.length > 0 && (
          <div className="flex flex-wrap items-end gap-3">
            {requiredPolicies.map(tp => {
              const distinctValues = [...new Set(
                agents.map(a => a.tags?.[tp.key]).filter(Boolean)
              )] as string[];
              if (distinctValues.length === 0) return null;
              return (
                <div key={tp.key} className="space-y-1">
                  <div className="h-4 flex items-center">
                    <label className="text-[10px] text-muted-foreground">{tp.key.replace(/^loom:/, "")}</label>
                  </div>
                  <MultiSelect
                    values={tagFilters[tp.key] ?? []}
                    options={distinctValues.sort()}
                    onChange={(v) => setTagFilters(prev => ({ ...prev, [tp.key]: v }))}
                  />
                </div>
              );
            })}
            <div className="space-y-1">
              <div className="h-4 flex items-center">
                <label className="text-[10px] text-muted-foreground">custom</label>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="h-7 w-[2.25rem] p-0 bg-input-bg"
                onClick={() => {
                  const next = !showCustomTags;
                  setShowCustomTags(next);
                  localStorage.setItem("loom:showCustomTags", String(next));
                }}
                title={showCustomTags ? "Hide custom tags" : "Show custom tags"}
              >
                {showCustomTags ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
              </Button>
            </div>
            {customPolicies.filter(p => activeCustomFilterKeys.includes(p.key)).map(tp => {
              const distinctValues = [...new Set(
                agents.map(a => a.tags?.[tp.key]).filter(Boolean)
              )] as string[];
              return (
                <div key={tp.key} className="space-y-1">
                  <div className="h-4 flex items-center gap-1">
                    <label className="text-[10px] text-muted-foreground">{tp.key}</label>
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground"
                      onClick={() => {
                        setActiveCustomFilterKeys(prev => prev.filter(k => k !== tp.key));
                        setTagFilters(prev => {
                          const next = { ...prev };
                          delete next[tp.key];
                          return next;
                        });
                      }}
                      title="Remove filter"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                  <MultiSelect
                    values={tagFilters[tp.key] ?? []}
                    options={distinctValues.sort()}
                    onChange={(v) => setTagFilters(prev => ({ ...prev, [tp.key]: v }))}
                  />
                </div>
              );
            })}
            {customPolicies.filter(p => !activeCustomFilterKeys.includes(p.key)).length > 0 && (
              <div className="space-y-1">
                <div className="h-4 flex items-center">
                  <label className="text-[10px] text-muted-foreground">custom filters</label>
                </div>
                <AddFilterDropdown
                  options={customPolicies
                    .filter(p => !activeCustomFilterKeys.includes(p.key))
                    .map(p => ({ key: p.key, label: p.key }))}
                  onSelect={(v) => setActiveCustomFilterKeys(prev => [...prev, v])}
                />
              </div>
            )}
            {(Object.values(tagFilters).some(v => v.length > 0) || activeCustomFilterKeys.length > 0) && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs self-end"
                onClick={() => { setTagFilters({}); setActiveCustomFilterKeys([]); }}
              >
                Clear filters
              </Button>
            )}
            <span className="text-xs text-muted-foreground ml-auto self-end">
              Showing {filteredAgents.length} of {agents.length} agents
            </span>
          </div>
        )}

        {loading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-48" />
            ))}
          </div>
        ) : filteredAgents.length === 0 ? (
          <p className="text-sm text-muted-foreground py-8">
            {agents.length === 0
              ? "No agents yet. Add one above."
              : "No agents match the selected filters."}
          </p>
        ) : (
          <>
            {viewMode === "cards" ? (
              <SortableCardGrid
                items={filteredAgents}
                getId={(a) => String(a.id)}
                getName={(a) => a.name ?? a.runtime_id ?? ""}
                storageKey="builder-agents"
                sortDirection={agentSortDir}
                onSortDirectionChange={(d) => { if (d) { setAgentSortDir(d); saveSortDirection("builder-agents", d); } }}
                renderItem={(agent) => (
                  <AgentCard
                    agent={agent}
                    onSelect={onSelectAgent}
                    onDelete={onDelete}
                    onEdit={hasScope("admin:write") ? (id) => { setExportAgentId(id); setShowAddForm(true); } : undefined}
                    readOnly={readOnly}
                    showOnCardKeys={effectiveShowOnCardKeys}
                    deleteStartTime={deleteStartTimes?.[agent.id]}
                    updateStartTime={updateStartTimes?.[agent.id]}
                    userGroups={userGroups}
                    registryEnabled={registryEnabled}
                  />
                )}
              />
            ) : (
              <div className="rounded-md border overflow-hidden">
                <Table className="table-fixed">
                  <TableHeader>
                    <TableRow className="bg-card hover:bg-card">
                      <SortableTableHead column="name" activeColumn={agentTableCol} direction={agentTableDir} onSort={handleAgentTableSort} className="w-[26%]">Name</SortableTableHead>
                      <SortableTableHead column="status" activeColumn={agentTableCol} direction={agentTableDir} onSort={handleAgentTableSort} className="w-[10%]">Status</SortableTableHead>
                      <SortableTableHead column="cost" activeColumn={agentTableCol} direction={agentTableDir} onSort={handleAgentTableSort} className="w-[12%]">Cost</SortableTableHead>
                      <SortableTableHead column="type" activeColumn={agentTableCol} direction={agentTableDir} onSort={handleAgentTableSort} className="w-[10%]">Type</SortableTableHead>
                      <SortableTableHead column="network" activeColumn={agentTableCol} direction={agentTableDir} onSort={handleAgentTableSort} className="w-[10%]">Network</SortableTableHead>
                      <SortableTableHead column="registry" activeColumn={agentTableCol} direction={agentTableDir} onSort={handleAgentTableSort} className="w-[10%]">Registry</SortableTableHead>
                      <SortableTableHead column="region" activeColumn={agentTableCol} direction={agentTableDir} onSort={handleAgentTableSort} className="w-[10%]">Region</SortableTableHead>
                      <SortableTableHead column="registered" activeColumn={agentTableCol} direction={agentTableDir} onSort={handleAgentTableSort} className="w-[14%]">Registered</SortableTableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sortRows(filteredAgents, agentTableCol, agentTableDir, {
                      name: (a) => a.name ?? a.runtime_id ?? "",
                      status: (a) => a.status ?? "",
                      cost: (a) => a.cost_summary?.total_cost ?? 0,
                      type: (a) => a.source ?? "",
                      network: (a) => a.network_mode ?? "",
                      registry: (a) => a.registry_status ?? "",
                      region: (a) => a.region ?? "",
                      registered: (a) => a.registered_at ?? "",
                    }).map((agent) => (
                      <TableRow
                        key={agent.id}
                        className="bg-input-bg hover:bg-input-bg/80 cursor-pointer"
                        onClick={() => onSelectAgent(agent.id)}
                      >
                        <TableCell className="font-medium text-sm">
                          <div className="flex items-center gap-2">
                            {agent.name ?? agent.runtime_id}
                            <RegistryStatusBadge status={agent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusVariant(agent.status)} className="text-[10px] px-1.5 py-0">
                            {agent.status ?? "unknown"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {agent.cost_summary && agent.cost_summary.total_cost > 0
                            ? (agent.cost_summary.total_cost < 0.01
                                ? `~$${agent.cost_summary.total_cost.toFixed(6)}`
                                : `~$${agent.cost_summary.total_cost.toFixed(4)}`)
                            : "\u2014"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {agent.source === "harness" ? "MANAGED" : agent.source === "deploy" ? "CUSTOM" : agent.source ?? "\u2014"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {agent.network_mode ?? "\u2014"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          <RegistryStatusBadge status={agent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">{agent.region}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatTimestamp(agent.registered_at, timezone)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
