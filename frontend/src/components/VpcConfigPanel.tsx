import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { SortButton, loadSortDirection, toggleSortDirection, type SortDirection } from "@/components/SortableCardGrid";
import { sortRows } from "@/components/SortableTableHead";
import { JsonConfigSection } from "@/components/JsonConfigSection";
import { ExpandableRow } from "@/components/ExpandableRow";
import { Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import * as settingsApi from "@/api/settings";
import type { AgentResponse, VpcConfig, VpcConfigCreateRequest, VpcConfigDetail, VpcSgRuleDetail } from "@/api/types";

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
  if (rule.protocol === "All") return "all";
  if (rule.from_port === null && rule.to_port === null) return "all";
  if (rule.from_port === rule.to_port) return String(rule.from_port);
  return `${rule.from_port}–${rule.to_port}`;
}

function ruleSource(rule: VpcSgRuleDetail): string {
  if (rule.cidr) return rule.cidr;
  if (rule.source_sg_id) return rule.source_sg_name ? `${rule.source_sg_id} (${rule.source_sg_name})` : rule.source_sg_id;
  return "—";
}

/** One rules table with INBOUND / OUTBOUND as labeled band rows, matching the security-group row grammar used elsewhere. */
function SgRulesBanded({ ingress, egress }: { ingress: VpcSgRuleDetail[]; egress: VpcSgRuleDetail[] }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-md border">
      <div className="grid grid-cols-[52px_52px_100px_minmax(0,1fr)] gap-2.5 bg-muted px-2.5 py-1.5 font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">
        <span>Proto</span><span>Port</span><span>Source</span><span>Note</span>
      </div>
      <div className="flex items-center gap-1.5 border-t bg-card px-2.5 py-1.5 font-mono text-[9.5px] tracking-wide text-success">
        ↓ INBOUND
      </div>
      {ingress.length === 0 ? (
        <div className="border-t px-2.5 py-1.5 text-[11px] text-muted-foreground">No inbound rules</div>
      ) : ingress.map((r, i) => (
        <div key={`in-${i}`} className="grid grid-cols-[52px_52px_100px_minmax(0,1fr)] items-center gap-2.5 border-t px-2.5 py-1.5">
          <span className="font-mono text-[11px]">{r.protocol}</span>
          <span className="font-mono text-[11px] tabular-nums">{formatPortRange(r)}</span>
          <span className="truncate font-mono text-[11px]" title={ruleSource(r)}>{ruleSource(r)}</span>
          <span className="truncate text-[11px] text-muted-foreground">{r.description ?? ""}</span>
        </div>
      ))}
      <div className="flex items-center gap-1.5 border-t bg-card px-2.5 py-1.5 font-mono text-[9.5px] tracking-wide text-muted-foreground">
        ↑ OUTBOUND
      </div>
      {egress.length === 0 ? (
        <div className="border-t px-2.5 py-1.5 text-[11px] text-muted-foreground">No outbound rules</div>
      ) : egress.map((r, i) => (
        <div key={`out-${i}`} className="grid grid-cols-[52px_52px_100px_minmax(0,1fr)] items-center gap-2.5 border-t px-2.5 py-1.5">
          <span className="font-mono text-[11px]">{r.protocol}</span>
          <span className="font-mono text-[11px] tabular-nums">{formatPortRange(r)}</span>
          <span className="truncate font-mono text-[11px]" title={ruleSource(r)}>{ruleSource(r)}</span>
          <span className="truncate text-[11px] text-muted-foreground">{r.description ?? ""}</span>
        </div>
      ))}
    </div>
  );
}

export function VpcConfigPanel({ readOnly, agents = [] }: { readOnly?: boolean; agents?: AgentResponse[] }) {
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

  const dependentsOf = (id: number) => agents.filter((a) => a.vpc_config_id === id);

  const resetForm = () => {
    setForm(EMPTY_FORM_STATE);
    setShowAddForm(false);
    setEditingId(null);
  };

  const startEdit = (cfg: VpcConfig) => {
    setEditingId(cfg.id);
    setForm(configToFormState(cfg));
    setShowAddForm(false);
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
  const sorted = sortRows(configs, "name", sortDir, { name: (c) => c.name });

  return (
    <div className="flex max-w-[1000px] flex-col gap-3">
      <div className="flex items-center gap-2.5">
        <span className="text-[13px] font-semibold">VPC configurations</span>
        <span className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">{configs.length}</span>
        <span className="text-[12.5px] text-muted-foreground">Builders pick from these instead of typing subnet and security-group ids.</span>
        <div className="ml-auto flex items-center gap-2 shrink-0">
          <SortButton direction={sortDir} onClick={() => setSortDir(toggleSortDirection("settings-vpc-configs", sortDir))} />
          {!readOnly && (
            <Button size="sm" onClick={() => { resetForm(); setShowAddForm(!showAddForm); }}>
              <Plus className="h-3.5 w-3.5 mr-1" />
              Add config
            </Button>
          )}
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
        <div className="flex flex-col gap-3">
          {sorted.map((cfg) => {
            const detail = detailCache[cfg.id];
            const dependents = dependentsOf(cfg.id);
            const azCount = detail && detail !== "loading" ? new Set(detail.subnets.map((s) => s.availability_zone).filter(Boolean)).size : null;
            const ipTotal = detail && detail !== "loading" ? detail.subnets.reduce((sum, s) => sum + (s.available_ips ?? 0), 0) : null;
            const subtitle = detail && detail !== "loading"
              ? `${detail.subnets.length} subnets · ${azCount} AZ${azCount === 1 ? "" : "s"} · ${ipTotal} IPs available · ${detail.security_groups.length} security group${detail.security_groups.length === 1 ? "" : "s"}`
              : `${cfg.subnet_ids.length} subnets · ${cfg.sg_ids.length} security group${cfg.sg_ids.length === 1 ? "" : "s"}`;

            return (
              <ExpandableRow
                key={cfg.id}
                expanded={expandedId === cfg.id || editingId === cfg.id}
                onToggle={() => toggleExpand(cfg.id)}
                title={cfg.name}
                typeBadge={cfg.vpc_id}
                subtitle={subtitle}
                meta={<span className="text-[11.5px] text-muted-foreground">used by {dependents.length} agent{dependents.length === 1 ? "" : "s"}</span>}
                actions={
                  !readOnly ? (
                    <>
                      <Button size="sm" variant="outline" className="h-[29px]" onClick={() => startEdit(cfg)}>Edit</Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-[29px] border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive disabled:opacity-40"
                        disabled={dependents.length > 0}
                        title={dependents.length > 0 ? "Blocked while agents depend on this config" : undefined}
                        onClick={() => setConfirmDeleteId(cfg.id)}
                      >
                        Delete
                      </Button>
                    </>
                  ) : undefined
                }
              >
                {editingId === cfg.id ? (
                  <Card>
                    <CardContent className="pt-4 space-y-3">
                      <JsonConfigSection onApply={handleJsonApply} onExport={handleJsonExport} placeholder="" />
                      <div className="grid grid-cols-2 gap-2">
                        <Input placeholder="Name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
                        <Input placeholder="Description (optional)" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
                      </div>
                      <Input placeholder="VPC ID" value={form.vpc_id} onChange={(e) => setForm((f) => ({ ...f, vpc_id: e.target.value }))} className="font-mono text-xs" />
                      <Input placeholder="Subnet IDs (comma-separated)" value={form.subnet_ids_raw} onChange={(e) => setForm((f) => ({ ...f, subnet_ids_raw: e.target.value }))} className="font-mono text-xs" />
                      <Input placeholder="Security group IDs (comma-separated)" value={form.sg_ids_raw} onChange={(e) => setForm((f) => ({ ...f, sg_ids_raw: e.target.value }))} className="font-mono text-xs" />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={handleSave} disabled={submitting || !form.name.trim() || !form.vpc_id.trim()}>{submitting ? "Saving..." : "Update"}</Button>
                        <Button size="sm" variant="ghost" onClick={resetForm}>Cancel</Button>
                      </div>
                    </CardContent>
                  </Card>
                ) : (
                  <>
                    {confirmDeleteId === cfg.id && (
                      <div className="mb-3 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
                        <span>Delete <span className="font-mono">{cfg.name}</span>? This can't be undone.</span>
                        <div className="flex items-center gap-2">
                          <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setConfirmDeleteId(null)}>Cancel</Button>
                          <Button size="sm" variant="destructive" className="h-6 text-xs" onClick={() => handleDelete(cfg.id)} disabled={submitting}>Confirm</Button>
                        </div>
                      </div>
                    )}
                    {detail === "loading" ? (
                      <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Loading details…
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                        <div className="flex flex-col gap-2 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Subnets</span>
                            <span className="font-mono text-[10.5px] text-muted-foreground">{detail ? detail.subnets.length : cfg.subnet_ids.length}</span>
                          </div>
                          <div className="flex flex-col gap-2">
                            {detail ? detail.subnets.map((s) => (
                              <div key={s.subnet_id} className="flex flex-col gap-1 rounded-md border bg-muted px-3 py-2.5">
                                <span className="truncate font-mono text-[11.5px]" title={s.subnet_id}>{s.subnet_id}{s.name ? ` (${s.name})` : ""}</span>
                                <div className="flex items-center gap-3.5 font-mono text-[10.5px] text-muted-foreground">
                                  <span>{s.availability_zone ?? "—"}</span>
                                  <span>{s.cidr_block ?? "—"}</span>
                                  <span className="ml-auto tabular-nums text-foreground">{s.available_ips != null ? `${s.available_ips} IPs` : "—"}</span>
                                </div>
                              </div>
                            )) : cfg.subnet_ids.map((id) => (
                              <div key={id} className="rounded-md border bg-muted px-3 py-2 font-mono text-[11.5px]">{id}</div>
                            ))}
                          </div>
                        </div>

                        <div className="flex flex-col gap-2 min-w-0">
                          {detail ? detail.security_groups.map((sg) => (
                            <div key={sg.sg_id} className="flex flex-col gap-2">
                              <div className="flex items-center gap-2 min-w-0">
                                <span className="font-mono text-[9.5px] tracking-wide text-muted-foreground uppercase">Security group</span>
                                <span className="truncate font-mono text-[10.5px]">{sg.name ?? sg.sg_id}</span>
                                <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{sg.sg_id}</span>
                              </div>
                              <SgRulesBanded ingress={sg.ingress} egress={sg.egress} />
                            </div>
                          )) : cfg.sg_ids.map((id) => (
                            <div key={id} className="rounded-md border bg-muted px-3 py-2 font-mono text-[11.5px]">{id}</div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </ExpandableRow>
            );
          })}
        </div>
      )}
    </div>
  );
}
