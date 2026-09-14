import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/api/client";
import {
  deleteMcpClient,
  fetchActiveMcpServers,
  fetchHubInfo,
  fetchMcpClients,
  fetchProfileGrants,
  fetchServerTools,
  patchMcpClient,
  putProfileGrants,
} from "../local-runtime/api";
import { ChannelAgentsToggle } from "../local-runtime/ChannelAgentsToggle";
import { ClientsList } from "../local-runtime/ClientsList";
import { buildRulesFromGrants } from "../local-runtime/grants";
import { HubInfoSection } from "../local-runtime/HubInfoSection";
import { ProfileGrantsEditor } from "../local-runtime/ProfileGrantsEditor";
import type {
  HubInfo,
  McpClientGrant,
  McpHubClient,
  McpServer,
  McpTool,
  ServerAccessRule,
} from "../local-runtime/types";
import { PROFILE_PLACEHOLDER } from "../local-runtime/types";

type Props = {
  canRead: boolean;
  canWrite: boolean;
};

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
    const next = await fetchMcpClients();
    setClients(next);
    return next;
  }, []);

  const loadTools = useCallback(async (serverId: number) => {
    setToolsByServer((prev) => {
      if (prev[serverId]) return prev;
      void fetchServerTools(serverId)
        .then((tools) => {
          setToolsByServer((p) => (p[serverId] ? p : { ...p, [serverId]: tools }));
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
        const data = await fetchProfileGrants(slug, group);
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
        const activeServers = await fetchActiveMcpServers();
        setServers(activeServers);
        if (nextClients[0]) {
          setSelectedSlug(nextClients[0].slug);
        }
        setHubInfo(await fetchHubInfo());
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
      await patchMcpClient(slug, { status: next });
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
      await patchMcpClient(slug, patch);
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
      await deleteMcpClient(slug);
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
      await putProfileGrants(selected.slug, selectedProfile, grants);
      if (selected.status !== "enabled" && grants.length > 0) {
        await patchMcpClient(selected.slug, { status: "enabled" });
      }
      await refreshClients();
      await loadProfileGrants(selected.slug, selectedProfile, servers);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to save grants");
    } finally {
      setSavingGrants(false);
    }
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

      <HubInfoSection hubInfo={hubInfo} canRead={canRead} error={error} />

      <section className="rounded-lg border bg-card p-4 space-y-3 text-sm">
        <ClientsList
          clients={clients}
          selectedSlug={selectedSlug}
          canRead={canRead}
          canWrite={canWrite}
          busy={busy}
          onRefresh={() => void refreshClients().catch((e) => setError(String(e)))}
          onSelect={selectChannel}
          onSetStatus={(slug, next) => void setClientStatus(slug, next)}
          onDelete={(slug) => void deleteClient(slug)}
        />

        {selected ? (
          <div className="rounded-md border bg-muted/20 p-3 space-y-3">
            <ChannelAgentsToggle
              client={selected}
              canWrite={canWrite}
              busy={busy}
              onToggle={(slug, enabled) => void setAgentsEnabled(slug, enabled)}
            />
            <ProfileGrantsEditor
              client={selected}
              servers={servers}
              selectedProfile={selectedProfile}
              rules={rules}
              toolsByServer={toolsByServer}
              canWrite={canWrite}
              profileLoaded={profileLoaded}
              loadingProfile={loadingProfile}
              savingGrants={savingGrants}
              onChangeProfile={(profile) => void changeProfile(profile)}
              onUpdateRule={updateRule}
              onToggleTool={toggleTool}
              onLoadTools={(serverId) => void loadTools(serverId).catch(() => undefined)}
              onSave={() => void saveGrants()}
            />
          </div>
        ) : null}
      </section>
    </div>
  );
}
