import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/api/client";

type Props = {
  canRead: boolean;
  canWrite: boolean;
};

type HubInfo = {
  mcp_hub_url: string;
  resource: string;
  auth: string;
  contract_version: string;
};

type McpClientGrant = {
  group?: string;
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
  agents_enabled?: boolean;
  allowed_groups?: string[];
  granted_profiles?: string[];
  grant_count?: number;
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

/** Full IdP profiles (GROUP_SCOPES); not short loom:group tags. */
const LOOM_PROFILES = [
  "g-users-demo",
  "g-users-test",
  "g-users-strategics",
  "g-admins-demo",
  "g-admins-mcp",
  "g-admins-security",
  "g-admins-memory",
  "g-admins-a2a",
  "g-admins-registry",
] as const;

const PROFILE_PLACEHOLDER = "";

function buildRulesFromGrants(
  grants: McpClientGrant[],
  servers: McpServer[],
): ServerAccessRule[] {
  const grantMap = new Map<number, McpClientGrant>();
  for (const g of grants) {
    const sid = Number(g.server_id);
    if (!Number.isFinite(sid)) continue;
    grantMap.set(sid, g);
  }
  const serverIds = new Set(servers.map((s) => s.id));
  const rows: ServerAccessRule[] = servers.map((s) => {
    const existing = grantMap.get(s.id);
    return {
      server_id: s.id,
      enabled: !!existing,
      access_level: existing?.access_level ?? "all_tools",
      allowed_tool_names: existing?.tool_names ?? [],
    };
  });
  for (const [sid, g] of grantMap) {
    if (serverIds.has(sid)) continue;
    rows.push({
      server_id: sid,
      enabled: true,
      access_level: g.access_level ?? "all_tools",
      allowed_tool_names: g.tool_names ?? [],
    });
  }
  return rows;
}

/**
 * Ops surface for local-runtime backends.
 * Channel → pick IdP profile on demand → load/save only that profile (ADR 0010).
 */
export function LocalRuntimePage({ canRead, canWrite }: Props) {
  const [hubInfo, setHubInfo] = useState<HubInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [clients, setClients] = useState<McpHubClient[]>([]);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<string>(PROFILE_PLACEHOLDER);
  const [rules, setRules] = useState<ServerAccessRule[]>([]);
  const [profileLoaded, setProfileLoaded] = useState(false);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [toolsByServer, setToolsByServer] = useState<Record<number, McpTool[]>>({});
  const [savingGrants, setSavingGrants] = useState(false);

  const selected = clients.find((c) => c.slug === selectedSlug) || null;

  const refreshClients = useCallback(async () => {
    const data = await apiFetch<{ clients: McpHubClient[] }>("/api/ext/local-runtime/mcp-clients");
    const next = data.clients || [];
    setClients(next);
    return next;
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

  const loadProfileGrants = useCallback(
    async (slug: string, group: string, catalog: McpServer[]) => {
      setLoadingProfile(true);
      setError(null);
      setProfileLoaded(false);
      try {
        const data = await apiFetch<{ group: string; grants: McpClientGrant[] }>(
          `/api/ext/local-runtime/mcp-clients/${encodeURIComponent(slug)}/profile-grants?group=${encodeURIComponent(group)}`,
        );
        setRules(buildRulesFromGrants(data.grants || [], catalog));
        setProfileLoaded(true);
      } catch (err) {
        // First-time profile (no grants yet): treat 404 as empty editor, not a hard failure.
        const status = err instanceof ApiError ? err.status : 0;
        if (status === 404) {
          setRules(buildRulesFromGrants([], catalog));
          setProfileLoaded(true);
          setError(null);
        } else {
          setRules([]);
          setProfileLoaded(false);
          setError(err instanceof ApiError ? err.detail : "Failed to load profile grants");
        }
      } finally {
        setLoadingProfile(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!canRead) return;
    void (async () => {
      try {
        const nextClients = await refreshClients();
        const list = await apiFetch<McpServer[]>("/api/mcp/servers");
        setServers((list || []).filter((s) => s.status === "active"));
        if (nextClients[0]) {
          setSelectedSlug(nextClients[0].slug);
        }
        const info = await apiFetch<HubInfo>("/api/mcp/hub/info");
        setHubInfo(info);
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : "Failed to load Hub clients");
      }
    })();
  }, [canRead, refreshClients]);

  useEffect(() => {
    if (!selected || !selectedProfile || !profileLoaded) return;
    for (const rule of rules) {
      if (rule.enabled && rule.access_level === "selected_tools") {
        void loadTools(rule.server_id).catch(() => undefined);
      }
    }
  }, [rules, selected, selectedProfile, profileLoaded, loadTools]);

  function selectChannel(client: McpHubClient) {
    setSelectedSlug(client.slug);
    setSelectedProfile(PROFILE_PLACEHOLDER);
    setRules([]);
    setProfileLoaded(false);
    setError(null);
  }

  async function changeProfile(profile: string) {
    setSelectedProfile(profile);
    setRules([]);
    setProfileLoaded(false);
    if (!profile || !selectedSlug) return;
    await loadProfileGrants(selectedSlug, profile, servers);
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

  async function setAgentsEnabled(slug: string, agentsEnabled: boolean) {
    setBusy(true);
    setError(null);
    try {
      const patch: { agents_enabled: boolean; status?: "enabled" } = {
        agents_enabled: agentsEnabled,
      };
      // Channel-level flag — independent of IdP profile. Turning agents on
      // also enables a discovered/disabled channel so tools/list can merge them.
      const client = clients.find((c) => c.slug === slug);
      if (agentsEnabled && client && client.status !== "enabled") {
        patch.status = "enabled";
      }
      await apiFetch(`/api/ext/local-runtime/mcp-clients/${encodeURIComponent(slug)}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      await refreshClients();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to update agents_enabled");
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
      if (selectedSlug === slug) {
        setSelectedSlug(null);
        setSelectedProfile(PROFILE_PLACEHOLDER);
        setRules([]);
        setProfileLoaded(false);
      }
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
    if (!selected || !selectedProfile || !profileLoaded) return;
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
      await apiFetch(`/api/ext/local-runtime/mcp-clients/${encodeURIComponent(selected.slug)}/profile-grants`, {
        method: "PUT",
        body: JSON.stringify({ group: selectedProfile, grants }),
      });
      if (selected.status !== "enabled" && grants.length > 0) {
        await apiFetch(`/api/ext/local-runtime/mcp-clients/${encodeURIComponent(selected.slug)}`, {
          method: "PATCH",
          body: JSON.stringify({ status: "enabled" }),
        });
      }
      await refreshClients();
      await loadProfileGrants(selected.slug, selectedProfile, servers);
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
          Extension plugin (ADR 0006 / 0010). Pick a channel, then an IdP profile — grants
          load and save on demand for that profile only (All / Selected tools).
        </p>
      </div>

      <section className="rounded-lg border bg-card p-4 space-y-3 text-sm">
        <h2 className="font-medium">MCP Hub (OAuth)</h2>
        <p className="text-muted-foreground">
          No mint. Point the IDE at the Hub URL only — Cursor authenticates via the
          active IdP (Keycloak / Microsoft Entra ID) with Authorization Code + PKCE.
          Use static <code>auth.CLIENT_ID</code> in <code>mcp.json</code>. After
          connect, the channel appears below for profile grants.
        </p>
        {error ? <p className="text-destructive text-xs">{error}</p> : null}
        {hubInfo ? (
          <div className="space-y-2 rounded-md bg-muted/40 p-3 font-mono text-xs break-all">
            <div>
              <div className="text-muted-foreground mb-1">Resource URL (mcp.json)</div>
              <div>{hubInfo.mcp_hub_url}</div>
            </div>
            <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-muted-foreground">
{`{
  "mcpServers": {
    "loom-hub": {
      "url": "${hubInfo.mcp_hub_url}",
      "auth": {
        "CLIENT_ID": "loom-mcp-hub",
        "scopes": ["openid", "profile"]
      }
    }
  }
}`}
            </pre>
            <div className="text-muted-foreground">
              auth={hubInfo.auth} · {hubInfo.contract_version} · PRM at{" "}
              http://127.0.0.1:8790/.well-known/oauth-protected-resource
            </div>
          </div>
        ) : canRead ? (
          <p className="text-muted-foreground text-xs">Loading Hub info…</p>
        ) : (
          <p className="text-muted-foreground">Requires mcp:read.</p>
        )}
      </section>

      <section className="rounded-lg border bg-card p-4 space-y-3 text-sm">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-medium">MCP Clients (channels)</h2>
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
          Discovered on IDE <code className="text-xs">initialize</code>. Select a channel,
          then choose an IdP profile to load or register its tool grants.
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
                <button type="button" className="text-left w-full" onClick={() => selectChannel(c)}>
                  <div className="font-medium">
                    {c.display_name || c.slug}{" "}
                    <span className="text-muted-foreground font-normal">({c.slug})</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    status={c.status} · family={c.declared_family} · agents=
                    {c.agents_enabled ? "on" : "off"} · grant rows=
                    {c.grant_count ?? 0}
                    {(c.granted_profiles || c.allowed_groups || []).length > 0
                      ? ` · profiles=${(c.granted_profiles || c.allowed_groups || []).join(",")}`
                      : ""}
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
            <div className="rounded-md border bg-background p-3 space-y-2">
              <h3 className="text-sm font-medium">Channel settings</h3>
              <p className="text-xs text-muted-foreground">
                Applies immediately on toggle — no profile and no Save button. Agent
                visibility still follows <code>loom:group</code> RBAC.
              </p>
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={Boolean(selected.agents_enabled)}
                  disabled={busy || !canWrite}
                  onChange={(e) => void setAgentsEnabled(selected.slug, e.target.checked)}
                />
                <span>
                  Expose Loom agents (<code>agents_enabled</code>)
                  {busy ? " · saving…" : selected.agents_enabled ? " · on" : " · off"}
                </span>
              </label>
            </div>

            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="space-y-2 min-w-0 flex-1">
                <h3 className="text-sm font-medium">
                  Profile tools — {selected.display_name || selected.slug}
                </h3>
                <label className="flex flex-col gap-1 text-xs max-w-sm">
                  <span className="text-muted-foreground">IdP profile</span>
                  <select
                    className="rounded-md border bg-background px-2 py-1.5 text-sm"
                    value={selectedProfile}
                    onChange={(e) => void changeProfile(e.target.value)}
                  >
                    <option value={PROFILE_PLACEHOLDER}>Select a profile…</option>
                    {LOOM_PROFILES.map((p) => {
                      const configured = (selected.granted_profiles || selected.allowed_groups || []).includes(p);
                      return (
                        <option key={p} value={p}>
                          {p}
                          {configured ? " · configured" : ""}
                        </option>
                      );
                    })}
                  </select>
                </label>
                {!selectedProfile ? (
                  <p className="text-xs text-muted-foreground">
                    Select a profile to load its grants or start registering tools for it.
                    The Save button appears after a profile is loaded.
                  </p>
                ) : loadingProfile ? (
                  <p className="text-xs text-muted-foreground">Loading {selectedProfile}…</p>
                ) : profileLoaded ? (
                  <p className="text-xs text-muted-foreground">
                    Editing <code className="text-xs">{selectedProfile}</code> only. Save writes
                    this profile; other profiles are untouched.
                  </p>
                ) : null}
              </div>
              {canWrite && selectedProfile && profileLoaded ? (
                <button
                  type="button"
                  className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-primary-foreground text-xs disabled:opacity-50"
                  disabled={savingGrants || loadingProfile}
                  onClick={() => void saveGrants()}
                >
                  {savingGrants ? "Saving…" : "Save profile grants"}
                </button>
              ) : null}
            </div>

            {selectedProfile && profileLoaded ? (
              servers.length === 0 ? (
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
              )
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
