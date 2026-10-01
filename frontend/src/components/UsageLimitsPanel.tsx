import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/StatusPill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
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
import { Plus, Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import {
  listUsageLimits,
  createUsageLimit,
  updateUsageLimit,
  deleteUsageLimit,
} from "@/api/usage_limits";
import type { UsageLimit } from "@/api/types";

interface LimitFormData {
  name: string;
  scope_type: "user" | "group";
  scope_value: string;
  target_type: "all" | "model" | "family";
  target_value: string;
  measure: "tokens" | "budget";
  threshold: number;
  window: "daily" | "weekly" | "monthly" | "rolling";
  enforcement: "warn" | "throttle" | "block";
  enabled: boolean;
}

const EMPTY_FORM: LimitFormData = {
  name: "",
  scope_type: "user",
  scope_value: "",
  target_type: "all",
  target_value: "",
  measure: "tokens",
  threshold: 100000,
  window: "daily",
  enforcement: "warn",
  enabled: true,
};

const ENFORCEMENT_VARIANT: Record<UsageLimit["enforcement"], "destructive" | "warning" | "neutral"> = {
  block: "destructive",
  throttle: "warning",
  warn: "neutral",
};

function scopeLabel(scope: UsageLimit["scope"]): string {
  return scope.type === "user" ? scope.username : scope.group;
}

function targetLabel(target: UsageLimit["target"]): string {
  if (target.type === "all") return "all models";
  if (target.type === "model") return target.model_id;
  return `${target.family} family`;
}

export function UsageLimitsPanel({ readOnly, onCountChange }: { readOnly?: boolean; onCountChange?: (count: number) => void }) {
  const [limits, setLimits] = useState<UsageLimit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<LimitFormData>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const loadLimits = useCallback(async () => {
    try {
      const data = await listUsageLimits();
      setLimits(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load usage limits");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadLimits();
  }, [loadLimits]);

  useEffect(() => { onCountChange?.(limits.length); }, [limits.length, onCountChange]);

  const buildPayload = () => ({
    name: form.name,
    scope:
      form.scope_type === "user"
        ? { type: "user", username: form.scope_value }
        : { type: "group", group: form.scope_value },
    target:
      form.target_type === "all"
        ? { type: "all" }
        : form.target_type === "model"
          ? { type: "model", model_id: form.target_value }
          : { type: "family", family: form.target_value },
    measure: form.measure,
    threshold: form.threshold,
    window: form.window,
    enforcement: form.enforcement,
    enabled: form.enabled,
  });

  const handleCreate = async () => {
    if (!form.name.trim() || !form.scope_value.trim()) return;
    setSubmitting(true);
    try {
      await createUsageLimit(buildPayload());
      toast.success("Usage limit created");
      setShowCreate(false);
      setForm(EMPTY_FORM);
      await loadLimits();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create usage limit");
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async () => {
    if (editingId === null || !form.name.trim() || !form.scope_value.trim()) return;
    setSubmitting(true);
    try {
      await updateUsageLimit(editingId, buildPayload());
      toast.success("Usage limit updated");
      setEditingId(null);
      setForm(EMPTY_FORM);
      await loadLimits();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update usage limit");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteUsageLimit(id);
      setConfirmDeleteId(null);
      toast.success("Usage limit deleted");
      await loadLimits();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete usage limit");
    }
  };

  const startEdit = (limit: UsageLimit) => {
    setEditingId(limit.id);
    setShowCreate(false);
    setForm({
      name: limit.name,
      scope_type: limit.scope.type,
      scope_value: scopeLabel(limit.scope),
      target_type: limit.target.type,
      target_value: limit.target.type === "all" ? "" : targetLabel(limit.target).replace(" family", ""),
      measure: limit.measure,
      threshold: limit.threshold,
      window: limit.window,
      enforcement: limit.enforcement,
      enabled: limit.enabled,
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setShowCreate(false);
    setForm(EMPTY_FORM);
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

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  const isFormOpen = showCreate || editingId !== null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Usage limits</h3>
        {!readOnly && !isFormOpen && (
          <Button
            size="sm"
            onClick={() => {
              setShowCreate(true);
              setEditingId(null);
              setForm(EMPTY_FORM);
            }}
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add limit
          </Button>
        )}
      </div>

      {isFormOpen && (
        <div className="rounded-lg border p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              {showCreate ? "New Usage Limit" : "Edit Usage Limit"}
            </span>
            <Button size="sm" variant="ghost" onClick={cancelEdit}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-xs">Name</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Marketing Team Daily Cap"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Threshold</Label>
              <Input
                type="number"
                value={form.threshold}
                onChange={(e) => setForm({ ...form, threshold: Number(e.target.value) })}
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Applies To</Label>
              <div className="flex gap-2">
                <Select
                  value={form.scope_type}
                  onValueChange={(v) => setForm({ ...form, scope_type: v as "user" | "group" })}
                >
                  <SelectTrigger className="w-[110px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="user">User</SelectItem>
                    <SelectItem value="group">Group</SelectItem>
                  </SelectContent>
                </Select>
                <Input
                  value={form.scope_value}
                  onChange={(e) => setForm({ ...form, scope_value: e.target.value })}
                  placeholder={form.scope_type === "user" ? "username" : "group name"}
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Model Scope</Label>
              <div className="flex gap-2">
                <Select
                  value={form.target_type}
                  onValueChange={(v) => setForm({ ...form, target_type: v as "all" | "model" | "family" })}
                >
                  <SelectTrigger className="w-[110px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All models</SelectItem>
                    <SelectItem value="model">Specific model</SelectItem>
                    <SelectItem value="family">Model family</SelectItem>
                  </SelectContent>
                </Select>
                {form.target_type !== "all" && (
                  <Input
                    value={form.target_value}
                    onChange={(e) => setForm({ ...form, target_value: e.target.value })}
                    placeholder={form.target_type === "model" ? "e.g. anthropic.claude-sonnet-4-6" : "e.g. anthropic"}
                  />
                )}
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Measure</Label>
              <Select
                value={form.measure}
                onValueChange={(v) => setForm({ ...form, measure: v as "tokens" | "budget" })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="tokens">Tokens</SelectItem>
                  <SelectItem value="budget">Budget ($)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Reset Window</Label>
              <Select
                value={form.window}
                onValueChange={(v) => setForm({ ...form, window: v as LimitFormData["window"] })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="daily">Daily</SelectItem>
                  <SelectItem value="weekly">Weekly</SelectItem>
                  <SelectItem value="monthly">Monthly</SelectItem>
                  <SelectItem value="rolling">Rolling 24h</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">When Exceeded</Label>
              <Select
                value={form.enforcement}
                onValueChange={(v) => setForm({ ...form, enforcement: v as LimitFormData["enforcement"] })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="warn">Warn only</SelectItem>
                  <SelectItem value="throttle">Throttle</SelectItem>
                  <SelectItem value="block">Block</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end pb-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                  className="rounded"
                />
                Enabled
              </label>
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button size="sm" variant="ghost" onClick={cancelEdit}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={showCreate ? handleCreate : handleUpdate}
              disabled={!form.name.trim() || !form.scope_value.trim() || submitting}
            >
              {submitting ? "Saving..." : showCreate ? "Create" : "Save"}
            </Button>
          </div>
        </div>
      )}

      {limits.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8">
          No usage limits configured.
        </p>
      ) : (
        <div className="rounded-md border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-card hover:bg-card">
                <TableHead>Limit</TableHead>
                <TableHead>Applies To</TableHead>
                <TableHead>Model Scope</TableHead>
                <TableHead>Usage</TableHead>
                <TableHead>On Exceed</TableHead>
                <TableHead className="text-right">State</TableHead>
                {!readOnly && <TableHead className="w-[1%]" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {limits.map((limit) => (
                <TableRow key={limit.id} className="group">
                  <TableCell className="font-mono text-[12.5px]">{limit.name}</TableCell>
                  <TableCell className="text-[12.5px] text-muted-foreground">
                    <span className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                      {limit.scope.type}: {scopeLabel(limit.scope)}
                    </span>
                  </TableCell>
                  <TableCell className="text-[12px] text-muted-foreground">{targetLabel(limit.target)}</TableCell>
                  <TableCell className="font-mono text-[11.5px] tabular-nums">
                    {limit.cached_usage !== null ? limit.cached_usage.toLocaleString() : "—"} / {limit.threshold.toLocaleString()} {limit.measure}
                    <span className="text-muted-foreground"> · {limit.window}</span>
                  </TableCell>
                  <TableCell>
                    <StatusPill label={limit.enforcement} variant={ENFORCEMENT_VARIANT[limit.enforcement]} />
                  </TableCell>
                  <TableCell className="text-right">
                    <StatusPill label={limit.enabled ? "enabled" : "disabled"} variant={limit.enabled ? "success" : "neutral"} className="ml-auto" />
                  </TableCell>
                  {!readOnly && (
                    <TableCell className="text-right">
                      {confirmDeleteId === limit.id ? (
                        <div className="flex items-center justify-end gap-1.5">
                          <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setConfirmDeleteId(null)}>Cancel</Button>
                          <Button size="sm" variant="destructive" className="h-6 text-xs" onClick={() => void handleDelete(limit.id)}>Confirm</Button>
                        </div>
                      ) : (
                        <div className="flex items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                          <button type="button" onClick={() => startEdit(limit)} className="text-muted-foreground/60 hover:text-foreground transition-colors" title="Edit">
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button type="button" onClick={() => setConfirmDeleteId(limit.id)} className="text-muted-foreground/60 hover:text-destructive transition-colors" title="Delete">
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      )}
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
