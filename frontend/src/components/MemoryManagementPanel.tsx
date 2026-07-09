import { useState, useEffect, useCallback, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
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
import { MultiSelect } from "@/components/ui/multi-select";
import { AddFilterDropdown } from "@/components/ui/add-filter-dropdown";
import { Plus, Loader2, Trash2, Lock, X, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { useTimezone } from "@/contexts/TimezoneContext";
import { formatTimestamp } from "@/lib/format";
import { statusVariant } from "@/lib/status";
import { listMemories, createMemory, importMemory, refreshMemory, deleteMemory, purgeMemory, exportMemory } from "@/api/memories";
import { listTagPolicies, listTagProfiles } from "@/api/settings";
import { ApiError } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import { trackAction } from "@/api/audit";
import type { MemoryResponse, MemoryStrategyRequest, TagPolicy, TagProfile } from "@/api/types";
import { MemoryCard } from "./MemoryCard";
import { SortableCardGrid, SortButton, loadSortDirection, toggleSortDirection, saveSortDirection, type SortDirection } from "./SortableCardGrid";
import { SortableTableHead, sortRows } from "./SortableTableHead";
import { ResourceTagFields } from "./ResourceTagFields";
import { JsonConfigSection } from "./JsonConfigSection";

const STRATEGY_TYPES = [
  { value: "semantic", label: "Semantic" },
  { value: "summary", label: "Summary" },
  { value: "user_preference", label: "User Preference" },
  { value: "episodic", label: "Episodic" },
  { value: "custom", label: "Custom" },
] as const;



interface StrategyFormState {
  strategy_type: MemoryStrategyRequest["strategy_type"];
  name: string;
  description: string;
  namespace: string;
}

function emptyStrategy(): StrategyFormState {
  return { strategy_type: "semantic", name: "", description: "", namespace: "" };
}

function mapErrorMessage(status: number, detail: string): string {
  switch (status) {
    case 400:
      return `Invalid request: ${detail}`;
    case 403:
      return "Access denied. Check your AWS permissions.";
    case 404:
      return "Memory resource not found.";
    case 409:
      return "A memory resource with this name already exists.";
    case 429:
      return "Rate limited. Please try again later.";
    case 502:
      return "AWS service error. Please try again.";
    default:
      return detail || "An unexpected error occurred.";
  }
}

function parseApiError(e: unknown): string {
  if (e instanceof ApiError) {
    return mapErrorMessage(e.status, e.detail);
  }
  if (e instanceof Error) {
    return e.message;
  }
  return "An unexpected error occurred.";
}

interface MemoryManagementPanelProps {
  viewMode: "cards" | "table";
  readOnly?: boolean;
  groupRestriction?: string;
  ownerRestriction?: string;
  userGroups?: string[];
}

export function MemoryManagementPanel({ viewMode, readOnly, groupRestriction, ownerRestriction, userGroups = [] }: MemoryManagementPanelProps) {
  const { timezone } = useTimezone();
  const { user, browserSessionId, hasScope } = useAuth();
  const [memories, setMemories] = useState<MemoryResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [addMode, setAddMode] = useState<"create" | "import">("create");
  const [submitting, setSubmitting] = useState(false);
  // Elapsed timer: tick a `now` timestamp every second so elapsed = now - created_at
  const [now, setNow] = useState(Date.now());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Track when deletes and creates were initiated for accurate elapsed timers
  const [deleteStartTimes, setDeleteStartTimes] = useState<Record<number, number>>({});
  const [creationStartTimes, setCreationStartTimes] = useState<Record<number, number>>({});

  // Create form state
  const [exportMemoryId, setExportMemoryId] = useState<number | null>(null);
  const [formName, setFormName] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formExpiryDays, setFormExpiryDays] = useState(7);
  const [formExpiryError, setFormExpiryError] = useState("");
  const [formStrategies, setFormStrategies] = useState<StrategyFormState[]>([]);

  // Tag state
  const [tagValues, setTagValues] = useState<Record<string, string>>({});
  const [tagPolicies, setTagPolicies] = useState<TagPolicy[]>([]);
  const [tagProfiles, setTagProfiles] = useState<TagProfile[]>([]);
  const [selectedTagProfileId, setSelectedTagProfileId] = useState<string | undefined>(undefined);
  const [tagFilters, setTagFilters] = useState<Record<string, string[]>>(() => {
    try { return JSON.parse(localStorage.getItem("loom:tagFilters:memories") || "{}") as Record<string, string[]>; } catch { return {}; }
  });

  // Import form state
  const [importMemoryId, setImportMemoryId] = useState("");

  const fetchMemories = useCallback(async () => {
    try {
      const data = await listMemories();
      setMemories(data);
    } catch (e) {
      toast.error(parseApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchMemories();
    void listTagPolicies().then(setTagPolicies).catch(() => {});
    void listTagProfiles().then(setTagProfiles).catch(() => {});
  }, [fetchMemories]);

  useEffect(() => {
    if (!exportMemoryId || !hasScope("admin:write")) return;
    void exportMemory(exportMemoryId).then((data) => {
      if (data.name) setFormName(data.name as string);
      if (data.description) setFormDescription(data.description as string);
      if (typeof data.event_expiry_duration === "number") setFormExpiryDays(data.event_expiry_duration);
      if (data.tags) {
        const match = tagProfiles.find((p) => p.name === data.tags);
        if (match) setSelectedTagProfileId(match.id.toString());
      }
      const rawStrategies = data.memory_strategies as Array<Record<string, unknown>> | undefined;
      if (Array.isArray(rawStrategies)) {
        const validTypes = ["semantic", "summary", "user_preference", "episodic", "custom"] as const;
        const strategies: StrategyFormState[] = rawStrategies.map((s) => {
          const st = validTypes.includes(s.strategy_type as typeof validTypes[number])
            ? (s.strategy_type as StrategyFormState["strategy_type"])
            : "semantic";
          const ns = Array.isArray(s.namespaces) ? (s.namespaces[0] as string) || "" : (s.namespace as string) || "";
          return { strategy_type: st, name: (s.name as string) || "", description: (s.description as string) || "", namespace: ns };
        });
        setFormStrategies(strategies);
      }
    }).catch(() => {});
  }, [exportMemoryId]);

  // 1-second tick for elapsed display, 3-second poll for AWS status
  const memoriesRef = useRef(memories);
  memoriesRef.current = memories;
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const elapsedFor = (mem: MemoryResponse): number => {
    const delStart = deleteStartTimes[mem.id];
    if (mem.status === "DELETING" && delStart) {
      return Math.max(0, Math.floor((now - delStart) / 1000));
    }
    const createStart = creationStartTimes[mem.id];
    if (mem.status === "CREATING" && createStart) {
      return Math.max(0, Math.floor((now - createStart) / 1000));
    }
    if (!mem.created_at) return 0;
    return Math.max(0, Math.floor((now - new Date(mem.created_at).getTime()) / 1000));
  };

  useEffect(() => {
    const hasTransitional = memories.some(
      (m) => m.status === "CREATING" || m.status === "DELETING",
    );

    if (!hasTransitional) {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }

    // 1-second tick for elapsed display
    if (!timerRef.current) {
      timerRef.current = setInterval(() => {
        setNow(Date.now());
      }, 1000);
    }

    // 3-second poll for AWS status
    if (!pollRef.current) {
      pollRef.current = setInterval(async () => {
        const current = memoriesRef.current;
        const transitional = current.filter(
          (m) => m.status === "CREATING" || m.status === "DELETING",
        );
        for (const mem of transitional) {
          // Check for 10-minute creation timeout
          if (mem.status === "CREATING") {
            const startTime = creationStartTimes[mem.id];
            if (startTime && (Date.now() - startTime) > 600_000) {
              toast.error(`Memory "${mem.name}" creation timed out after 10 minutes`);
              setCreationStartTimes((prev) => {
                const next = { ...prev };
                delete next[mem.id];
                return next;
              });
              continue;
            }
          }
          try {
            const updated = await refreshMemory(mem.id);
            setMemories((prev) => prev.map((m) => (m.id === mem.id ? updated : m)));
          } catch (e) {
            // If a DELETING memory returns 404, it's gone from AWS — purge locally
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

  const validateExpiry = (days: number) => {
    if (days < 3 || days >= 365) {
      setFormExpiryError("Must be between 3 and 364 days");
    } else {
      setFormExpiryError("");
    }
  };

  const resetForm = () => {
    setFormName("");
    setFormDescription("");
    setFormExpiryDays(7);
    setFormExpiryError("");
    setFormStrategies([]);
    setImportMemoryId("");
  };

  const handleCreate = async () => {
    if (!formName.trim() || formExpiryError) return;
    setSubmitting(true);
    try {
      const strategies: MemoryStrategyRequest[] | undefined =
        formStrategies.length > 0
          ? formStrategies.map((s) => ({
              strategy_type: s.strategy_type,
              name: s.name,
              description: s.description || undefined,
              namespaces: s.namespace ? [s.namespace] : undefined,
            }))
          : undefined;

      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'memory', 'create', formName.trim());
      const created = await createMemory({
        name: formName.trim(),
        description: formDescription.trim() || undefined,
        event_expiry_duration: formExpiryDays,
        memory_strategies: strategies,
        tags: Object.keys(tagValues).length > 0 ? tagValues : undefined,
      });
      if (created && created.id) {
        setCreationStartTimes((prev) => ({ ...prev, [created.id]: Date.now() }));
      }
      resetForm();
      setShowAddForm(false);
      toast.success("Memory resource created");
      void fetchMemories();
    } catch (e) {
      toast.error(parseApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleImport = async () => {
    if (!importMemoryId.trim()) return;
    setSubmitting(true);
    try {
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'memory', 'import', importMemoryId.trim());
      await importMemory(importMemoryId.trim());
      resetForm();
      setShowAddForm(false);
      toast.success("Memory resource imported");
      void fetchMemories();
    } catch (e) {
      toast.error(parseApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number, deleteInAws: boolean) => {
    setSubmitting(true);
    try {
      const memName = memories.find(m => m.id === id)?.name ?? String(id);
      if (user && browserSessionId) trackAction(user.username ?? user.sub, browserSessionId, 'memory', 'delete', memName);
      const updated = await deleteMemory(id, deleteInAws);
      if (updated.status === "DELETING") {
        // Async deletion — update local state so polling picks it up
        setDeleteStartTimes((prev) => ({ ...prev, [id]: Date.now() }));
        setMemories((prev) => prev.map((m) => (m.id === id ? updated : m)));
        toast.success("Memory deletion initiated");
      } else {
        // Immediately removed (local-only, FAILED state, or no AWS ID)
        setMemories((prev) => prev.filter((m) => m.id !== id));
        toast.success(deleteInAws ? "Memory resource deleted" : "Memory removed from Loom");
      }
    } catch (e) {
      toast.error(parseApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  const addStrategy = () => {
    setFormStrategies([...formStrategies, emptyStrategy()]);
  };

  const removeStrategy = (index: number) => {
    setFormStrategies(formStrategies.filter((_, i) => i !== index));
  };

  const updateStrategy = (index: number, updates: Partial<StrategyFormState>) => {
    setFormStrategies(formStrategies.map((s, i) => (i === index ? { ...s, ...updates } : s)));
  };

  const showOnCardPolicies = tagPolicies.filter(tp => tp.show_on_card);
  const showOnCardKeys = showOnCardPolicies.map(tp => tp.key);

  // R3: Progressive disclosure filtering
  const requiredPolicies = showOnCardPolicies.filter(tp => tp.required);
  const customFilterPolicies = showOnCardPolicies.filter(tp => !tp.required);
  const [activeCustomFilterKeys, setActiveCustomFilterKeys] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("loom:customFilterKeys:memories") || "[]") as string[]; } catch { return []; }
  });

  // Persist filter state to localStorage
  useEffect(() => { localStorage.setItem("loom:tagFilters:memories", JSON.stringify(tagFilters)); }, [tagFilters]);
  useEffect(() => { localStorage.setItem("loom:customFilterKeys:memories", JSON.stringify(activeCustomFilterKeys)); }, [activeCustomFilterKeys]);

  // R4: Custom tag show/hide toggle
  const [showCustomTags, setShowCustomTags] = useState(() => localStorage.getItem("loom:showCustomTags") !== "false");
  const requiredKeySet = new Set(requiredPolicies.map(tp => tp.key));
  const effectiveShowOnCardKeys = showCustomTags ? showOnCardKeys : showOnCardKeys.filter(k => requiredKeySet.has(k));

  const [memorySortDir, setMemorySortDir] = useState<SortDirection>(() => loadSortDirection("memory-resources"));
  const [memoryTableCol, setMemoryTableCol] = useState<string | null>("name");
  const [memoryTableDir, setMemoryTableDir] = useState<SortDirection>("asc");

  const handleMemoryTableSort = (col: string) => {
    if (memoryTableCol === col) {
      setMemoryTableDir(memoryTableDir === "asc" ? "desc" : "asc");
    } else {
      setMemoryTableCol(col);
      setMemoryTableDir("asc");
    }
  };

  const filteredMemories = memories
    .filter(mem => {
      return Object.entries(tagFilters).every(([key, values]) => {
        if (values.length === 0) return true;
        return values.includes(mem.tags?.[key] ?? "");
      });
    })
    .filter(mem => !groupRestriction || mem.tags?.["loom:group"] === groupRestriction);

  const isTransitional = (status: string) => status === "CREATING" || status === "DELETING";

  const strategiesCount = (mem: MemoryResponse): number => {
    if (Array.isArray(mem.strategies_config)) return mem.strategies_config.length;
    if (Array.isArray(mem.strategies_response)) return mem.strategies_response.length;
    return 0;
  };

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">Memory Resources</h3>
          <p className="text-xs text-muted-foreground mt-1 whitespace-pre-line">
            {"A memory resource is attached to an agent.\nBy default, it includes only short-term memory. If long-term memory is desired, add the appropriate strategy."}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-4">
          <SortButton direction={memorySortDir} onClick={() => setMemorySortDir(toggleSortDirection("memory-resources", memorySortDir))} />
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setShowAddForm(!showAddForm);
              resetForm();
            }}
            disabled={readOnly}
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add Memory
          </Button>
        </div>
      </div>

      {showAddForm && (
        <Card>
          <CardContent className="pt-4 space-y-3">
            <div className="flex rounded-md border text-sm w-fit" role="tablist">
              {(["create", "import"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={addMode === tab}
                  className={`px-4 py-1.5 transition-colors ${
                    tab === "create" ? "rounded-l-md" : "rounded-r-md"
                  } ${
                    addMode === tab
                      ? "bg-primary text-primary-foreground"
                      : "hover:bg-accent"
                  }`}
                  onClick={() => { setAddMode(tab); resetForm(); }}
                >
                  {tab === "create" ? "Create" : "Import"}
                </button>
              ))}
            </div>

            {addMode === "create" ? (
              <>
                <JsonConfigSection
                  onApply={(json) => {
                    try {
                      const parsed = JSON.parse(json);
                      if (parsed.name) setFormName(parsed.name);
                      if (parsed.description) setFormDescription(parsed.description);
                      if (parsed.event_expiry_duration !== undefined) {
                        const days = Number(parsed.event_expiry_duration);
                        if (isNaN(days) || days < 3 || days > 364) {
                          return "event_expiry_duration must be between 3 and 364.";
                        }
                        setFormExpiryDays(days);
                        setFormExpiryError("");
                      }
                      if (parsed.tags) {
                        const match = tagProfiles.find((p) => p.name === parsed.tags);
                        if (match) {
                          setSelectedTagProfileId(match.id.toString());
                        }
                      }
                      const rawStrategies = parsed.memory_strategies || parsed.strategies;
                      if (Array.isArray(rawStrategies)) {
                        const validTypes = ["semantic", "summary", "user_preference", "episodic", "custom"];
                        const strategies: StrategyFormState[] = [];
                        for (const s of rawStrategies) {
                          if (s.strategy_type && !validTypes.includes(s.strategy_type)) continue;
                          const ns = Array.isArray(s.namespaces) ? s.namespaces[0] || "" : s.namespace || "";
                          strategies.push({
                            strategy_type: s.strategy_type || "semantic",
                            name: s.name || "",
                            description: s.description || "",
                            namespace: ns,
                          });
                        }
                        setFormStrategies(strategies);
                      }
                      return null;
                    } catch {
                      return "Invalid JSON. Please check the format and try again.";
                    }
                  }}
                  onExport={async () => {
                    if (exportMemoryId && hasScope("admin:write")) {
                      const data = await exportMemory(exportMemoryId);
                      return JSON.stringify(data, null, 2);
                    }
                    const result: Record<string, unknown> = {};
                    if (formName) result.name = formName;
                    if (formDescription) result.description = formDescription;
                    result.event_expiry_duration = formExpiryDays;
                    if (selectedTagProfileId) {
                      const profile = tagProfiles.find((p) => p.id.toString() === selectedTagProfileId);
                      if (profile) result.tags = profile.name;
                    }
                    if (formStrategies.length > 0) {
                      result.strategies = formStrategies.map((s) => {
                        const strat: Record<string, unknown> = {
                          strategy_type: s.strategy_type,
                          name: s.name,
                        };
                        if (s.description) strat.description = s.description;
                        if (s.namespace) strat.namespace = s.namespace;
                        return strat;
                      });
                    }
                    return JSON.stringify(result, null, 2);
                  }}
                  placeholder='{"name": "...", "description": "...", "strategies": [{"name": "...", "strategy_type": "semantic", "description": "...", "namespace": "..."}], "tags": "..."}'
                />
                <div className="flex gap-3">
                  <div className="w-1/3 min-w-0">
                    <label className="text-xs text-muted-foreground">Name *</label>
                    <Input
                      value={formName}
                      onChange={(e) => setFormName(e.target.value)}
                      placeholder="Memory resource name"
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <label className="text-xs text-muted-foreground">Description</label>
                    <Input
                      value={formDescription}
                      onChange={(e) => setFormDescription(e.target.value)}
                      placeholder="Optional description"
                    />
                  </div>
                  <div className="w-[160px]">
                    <label className="text-xs text-muted-foreground">Event Expiry (days)</label>
                    <Input
                      type="number"
                      value={formExpiryDays}
                      onChange={(e) => {
                        const v = parseInt(e.target.value, 10) || 0;
                        setFormExpiryDays(v);
                        validateExpiry(v);
                      }}
                      min={3}
                      max={364}
                    />
                    {formExpiryError && (
                      <p className="text-[10px] text-destructive mt-1">{formExpiryError}</p>
                    )}
                  </div>
                </div>

                {/* Resource Tags */}
                <ResourceTagFields onChange={setTagValues} profileId={selectedTagProfileId} groupRestriction={groupRestriction} ownerRestriction={ownerRestriction} />

                {/* Long-Term Strategies */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-xs text-muted-foreground font-medium">Long-term Strategies</label>
                    <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={addStrategy}>
                      <Plus className="h-3 w-3 mr-1" />
                      Add Strategy
                    </Button>
                  </div>
                  {formStrategies.length === 0 && (
                    <p className="text-xs text-muted-foreground italic">
                      No long-term strategies currently configured. As configured, only short-term memory will be used.
                    </p>
                  )}
                  {formStrategies.map((strategy, idx) => (
                    <div key={idx} className="rounded border border-dashed p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium">Strategy {idx + 1}</span>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 w-6 p-0"
                          onClick={() => removeStrategy(idx)}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                      <div className="flex gap-3">
                        <div className="w-[30%] min-w-0">
                          <label className="text-xs text-muted-foreground">Name</label>
                          <Input
                            value={strategy.name}
                            onChange={(e) => updateStrategy(idx, { name: e.target.value })}
                            placeholder="Strategy name"
                          />
                        </div>
                        <div className="w-[15%] min-w-0">
                          <label className="text-xs text-muted-foreground">Type</label>
                          <Select
                            value={strategy.strategy_type}
                            onValueChange={(v) =>
                              updateStrategy(idx, {
                                strategy_type: v as MemoryStrategyRequest["strategy_type"],
                              })
                            }
                          >
                            <SelectTrigger className="w-full text-sm">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {STRATEGY_TYPES.map((t) => (
                                <SelectItem key={t.value} value={t.value}>
                                  {t.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="flex-1 min-w-0">
                          <label className="text-xs text-muted-foreground">Description</label>
                          <Input
                            value={strategy.description}
                            onChange={(e) => updateStrategy(idx, { description: e.target.value })}
                            placeholder="Optional description"
                          />
                        </div>
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground">
                          Namespace
                        </label>
                        <Input
                          value={strategy.namespace}
                          onChange={(e) => updateStrategy(idx, { namespace: e.target.value })}
                          placeholder="e.g. /strategy/{memoryStrategyId}/actor/{actorId}/"
                        />
                      </div>
                    </div>
                  ))}
                </div>

                <div className="space-y-1.5 pt-2">
                  <p className="text-[10px] text-muted-foreground italic">
                    Creation typically takes ~3 minutes
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      className="min-w-[120px]"
                      onClick={handleCreate}
                      disabled={submitting || !formName.trim() || !!formExpiryError}
                    >
                      {submitting ? "Creating..." : "Create"}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setShowAddForm(false);
                        resetForm();
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="flex gap-3 items-end">
                  <div className="flex-1 min-w-0">
                    <label className="text-xs text-muted-foreground">AWS Memory ID *</label>
                    <Input
                      value={importMemoryId}
                      onChange={(e) => setImportMemoryId(e.target.value)}
                      placeholder="e.g. my_memory-zYcvlyGXsK"
                    />
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    className="min-w-[120px]"
                    onClick={handleImport}
                    disabled={submitting || !importMemoryId.trim()}
                  >
                    {submitting ? "Importing..." : "Import"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setShowAddForm(false);
                      resetForm();
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* Tag Filters */}
      {showOnCardPolicies.length > 0 && memories.length > 0 && (
        <div className="flex flex-wrap items-end gap-3">
          {requiredPolicies.map(tp => {
            const distinctValues = [...new Set(
              memories.map(m => m.tags?.[tp.key]).filter(Boolean)
            )] as string[];
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
            const distinctValues = [...new Set(
              memories.map(m => m.tags?.[tp.key]).filter(Boolean)
            )] as string[];
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
            Showing {filteredMemories.length} of {memories.length} memories
          </span>
        </div>
      )}

      {filteredMemories.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8">
          {memories.length === 0
            ? "No memory resources yet. Add one above."
            : "No memories match the selected filters."}
        </p>
      ) : (
        <>
          {viewMode === "cards" ? (
            <SortableCardGrid
              items={filteredMemories}
              getId={(m) => String(m.id)}
              getName={(m) => m.name}
              storageKey="memory-resources"
              sortDirection={memorySortDir}
              onSortDirectionChange={(d) => { if (d) { setMemorySortDir(d); saveSortDirection("memory-resources", d); } }}
              renderItem={(mem) => (
                <MemoryCard
                  memory={mem}
                  now={now}
                  submitting={submitting}
                  onDelete={handleDelete}
                  onEdit={hasScope("admin:write") ? (id) => { setExportMemoryId(id); setShowAddForm(true); setAddMode("create"); } : undefined}
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
                        <div className="flex items-center gap-1.5">
                          <Badge variant={statusVariant(mem.status)} className="text-[10px] px-1.5 py-0">
                            {mem.status}
                          </Badge>
                          {isTransitional(mem.status) && (
                            <>
                              <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                              <span className="text-[10px] text-muted-foreground">
                                ({elapsedFor(mem)}s)
                              </span>
                            </>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {mem.cost_summary && mem.cost_summary.total_memory_estimated_cost > 0
                          ? (mem.cost_summary.total_memory_estimated_cost < 0.01
                              ? `~$${mem.cost_summary.total_memory_estimated_cost.toFixed(6)}`
                              : `~$${mem.cost_summary.total_memory_estimated_cost.toFixed(4)}`)
                          : "\u2014"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {strategiesCount(mem)}
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
          )}
        </>
      )}

      {/* Coming soon */}
      <section className="space-y-3 pt-2">
        <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Additional Configuration</h4>
        <div className="space-y-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <Lock className="h-3.5 w-3.5" />
            <span>Encryption Key ARN</span>
            <span className="text-[10px] italic">Coming soon</span>
          </div>
        </div>
      </section>
    </div>
  );
}
