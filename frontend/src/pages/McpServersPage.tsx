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
import { useMcpServers } from "@/hooks/useMcpServers";
import { McpServerForm } from "@/components/McpServerForm";
import { McpToolList } from "@/components/McpToolList";
import { McpAccessControl } from "@/components/McpAccessControl";
import { setUserApiKey, getUserApiKeyStatus, deleteUserApiKey } from "@/api/mcp";
import { Input } from "@/components/ui/input";
import { SortableCardGrid, SortButton, loadSortDirection, toggleSortDirection, saveSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import { SortableTableHead, sortRows } from "@/components/SortableTableHead";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import { RegistryActions } from "@/components/RegistryActions";
import type { McpServer, McpServerCreateRequest, AgentResponse } from "@/api/types";

interface McpServersPageProps {
  viewMode: "cards" | "table";
  onViewModeChange: (mode: "cards" | "table") => void;
  readOnly?: boolean;
  initialSelectedId?: number | null;
  agents?: AgentResponse[];
  onCountChange?: (count: number) => void;
}

function mcpHealth(status: McpServer["status"]): { label: string; variant: BadgeVariant } {
  switch (status) {
    case "active": return { label: "reachable", variant: "success" };
    case "error": return { label: "unreachable", variant: "destructive" };
    default: return { label: "inactive", variant: "neutral" };
  }
}

function transportLabel(t: McpServer["transport_type"]): string {
  return t === "streamable_http" ? "Streamable HTTP" : "SSE";
}

function mcpAuthLabel(t: McpServer["auth_type"]): string {
  return t === "oauth2" ? "OAuth2" : t === "api_key" ? "API Key" : "None";
}

export function McpServersPage({ viewMode, onViewModeChange, readOnly, initialSelectedId, agents = [], onCountChange }: McpServersPageProps) {
  const { timezone } = useTimezone();
  const { user, browserSessionId } = useAuth();
  const { servers, loading, fetchServers, createServer, updateServer, deleteServer } = useMcpServers();
  const [showAddForm, setShowAddForm] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState<number | null>(initialSelectedId ?? null);
  const [detailTab, setDetailTab] = useState<"tools" | "access" | "api-key">("tools");
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<number | null>(null);
  const [editingServer, setEditingServer] = useState<McpServer | null>(null);
  const [registryEnabled, setRegistryEnabled] = useState(false);

  useEffect(() => {
    getRegistryConfig().then((c) => setRegistryEnabled(c.enabled)).catch(() => {});
  }, []);

  useEffect(() => {
    onCountChange?.(servers.length);
  }, [servers.length, onCountChange]);

  const [cardSortDir, setCardSortDir] = useState<SortDirection>(() => loadSortDirection("mcp-servers"));
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

  const selectedServer = servers.find((s) => s.id === selectedServerId) ?? null;

  const dependentsOf = (serverName: string) => agents.filter((a) => a.mcp_names?.includes(serverName));

  const handleCreate = async (data: McpServerCreateRequest) => {
    try {
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'mcp', 'add_server', data.name);
      await createServer(data);
      setShowAddForm(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create server");
    }
  };

  const handleUpdate = async (data: McpServerCreateRequest) => {
    if (!editingServer) return;
    try {
      await updateServer(editingServer.id, data);
      setEditingServer(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update server");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const serverName = servers.find(s => s.id === id)?.name ?? String(id);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'mcp', 'delete_server', serverName);
      await deleteServer(id);
      setConfirmingDeleteId(null);
      if (selectedServerId === id) setSelectedServerId(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete server");
    }
  };

  if (selectedServer) {
    const health = mcpHealth(selectedServer.status);
    const dependents = dependentsOf(selectedServer.name);
    return (
      <Tabs key={selectedServer.id} value={detailTab} onValueChange={(v) => setDetailTab(v as typeof detailTab)} className="gap-0">
        <div className="flex flex-col gap-4 rounded-t-xl border bg-card px-6 pt-5">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <button type="button" onClick={() => { setSelectedServerId(null); setEditingServer(null); }} className="hover:text-foreground">Integrations</button>
            <span>/</span>
            <button type="button" onClick={() => { setSelectedServerId(null); setEditingServer(null); }} className="hover:text-foreground">MCP servers</button>
            <span>/</span>
            <span className="font-mono text-foreground">{selectedServer.name}</span>
          </div>
          <div className="flex items-start gap-4">
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="truncate font-mono text-2xl font-semibold tracking-tight">{selectedServer.name}</h1>
                <RegistryStatusBadge status={selectedServer.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                <StatusPill label={health.label} variant={health.variant} />
              </div>
              <div className="flex items-center gap-1.5 text-[13.5px] text-muted-foreground">
                <span className="max-w-xl truncate">{selectedServer.description ?? <span className="italic">No description set.</span>}</span>
                {!readOnly && (
                  <button type="button" onClick={() => setEditingServer(selectedServer)} className="shrink-0 text-[11.5px] text-primary hover:underline">
                    Edit
                  </button>
                )}
              </div>
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-2">
              {!readOnly && registryEnabled && (
                <RegistryActions
                  resourceType="mcp"
                  resourceId={selectedServer.id}
                  registryRecordId={selectedServer.registry_record_id}
                  registryStatus={selectedServer.registry_status}
                  onAction={() => void fetchServers()}
                />
              )}
              {!readOnly && (
                <button
                  type="button"
                  onClick={() => setConfirmingDeleteId(selectedServer.id)}
                  className="text-muted-foreground/60 transition-colors hover:text-destructive"
                  title="Delete server"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
          <TabsList variant="line" className="h-auto justify-start gap-5 rounded-none bg-transparent p-0">
            <TabsTrigger value="tools" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">Tools</TabsTrigger>
            <TabsTrigger value="access" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">Access</TabsTrigger>
            {selectedServer.auth_type === "api_key" && (
              <TabsTrigger value="api-key" className="rounded-none px-0.5 pb-2.5 text-[13.5px] font-medium data-[state=active]:shadow-none">API Key</TabsTrigger>
            )}
          </TabsList>
        </div>

        {editingServer && (
          <Card className="mt-4">
            <CardContent className="pt-4">
              <McpServerForm
                onSubmit={handleUpdate}
                onCancel={() => setEditingServer(null)}
                initialData={{
                  id: editingServer.id,
                  name: editingServer.name,
                  description: editingServer.description ?? undefined,
                  endpoint_url: editingServer.endpoint_url,
                  transport_type: editingServer.transport_type,
                  auth_type: editingServer.auth_type,
                  oauth2_well_known_url: editingServer.oauth2_well_known_url ?? undefined,
                  oauth2_client_id: editingServer.oauth2_client_id ?? undefined,
                  oauth2_scopes: editingServer.oauth2_scopes ?? undefined,
                  api_key_header_name: editingServer.api_key_header_name ?? undefined,
                  delegation_mode: editingServer.delegation_mode ?? undefined,
                  obo_grant_type: editingServer.obo_grant_type ?? undefined,
                  supports_elicitation: editingServer.supports_elicitation,
                }}
              />
            </CardContent>
          </Card>
        )}

        {confirmingDeleteId === selectedServer.id && (
          <div className="mt-4 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm">
            <span>Delete <span className="font-mono">{selectedServer.name}</span>? This can't be undone.</span>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfirmingDeleteId(null)}>Cancel</Button>
              <Button size="sm" variant="destructive" onClick={() => void handleDelete(selectedServer.id)}>Delete</Button>
            </div>
          </div>
        )}

        <TabsContent value="tools" className="grid grid-cols-1 gap-4 pt-4 lg:grid-cols-[1fr_320px]">
          <McpToolList serverId={selectedServer.id} readOnly={readOnly} />
          <div className="flex flex-col gap-3.5">
            <Card className="gap-3.5 py-4">
              <CardContent className="flex flex-col gap-3.5">
                <span className="text-[13px] font-semibold">Connection</span>
                <CopyField label="Endpoint" value={selectedServer.endpoint_url} />
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Transport</span>
                  <span className="font-mono text-xs">{transportLabel(selectedServer.transport_type)}</span>
                </div>
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Auth</span>
                  <span className="font-mono text-xs">{mcpAuthLabel(selectedServer.auth_type)}</span>
                </div>
                <div className="flex items-center justify-between gap-2.5">
                  <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Elicitation</span>
                  <span className="font-mono text-xs">{selectedServer.supports_elicitation ? "Supported" : "Not supported"}</span>
                </div>
                {selectedServer.created_at && (
                  <div className="flex items-center justify-between gap-2.5">
                    <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Created</span>
                    <span className="font-mono text-xs">{formatTimestamp(selectedServer.created_at, timezone)}</span>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="gap-2.5 py-4">
              <CardHeader className="px-[18px]">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-[13px] font-semibold">Used by</CardTitle>
                  <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-mono">{dependents.length}</Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-1.5 px-[18px]">
                {dependents.length === 0 ? (
                  <p className="rounded-md border border-dashed px-3 py-2.5 text-[11.5px] text-muted-foreground">No agents reference this server yet.</p>
                ) : (
                  <>
                    {dependents.map((a) => (
                      <div key={a.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 font-mono text-[11.5px]">
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDotClass(statusVariant(a.status))}`} />
                        <span className="truncate">{a.name ?? a.runtime_id}</span>
                      </div>
                    ))}
                    <p className="text-[11px] text-muted-foreground">Deleting this server may break {dependents.length === 1 ? "this agent" : "these agents"}.</p>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
        <TabsContent value="access" className="pt-4">
          <McpAccessControl serverId={selectedServer.id} readOnly={readOnly} />
        </TabsContent>
        <TabsContent value="api-key" className="pt-4">
          <McpUserApiKeyPanel serverId={selectedServer.id} hasAdminApiKey={selectedServer.has_admin_api_key} />
        </TabsContent>
      </Tabs>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">MCP servers</h2>
          <p className="text-sm text-muted-foreground">
            Tool servers available to agents on this platform.
          </p>
        </div>
        <ViewModeToggle viewMode={viewMode} onViewModeChange={onViewModeChange} />
      </div>

      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">Servers</h3>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <SortButton direction={cardSortDir} onClick={() => setCardSortDir(toggleSortDirection("mcp-servers", cardSortDir))} />
          {!readOnly && (
            <Button
              size="sm"
              onClick={() => setShowAddForm(!showAddForm)}
            >
              <Plus className="h-3.5 w-3.5 mr-1" />
              Add MCP Server
            </Button>
          )}
        </div>
      </div>

      {showAddForm && (
        <Card>
          <CardContent className="pt-4">
            <McpServerForm
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
      ) : servers.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8">
          No MCP servers registered yet. Add one above.
        </p>
      ) : viewMode === "cards" ? (
        <SortableCardGrid
          items={servers}
          getId={(s) => String(s.id)}
          getName={(s) => s.name}
          storageKey="mcp-servers"
          sortDirection={cardSortDir}
          onSortDirectionChange={(d) => { if (d) { setCardSortDir(d); saveSortDirection("mcp-servers", d); } }}
          renderItem={(server) => {
            const health = mcpHealth(server.status);
            const dependentCount = dependentsOf(server.name).length;
            return (
              <Card
                className="group relative flex h-full cursor-pointer flex-col gap-3.5 py-4 transition-colors hover:bg-accent/50"
                onClick={() => setSelectedServerId(server.id)}
              >
                <CardHeader className="gap-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="min-w-0 flex-1 truncate font-mono text-sm font-medium tracking-tight" title={server.name}>
                      {server.name}
                    </CardTitle>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <RegistryStatusBadge status={server.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setEditingServer(server); setSelectedServerId(server.id); }}
                          className="text-muted-foreground/50 opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100"
                          title="Edit server"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setConfirmingDeleteId(server.id); }}
                          className="text-muted-foreground/50 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100"
                          title="Delete server"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col gap-3.5">
                  <div onClick={(e) => e.stopPropagation()}>
                    <CopyField value={server.endpoint_url} />
                  </div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2.5 text-xs">
                    <div className="flex flex-col gap-0.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Transport</span>
                      <span className="truncate">{transportLabel(server.transport_type)}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Auth</span>
                      <span className="truncate">{mcpAuthLabel(server.auth_type)}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground/80 uppercase">Elicitation</span>
                      <span className="truncate">{server.supports_elicitation ? "Supported" : "Not supported"}</span>
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
                  {confirmingDeleteId === server.id && (
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
                          onClick={() => void handleDelete(server.id)}
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
                <SortableTableHead column="endpoint" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[38%]">Endpoint</SortableTableHead>
                <SortableTableHead column="transport" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[10%]">Transport</SortableTableHead>
                <SortableTableHead column="auth" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[8%]">Auth</SortableTableHead>
                <SortableTableHead column="registry" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[10%]">Registry</SortableTableHead>
                <SortableTableHead column="created" activeColumn={tableCol} direction={tableDir} onSort={handleTableSort} className="w-[16%]">Created</SortableTableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortRows(servers, tableCol, tableDir, {
                name: (s) => s.name,
                endpoint: (s) => s.endpoint_url,
                transport: (s) => s.transport_type,
                auth: (s) => s.auth_type,
                registry: (s) => s.registry_status ?? "",
                created: (s) => s.created_at ?? "",
              }).map((server) => (
                <TableRow
                  key={server.id}
                  className="bg-input-bg hover:bg-input-bg/80 cursor-pointer"
                  onClick={() => setSelectedServerId(server.id)}
                >
                  <TableCell className="font-medium text-sm">{server.name}</TableCell>
                  <TableCell className="text-xs text-muted-foreground truncate">{server.endpoint_url}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{transportLabel(server.transport_type)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{mcpAuthLabel(server.auth_type)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    <RegistryStatusBadge status={server.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatTimestamp(server.created_at, timezone)}
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

function McpUserApiKeyPanel({ serverId, hasAdminApiKey }: { serverId: number; hasAdminApiKey: boolean }) {
  const [apiKeyValue, setApiKeyValue] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getUserApiKeyStatus(serverId)
      .then((res) => setHasKey(res.has_user_api_key))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [serverId]);

  const handleSave = async () => {
    if (!apiKeyValue.trim()) return;
    try {
      const res = await setUserApiKey(serverId, apiKeyValue.trim());
      setHasKey(res.has_user_api_key);
      setApiKeyValue("");
      toast.success("API key saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save API key");
    }
  };

  const handleDelete = async () => {
    try {
      const res = await deleteUserApiKey(serverId);
      setHasKey(res.has_user_api_key);
      toast.success("API key removed");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to remove API key");
    }
  };

  if (loading) {
    return <Skeleton className="h-20" />;
  }

  return (
    <Card>
      <CardContent className="pt-4 space-y-4">
        <div className="text-sm space-y-1">
          <div>
            <span className="font-medium">Admin Key:</span>{" "}
            {hasAdminApiKey ? (
              <span className="text-green-600 dark:text-green-400">Configured</span>
            ) : (
              <span className="text-muted-foreground">Not configured</span>
            )}
          </div>
          <div>
            <span className="font-medium">User Key:</span>{" "}
            {hasKey ? (
              <span className="text-green-600 dark:text-green-400">Configured</span>
            ) : (
              <span className="text-muted-foreground">Not configured</span>
            )}
          </div>
        </div>
        <div className="flex items-end gap-2">
          <div className="flex-1 min-w-0">
            <label className="text-xs text-muted-foreground">{hasKey ? "Update User API Key" : "Set User API Key"}</label>
            <Input
              type="password"
              value={apiKeyValue}
              onChange={(e) => setApiKeyValue(e.target.value)}
              placeholder="Enter your API key"
            />
          </div>
          <Button size="sm" onClick={handleSave} disabled={!apiKeyValue.trim()}>
            Save
          </Button>
          {hasKey && (
            <Button size="sm" variant="destructive" onClick={handleDelete}>
              Delete
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
