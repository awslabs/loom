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
  listApprovalPolicies,
  createApprovalPolicy,
  updateApprovalPolicy,
  deleteApprovalPolicy,
} from "@/api/approvals";
import type { ApprovalPolicy } from "@/api/types";

interface PolicyFormData {
  name: string;
  policy_type: string;
  tool_match_rules: string;
  approval_mode: string;
  timeout_seconds: number;
  approval_cache_ttl: number;
  enabled: boolean;
}

const EMPTY_FORM: PolicyFormData = {
  name: "",
  policy_type: "loop_hook",
  tool_match_rules: "",
  approval_mode: "require_approval",
  timeout_seconds: 300,
  approval_cache_ttl: 0,
  enabled: true,
};

const POLICY_TYPE_LABELS: Record<string, string> = {
  loop_hook: "Loop hook",
  tool_context: "Tool context",
  mcp_elicitation: "MCP elicitation",
};

export function ApprovalPolicyPanel({ readOnly, onCountChange }: { readOnly?: boolean; onCountChange?: (count: number) => void }) {
  const [policies, setPolicies] = useState<ApprovalPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<PolicyFormData>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const loadPolicies = useCallback(async () => {
    try {
      const data = await listApprovalPolicies();
      setPolicies(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load policies");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPolicies();
  }, [loadPolicies]);

  useEffect(() => { onCountChange?.(policies.length); }, [policies.length, onCountChange]);

  const handleCreate = async () => {
    if (!form.name.trim()) return;
    setSubmitting(true);
    try {
      const rules = form.tool_match_rules
        .split(",")
        .map((r) => r.trim())
        .filter(Boolean);
      await createApprovalPolicy({
        name: form.name,
        policy_type: form.policy_type,
        tool_match_rules: rules.length > 0 ? rules : undefined,
        approval_mode: form.approval_mode,
        timeout_seconds: form.timeout_seconds,
        approval_cache_ttl: form.approval_cache_ttl || undefined,
        enabled: form.enabled,
      });
      toast.success("Approval policy created");
      setShowCreate(false);
      setForm(EMPTY_FORM);
      await loadPolicies();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create policy");
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async () => {
    if (editingId === null || !form.name.trim()) return;
    setSubmitting(true);
    try {
      const rules = form.tool_match_rules
        .split(",")
        .map((r) => r.trim())
        .filter(Boolean);
      await updateApprovalPolicy(editingId, {
        name: form.name,
        policy_type: form.policy_type,
        tool_match_rules: rules,
        approval_mode: form.approval_mode,
        timeout_seconds: form.timeout_seconds,
        approval_cache_ttl: form.approval_cache_ttl,
        enabled: form.enabled,
      });
      toast.success("Approval policy updated");
      setEditingId(null);
      setForm(EMPTY_FORM);
      await loadPolicies();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update policy");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteApprovalPolicy(id);
      setConfirmDeleteId(null);
      toast.success("Approval policy deleted");
      await loadPolicies();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete policy");
    }
  };

  const startEdit = (policy: ApprovalPolicy) => {
    setEditingId(policy.id);
    setShowCreate(false);
    setForm({
      name: policy.name,
      policy_type: policy.policy_type,
      tool_match_rules: policy.tool_match_rules.join(", "),
      approval_mode: policy.approval_mode,
      timeout_seconds: policy.timeout_seconds,
      approval_cache_ttl: policy.approval_cache_ttl,
      enabled: policy.enabled,
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
        <h3 className="text-sm font-medium">Approval policies</h3>
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
            Add policy
          </Button>
        )}
      </div>

      {isFormOpen && (
        <div className="rounded-lg border p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              {showCreate ? "New Approval Policy" : "Edit Approval Policy"}
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
                placeholder="e.g. Sensitive Tool Guard"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Policy Type</Label>
              <Select
                value={form.policy_type}
                onValueChange={(v) => setForm({ ...form, policy_type: v })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="loop_hook">Loop Hook</SelectItem>
                  <SelectItem value="tool_context">Tool Context</SelectItem>
                  <SelectItem value="mcp_elicitation">MCP Elicitation</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Approval Mode</Label>
              <Select
                value={form.approval_mode}
                onValueChange={(v) => setForm({ ...form, approval_mode: v })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="require_approval">Require Approval</SelectItem>
                  <SelectItem value="notify_only">Notify Only</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Timeout (seconds)</Label>
              <Input
                type="number"
                value={form.timeout_seconds}
                onChange={(e) =>
                  setForm({ ...form, timeout_seconds: Number(e.target.value) })
                }
              />
            </div>
            <div className="col-span-2 space-y-1">
              <Label className="text-xs">Tool Match Rules (comma-separated glob patterns)</Label>
              <Input
                value={form.tool_match_rules}
                onChange={(e) =>
                  setForm({ ...form, tool_match_rules: e.target.value })
                }
                placeholder="e.g. db_*, file_write, deploy_*"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Cache TTL (seconds, 0 = no cache)</Label>
              <Input
                type="number"
                value={form.approval_cache_ttl}
                onChange={(e) =>
                  setForm({ ...form, approval_cache_ttl: Number(e.target.value) })
                }
              />
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
              disabled={!form.name.trim() || submitting}
            >
              {submitting ? "Saving..." : showCreate ? "Create" : "Save"}
            </Button>
          </div>
        </div>
      )}

      {policies.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8">
          No approval policies configured.
        </p>
      ) : (
        <div className="rounded-md border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-card hover:bg-card">
                <TableHead>Policy</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Matches</TableHead>
                <TableHead>Timeout</TableHead>
                <TableHead className="text-right">State</TableHead>
                {!readOnly && <TableHead className="w-[1%]" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {policies.map((policy) => (
                <TableRow key={policy.id} className="group">
                  <TableCell className="font-mono text-[12.5px]">{policy.name}</TableCell>
                  <TableCell className="text-[12.5px] text-muted-foreground">{POLICY_TYPE_LABELS[policy.policy_type] ?? policy.policy_type}</TableCell>
                  <TableCell>
                    {policy.tool_match_rules.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {policy.tool_match_rules.map((rule) => (
                          <span key={rule} className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[11px]">{rule}</span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-[12px] text-muted-foreground">all tools</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-[11.5px] tabular-nums">
                    {policy.timeout_seconds}s
                    {policy.approval_cache_ttl > 0 && <span className="text-muted-foreground"> · cache {policy.approval_cache_ttl}s</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <StatusPill label={policy.enabled ? "enabled" : "disabled"} variant={policy.enabled ? "success" : "neutral"} className="ml-auto" />
                  </TableCell>
                  {!readOnly && (
                    <TableCell className="text-right">
                      {confirmDeleteId === policy.id ? (
                        <div className="flex items-center justify-end gap-1.5">
                          <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setConfirmDeleteId(null)}>Cancel</Button>
                          <Button size="sm" variant="destructive" className="h-6 text-xs" onClick={() => void handleDelete(policy.id)}>Confirm</Button>
                        </div>
                      ) : (
                        <div className="flex items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                          <button type="button" onClick={() => startEdit(policy)} className="text-muted-foreground/60 hover:text-foreground transition-colors" title="Edit">
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button type="button" onClick={() => setConfirmDeleteId(policy.id)} className="text-muted-foreground/60 hover:text-destructive transition-colors" title="Delete">
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
