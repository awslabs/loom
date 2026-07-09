import { useState, useEffect, useMemo, Component, type ReactNode, type ErrorInfo } from "react";
import { Search, Check, Circle, X, LayoutGrid, TableIcon, ChevronRight, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { useRegistry } from "@/hooks/useRegistry";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import { RegistryActions } from "@/components/RegistryActions";
import { SortableTableHead, sortRows } from "@/components/SortableTableHead";
import { SortableCardGrid, loadSortDirection, saveSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import * as registryApi from "@/api/registry";
import type { RegistryRecord, RegistryRecordDetail } from "@/api/types";

/* ---------- Error Boundary ---------- */
interface ErrorBoundaryState { hasError: boolean; error: Error | null }

class DetailErrorBoundary extends Component<{ children: ReactNode; onBack: () => void }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Registry detail render error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="space-y-4">
          <p className="text-sm text-destructive">Failed to render record detail.</p>
          <Button variant="outline" size="sm" onClick={() => { this.setState({ hasError: false, error: null }); this.props.onBack(); }}>
            &larr; Back to registry
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}

/* ---------- Lifecycle Timeline ---------- */
const LIFECYCLE_STEPS = ["DRAFT", "PENDING_APPROVAL", "APPROVED"] as const;

const STEP_LABELS: Record<string, string> = {
  DRAFT: "Draft",
  PENDING_APPROVAL: "Pending Approval",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};

function LifecycleTimeline({ status }: { status: string }) {
  const isRejected = status === "REJECTED";

  // For the main flow, figure out which step index is current
  const currentIdx = LIFECYCLE_STEPS.indexOf(status as typeof LIFECYCLE_STEPS[number]);
  // If status is not in main flow (e.g. REJECTED), treat PENDING_APPROVAL as the last completed step
  const activeIdx = isRejected ? 2 : currentIdx;

  const steps = isRejected
    ? [...LIFECYCLE_STEPS.slice(0, 2), "REJECTED" as const]
    : [...LIFECYCLE_STEPS];

  const items: { type: "node"; step: string; isRejectStep: boolean; isCurrent: boolean; isCompleted: boolean; isFuture: boolean; circleClasses: string; labelClasses: string }[] = [];
  const lines: { type: "line"; lineClasses: string }[] = [];

  steps.forEach((step, i) => {
    const isCompleted = i < activeIdx;
    const isCurrent = i === activeIdx;
    const isRejectStep = step === "REJECTED";
    const isFuture = !isCompleted && !isCurrent;

    let circleClasses = "w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium shrink-0 ";
    if (isRejectStep && isCurrent) {
      circleClasses += "bg-destructive text-destructive-foreground ring-2 ring-destructive/30";
    } else if (isCurrent) {
      circleClasses += "bg-primary text-primary-foreground ring-2 ring-primary/30";
    } else if (isCompleted) {
      circleClasses += "bg-primary text-primary-foreground";
    } else {
      circleClasses += "bg-primary/30 text-primary-foreground";
    }

    let lineClasses = "h-0.5 flex-1 min-w-24 ";
    if (isRejectStep && (isCompleted || isCurrent)) {
      lineClasses += "bg-destructive/50";
    } else if (isCompleted || isCurrent) {
      lineClasses += "bg-primary/50";
    } else {
      lineClasses += "bg-primary/30";
    }

    let labelClasses = "text-[10px] mt-1 text-center whitespace-nowrap ";
    if (isRejectStep && isCurrent) {
      labelClasses += "text-destructive font-medium";
    } else if (isCurrent) {
      labelClasses += "text-foreground font-medium";
    } else {
      labelClasses += "text-muted-foreground";
    }

    items.push({ type: "node", step, isRejectStep, isCurrent, isCompleted, isFuture, circleClasses, labelClasses });
    if (i > 0) {
      lines.push({ type: "line", lineClasses });
    }
  });

  // Render: node0, line0, node1, line1, node2 as flat siblings
  const elements: ReactNode[] = [];
  items.forEach((node, i) => {
    if (i > 0) {
      const line = lines[i - 1]!;
      elements.push(
        <div key={`line-${i}`} className={line.lineClasses} />,
      );
    }
    elements.push(
      <div key={node.step} className="relative shrink-0 w-8 h-8" role="listitem">
        <div className={node.circleClasses}>
          {node.isRejectStep && node.isCurrent ? (
            <X className="h-4 w-4 text-white" />
          ) : node.isCompleted || node.isCurrent ? (
            <Check className="h-4 w-4" />
          ) : node.isFuture ? (
            <Circle className="h-3.5 w-3.5" />
          ) : (
            <span className="text-[10px]">{i + 1}</span>
          )}
        </div>
        <span className={`${node.labelClasses} absolute top-full left-1/2 -translate-x-1/2`}>{STEP_LABELS[node.step] ?? node.step}</span>
      </div>,
    );
  });

  return (
    <div className="flex items-center gap-2 pb-5" role="list" aria-label="Lifecycle timeline">
      {elements}
    </div>
  );
}

/* ---------- Descriptor View ---------- */

function tryParseJson(val: unknown): unknown {
  if (typeof val === "string") {
    try { return JSON.parse(val); } catch { return val; }
  }
  return val;
}

function DescriptorView({ descriptors, descriptorType, metadataSlot }: { descriptors: Record<string, unknown>; descriptorType: string; metadataSlot?: ReactNode }) {
  if (!descriptors || typeof descriptors !== "object" || Object.keys(descriptors).length === 0) {
    return <p className="text-xs text-muted-foreground">No descriptors available.</p>;
  }

  if (descriptorType === "A2A" || descriptors.a2a) {
    const a2a = descriptors.a2a as Record<string, unknown> | undefined;
    const cardRaw = a2a?.agentCard as Record<string, unknown> | undefined;
    const card = tryParseJson(cardRaw?.inlineContent ?? cardRaw) as Record<string, unknown> | null;
    if (!card || typeof card !== "object") {
      return <p className="text-xs text-muted-foreground">No agent card available.</p>;
    }

    const skills = Array.isArray(card.skills) ? card.skills as Array<Record<string, unknown>> : [];
    const caps = card.capabilities as Record<string, unknown> | undefined;
    const provider = card.provider as Record<string, string> | undefined;
    const meta = card._meta as Record<string, Record<string, string>> | undefined;
    const loomMeta = meta?.loom;

    return (
      <Card className="py-3 gap-1">
        <CardHeader className="gap-1 pb-3">
          <div className="text-sm font-medium">Descriptors</div>
        </CardHeader>
        <CardContent className="space-y-3 text-xs text-muted-foreground">
          <div>
            <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70 mb-1">Overview</div>
            <div className="rounded border bg-input-bg p-3 space-y-0.5">
              <div>Name: <span className="text-foreground">{String(card.name ?? "")}</span></div>
              {card.description ? <div>Description: <span className="text-foreground">{String(card.description)}</span></div> : null}
              <div>Version: <span className="text-foreground">{String(card.version ?? "")}</span></div>
              <div>Protocol Version: <span className="text-foreground">{String(card.protocolVersion ?? "")}</span></div>
              {card.url ? <div>URL: <span className="text-foreground">{String(card.url)}</span></div> : null}
              {Array.isArray(card.defaultInputModes) && (
                <div>Input Modes: <span className="text-foreground">{(card.defaultInputModes as string[]).join(", ")}</span></div>
              )}
              {Array.isArray(card.defaultOutputModes) && (
                <div>Output Modes: <span className="text-foreground">{(card.defaultOutputModes as string[]).join(", ")}</span></div>
              )}
            </div>
          </div>

          {caps && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70 mb-1">Capabilities</div>
              <div className="rounded border bg-input-bg p-3 space-y-0.5">
                {Object.entries(caps).map(([k, v]) => (
                  <div key={k}>{k}: <span className="text-foreground">{String(v ?? "")}</span></div>
                ))}
              </div>
            </div>
          )}

          {skills.length > 0 && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70 mb-1">Skills</div>
              <div className="space-y-1">
                {skills.map((skill, i) => (
                  <div key={String(skill.id ?? i)} className="rounded border bg-input-bg px-2 py-1">
                    <span className="font-medium text-foreground">{String(skill.name ?? skill.id)}</span>
                    {skill.description ? <span className="ml-1">&mdash; {String(skill.description)}</span> : null}
                    {Array.isArray(skill.tags) && (skill.tags as string[]).length > 0 && (
                      <span className="ml-2 text-muted-foreground/60">[{(skill.tags as string[]).join(", ")}]</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {provider && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70 mb-1">Provider</div>
              <div className="rounded border bg-input-bg p-3 space-y-0.5">
                <div>Organization: <span className="text-foreground">{provider.organization ?? ""}</span></div>
                {provider.url && <div>URL: <span className="text-foreground">{provider.url}</span></div>}
              </div>
            </div>
          )}

          {loomMeta && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70 mb-1">Loom Metadata</div>
              <div className="rounded border bg-input-bg p-3 space-y-0.5">
                {Object.entries(loomMeta).map(([k, v]) => (
                  <div key={k}>{k}: <span className="text-foreground">{String(v)}</span></div>
                ))}
              </div>
            </div>
          )}

          {metadataSlot}
        </CardContent>
      </Card>
    );
  }

  if (descriptorType === "MCP" || descriptors.mcp) {
    const mcp = descriptors.mcp as Record<string, unknown> | undefined;
    const serverRaw = (mcp?.server as Record<string, unknown>)?.inlineContent;
    const toolsRaw = (mcp?.tools as Record<string, unknown>)?.inlineContent;
    const server = tryParseJson(serverRaw) as Record<string, unknown> | null;
    const toolsParsed = tryParseJson(toolsRaw);
    const tools = (Array.isArray(toolsParsed) ? toolsParsed : Array.isArray((toolsParsed as Record<string, unknown>)?.tools) ? (toolsParsed as Record<string, unknown>).tools : null) as Array<Record<string, unknown>> | null;

    return (
      <Card className="py-3 gap-1">
        <CardHeader className="gap-1 pb-3">
          <div className="text-sm font-medium">Descriptors</div>
        </CardHeader>
        <CardContent className="space-y-3 text-xs text-muted-foreground">
          {server && typeof server === "object" && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70 mb-1">Server</div>
              <div className="rounded border bg-input-bg p-3 space-y-0.5">
                <div>Name: <span className="text-foreground">{String(server.name ?? "")}</span></div>
                {server.description ? <div>Description: <span className="text-foreground">{String(server.description)}</span></div> : null}
                {(server.url || server.endpoint_url) ? <div>Endpoint: <span className="text-foreground">{String(server.url ?? server.endpoint_url)}</span></div> : null}
                {(server.transport || server.transport_type) ? <div>Transport: <span className="text-foreground">{String(server.transport ?? server.transport_type)}</span></div> : null}
                {server.version ? <div>Version: <span className="text-foreground">{String(server.version)}</span></div> : null}
                {server.protocolVersion ? <div>Protocol Version: <span className="text-foreground">{String(server.protocolVersion)}</span></div> : null}
              </div>
            </div>
          )}

          {Array.isArray(tools) && tools.length > 0 && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70 mb-1">Tools ({tools.length})</div>
              <div className="space-y-1">
                {tools.map((tool, i) => (
                  <div key={String(tool.name ?? i)} className="rounded border bg-input-bg px-3 py-2">
                    <span className="font-medium text-foreground">{String(tool.name)}</span>
                    {tool.description ? <span className="ml-1">&mdash; {String(tool.description)}</span> : null}
                  </div>
                ))}
              </div>
            </div>
          )}

          {metadataSlot}
        </CardContent>
      </Card>
    );
  }

  // Fallback for CUSTOM or unknown types
  const customRaw = (descriptors.custom as Record<string, unknown>)?.inlineContent;
  const custom = tryParseJson(customRaw ?? descriptors) as Record<string, unknown> | null;

  if (custom && typeof custom === "object") {
    return (
      <Card className="py-3 gap-1">
        <CardHeader className="gap-1 pb-3">
          <div className="text-sm font-medium">Descriptors</div>
        </CardHeader>
        <CardContent className="space-y-3 text-xs text-muted-foreground">
          <div className="rounded border bg-input-bg p-3 space-y-0.5">
            {Object.entries(custom).map(([k, v]) => (
              <div key={k}>{k}: <span className="text-foreground">{typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}</span></div>
            ))}
          </div>
          {metadataSlot}
        </CardContent>
      </Card>
    );
  }

  return <p className="text-xs text-muted-foreground">No descriptors available.</p>;
}

const STATUS_SORT_ORDER: Record<string, number> = {
  DRAFT: 0,
  PENDING_APPROVAL: 1,
  APPROVED: 2,
  REJECTED: 3,
  DEPRECATED: 4,
};

function defaultSort(a: RegistryRecord, b: RegistryRecord): number {
  const sa = STATUS_SORT_ORDER[a.status] ?? 9;
  const sb = STATUS_SORT_ORDER[b.status] ?? 9;
  if (sa !== sb) return sa - sb;
  const ta = a.descriptor_type;
  const tb = b.descriptor_type;
  if (ta !== tb) return ta.localeCompare(tb);
  return (a.name ?? "").localeCompare(b.name ?? "");
}

interface RegistryPageProps {
  readOnly?: boolean;
  isEndUserRole?: boolean;
}

export function RegistryPage({ readOnly, isEndUserRole }: RegistryPageProps) {
  const { timezone } = useTimezone();
  const { records, loading, error, fetchRecords } = useRegistry();

  const [viewMode, setViewMode] = useState<"cards" | "table">("cards");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Array<Record<string, unknown>> | null>(null);
  const [searching, setSearching] = useState(false);
  const [tableCol, setTableCol] = useState<string>("status");
  const [tableDir, setTableDir] = useState<"asc" | "desc">("asc");
  const [cardSortDir, setCardSortDir] = useState<SortDirection>(loadSortDirection("registry-records") ?? "asc");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const toggleGroup = (group: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  const handleTableSort = (col: string) => {
    if (tableCol === col) {
      setTableDir(tableDir === "asc" ? "desc" : "asc");
    } else {
      setTableCol(col);
      setTableDir("asc");
    }
  };

  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [recordDetail, setRecordDetail] = useState<RegistryRecordDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Apply filters
  useEffect(() => {
    const params: { status?: string; descriptorType?: string } = {};
    if (statusFilter !== "all") params.status = statusFilter;
    if (typeFilter !== "all") params.descriptorType = typeFilter;
    // For end-user role, only show APPROVED records
    if (isEndUserRole) params.status = "APPROVED";
    void fetchRecords(params);
  }, [statusFilter, typeFilter, isEndUserRole, fetchRecords]);

  // Fetch detail when a record is selected
  useEffect(() => {
    if (!selectedRecordId) {
      setRecordDetail(null);
      return;
    }
    setLoadingDetail(true);
    registryApi.getRegistryRecord(selectedRecordId)
      .then(setRecordDetail)
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : "Failed to fetch record detail");
        setSelectedRecordId(null);
      })
      .finally(() => setLoadingDetail(false));
  }, [selectedRecordId]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    try {
      const result = await registryApi.searchRegistry(searchQuery.trim());
      setSearchResults(result.results);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Search failed");
    } finally {
      setSearching(false);
    }
  };

  const refreshDetail = async (recordId: string) => {
    try {
      const detail = await registryApi.getRegistryRecord(recordId);
      setRecordDetail(detail);
    } catch {
      // detail refresh is best-effort
    }
  };


  // Compute display records before any early returns so hooks are called consistently
  const displayRecords = searchResults !== null
    ? records.filter((r) => searchResults.some((sr) => (sr as Record<string, unknown>).record_id === r.record_id))
    : records;

  const sortedRecords = useMemo(() => [...displayRecords].sort(defaultSort), [displayRecords]);

  const STATUS_GROUPS: Array<{ key: string; label: string; statuses: string[] }> = [
    { key: "draft", label: "Draft", statuses: ["DRAFT"] },
    { key: "pending", label: "Pending", statuses: ["PENDING_APPROVAL"] },
    { key: "approved", label: "Approved", statuses: ["APPROVED"] },
    { key: "rejected", label: "Rejected", statuses: ["REJECTED", "DEPRECATED"] },
  ];

  const groupedRecords = useMemo(() => {
    return STATUS_GROUPS.map((g) => ({
      ...g,
      records: sortedRecords.filter((r) => g.statuses.includes(r.status)),
    }));
  }, [sortedRecords]);

  const goBackToList = () => {
    setSelectedRecordId(null);
    setRecordDetail(null);
  };

  // Detail view
  if (selectedRecordId) {
    return (
      <DetailErrorBoundary onBack={goBackToList}>
        <div className="space-y-6">
          <div>
            <Button
              variant="ghost"
              size="sm"
              onClick={goBackToList}
              className="mb-2"
            >
              &larr; Back to registry
            </Button>
            {loadingDetail || !recordDetail ? (
              <Skeleton className="h-64" />
            ) : (
            <div className="space-y-6">
              {/* Lifecycle Timeline */}
              <div className="rounded border bg-input-bg p-4 flex flex-col items-center gap-3">
                <LifecycleTimeline status={recordDetail.status} />
                {recordDetail.status_reason && (
                  <div className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">
                      {recordDetail.status === "APPROVED" ? "Approval Reason:" : recordDetail.status === "REJECTED" ? "Rejection Reason:" : "Status Reason:"}
                    </span> {recordDetail.status_reason}
                  </div>
                )}
              </div>

              {/* Header: name, badges, actions */}
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold">{recordDetail.name}</h2>
                <RegistryStatusBadge status={recordDetail.status} showUnregistered />
                <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                  {recordDetail.descriptor_type}
                </Badge>
                {!readOnly && (
                  <RegistryActions
                    resourceType={recordDetail.descriptor_type.toLowerCase() as "mcp" | "a2a" | "agent"}
                    resourceId={0}
                    registryRecordId={recordDetail.record_id}
                    registryStatus={recordDetail.status}
                    onAction={() => { void fetchRecords(); void refreshDetail(recordDetail.record_id); }}
                  />
                )}
              </div>

              {/* Descriptors + Record metadata */}
              <DescriptorView
                descriptors={recordDetail.descriptors}
                descriptorType={recordDetail.descriptor_type}
                metadataSlot={
                  <div>
                    <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70 mb-1">Record Metadata</div>
                    <div className="rounded border bg-input-bg p-3 space-y-0.5">
                      <div>Record ID: <span className="text-foreground">{recordDetail.record_id}</span></div>
                      <div>Descriptor Type: <span className="text-foreground">{recordDetail.descriptor_type}</span></div>
                      {recordDetail.record_version && (
                        <div>Version: <span className="text-foreground">{recordDetail.record_version}</span></div>
                      )}
                      {recordDetail.created_at && (
                        <div>Created: <span className="text-foreground">{formatTimestamp(recordDetail.created_at, timezone)}</span></div>
                      )}
                      {recordDetail.updated_at && (
                        <div>Updated: <span className="text-foreground">{formatTimestamp(recordDetail.updated_at, timezone)}</span></div>
                      )}
                    </div>
                  </div>
                }
              />
            </div>
          )}
        </div>
      </div>
      </DetailErrorBoundary>
    );
  }

  // List view
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">Agent Registry</h2>
          <p className="text-sm text-muted-foreground">
            Browse and manage registered MCP servers and A2A agents.
          </p>
        </div>
        <div className="flex rounded-md border text-sm shrink-0" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "cards"}
            className={`px-2 py-1 rounded-l-md transition-colors ${viewMode === "cards" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
            onClick={() => setViewMode("cards")}
            title="Card view"
          >
            <LayoutGrid className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "table"}
            className={`px-2 py-1 rounded-r-md transition-colors ${viewMode === "table" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
            onClick={() => setViewMode("table")}
            title="Table view"
          >
            <TableIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        {!isEndUserRole && (
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-8 w-40 text-xs">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              <SelectItem value="DRAFT">Draft</SelectItem>
              <SelectItem value="PENDING_APPROVAL">Pending Approval</SelectItem>
              <SelectItem value="APPROVED">Approved</SelectItem>
              <SelectItem value="REJECTED">Rejected</SelectItem>
              <SelectItem value="DEPRECATED">Deprecated</SelectItem>
            </SelectContent>
          </Select>
        )}

        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="h-8 w-32 text-xs">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="mcp">MCP</SelectItem>
            <SelectItem value="a2a">A2A</SelectItem>
          </SelectContent>
        </Select>

        <div className="flex items-center gap-1 flex-1 max-w-sm">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleSearch(); }}
              placeholder="Search registry..."
              className="h-8 w-full rounded border bg-input-bg pl-7 pr-2 text-xs"
            />
          </div>
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => void handleSearch()} disabled={searching}>
            {searching ? "..." : "Search"}
          </Button>
          {searchResults !== null && (
            <Button
              size="sm"
              variant="ghost"
              className="h-8 text-xs"
              onClick={() => { setSearchResults(null); setSearchQuery(""); }}
            >
              Clear
            </Button>
          )}
        </div>
      </div>

      {error && (
        <p className="text-sm text-destructive">{error}</p>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : sortedRecords.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8">
          {searchResults !== null ? "No matching records found." : "No registry records found."}
        </p>
      ) : (
        <div className="space-y-4">
          {groupedRecords.map(({ key, label, records: groupRecords }) => {
            if (groupRecords.length === 0) return null;
            const collapsed = collapsedGroups.has(key);
            return (
              <div key={key} className="space-y-2">
                <button
                  type="button"
                  onClick={() => toggleGroup(key)}
                  className="flex items-center gap-1 text-xs font-medium text-muted-foreground uppercase tracking-wide hover:text-foreground"
                >
                  {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                  {label} ({groupRecords.length})
                </button>

                {!collapsed && (viewMode === "cards" ? (
                  <SortableCardGrid
                    items={groupRecords}
                    getId={(r) => r.record_id}
                    getName={(r) => `${STATUS_SORT_ORDER[r.status] ?? 9}_${r.descriptor_type}_${r.name}`}
                    storageKey={`registry-records-${key}`}
                    sortDirection={cardSortDir}
                    onSortDirectionChange={(d) => { if (d) { setCardSortDir(d); saveSortDirection("registry-records", d); } }}
                    renderItem={(record) => (
                      <Card
                        className="cursor-pointer transition-colors hover:bg-accent/50 py-3 gap-1"
                        onClick={() => setSelectedRecordId(record.record_id)}
                      >
                        <CardHeader className="gap-1 pb-2">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 min-w-0">
                              <div className="text-sm font-medium truncate" title={record.name}>
                                {record.name}
                              </div>
                              <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0">
                                {record.descriptor_type}
                              </Badge>
                              <RegistryStatusBadge status={record.status} showUnregistered />
                            </div>
                          </div>
                        </CardHeader>
                        <CardContent className="text-xs text-muted-foreground">
                          <div className="rounded border bg-input-bg p-3 space-y-0.5">
                            {record.description && (
                              <div className="truncate" title={record.description}>
                                {record.description}
                              </div>
                            )}
                            {record.created_at && (
                              <div><span className="text-muted-foreground/70">Created:</span> {formatTimestamp(record.created_at, timezone)}</div>
                            )}
                            {record.updated_at && (
                              <div><span className="text-muted-foreground/70">Updated:</span> {formatTimestamp(record.updated_at, timezone)}</div>
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
                          <SortableTableHead column="name" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[20%]">Name</SortableTableHead>
                          <SortableTableHead column="status" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[10%]">Status</SortableTableHead>
                          <SortableTableHead column="type" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[10%]">Type</SortableTableHead>
                          <SortableTableHead column="description" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[40%]">Description</SortableTableHead>
                          <SortableTableHead column="created" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[20%]">Created</SortableTableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {sortRows(groupRecords, tableCol, tableDir, {
                          name: (r) => r.name ?? "",
                          status: (r) => STATUS_SORT_ORDER[r.status] ?? 9,
                          type: (r) => r.descriptor_type ?? "",
                          description: (r) => r.description ?? "",
                          created: (r) => r.created_at ?? "",
                        }).map((record) => (
                          <TableRow
                            key={record.record_id}
                            className="bg-input-bg hover:bg-input-bg/80 cursor-pointer"
                            onClick={() => setSelectedRecordId(record.record_id)}
                          >
                            <TableCell className="font-medium text-sm truncate">
                              {record.name}
                            </TableCell>
                            <TableCell>
                              <RegistryStatusBadge status={record.status} showUnregistered />
                            </TableCell>
                            <TableCell>
                              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                                {record.descriptor_type}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground truncate" title={record.description ?? ""}>
                              {record.description ?? "\u2014"}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {record.created_at ? formatTimestamp(record.created_at, timezone) : "\u2014"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
