import { useState, useEffect } from "react";
import { getRegistryConfig } from "@/api/settings";
import { LayoutGrid, TableIcon, Plus, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
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
import type { McpServer, McpServerCreateRequest } from "@/api/types";

interface McpServersPageProps {
  viewMode: "cards" | "table";
  onViewModeChange: (mode: "cards" | "table") => void;
  readOnly?: boolean;
  initialSelectedId?: number | null;
}

export function McpServersPage({ viewMode, onViewModeChange, readOnly, initialSelectedId }: McpServersPageProps) {
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
    return (
      <div className="space-y-6">
        <div>
          <Button variant="ghost" size="sm" onClick={() => { setSelectedServerId(null); setEditingServer(null); }} className="mb-2">
            &larr; Back to servers
          </Button>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold">{selectedServer.name}</h2>
            <RegistryStatusBadge status={selectedServer.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
            {!readOnly && (
              <button
                type="button"
                onClick={() => setEditingServer(selectedServer)}
                className="text-muted-foreground/50 hover:text-foreground transition-colors"
                title="Edit server"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
            {!readOnly && registryEnabled && (
              <RegistryActions
                resourceType="mcp"
                resourceId={selectedServer.id}
                registryRecordId={selectedServer.registry_record_id}
                registryStatus={selectedServer.registry_status}
                onAction={() => void fetchServers()}
              />
            )}
          </div>
          {selectedServer.description && <p className="text-sm text-muted-foreground">{selectedServer.description}</p>}
        </div>

        {editingServer && (
          <Card>
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

        <div className="flex rounded-md border text-sm w-fit" role="tablist">
          {(["tools", "access"] as const).map((tab, idx) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={detailTab === tab}
              className={`px-4 py-1.5 transition-colors ${
                idx === 0 ? "rounded-l-md" : ""
              } ${
                idx === 1 && selectedServer.auth_type !== "api_key" ? "rounded-r-md" : ""
              } ${
                detailTab === tab
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-accent"
              }`}
              onClick={() => setDetailTab(tab)}
            >
              {tab === "tools" ? "Tools" : "Access"}
            </button>
          ))}
          {selectedServer.auth_type === "api_key" && (
            <button
              type="button"
              role="tab"
              aria-selected={detailTab === "api-key"}
              className={`px-4 py-1.5 transition-colors rounded-r-md ${
                detailTab === "api-key"
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-accent"
              }`}
              onClick={() => setDetailTab("api-key")}
            >
              API Key
            </button>
          )}
        </div>

        {detailTab === "tools" && <McpToolList serverId={selectedServer.id} readOnly={readOnly} />}
        {detailTab === "access" && <McpAccessControl serverId={selectedServer.id} readOnly={readOnly} />}
        {detailTab === "api-key" && selectedServer && (
          <McpUserApiKeyPanel serverId={selectedServer.id} hasAdminApiKey={selectedServer.has_admin_api_key} />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">MCP Server Administration</h2>
          <p className="text-sm text-muted-foreground">
            Register and manage Model Context Protocol servers for agent tool access.
          </p>
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

      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">Servers</h3>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <SortButton direction={cardSortDir} onClick={() => setCardSortDir(toggleSortDirection("mcp-servers", cardSortDir))} />
          {!readOnly && (
            <Button
              size="sm"
              variant="outline"
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
          renderItem={(server) => (
            <Card
              className="relative cursor-pointer transition-colors hover:bg-accent/50 py-3 gap-1"
              onClick={() => setSelectedServerId(server.id)}
            >
              <CardHeader className="gap-1 pb-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="text-sm font-medium truncate min-w-0" title={server.name}>
                      {server.name}
                    </div>
                    <RegistryStatusBadge status={server.registry_status} showUnregistered={registryEnabled} registryEnabled={registryEnabled} />
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {!readOnly && (
                      <>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setEditingServer(server); setSelectedServerId(server.id); }}
                          className="text-muted-foreground/50 hover:text-foreground transition-colors"
                          title="Edit server"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setConfirmingDeleteId(server.id); }}
                          className="text-muted-foreground/50 hover:text-destructive transition-colors"
                          title="Delete server"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-2 text-xs text-muted-foreground">
                <div className="rounded border bg-input-bg p-3 space-y-0.5">
                  <div className="truncate" title={server.endpoint_url}><span className="text-muted-foreground/70">Endpoint:</span> {server.endpoint_url}</div>
                  <div><span className="text-muted-foreground/70">Transport:</span> {server.transport_type === "streamable_http" ? "Streamable HTTP" : "SSE"}</div>
                  <div><span className="text-muted-foreground/70">Authentication:</span> {server.auth_type === "oauth2" ? "OAuth2" : server.auth_type === "api_key" ? "API Key" : "None"}</div>
                  <div><span className="text-muted-foreground/70">Elicitation:</span> {server.supports_elicitation ? "Supported" : "Not supported"}</div>
                  {server.created_at && (
                    <div><span className="text-muted-foreground/70">Created:</span> {formatTimestamp(server.created_at, timezone)}</div>
                  )}
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
          )}
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
                  <TableCell className="text-xs text-muted-foreground">{server.transport_type === "streamable_http" ? "Streamable HTTP" : "SSE"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{server.auth_type === "oauth2" ? "OAuth2" : server.auth_type === "api_key" ? "API Key" : "None"}</TableCell>
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
