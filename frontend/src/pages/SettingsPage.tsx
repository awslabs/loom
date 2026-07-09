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
import { listSiteSettings, updateSiteSetting, getRegistryConfig, updateRegistryConfig, getEnabledModels, updateEnabledModels } from "@/api/settings";
import { groupModels } from "@/lib/models";
import type { ModelOption } from "@/api/types";
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

  useEffect(() => { void loadSiteSettings(); }, [loadSiteSettings]);
  useEffect(() => { void loadRegistryConfig(); }, [loadRegistryConfig]);
  useEffect(() => { void loadModelsConfig(); }, [loadModelsConfig]);

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

      {activeTab === "models" && (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-medium">Enabled Models</h3>
            <p className="text-xs text-muted-foreground mt-1">
              Select which models are available for agent deployment and runtime selection. When none are selected, all models are available.
            </p>
          </div>
          <div className="space-y-2">
            {groupModels(allModels).map(([group, models]) => (
              <div key={group} className="flex flex-wrap gap-x-4 gap-y-1 items-center">
                <span className="text-xs font-medium text-muted-foreground w-20 shrink-0">{group}</span>
                {models.map((m) => (
                  <label key={m.model_id} className="flex items-center gap-1.5 text-xs cursor-pointer">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 shrink-0"
                      checked={enabledModelIds.length === 0 || enabledModelIds.includes(m.model_id)}
                      onChange={(e) => {
                        setEnabledModelIds((prev) => {
                          const current = prev.length === 0
                            ? allModels.map((am) => am.model_id)
                            : [...prev];
                          if (e.target.checked) {
                            return current.includes(m.model_id) ? current : [...current, m.model_id];
                          }
                          const next = current.filter((id) => id !== m.model_id);
                          return next.length === allModels.length ? [] : next;
                        });
                      }}
                    />
                    <span>{m.display_name}</span>
                  </label>
                ))}
              </div>
            ))}
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
        </div>
      )}

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
