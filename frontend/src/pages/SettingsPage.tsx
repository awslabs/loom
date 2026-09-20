import { useEffect, useState, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight } from "lucide-react";
import { SUPPORTED_LANGUAGES } from "@/i18n";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { useTimezone, type TimezonePreference } from "@/contexts/TimezoneContext";
import { useTheme, THEME_LABELS, type Theme } from "@/contexts/ThemeContext";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/StatusPill";
import { SettingsCard, SettingsRow } from "@/components/SettingsRow";
import { listSiteSettings, updateSiteSetting, getRegistryConfig, updateRegistryConfig, getEnabledModels, updateEnabledModels, getLitellmProxyConfig, updateLitellmProxyConfig, refreshLitellmModels } from "@/api/settings";
import { groupModels } from "@/lib/models";
import type { ModelOption, AgentResponse } from "@/api/types";
import { VpcConfigPanel } from "@/components/VpcConfigPanel";
import { TaggingPage } from "@/pages/TaggingPage";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

type SettingsTab = "general" | "models" | "networking" | "infrastructure" | "tagging";

function isEmbeddingModel(m: ModelOption): boolean {
  return /embed/i.test(m.model_id) || /embed/i.test(m.display_name);
}

/** Checkbox that supports the indeterminate visual state (not expressible as a plain JSX prop). */
function TriCheckbox({ checked, indeterminate, onChange, className = "" }: { checked: boolean; indeterminate?: boolean; onChange: (checked: boolean) => void; className?: string }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = !!indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      className={`h-3.5 w-3.5 shrink-0 accent-primary ${className}`}
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}

interface SettingsPageProps {
  canViewTagging?: boolean;
  canEditTagging?: boolean;
  userGroups?: string[];
  agents?: AgentResponse[];
}

export function SettingsPage({ canViewTagging = false, canEditTagging = false, userGroups = [], agents = [] }: SettingsPageProps) {
  const { t, i18n } = useTranslation();
  const { timezone, setTimezone } = useTimezone();
  const { theme, setTheme } = useTheme();
  const localTz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [expandedVendors, setExpandedVendors] = useState<Set<string>>(new Set());
  const [litellmConnectionExpanded, setLitellmConnectionExpanded] = useState(false);
  const [editingModels, setEditingModels] = useState(false);
  const [modelKind, setModelKind] = useState<"chat" | "embedding" | "all">("chat");

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
  const [initialEnabledModelIds, setInitialEnabledModelIds] = useState<string[]>([]);
  const [modelsSaved, setModelsSaved] = useState(false);
  const [modelsSaving, setModelsSaving] = useState(false);
  const [modelSearch, setModelSearch] = useState("");

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
      setInitialEnabledModelIds(config.model_ids);
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
    { key: "general", label: t("settings.tabs.general") },
    { key: "models", label: t("settings.tabs.models") },
    { key: "networking", label: t("settings.tabs.networking") },
    { key: "infrastructure", label: t("settings.tabs.infrastructure") },
    ...(canViewTagging ? [{ key: "tagging" as const, label: t("settings.tabs.tagging") }] : []),
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">{t("settings.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("settings.description")}</p>
      </div>

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as SettingsTab)}>
        <TabsList variant="line" className="h-auto justify-start gap-5 rounded-none border-b bg-transparent p-0">
          {tabs.map((tab) => (
            <TabsTrigger key={tab.key} value={tab.key} className="rounded-none px-0.5 pb-2.5 text-[13px] font-medium data-[state=active]:shadow-none">
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {activeTab === "general" && (
        <div className="flex flex-col gap-4">
          <SettingsCard title={t("settings.preferences.title")} description={t("settings.preferences.description")}>
            <SettingsRow label="Theme" helper="Applies to your account only">
              <div className="flex w-fit items-center gap-0.5 rounded-md border bg-muted p-[3px]">
                {(["light", "dark"] as Theme[]).map((th) => (
                  <button
                    key={th}
                    type="button"
                    onClick={() => setTheme(th)}
                    className={`rounded-[5px] px-3 py-1 text-[12.5px] transition-colors ${theme === th ? "bg-card font-medium text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                  >
                    {THEME_LABELS[th]}
                  </button>
                ))}
              </div>
            </SettingsRow>
            <SettingsRow label={t("settings.preferences.timezone")} helper="Used for all timestamps">
              <Select value={timezone} onValueChange={(v) => setTimezone(v as TimezonePreference)}>
                <SelectTrigger className="h-8 w-full text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">{localTz}</SelectItem>
                  <SelectItem value="UTC">UTC</SelectItem>
                </SelectContent>
              </Select>
            </SettingsRow>
            <SettingsRow label={t("settings.preferences.language")}>
              <Select
                value={i18n.resolvedLanguage ?? "en"}
                onValueChange={(v) => void i18n.changeLanguage(v)}
              >
                <SelectTrigger className="h-8 w-full text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SUPPORTED_LANGUAGES.map((lang) => (
                    <SelectItem key={lang} value={lang}>
                      {t(`languages.${lang}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </SettingsRow>
          </SettingsCard>

          <SettingsCard title={t("settings.costEstimation.title")} description={t("settings.costEstimation.description")}>
            <SettingsRow label={t("settings.costEstimation.cpuIdleDiscount")} helper="Range 0–99" align="start">
              <div className="flex items-center gap-2.5">
                <input
                  type="range"
                  min={0}
                  max={99}
                  value={cpuIdleDiscount}
                  onChange={(e) => setCpuIdleDiscount(e.target.value)}
                  onMouseUp={(e) => void saveCpuIdleDiscount((e.target as HTMLInputElement).value)}
                  onTouchEnd={(e) => void saveCpuIdleDiscount((e.target as HTMLInputElement).value)}
                  className="h-1 flex-1 accent-primary"
                />
                <div className="flex items-center gap-1 rounded-md border bg-card px-2.5 py-1 font-mono text-[12.5px] tabular-nums">
                  {cpuIdleDiscount}<span className="text-muted-foreground">%</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {cpuIdleSaved && <span className="text-[11px] text-success">Saved</span>}
              </div>
              <p className="text-[11px] leading-[1.5] text-muted-foreground">
                Assumed share of CPU time spent waiting on I/O (e.g. model API calls). Discounts runtime CPU cost in both estimates and actuals.
              </p>
            </SettingsRow>
          </SettingsCard>
        </div>
      )}

      {activeTab === "models" && (() => {
        const setIdsEnabled = (ids: string[], enabled: boolean) => {
          setEnabledModelIds((prev) => {
            const current = prev.length === 0 ? allModels.map((am) => am.model_id) : [...prev];
            const set = new Set(current);
            if (enabled) ids.forEach((id) => set.add(id));
            else ids.forEach((id) => set.delete(id));
            const next = Array.from(set);
            return next.length === allModels.length ? [] : next;
          });
        };
        const isEnabled = (id: string) => enabledModelIds.length === 0 || enabledModelIds.includes(id);
        const matchesSearch = (m: ModelOption) => {
          if (!modelSearch.trim()) return true;
          const q = modelSearch.trim().toLowerCase();
          return m.display_name.toLowerCase().includes(q) || m.model_id.toLowerCase().includes(q);
        };

        const chatModels = allModels.filter((m) => !isEmbeddingModel(m));
        const embeddingModels = allModels.filter(isEmbeddingModel);
        const kindFiltered = modelKind === "all" ? allModels : modelKind === "embedding" ? embeddingModels : chatModels;
        const searchMatched = kindFiltered.filter(matchesSearch);
        const vendorGroups = groupModels(searchMatched);

        const nothingRestricted = enabledModelIds.length === 0;
        const showSummary = nothingRestricted && !editingModels;

        // Impact preview relative to the last-saved baseline
        const currentlyEnabled = new Set(nothingRestricted ? allModels.map((m) => m.model_id) : enabledModelIds);
        const baselineEnabled = new Set(initialEnabledModelIds.length === 0 ? allModels.map((m) => m.model_id) : initialEnabledModelIds);
        const newlyDisabled = allModels.filter((m) => baselineEnabled.has(m.model_id) && !currentlyEnabled.has(m.model_id));
        const newlyEnabled = allModels.filter((m) => !baselineEnabled.has(m.model_id) && currentlyEnabled.has(m.model_id));
        const affectedAgents = newlyDisabled.length > 0
          ? agents.filter((a) => newlyDisabled.some((m) => a.model_id === m.model_id || a.allowed_model_ids?.includes(m.model_id)))
          : [];
        const isDirty = newlyDisabled.length > 0 || newlyEnabled.length > 0;

        const toggleVendor = (vendor: string) => setExpandedVendors((prev) => {
          const next = new Set(prev);
          next.has(vendor) ? next.delete(vendor) : next.add(vendor);
          return next;
        });
        const vendorExpanded = (vendor: string) => (modelSearch.trim() ? true : expandedVendors.has(vendor));

        return (
          <div className="flex flex-col gap-4">
            <SettingsCard
              title="Enabled models"
              description="Select which models are available for agent deployment and runtime selection."
            >
              {showSummary ? (
                <div className="flex flex-col gap-3.5 px-[18px] py-4">
                  <div className="grid grid-cols-3 overflow-hidden rounded-md border">
                    <div className="flex flex-col gap-1 border-r px-3.5 py-2.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Chat models</span>
                      <span className="font-mono text-[15px] tabular-nums">{chatModels.length}</span>
                    </div>
                    <div className="flex flex-col gap-1 border-r px-3.5 py-2.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Embedding models</span>
                      <span className="font-mono text-[15px] tabular-nums">{embeddingModels.length}</span>
                    </div>
                    <div className="flex flex-col gap-1 px-3.5 py-2.5">
                      <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Vendors</span>
                      <span className="font-mono text-[15px] tabular-nums">{groupModels(allModels).length}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-muted-foreground">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-success" />
                      All models available — no restrictions in effect
                    </span>
                    <Button size="sm" variant="outline" className="ml-auto h-7 text-xs" onClick={() => setEditingModels(true)}>
                      Restrict models
                    </Button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2.5 border-b bg-muted px-[18px] py-2.5">
                    <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-muted-foreground">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${nothingRestricted ? "bg-success" : "bg-warning"}`} />
                      {nothingRestricted ? "All models available — no restrictions in effect" : `${enabledModelIds.length} of ${allModels.length} models enabled`}
                    </span>
                    <div className="ml-auto flex items-center gap-2">
                      <div className="flex items-center gap-0.5 rounded-md border bg-card p-[3px]">
                        {(["chat", "embedding", "all"] as const).map((k) => (
                          <button key={k} type="button" onClick={() => setModelKind(k)} className={`rounded-[4px] px-2 py-1 text-[11px] capitalize transition-colors ${modelKind === k ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"}`}>
                            {k}
                          </button>
                        ))}
                      </div>
                      <Input
                        placeholder="Filter by name or model id…"
                        value={modelSearch}
                        onChange={(e) => setModelSearch(e.target.value)}
                        className="h-7 max-w-[200px] bg-card text-xs"
                      />
                    </div>
                  </div>
                  {modelSearch.trim() && (
                    <div className="border-b px-[18px] py-1.5 font-mono text-[10.5px] text-muted-foreground">
                      {searchMatched.length} of {kindFiltered.length} shown
                    </div>
                  )}

                  {vendorGroups.length === 0 ? (
                    <p className="px-[18px] py-6 text-sm text-muted-foreground">No models match &quot;{modelSearch}&quot;.</p>
                  ) : (
                    vendorGroups.map(([vendor, models]) => {
                      const enabledCount = models.filter((m) => isEnabled(m.model_id)).length;
                      const expanded = vendorExpanded(vendor);
                      return (
                        <div key={vendor} className="flex flex-col border-b last:border-b-0">
                          <div className={`flex items-center gap-3 px-[18px] py-3 ${expanded ? "bg-muted" : ""}`}>
                            <TriCheckbox
                              checked={enabledCount === models.length}
                              indeterminate={enabledCount > 0 && enabledCount < models.length}
                              onChange={(checked) => setIdsEnabled(models.map((m) => m.model_id), checked)}
                            />
                            <button type="button" onClick={() => toggleVendor(vendor)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
                              {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                              <span className="w-28 shrink-0 text-[12.5px] font-semibold">{vendor}</span>
                              <span className="shrink-0 rounded-md border bg-card px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">{enabledCount} / {models.length}</span>
                              <div className="h-1 max-w-[220px] flex-1 overflow-hidden rounded-full bg-input-bg">
                                <div className="h-full bg-primary" style={{ width: `${models.length > 0 ? (enabledCount / models.length) * 100 : 0}%` }} />
                              </div>
                              {!expanded && (
                                <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted-foreground">
                                  {models.slice(0, 4).map((m) => m.display_name).join(" · ")}{models.length > 4 ? ` +${models.length - 4}` : ""}
                                </span>
                              )}
                            </button>
                            <div className="ml-auto flex shrink-0 items-center gap-2.5">
                              <button type="button" className="font-mono text-[10.5px] text-primary" onClick={() => setIdsEnabled(models.map((m) => m.model_id), true)}>all</button>
                              <button type="button" className="font-mono text-[10.5px] text-primary" onClick={() => setIdsEnabled(models.map((m) => m.model_id), false)}>none</button>
                            </div>
                          </div>
                          {expanded && (
                            <div className="grid grid-cols-1 gap-x-6 gap-y-0.5 px-[18px] pb-3 pl-11 sm:grid-cols-2">
                              {models.map((m) => (
                                <label key={m.model_id} className="flex items-center gap-2.5 border-b py-1.5 text-xs last:border-b-0" title={m.model_id}>
                                  <TriCheckbox checked={isEnabled(m.model_id)} onChange={(checked) => setIdsEnabled([m.model_id], checked)} />
                                  <span className="min-w-0 flex-1 truncate">{m.display_name}</span>
                                  <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">{m.model_id}</span>
                                </label>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}

                  {/* LiteLLM connection — its models merge into the vendor rows above once configured */}
                  <div className="flex flex-col border-t">
                    <button type="button" onClick={() => setLitellmConnectionExpanded((v) => !v)} className={`flex items-center gap-3 px-[18px] py-3 text-left ${litellmConnectionExpanded ? "bg-muted" : ""}`}>
                      {litellmConnectionExpanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                      <span className="text-[12.5px] font-semibold">LiteLLM connection</span>
                      {litellmEnabled ? (
                        allModels.some((m) => m.provider === "litellm")
                          ? <StatusPill label="connected" variant="success" />
                          : <StatusPill label="no models detected" variant="warning" />
                      ) : (
                        <span className="text-[11.5px] text-muted-foreground">Not connected</span>
                      )}
                      <span className="ml-auto text-[11.5px] text-muted-foreground">Optional proxy — check connection, then refresh</span>
                    </button>
                    {litellmConnectionExpanded && (
                      <div className="flex flex-col gap-3.5 px-[18px] pb-4 pl-11">
                        <label className="flex items-center gap-2 text-xs cursor-pointer shrink-0">
                          <input
                            type="checkbox"
                            className="h-3.5 w-3.5 accent-primary"
                            checked={litellmEnabled}
                            onChange={(e) => setLitellmEnabled(e.target.checked)}
                          />
                          Enabled
                        </label>

                        {litellmEnabled && (
                          <>
                            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                              <div className="space-y-1">
                                <label className="text-xs text-muted-foreground">Agent base URL</label>
                                <Input
                                  type="text"
                                  className="h-8 text-xs font-mono"
                                  placeholder="https://litellm.example.com"
                                  value={litellmBaseUrl}
                                  onChange={(e) => setLitellmBaseUrl(e.target.value)}
                                />
                              </div>
                              <div className="space-y-1">
                                <label className="text-xs text-muted-foreground">Discovery base URL (optional)</label>
                                <Input
                                  type="text"
                                  className="h-8 text-xs font-mono"
                                  placeholder={litellmBaseUrl || "http://localhost:4000"}
                                  value={litellmDiscoveryBaseUrl}
                                  onChange={(e) => setLitellmDiscoveryBaseUrl(e.target.value)}
                                />
                              </div>
                            </div>
                            <div className="space-y-1">
                              <label className="text-xs text-muted-foreground">Master key</label>
                              <div className="flex items-center gap-2">
                                <Input
                                  type="password"
                                  className="h-8 max-w-[400px] text-xs"
                                  placeholder={litellmHasMasterKey ? "(unchanged)" : "sk-..."}
                                  value={litellmMasterKey}
                                  onChange={(e) => setLitellmMasterKey(e.target.value)}
                                  autoComplete="off"
                                />
                                <Button size="sm" variant="outline" className="h-8 text-xs" disabled={litellmSaving} onClick={() => void saveLitellmProxyConfig()}>
                                  Save
                                </Button>
                                {litellmSaved && <span className="text-[11px] text-success">Saved</span>}
                              </div>
                              {litellmError && <p className="text-xs text-destructive">{litellmError}</p>}
                              <p className="text-[10.5px] text-muted-foreground">
                                {litellmHasMasterKey ? "A master key is configured." : "No master key configured — LiteLLM-provider agents cannot be deployed until one is set."}
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                className="font-mono text-[10.5px] text-primary hover:underline disabled:opacity-50"
                                disabled={litellmRefreshing}
                                onClick={() => void refreshLitellmModelsList()}
                              >
                                {litellmRefreshing ? "Refreshing…" : "Refresh models"}
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </>
              )}
            </SettingsCard>

            {!showSummary && (
              <div className="flex max-w-[980px] flex-wrap items-center gap-3 rounded-md border bg-muted px-3.5 py-2.5">
                {isDirty ? (
                  <>
                    <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${affectedAgents.length > 0 ? "bg-destructive" : "bg-warning"}`} />
                    <span className="text-[12.5px]">
                      {newlyDisabled.length > 0 ? `${newlyDisabled.length} model${newlyDisabled.length === 1 ? "" : "s"} disabled` : "Model selection changed"}
                    </span>
                    {newlyDisabled.length > 0 && (
                      affectedAgents.length > 0 ? (
                        <span className="font-mono text-[11px] text-destructive">{affectedAgents.length} agent{affectedAgents.length === 1 ? "" : "s"} currently use{affectedAgents.length === 1 ? "s" : ""} a disabled model</span>
                      ) : (
                        <span className="font-mono text-[11px] text-muted-foreground">no agent currently uses them</span>
                      )
                    )}
                  </>
                ) : (
                  <span className="text-[12.5px] text-muted-foreground">No unsaved changes</span>
                )}
                <div className="ml-auto flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!isDirty}
                    onClick={() => {
                      setEnabledModelIds(initialEnabledModelIds);
                      if (initialEnabledModelIds.length === 0) setEditingModels(false);
                    }}
                  >
                    Discard
                  </Button>
                  <Button
                    size="sm"
                    disabled={modelsSaving || !isDirty}
                    onClick={async () => {
                      setModelsSaving(true);
                      try {
                        const idsToSave = enabledModelIds.length === allModels.length ? [] : enabledModelIds;
                        const config = await updateEnabledModels(idsToSave);
                        setEnabledModelIds(config.model_ids);
                        setInitialEnabledModelIds(config.model_ids);
                        setModelsSaved(true);
                        setTimeout(() => setModelsSaved(false), 2000);
                      } finally {
                        setModelsSaving(false);
                      }
                    }}
                  >
                    Save changes
                  </Button>
                  {modelsSaved && <span className="text-[11px] text-success">Saved</span>}
                </div>
              </div>
            )}
          </div>
        );
      })()}

      {activeTab === "networking" && (
        <VpcConfigPanel agents={agents} />
      )}

      {activeTab === "infrastructure" && (
        <SettingsCard
          title="Agent registry"
          action={<StatusPill label={registryEnabled ? "enabled" : "disabled"} variant={registryEnabled ? "success" : "neutral"} />}
        >
          <SettingsRow label="Registry ARN" helper={registryEnabled ? `ID ${registryId}` : undefined} align="start">
            <div className="flex items-center gap-2">
              <Input
                type="text"
                className="h-8 max-w-[420px] text-xs font-mono"
                placeholder="arn:aws:bedrock-agentcore:us-east-1:123456789012:registry/loom-registry"
                value={registryArn}
                onChange={(e) => setRegistryArn(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void saveRegistryConfig(); }}
              />
              <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => void saveRegistryConfig()}>
                Save
              </Button>
              {registrySaved && <span className="text-[11px] text-success">Saved</span>}
            </div>
            {registryError && <p className="text-xs text-destructive">{registryError}</p>}
            <p className="text-[11px] leading-[1.5] text-muted-foreground">
              While enabled, agents, MCP servers, and A2A agents must be approved in the registry before end users can invoke them.
            </p>
          </SettingsRow>

          <div className="flex items-center gap-3 px-[18px] py-3.5">
            <div className="flex flex-col gap-0.5">
              <span className="text-[12.5px] font-medium text-destructive">Disable registry</span>
              <span className="text-[11.5px] text-muted-foreground">Governance workflows stop; approved resources stay approved.</span>
            </div>
            <div className="ml-auto shrink-0">
              {confirmingDisable ? (
                <div className="flex items-center gap-2">
                  <span className="text-[11.5px] text-destructive">Disable registry?</span>
                  <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setConfirmingDisable(false)}>Cancel</Button>
                  <Button size="sm" variant="destructive" className="h-7 text-xs" onClick={() => { setConfirmingDisable(false); void disableRegistry(); }}>Confirm</Button>
                </div>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  disabled={!registryEnabled}
                  onClick={() => setConfirmingDisable(true)}
                >
                  Disable
                </Button>
              )}
            </div>
          </div>
        </SettingsCard>
      )}

      {activeTab === "tagging" && canViewTagging && (
        <TaggingPage readOnly={!canEditTagging} userGroups={userGroups} agents={agents} />
      )}
    </div>
  );
}
