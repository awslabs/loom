import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/api/client";

type Props = {
  canRead: boolean;
  canWrite: boolean;
};

type HubMint = {
  hub_session_token: string;
  hub_session_id: string;
  mcp_hub_url: string;
  expires_at: string;
  contract_version: string;
};

type McpClientGrant = {
  server_id: number;
  access_level: "all_tools" | "selected_tools";
  tool_names: string[];
};

type McpHubClient = {
  slug: string;
  display_name: string;
  declared_name: string;
  declared_version: string;
  declared_family: string;
  status: "discovered" | "enabled" | "disabled";
  allowed_groups: string[];
  grants: McpClientGrant[];
  first_seen_at?: string;
  last_seen_at?: string;
};

type McpServer = {
  id: number;
  name: string;
  status: string;
  template_id?: string | null;
};

type McpTool = {
  id?: number;
  tool_name: string;
};

type ServerAccessRule = {
  server_id: number;
  enabled: boolean;
  access_level: "all_tools" | "selected_tools";
  allowed_tool_names: string[];
};

/**
 * Ops surface for local-runtime backends.
 * MCP Client grants mirror Integrations → MCP access control (servers × tools).
 */
export function LocalRuntimePage({ canRead, canWrite }: Props) {
  const [mint, setMint] = useState<HubMint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [clients, setClients] = useState<McpHubClient[]>([]);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [rules, setRules] = useState<ServerAccessRule[]>([]);
  const [toolsByServer, setToolsByServer] = useState<Record<number, McpTool[]>>({});
  const [savingGrants, setSavingGrants] = useState(false);

  const selected = clients.find((c) => c.slug === selectedSlug) || null;

  const refreshClients = useCallback(async () => {
    const data = await apiFetch<{ clients: McpHubClient[] }>("/api/ext/local-runtime/mcp-clients");
    setClients(data.clients || []);
  }, []);

  const loadTools = useCallback(async (serverId: number) => {
    setToolsByServer((prev) => {
      if (prev[serverId]) return prev;
      void apiFetch<McpTool[]>(`/api/mcp/servers/${serverId}/tools`)
        .then((tools) => {
          setToolsByServer((p) => (p[serverId] ? p : { ...p, [serverId]: tools || [] }));
        })
        .catch(() => undefined);
      return prev;
    });
  }, []);

  useEffect(() => {
    if (!canRead) return;
    void (async () => {
      try {
        await refreshClients();
        const list = await apiFetch<McpServer[]>("/api/mcp/servers");
        setServers((list || []).filter((s) => s.status === "active"));
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : "Failed to load Hub clients");
      }
    })();
  }, [canRead, refreshClients]);

  useEffect(() => {
    if (!selected) {
      setRules([]);
      return;
    }
    const grantMap = new Map<number, McpClientGrant>();
    for (const g of selected.grants || []) {
      grantMap.set(g.server_id, g);
    }
    setRules(
      servers.map((s) => {
        const existing = grantMap.get(s.id);
        return {
          server_id: s.id,
          enabled: !!existing,
          access_level: existing?.access_level ?? "all_tools",
          allowed_tool_names: existing?.tool_names ?? [],
        };
      }),
    );
  }, [selected, servers]);

  useEffect(() => {
    if (!selected) return;
    for (const rule of rules) {
      if (rule.enabled && rule.access_level === "selected_tools") {
        void loadTools(rule.server_id).catch(() => undefined);
      }
    }
  }, [rules, selected, loadTools]);

  async function mintHubSession() {
    setBusy(true);
    setError(null);
    try {
      const data = await apiFetch<HubMint>("/api/mcp/hub/sessions", {
        method: "POST",
        body: JSON.stringify({ client_label: "local-runtime-ui" }),
      });
      setMint(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Mint failed (${err.status}): ${err.detail.slice(0, 200)}`);
      } else {
        setError(err instanceof Error ? err.message : "Mint failed");
      }
    } finally {
      setBusy(false);
    }
  }

  async function setClientStatus(slug: string, next: "enabled" | "disabled") {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/ext/local-runtime/mcp-clients/${encodeURIComponent(slug)}`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      await refreshClients();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to update client");
    } finally {
      setBusy(false);
    }
  }

  async function deleteClient(slug: string) {
    if (!window.confirm(`Delete MCP client "${slug}"?`)) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/ext/local-runtime/mcp-clients/${encodeURIComponent(slug)}`, {
        method: "DELETE",
      });
      if (selectedSlug === slug) setSelectedSlug(null);
      await refreshClients();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to delete client");
    } finally {
      setBusy(false);
    }
  }

  function updateRule(serverId: number, updates: Partial<ServerAccessRule>) {
    setRules((prev) =>
      prev.map((r) => (r.server_id === serverId ? { ...r, ...updates } : r)),
    );
  }

  function toggleTool(serverId: number, toolName: string) {
    setRules((prev) =>
      prev.map((r) => {
        if (r.server_id !== serverId) return r;
        const names = r.allowed_tool_names.includes(toolName)
          ? r.allowed_tool_names.filter((n) => n !== toolName)
          : [...r.allowed_tool_names, toolName];
        return { ...r, allowed_tool_names: names };
      }),
    );
  }

  async function saveGrants() {
    if (!selected) return;
    setSavingGrants(true);
    setError(null);
    try {
      const grants: McpClientGrant[] = rules
        .filter((r) => r.enabled)
        .map((r) => ({
          server_id: r.server_id,
          access_level: r.access_level,
          tool_names: r.access_level === "selected_tools" ? r.allowed_tool_names : [],
        }));
      await apiFetch(`/api/ext/local-runtime/mcp-clients/${encodeURIComponent(selected.slug)}/grants`, {
        method: "PUT",
        body: JSON.stringify({ grants }),
      });
      if (selected.status !== "enabled" && grants.length > 0) {
        await apiFetch(`/api/ext/local-runtime/mcp-clients/${encodeURIComponent(selected.slug)}`, {
          method: "PATCH",
          body: JSON.stringify({ status: "enabled" }),
        });
      }
      await refreshClients();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to save grants");
    } finally {
      setSavingGrants(false);
    }
  }

  function serverLabel(serverId: number): string {
    const s = servers.find((x) => x.id === serverId);
    if (!s) return `Server #${serverId}`;
    const suffix = s.template_id ? ` · ${s.template_id}` : "";
    return `${s.name}${suffix}`;
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Local runtime</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Extension plugin (ADR 0006). MCP Hub discovers IDE clients on connect; grant
          catalog servers the same way as Integrations → MCP access control.
        </p>
      </div>

      <section className="rounded-lg border bg-card p-4 space-y-3 text-sm">
        <h2 className="font-medium">MCP Hub session</h2>
        <p className="text-muted-foreground">
          Mint after IdP login, put the URL + Bearer in your IDE MCP config, connect once
          so the Hub registers the client, then configure server access below.
        </p>
        {canRead ? (
          <button
            type="button"
            className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-primary-foreground text-sm disabled:opacity-50"
            disabled={busy}
            onClick={() => void mintHubSession()}
          >
            {busy ? "Minting…" : "Mint Hub session"}
          </button>
        ) : (
          <p className="text-muted-foreground">Requires mcp:read.</p>
        )}
        {error ? <p className="text-destructive text-xs">{error}</p> : null}
        {mint ? (
          <div className="space-y-2 rounded-md bg-muted/40 p-3 font-mono text-xs break-all">
            <div>
              <div className="text-muted-foreground mb-1">URL</div>
              <div>{mint.mcp_hub_url}</div>
            </div>
            <div>
              <div className="text-muted-foreground mb-1">Bearer (Hub session)</div>
              <div>{mint.hub_session_token}</div>
            </div>
            <div className="text-muted-foreground">
              expires {mint.expires_at} · {mint.contract_version}
            </div>
          </div>
        ) : null}
      </section>

      <section className="rounded-lg border bg-card p-4 space-y-3 text-sm">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-medium">MCP Clients</h2>
          <button
            type="button"
            className="text-xs text-muted-foreground underline disabled:opacity-50"
            disabled={busy || !canRead}
            onClick={() => void refreshClients().catch((e) => setError(String(e)))}
          >
            Refresh
          </button>
        </div>
        <p className="text-muted-foreground text-xs">
          Discovered on IDE <code className="text-xs">initialize</code>. Select a client to
          grant MCP servers (deny by default until checked).
        </p>
        {clients.length === 0 ? (
          <p className="text-muted-foreground text-xs">No clients discovered yet.</p>
        ) : (
          <ul className="space-y-2">
            {clients.map((c) => (
              <li
                key={c.slug}
                className={`rounded-md border px-3 py-2 space-y-1 ${
                  selectedSlug === c.slug ? "border-primary bg-muted/30" : ""
                }`}
              >
                <button
                  type="button"
                  className="text-left w-full"
                  onClick={() => setSelectedSlug(c.slug)}
                >
                  <div className="font-medium">
                    {c.display_name || c.slug}{" "}
                    <span className="text-muted-foreground font-normal">({c.slug})</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    status={c.status} · family={c.declared_family} · servers=
                    {(c.grants || []).length}
                  </div>
                </button>
                {canWrite ? (
                  <div className="flex flex-wrap gap-3 pt-1 text-xs">
                    <button
                      type="button"
                      className="underline disabled:opacity-50"
                      disabled={busy || c.status === "enabled"}
                      onClick={() => void setClientStatus(c.slug, "enabled")}
                    >
                      Enable
                    </button>
                    <button
                      type="button"
                      className="underline disabled:opacity-50"
                      disabled={busy || c.status === "disabled"}
                      onClick={() => void setClientStatus(c.slug, "disabled")}
                    >
                      Disable
                    </button>
                    <button
                      type="button"
                      className="underline text-destructive disabled:opacity-50"
                      disabled={busy}
                      onClick={() => void deleteClient(c.slug)}
                    >
                      Delete
                    </button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {selected ? (
          <div className="rounded-md border bg-muted/20 p-3 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-medium">Server access — {selected.display_name || selected.slug}</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Same pattern as Integrations → MCP: check a server, then All Tools or
                  Selected Tools. Uncheck to revoke.
                </p>
              </div>
              {canWrite ? (
                <button
                  type="button"
                  className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-primary-foreground text-xs disabled:opacity-50"
                  disabled={savingGrants}
                  onClick={() => void saveGrants()}
                >
                  {savingGrants ? "Saving…" : "Save"}
                </button>
              ) : null}
            </div>

            {servers.length === 0 ? (
              <p className="text-xs text-muted-foreground">No active MCP servers in the catalog.</p>
            ) : (
              <div className="space-y-2">
                {rules.map((rule) => {
                  const tools = toolsByServer[rule.server_id] || [];
                  return (
                    <div key={rule.server_id} className="rounded border bg-background p-3 space-y-2">
                      <label className="flex items-center gap-2 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={rule.enabled}
                          disabled={!canWrite}
                          onChange={(e) => {
                            updateRule(rule.server_id, { enabled: e.target.checked });
                            if (e.target.checked && rule.access_level === "selected_tools") {
                              void loadTools(rule.server_id).catch(() => undefined);
                            }
                          }}
                          className="h-3.5 w-3.5"
                        />
                        <span className="text-sm font-medium">{serverLabel(rule.server_id)}</span>
                      </label>

                      {rule.enabled ? (
                        <div className="pl-6 space-y-2">
                          <div className="flex items-center gap-4">
                            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                              <input
                                type="radio"
                                checked={rule.access_level === "all_tools"}
                                disabled={!canWrite}
                                onChange={() => updateRule(rule.server_id, { access_level: "all_tools" })}
                                className="h-3 w-3"
                              />
                              All Tools
                            </label>
                            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                              <input
                                type="radio"
                                checked={rule.access_level === "selected_tools"}
                                disabled={!canWrite}
                                onChange={() => {
                                  updateRule(rule.server_id, { access_level: "selected_tools" });
                                  void loadTools(rule.server_id).catch(() => undefined);
                                }}
                                className="h-3 w-3"
                              />
                              Selected Tools
                            </label>
                          </div>

                          {rule.access_level === "selected_tools" ? (
                            <div className="flex flex-wrap gap-2">
                              {tools.length === 0 ? (
                                <span className="text-xs text-muted-foreground italic">
                                  No tools available. Refresh tools on the server in Integrations first.
                                </span>
                              ) : (
                                tools.map((tool) => (
                                  <label
                                    key={tool.tool_name}
                                    className="flex items-center gap-1.5 text-xs cursor-pointer"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={rule.allowed_tool_names.includes(tool.tool_name)}
                                      disabled={!canWrite}
                                      onChange={() => toggleTool(rule.server_id, tool.tool_name)}
                                      className="h-3 w-3"
                                    />
                                    {tool.tool_name}
                                  </label>
                                ))
                              )}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : null}
      </section>
    </div>
  );
}
