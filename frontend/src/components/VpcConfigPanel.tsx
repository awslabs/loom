import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { SortableCardGrid, SortButton, loadSortDirection, toggleSortDirection, saveSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import { JsonConfigSection } from "@/components/JsonConfigSection";
import { ChevronDown, ChevronRight, Trash2, Plus, Pencil, Loader2, Network, Shield, LogIn, LogOut } from "lucide-react";
import { toast } from "sonner";
import * as settingsApi from "@/api/settings";
import type { VpcConfig, VpcConfigCreateRequest, VpcConfigDetail, VpcSgRuleDetail } from "@/api/types";

function parseIds(raw: string): string[] {
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

function joinIds(ids: string[]): string {
  return ids.join(", ");
}

interface FormState {
  name: string;
  description: string;
  vpc_id: string;
  subnet_ids_raw: string;
  sg_ids_raw: string;
}

const EMPTY_FORM_STATE: FormState = {
  name: "",
  description: "",
  vpc_id: "",
  subnet_ids_raw: "",
  sg_ids_raw: "",
};

function formToRequest(form: FormState): VpcConfigCreateRequest {
  return {
    name: form.name.trim(),
    description: form.description.trim() || undefined,
    vpc_id: form.vpc_id.trim(),
    subnet_ids: parseIds(form.subnet_ids_raw),
    sg_ids: parseIds(form.sg_ids_raw),
  };
}

function configToFormState(cfg: VpcConfig): FormState {
  return {
    name: cfg.name,
    description: cfg.description ?? "",
    vpc_id: cfg.vpc_id,
    subnet_ids_raw: joinIds(cfg.subnet_ids),
    sg_ids_raw: joinIds(cfg.sg_ids),
  };
}

function formatPortRange(rule: VpcSgRuleDetail): string {
  if (rule.protocol === "All") return "All";
  if (rule.from_port === null && rule.to_port === null) return "All";
  if (rule.from_port === rule.to_port) return String(rule.from_port);
  return `${rule.from_port}–${rule.to_port}`;
}

function SgRulesTable({ rules, label, icon }: { rules: VpcSgRuleDetail[]; label: string; icon: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {icon}
        {label}
      </div>
      <table className="text-xs w-full border-collapse border border-border rounded table-fixed">
        <colgroup>
          <col className="w-20" />
          <col className="w-24" />
          <col className="w-[25%]" />
          <col />
        </colgroup>
        <thead>
          <tr className="text-muted-foreground bg-accent">
            <th className="text-left font-medium px-2 py-1 border border-border">Protocol</th>
            <th className="text-left font-medium px-2 py-1 border border-border">Port</th>
            <th className="text-left font-medium px-2 py-1 border border-border">Source / Destination</th>
            <th className="text-left font-medium px-2 py-1 border border-border">Description</th>
          </tr>
        </thead>
        <tbody>
          {rules.length === 0 ? (
            <tr className="bg-background">
              <td colSpan={4} className="px-2 py-1 border border-border text-muted-foreground italic">No rules</td>
            </tr>
          ) : rules.map((r, i) => (
            <tr key={i} className="bg-background align-top">
              <td className="px-2 py-0.5 font-mono border border-border">{r.protocol}</td>
              <td className="px-2 py-0.5 font-mono border border-border">{formatPortRange(r)}</td>
              <td className="px-2 py-0.5 font-mono border border-border break-all">
                {r.cidr ?? (r.source_sg_id
                  ? (r.source_sg_name ? `${r.source_sg_id} (${r.source_sg_name})` : r.source_sg_id)
                  : "—")}
              </td>
              <td className="px-2 py-0.5 border border-border text-muted-foreground break-words">{r.description ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function VpcConfigPanel({ readOnly }: { readOnly?: boolean }) {
  const [configs, setConfigs] = useState<VpcConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM_STATE);
  const [submitting, setSubmitting] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detailCache, setDetailCache] = useState<Record<number, VpcConfigDetail | "loading">>({});
  const [sortDir, setSortDir] = useState<SortDirection>(() => loadSortDirection("settings-vpc-configs"));

  const loadConfigs = () => {
    setLoading(true);
    settingsApi.listVpcConfigs()
      .then(setConfigs)
      .catch(() => toast.error("Failed to load VPC configurations"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadConfigs(); }, []);

  const resetForm = () => {
    setForm(EMPTY_FORM_STATE);
    setShowAddForm(false);
    setEditingId(null);
  };

  const startEdit = (cfg: VpcConfig) => {
    setEditingId(cfg.id);
    setForm(configToFormState(cfg));
    setShowAddForm(false);
    setExpandedId(null);
  };

  const handleSave = async () => {
    if (!form.name.trim() || !form.vpc_id.trim()) return;
    setSubmitting(true);
    const request = formToRequest(form);
    try {
      if (editingId !== null) {
        const updated = await settingsApi.updateVpcConfig(editingId, request);
        setConfigs((prev) => prev.map((c) => c.id === editingId ? updated : c));
        setDetailCache((prev) => { const next = { ...prev }; delete next[editingId]; return next; });
        toast.success("VPC configuration updated");
      } else {
        const created = await settingsApi.createVpcConfig(request);
        setConfigs((prev) => [...prev, created]);
        toast.success("VPC configuration created");
      }
      resetForm();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleExpand = (id: number) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!detailCache[id]) {
      setDetailCache((prev) => ({ ...prev, [id]: "loading" }));
      settingsApi.getVpcConfigDetail(id)
        .then((d) => setDetailCache((prev) => ({ ...prev, [id]: d })))
        .catch(() => setDetailCache((prev) => { const next = { ...prev }; delete next[id]; return next; }));
    }
  };

  const handleDelete = async (id: number) => {
    setSubmitting(true);
    try {
      await settingsApi.deleteVpcConfig(id);
      setConfigs((prev) => prev.filter((c) => c.id !== id));
      setConfirmDeleteId(null);
      toast.success("VPC configuration deleted");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setSubmitting(false);
    }
  };

  const handleJsonApply = (json: string): string | null => {
    try {
      const obj = JSON.parse(json) as Record<string, unknown>;
      setForm((prev) => ({
        name: typeof obj.name === "string" ? obj.name : prev.name,
        description: typeof obj.description === "string" ? obj.description : prev.description,
        vpc_id: typeof obj.vpc_id === "string" ? obj.vpc_id : prev.vpc_id,
        subnet_ids_raw: Array.isArray(obj.subnet_ids)
          ? joinIds(obj.subnet_ids as string[])
          : typeof obj.subnet_ids === "string"
          ? obj.subnet_ids
          : prev.subnet_ids_raw,
        sg_ids_raw: Array.isArray(obj.sg_ids)
          ? joinIds(obj.sg_ids as string[])
          : typeof obj.sg_ids === "string"
          ? obj.sg_ids
          : prev.sg_ids_raw,
      }));
      return null;
    } catch {
      return "Invalid JSON. Expected a VPC configuration object.";
    }
  };

  const handleJsonExport = (): string => {
    // When editing, export the saved record; otherwise export current form state.
    if (editingId !== null) {
      const saved = configs.find((c) => c.id === editingId);
      if (saved) {
        return JSON.stringify({
          name: saved.name,
          description: saved.description || undefined,
          vpc_id: saved.vpc_id,
          subnet_ids: saved.subnet_ids,
          sg_ids: saved.sg_ids,
        }, null, 2);
      }
    }
    const req = formToRequest(form);
    return JSON.stringify({
      name: req.name || undefined,
      description: req.description || undefined,
      vpc_id: req.vpc_id || undefined,
      subnet_ids: req.subnet_ids.length > 0 ? req.subnet_ids : undefined,
      sg_ids: req.sg_ids.length > 0 ? req.sg_ids : undefined,
    }, null, 2);
  };

  if (loading) {
    return <div className="space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>;
  }

  const isEditing = editingId !== null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">VPC Configurations</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Named VPC configurations approved for use in Loom.<br />
            Builders select from these when deploying VPC-enabled agents instead of entering subnet and security group IDs directly.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-4">
          <SortButton direction={sortDir} onClick={() => setSortDir(toggleSortDirection("settings-vpc-configs", sortDir))} />
          <Button
            size="sm"
            variant="outline"
            onClick={() => { resetForm(); setShowAddForm(!showAddForm); }}
            disabled={readOnly}
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add Config
          </Button>
        </div>
      </div>

      {(showAddForm || isEditing) && (
        <Card>
          <CardContent className="pt-4 space-y-3">
            <JsonConfigSection
              onApply={handleJsonApply}
              onExport={handleJsonExport}
              placeholder='{"name": "prod-private", "vpc_id": "vpc-xxxxxxxx", "subnet_ids": ["subnet-aaa", "subnet-bbb"], "sg_ids": ["sg-xxx"]}'
            />
            <div className="grid grid-cols-2 gap-2">
              <Input
                placeholder="Name (e.g. prod-private)"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
              <Input
                placeholder="Description (optional)"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </div>
            <Input
              placeholder="VPC ID (vpc-xxxxxxxx)"
              value={form.vpc_id}
              onChange={(e) => setForm((f) => ({ ...f, vpc_id: e.target.value }))}
              className="font-mono text-xs"
            />
            <Input
              placeholder="Subnet IDs (comma-separated, e.g. subnet-aaa, subnet-bbb)"
              value={form.subnet_ids_raw}
              onChange={(e) => setForm((f) => ({ ...f, subnet_ids_raw: e.target.value }))}
              className="font-mono text-xs"
            />
            <Input
              placeholder="Security group IDs (comma-separated, e.g. sg-xxx, sg-yyy)"
              value={form.sg_ids_raw}
              onChange={(e) => setForm((f) => ({ ...f, sg_ids_raw: e.target.value }))}
              className="font-mono text-xs"
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={handleSave}
                disabled={submitting || !form.name.trim() || !form.vpc_id.trim()}
              >
                {submitting ? "Saving..." : isEditing ? "Update" : "Create"}
              </Button>
              <Button size="sm" variant="ghost" onClick={resetForm}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {configs.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8">No VPC configurations yet. Add one above.</p>
      ) : (
        <SortableCardGrid
          items={configs}
          getId={(c) => c.id.toString()}
          getName={(c) => c.name}
          storageKey="settings-vpc-configs"
          sortDirection={sortDir}
          onSortDirectionChange={(d) => { if (d) { setSortDir(d); saveSortDirection("settings-vpc-configs", d); } }}
          className="grid gap-2"
          renderItem={(cfg) => (
            <Card className="relative py-3 gap-1 transition-colors hover:bg-accent/50">
              <CardHeader className="gap-1 pb-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <button
                      type="button"
                      onClick={() => toggleExpand(cfg.id)}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      {expandedId === cfg.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </button>
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">{cfg.name}</div>
                      <div className="text-xs text-muted-foreground font-mono truncate">{cfg.vpc_id}</div>
                    </div>
                  </div>
                  {!readOnly && (
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        onClick={() => startEdit(cfg)}
                        className="text-muted-foreground/50 hover:text-foreground transition-colors"
                        title="Edit"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(cfg.id)}
                        className="text-muted-foreground/50 hover:text-destructive transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                {expandedId === cfg.id && (
                  <div className="ml-6 space-y-2">
                    {detailCache[cfg.id] === "loading" ? (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Loading details…
                      </div>
                    ) : detailCache[cfg.id] ? (() => {
                      const detail = detailCache[cfg.id] as import("@/api/types").VpcConfigDetail;
                      return (
                        <>
                          <div className="space-y-1.5">
                            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                              <Network className="h-3.5 w-3.5" />
                              Subnets ({detail.subnets.length})
                            </div>
                            <table className="text-xs w-full border-collapse border border-border rounded">
                              <thead>
                                <tr className="text-muted-foreground bg-accent">
                                  <th className="text-left font-medium px-2 py-1 border border-border">Subnet ID</th>
                                  <th className="text-left font-medium px-2 py-1 border border-border">Availability Zone / ID</th>
                                  <th className="text-left font-medium px-2 py-1 border border-border">CIDR</th>
                                  <th className="text-left font-medium px-2 py-1 border border-border">Available IPs</th>
                                </tr>
                              </thead>
                              <tbody>
                                {detail.subnets.map((s) => (
                                  <tr key={s.subnet_id} className="bg-background align-top">
                                    <td className="px-2 py-0.5 font-mono border border-border">
                                      {s.subnet_id}
                                      {s.name && <span className="ml-1 text-muted-foreground">({s.name})</span>}
                                    </td>
                                    <td className="px-2 py-0.5 font-mono border border-border">
                                      {s.availability_zone ?? "—"}
                                      {s.availability_zone_id && (
                                        <span className="ml-1 text-muted-foreground">({s.availability_zone_id})</span>
                                      )}
                                    </td>
                                    <td className="px-2 py-0.5 font-mono border border-border">{s.cidr_block ?? "—"}</td>
                                    <td className="px-2 py-0.5 border border-border text-muted-foreground">{s.available_ips ?? "—"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          {detail.security_groups.map((sg) => (
                            <div key={sg.sg_id} className="space-y-2">
                              <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                                <Shield className="h-3.5 w-3.5" />
                                {sg.sg_id}{sg.name ? ` — ${sg.name}` : ""}
                              </div>
                              <SgRulesTable rules={sg.ingress} label="Inbound rules" icon={<LogIn className="h-3 w-3" />} />
                              <SgRulesTable rules={sg.egress} label="Outbound rules" icon={<LogOut className="h-3 w-3" />} />
                            </div>
                          ))}
                        </>
                      );
                    })() : (
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                          <Network className="h-3.5 w-3.5" />
                          Subnets ({cfg.subnet_ids.length})
                        </div>
                        <table className="text-xs w-full border-collapse border border-border rounded">
                          <tbody>
                            {cfg.subnet_ids.map((id) => (
                              <tr key={id} className="bg-background">
                                <td className="px-2 py-0.5 font-mono border border-border">{id}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground pt-1">
                          <Shield className="h-3.5 w-3.5" />
                          Security Groups ({cfg.sg_ids.length})
                        </div>
                        <table className="text-xs w-full border-collapse border border-border rounded">
                          <tbody>
                            {cfg.sg_ids.map((id) => (
                              <tr key={id} className="bg-background">
                                <td className="px-2 py-0.5 font-mono border border-border">{id}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
                {confirmDeleteId === cfg.id && (
                  <div className="flex items-center justify-end gap-2 pt-1">
                    <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setConfirmDeleteId(null)}>
                      Cancel
                    </Button>
                    <Button size="sm" variant="destructive" className="h-6 text-xs" onClick={() => handleDelete(cfg.id)} disabled={submitting}>
                      Confirm
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        />
      )}
    </div>
  );
}
