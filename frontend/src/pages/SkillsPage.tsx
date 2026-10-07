import { useCallback, useEffect, useRef, useState } from "react";
import { isSafeExternalUrl } from "@/lib/navigation";
import { AlertTriangle, ArrowLeft, Download, ExternalLink, FileUp, Loader2, Puzzle, RefreshCw, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { RegistryStatusBadge } from "@/components/RegistryStatusBadge";
import { RegistryActions } from "@/components/RegistryActions";
import { SkillDocument } from "@/components/SkillDocument";
import { SkillEditor, type SkillEditorValues } from "@/components/SkillEditor";
import { useTimezone } from "@/contexts/TimezoneContext";
import { useAuth } from "@/contexts/AuthContext";
import { formatTimestamp } from "@/lib/format";
import { parseSkillMd, countSteps } from "@/lib/skillMd";
import {
  listRegistryRecords,
  getRegistryRecord,
  createRegistryRecord,
  updateSkillRecord,
  deleteRegistryRecord,
  getSkillDependents,
} from "@/api/registry";
import { getRegistryConfig } from "@/api/settings";
import type { RegistryRecord, RegistryRecordDetail, SkillDependent } from "@/api/types";

/** Agent Skills surface: the SKILL-typed records of the bound Agent Registry.
 *
 * Admin-only end to end (registry:read to view, registry:write to author) —
 * both gates are enforced server-side already (registry:read/write are only
 * ever granted to g-admins-super/demo/registry in GROUP_SCOPES, never to any
 * g-users-* group), but this page also checks explicitly rather than relying
 * solely on the sidebar hiding its own nav item, so a stray navigation path
 * can't land here and fire a pile of fetches doomed to 403.
 */

interface SkillLinks {
  repositoryUrl?: string;
  websiteUrl?: string;
}

function parseSkillLinks(detail: RegistryRecordDetail): SkillLinks {
  try {
    const def = detail.descriptors?.agentSkillsDefinition as { data?: string } | undefined;
    if (!def?.data) return {};
    const data = JSON.parse(def.data) as { repository?: { url?: string }; websiteUrl?: string };
    return { repositoryUrl: data.repository?.url, websiteUrl: data.websiteUrl };
  } catch {
    return {};
  }
}

interface SkillEditDefaults extends SkillEditorValues { skillMdBody: string }

function parseSkillEditDefaults(detail: RegistryRecordDetail): SkillEditDefaults {
  const def = detail.descriptors?.agentSkillsDefinition as
    | { data?: string; additionalData?: { skillMd?: { data?: string } } }
    | undefined;
  let license = "";
  let author = "";
  let version = "";
  try {
    if (def?.data) {
      const data = JSON.parse(def.data) as { license?: string; metadata?: { author?: string; version?: string } };
      license = data.license ?? "";
      author = data.metadata?.author ?? "";
      version = data.metadata?.version ?? "";
    }
  } catch {
    // fall through with defaults
  }
  const skillMd = def?.additionalData?.skillMd?.data ?? "";
  return {
    name: detail.name,
    description: detail.description ?? "",
    license,
    author,
    version,
    body: skillMd,
    skillMdBody: skillMd,
  };
}

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 text-xs py-1.5 border-b last:border-0">
      <span className="w-28 shrink-0 text-muted-foreground uppercase tracking-wide text-[10px] pt-0.5">{label}</span>
      <span className="min-w-0 break-all">{children}</span>
    </div>
  );
}

function ExternalLinkRow({ url }: { url: string }) {
  // url comes from the skill record's agentSkillsDefinition descriptor
  // (repository.url / websiteUrl), which is authored through the registry.
  // An unchecked href here is a one-click XSS: a javascript: target would run
  // in Loom's origin, where the session tokens live. Show the value either
  // way so nothing is silently hidden, but only make it clickable if it is a
  // real https URL.
  if (!isSafeExternalUrl(url)) {
    return (
      <span className="inline-flex items-center gap-1 break-all text-muted-foreground" title="Not a valid https URL, so it is not linked">
        {url}
      </span>
    );
  }
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
      {url} <ExternalLink className="h-3 w-3 shrink-0" />
    </a>
  );
}

function downloadSkillMd(name: string, content: string) {
  const blob = new Blob([content], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name || "skill"}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------
function SkillDetail({ recordId, canWrite, onBack, onDeleted }: {
  recordId: string;
  canWrite: boolean;
  onBack: () => void;
  onDeleted: () => void;
}) {
  const { timezone } = useTimezone();
  const [detail, setDetail] = useState<RegistryRecordDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [dependents, setDependents] = useState<SkillDependent[]>([]);
  const [showSource, setShowSource] = useState(false);

  const load = useCallback(() => {
    getRegistryRecord(recordId)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load skill detail"));
    getSkillDependents(recordId).then((r) => setDependents(r.dependents)).catch(() => {});
  }, [recordId]);

  useEffect(() => { load(); }, [load]);

  const links = detail ? parseSkillLinks(detail) : {};
  const editDefaults = detail ? parseSkillEditDefaults(detail) : null;
  const skillMdBody = editDefaults ? parseSkillMd(editDefaults.skillMdBody).body : "";

  const handleUpdate = async (values: SkillEditorValues) => {
    try {
      await updateSkillRecord(recordId, {
        skill_name: values.name,
        skill_description: values.description,
        skill_license: values.license,
        skill_version: values.version,
        skill_md: values.body,
      });
      toast.success("Skill updated");
      setEditing(false);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update skill");
    }
  };

  const handleDelete = async () => {
    const dependentNames = dependents.map((d) => d.agent_name).join(", ");
    const message = dependents.length > 0
      ? `Delete skill "${detail?.name ?? recordId}"? It's currently attached to ${dependents.length} agent${dependents.length === 1 ? "" : "s"} (${dependentNames}) — they'll stop picking up its content on their next redeploy. This cannot be undone.`
      : `Delete skill "${detail?.name ?? recordId}"? This cannot be undone.`;
    if (!window.confirm(message)) return;
    setDeleting(true);
    try {
      await deleteRegistryRecord(recordId);
      toast.success("Skill deleted");
      onDeleted();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete skill");
      setDeleting(false);
    }
  };

  if (editing && detail && editDefaults) {
    return (
      <div className="space-y-4">
        <Button variant="outline" size="sm" onClick={() => setEditing(false)} className="gap-1.5">
          <ArrowLeft className="h-3 w-3" /> Back to skill
        </Button>
        <SkillEditor
          mode="edit"
          initial={editDefaults}
          dependentCount={dependents.length}
          onSubmit={handleUpdate}
          onCancel={() => setEditing(false)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <button onClick={onBack} className="hover:underline">Skills</button>
        <span>/</span>
        <span className="font-mono text-foreground">{detail?.name ?? recordId}</span>
      </div>

      {error && <div className="text-sm text-destructive">{error}</div>}
      {!detail && !error && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading skill…
        </div>
      )}

      {detail && (
        <>
          <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
            <div className="flex items-start gap-4">
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2.5">
                  <h1 className="truncate font-mono text-2xl font-semibold tracking-tight">{detail.name}</h1>
                  {editDefaults?.version && (
                    <span className="rounded-md border bg-muted px-1.5 py-0.5 font-mono text-[10px] tracking-wide text-muted-foreground">
                      v{editDefaults.version}
                    </span>
                  )}
                  <RegistryStatusBadge status={detail.status} />
                </div>
                <div className="flex items-center gap-1.5 text-[13.5px] text-muted-foreground">
                  <span>{detail.description ?? <span className="italic">No description set.</span>}</span>
                </div>
              </div>
              <div className="ml-auto flex items-center gap-2 flex-none">
                <Button size="sm" variant="outline" onClick={() => downloadSkillMd(detail.name, editDefaults?.skillMdBody ?? "")} className="gap-1.5">
                  <Download className="h-3 w-3" /> Download .md
                </Button>
                {canWrite && (
                  <Button size="sm" variant="ghost" disabled={deleting} onClick={() => void handleDelete()} className="gap-1.5 text-muted-foreground hover:text-destructive">
                    {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                  </Button>
                )}
                {canWrite && (
                  <Button size="sm" onClick={() => setEditing(true)}>Edit skill</Button>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] gap-4 items-start">
            {/* rendered doc */}
            <Card>
              <CardContent className="p-0">
                <div className="flex items-center gap-3 px-4 py-2.5 border-b">
                  <span className="font-mono text-[11px] text-muted-foreground">SKILL.md</span>
                  <div className="ml-auto flex items-center rounded-md border p-0.5 bg-muted/50">
                    <button
                      onClick={() => setShowSource(false)}
                      className={`px-2.5 py-1 rounded text-[11px] font-mono ${!showSource ? "bg-background shadow-sm" : "text-muted-foreground"}`}
                    >rendered</button>
                    <button
                      onClick={() => setShowSource(true)}
                      className={`px-2.5 py-1 rounded text-[11px] font-mono ${showSource ? "bg-background shadow-sm" : "text-muted-foreground"}`}
                    >source</button>
                  </div>
                </div>
                <div className="p-5">
                  {showSource ? (
                    <pre className="font-mono text-[11px] leading-relaxed whitespace-pre-wrap">{editDefaults?.skillMdBody}</pre>
                  ) : (
                    <SkillDocument body={skillMdBody} />
                  )}
                </div>
              </CardContent>
            </Card>

            {/* rail */}
            <div className="flex flex-col gap-3">
              <Card className="gap-2.5 py-4">
                <CardHeader className="px-[18px]">
                  <CardTitle className="text-[13px] font-semibold">Record</CardTitle>
                </CardHeader>
                <CardContent className="space-y-1 px-[18px]">
                  <MetaRow label="Record ID"><code className="text-[10px]">{detail.record_id}</code></MetaRow>
                  {editDefaults?.license && <MetaRow label="License">{editDefaults.license}</MetaRow>}
                  {editDefaults?.author && <MetaRow label="Author">{editDefaults.author}</MetaRow>}
                  {detail.created_at && <MetaRow label="Created">{formatTimestamp(detail.created_at, timezone)}</MetaRow>}
                  {detail.updated_at && <MetaRow label="Updated">{formatTimestamp(detail.updated_at, timezone)}</MetaRow>}
                  {links.repositoryUrl && <MetaRow label="Repository"><ExternalLinkRow url={links.repositoryUrl} /></MetaRow>}
                  {links.websiteUrl && <MetaRow label="Website"><ExternalLinkRow url={links.websiteUrl} /></MetaRow>}
                </CardContent>
              </Card>

              <Card className="gap-2.5 py-4">
                <CardHeader className="px-[18px]">
                  <CardTitle className="text-[13px] font-semibold">Registry</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2.5 px-[18px]">
                  {editDefaults?.version && (
                    <MetaRow label={detail.status === "APPROVED" ? "Approved version" : "Version"}>
                      <span className="font-mono">v{editDefaults.version}</span>
                    </MetaRow>
                  )}
                  {detail.status_reason && <p className="text-[12.5px] leading-[1.55] text-muted-foreground">{detail.status_reason}</p>}
                  {canWrite && (
                    <RegistryActions
                      resourceType="skill"
                      resourceId={0}
                      registryRecordId={detail.record_id}
                      registryStatus={detail.status}
                      onAction={load}
                    />
                  )}
                </CardContent>
              </Card>

              <Card className="gap-2.5 py-4">
                <CardHeader className="px-[18px]">
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-[13px] font-semibold">Used by</CardTitle>
                    <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-mono">{dependents.length}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-col gap-1.5 px-[18px]">
                  {dependents.length === 0 && <div className="text-xs text-muted-foreground">No agents currently have this skill attached.</div>}
                  {dependents.map((d) => (
                    <div key={d.agent_id} className="flex items-center gap-2 px-2.5 py-1.5 rounded-md border text-[11.5px]">
                      <div className="h-1.5 w-1.5 rounded-full bg-success shrink-0" />
                      <span className="font-mono truncate">{d.agent_name}</span>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------
interface SkillCardExtra {
  license?: string;
  author?: string;
  version?: string;
  stepCount?: number;
  dependentCount?: number;
}

interface SkillsPageProps {
  initialSelectedId?: string | null;
}

export function SkillsPage({ initialSelectedId }: SkillsPageProps) {
  const { timezone } = useTimezone();
  const { user, hasScope } = useAuth();
  const canView = hasScope("registry:read");
  const canWrite = hasScope("registry:write");
  const [registryEnabled, setRegistryEnabled] = useState<boolean | null>(null);
  const [skills, setSkills] = useState<RegistryRecord[]>([]);
  const [extras, setExtras] = useState<Record<string, SkillCardExtra>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId ?? null);
  const [creating, setCreating] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);
  const importInputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const config = await getRegistryConfig();
      setRegistryEnabled(config.enabled);
      if (!config.enabled) {
        setSkills([]);
        return;
      }
      const records = await listRegistryRecords({ descriptorType: "SKILL" });
      setSkills([...records].sort((a, b) => a.name.localeCompare(b.name)));
      setLastSyncedAt(Date.now());

      void Promise.all(records.map(async (r) => {
        try {
          const [detail, dep] = await Promise.all([getRegistryRecord(r.record_id), getSkillDependents(r.record_id)]);
          const def = detail.descriptors?.agentSkillsDefinition as { data?: string; additionalData?: { skillMd?: { data?: string } } } | undefined;
          let license: string | undefined;
          let author: string | undefined;
          let version: string | undefined;
          try {
            if (def?.data) {
              const data = JSON.parse(def.data) as { license?: string; metadata?: { author?: string; version?: string } };
              license = data.license;
              author = data.metadata?.author;
              version = data.metadata?.version;
            }
          } catch { /* leave undefined */ }
          const body = def?.additionalData?.skillMd?.data ?? "";
          setExtras((prev) => ({ ...prev, [r.record_id]: { license, author, version, stepCount: countSteps(body), dependentCount: dep.dependents.length } }));
        } catch { /* leave this card's chips absent rather than failing the whole list */ }
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load skills from the registry");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (canView) void load(); }, [load, canView]);

  const [syncedLabel, setSyncedLabel] = useState("");
  useEffect(() => {
    if (!lastSyncedAt) return;
    const tick = () => {
      const secs = Math.max(0, Math.round((Date.now() - lastSyncedAt) / 1000));
      setSyncedLabel(secs < 60 ? `${secs}s ago` : `${Math.round(secs / 60)}m ago`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [lastSyncedAt]);

  const handleCreate = async (values: SkillEditorValues) => {
    try {
      await createRegistryRecord({
        resource_type: "skill",
        skill_name: values.name,
        skill_description: values.description,
        skill_license: values.license,
        skill_version: values.version,
        skill_md: values.body,
      });
      toast.success("Skill created");
      setCreating(false);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create skill");
    }
  };

  const [importedDraft, setImportedDraft] = useState<SkillEditorValues | null>(null);

  const handleImportFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? "");
      const parsed = parseSkillMd(text);
      setCreating(true);
      setImportedDraft({
        name: parsed.frontmatter.name ?? file.name.replace(/\.md$/i, ""),
        description: parsed.frontmatter.description ?? "",
        license: parsed.frontmatter.license ?? "MIT",
        author: user?.username ?? "",
        version: parsed.frontmatter.version ?? "1.0.0",
        body: text,
      });
    };
    reader.readAsText(file);
  };

  if (!canView) {
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center gap-3 text-center">
            <AlertTriangle className="h-8 w-8 text-muted-foreground/40" aria-hidden />
            <div className="text-sm font-medium">Admin access required</div>
            <p className="max-w-md text-xs text-muted-foreground">Skills are only visible to registry administrators.</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (selectedId) {
    return (
      <SkillDetail
        recordId={selectedId}
        canWrite={canWrite}
        onBack={() => setSelectedId(null)}
        onDeleted={() => { setSelectedId(null); void load(); }}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-semibold">Skills</h2>
          <p className="text-sm text-muted-foreground">Reusable agent capabilities published to the Agent Registry.</p>
        </div>
        {canWrite && registryEnabled && !creating && (
          <div className="flex items-center gap-2">
            <input
              ref={importInputRef}
              type="file"
              accept=".md"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImportFile(f); e.target.value = ""; }}
            />
            <Button size="sm" variant="outline" onClick={() => importInputRef.current?.click()} className="gap-1.5">
              <FileUp className="h-3 w-3" /> Import SKILL.md
            </Button>
            <Button size="sm" onClick={() => { setImportedDraft(null); setCreating(true); }}>New skill</Button>
          </div>
        )}
      </div>

      {!loading && !error && registryEnabled === true && (
        <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            live from Agent Registry{syncedLabel && ` · synced ${syncedLabel}`}
          </span>
          <button onClick={() => void load()} className="text-primary hover:underline flex items-center gap-1">
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> refresh
          </button>
        </div>
      )}

      {creating && (
        <SkillEditor
          mode="create"
          initial={importedDraft ?? { name: "", description: "", license: "MIT", author: user?.username ?? "", version: "1.0.0", body: "" }}
          onSubmit={handleCreate}
          onCancel={() => { setCreating(false); setImportedDraft(null); }}
        />
      )}

      {loading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-40" />)}
        </div>
      )}
      {error && <div className="text-sm text-destructive">{error}</div>}

      {!loading && !error && registryEnabled === false && (
        <Card>
          <CardContent className="py-12">
            <div className="flex flex-col items-center gap-3 text-center">
              <Puzzle className="h-8 w-8 text-muted-foreground/40" aria-hidden />
              <div className="text-sm font-medium">Agent Registry not configured</div>
              <p className="max-w-md text-xs text-muted-foreground">Skills are served from the AWS Agent Registry. Configure a registry ARN in Settings to browse the skills published to it.</p>
            </div>
          </CardContent>
        </Card>
      )}

      {!loading && !error && registryEnabled === true && skills.length === 0 && !creating && (
        <Card>
          <CardContent className="py-12">
            <div className="flex flex-col items-center gap-3 text-center">
              <Puzzle className="h-8 w-8 text-muted-foreground/40" aria-hidden />
              <div className="text-sm font-medium">No skills in the registry</div>
              <p className="max-w-md text-xs text-muted-foreground">
                {canWrite ? "Write one here, or import an existing SKILL.md file." : "SKILL records published to the bound Agent Registry will appear here."}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {!loading && !error && skills.length > 0 && !creating && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {skills.map((s) => {
            const extra = extras[s.record_id];
            return (
              <Card
                key={s.record_id}
                role="button"
                tabIndex={0}
                aria-label={`Open skill ${s.name}`}
                onClick={() => setSelectedId(s.record_id)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedId(s.record_id); } }}
                className="group relative flex h-full cursor-pointer flex-col gap-3.5 py-4 transition-colors hover:bg-accent/50 focus-visible:ring-2 focus-visible:ring-primary outline-none"
              >
                <CardHeader className="gap-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <CardTitle className="truncate font-mono text-sm font-medium tracking-tight" title={s.name}>
                        {s.name}
                      </CardTitle>
                      {extra?.version && <span className="font-mono text-[10px] text-muted-foreground shrink-0">v{extra.version}</span>}
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <RegistryStatusBadge status={s.status} />
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col gap-3.5">
                  {s.description ? (
                    <p className="text-xs text-muted-foreground line-clamp-2">{s.description}</p>
                  ) : (
                    <div className="flex items-start gap-1.5 rounded-md border border-warning/30 bg-warning-bg px-2 py-1.5">
                      <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5 text-warning" />
                      <span className="text-[11px] leading-snug text-warning">Description missing — agents use it to decide when to apply this skill.</span>
                    </div>
                  )}

                  <div className="flex flex-wrap gap-1.5">
                    {extra?.stepCount ? <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-muted border text-muted-foreground">{extra.stepCount} steps</span> : null}
                    {extra?.license && <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-muted border text-muted-foreground">{extra.license}</span>}
                    {extra?.author && <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-muted border text-muted-foreground truncate max-w-[140px]">{extra.author}</span>}
                  </div>

                  <div className="mt-auto flex items-center gap-2 border-t pt-3 text-[11px] text-muted-foreground">
                    {s.updated_at && <span>updated {formatTimestamp(s.updated_at, timezone).split(",")[0]}</span>}
                    {typeof extra?.dependentCount === "number" && (
                      <>
                        <span className="h-2.5 w-px bg-border" />
                        <span>{extra.dependentCount === 0 ? "unused" : `${extra.dependentCount} agent${extra.dependentCount === 1 ? "" : "s"}`}</span>
                      </>
                    )}
                    <span className="ml-auto text-primary">Details</span>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {!loading && skills.length > 0 && !creating && (
        <p className="text-[11px] text-muted-foreground">Served live from the bound Agent Registry ({skills.length} SKILL record{skills.length === 1 ? "" : "s"}).</p>
      )}
    </div>
  );
}
