import { useState, useEffect, useCallback, useRef } from "react";
import { AgentCard } from "@/components/AgentCard";
import { MemoryCard } from "@/components/MemoryCard";
import { SortableCardGrid, SortButton, loadSortDirection, toggleSortDirection, saveSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import { SortableTableHead, sortRows } from "@/components/SortableTableHead";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { MultiSelect } from "@/components/ui/multi-select";
import { AddFilterDropdown } from "@/components/ui/add-filter-dropdown";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LayoutGrid, TableIcon, X, Eye, EyeOff, ChevronRight, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant } from "@/lib/status";
import { listMemories, refreshMemory, deleteMemory, purgeMemory } from "@/api/memories";
import { listMcpServers } from "@/api/mcp";
import { listA2aAgents } from "@/api/a2a";
import { listTagPolicies, getRegistryConfig } from "@/api/settings";
import { ApiError } from "@/api/client";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import type { AgentResponse, MemoryResponse, McpServer, A2aAgent, TagPolicy } from "@/api/types";

interface CatalogPageProps {
  agents: AgentResponse[];
  loading: boolean;
  viewMode: "cards" | "table";
  onViewModeChange: (mode: "cards" | "table") => void;
  onSelectAgent: (id: number) => void;
  onRefreshAgent: (id: number) => void;
  onDelete: (id: number, cleanupAws: boolean) => void;
  readOnly?: boolean;
  agentDeleteStartTimes?: Record<number, number>;
  canViewAgents?: boolean;
  canViewMemories?: boolean;
  canViewMcp?: boolean;
  canViewA2a?: boolean;
  groupRestriction?: string;
  userGroups?: string[];
  onNavigateToMcp?: (serverId: number) => void;
  onNavigateToA2a?: (agentId: number) => void;
}

export function CatalogPage({
  agents,
  loading,
  viewMode,
  onViewModeChange,
  onSelectAgent,
  onRefreshAgent: _onRefreshAgent,
  onDelete,
  readOnly,
  agentDeleteStartTimes,
  canViewAgents = true,
  canViewMemories = true,
  canViewMcp = true,
  canViewA2a = true,
  groupRestriction,
  userGroups = [],
  onNavigateToMcp,
  onNavigateToA2a,
}: CatalogPageProps) {
  const { timezone } = useTimezone();
  // Tag filter state
  const [registryEnabled, setRegistryEnabled] = useState(false);
  const [tagPolicies, setTagPolicies] = useState<TagPolicy[]>([]);
  const [tagFilters, setTagFilters] = useState<Record<string, string[]>>(() => {
    try { return JSON.parse(localStorage.getItem("loom:tagFilters:catalog") || "{}") as Record<string, string[]>; } catch { return {}; }
  });

  useEffect(() => {
    // Only fetch tag policies if user can view any section
    if (canViewAgents || canViewMemories || canViewMcp || canViewA2a) {
      void listTagPolicies().then(setTagPolicies).catch(() => {});
    }
  }, [canViewAgents, canViewMemories, canViewMcp, canViewA2a]);

  useEffect(() => {
    getRegistryConfig().then((c) => setRegistryEnabled(c.enabled)).catch(() => {});
  }, []);

  const showOnCardPolicies = tagPolicies.filter(tp => tp.show_on_card);
  const showOnCardKeys = showOnCardPolicies.map(tp => tp.key);

  // R3: Progressive disclosure filtering
  const requiredPolicies = showOnCardPolicies.filter(tp => tp.required);
  const customFilterPolicies = showOnCardPolicies.filter(tp => !tp.required);
  const [activeCustomFilterKeys, setActiveCustomFilterKeys] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("loom:customFilterKeys:catalog") || "[]") as string[]; } catch { return []; }
  });

  // Persist filter state to localStorage
  useEffect(() => { localStorage.setItem("loom:tagFilters:catalog", JSON.stringify(tagFilters)); }, [tagFilters]);
  useEffect(() => { localStorage.setItem("loom:customFilterKeys:catalog", JSON.stringify(activeCustomFilterKeys)); }, [activeCustomFilterKeys]);

  // R4: Custom tag show/hide toggle
  const [showCustomTags, setShowCustomTags] = useState(() => localStorage.getItem("loom:showCustomTags") !== "false");
  const requiredKeySet = new Set(requiredPolicies.map(tp => tp.key));
  const effectiveShowOnCardKeys = showCustomTags ? showOnCardKeys : showOnCardKeys.filter(k => requiredKeySet.has(k));

  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem("loom:collapsedSections:catalog") || "[]") as string[];
      return new Set(stored);
    } catch { return new Set(); }
  });
  const toggleSection = (section: string) => {
    setCollapsedSections(prev => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section); else next.add(section);
      localStorage.setItem("loom:collapsedSections:catalog", JSON.stringify([...next]));
      return next;
    });
  };

  const matchesFilters = (tags: Record<string, string> | undefined) => {
    return Object.entries(tagFilters).every(([key, values]) => {
      if (values.length === 0) return true;
      return values.includes(tags?.[key] ?? "");
    });
  };

  const [agentSortDir, setAgentSortDir] = useState<SortDirection>(() => loadSortDirection("catalog-agents"));
  const [memorySortDir, setMemorySortDir] = useState<SortDirection>(() => loadSortDirection("catalog-memories"));
  const [mcpSortDir, setMcpSortDir] = useState<SortDirection>(() => loadSortDirection("catalog-mcp"));
  const [agentTableCol, setAgentTableCol] = useState<string | null>("name");
  const [agentTableDir, setAgentTableDir] = useState<SortDirection>("asc");
  const [memoryTableCol, setMemoryTableCol] = useState<string | null>("name");
  const [memoryTableDir, setMemoryTableDir] = useState<SortDirection>("asc");
  const [mcpTableCol, setMcpTableCol] = useState<string | null>("name");
  const [mcpTableDir, setMcpTableDir] = useState<SortDirection>("asc");
  const [a2aSortDir, setA2aSortDir] = useState<SortDirection>(() => loadSortDirection("catalog-a2a"));
  const [a2aTableCol, setA2aTableCol] = useState<string | null>("name");
  const [a2aTableDir, setA2aTableDir] = useState<SortDirection>("asc");

  const handleAgentTableSort = (col: string) => {
    if (agentTableCol === col) {
      setAgentTableDir(agentTableDir === "asc" ? "desc" : "asc");
    } else {
      setAgentTableCol(col);
      setAgentTableDir("asc");
    }
  };
  const handleMemoryTableSort = (col: string) => {
    if (memoryTableCol === col) {
      setMemoryTableDir(memoryTableDir === "asc" ? "desc" : "asc");
    } else {
      setMemoryTableCol(col);
      setMemoryTableDir("asc");
    }
  };
  const handleMcpTableSort = (col: string) => {
    if (mcpTableCol === col) {
      setMcpTableDir(mcpTableDir === "asc" ? "desc" : "asc");
    } else {
      setMcpTableCol(col);
      setMcpTableDir("asc");
    }
  };
  const handleA2aTableSort = (col: string) => {
    if (a2aTableCol === col) {
      setA2aTableDir(a2aTableDir === "asc" ? "desc" : "asc");
    } else {
      setA2aTableCol(col);
      setA2aTableDir("asc");
    }
  };

  const filteredAgents = agents
    .filter(agent => matchesFilters(agent.tags))
    .filter(agent => !groupRestriction || agent.tags?.["loom:group"] === groupRestriction);

  // MCP server data
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [mcpLoading, setMcpLoading] = useState(true);

  const fetchMcpData = useCallback(async () => {
    if (!canViewMcp) {
      setMcpLoading(false);
      return;
    }
    try {
      const data = await listMcpServers();
      setMcpServers(data);
    } catch {
      // silently ignore
    } finally {
      setMcpLoading(false);
    }
  }, [canViewMcp]);

  useEffect(() => {
    void fetchMcpData();
  }, [fetchMcpData]);

  // A2A agent data
  const [a2aAgents, setA2aAgents] = useState<A2aAgent[]>([]);
  const [a2aLoading, setA2aLoading] = useState(true);

  const fetchA2aData = useCallback(async () => {
    if (!canViewA2a) {
      setA2aLoading(false);
      return;
    }
    try {
      const data = await listA2aAgents();
      setA2aAgents(data);
    } catch {
      // silently ignore
    } finally {
      setA2aLoading(false);
    }
  }, [canViewA2a]);

  useEffect(() => {
    void fetchA2aData();
  }, [fetchA2aData]);

  // Memory data
  const [memories, setMemories] = useState<MemoryResponse[]>([]);
  const [memoriesLoading, setMemoriesLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deleteStartTimes, setDeleteStartTimes] = useState<Record<number, number>>({});
  const filteredMemories = memories
    .filter(mem => matchesFilters(mem.tags))
    .filter(mem => !groupRestriction || mem.tags?.["loom:group"] === groupRestriction);

  // Elapsed timer for transitional states
  const [now, setNow] = useState(Date.now());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const memoriesRef = useRef(memories);
  memoriesRef.current = memories;

  const fetchMemoryData = useCallback(async () => {
    if (!canViewMemories) {
      setMemoriesLoading(false);
      return;
    }
    try {
      const data = await listMemories();
      setMemories(data);
    } catch {
      // silently ignore
    } finally {
      setMemoriesLoading(false);
    }
  }, [canViewMemories]);

  useEffect(() => {
    void fetchMemoryData();
  }, [fetchMemoryData]);

  // 1-second tick for elapsed display, 3-second poll for AWS status
  useEffect(() => {
    const hasTransitional = memories.some(
      (m) => m.status === "CREATING" || m.status === "DELETING",
    );

    if (!hasTransitional) {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }

    if (!timerRef.current) {
      timerRef.current = setInterval(() => {
        setNow(Date.now());
      }, 1000);
    }

    if (!pollRef.current) {
      pollRef.current = setInterval(async () => {
        const current = memoriesRef.current;
        const transitional = current.filter(
          (m) => m.status === "CREATING" || m.status === "DELETING",
        );
        for (const mem of transitional) {
          try {
            const updated = await refreshMemory(mem.id);
            setMemories((prev) => prev.map((m) => (m.id === mem.id ? updated : m)));
          } catch (e) {
            if (mem.status === "DELETING" && e instanceof ApiError && e.status === 404) {
              try {
                await purgeMemory(mem.id);
              } catch {
                // ignore cleanup errors
              }
              setMemories((prev) => prev.filter((m) => m.id !== mem.id));
              toast.success("Memory resource deleted");
            }
          }
        }
      }, 3000);
    }

    return () => {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [memories.map((m) => `${m.id}:${m.status}`).join(",")]);



  const handleMemoryDelete = async (id: number, deleteInAws: boolean) => {
    setSubmitting(true);
    try {
      const updated = await deleteMemory(id, deleteInAws);
      if (updated.status === "DELETING") {
        setDeleteStartTimes((prev) => ({ ...prev, [id]: Date.now() }));
        setMemories((prev) => prev.map((m) => (m.id === id ? updated : m)));
        toast.success("Memory deletion initiated");
      } else {
        setMemories((prev) => prev.filter((m) => m.id !== id));
        toast.success(deleteInAws ? "Memory resource deleted" : "Memory removed from Loom");
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Failed to delete memory");
    } finally {
      setSubmitting(false);
    }
  };



  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Platform Catalog</h2>
          <p className="text-sm text-muted-foreground">Browse and manage registered agents and resources.</p>
          <p className="text-sm text-muted-foreground">Costs for agents and memory resources are <em>estimates</em>.</p>
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

      {/* Tag Filters */}
      {showOnCardPolicies.length > 0 && (agents.length > 0 || memories.length > 0) && (
        <div className="flex flex-wrap items-end gap-3">
          {requiredPolicies.map(tp => {
            const distinctValues = [...new Set([
              ...agents.map(a => a.tags?.[tp.key]).filter(Boolean),
              ...memories.map(m => m.tags?.[tp.key]).filter(Boolean),
            ])] as string[];
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
          {customFilterPolicies.filter(p => activeCustomFilterKeys.includes(p.key)).map(tp => {
            const distinctValues = [...new Set([
              ...agents.map(a => a.tags?.[tp.key]).filter(Boolean),
              ...memories.map(m => m.tags?.[tp.key]).filter(Boolean),
            ])] as string[];
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
          {customFilterPolicies.filter(p => !activeCustomFilterKeys.includes(p.key)).length > 0 && (
            <div className="space-y-1">
              <div className="h-4 flex items-center">
                <label className="text-[10px] text-muted-foreground">custom filters</label>
              </div>
              <AddFilterDropdown
                options={customFilterPolicies
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
            Showing {filteredAgents.length} of {agents.length} agents, {filteredMemories.length} of {memories.length} memories
          </span>
        </div>
      )}

      {/* Agents Section */}
      {canViewAgents && (
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <button type="button" className="flex items-center gap-1 text-sm font-medium hover:text-foreground/80" onClick={() => toggleSection("agents")}>
            {collapsedSections.has("agents") ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            Agents
          </button>
          {!collapsedSections.has("agents") && <SortButton direction={agentSortDir} onClick={() => setAgentSortDir(toggleSortDirection("catalog-agents", agentSortDir))} />}
        </div>

        {!collapsedSections.has("agents") && (loading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-48" />
            ))}
          </div>
        ) : filteredAgents.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            {agents.length === 0
              ? "No agents registered. Use the Builder page to register or deploy an agent."
              : "No agents match the selected filters."}
          </p>
        ) : (
          <>
            {viewMode === "cards" ? (
              <SortableCardGrid
                items={filteredAgents}
                getId={(a) => String(a.id)}
                getName={(a) => a.name ?? a.runtime_id ?? ""}
                storageKey="catalog-agents"
                sortDirection={agentSortDir}
                onSortDirectionChange={(d) => { if (d) { setAgentSortDir(d); saveSortDirection("catalog-agents", d); } }}
                renderItem={(agent) => (
                  <AgentCard
                    agent={agent}
                    onSelect={onSelectAgent}
                    onDelete={onDelete}
                    readOnly={readOnly}
                    showOnCardKeys={effectiveShowOnCardKeys}
                    deleteStartTime={agentDeleteStartTimes?.[agent.id]}
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
        ))}
      </section>
      )}

      {/* Memory Resources Section */}
      {canViewMemories && (
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <button type="button" className="flex items-center gap-1 text-sm font-medium hover:text-foreground/80" onClick={() => toggleSection("memories")}>
            {collapsedSections.has("memories") ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            Memory Resources
          </button>
          {!collapsedSections.has("memories") && <SortButton direction={memorySortDir} onClick={() => setMemorySortDir(toggleSortDirection("catalog-memories", memorySortDir))} />}
        </div>

        {!collapsedSections.has("memories") && (memoriesLoading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-40" />
            ))}
          </div>
        ) : filteredMemories.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            {memories.length === 0
              ? "No memory resources. Use the Memory page to create or import one."
              : "No memory resources match the selected filters."}
          </p>
        ) : viewMode === "cards" ? (
          <SortableCardGrid
            items={filteredMemories}
            getId={(m) => String(m.id)}
            getName={(m) => m.name}
            storageKey="catalog-memories"
            sortDirection={memorySortDir}
            onSortDirectionChange={(d) => { if (d) { setMemorySortDir(d); saveSortDirection("catalog-memories", d); } }}
            renderItem={(mem) => (
              <MemoryCard
                memory={mem}
                now={now}
                submitting={submitting}
                onDelete={handleMemoryDelete}
                readOnly={readOnly}
                showOnCardKeys={effectiveShowOnCardKeys}
                deleteStartTime={deleteStartTimes[mem.id]}
                userGroups={userGroups}
              />
            )}
          />
        ) : (
          <div className="rounded-md border overflow-hidden">
            <Table className="table-fixed">
              <TableHeader>
                <TableRow className="bg-card hover:bg-card">
                  <SortableTableHead column="name" activeColumn={memoryTableCol} direction={memoryTableDir} onSort={handleMemoryTableSort} className="w-[26%]">Name</SortableTableHead>
                  <SortableTableHead column="status" activeColumn={memoryTableCol} direction={memoryTableDir} onSort={handleMemoryTableSort} className="w-[10%]">Status</SortableTableHead>
                  <SortableTableHead column="cost" activeColumn={memoryTableCol} direction={memoryTableDir} onSort={handleMemoryTableSort} className="w-[12%]">Cost</SortableTableHead>
                  <SortableTableHead column="strategies" activeColumn={memoryTableCol} direction={memoryTableDir} onSort={handleMemoryTableSort} className="w-[12%]">Strategies</SortableTableHead>
                  <SortableTableHead column="expiry" activeColumn={memoryTableCol} direction={memoryTableDir} onSort={handleMemoryTableSort} className="w-[12%]">Event Expiry</SortableTableHead>
                  <SortableTableHead column="region" activeColumn={memoryTableCol} direction={memoryTableDir} onSort={handleMemoryTableSort} className="w-[12%]">Region</SortableTableHead>
                  <SortableTableHead column="registered" activeColumn={memoryTableCol} direction={memoryTableDir} onSort={handleMemoryTableSort} className="w-[16%]">Registered</SortableTableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortRows(filteredMemories, memoryTableCol, memoryTableDir, {
                  name: (m) => m.name,
                  status: (m) => m.status,
                  cost: (m) => m.cost_summary?.total_memory_estimated_cost ?? 0,
                  strategies: (m) => Array.isArray(m.strategies_config) ? m.strategies_config.length : Array.isArray(m.strategies_response) ? m.strategies_response.length : 0,
                  expiry: (m) => m.event_expiry_duration,
                  region: (m) => m.region ?? "",
                  registered: (m) => m.created_at ?? "",
                }).map((mem) => (
                  <TableRow key={mem.id} className="bg-input-bg hover:bg-input-bg/80">
                    <TableCell className="font-medium text-sm">{mem.name}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(mem.status)} className="text-[10px] px-1.5 py-0">
                        {mem.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {mem.cost_summary && mem.cost_summary.total_memory_estimated_cost > 0
                        ? (mem.cost_summary.total_memory_estimated_cost < 0.01
                            ? `~$${mem.cost_summary.total_memory_estimated_cost.toFixed(6)}`
                            : `~$${mem.cost_summary.total_memory_estimated_cost.toFixed(4)}`)
                        : "\u2014"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {Array.isArray(mem.strategies_config) ? mem.strategies_config.length : Array.isArray(mem.strategies_response) ? mem.strategies_response.length : 0}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {mem.event_expiry_duration}d
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{mem.region}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatTimestamp(mem.created_at, timezone)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ))}
      </section>
      )}

      {/* MCP Servers Section */}
      {canViewMcp && (
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <button type="button" className="flex items-center gap-1 text-sm font-medium hover:text-foreground/80" onClick={() => toggleSection("mcp")}>
            {collapsedSections.has("mcp") ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            MCP Servers
          </button>
          {!collapsedSections.has("mcp") && <SortButton direction={mcpSortDir} onClick={() => setMcpSortDir(toggleSortDirection("catalog-mcp", mcpSortDir))} />}
        </div>

        {!collapsedSections.has("mcp") && (mcpLoading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-32" />
            ))}
          </div>
        ) : mcpServers.length === 0 ? (
          <p className="text-sm text-muted-foreground py-8 text-center">
            No MCP servers registered. Use the MCP Servers page to register one.
          </p>
        ) : viewMode === "cards" ? (
          <SortableCardGrid
            items={mcpServers}
            getId={(s) => String(s.id)}
            getName={(s) => s.name}
            storageKey="catalog-mcp"
            sortDirection={mcpSortDir}
            onSortDirectionChange={(d) => { if (d) { setMcpSortDir(d); saveSortDirection("catalog-mcp", d); } }}
            renderItem={(server) => (
              <Card
                className={`py-3 gap-1 transition-colors hover:bg-accent/50${onNavigateToMcp ? " cursor-pointer" : ""}`}
                onClick={onNavigateToMcp ? () => onNavigateToMcp(server.id) : undefined}
              >
                <CardHeader className="gap-0 pb-2">
                  <div className="flex items-center gap-2">
                    <div className="text-sm font-medium truncate" title={server.name}>
                      {server.name}
                    </div>
                    <RegistryStatusBadge status={server.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                  </div>
                </CardHeader>
                <CardContent className="text-xs text-muted-foreground">
                  <div className="rounded border bg-input-bg p-3 space-y-0.5">
                    <div className="truncate" title={server.endpoint_url}><span className="text-muted-foreground/70">Endpoint:</span> {server.endpoint_url}</div>
                    <div><span className="text-muted-foreground/70">Transport:</span> {server.transport_type === "streamable_http" ? "Streamable HTTP" : "SSE"}</div>
                    <div><span className="text-muted-foreground/70">Authentication:</span> {server.auth_type === "oauth2" ? "OAuth2" : "None"}</div>
                    {server.created_at && (
                      <div><span className="text-muted-foreground/70">Created:</span> {formatTimestamp(server.created_at, timezone)}</div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          />
        ) : (
          <div className="rounded-md border overflow-hidden">
            <Table className="table-fixed">
              <TableHeader>
                <TableRow className="bg-card hover:bg-card">
                  <SortableTableHead column="name" activeColumn={mcpTableCol} direction={mcpTableDir} onSort={handleMcpTableSort} className="w-[18%]">Name</SortableTableHead>
                  <SortableTableHead column="endpoint" activeColumn={mcpTableCol} direction={mcpTableDir} onSort={handleMcpTableSort} className="w-[46%]">Endpoint</SortableTableHead>
                  <SortableTableHead column="transport" activeColumn={mcpTableCol} direction={mcpTableDir} onSort={handleMcpTableSort} className="w-[10%]">Transport</SortableTableHead>
                  <SortableTableHead column="auth" activeColumn={mcpTableCol} direction={mcpTableDir} onSort={handleMcpTableSort} className="w-[10%]">Auth</SortableTableHead>
                  <SortableTableHead column="created" activeColumn={mcpTableCol} direction={mcpTableDir} onSort={handleMcpTableSort} className="w-[16%]">Created</SortableTableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortRows(mcpServers, mcpTableCol, mcpTableDir, {
                  name: (s) => s.name,
                  endpoint: (s) => s.endpoint_url,
                  transport: (s) => s.transport_type,
                  auth: (s) => s.auth_type,
                  created: (s) => s.created_at ?? "",
                }).map((server) => (
                  <TableRow
                    key={server.id}
                    className={`bg-input-bg hover:bg-input-bg/80${onNavigateToMcp ? " cursor-pointer" : ""}`}
                    onClick={onNavigateToMcp ? () => onNavigateToMcp(server.id) : undefined}
                  >
                    <TableCell className="font-medium text-sm">
                      <div className="flex items-center gap-2">
                        {server.name}
                        <RegistryStatusBadge status={server.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground truncate">{server.endpoint_url}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{server.transport_type === "streamable_http" ? "Streamable HTTP" : "SSE"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{server.auth_type === "oauth2" ? "OAuth2" : "None"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatTimestamp(server.created_at, timezone)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ))}
      </section>
      )}

      {/* A2A Agents Section */}
      {canViewA2a && (
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <button type="button" className="flex items-center gap-1 text-sm font-medium hover:text-foreground/80" onClick={() => toggleSection("a2a")}>
            {collapsedSections.has("a2a") ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            A2A Agents
          </button>
          {!collapsedSections.has("a2a") && <SortButton direction={a2aSortDir} onClick={() => setA2aSortDir(toggleSortDirection("catalog-a2a", a2aSortDir))} />}
        </div>

        {!collapsedSections.has("a2a") && (a2aLoading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-32" />
            ))}
          </div>
        ) : a2aAgents.length === 0 ? (
          <p className="text-sm text-muted-foreground py-8 text-center">
            No A2A agents registered. Use the A2A Agents page to register one.
          </p>
        ) : viewMode === "cards" ? (
          <SortableCardGrid
            items={a2aAgents}
            getId={(a) => String(a.id)}
            getName={(a) => a.name}
            storageKey="catalog-a2a"
            sortDirection={a2aSortDir}
            onSortDirectionChange={(d) => { if (d) { setA2aSortDir(d); saveSortDirection("catalog-a2a", d); } }}
            renderItem={(agent) => (
              <Card
                className={`py-3 gap-1 transition-colors hover:bg-accent/50${onNavigateToA2a ? " cursor-pointer" : ""}`}
                onClick={onNavigateToA2a ? () => onNavigateToA2a(agent.id) : undefined}
              >
                <CardHeader className="gap-0 pb-2">
                  <div className="flex items-center gap-2">
                    <div className="text-sm font-medium truncate" title={agent.name}>
                      {agent.name}
                    </div>
                    <RegistryStatusBadge status={agent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                  </div>
                </CardHeader>
                <CardContent className="text-xs text-muted-foreground">
                  <div className="rounded border bg-input-bg p-3 space-y-0.5">
                    {agent.description && (
                      <div className="truncate" title={agent.description}>{agent.description}</div>
                    )}
                    <div className="truncate" title={agent.base_url}><span className="text-muted-foreground/70">URL:</span> {agent.base_url}</div>
                    <div><span className="text-muted-foreground/70">Version:</span> {agent.agent_version}</div>
                    <div><span className="text-muted-foreground/70">Auth:</span> {agent.auth_type === "oauth2" ? "OAuth2" : "None"}</div>
                    {agent.provider_organization && (
                      <div><span className="text-muted-foreground/70">Provider:</span> {agent.provider_organization}</div>
                    )}
                    {agent.created_at && (
                      <div><span className="text-muted-foreground/70">Created:</span> {formatTimestamp(agent.created_at, timezone)}</div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          />
        ) : (
          <div className="rounded-md border overflow-hidden">
            <Table className="table-fixed">
              <TableHeader>
                <TableRow className="bg-card hover:bg-card">
                  <SortableTableHead column="name" activeColumn={a2aTableCol} direction={a2aTableDir} onSort={handleA2aTableSort} className="w-[18%]">Name</SortableTableHead>
                  <SortableTableHead column="url" activeColumn={a2aTableCol} direction={a2aTableDir} onSort={handleA2aTableSort} className="w-[46%]">Base URL</SortableTableHead>
                  <SortableTableHead column="version" activeColumn={a2aTableCol} direction={a2aTableDir} onSort={handleA2aTableSort} className="w-[10%]">Version</SortableTableHead>
                  <SortableTableHead column="auth" activeColumn={a2aTableCol} direction={a2aTableDir} onSort={handleA2aTableSort} className="w-[10%]">Auth</SortableTableHead>
                  <SortableTableHead column="created" activeColumn={a2aTableCol} direction={a2aTableDir} onSort={handleA2aTableSort} className="w-[16%]">Created</SortableTableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortRows(a2aAgents, a2aTableCol, a2aTableDir, {
                  name: (a) => a.name,
                  url: (a) => a.base_url,
                  version: (a) => a.agent_version,
                  auth: (a) => a.auth_type,
                  created: (a) => a.created_at ?? "",
                }).map((agent) => (
                  <TableRow
                    key={agent.id}
                    className={`bg-input-bg hover:bg-input-bg/80${onNavigateToA2a ? " cursor-pointer" : ""}`}
                    onClick={onNavigateToA2a ? () => onNavigateToA2a(agent.id) : undefined}
                  >
                    <TableCell className="font-medium text-sm">
                      <div className="flex items-center gap-2">
                        {agent.name}
                        <RegistryStatusBadge status={agent.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground truncate">{agent.base_url}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{agent.agent_version}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{agent.auth_type === "oauth2" ? "OAuth2" : "None"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatTimestamp(agent.created_at, timezone)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ))}
      </section>
      )}
    </div>
  );
}
