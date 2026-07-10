import { useEffect, useState, useCallback } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { useTimezone, type TimezonePreference } from "@/contexts/TimezoneContext";
import { Button } from "@/components/ui/button";
import { listSiteSettings, updateSiteSetting, getRegistryConfig, updateRegistryConfig, getEnabledModels, updateEnabledModels, getLitellmProxyConfig, updateLitellmProxyConfig, refreshLitellmModels } from "@/api/settings";
import { fetchProviders } from "@/api/agents";
import { groupModels } from "@/lib/models";
import type { ModelOption, Provider } from "@/api/types";
import { VpcConfigPanel } from "@/components/VpcConfigPanel";

type SettingsTab = "general" | "models" | "networking" | "infrastructure";

export function SettingsPage() {
  const { timezone, setTimezone } = useTimezone();
  const localTz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

  const [cpuIdleDiscount, setCpuIdleDiscount] = useState("75");
  const [cpuIdleSaved, setCpuIdleSaved] = useState(false);

  const [registryArn, setRegistryArn] = useState("");
  const [registryId, setRegistryId] = useState("");
  const [registryEnabled, setRegistryEnabled] = useState(false);
  const [registrySaved, setRegistrySaved] = useState(false);
  const [registryError, setRegistryError] = useState("");
  const [confirmingDisable, setConfirmingDisable] = useState(false);

  const [allModels, setAllModels] = useState<ModelOption[]>([]);
  const [enabledModelIds, setEnabledModelIds] = useState<string[]>([]);
  const [modelsSaved, setModelsSaved] = useState(false);
  const [modelsSaving, setModelsSaving] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);

  const [litellmEnabled, setLitellmEnabled] = useState(false);
  const [litellmBaseUrl, setLitellmBaseUrl] = useState("");
  const [litellmDiscoveryBaseUrl, setLitellmDiscoveryBaseUrl] = useState("");
  const [litellmMasterKey, setLitellmMasterKey] = useState("");
  const [litellmHasMasterKey, setLitellmHasMasterKey] = useState(false);
  const [litellmSaved, setLitellmSaved] = useState(false);
  const [litellmSaving, setLitellmSaving] = useState(false);
  const [litellmError, setLitellmError] = useState("");
  const [litellmRefreshing, setLitellmRefreshing] = useState(false);

  const loadSiteSettings = useCallback(async () => {
    try {
      const settings = await listSiteSettings();
      const discount = settings.find((s) => s.key === "cpu_io_wait_discount");
      if (discount) setCpuIdleDiscount(discount.value);
    } catch {
      // ignore
    }
  }, []);

  const loadRegistryConfig = useCallback(async () => {
    try {
      const config = await getRegistryConfig();
      setRegistryArn(config.registry_arn);
      setRegistryId(config.registry_id);
      setRegistryEnabled(config.enabled);
    } catch {
      // ignore
    }
  }, []);

  const loadModelsConfig = useCallback(async () => {
    try {
      const config = await getEnabledModels();
      setAllModels(config.all_models as ModelOption[]);
      setEnabledModelIds(config.model_ids);
    } catch {
      // ignore
    }
  }, []);

  const loadLitellmProxyConfig = useCallback(async () => {
    try {
      const config = await getLitellmProxyConfig();
      setLitellmEnabled(config.enabled);
      setLitellmBaseUrl(config.base_url);
      setLitellmDiscoveryBaseUrl(config.discovery_base_url);
      setLitellmHasMasterKey(config.has_master_key);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => { void loadSiteSettings(); }, [loadSiteSettings]);
  useEffect(() => { void loadRegistryConfig(); }, [loadRegistryConfig]);
  useEffect(() => { void loadModelsConfig(); }, [loadModelsConfig]);
  useEffect(() => { void loadLitellmProxyConfig(); }, [loadLitellmProxyConfig]);
  useEffect(() => { void fetchProviders().then(setProviders).catch(() => {}); }, []);

  const saveLitellmProxyConfig = async () => {
    setLitellmError("");
    setLitellmSaving(true);
    try {
      const config = await updateLitellmProxyConfig(
        litellmEnabled, litellmBaseUrl, litellmDiscoveryBaseUrl, litellmMasterKey || undefined,
      );
      setLitellmEnabled(config.enabled);
      setLitellmHasMasterKey(config.has_master_key);
      setLitellmMasterKey("");
      setLitellmSaved(true);
      setTimeout(() => setLitellmSaved(false), 2000);
      void loadModelsConfig();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save";
      setLitellmError(msg);
    } finally {
      setLitellmSaving(false);
    }
  };

  const refreshLitellmModelsList = async () => {
    setLitellmError("");
    setLitellmRefreshing(true);
    try {
      const config = await refreshLitellmModels();
      setAllModels(config.all_models as ModelOption[]);
      setEnabledModelIds(config.model_ids);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to refresh models";
      setLitellmError(msg);
    } finally {
      setLitellmRefreshing(false);
    }
  };

  const saveRegistryConfig = async () => {
    setRegistryError("");
    try {
      const config = await updateRegistryConfig(registryArn);
      setRegistryId(config.registry_id);
      setRegistryEnabled(config.enabled);
      setRegistrySaved(true);
      setTimeout(() => setRegistrySaved(false), 2000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save";
      setRegistryError(msg);
    }
  };

  const disableRegistry = async () => {
    setRegistryArn("");
    setRegistryError("");
    try {
      const config = await updateRegistryConfig("");
      setRegistryId(config.registry_id);
      setRegistryEnabled(config.enabled);
      setRegistrySaved(true);
      setTimeout(() => setRegistrySaved(false), 2000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to disable";
      setRegistryError(msg);
    }
  };

  const saveCpuIdleDiscount = async (value: string) => {
    const num = Math.max(0, Math.min(99, parseInt(value, 10) || 0));
    setCpuIdleDiscount(String(num));
    try {
      await updateSiteSetting("cpu_io_wait_discount", String(num));
      setCpuIdleSaved(true);
      setTimeout(() => setCpuIdleSaved(false), 2000);
    } catch {
      // ignore
    }
  };

  const tabs: { key: SettingsTab; label: string }[] = [
    { key: "general", label: "General" },
    { key: "models", label: "Models" },
    { key: "networking", label: "Networking" },
    { key: "infrastructure", label: "Infrastructure" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Settings</h2>
        <p className="text-sm text-muted-foreground">Manage preferences, models, networking, and infrastructure.</p>
      </div>

      <div className="flex rounded-md border text-sm w-fit" role="tablist">
        {tabs.map((tab, i) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.key}
            className={`px-4 py-1.5 transition-colors ${
              i === 0 ? "rounded-l-md" : ""
            } ${
              i === tabs.length - 1 ? "rounded-r-md" : ""
            } ${
              activeTab === tab.key
                ? "bg-primary text-primary-foreground"
                : "hover:bg-accent"
            }`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "general" && (
        <div className="space-y-6">
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-medium">Preferences</h3>
              <p className="text-xs text-muted-foreground mt-1">
                Appearance and display settings.
              </p>
            </div>
            <div className="flex gap-4">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Timezone</label>
                <Select value={timezone} onValueChange={(v) => setTimezone(v as TimezonePreference)}>
                  <SelectTrigger className="h-8 w-[200px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="local">{localTz}</SelectItem>
                    <SelectItem value="UTC">UTC</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-medium">Cost Estimation</h3>
              <p className="text-xs text-muted-foreground mt-1">
                Configure assumptions for runtime cost calculations.
              </p>
            </div>
            <div className="flex gap-4 items-end">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">CPU I/O Wait Discount (%)</label>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={0}
                    max={99}
                    className="h-8 w-[100px] text-xs font-mono"
                    value={cpuIdleDiscount}
                    onChange={(e) => setCpuIdleDiscount(e.target.value)}
                    onBlur={(e) => void saveCpuIdleDiscount(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") void saveCpuIdleDiscount(cpuIdleDiscount); }}
                  />
                  {cpuIdleSaved && (
                    <span className="text-xs text-green-600 dark:text-green-400">Saved</span>
                  )}
                </div>
                <p className="text-[10px] text-muted-foreground">
                  Assumed % of CPU time spent waiting on I/O (e.g., model API calls). Applied as a discount to runtime CPU cost across estimates and actuals. Range: 0–99.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "models" && (() => {
        const providerDisplayName = (id: string) => providers.find((p) => p.id === id)?.display_name ?? id;
        const setGroupEnabled = (groupModelIds: string[], enabled: boolean) => {
          setEnabledModelIds((prev) => {
            const current = prev.length === 0 ? allModels.map((am) => am.model_id) : [...prev];
            const set = new Set(current);
            if (enabled) groupModelIds.forEach((id) => set.add(id));
            else groupModelIds.forEach((id) => set.delete(id));
            const next = Array.from(set);
            return next.length === allModels.length ? [] : next;
          });
        };
        const matchesSearch = (m: ModelOption) => {
          if (!modelSearch.trim()) return true;
          const q = modelSearch.trim().toLowerCase();
          return m.display_name.toLowerCase().includes(q) || m.model_id.toLowerCase().includes(q);
        };
        const renderModelGrid = (models: ModelOption[]) => (
          <div className="space-y-2">
            {groupModels(models).map(([group, groupedModels]) => (
              <div key={group} className="pl-1">
                <span className="text-[11px] font-medium text-muted-foreground">{group}</span>
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-x-3 gap-y-1 mt-0.5">
                  {groupedModels.map((m) => (
                    <label key={m.model_id} className="flex items-center gap-1.5 text-xs cursor-pointer" title={m.model_id}>
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 shrink-0"
                        checked={enabledModelIds.length === 0 || enabledModelIds.includes(m.model_id)}
                        onChange={(e) => {
                          setEnabledModelIds((prev) => {
                            const current = prev.length === 0 ? allModels.map((am) => am.model_id) : [...prev];
                            if (e.target.checked) {
                              return current.includes(m.model_id) ? current : [...current, m.model_id];
                            }
                            const next = current.filter((id) => id !== m.model_id);
                            return next.length === allModels.length ? [] : next;
                          });
                        }}
                      />
                      <span className="truncate">{m.display_name}</span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        );

        const bedrockModels = allModels.filter((m) => (m.provider ?? "bedrock") === "bedrock" && matchesSearch(m));
        const litellmModelsList = allModels.filter((m) => m.provider === "litellm" && matchesSearch(m));

        return (
          <div className="space-y-6">
            <div>
              <h3 className="text-sm font-medium">Enabled Models</h3>
              <p className="text-xs text-muted-foreground mt-1">
                Select which models are available for agent deployment and runtime selection. When none are selected for a provider, all of that provider's models are available.
              </p>
            </div>
            <Input
              placeholder="Filter by name or model id..."
              value={modelSearch}
              onChange={(e) => setModelSearch(e.target.value)}
              className="h-8 max-w-xs text-xs"
            />

            {/* Bedrock — always available, no toggle */}
            <div className="space-y-2">
              <div className="flex items-center justify-between border-b pb-1">
                <h4 className="text-xs font-semibold uppercase tracking-wide">
                  {providerDisplayName("bedrock")}{" "}
                  <span className="text-muted-foreground font-normal">({bedrockModels.length})</span>
                </h4>
                <div className="flex gap-2">
                  <button type="button" className="text-[10px] text-muted-foreground hover:underline" onClick={() => setGroupEnabled(bedrockModels.map((m) => m.model_id), true)}>All</button>
                  <button type="button" className="text-[10px] text-muted-foreground hover:underline" onClick={() => setGroupEnabled(bedrockModels.map((m) => m.model_id), false)}>None</button>
                </div>
              </div>
              {bedrockModels.length > 0 ? renderModelGrid(bedrockModels) : (
                <p className="text-xs text-muted-foreground">No models match &quot;{modelSearch}&quot;.</p>
              )}
            </div>

            {/* LiteLLM — optional, connection managed here */}
            <div className="space-y-3 border-t pt-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium">LiteLLM</h3>
                  <p className="text-xs text-muted-foreground mt-1">
                    Optional. Connect a LiteLLM proxy to make its models available for agent deployment.
                  </p>
                </div>
                <label className="flex items-center gap-2 text-xs cursor-pointer shrink-0">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5"
                    checked={litellmEnabled}
                    onChange={(e) => setLitellmEnabled(e.target.checked)}
                  />
                  Enabled
                </label>
              </div>

              {litellmEnabled && (
                <>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Agent Base URL</label>
                    <p className="text-[10px] text-muted-foreground">Used by deployed agents/harnesses at runtime — must be reachable from where they run (e.g. an internal ALB).</p>
                    <Input
                      type="text"
                      className="h-8 w-[400px] text-xs font-mono"
                      placeholder="https://litellm.example.com"
                      value={litellmBaseUrl}
                      onChange={(e) => setLitellmBaseUrl(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Discovery Base URL (optional)</label>
                    <p className="text-[10px] text-muted-foreground">Used by Loom itself to list models. Leave blank to reuse Agent Base URL — set this separately only when testing locally (e.g. an SSM tunnel).</p>
                    <Input
                      type="text"
                      className="h-8 w-[400px] text-xs font-mono"
                      placeholder={litellmBaseUrl || "http://localhost:4000"}
                      value={litellmDiscoveryBaseUrl}
                      onChange={(e) => setLitellmDiscoveryBaseUrl(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Master Key</label>
                    <div className="flex items-center gap-2">
                      <Input
                        type="password"
                        className="h-8 w-[400px] text-xs"
                        placeholder={litellmHasMasterKey ? "(unchanged)" : "sk-..."}
                        value={litellmMasterKey}
                        onChange={(e) => setLitellmMasterKey(e.target.value)}
                        autoComplete="off"
                      />
                      <Button size="sm" variant="outline" className="h-8 text-xs" disabled={litellmSaving} onClick={() => void saveLitellmProxyConfig()}>
                        Save
                      </Button>
                      {litellmSaved && (
                        <span className="text-xs text-green-600 dark:text-green-400">Saved</span>
                      )}
                    </div>
                    {litellmError && (
                      <p className="text-xs text-destructive">{litellmError}</p>
                    )}
                    <p className="text-[10px] text-muted-foreground">
                      {litellmHasMasterKey ? "A master key is configured." : "No master key configured — LiteLLM-provider agents cannot be deployed until one is set."}
                    </p>
                  </div>

                  <div className="space-y-2 pt-1">
                    <div className="flex items-center justify-between border-b pb-1">
                      <h4 className="text-xs font-semibold uppercase tracking-wide">
                        {providerDisplayName("litellm")}{" "}
                        <span className="text-muted-foreground font-normal">({litellmModelsList.length})</span>
                      </h4>
                      <div className="flex gap-2">
                        {litellmModelsList.length > 0 && (
                          <>
                            <button type="button" className="text-[10px] text-muted-foreground hover:underline" onClick={() => setGroupEnabled(litellmModelsList.map((m) => m.model_id), true)}>All</button>
                            <button type="button" className="text-[10px] text-muted-foreground hover:underline" onClick={() => setGroupEnabled(litellmModelsList.map((m) => m.model_id), false)}>None</button>
                          </>
                        )}
                        <button
                          type="button"
                          className="text-[10px] text-muted-foreground hover:underline disabled:opacity-50"
                          disabled={litellmRefreshing}
                          onClick={() => void refreshLitellmModelsList()}
                        >
                          {litellmRefreshing ? "Refreshing…" : "Refresh"}
                        </button>
                      </div>
                    </div>
                    {litellmModelsList.length > 0
                      ? renderModelGrid(litellmModelsList)
                      : (
                        <p className="text-xs text-muted-foreground">
                          No models detected — check the connection settings above, then Refresh.
                        </p>
                      )}
                  </div>
                </>
              )}
            </div>

            <div className="flex items-center gap-2 pt-1">
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs"
                disabled={modelsSaving}
                onClick={async () => {
                  setModelsSaving(true);
                  try {
                    const idsToSave = enabledModelIds.length === allModels.length ? [] : enabledModelIds;
                    const config = await updateEnabledModels(idsToSave);
                    setEnabledModelIds(config.model_ids);
                    setModelsSaved(true);
                    setTimeout(() => setModelsSaved(false), 2000);
                  } finally {
                    setModelsSaving(false);
                  }
                }}
              >
                Save
              </Button>
              {modelsSaved && (
                <span className="text-xs text-green-600 dark:text-green-400">Saved</span>
              )}
            </div>
            <p className="text-[10px] text-muted-foreground">
              {enabledModelIds.length === 0
                ? "All models are currently available."
                : `${enabledModelIds.length} of ${allModels.length} models enabled.`}
            </p>
          </div>
        );
      })()}

      {activeTab === "networking" && (
        <VpcConfigPanel />
      )}

      {activeTab === "infrastructure" && (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-medium">Agent Registry</h3>
            <p className="text-xs text-muted-foreground mt-1">
              Configure AWS Agent Registry for governance and discovery. When enabled, agents, MCP servers, and A2A agents must be approved in the registry before they can be used by end users.
            </p>
          </div>
          <div className="space-y-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Registry ARN</label>
              <div className="flex items-center gap-2">
                <Input
                  type="text"
                  className="h-8 w-[625px] text-xs font-mono"
                  placeholder="arn:aws:bedrock-agentcore:us-east-1:123456789012:registry/loom-registry"
                  value={registryArn}
                  onChange={(e) => setRegistryArn(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") void saveRegistryConfig(); }}
                />
                <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => void saveRegistryConfig()}>
                  Save
                </Button>
                {registryEnabled && !confirmingDisable && (
                  <Button size="sm" variant="ghost" className="h-8 text-xs text-destructive" onClick={() => setConfirmingDisable(true)}>
                    Disable
                  </Button>
                )}
                {confirmingDisable && (
                  <>
                    <span className="text-xs text-destructive">Disable registry?</span>
                    <Button size="sm" variant="destructive" className="h-6 text-xs" onClick={() => { setConfirmingDisable(false); void disableRegistry(); }}>
                      Confirm
                    </Button>
                    <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setConfirmingDisable(false)}>
                      Cancel
                    </Button>
                  </>
                )}
                {registrySaved && (
                  <span className="text-xs text-green-600 dark:text-green-400">Saved</span>
                )}
              </div>
              {registryError && (
                <p className="text-xs text-destructive">{registryError}</p>
              )}
              <p className="text-[10px] text-muted-foreground">
                {registryEnabled
                  ? `Registry enabled (ID: ${registryId}). Governance workflows are active.`
                  : "No registry configured. All resources are available without registry approval."}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
